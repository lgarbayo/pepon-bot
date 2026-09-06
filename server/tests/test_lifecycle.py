# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

import asyncio
import errno
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from recorder import EpisodeRecorder


def test_busy_port_exits_before_loading_models_or_saving_memory():
    with patch.object(main.socket, 'create_server', side_effect=OSError(errno.EADDRINUSE, 'busy')), \
         patch.object(main, '_run_server') as run:
        with pytest.raises(SystemExit) as exc:
            main.run_server()
        assert exc.value.code == 1
        run.assert_not_called()


def test_lifespan_stops_detection_and_flushes_episodes(tmp_path):
    async def run():
        recorder = EpisodeRecorder(tmp_path)
        started = asyncio.Event()
        stopped = asyncio.Event()
        async def detection():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        companion = SimpleNamespace(save=AsyncMock())
        gemma = SimpleNamespace(aclose=AsyncMock())
        with patch.multiple(main, load_perception_model=AsyncMock(), load_speech_model=AsyncMock(),
                            _detection_loop=detection, companion=companion, gemma_agent=gemma,
                            recorder=recorder, agent=SimpleNamespace(cancel_search=Mock())):
            async with main.app.router.lifespan_context(main.app):
                await started.wait()
                episode = recorder.start_episode('hola', {'intent': 'UNKNOWN'})
                recorder.end_episode(episode, 'success')
            assert stopped.is_set()
            assert recorder._task is None
            metadata = json.loads((tmp_path / episode / 'metadata.json').read_text())
            assert metadata['result']['status'] == 'success'
            companion.save.assert_awaited_once()
            gemma.aclose.assert_awaited_once()
    asyncio.run(run())


def test_startup_failure_closes_client_without_overwriting_saved_memory():
    async def run():
        companion = SimpleNamespace(save=AsyncMock())
        gemma = SimpleNamespace(aclose=AsyncMock())
        recorder = SimpleNamespace(start=Mock(), stop=AsyncMock())
        with patch.multiple(main, load_perception_model=AsyncMock(),
                            load_speech_model=AsyncMock(side_effect=RuntimeError('model failed')),
                            companion=companion, gemma_agent=gemma, recorder=recorder):
            with pytest.raises(RuntimeError, match='model failed'):
                async with main.lifespan(main.app):
                    pytest.fail('startup should fail')
            recorder.start.assert_not_called()
            companion.save.assert_not_awaited()
            recorder.stop.assert_awaited_once()
            gemma.aclose.assert_awaited_once()
    asyncio.run(run())
