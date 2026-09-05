"""Essential tests for GemmaAgent's response parsing/validation and
failure behavior — not testing Ollama itself, just that malformed or
disallowed model output never reaches Agent unvalidated, and that a
dead/disabled Ollama degrades gracefully instead of raising.

No pytest-asyncio dependency: async cases just wrap asyncio.run().
"""
import asyncio
import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cognition.gemma_agent import GemmaAgent, GemmaDecision, _compact_world_state, _known_objects
from world_state import WorldState


def _world_with_bottle() -> WorldState:
    ws = WorldState()
    ws.update_detections([{"class": "bottle", "confidence": 0.91, "x": 0.6, "y": 0.0}])
    return ws


def _chat_response(content: str) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    return httpx.Response(200, json={"message": {"content": content}}, request=request)


def test_compact_world_state_separates_visible_from_memory():
    ws = _world_with_bottle()
    compact = _compact_world_state(ws)
    assert compact["visible_objects"] == [{"class": "bottle", "position": "right", "confidence": 0.91}]
    assert compact["memory"] == {}
    assert _known_objects(compact) == {"bottle"}


def test_valid_decision_is_accepted():
    async def run():
        agent = GemmaAgent(enabled=True)
        good = _chat_response('{"action": "LOOK_AT", "target": "bottle", "text": null}')
        with patch.object(agent._client, "post", AsyncMock(return_value=good)):
            decision = await agent.decide("look at the bottle", _world_with_bottle())
        await agent.aclose()
        return decision

    decision = asyncio.run(run())
    assert decision == GemmaDecision(action="LOOK_AT", target="bottle", text=None)


def test_frame_jpeg_is_sent_as_base64_image():
    """decide(frame_jpeg=...) should attach the frame as base64 on the
    user message (multimodal), and omit "images" entirely when no frame
    is given (existing text-only behavior)."""
    async def run():
        agent = GemmaAgent(enabled=True)
        good = _chat_response('{"action": "LOOK_AT", "target": "bottle", "text": null}')
        mock_post = AsyncMock(return_value=good)
        with patch.object(agent._client, "post", mock_post):
            await agent.decide("look at the bottle", _world_with_bottle(), frame_jpeg=b"\xff\xd8fake-jpeg")
        await agent.aclose()
        return mock_post.call_args.kwargs["json"]["messages"][1]

    user_message = asyncio.run(run())
    assert user_message["images"] == [base64.b64encode(b"\xff\xd8fake-jpeg").decode("ascii")]


def test_no_frame_means_no_images_key():
    async def run():
        agent = GemmaAgent(enabled=True)
        good = _chat_response('{"action": "LOOK_AT", "target": "bottle", "text": null}')
        mock_post = AsyncMock(return_value=good)
        with patch.object(agent._client, "post", mock_post):
            await agent.decide("look at the bottle", _world_with_bottle())
        await agent.aclose()
        return mock_post.call_args.kwargs["json"]["messages"][1]

    user_message = asyncio.run(run())
    assert "images" not in user_message


def test_invented_object_is_rejected_and_falls_back():
    """Gemma naming an object nobody detected must never reach Agent —
    both attempts return an object outside visible_objects/memory."""
    async def run():
        agent = GemmaAgent(enabled=True)
        hallucinated = _chat_response('{"action": "LOOK_AT", "target": "unicorn", "text": null}')
        with patch.object(agent._client, "post", AsyncMock(return_value=hallucinated)):
            decision = await agent.decide("look at the unicorn", _world_with_bottle())
        await agent.aclose()
        return decision

    decision = asyncio.run(run())
    assert decision.action == "SPEAK"
    assert decision.target is None


def test_malformed_json_retries_once_then_falls_back():
    async def run():
        agent = GemmaAgent(enabled=True)
        garbage = _chat_response("not json at all")
        mock_post = AsyncMock(return_value=garbage)
        with patch.object(agent._client, "post", mock_post):
            decision = await agent.decide("do something", _world_with_bottle())
        await agent.aclose()
        return decision, mock_post.call_count

    decision, call_count = asyncio.run(run())
    assert call_count == 2  # one retry, per spec
    assert decision.action == "SPEAK"


def test_disallowed_action_name_is_rejected():
    async def run():
        agent = GemmaAgent(enabled=True)
        invented_action = _chat_response('{"action": "EXECUTE_SHELL", "target": null, "text": null}')
        with patch.object(agent._client, "post", AsyncMock(return_value=invented_action)):
            decision = await agent.decide("do something", _world_with_bottle())
        await agent.aclose()
        return decision

    decision = asyncio.run(run())
    assert decision.action == "SPEAK"


def test_ollama_unreachable_degrades_gracefully():
    async def run():
        agent = GemmaAgent(base_url="http://localhost:1", timeout=1.0, enabled=True)
        decision = await agent.decide("look at the bottle", _world_with_bottle())
        health = await agent.health()
        await agent.aclose()
        return decision, health

    decision, health = asyncio.run(run())
    assert decision.action == "SPEAK"
    assert health == "unavailable"


def test_disabled_agent_never_calls_ollama():
    async def run():
        agent = GemmaAgent(enabled=False)
        with patch.object(agent._client, "post", AsyncMock()) as mock_post:
            decision = await agent.decide("anything", _world_with_bottle())
        health = await agent.health()
        await agent.aclose()
        return decision, health, mock_post.called

    decision, health, called = asyncio.run(run())
    assert decision == GemmaDecision(action="IDLE")
    assert health == "disabled"
    assert called is False


if __name__ == "__main__":
    import inspect
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{failures} test(s) failed")
    print("All tests passed.")
