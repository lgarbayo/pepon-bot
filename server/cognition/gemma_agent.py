"""GemmaAgent — Pepon's semantic reasoning/planning layer.

Sits between intent.py's deterministic parser and the existing
Agent/ActionExecutor: when a voice command doesn't match one of
intent.py's patterns, GemmaAgent.decide() asks a small local Gemma
model (via Ollama's HTTP API) to pick ONE high-level action from a
fixed vocabulary, grounded only in a compact WorldState snapshot.

GemmaAgent never computes coordinates, never talks to the phone, and
never touches actions.py directly — its output is a validated
GemmaDecision that agent.Agent.handle_semantic() maps onto the exact
same resolution/execution code deterministic intents already use.

Deliberately NOT in any real-time loop (camera/detection/tracking) —
called at most once per voice command, off the hot path.

decide() optionally also takes the current camera frame (gemma3 is
multimodal). This is the one deliberate exception to "no raw images":
it only ever happens on this same once-per-command path, letting Gemma
reason about things outside YOLO's 80-class vocabulary (e.g. "the red
mug") — but it still can't hand back coordinates for an object
WorldState never tracked, so LOOK_AT/SEARCH_OBJECT/ANSWER_LOCATION
still require a target from visible_objects/memory; an image-only
object can only be described via SPEAK/DESCRIBE_SCENE.
"""
import base64
import json
import time
from typing import Optional, Tuple

import httpx
from pydantic import BaseModel, ValidationError

import config
from world_state import WorldState

# The only actions Gemma is allowed to choose. LOOK_AT/SEARCH_OBJECT map
# straight onto actions.ActionType; DESCRIBE_SCENE/ANSWER_LOCATION don't
# need their own ActionType since Agent already turns them into a SPEAK
# action deterministically (see Agent._what_do_you_see / _where_is).
SEMANTIC_ACTIONS = ("LOOK_AT", "SEARCH_OBJECT", "DESCRIBE_SCENE", "ANSWER_LOCATION", "SPEAK", "IDLE")
_ACTIONS_NEEDING_TARGET = {"LOOK_AT", "SEARCH_OBJECT", "ANSWER_LOCATION"}

SYSTEM_PROMPT = """You are the semantic reasoning module of Pepon, a small desktop robot.
Given a spoken instruction and Pepon's current WorldState, choose exactly ONE action.

Rules:
- Output JSON only. No prose, no markdown, no code, no explanation of your reasoning.
- Choose "action" from EXACTLY these values: LOOK_AT, SEARCH_OBJECT, DESCRIBE_SCENE, ANSWER_LOCATION, SPEAK, IDLE.
- Never invent an object that is not listed in visible_objects or memory. If nothing fits, use IDLE or SPEAK.
- Prefer visible_objects (currently seen) over memory (last seen N seconds ago) when both could answer.
- If you use memory, "text" must clearly describe a PAST observation ("last saw it..."), never claim it is currently there.
- LOOK_AT, SEARCH_OBJECT and ANSWER_LOCATION require "target" to be one of the object classes given to you in visible_objects/memory — never a word you only saw in an attached image.
- An attached image, if present, is what Pepon's camera currently sees — use it to understand the scene better and disambiguate the instruction. If it shows something useful that ISN'T in visible_objects/memory, you cannot LOOK_AT/SEARCH_OBJECT/ANSWER_LOCATION it (no known position) — use SPEAK to describe it instead.
- Keep "text" short (one sentence), in Spanish, and only set it for SPEAK or a brief remark alongside LOOK_AT/SEARCH_OBJECT.
- Never output sensor data, coordinates, or code."""

# Kept intentionally short — a second full explanation would cost latency
# for little gain; this just nudges the model back toward valid JSON.
CORRECTIVE_SUFFIX = (
    '\n\nYour previous answer was invalid. Reply again with ONLY a JSON object '
    'shaped like {"action": "...", "target": null, "text": null}, using an '
    "allowed action and, if a target is needed, an object from visible_objects/memory."
)


class GemmaDecision(BaseModel):
    action: str
    target: Optional[str] = None
    text: Optional[str] = None


_RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(SEMANTIC_ACTIONS)},
        "target": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
    },
    "required": ["action"],
}


