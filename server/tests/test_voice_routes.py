# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Exercise the HTTP/WS pipeline without loading GPU models or using a mic."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from actions import PhoneExecutor
from agent import Agent
from cognition.gemma_agent import GemmaDecision
from companion import Companion, ConversationContext
from world_state import WorldState


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class Speech:
    def transcribe(self, audio):
        return '¿Ves una botella?'


def test_voice_pipeline_context_cancellation_and_api(tmp_path):
    async def run():
        world = WorldState()
        world.update_detections([{'class': 'bottle', 'confidence': .9, 'x': .5, 'y': 0}])
        companion = Companion(world, tmp_path / 'companion.json')
        socket = Socket()
        executor = PhoneExecutor(main.broadcast)
        agent = Agent(world, executor)
        with patch.multiple(main, world_state=world, companion=companion, connections={socket},
                            voice_sessions={}, manual_context=ConversationContext(),
                            action_executor=executor, agent=agent, speech_service=Speech(),
                            command_lock=asyncio.Lock(), speech_lock=asyncio.Lock()):
            client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test')
            async with client:
                await main._handle_text_message(json.dumps({'type': 'conversation', 'session': 'first', 'active': True}), socket)
                result = await client.post('/api/voice/audio', content=b'audio', headers={'X-Conversation-ID': 'first', 'X-Turn-ID': '1'})
                assert result.status_code == 200
                assert result.json()['intent']['object'] == 'bottle'
                assert socket.sent[-1]['session'] == 'first'
                assert socket.sent[-1]['turn'] == 1
                result = await main._route_voice_text('¿Dónde está?', ('first', 1))
                assert result['intent']['object'] == 'bottle'
                result = await main._route_voice_text('avísame cuando desaparezca', ('first', 1))
                assert result['intent']['intent'] == 'WATCH'
                status = (await client.get('/api/assistant')).json()
                assert len(status['watches']) == 1
                assert 'botella' in status['watches'][0]['label']
                await client.post('/api/assistant/preferences', json={'quiet': True})
                assert companion.quiet
                await client.delete('/api/assistant/watches/' + status['watches'][0]['id'])
                assert not companion.watches
                # End the session while a slow semantic response is in flight.
                started, release = asyncio.Event(), asyncio.Event()
                async def delayed(*args, **kwargs):
                    assert kwargs['history']
                    started.set()
                    await release.wait()
                    return GemmaDecision(action='SPEAK', text='Esta respuesta ya no debe sonar')
                with patch.object(main.gemma_agent, 'decide', delayed), patch.object(main.gemma_agent, 'enabled', True):
                    pending = asyncio.create_task(main._route_voice_text('cuéntame un cuento', ('first', 1)))
                    await started.wait()
                    await main._handle_text_message(json.dumps({'type': 'conversation', 'session': 'first', 'active': False}), socket)
                    release.set()
                    assert (await pending)['cancelled']
                assert not any('ya no debe' in m.get('text', '') for m in socket.sent)
                stale = await client.post('/api/voice/audio', content=b'audio', headers={'X-Conversation-ID': 'first', 'X-Turn-ID': '1'})
                assert stale.json()['cancelled']
                await main._handle_text_message(json.dumps({'type': 'conversation', 'session': 'second', 'active': True}), socket)
                assert main.voice_sessions['second']['context'].current_referent() is None
                # Older turns cannot run after an interruption.
                await main._handle_text_message(json.dumps({'type': 'voice_activity', 'session': 'second', 'turn': 3, 'state': 'capturing'}), socket)
                stale = await client.post('/api/voice/audio', content=b'audio', headers={'X-Conversation-ID': 'second', 'X-Turn-ID': '2'})
                assert stale.json()['cancelled']
                too_large = await client.post('/api/voice/audio', content=b'x' * 4_000_001)
                assert too_large.status_code == 413
    asyncio.run(run())


def test_simple_visibility_questions_bypass_semantic_model():
    async def run():
        world = WorldState()
        world.update_detections([{'class': 'cup', 'confidence': .9, 'x': .5, 'y': 0}])
        socket = Socket()
        executor = PhoneExecutor(main.broadcast)
        with patch.multiple(main, world_state=world, companion=Companion(world), connections={socket},
                            manual_context=ConversationContext(), agent=Agent(world, executor),
                            command_lock=asyncio.Lock()), patch.object(main.gemma_agent, 'decide', AsyncMock()) as semantic:
            for text in ['¿Ves la taza?', 'Bes la taza', 'Vale, ¿ves una taza?']:
                result = await main._route_voice_text(text)
                assert result['intent'] == {'intent': 'WHERE_IS', 'object': 'cup'}
                assert 'Ahora mismo veo la taza' in result['response']
            assert not semantic.called
    asyncio.run(run())
