# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Local persistent errands, conversational context and restrained initiative."""
import asyncio
import json
import time
import uuid
from collections import deque
from pathlib import Path

from vocabulary import OBJECT_ES
from world_state import object_es


class ConversationContext:
    def __init__(self):
        self.referent = None
        self.updated_at = 0
        self.history = deque(maxlen=12)

    def current_referent(self):
        if time.time() - self.updated_at > 300:
            self.history.clear()
            self.referent = None
        return self.referent

    def remember(self, text, response, target=None):
        if target:
            self.referent = target
        self.updated_at = time.time()
        self.history.append({'user': text[:1000], 'assistant': response[:1500]})


class Companion:
    def __init__(self, world, path=None):
        self.world = world
        self.path = Path(path) if path else None
        self.quiet = False
        self.watches = []
        self.notifications = []
        self.last_social_at = 0
        self.person_absent_since = None
        self.person_seen = False
        self._save_lock = asyncio.Lock()
        self._load()
        self.camera_lost()

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            self.quiet = bool(data.get('quiet', False))
            self.watches = [w for w in data.get('watches', []) if isinstance(w, dict)
                            and w.get('object') in OBJECT_ES and w.get('event') in ('appear', 'disappear', 'return')
                            and isinstance(w.get('id'), str)][:32]
            self.notifications = [n for n in data.get('notifications', []) if isinstance(n, dict)
                                  and isinstance(n.get('id'), str) and isinstance(n.get('text'), str)][:32]
            self.world.restore_memory(data.get('memory', {}))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            print(f'[companion] could not restore memory: {exc}')

    def as_dict(self):
        events = {'appear': 'Aparezca', 'disappear': 'Deje de verse', 'return': 'Vuelva a verse'}
        watches = [{**w, 'label': f"{events[w['event']]} {object_es(w['object'])}" +
                    (f": {w['reminder']}" if w.get('reminder') else '')} for w in self.watches]
        return {'quiet': self.quiet, 'watches': watches, 'notifications': self.notifications}

    async def save(self):
        if not self.path:
            return
        async with self._save_lock:
            payload = json.dumps({**self.as_dict(), 'memory': self.world.export_memory()}, ensure_ascii=False, indent=2)
            await asyncio.to_thread(self._write, payload)

    def _write(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(payload)
        temp.replace(self.path)

    def notify(self, text, kind='errand'):
        notice = {'id': uuid.uuid4().hex, 'text': text, 'kind': kind, 'at': time.time()}
        self.notifications.append(notice)
        self.notifications = self.notifications[-32:]
        return notice

    def acknowledge(self, notice_id):
        self.notifications = [n for n in self.notifications if n['id'] != notice_id]

    def camera_lost(self):
        # A disconnected/rotated camera is not evidence somebody left.
        self.person_absent_since = None
        for watch in self.watches:
            watch['absence_since'] = None
            watch['seen'] = False

    async def handle(self, parsed, context):
        kind = parsed['intent']
        if kind == 'CLARIFY_OBJECT':
            return '¿A qué objeto te refieres?'
        if kind == 'SCENE_CHANGES':
            return self.world.describe_changes()
        if kind == 'QUIET_MODE':
            self.quiet = parsed['enabled']
            if self.quiet:
                self.notifications = [n for n in self.notifications if n['kind'] != 'social']
            await self.save()
            return 'Modo tranquilo activado. Solo hablaré si me preguntas o si se cumple un encargo.' if self.quiet else 'Modo sociable activado.'
        if kind == 'LIST_WATCHES':
            if not self.watches:
                return 'No tienes encargos pendientes.'
            events = {'appear': 'aparezca', 'disappear': 'deje de verse', 'return': 'vuelva a verse'}
            return 'Pendientes: ' + '; '.join(
                f"avisar cuando {events[w['event']]} {object_es(w['object'])}" +
                (f": {w['reminder']}" if w.get('reminder') else '') for w in self.watches) + '.'
        if kind == 'CANCEL_WATCHES':
            obj = parsed.get('object')
            self.watches = [w for w in self.watches if obj and w['object'] != obj]
            await self.save()
            return 'He cancelado los encargos de ese objeto.' if obj else 'He cancelado todos los encargos pendientes.'
        if kind != 'WATCH':
            return None
        if len(self.watches) >= 32:
            return 'Ya tengo 32 encargos. Cancela alguno antes de añadir otro.'
        reminder = parsed.get('reminder', '')
        if reminder in ('esto', 'eso', 'lo anterior'):
            if not context.history:
                return 'Dime qué quieres que te recuerde cuando vuelvas.'
            reminder = context.history[-1]['assistant'] or context.history[-1]['user']
        obj, event = parsed['object'], parsed['event']
        if any(w['object'] == obj and w['event'] == event and w.get('reminder', '') == reminder for w in self.watches):
            return 'Ese encargo ya está pendiente.'
        present = self.world.camera_fresh and self.world.scene_ready and obj in self.world.stable_scene
        if event == 'appear' and present:
            return f'Ahora mismo ya veo {object_es(obj)}. Si quieres, puedo avisarte cuando vuelva a aparecer.'
        watch = {'id': uuid.uuid4().hex, 'object': obj, 'event': event,
                 'reminder': reminder[:1000], 'created_at': time.time(),
                 'seen': bool(present), 'absence_since': None}
        self.watches.append(watch)
        await self.save()
        trigger = {'appear': 'aparezca', 'disappear': 'deje de verse', 'return': 'vuelva a verse'}[event]
        return f"Te avisaré cuando {trigger} {object_es(obj)} en la cámara." + (f' Te recordaré: {reminder}.' if reminder else '')

    def observe(self, busy=False):
        world = self.world
        if not world.camera_fresh or not world.scene_ready:
            return False
        now = time.time()
        changed = False
        for watch in list(self.watches):
            present = watch['object'] in world.stable_scene
            previously_seen = watch.get('seen', False)
            if present:
                watch['seen'] = True
            else:
                watch['absence_since'] = watch.get('absence_since') or now
            event = watch['event']
            fire = (event == 'appear' and present or
                    event == 'disappear' and previously_seen and not present or
                    event == 'return' and present and watch.get('absence_since') is not None
                    and now - watch['absence_since'] >= 3)
            if fire:
                text = watch.get('reminder')
                if text:
                    text = f'Hay alguien de vuelta en la cámara. Te recuerdo: {text}.'
                else:
                    verb = 'He dejado de ver' if event == 'disappear' else 'Ahora veo'
                    text = f"{verb} {object_es(watch['object'])} en la cámara."
                self.notify(text)
                self.watches.remove(watch)
                changed = True
            elif present:
                watch['absence_since'] = None
        person = 'person' in world.stable_scene
        if person:
            absent_for = now - self.person_absent_since if self.person_absent_since is not None else 0
            if self.person_seen and absent_for >= 30 and not self.quiet and not busy and now - self.last_social_at >= 120:
                self.notify('¡Hola! Vuelvo a ver a alguien por aquí.', 'social')
                self.last_social_at = now
                changed = True
            self.person_seen = True
            self.person_absent_since = None
        elif self.person_seen and self.person_absent_since is None:
            self.person_absent_since = now
        # Social remarks expire rather than greeting somebody minutes later.
        self.notifications = [n for n in self.notifications if n['kind'] != 'social' or now - n['at'] < 20]
        return changed

    def react_to_pickup(self, busy=False):
        now = time.time()
        if not self.quiet and not busy and now - self.last_social_at >= 120:
            self.last_social_at = now
            self.notify('¡Vamos allá! ¿Qué me quieres enseñar?', 'social')
            return True
        return False