def _compact_world_state(world_state: WorldState) -> dict:
    """Reshape WorldState into exactly the fields Gemma needs — no raw
    images, no detection history, no internal bookkeeping."""
    visible = []
    memory = {}
    for cls, mem in world_state.objects.items():
        if mem.visible:
            visible.append({
                "class": cls,
                "position": mem.position.lower(),
                "confidence": round(mem.confidence, 2),
            })
        else:
            seconds = mem.seconds_since_seen()
            memory[cls] = {
                "visible": False,
                "last_position": mem.position.lower(),
                "last_seen_seconds_ago": round(seconds) if seconds is not None else None,
            }

    # Only phone-motion phase is available (no absolute gyroscope reading),
    # so this is a coarse heuristic, not a real orientation estimate.
    movement = "moving" if world_state.phone_motion_phase in ("SHAKEN", "PICKED_UP") else "stable"
    orientation = "tilted" if world_state.phone_motion_phase == "TILTED" else "upright"

    return {
        "visible_objects": visible,
        "memory": memory,
        "body_state": {"orientation": orientation, "movement": movement},
    }


def _known_objects(world_state_compact: dict) -> set:
    known = {o["class"] for o in world_state_compact["visible_objects"]}
    known.update(world_state_compact["memory"].keys())
    return known


class GemmaAgent:
    """Talks to a local Ollama server over its HTTP API. Disabled or
    unreachable -> every public method degrades to a safe fallback
    instead of raising, so the rest of Pepon never depends on Gemma
    being up."""

    def __init__(
        self,
        base_url: str = config.OLLAMA_BASE_URL,
        model: str = config.OLLAMA_MODEL,
        timeout: float = config.GEMMA_TIMEOUT_SECONDS,
        enabled: bool = config.GEMMA_ENABLED,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enabled = enabled
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def decide(
        self, instruction: str, world_state: WorldState, frame_jpeg: Optional[bytes] = None
    ) -> GemmaDecision:
        """Never raises. Returns a validated GemmaDecision, falling back
        to a safe SPEAK on any failure (Ollama down, malformed output
        twice in a row, disallowed action/object, ...).

        frame_jpeg is optional and only meant for this one-off semantic
        call — never pass a live/streaming frame source here, and never
        call decide() from a per-frame loop."""
        if not self.enabled:
            return GemmaDecision(action="IDLE")

        compact = _compact_world_state(world_state)
        known = _known_objects(compact)
        user_payload = json.dumps({"instruction": instruction, "world_state": compact}, ensure_ascii=False)
        image_b64 = base64.b64encode(frame_jpeg).decode("ascii") if frame_jpeg else None

        start = time.monotonic()
        decision, error = await self._ask(user_payload, known, image_b64)
        if decision is None:
            decision, error = await self._ask(user_payload + CORRECTIVE_SUFFIX, known, image_b64)
        latency_ms = round((time.monotonic() - start) * 1000)

        print(f'[GEMMA] instruction="{instruction}"')
        if config.GEMMA_DEBUG:
            print(f"[GEMMA] world_state={compact}")
        print(f"[GEMMA] latency={latency_ms}ms")
        if decision is None:
            print(f"[GEMMA] validation=FAILED ({error}) -> fallback")
            return GemmaDecision(action="SPEAK", text="No he entendido bien eso.")
        print(f"[GEMMA] action={decision.action} target={decision.target} validation=OK")
        return decision

    async def _ask(
        self, user_content: str, known_objects: set, image_b64: Optional[str] = None
    ) -> Tuple[Optional[GemmaDecision], Optional[str]]:
        user_message = {"role": "user", "content": user_content}
        if image_b64:
            user_message["images"] = [image_b64]
        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        user_message,
                    ],
                    "format": _RESPONSE_JSON_SCHEMA,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return None, f"ollama request failed: {exc}"

        return self._parse_and_validate(response, known_objects)

    @staticmethod
    def _parse_and_validate(response: httpx.Response, known_objects: set) -> Tuple[Optional[GemmaDecision], Optional[str]]:
        try:
            raw = response.json()["message"]["content"]
            decision = GemmaDecision.model_validate_json(raw)
        except (KeyError, ValueError, ValidationError) as exc:
            return None, f"invalid model output: {exc}"

        if decision.action not in SEMANTIC_ACTIONS:
            return None, f"disallowed action {decision.action!r}"
        if decision.action in _ACTIONS_NEEDING_TARGET:
            if not decision.target or decision.target not in known_objects:
                return None, f"target {decision.target!r} not in known objects"

        return decision, None

    async def health(self) -> str:
        """For the /api/health endpoint — never raises."""
        if not self.enabled:
            return "disabled"
        try:
            response = await self._client.get("/api/tags", timeout=2.0)
            response.raise_for_status()
        except httpx.HTTPError:
            return "unavailable"
        return "ok"

    async def aclose(self) -> None:
        await self._client.aclose()
