# Architecture decisions

A lightweight log of the real trial-and-error behind PeponBot, in the order it happened, written honestly — including the dead ends. Each entry is a short ADR: context, decision, consequences. New entries go at the bottom, oldest first, so this reads as a history.

## 1. Phone as body, PC as brain, over WebSocket + HTTPS

**Context**: we wanted a physically embodied assistant without buying robot hardware — an old Android phone already has a camera, microphone, speaker, screen and motion sensors.

**Decision**: the phone runs nothing but a browser page; every sensor reading goes to a FastAPI backend on the PC over a WebSocket, and every action (look, speak, show an expression) comes back the same way. HTTPS with a locally-generated self-signed certificate, because `getUserMedia`/`AudioWorklet` require a secure context.

**Consequences**: zero app install on the phone, but the phone and PC must share a network, and the self-signed certificate needs one manual "accept the warning" per device. There is currently no authentication — acceptable for a same-Wi-Fi personal project, explicitly flagged as a limitation in `SECURITY.md` and not something to expose publicly as-is.

## 2. Perception and detection stay off the LLM's hot path

**Context**: object detection runs every ~250ms; calling an LLM at that rate would be far too slow and unnecessary for most commands.

**Decision**: YOLOv8n runs locally on every frame into `WorldState`. A fast deterministic parser (`intent.py`) handles the common questions instantly, matching against `WorldState` directly — no LLM involved. `GemmaAgent` (a local LLM via Ollama) is called at most once per voice command, and only when the deterministic parser found no match.

**Consequences**: instant responses for the common case, and Gemma's ~0.3–1s latency is only paid for the questions that actually need reasoning. The deterministic parser initially covered only 6 object classes; this was later expanded to the full 80-class COCO vocabulary once it became clear most objects didn't need an LLM to answer "where is X", just more vocabulary.

## 3. Grounding Gemma strictly in WorldState (and the bug that justified it)

**Context**: an early version let Gemma answer freely from a compact `WorldState` snapshot. It was tempting to let it also reason a bit more loosely to sound more natural.

**Decision**: `GemmaAgent`'s system prompt requires every claim to reference `visible_objects` or `memory`; its output is JSON-schema-constrained (`target` is an enum of exactly the currently-known object classes), validated again after generation, and retried once on malformed output before falling back to a safe `SPEAK`.

**Consequences, and a real bug this caught**: once persistent 24h memory was added (decision 5), a single misdetected YOLO frame (e.g. a "vase" that was never really there) got written into `WorldState` immediately and, being now visible to Gemma as "known", was cited back across an entire conversation as if real — including once the object had left frame and only "memory" of it remained. The fix (`ObjectMemory.confirmed`) reuses the *same* stability check already built for confirmed scene changes (a class must survive 3+ consecutive detection frames spanning ≥1s) before `GemmaAgent` is told about it at all. Fast deterministic answers were deliberately left unaffected — a one-off error there self-corrects on the very next frame, so the risk profile is different from something Gemma can repeat back as an established fact minutes or hours later.

## 4. Voice input: three iterations, in order

1. **Web Speech API** (`SpeechRecognition`): simplest to build, but Chromium-only (no Firefox/Safari) and triggers Android's OS-level "mic active" beep on every start/stop cycle — jarring for a supposedly natural conversation.
2. **`faster-whisper`, fixed-length recording chunks**: solved both problems (works in any browser via plain `getUserMedia`/`MediaRecorder`, no repeated mic start/stop) but cut sentences at arbitrary 4-second boundaries and needed a manual stop.
3. **`faster-whisper` + `AudioWorklet`-based capture with silence-based turn-ending**: the current approach. Continuous listening, a phrase ends on ~700ms of silence rather than a fixed duration or a manual stop, with a short pre-roll so the very start of speech isn't clipped, and energy-based barge-in so talking over a reply interrupts it.

**Consequences**: `faster-whisper`'s CUDA path needs the CUDA 12 ABI specifically (`nvidia-cublas-cu12`/`nvidia-cudnn-cu12`) — installing only newer CUDA 13 packages (already present on the dev machine for something else) produced `libcublas.so.12 not found` at first transcription, not at model load, which made it a confusing bug to chase down. Barge-in is energy-based, not real echo cancellation beyond the browser's own `echoCancellation` constraint — it's the most fragile part of the voice pipeline and needs real-device tuning for loud rooms or residual echo.

## 5. Memory: from "forget in 2 minutes" to "remember for a day"

**Context**: the original `WorldState` only tracked the *current* detection cycle, forgetting anything not seen for 120 seconds — enough to answer "where's the bottle?" a moment after it left frame, not enough to answer it an hour later.

**Decision**: extended to 24h retention, restored strictly as *past* observation on restart (never as current visibility), plus a `Companion` layer for one-shot watches ("tell me when X appears/disappears/comes back") and return reminders, persisted to `data/companion.json` via atomic writes.

**Consequences**: this is what made the bug in decision 3 possible — a false detection that would have self-corrected in 2 minutes now persisted for a full day. The fix wasn't to shorten the memory window back down (that would have thrown away the actual feature), but to require confirmation before anything enters memory as fact in the first place.

## 6. Ollama's default model registry was unreachable

**Context**: `ollama pull gemma3:4b` hung/timed out on the development network.

**Decision**: diagnosed via direct `curl` to Ollama's blob host (Cloudflare R2) — confirmed unreachable independent of Ollama itself (same failure with an unrelated model), while `ollama.com` and `huggingface.co` were both reachable. Switched the default `OLLAMA_MODEL` to Ollama's HuggingFace passthrough tag (`hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M`) — same weights, different CDN.

**Consequences**: works around a specific network's blocklist rather than fixing anything in PeponBot itself; anyone hitting the same block on their own network should try the same workaround, documented in the README's troubleshooting section.

## 7. Conversation scope: grounded assistant, not a general chatbot

**Context**: it's tempting to let a capable local LLM answer *anything* — jokes, trivia, general chit-chat — since the model underneath can.

**Decision**: deliberately left the system prompt scoped to what Pepón perceives. Tested directly: small talk ("¿cómo estás?") works, but general trivia ("cuéntame un chiste", "¿cuál es la capital de Francia?") is politely declined by design.

**Consequences**: Pepón stays focused and predictable as a room-aware assistant instead of drifting into an unbounded chatbot persona, at the cost of not being useful for open-ended conversation. Documented as an intentional trade-off in the README rather than treated as a gap to close.

## 8. Not deployed beyond the local network (for now)

**Context**: asked whether this should be deployed somewhere reachable from outside the house.

**Decision**: left as a local-network application. The three realistic options considered were (a) stay local, optionally with mDNS/`systemd` for convenience, (b) reach it remotely over a private mesh VPN (e.g. Tailscale) without exposing it publicly, or (c) genuinely deploy it publicly, which would require moving YOLO/Whisper/Gemma to a GPU cloud instance, a real TLS certificate, and — critically — adding authentication, since the server currently has none (see `SECURITY.md`).

**Consequences**: none of the three has been implemented; this entry exists so the trade-off is visible if/when it comes up again, rather than re-deriving it from scratch.
