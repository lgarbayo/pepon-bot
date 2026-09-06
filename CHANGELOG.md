# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and every entry explains *why* a change happened, not just what files it touched.

Every maintainer and contributor — human or AI-assisted — is expected to update this file for any user-facing change, as part of the pull request that makes it.

## [Unreleased]

### Added

- Open-source project packaging: README overhaul with architecture diagram and troubleshooting, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, MIT licensing with REUSE-compliant SPDX metadata, issue/PR templates, CI workflows and Dependabot — done once the initial build stabilized, so outside contributors have a clear entry point.

## [0.1.0] - 2026-09-06

Initial build, developed as a fast personal project over two days.

### Added

- FastAPI + WebSocket backend linking an Android phone (camera, microphone, sensors, speaker, screen) to a PC as compute — the phone is the body, the PC is the brain.
- Pixel-art face UI with 7 expression states, later restyled as a monochrome Game Boy palette.
- Real-time object detection via YOLOv8n, expanded from an initial 6-class allowlist to the full 80-class COCO vocabulary so any everyday object can be found, not just a hardcoded few.
- Person tracking, so Pepón's gaze follows whoever it sees, plus front/rear camera switching.
- Motion sensing (shake, pick-up, stability) from the phone's accelerometer.
- WorldState: short-term memory of what's currently visible vs. last seen and when. Later extended with 24h persistent memory, confirmed scene-change detection (require several consecutive frames before reporting a change, to avoid false alarms from a single bad frame), and a companion layer — one-shot watches, return reminders, quiet/sociable personality — backed by `data/companion.json`.
- Deterministic voice command parsing (find/where/look-at/what-do-you-see), initially via the browser's Web Speech API.
- GemmaAgent: a local-LLM (Gemma 3 via Ollama) semantic fallback for anything the deterministic parser can't handle, strictly grounded in WorldState (and optionally the live camera frame) so it never invents an object that was never actually seen.
- Fully local speech-to-text via `faster-whisper`, replacing the Web Speech API so voice input works in any browser, not just Chromium — and to remove the OS-level "mic active" beep triggered by repeatedly starting/stopping browser speech recognition.
- Continuous, hands-free conversation via real AudioWorklet-based capture: listening starts on speech, ends on silence rather than a manual stop, supports barge-in (interrupting a spoken reply) and shows a live volume meter. An earlier Siri-style push-to-talk button was replaced by this.
- `EpisodeRecorder`: every voice interaction logged to disk for later inspection.
- `/debug` page and `/api/health` for live diagnostics.

### Fixed

- `SPEAK` decisions with empty text produced silence with no visible cause; Gemma's fallback text and response logging were fixed so failures are visible instead of silent.
- `faster-whisper`'s CUDA path failed with `libcublas.so.12 not found` when only newer CUDA 13 NVIDIA packages were already installed; pinned `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` explicitly, matching the CUDA 12 ABI it actually needs.
- Ollama's default model registry (Cloudflare R2-hosted blobs) was unreachable from the development network; defaulted `OLLAMA_MODEL` to the HuggingFace-hosted equivalent tag instead.
- A single misdetected object (e.g. one stray YOLO frame reading "vase") could enter memory and then be repeated back by Gemma as fact for up to 24 hours once persistent memory was introduced. Object memory now requires confirmation across several consecutive detection frames before `GemmaAgent` is allowed to reference it — see `docs/ARCHITECTURE_DECISIONS.md`.
- Ctrl+C printed a spurious `KeyboardInterrupt` traceback after an already-clean shutdown (a uvloop re-raise); this is now suppressed so a clean stop doesn't look like a crash.

### Changed

- README translated to English and clarified that Gemma's conversation scope is intentionally limited to grounded, perception-related answers — not general trivia — with real examples from testing.
