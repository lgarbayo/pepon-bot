# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""EpisodeRecorder — records one meaningful voice interaction as a
small, structured episode on disk. Built for later inspection (and,
someday, imitation-learning experiments) — no training pipeline here,
just the recording format.

Non-blocking by design: every public method just does in-memory
bookkeeping and `queue.put_nowait(...)` — actual disk I/O happens in a
single background task that drains the queue via `asyncio.to_thread`,
strictly in order. Callers never await a write, so a slow disk can
never stall the live demo.

Layout per episode (data/episodes/episode_000001/):
  metadata.json       episode_id, start_time, end_time, result
  conversation.json   transcript, parsed intent, spoken responses
  observations.jsonl  one line per meaningful snapshot (not every frame)
  actions.jsonl       one line per Action the Agent executed
  frames/             optional JPEGs tied to a specific observation
"""
import asyncio
import json
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "episodes"


@dataclass
class _OpenEpisode:
    episode_id: str
    dir: Path
    start_time: float
    transcript: str
    intent: dict[str, Any]
    responses: list[dict] = field(default_factory=list)


class EpisodeRecorder:
    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._queue: asyncio.Queue[tuple] = asyncio.Queue()
        self._open: dict[str, _OpenEpisode] = {}
        self._next_id = self._infer_next_id()
        self._task = None

    def start(self) -> None:
        """Launch the background writer. Call once at app startup."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """Flush pending episode writes before stopping the background worker."""
        if self._task is None:
            return
        await self._queue.join()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def _infer_next_id(self) -> int:
        numbers = []
        for path in self.base_dir.glob("episode_*"):
            if path.is_dir():
                try:
                    numbers.append(int(path.name.split("_")[1]))
                except (IndexError, ValueError):
                    continue
        return max(numbers) + 1 if numbers else 1

    # ---- public API — every call returns immediately, never awaited ----

    def start_episode(self, transcript: str, intent: dict[str, Any]) -> str:
        episode_id = f"episode_{self._next_id:06d}"
        self._next_id += 1
        open_ep = _OpenEpisode(
            episode_id=episode_id,
            dir=self.base_dir / episode_id,
            start_time=time.time(),
            transcript=transcript,
            intent=intent,
        )
        self._open[episode_id] = open_ep

        self._queue.put_nowait(("mkdir", open_ep.dir, None))
        self._queue.put_nowait(("write_json", open_ep.dir / "metadata.json", {
            "episode_id": episode_id,
            "start_time": open_ep.start_time,
            "end_time": None,
            "result": None,
        }))
        self._queue.put_nowait(("write_json", open_ep.dir / "conversation.json", self._conversation(open_ep)))
        return episode_id

    def record_observation(
        self, episode_id: str, obs_type: str, data: dict[str, Any], frame_jpeg: bytes | None = None
    ) -> None:
        """A snapshot at a meaningful moment — not a per-frame stream.
        Callers decide what's worth recording (episode start, an object
        becoming visible, ...); this just persists it."""
        open_ep = self._open.get(episode_id)
        if open_ep is None:
            return
        timestamp = time.time()
        record = {"timestamp": timestamp, "type": obs_type, "data": data}
        if frame_jpeg is not None:
            frame_name = f"{obs_type}_{int(timestamp * 1000)}.jpg"
            record["frame"] = frame_name
            self._queue.put_nowait(("write_bytes", open_ep.dir / "frames" / frame_name, frame_jpeg))
        self._queue.put_nowait(("append_jsonl", open_ep.dir / "observations.jsonl", record))

    def record_action(self, episode_id: str, action_type: str, params: dict[str, Any]) -> None:
        open_ep = self._open.get(episode_id)
        if open_ep is None:
            return
        timestamp = time.time()
        self._queue.put_nowait((
            "append_jsonl", open_ep.dir / "actions.jsonl",
            {"timestamp": timestamp, "type": action_type, "params": params},
        ))
        if action_type == "SPEAK":
            # Spoken text doubles as the "conversation" half of this episode.
            open_ep.responses.append({"timestamp": timestamp, "text": params.get("text")})
            self._queue.put_nowait(("write_json", open_ep.dir / "conversation.json", self._conversation(open_ep)))

    def end_episode(self, episode_id: str, status: str, detail: str | None = None) -> None:
        open_ep = self._open.pop(episode_id, None)
        if open_ep is None:
            return
        self._queue.put_nowait(("write_json", open_ep.dir / "metadata.json", {
            "episode_id": episode_id,
            "start_time": open_ep.start_time,
            "end_time": time.time(),
            "result": {"status": status, "detail": detail},
        }))

    def is_open(self, episode_id: str) -> bool:
        return episode_id in self._open

    @staticmethod
    def _conversation(open_ep: _OpenEpisode) -> dict:
        return {
            "transcript": open_ep.transcript,
            "intent": open_ep.intent,
            "responses": list(open_ep.responses),
        }

    # ---- background writer: the only place that touches disk ----

    async def _worker(self) -> None:
        while True:
            op, path, payload = await self._queue.get()
            try:
                await asyncio.to_thread(self._perform, op, path, payload)
            except Exception as exc:
                print(f"[recorder] write failed ({op} {path}): {exc}")
            finally:
                self._queue.task_done()

    @staticmethod
    def _perform(op: str, path: Path, payload) -> None:
        if op == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
        elif op == "write_json":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, default=str))
        elif op == "append_jsonl":
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        elif op == "write_bytes":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
