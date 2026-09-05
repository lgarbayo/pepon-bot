"""Maps a parsed Intent to Action(s), using WorldState for context.

Small and rule-based on purpose, mirroring intent.py: swap the intent
parser for an LLM later and this still works unchanged, since it only
ever depends on the {"intent": ..., ...} shape coming out of parse().

Also the only place that decides what counts as one EpisodeRecorder
episode: one voice command in, until its result is known. Most
intents resolve synchronously within handle(); FIND_OBJECT can stay
open across several detection cycles (or time out) if the object
isn't visible yet — see check_active_target().
"""
import asyncio
from typing import Callable, Optional

import actions
from cognition.gemma_agent import GemmaDecision
from intent import (
    INTENT_FIND_OBJECT,
    INTENT_LOOK_AT_ME,
    INTENT_WHAT_DO_YOU_SEE,
    INTENT_WHERE_IS,
)
from recorder import EpisodeRecorder
from world_state import ObjectMemory, WorldState, object_es, position_es_phrase

FIND_TIMEOUT_SECONDS = 10.0  # short enough that "I can't see it" still feels live, not stuck


class Agent:
    def __init__(
        self,
        world_state: WorldState,
        action_executor: actions.ActionExecutor,
        recorder: Optional[EpisodeRecorder] = None,
        frame_provider: Optional[Callable[[], Optional[bytes]]] = None,
    ):
        self.world_state = world_state
        self.action_executor = action_executor
        self.recorder = recorder
        self.frame_provider = frame_provider

    async def handle(self, intent: dict, transcript: str = "") -> None:
        episode_id = None
        if self.recorder:
            episode_id = self.recorder.start_episode(transcript, intent)
            # One snapshot of what Pepon currently knows, taken when the
            # command came in — not a running log of every detection cycle.
            self.recorder.record_observation(episode_id, "world_state", self.world_state.as_dict())

        kind = intent.get("intent")
        if kind == INTENT_WHAT_DO_YOU_SEE:
            await self._what_do_you_see(episode_id)
            self._end(episode_id, "success")
        elif kind == INTENT_FIND_OBJECT:
            await self._find_object(intent["object"], episode_id)
            # Left open on purpose when the object isn't visible yet —
            # check_active_target() or _timeout_search() closes it later.
        elif kind == INTENT_WHERE_IS:
            await self._where_is(intent["object"], episode_id)
            self._end(episode_id, "success")
        elif kind == INTENT_LOOK_AT_ME:
            found_person = await self._look_at_me(episode_id)
            self._end(episode_id, "success" if found_person else "failure",
                       None if found_person else "person not visible")
        else:
            await self._unknown(episode_id)
            self._end(episode_id, "failure", "unrecognized command")

    async def handle_semantic(self, decision: GemmaDecision, transcript: str = "") -> None:
        """Executes a validated GemmaAgent decision, reusing the exact
        same resolution/execution/recording paths as a deterministic
        intent — Gemma never computes coordinates or touches actions.py
        directly, it only chose which of these to run.

        LOOK_AT and SEARCH_OBJECT both go through _find_object(): if the
        target is already visible it looks at it (and speaks) right
        away; if not, it starts the same SEARCHING flow deterministic
        FIND_OBJECT uses, which stays open until check_active_target()
        or _timeout_search() resolves it — so this method deliberately
        does NOT end the episode in that case.
        """
        episode_id = None
        if self.recorder:
            episode_id = self.recorder.start_episode(
                transcript, {"intent": "SEMANTIC", "gemma_action": decision.action, "target": decision.target}
            )
            self.recorder.record_observation(episode_id, "world_state", self.world_state.as_dict())
            self.recorder.record_observation(episode_id, "gemma_decision", decision.model_dump())

        if decision.action in ("LOOK_AT", "SEARCH_OBJECT") and decision.target:
            await self._find_object(decision.target, episode_id)
            return  # _find_object leaves the episode open when it has to search

        if decision.action == "ANSWER_LOCATION" and decision.target:
            await self._where_is(decision.target, episode_id)
        elif decision.action == "DESCRIBE_SCENE":
            await self._what_do_you_see(episode_id)
        elif decision.action == "SPEAK":
            # Gemma is asked to always set text for SPEAK, but if it
            # didn't, silently doing nothing would leave the person who
            # just spoke to Pepon with zero feedback at all — worse than
            # a generic reply.
            await self._act(actions.speak(decision.text or "No sé qué decir a eso."), episode_id)
        # IDLE (or a target-needing action GemmaAgent already validated
        # away) intentionally does nothing further — episode still ends
        # below so it isn't left open forever.

        self._end(episode_id, "success")

    async def check_active_target(self) -> None:
        """Called once per detection cycle (from the perception loop): if
        we're actively searching for something and it just became
        visible, announce it. Lets FIND_OBJECT resolve asynchronously
        instead of blocking the voice command on "is it visible yet"."""
        target = self.world_state.active_target
        if target is None:
            return
        memory = self.world_state.get_object(target)
        if memory and memory.visible:
            episode_id = self.world_state.active_target_episode_id
            await self._announce_found(target, memory, episode_id)
            self._end(episode_id, "success")

    # ---- intent handlers ----

    async def _what_do_you_see(self, episode_id: Optional[str]) -> None:
        visible = [cls for cls, m in self.world_state.objects.items() if m.visible]
        if visible:
            names = ", ".join(object_es(cls) for cls in visible)
            text = f"Veo {names}."
        else:
            text = "Ahora mismo no veo nada."
        await self._act(actions.speak(text), episode_id)

    async def _find_object(self, obj: str, episode_id: Optional[str]) -> None:
        memory = self.world_state.get_object(obj)
        if memory and memory.visible:
            await self._announce_found(obj, memory, episode_id)
            self._end(episode_id, "success")
            return

        # Superseding a still-pending search for something else — close
        # that episode out rather than leaving it open forever.
        prev_target = self.world_state.active_target
        prev_episode_id = self.world_state.active_target_episode_id
        if prev_target and prev_target != obj and prev_episode_id:
            self._end(prev_episode_id, "superseded", f"new search for {obj} started first")

        self.world_state.set_active_target(obj, episode_id)
        self.world_state.set_pepon_state("SEARCHING")  # bookkeeping only —
        # actions.search_object() below already renders the SEARCHING
        # expression on the phone, so don't also go through
        # _set_expression() or the phone gets the same state twice.
        await self._act(actions.search_object(obj), episode_id)
        await self._act(actions.speak(f"Buscando {object_es(obj)}."), episode_id)
        if episode_id:
            asyncio.create_task(self._timeout_search(obj, episode_id))

    async def _where_is(self, obj: str, episode_id: Optional[str]) -> None:
        await self._act(actions.speak(self.world_state.describe(obj)), episode_id)

    async def _look_at_me(self, episode_id: Optional[str]) -> bool:
        person = self.world_state.get_object("person")
        if person and person.visible:
            await self._act(actions.look_at(person.x, person.y, target="person"), episode_id)
            return True
        await self._act(actions.speak("Ahora mismo no te veo."), episode_id)
        return False

    async def _unknown(self, episode_id: Optional[str]) -> None:
        await self._set_expression("CONFUSED", episode_id)
        await self._act(actions.speak("Perdona, no te he entendido."), episode_id)

    # ---- shared helpers ----

    async def _timeout_search(self, obj: str, episode_id: str) -> None:
        await asyncio.sleep(FIND_TIMEOUT_SECONDS)
        if self.world_state.active_target != obj:
            return  # already resolved (found) or superseded by a newer command
        self.world_state.set_active_target(None)
        await self._set_expression("IDLE", episode_id)
        await self._act(actions.speak(f"No veo {object_es(obj)}."), episode_id)
        self._end(episode_id, "timeout", f"gave up looking for {obj} after {int(FIND_TIMEOUT_SECONDS)}s")

    async def _announce_found(self, obj: str, memory: ObjectMemory, episode_id: Optional[str]) -> None:
        # SET_EXPRESSION before LOOK_AT: on the phone, a state change resets
        # gaze to that state's default (Pepon.setState() clears manualGaze),
        # so sending LOOK_AT second is what makes the eyes actually end up
        # on the object instead of snapping back to center right after.
        await self._set_expression("FOUND", episode_id)
        await self._act(actions.look_at(memory.x, memory.y, target=obj), episode_id)
        if self.recorder and episode_id:
            frame = self.frame_provider() if self.frame_provider else None
            self.recorder.record_observation(
                episode_id, "found",
                {"object": obj, "x": memory.x, "y": memory.y, "position": memory.position},
                frame_jpeg=frame,
            )
        await self._act(
            actions.speak(f"Encontré {object_es(obj)}, {position_es_phrase(memory.position)}."),
            episode_id,
        )
        self.world_state.set_active_target(None)

    async def _set_expression(self, state: str, episode_id: Optional[str] = None) -> None:
        """Renders SET_EXPRESSION *and* keeps world_state.pepon_state in
        sync — mirrors main.py's _set_pepon_state, kept local here to
        avoid an agent.py <-> main.py import cycle."""
        self.world_state.set_pepon_state(state)
        await self._act(actions.set_expression(state), episode_id)

    async def _act(self, action: actions.Action, episode_id: Optional[str]) -> None:
        await self.action_executor.execute(action)
        if self.recorder and episode_id:
            self.recorder.record_action(episode_id, action.type.value, action.params)

    def _end(self, episode_id: Optional[str], status: str, detail: Optional[str] = None) -> None:
        if self.recorder and episode_id:
            self.recorder.end_episode(episode_id, status, detail)
