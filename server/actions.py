# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Pepon's action layer — the boundary between "what Pepon decided to
do" and "how that gets carried out".

Agent/world logic builds Action objects (plain structured data) and
hands them to an ActionExecutor without knowing anything about phones,
WebSockets, or, later, servos. Today there's exactly one executor
(PhoneExecutor, rendering on the phone over the existing WebSocket);
a future ESP32Executor or ServoExecutor would implement the same
interface and nothing upstream — not the actions, not the code that
produces them — would need to change.

Deliberately small: one Action shape, one executor interface, no
routing/registry/plugin machinery.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional


class ActionType(str, Enum):
    LOOK_AT = "LOOK_AT"
    SPEAK = "SPEAK"
    LISTEN = "LISTEN"
    SEARCH_OBJECT = "SEARCH_OBJECT"
    SET_EXPRESSION = "SET_EXPRESSION"
    ALERT = "ALERT"


@dataclass
class Action:
    type: ActionType
    params: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Flat structured form, e.g. {"type": "LOOK_AT", "x": 0.61, ...} —
        matches what comes in over POST /api/action and what a body-side
        executor needs to render."""
        return {"type": self.type.value, **self.params}


# ---- convenience constructors: what Agent/World code actually calls ----

def look_at(x: float, y: float, target: Optional[str] = None) -> Action:
    params: Dict[str, Any] = {"x": round(x, 3), "y": round(y, 3)}
    if target is not None:
        params["target"] = target
    return Action(ActionType.LOOK_AT, params)


def speak(text: str) -> Action:
    return Action(ActionType.SPEAK, {"text": text})


def listen() -> Action:
    return Action(ActionType.LISTEN, {})


def search_object(target: str) -> Action:
    return Action(ActionType.SEARCH_OBJECT, {"target": target})


def set_expression(state: str) -> Action:
    return Action(ActionType.SET_EXPRESSION, {"state": state.upper()})


def alert(reason: str) -> Action:
    return Action(ActionType.ALERT, {"reason": reason})


class ActionExecutor:
    """Anything capable of carrying out an Action on Pepon's body."""

    async def execute(self, action: Action) -> None:
        raise NotImplementedError


class PhoneExecutor(ActionExecutor):
    """Current executor: renders actions on the phone (eyes/speech) over
    the existing WebSocket link.

    `send` is anything that broadcasts a JSON-able dict to connected
    phones — main.py's `broadcast()` today. Injected rather than
    imported so this module has zero FastAPI/WebSocket dependency.
    """

    def __init__(self, send: Callable[[dict], Awaitable[None]]):
        self._send = send

    async def execute(self, action: Action) -> None:
        if action.type == ActionType.LOOK_AT:
            await self._send({
                "type": "look_at",
                "x": action.params["x"],
                "y": action.params["y"],
            })
        elif action.type == ActionType.SPEAK:
            await self._send({"type": "speak", "text": action.params["text"]})
        elif action.type == ActionType.LISTEN:
            # No dedicated phone rendering for "start listening" beyond the
            # existing LISTENING expression — reuse it.
            await self._send({"type": "state", "value": "LISTENING"})
        elif action.type == ActionType.SEARCH_OBJECT:
            # Same idea: "searching" already has a face expression for it.
            await self._send({"type": "state", "value": "SEARCHING"})
        elif action.type == ActionType.SET_EXPRESSION:
            await self._send({"type": "state", "value": action.params["state"]})
        elif action.type == ActionType.ALERT:
            await self._send({"type": "alert", "reason": action.params.get("reason")})
