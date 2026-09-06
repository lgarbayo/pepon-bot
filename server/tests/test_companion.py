import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion import Companion, ConversationContext
from intent import parse
from vocabulary import OBJECT_ES, extract_object
from world_state import WorldState


def detection(cls='cup', x=0):
    return {'class': cls, 'confidence': .9, 'x': x, 'y': 0}


def stable(world, at, detections):
    for offset in (0, .5, 1.1):
        with patch('time.time', return_value=at + offset):
            world.update_detections(detections)


def test_all_80_classes_and_word_boundaries():
    assert len(OBJECT_ES) == 80
    for cls, name in OBJECT_ES.items():
        assert extract_object(cls) == cls
        assert parse(f'¿Dónde está {name}?')['object'] == cls
    assert extract_object('apoyo') is None
    assert extract_object('bowl') == 'bowl'
    assert extract_object('oso de peluche') == 'teddy bear'
    assert extract_object('botellas') == 'bottle'


def test_context_and_new_intents():
    assert parse('¿Ves una botella?')['object'] == 'bottle'
    assert parse('¿Y dónde está?', 'bottle')['object'] == 'bottle'
    assert parse('avísame cuando desaparezca', 'bottle') == {'intent': 'WATCH', 'object': 'bottle', 'event': 'disappear'}
    assert parse('dónde está')['intent'] == 'CLARIFY_OBJECT'
    assert parse('vigila si vuelve a estar la taza')['event'] == 'return'
    assert parse('qué ha cambiado en la mesa')['intent'] == 'SCENE_CHANGES'
    assert parse('desactiva el modo tranquilo')['enabled'] is False
    assert parse('modo tranquilo')['enabled'] is True
    assert parse('recuérdame beber agua cuando vuelva')['reminder'] == 'beber agua'
    context = ConversationContext()
    with patch('time.time', return_value=100):
        context.remember('taza', 'veo una taza', 'cup')
    with patch('time.time', return_value=500):
        assert context.current_referent() is None
        assert not context.history


def test_scene_debounce_and_stale_camera():
    world = WorldState()
    stable(world, 100, [detection()])
    with patch('time.time', return_value=101.2):
        world.update_detections([])
        assert 'cup' in world.stable_scene
    with patch('time.time', return_value=101.3):
        world.update_detections([detection()])
        assert not world.changes
    stable(world, 102, [])
    with patch('time.time', return_value=103.2):
        assert 'dejado de ver la taza' in world.describe_changes()
        assert 'última vez' in world.describe('cup')
    stable(world, 104, [detection(x=.7)])
    with patch('time.time', return_value=110):
        assert 'Ahora mismo' not in world.describe('cup')
        assert not world.camera_fresh
        assert not world.stable_scene
        assert world.get_object('cup') is not None


def test_memory_persists_as_past_observation(tmp_path):
    async def run():
        with patch('time.time', return_value=100):
            world = WorldState()
            world.update_detections([detection()])
            companion = Companion(world, tmp_path / 'memory.json')
            companion.quiet = True
            await companion.save()
        with patch('time.time', return_value=200):
            restored = WorldState()
            companion = Companion(restored, tmp_path / 'memory.json')
            assert companion.quiet
            assert 'última vez' in restored.describe('cup')
            assert not restored.get_object('cup').visible
    asyncio.run(run())


def test_errand_debounce_delivery_and_restart(tmp_path):
    async def run():
        world = WorldState()
        companion = Companion(world, tmp_path / 'memory.json')
        stable(world, 100, [detection()])
        with patch('time.time', return_value=101.2):
            await companion.handle(parse('avísame cuando desaparezca la taza'), ConversationContext())
        with patch('time.time', return_value=102):
            world.update_detections([])
            companion.observe()
            assert not companion.notifications
        with patch('time.time', return_value=102.2):
            world.update_detections([detection()])
            companion.observe()
            assert not companion.notifications
        stable(world, 103, [])
        with patch('time.time', return_value=104.2):
            companion.observe()
            assert len(companion.notifications) == 1
            assert not companion.watches
            companion.observe()
            assert len(companion.notifications) == 1
            await companion.save()
            restored = Companion(WorldState(), tmp_path / 'memory.json')
            assert len(restored.notifications) == 1
            restored.acknowledge(restored.notifications[0]['id'])
            await restored.save()
            assert not Companion(WorldState(), tmp_path / 'memory.json').notifications
    asyncio.run(run())


def test_disconnect_is_not_disappearance():
    async def run():
        world = WorldState()
        companion = Companion(world)
        stable(world, 100, [detection()])
        with patch('time.time', return_value=101.2):
            await companion.handle(parse('avísame cuando desaparezca la taza'), ConversationContext())
            world.invalidate_camera()
            companion.camera_lost()
        stable(world, 200, [])
        with patch('time.time', return_value=201.2):
            companion.observe()
            assert not companion.notifications
            assert companion.watches
    asyncio.run(run())


def test_return_reminder_and_quiet_greeting():
    async def run():
        world = WorldState()
        companion = Companion(world)
        stable(world, 100, [detection('person')])
        with patch('time.time', return_value=101.2):
            companion.observe()
            await companion.handle(parse('recuérdame beber agua cuando vuelva'), ConversationContext())
            await companion.handle(parse('modo tranquilo'), ConversationContext())
            companion.observe()
            assert not companion.notifications
        stable(world, 105, [])
        with patch('time.time', return_value=106.2):
            companion.observe()
        stable(world, 145, [detection('person')])
        with patch('time.time', return_value=146.2):
            companion.observe()
            assert len(companion.notifications) == 1
            assert 'beber agua' in companion.notifications[0]['text']
            assert companion.notifications[0]['kind'] == 'errand'
            assert not companion.watches
    asyncio.run(run())


def test_sociable_greeting_cooldown_and_pickup():
    world = WorldState()
    companion = Companion(world)
    stable(world, 1000, [detection('person')])
    with patch('time.time', return_value=1001.2):
        companion.observe()
        assert not companion.notifications
    stable(world, 1005, [])
    with patch('time.time', return_value=1006.2):
        companion.observe()
    stable(world, 1040, [detection('person')])
    with patch('time.time', return_value=1041.2):
        companion.observe()
        assert len(companion.notifications) == 1
        assert not companion.react_to_pickup()
    with patch('time.time', return_value=1200):
        assert companion.react_to_pickup()
        companion.quiet = True
    with patch('time.time', return_value=1400):
        assert not companion.react_to_pickup()
