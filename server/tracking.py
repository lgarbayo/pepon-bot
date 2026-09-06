# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Turns raw person detections into a single smoothed gaze target for
Pepon's eyes.

Deliberately simple — no identity/re-id, no Kalman filter: just
nearest-neighbor continuity (stick with whichever detection is closest
to where we were already looking) plus exponential smoothing. Good
enough to convincingly follow one person around a frame; swap for a
real multi-object tracker later without touching the caller.
"""
import time
from typing import List, Optional, Tuple

TRACK_CONFIDENCE_THRESHOLD = 0.55  # stricter than the general detection threshold
MAX_ASSOCIATION_DISTANCE = 0.6  # normalized units a "same" target may move between cycles
EMA_ALPHA_TRACK = 0.35  # higher = snappier, lower = smoother
EMA_ALPHA_RETURN = 0.15  # slower ease back to neutral once the target is lost
LOST_GRACE_SECONDS = 0.8  # brief pause before easing back, so one missed frame doesn't jolt the eyes
NEUTRAL_EPSILON = 0.03  # close enough to center to stop sending updates

Point = Tuple[float, float]


class PersonTracker:
    def __init__(self):
        self._smoothed: Optional[Point] = None
        self._raw_target: Optional[Point] = None
        self._last_seen_at: Optional[float] = None
        self._at_neutral = True

    def update(self, detections: List[dict]) -> Optional[Point]:
        """Feed the latest detections; returns (x, y) to look_at, or None
        if nothing should be sent this cycle."""
        now = time.time()
        people = [
            d for d in detections
            if d["class"] == "person" and d["confidence"] >= TRACK_CONFIDENCE_THRESHOLD
        ]

        candidate = self._pick_candidate(people)
        if candidate is not None:
            self._raw_target = (candidate["x"], candidate["y"])
            self._last_seen_at = now
            self._at_neutral = False
            self._smoothed = _ema(self._smoothed, self._raw_target, EMA_ALPHA_TRACK)
            return self._smoothed

        # No usable person this cycle: hold, ease back to neutral, or stay quiet.
        if self._last_seen_at is None or self._at_neutral:
            return None
        if now - self._last_seen_at < LOST_GRACE_SECONDS:
            return None  # brief pause — don't react to a single missed frame

        self._smoothed = _ema(self._smoothed, (0.0, 0.0), EMA_ALPHA_RETURN)
        if abs(self._smoothed[0]) < NEUTRAL_EPSILON and abs(self._smoothed[1]) < NEUTRAL_EPSILON:
            self._at_neutral = True
            self._raw_target = None
        return self._smoothed

    def _pick_candidate(self, people: List[dict]) -> Optional[dict]:
        if not people:
            return None
        if self._raw_target is not None:
            close = [
                p for p in people
                if _distance((p["x"], p["y"]), self._raw_target) <= MAX_ASSOCIATION_DISTANCE
            ]
            if close:
                return min(close, key=lambda p: _distance((p["x"], p["y"]), self._raw_target))
        return max(people, key=lambda p: p["confidence"])


def _ema(previous: Optional[Point], sample: Point, alpha: float) -> Point:
    if previous is None:
        return sample
    return (
        previous[0] + alpha * (sample[0] - previous[0]),
        previous[1] + alpha * (sample[1] - previous[1]),
    )


def _distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
