# License rationale and third-party components

This is not legal advice — it's an honest, best-effort record of why PeponBot is licensed the way it is, and what to be aware of in its dependencies. If you're building on this project commercially or at scale, get your own legal review, especially regarding Ultralytics/YOLOv8 below.

## Why MIT for PeponBot's own code

PeponBot's own code (`server/`, `static/`) is licensed under the [MIT License](../LICENSE): the simplest, most widely understood permissive license, with no patent clause and minimal friction for anyone who wants to reuse, fork, or build on it — appropriate for a small personal project whose goal is to be a useful, readable reference, not to enforce that derivatives stay open.

## Direct dependencies (`requirements.txt`)

| Package | License | Notes |
| --- | --- | --- |
| `fastapi` | MIT | |
| `uvicorn[standard]` | BSD-3-Clause | |
| `Pillow` | MIT-CMU / HPND | Permissive, MIT-compatible. |
| `httpx` | BSD-3-Clause | |
| `faster-whisper` | MIT | |
| `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` | **Proprietary — NVIDIA EULA**, not OSI-approved | Redistributed via pip as runtime binaries required by `faster-whisper`'s CUDA path. Not open source; usable under NVIDIA's own license terms for running CUDA software, which is the intended use here. |
| `ultralytics` (YOLOv8n) | **AGPL-3.0-or-later**, or Ultralytics' commercial Enterprise License | See below — the one dependency that actually constrains how this project (and anything built on it) can be licensed and distributed. |

Transitive dependencies (`torch`, `numpy`, `ctranslate2`, and whatever `pip` pulls in underneath the above) are not individually audited here; run `pip install pip-licenses && pip-licenses` for a full transitive report before relying on this list for a formal compliance review.

## The Ultralytics/YOLOv8 AGPL-3.0 consideration

`ultralytics` (which provides YOLOv8n object detection) is licensed under **AGPL-3.0-or-later**, with a paid commercial license available from Ultralytics for closed-source use. AGPL is a *network copyleft* license: if a program that incorporates AGPL-licensed code is made available to users over a network, the complete corresponding source must be made available to those users.

PeponBot uses `ultralytics` as an unmodified library dependency (`from ultralytics import YOLO`), not by copying or modifying its source, and this repository is itself fully public and MIT-licensed already — so in practice, source availability isn't a gap here. If you fork PeponBot into something **closed-source**, or offer it as a hosted service without publishing your modifications, the AGPL obligations from the `ultralytics` dependency apply to you and are not waived by PeponBot's own MIT license — MIT only covers the code we wrote, not the libraries it imports. Swapping in a permissively-licensed detector (or Ultralytics' commercial license) would remove this constraint entirely, if that ever matters for your use case.

## Gemma model weights (not a code dependency, but a runtime one)

PeponBot downloads and runs a Gemma 3 model through Ollama at runtime. Google's Gemma models are distributed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms) and an accompanying Prohibited Use Policy — **not an OSI-approved open source license**. No model weights are redistributed by this repository; users pull the model themselves via `ollama pull`, and by doing so accept Google's terms directly. If you swap in a different model through `OLLAMA_MODEL`, its own license/terms apply instead.

## Ollama itself

[Ollama](https://ollama.com) (the local LLM server PeponBot talks to over HTTP) is MIT-licensed. It's an external application PeponBot depends on at runtime, not a bundled dependency.

## YOLOv8n weights file (`yolov8n.pt`)

Auto-downloaded by `ultralytics` on first run into the repository root; it is `.gitignore`d (`*.pt`) and never committed. It's covered by Ultralytics' own model license terms (same AGPL-3.0/commercial choice as the library above), not by PeponBot's MIT license.
