"""Local Whisper transcription for pause-delimited PCM/WAV utterances.
The phone's AudioWorklet handles capture and voice activity; this service
also accepts older MediaRecorder containers through PyAV decoding.
"""
import io
from typing import BinaryIO, Union

import config


class SpeechService:
    """Loads a local Whisper model once and transcribes short audio
    clips. Tries CUDA first, falls back to CPU if that fails (e.g. no
    compatible GPU) — a slower transcription still beats a crash."""

    def __init__(self):
        from faster_whisper import WhisperModel  # local import: keep ctranslate2 out of every other module

        try:
            self._model = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16")
            self.device = "cuda"
        except Exception as exc:
            print(f"[speech] CUDA unavailable for Whisper ({exc}), falling back to CPU")
            self._model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
            self.device = "cpu"

    def transcribe(self, audio_bytes: Union[bytes, BinaryIO]) -> str:
        """Blocking — call via asyncio.to_thread. Accepts whatever
        container MediaRecorder produced (webm/opus, mp4/aac, ...);
        faster-whisper decodes it via PyAV, no format-specific handling
        needed here."""
        buffer = io.BytesIO(audio_bytes) if isinstance(audio_bytes, (bytes, bytearray)) else audio_bytes
        segments, _info = self._model.transcribe(
            buffer,
            language=config.WHISPER_LANGUAGE,
            vad_filter=True,  # second pass: discard remaining silence before transcription
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
