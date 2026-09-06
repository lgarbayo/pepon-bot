# Pepón

Desktop robot: the phone provides camera, microphone, screen, speaker and sensors; the PC runs FastAPI, YOLO, Whisper and Gemma via Ollama.

## Starting it up

```sh
# In one terminal, if Ollama isn't already running:
ollama serve

# In another terminal:
cd /home/lgarbayo/pepon-bot/server
python3 main.py
```

Open `https://<LAN-IP>:8000` on the phone and accept the local certificate. `/debug` shows the camera, memory, voice, watches and pending notifications. The first tap unlocks the browser's audio.

## Conversation and controls

- Tap the orb to talk. The mic stays open for that session; each phrase ends after roughly **700ms of silence**, with no need to tap to send it. It keeps up to 420ms of audio from before speech onset. Phrases are capped at 20 seconds to bound memory and requests.
- The bars reflect the mic's real volume. The orb distinguishes listening, processing, replying and error. Replies are also shown as text.
- You can interrupt a reply by talking. Capture requests echo cancellation and requires louder, sustained speech while Pepón is talking. It's an adaptive energy-based detector: loud noise or residual echo can be mistaken for speech; this needs tuning/checking on the real Redmi.
- Tap again to end: it stops the mic tracks and the AudioContext, cancels the in-flight request and speech, and discards late replies. It also does this when the page is hidden or the WebSocket drops.
- The **PEPÓN** menu lets you toggle quiet mode and view/cancel watches. Quiet mode disables unprompted remarks; it keeps requested replies and notifications.

Capture uses [AudioWorklet](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor), processed locally, as mono WAV. Whisper is still the only transcriber; no audio is sent to an external service. The speaking animation reflects playback state: the browser doesn't expose `speechSynthesis` audio to the mic meter.

## Examples

| Feature | What you can say |
| --- | --- |
| Perception | "What do you see?", "Do you see a bottle?", "Find the book", "Look at me" |
| Cross-turn references | "Do you see a bottle?" → "Where is it?" → "Tell me when it disappears" |
| Visual memory | "Where did you last see my cup?" |
| Changes | "What's changed on the table?" |
| Watches | "Tell me when someone appears", "Watch for the cup coming back" |
| Return reminders | "Remind me to drink water when I get back" |
| Management | "What are you keeping an eye on", "Cancel the cup watches", "Cancel all watches" |
| Personality | "Quiet mode", "Sociable mode" |

The parser covers all **80 COCO classes**, their Spanish names and synonyms. Gemma receives up to 12 recent turns and the current visual state for other questions. The referent expires after five minutes of inactivity and resets when a new session starts.

## Conversation scope

Gemma is deliberately scoped to what Pepón perceives, not open-ended chit-chat. Its system prompt frames it as "the semantic reasoning module of Pepón" and requires every claim to be grounded in `visible_objects`/`memory`, with short, one-sentence answers. Tested directly against the running server:

| You say | Pepón answers |
| --- | --- |
| "¿Cómo estás?" (How are you?) | "Estoy bien, gracias por preguntar." — small talk works |
| "Cuéntame un chiste" (Tell me a joke) | "Lo siento, no puedo contar chistes en este momento." — declines |
| "¿Cuál es la capital de Francia?" (What's the capital of France?) | "Lo siento, no puedo responder preguntas sobre capitales de países." — declines |

This is a deliberate trade-off, not a bug: it keeps Pepón focused on being useful about the room instead of drifting into general trivia. Conversation history (up to 12 turns, 5-minute expiry) is used to follow up on questions about what it sees, not to hold an open-ended chat. Widening the system prompt to allow general conversation would be a small, deliberate change — intentionally left as-is for this project.

## Memory, watches and personality

- Visual memory retains up to 24 hours of recent observations, with side and age. On restart it's restored strictly as **past** observation, never as current visibility.
- Changes are confirmed over at least one second and three distinct detection frames. The comparison describes class changes and frame-position changes over the last minute.
- A stale camera, disconnect, camera switch or picking up the phone all reset the comparison; none of these are treated as objects having disappeared. If the phone keeps moving, the visual comparison can stay imprecise.
- Up to 32 one-shot watches for appearance, disappearance or return. They're persisted to disk and can be cancelled. Disappearance requires having seen the object during continuous observation; return requires a confirmed absence of at least three seconds before it reappears.
- Fulfilled notifications stay pending until played back and acknowledged from the phone. If the browser's audio isn't unlocked, an **ESCUCHAR AVISO** ("listen to notification") button appears. Detection requires the PC and camera to be active: it doesn't watch while they're off.
- In sociable mode it can greet you after an observed absence of at least 30 seconds and comment on being picked up. No more than one unprompted remark every two minutes; it never interrupts an ongoing voice turn.
- When it starts talking, its gaze turns toward the visible person and keeps tracking them. **It doesn't identify individual people or localize voices by direction**: the mono microphone can't reliably attribute who's speaking in a group. "When they get back" means a person reappears in frame.
- Memory and watches live in `data/companion.json`, gitignored. It's written via atomic replace; memory is saved roughly every ten seconds and on shutdown. Every interaction is still logged to `data/episodes/`.

Observations are per **class**, not identity: two cups aren't tracked as distinct personal objects. A past location belongs to that moment's framing; it doesn't establish where an out-of-frame object is now.

## Diagnostics and verification

- `GET /api/health`: status of local services.
- `GET /api/world`: memory, camera freshness and confirmed changes.
- `GET /api/voice/status`: transcript, errors, session state and the last semantic query's outcome (failure cause and latency).
- `GET /api/assistant`: preferences, watches and pending notifications.
- `POST /api/assistant/preferences`: `{"quiet": true}`.
- `DELETE /api/assistant/watches/{id}`: cancel a watch.
- `POST /api/assistant/notifications/{id}/ack`: acknowledge a notification.

```sh
python3 -m pytest server/tests -q
node static/tests/voice-vad.test.cjs
python3 static/tests/browser_checks.py
```

The last check needs Playwright and Chromium installed. It drives a real AudioWorklet with a synthetic signal and mocks HTTP, WebSocket and speech synthesis: it checks capture, WAV delivery, interruption, late permissions, mic release, errors, accessibility and screen sizes. It doesn't replace an acoustic test on the real Redmi, especially for echo and ambient noise.

Gemma queries get 20 seconds per request and 35 seconds total (`GEMMA_TIMEOUT_SECONDS`, `GEMMA_TOTAL_TIMEOUT_SECONDS`), to allow for vision cold-start. Service failures and timeouts are reported distinctly from "didn't understand the question"; `/debug` shows the technical detail.
