"""Turns a recognized voice command (plain text from the phone's STT)
into a structured Intent.

Deterministic pattern matching — no LLM, because these 5 MVP commands
don't need one. `parse(text) -> dict` is the entire contract; swap
this module for an LLM-based parser later without touching Agent or
anything else that consumes an Intent, as long as it keeps returning
the same {"intent": ..., ...} shape.

Bilingual (English + Spanish) since the demo runs in Spanish but the
patterns cost nothing to keep alongside the originals. Accents are
stripped before matching so "qué"/"que", "dónde"/"donde",
"está"/"esta" all match the same pattern regardless of whether the
STT engine included them.
"""
import re
import unicodedata
from typing import Optional

# Spoken words -> canonical COCO class name (same vocabulary PerceptionService
# detects). Longest/most specific aliases first so "cell phone" doesn't get
# shadowed by a shorter partial match. Written without accents — input is
# de-accented before matching (see _strip_accents).
OBJECT_ALIASES = {
    "cell phone": "cell phone",
    "cellphone": "cell phone",
    "mobile phone": "cell phone",
    "phone": "cell phone",
    "movil": "cell phone",
    "telefono": "cell phone",
    "bottle": "bottle",
    "botella": "bottle",
    "laptop": "laptop",
    "portatil": "laptop",
    "ordenador": "laptop",
    "chair": "chair",
    "silla": "chair",
    "cup": "cup",
    "taza": "cup",
    "person": "person",
    "persona": "person",
}

INTENT_WHAT_DO_YOU_SEE = "WHAT_DO_YOU_SEE"
INTENT_FIND_OBJECT = "FIND_OBJECT"
INTENT_WHERE_IS = "WHERE_IS"
INTENT_LOOK_AT_ME = "LOOK_AT_ME"
INTENT_UNKNOWN = "UNKNOWN"


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _extract_object(text: str) -> Optional[str]:
    for alias, canonical in OBJECT_ALIASES.items():
        if alias in text:
            return canonical
    return None


def parse(text: str) -> dict:
    """Never raises — worst case returns INTENT_UNKNOWN so the caller
    (Agent) can react gracefully (e.g. a CONFUSED expression) instead
    of crashing on an unrecognized phrase."""
    normalized = re.sub(r"[?.!,¿¡]", "", text.strip().lower())
    normalized = _strip_accents(normalized)

    if re.search(r"\bwhat (do|can) you see\b", normalized) or re.search(r"\bque ves\b", normalized):
        return {"intent": INTENT_WHAT_DO_YOU_SEE}

    if re.search(r"\bwhere (is|are|'s)\b", normalized) or re.search(r"\bdonde est", normalized):
        obj = _extract_object(normalized)
        if obj:
            return {"intent": INTENT_WHERE_IS, "object": obj}

    if re.search(r"\b(find|look for|search for)\b", normalized) or re.search(
        r"\b(encuentra|busca|encontrar|buscar)\b", normalized
    ):
        obj = _extract_object(normalized)
        if obj:
            return {"intent": INTENT_FIND_OBJECT, "object": obj}

    if re.search(r"\blook at me\b", normalized) or re.search(r"\bmirame\b", normalized) or re.search(
        r"\bmira a mi\b", normalized
    ):
        return {"intent": INTENT_LOOK_AT_ME}

    return {"intent": INTENT_UNKNOWN, "text": text}
