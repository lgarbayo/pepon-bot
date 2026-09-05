"""Turns a recognized voice command (plain text from the phone's STT)
into a structured Intent.

Deterministic pattern matching — no LLM, because these 5 MVP commands
don't need one. `parse(text) -> dict` is the entire contract; swap
this module for an LLM-based parser later without touching Agent or
anything else that consumes an Intent, as long as it keeps returning
the same {"intent": ..., ...} shape.
"""
import re
from typing import Optional

# Spoken words -> canonical COCO class name (same vocabulary PerceptionService
# detects). Longest/most specific aliases first so "cell phone" doesn't get
# shadowed by a shorter partial match.
OBJECT_ALIASES = {
    "cell phone": "cell phone",
    "cellphone": "cell phone",
    "mobile phone": "cell phone",
    "phone": "cell phone",
    "bottle": "bottle",
    "laptop": "laptop",
    "chair": "chair",
    "cup": "cup",
    "person": "person",
}

INTENT_WHAT_DO_YOU_SEE = "WHAT_DO_YOU_SEE"
INTENT_FIND_OBJECT = "FIND_OBJECT"
INTENT_WHERE_IS = "WHERE_IS"
INTENT_LOOK_AT_ME = "LOOK_AT_ME"
INTENT_UNKNOWN = "UNKNOWN"


def _extract_object(text: str) -> Optional[str]:
    for alias, canonical in OBJECT_ALIASES.items():
        if alias in text:
            return canonical
    return None


def parse(text: str) -> dict:
    """Never raises — worst case returns INTENT_UNKNOWN so the caller
    (Agent) can react gracefully (e.g. a CONFUSED expression) instead
    of crashing on an unrecognized phrase."""
    normalized = re.sub(r"[?.!,]", "", text.strip().lower())

    if re.search(r"\bwhat (do|can) you see\b", normalized):
        return {"intent": INTENT_WHAT_DO_YOU_SEE}

    if re.search(r"\bwhere (is|are|'s)\b", normalized):
        obj = _extract_object(normalized)
        if obj:
            return {"intent": INTENT_WHERE_IS, "object": obj}

    if re.search(r"\b(find|look for|search for)\b", normalized):
        obj = _extract_object(normalized)
        if obj:
            return {"intent": INTENT_FIND_OBJECT, "object": obj}

    if re.search(r"\blook at me\b", normalized):
        return {"intent": INTENT_LOOK_AT_ME}

    return {"intent": INTENT_UNKNOWN, "text": text}
