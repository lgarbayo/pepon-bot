# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Turns raw phone motion samples into discrete, debounced events.

No ML — just thresholds on accelerationIncludingGravity magnitude
(constant ~9.81 regardless of phone orientation, so it's a clean
motion-intensity signal on its own) plus device-orientation tilt
angle. Emits an event only when the classified phase *changes*, so
holding the phone still after a shake doesn't spam PHONE_STABLE.
"""
import math
import time
from collections import deque
from typing import Optional

GRAVITY = 9.81  # m/s^2

STABLE_DELTA_THRESHOLD = 0.5      # |accel| - gravity, below this = basically still
PICKUP_DELTA_THRESHOLD = 2.5      # a single jolt above this = picked up
SHAKE_SPIKE_THRESHOLD = 5.0       # a bigger jolt counts as a "spike" for shake detection
SHAKE_MIN_CROSSINGS = 3           # this many spikes inside the window = shaking, not just one jolt
SHAKE_WINDOW_SECONDS = 0.8
TILT_ANGLE_THRESHOLD = 35.0       # degrees of beta/gamma from resting flat

PHASES = ("STABLE", "TILTED", "PICKED_UP", "SHAKEN")


class MotionClassifier:
    def __init__(self):
        self._deltas: deque = deque()  # (timestamp, delta) for the shake window
        self._last_phase = "STABLE"

    @property
    def phase(self) -> str:
        """Current classified phase (STABLE/TILTED/PICKED_UP/SHAKEN)."""
        return self._last_phase

    def update(self, accel_gravity: Optional[dict], orientation: Optional[dict]) -> Optional[str]:
        """Feed one sample. Returns "PHONE_<PHASE>" only on a phase
        transition, else None. Missing sensors degrade gracefully —
        whatever signal is available (or none) is used."""
        now = time.time()

        delta = None
        if accel_gravity and all(k in accel_gravity and accel_gravity[k] is not None for k in ("x", "y", "z")):
            magnitude = math.sqrt(accel_gravity["x"] ** 2 + accel_gravity["y"] ** 2 + accel_gravity["z"] ** 2)
            delta = abs(magnitude - GRAVITY)
            self._deltas.append((now, delta))
            cutoff = now - SHAKE_WINDOW_SECONDS
            while self._deltas and self._deltas[0][0] < cutoff:
                self._deltas.popleft()

        spikes = sum(1 for _, d in self._deltas if d > SHAKE_SPIKE_THRESHOLD)

        tilt_angle = None
        if orientation and orientation.get("beta") is not None and orientation.get("gamma") is not None:
            tilt_angle = max(abs(orientation["beta"]), abs(orientation["gamma"]))

        phase = self._classify(delta, spikes, tilt_angle)
        if phase is None or phase == self._last_phase:
            return None
        self._last_phase = phase
        return f"PHONE_{phase}"

    def _classify(self, delta, spikes, tilt_angle) -> Optional[str]:
        if spikes >= SHAKE_MIN_CROSSINGS:
            return "SHAKEN"
        if delta is not None and delta > PICKUP_DELTA_THRESHOLD:
            return "PICKED_UP"
        if tilt_angle is not None and tilt_angle > TILT_ANGLE_THRESHOLD:
            return "TILTED"
        if delta is not None and delta < STABLE_DELTA_THRESHOLD and (
            tilt_angle is None or tilt_angle < TILT_ANGLE_THRESHOLD
        ):
            return "STABLE"
        if delta is None and tilt_angle is None:
            return None  # no usable sensor data at all
        return None  # ambiguous mid-range sample: hold the previous phase
