"""Pepon's short-term memory of what it currently perceives.

This is NOT a database or a knowledge graph — just enough recent state
(what's visible right now, where it was last seen, Pepon's own state)
to answer something like "where's the bottle?" without re-querying the
camera. Perception/tracking/proprioception write into it; the future
voice Agent reads from it.
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

POSITION_LEFT = "LEFT"
POSITION_CENTER = "CENTER"
POSITION_RIGHT = "RIGHT"
CENTER_BAND = 0.25  # |x| below this counts as CENTER, matching lookAt's -1..1 convention

FORGET_AFTER_SECONDS = 120.0  # drop an object's memory once it's this stale


def position_from_x(x: float) -> str:
    if x < -CENTER_BAND:
        return POSITION_LEFT
    if x > CENTER_BAND:
        return POSITION_RIGHT
    return POSITION_CENTER


@dataclass
class ObjectMemory:
    cls: str
    visible: bool = False
    confidence: float = 0.0
    x: float = 0.0
    y: float = 0.0
    position: str = POSITION_CENTER
    last_seen_at: Optional[float] = None

    def seconds_since_seen(self) -> Optional[float]:
        return None if self.last_seen_at is None else time.time() - self.last_seen_at

    def as_dict(self) -> dict:
        seconds = self.seconds_since_seen()
        return {
            "visible": self.visible,
            "confidence": round(self.confidence, 2),
            "position": self.position,
            "seconds_since_seen": round(seconds, 1) if seconds is not None else None,
        }


class WorldState:
    """Small, inspectable snapshot of Pepon's short-term situation."""

    def __init__(self):
        self.objects: Dict[str, ObjectMemory] = {}
        self.active_target: Optional[str] = None
        self.pepon_state: str = "IDLE"
        self.phone_motion_phase: str = "STABLE"
        self.last_motion_event: Optional[str] = None
        self.last_motion_event_at: Optional[float] = None

    # ---- updates from Perception ----

    def update_detections(self, detections: List[dict]) -> None:
        """Call once per detection cycle with that frame's detections."""
        seen_this_cycle = set()
        for det in detections:
            cls = det["class"]
            seen_this_cycle.add(cls)
            memory = self.objects.setdefault(cls, ObjectMemory(cls=cls))
            memory.visible = True
            memory.confidence = det["confidence"]
            memory.x = det["x"]
            memory.y = det["y"]
            memory.position = position_from_x(det["x"])
            memory.last_seen_at = time.time()

        for cls, memory in self.objects.items():
            if cls not in seen_this_cycle:
                memory.visible = False

        self._forget_stale()

    def _forget_stale(self) -> None:
        cutoff = time.time() - FORGET_AFTER_SECONDS
        stale = [
            cls for cls, m in self.objects.items()
            if not m.visible and (m.last_seen_at or 0) < cutoff
        ]
        for cls in stale:
            del self.objects[cls]

    # ---- updates from Proprioception ----

    def set_phone_motion(self, phase: str, event: Optional[str] = None) -> None:
        self.phone_motion_phase = phase
        if event is not None:
            self.last_motion_event = event
            self.last_motion_event_at = time.time()

    # ---- updates from Action / the state machine ----

    def set_pepon_state(self, state: str) -> None:
        self.pepon_state = state

    def set_active_target(self, cls: Optional[str]) -> None:
        self.active_target = cls

    # ---- reads ----

    @property
    def person_visible(self) -> bool:
        person = self.objects.get("person")
        return bool(person and person.visible)

    def get_object(self, cls: str) -> Optional[ObjectMemory]:
        return self.objects.get(cls)

    def describe(self, cls: str) -> str:
        """Plain-language answer to "where is the <cls>?" — simple enough
        for the voice Agent to speak directly, no LLM needed."""
        memory = self.objects.get(cls)
        if memory is None:
            return f"I haven't seen a {cls} yet."
        side = memory.position.lower()
        if memory.visible:
            return f"I can see the {cls} right now, on my {side}."
        seconds = memory.seconds_since_seen()
        return f"I last saw the {cls} {round(seconds)}s ago, on my {side}."

    def as_dict(self) -> dict:
        return {
            "objects": {cls: m.as_dict() for cls, m in self.objects.items()},
            "active_target": self.active_target,
            "person_visible": self.person_visible,
            "pepon_state": self.pepon_state,
            "phone_motion_phase": self.phone_motion_phase,
            "last_motion_event": self.last_motion_event,
        }
