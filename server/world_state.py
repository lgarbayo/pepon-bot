# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Pepon's short-term memory of what it currently perceives.

This is NOT a database or a knowledge graph — just enough recent state
(what's visible right now, where it was last seen, Pepon's own state)
to answer something like "where's the bottle?" without re-querying the
camera. Perception/tracking/proprioception write into it; the future
voice Agent reads from it.
"""
import time
from collections import deque
from dataclasses import asdict, dataclass

from vocabulary import OBJECT_ES

POSITION_LEFT = "LEFT"
POSITION_CENTER = "CENTER"
POSITION_RIGHT = "RIGHT"
CENTER_BAND = 0.25  # |x| below this counts as CENTER, matching lookAt's -1..1 convention

FORGET_AFTER_SECONDS = 86400.0  # drop an object's memory once it's this stale

# Spoken-Spanish vocabulary for describe()/Agent — internal keys (object
# class, position) stay in English/COCO form throughout the rest of the
# system; this is purely for composing what Pepon says out loud.
POSITION_ES_PHRASE = {
    POSITION_LEFT: "a mi izquierda",
    POSITION_RIGHT: "a mi derecha",
    POSITION_CENTER: "en el centro",
}


def object_es(cls: str) -> str:
    return OBJECT_ES.get(cls, cls)


def position_es_phrase(position: str) -> str:
    return POSITION_ES_PHRASE.get(position, "")


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
    last_seen_at: float | None = None
    # Set once this class has survived the same stability check as
    # stable_scene/changes (see _update_scene): a handful of consecutive
    # frames over >=1s. A single stray YOLO frame (e.g. a misdetected
    # "vase") sits here as unconfirmed and is kept out of what GemmaAgent
    # is told about, instead of instantly becoming a fact it can cite for
    # up to FORGET_AFTER_SECONDS.
    confirmed: bool = False

    def seconds_since_seen(self) -> float | None:
        return None if self.last_seen_at is None else time.time() - self.last_seen_at

    def as_dict(self) -> dict:
        seconds = self.seconds_since_seen()
        return {
            "visible": self.visible,
            "confidence": round(self.confidence, 2),
            "position": self.position,
            "seconds_since_seen": round(seconds, 1) if seconds is not None else None,
            "confirmed": self.confirmed,
        }


class WorldState:
    """Small, inspectable snapshot of Pepon's short-term situation."""

    def __init__(self):
        self.objects: dict[str, ObjectMemory] = {}
        self.last_detection_at = None
        self.camera_view = 'user'
        self.camera_revision = 0
        self.stable_scene = {}
        self._candidates = {}
        self.changes = deque(maxlen=80)
        self.scene_ready = False
        self._scene_started = None
        self.active_target: str | None = None
        self.active_target_episode_id: str | None = None
        self.pepon_state: str = "IDLE"
        self.phone_motion_phase: str = "STABLE"
        self.last_motion_event: str | None = None
        self.last_motion_event_at: float | None = None

    # ---- updates from Perception ----

    def update_detections(self, detections: list[dict]) -> None:
        """Call once per detection cycle with that frame's detections."""
        now = time.time()
        self.last_detection_at = now
        seen_this_cycle = set()
        # Keep the highest-confidence instance for class-level memory.
        detections = sorted(detections, key=lambda d: d['confidence'])
        for det in detections:
            cls = det["class"]
            seen_this_cycle.add(cls)
            memory = self.objects.setdefault(cls, ObjectMemory(cls=cls))
            memory.visible = True
            memory.confidence = det["confidence"]
            memory.x = det["x"]
            memory.y = det["y"]
            memory.position = position_from_x(det["x"])
            memory.last_seen_at = now

        for cls, memory in self.objects.items():
            if cls not in seen_this_cycle:
                memory.visible = False

        self._forget_stale()
        self._update_scene(now)

    def _forget_stale(self) -> None:
        cutoff = time.time() - FORGET_AFTER_SECONDS
        stale = [
            cls for cls, m in self.objects.items()
            if not m.visible and (m.last_seen_at or 0) < cutoff
        ]
        for cls in stale:
            del self.objects[cls]

    # ---- updates from Proprioception ----

    def set_phone_motion(self, phase: str, event: str | None = None) -> None:
        self.phone_motion_phase = phase
        if event is not None:
            self.last_motion_event = event
            self.last_motion_event_at = time.time()

    # ---- updates from Action / the state machine ----

    def set_pepon_state(self, state: str) -> None:
        self.pepon_state = state

    def set_active_target(self, cls: str | None, episode_id: str | None = None) -> None:
        self.active_target = cls
        self.active_target_episode_id = episode_id if cls is not None else None

    # ---- reads ----

    @property
    def person_visible(self) -> bool:
        person = self.objects.get("person")
        return bool(person and person.visible)

    def get_object(self, cls: str) -> ObjectMemory | None:
        return self.objects.get(cls)

    def describe(self, cls: str) -> str:
        """Plain-language (Spanish) answer to "¿dónde está X?" — simple
        enough for the voice Agent to speak directly, no LLM needed."""
        name = object_es(cls)
        self.expire_camera()
        memory = self.objects.get(cls)
        if memory is None:
            return f"Todavía no he visto {name}."
        side = position_es_phrase(memory.position)
        if memory.visible:
            return f"Ahora mismo veo {name}, {side}."
        seconds = memory.seconds_since_seen()
        age = f"{round(seconds)} segundos" if seconds < 60 else f"{max(1, round(seconds / 60))} minutos"
        return f"Vi {name} por última vez hace {age}, {side} en la imagen de entonces. Ahora no puedo confirmar dónde está."

    def as_dict(self) -> dict:
        self.expire_camera()
        return {
            "camera_fresh": self.camera_fresh,
            "camera_view": self.camera_view,
            "stable_scene": self.stable_scene,
            "recent_changes": list(self.changes),
            "objects": {cls: m.as_dict() for cls, m in self.objects.items()},
            "active_target": self.active_target,
            "person_visible": self.person_visible,
            "pepon_state": self.pepon_state,
            "phone_motion_phase": self.phone_motion_phase,
            "last_motion_event": self.last_motion_event,
        }

    @property
    def camera_fresh(self):
        return self.last_detection_at is not None and time.time() - self.last_detection_at < 2.5

    def expire_camera(self):
        if not self.camera_fresh:
            self.invalidate_camera()
        self._forget_stale()

    def invalidate_camera(self):
        self.camera_revision += 1
        for memory in self.objects.values():
            memory.visible = False
        self.last_detection_at = None
        self._candidates.clear()
        self.stable_scene.clear()
        self.scene_ready = False
        self._scene_started = None
        self.changes.clear()

    def _update_scene(self, now):
        if self._scene_started is None:
            self._scene_started = now
        scene = {cls: m.position for cls, m in self.objects.items() if m.visible}
        for cls in set(scene) | set(self.stable_scene) | set(self._candidates):
            value = scene.get(cls)
            old = self.stable_scene.get(cls)
            if value == old:
                self._candidates.pop(cls, None)
                continue
            candidate = self._candidates.get(cls)
            if candidate is None or candidate[0] != value:
                self._candidates[cls] = (value, now, 1)
                continue
            value, since, count = candidate
            self._candidates[cls] = (value, since, count + 1)
            # Require distinct fresh frames AND duration, so one bad frame
            # or replayed image can never fire a disappearance alert.
            if count + 1 < 3 or now - since < 1.0:
                continue
            if value is None:
                self.stable_scene.pop(cls, None)
            else:
                self.stable_scene[cls] = value
                if cls in self.objects:
                    self.objects[cls].confirmed = True
            if self.scene_ready:
                kind = 'disappear' if value is None else ('appear' if old is None else 'move')
                self.changes.append({'object': cls, 'event': kind, 'from': old, 'to': value, 'at': now})
            self._candidates.pop(cls, None)
        if now - self._scene_started >= 1.0:
            self.scene_ready = True

    def describe_changes(self):
        self.expire_camera()
        if not self.camera_fresh or not self.scene_ready:
            return 'Necesito unos segundos de cámara estable para comparar la escena.'
        recent = [c for c in self.changes if time.time() - c['at'] < 60]
        if not recent:
            return 'No he confirmado cambios en los objetos durante el último minuto.'
        descriptions = []
        for c in recent[-6:]:
            name = object_es(c['object'])
            if c['event'] == 'appear':
                descriptions.append(f"Ha aparecido {name}")
            elif c['event'] == 'disappear':
                descriptions.append(f"He dejado de ver {name}")
            else:
                descriptions.append(f"{name} ha pasado a estar {position_es_phrase(c['to'])} en la imagen")
        return '. '.join(descriptions) + '. Los cambios son respecto al encuadre de la cámara.'

    def export_memory(self):
        self._forget_stale()
        return {cls: asdict(m) for cls, m in self.objects.items()}

    def restore_memory(self, data):
        for cls, values in data.items():
            if cls not in OBJECT_ES or not isinstance(values, dict):
                continue
            try:
                memory = ObjectMemory(**values)
                if memory.cls != cls or not isinstance(memory.last_seen_at, (int, float)):
                    continue
                memory.visible = False
                self.objects[cls] = memory
            except (TypeError, ValueError):
                continue
        self._forget_stale()
