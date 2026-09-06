# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Fast, accent-insensitive commands with an optional conversational referent."""
import re

from vocabulary import extract_object, normalize

INTENT_WHAT_DO_YOU_SEE = 'WHAT_DO_YOU_SEE'
INTENT_FIND_OBJECT = 'FIND_OBJECT'
INTENT_WHERE_IS = 'WHERE_IS'
INTENT_LOOK_AT_ME = 'LOOK_AT_ME'
INTENT_UNKNOWN = 'UNKNOWN'
_strip_accents = normalize
_extract_object = extract_object


def parse(text: str, referent=None) -> dict:
    n = re.sub(r'[?.!,¿¡]', '', normalize(text.strip()))
    # Whisper occasionally spells the homophones "ves"/"bes" alike.
    # Only correct the question verb directly before an object phrase.
    n = re.sub(r'\bbes(?=\s+(?:el|la|los|las|un|una|mi|mis|algo)\b)', 'ves', n)
    obj = extract_object(n)
    # A pronoun or omitted object may use the recent referent; an explicit
    # unsupported noun must go to Gemma, never silently become the last object.
    implicit = bool(re.search(r'\b(ella|ello|eso|lo|la|desaparezca|aparezca)\b', n)) or bool(
        re.fullmatch(r'(y )?(donde esta|donde lo viste|donde la viste|buscal[oa])', n))
    target = obj or (referent if implicit else None)
    if re.search(r'\b(modo tranquilo|modo silencioso|no hables solo)\b', n) and not re.search(r'desactiva|quita', n):
        return {'intent': 'QUIET_MODE', 'enabled': True}
    if re.search(r'\b(modo sociable|desactiva el modo tranquilo|puedes saludar)\b', n):
        return {'intent': 'QUIET_MODE', 'enabled': False}
    if re.search(r'\b(cancela|borra|elimina)\b.*\b(avisos|encargos|recordatorios|aviso|encargo)\b', n):
        return {'intent': 'CANCEL_WATCHES', 'object': obj}
    if re.search(r'\b(que|mis|lista|dime)\b.*\b(avisos|encargos|recordatorios)\b', n):
        return {'intent': 'LIST_WATCHES'}
    reminder = re.search(r'recuerdame (.+?) cuando (?:vuelva|regrese)(?:\s|$)', n)
    if reminder:
        return {'intent': 'WATCH', 'object': 'person', 'event': 'return', 'reminder': reminder.group(1)}
    if re.search(r'\b(avisame|vigila|avisa|alertame)\b', n):
        event = 'disappear' if re.search(r'desaparez|no (?:este|veas)|se (?:vaya|vayan)|deje de', n) else 'appear'
        if re.search(r'vuelv|regres', n):
            event = 'return'
        if target:
            return {'intent': 'WATCH', 'object': target, 'event': event}
        return {'intent': 'CLARIFY_OBJECT'}
    if re.search(r'\bque (?:ha cambiado|cambio|cambios)|cambios en (?:la mesa|la escena)', n):
        return {'intent': 'SCENE_CHANGES'}
    if re.search(r'\bwhat (do|can) you see\b|\bque ves\b', n):
        return {'intent': INTENT_WHAT_DO_YOU_SEE}
    if re.search(r'\bwhere (is|are)|\bdonde (?:est|viste|lo viste|la viste)|ultima vez', n):
        return {'intent': INTENT_WHERE_IS, 'object': target} if target else {'intent': 'CLARIFY_OBJECT'}
    if re.search(r'\b(find|look for|search for|encuentra|busca|encontrar|buscar|buscalo|buscala)\b', n):
        if target:
            return {'intent': INTENT_FIND_OBJECT, 'object': target}
    if re.search(r'\b(ves|puedes ver)\b', n) and obj:
        return {'intent': INTENT_WHERE_IS, 'object': obj}
    if re.search(r'\b(look at me|mirame|mira a mi)\b', n):
        return {'intent': INTENT_LOOK_AT_ME}
    return {'intent': INTENT_UNKNOWN, 'text': text}
