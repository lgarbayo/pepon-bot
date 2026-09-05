// ---------- Pepon's virtual eyes ----------
// Frontend API: Pepon.setState(name), Pepon.lookAt(x, y), Pepon.blink()
// x/y are normalized to [-1, 1] (left/up = -1, right/down = 1).

const VALID_STATES = ['idle', 'listening', 'thinking', 'searching', 'found', 'confused', 'surprised'];
const POP_STATES = ['found', 'surprised']; // states with a one-shot startled entrance
const MAX_GAZE_OFFSET_PX = 30; // how far pupils can travel from eye center

const face = document.getElementById('face');
const stateLabel = document.getElementById('state-label');
const eyes = [document.getElementById('eye-left'), document.getElementById('eye-right')];
const eyeInners = eyes.map((eye) => eye.querySelector('.eye-inner'));
const dizzyWraps = eyes.map((eye) => eye.querySelector('.dizzy-wrap'));
const pupilWraps = eyes.map((eye) => eye.querySelector('.pupil-wrap'));

eyeInners.forEach((el) => {
  el.addEventListener('animationend', () => el.classList.remove('blinking'));
});
dizzyWraps.forEach((el) => {
  el.addEventListener('animationend', () => el.classList.remove('dizzy'));
});
eyes.forEach((eye) => {
  eye.addEventListener('animationend', () => eye.classList.remove('pop'));
});

let currentState = 'idle';
let manualGaze = null; // set by an explicit lookAt() call; overrides auto motion
let lastBlinkAt = 0;
let nextBlinkDelay = randomBlinkDelay();

// Driven by speakText() below. Deliberately NOT a Pepon.setState() —
// talking is an overlay on top of whatever expression is already active
// (e.g. still looking at a just-found bottle while announcing it), not a
// state swap, so it must never touch currentState/manualGaze/face.className.
let isTalking = false;
let wasTalking = false;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function randomBlinkDelay() {
  return 2200 + Math.random() * 2600;
}

function applyGaze(x, y) {
  const px = clamp(x, -1, 1) * MAX_GAZE_OFFSET_PX;
  const py = clamp(y, -1, 1) * MAX_GAZE_OFFSET_PX;
  pupilWraps.forEach((wrap) => {
    wrap.style.transform = `translate(${px}px, ${py}px)`;
  });
}

function setState(name) {
  const state = String(name).toLowerCase();
  if (!VALID_STATES.includes(state)) {
    console.warn('Pepon.setState: unknown state', name);
    return;
  }
  currentState = state;
  manualGaze = null; // fresh state starts from its own default gaze/motion
  face.className = `state-${state}`;
  stateLabel.textContent = state.toUpperCase();

  if (POP_STATES.includes(state)) {
    eyes.forEach((eye) => {
      eye.classList.remove('pop');
      void eye.offsetWidth; // restart animation even if triggered twice quickly
      eye.classList.add('pop');
    });
  }
}

function lookAt(x, y) {
  manualGaze = { x: Number(x), y: Number(y) };
  applyGaze(manualGaze.x, manualGaze.y);
}

function blink() {
  eyeInners.forEach((el) => {
    el.classList.remove('blinking');
    void el.offsetWidth; // restart animation even if triggered twice quickly
    el.classList.add('blinking');
  });
  lastBlinkAt = performance.now();
  nextBlinkDelay = randomBlinkDelay();
}

function dizzy() {
  dizzyWraps.forEach((el) => {
    el.classList.remove('dizzy');
    void el.offsetWidth; // restart animation even if triggered twice quickly
    el.classList.add('dizzy');
  });
}

// Automatic idle motion per state (only runs while no explicit lookAt()
// is in effect for the current state) + automatic blinking in any state.
function tick(timestamp) {
  if (!manualGaze) {
    const t = timestamp / 1000;
    switch (currentState) {
      case 'thinking':
        applyGaze(Math.sin(t * 2) * 0.5, 0);
        break;
      case 'searching':
        applyGaze(Math.sin(t * 1.2) * 0.8, Math.sin(t * 0.6) * 0.15);
        break;
      case 'confused':
        applyGaze(Math.sin(t * 9) * 0.12, Math.cos(t * 7) * 0.08);
        break;
      default:
        applyGaze(0, 0);
    }
  }

  if (timestamp - lastBlinkAt > nextBlinkDelay) {
    blink();
  }

  // Talking indicator: a gentle brightness pulse driven straight via
  // inline style (not a CSS class/keyframe), so it can never collide
  // with the per-state `animation`/`transform` rules on these same
  // elements (e.g. CONFUSED's wiggle, FOUND's pop) — see isTalking above.
  if (isTalking) {
    const pulse = 1 + Math.sin(timestamp / 90) * 0.25;
    eyes.forEach((eye) => { eye.style.filter = `brightness(${pulse})`; });
  } else if (wasTalking) {
    eyes.forEach((eye) => { eye.style.filter = ''; });
  }
  wasTalking = isTalking;

  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

window.Pepon = { setState, lookAt, blink, dizzy };

// ---------- WebSocket link ----------

const statusBar = document.getElementById('status-bar');
const statusText = document.getElementById('status-text');

let ws;
let reconnectDelay = 1000;

// SPEAK action rendering — plain Web Speech API TTS, no server-side
// speech synthesis needed. The backend decided WHAT to say; everything
// here is purely HOW: pick a voice engine and show a "talking" cue
// while it plays, on top of whatever expression is already showing
// (e.g. Pepon stays looking at a just-found bottle while announcing
// it — see the isTalking comment above tick()).
function speakText(text) {
  if (!('speechSynthesis' in window) || !text) return;
  speechSynthesis.cancel(); // don't queue behind a stale utterance
  isTalking = false; // cancel() doesn't reliably fire onend on the interrupted utterance

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'es-ES'; // Agent's spoken responses are Spanish now
  utterance.onstart = () => { isTalking = true; };
  utterance.onend = () => { isTalking = false; };
  utterance.onerror = (event) => {
    isTalking = false;
    // e.g. "not-allowed" if this fires before any real tap on the page —
    // Chrome/Android mute speechSynthesis until user activation, which
    // hands-free voice (no click involved) never provides on its own.
    console.error('[speak] synthesis error:', event.error);
    sendJSON({ type: 'voice_error', error: `speak: ${event.error}` });
  };
  speechSynthesis.speak(utterance);
}

// Android Chrome sometimes has no voices loaded yet on first use, and
// separately mutes speechSynthesis entirely until the page has real
// user activation (a tap), which hands-free voice never provides on
// its own. Priming both here means the FIRST tap anywhere on the page
// (opening it, granting mic permission, tapping the talk button, ...)
// is enough to unlock spoken responses for the rest of the session —
// without this, LOOK_AT/ANSWER_LOCATION/etc. still execute silently.
if ('speechSynthesis' in window) {
  speechSynthesis.getVoices();
  speechSynthesis.onvoiceschanged = () => speechSynthesis.getVoices();
  document.body.addEventListener(
    'pointerdown',
    () => {
      const unlock = new SpeechSynthesisUtterance('');
      unlock.volume = 0;
      speechSynthesis.speak(unlock);
    },
    { once: true }
  );
}

function sendJSON(obj) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify(obj));
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    statusBar.classList.remove('disconnected');
    statusBar.classList.add('connected');
    statusText.textContent = 'CONNECTED';
    reconnectDelay = 1000;
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case 'state':
        Pepon.setState(msg.value);
        break;
      case 'look_at':
        Pepon.lookAt(msg.x, msg.y);
        break;
      case 'blink':
        Pepon.blink();
        break;
      case 'detections':
        console.log('[detections]', msg.objects);
        break;
      case 'dizzy':
        Pepon.dizzy();
        break;
      case 'motion_event':
        console.log('[motion]', msg.event);
        break;
      case 'speak':
        speakText(msg.text);
        break;
      case 'alert':
        console.warn('[ALERT]', msg.reason);
        break;
    }
  };

  ws.onclose = () => {
    statusBar.classList.remove('connected');
    statusBar.classList.add('disconnected');
    statusText.textContent = 'DISCONNECTED';
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  setTimeout(connect, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
}

connect();

// ---------- Camera streaming ----------
// Captures the phone camera and streams JPEG frames to the backend as
// binary WebSocket messages. Low latency > image quality: modest
// resolution/fps/quality are enough for object detection, not for a
// photo. Requires a secure context (https or localhost) for getUserMedia.

const CAMERA_WIDTH = 640;
const CAMERA_HEIGHT = 480;
const CAMERA_FPS = 10;
const JPEG_QUALITY = 0.6;

const captureCanvas = document.createElement('canvas');
captureCanvas.width = CAMERA_WIDTH;
captureCanvas.height = CAMERA_HEIGHT;
const captureCtx = captureCanvas.getContext('2d', { willReadFrequently: true });
let cameraVideo = null;
let cameraStream = null;
let frameInFlight = false;

// 'user' = front/selfie camera (primary — lets Pepon and the person see
// each other), 'environment' = rear camera. sendFrame's interval is
// started once and just keeps reading from whatever cameraVideo/stream
// switchCamera() last swapped in, so switching never stacks intervals.
let currentFacingMode = 'user';

async function startCamera(facingMode = currentFacingMode) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    console.warn('getUserMedia unavailable (needs https or localhost)');
    return false;
  }

  // Release whatever camera is currently active BEFORE requesting a new
  // one — most Android devices only allow one open camera session at a
  // time, so asking for the rear camera while the front one is still
  // active can silently hand back the same front stream again instead
  // of erroring, which is why switching looked like a no-op.
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }

  const videoBase = { width: { ideal: CAMERA_WIDTH }, height: { ideal: CAMERA_HEIGHT } };
  let stream;
  try {
    // Forced exact facing mode — a plain facingMode string is only a hint
    // and some devices/browsers ignore it and fall back to the wrong camera.
    stream = await navigator.mediaDevices.getUserMedia({
      video: { ...videoBase, facingMode: { exact: facingMode } },
      audio: false,
    });
  } catch (err) {
    console.warn(`Exact ${facingMode} camera unavailable, falling back to any camera:`, err);
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { ...videoBase, facingMode },
        audio: false,
      });
    } catch (err2) {
      console.error('Camera unavailable:', err2);
      return false;
    }
  }

  try {
    cameraStream = stream;
    currentFacingMode = facingMode;
    if (!cameraVideo) {
      cameraVideo = document.createElement('video');
      cameraVideo.playsInline = true;
      cameraVideo.muted = true;
      setInterval(sendFrame, 1000 / CAMERA_FPS); // started once, on first successful camera
    }
    cameraVideo.srcObject = stream;
    await cameraVideo.play();
    return true;
  } catch (err) {
    console.error('Camera unavailable:', err);
    return false;
  }
}

async function switchCamera() {
  const next = currentFacingMode === 'user' ? 'environment' : 'user';
  const ok = await startCamera(next);
  if (!ok) {
    console.warn(`Switching to ${next} camera failed, staying on ${currentFacingMode}`);
    await startCamera(currentFacingMode); // best-effort: recover the camera we still had
  }
}

function sendFrame() {
  if (!cameraVideo || cameraVideo.readyState < 2) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (frameInFlight) return; // drop this tick if the previous frame hasn't finished encoding
  frameInFlight = true;
  captureCtx.drawImage(cameraVideo, 0, 0, CAMERA_WIDTH, CAMERA_HEIGHT);
  captureCanvas.toBlob(
    (blob) => {
      frameInFlight = false;
      if (blob && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(blob);
      }
    },
    'image/jpeg',
    JPEG_QUALITY
  );
}

startCamera();

const cameraSwitchBtn = document.getElementById('camera-switch-btn');
if (cameraSwitchBtn) {
  cameraSwitchBtn.addEventListener('click', switchCamera);
}

// ---------- Proprioception (motion sensors) ----------
// Reads accelerometer (via DeviceMotionEvent) and orientation (via
// DeviceOrientationEvent) and forwards raw samples to the backend as
// JSON WebSocket text messages, throttled well below their native
// firing rate. The backend turns these into PHONE_* events — this
// side just degrades gracefully when a sensor/permission is missing.

const MOTION_SEND_INTERVAL_MS = 100; // ~10Hz: plenty for threshold detection

let latestAccelGravity = null; // {x,y,z} m/s^2, includes gravity — broadly supported
let latestOrientation = null; // {alpha,beta,gamma} degrees

function handleDeviceMotion(event) {
  const g = event.accelerationIncludingGravity;
  if (g && g.x !== null && g.y !== null && g.z !== null) {
    latestAccelGravity = { x: g.x, y: g.y, z: g.z };
  }
}

function handleDeviceOrientation(event) {
  if (event.beta !== null && event.gamma !== null) {
    latestOrientation = { alpha: event.alpha, beta: event.beta, gamma: event.gamma };
  }
}

async function startMotionSensors() {
  // iOS 13+ Safari requires an explicit user-gesture permission prompt;
  // Android Chrome exposes no such API and just needs a secure context.
  const needsIOSPermission =
    typeof DeviceMotionEvent !== 'undefined' &&
    typeof DeviceMotionEvent.requestPermission === 'function';

  if (needsIOSPermission) {
    try {
      const result = await DeviceMotionEvent.requestPermission();
      if (result !== 'granted') {
        console.warn('Motion sensor permission denied');
        return;
      }
      if (typeof DeviceOrientationEvent.requestPermission === 'function') {
        await DeviceOrientationEvent.requestPermission();
      }
    } catch (err) {
      console.warn('Motion sensor permission request failed:', err);
      return;
    }
  }

  if (typeof DeviceMotionEvent !== 'undefined') {
    window.addEventListener('devicemotion', handleDeviceMotion);
  } else {
    console.warn('DeviceMotionEvent unsupported on this browser');
  }

  if (typeof DeviceOrientationEvent !== 'undefined') {
    window.addEventListener('deviceorientation', handleDeviceOrientation);
  } else {
    console.warn('DeviceOrientationEvent unsupported on this browser');
  }

  setInterval(sendMotionSample, MOTION_SEND_INTERVAL_MS);
}

function sendMotionSample() {
  if (!latestAccelGravity && !latestOrientation) return; // nothing to report yet
  sendJSON({ type: 'motion', accel_gravity: latestAccelGravity, orientation: latestOrientation });
}

// iOS needs this triggered from a user gesture; a tap anywhere on the
// page satisfies that without adding a dedicated permission button.
if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
  document.body.addEventListener('click', startMotionSensors, { once: true });
} else {
  startMotionSensors();
}

// ---------- Voice interaction (Siri-style conversation button) ----------
// STT runs entirely on the backend via Whisper (SpeechService) — the
// phone only captures audio (getUserMedia + MediaRecorder, supported
// on any browser, unlike Chrome-only SpeechRecognition).
//
// One button, one gesture: tap to start a conversation, tap again to
// end it. While active, Pepon keeps listening in rolling CHUNK_MS clips
// and treats each one as a command directly — no wake word, no per-turn
// "stop recording" step, since tapping the button already is the "I'm
// talking to you" signal, same as pressing Siri's mic once and just
// talking. This single deliberate tap is also what unlocks
// speechSynthesis (browsers mute it until a real user gesture happens
// on the page), so it's the one thing this whole app ever asks you to
// physically touch.
const CHUNK_MS = 4000; // resolution of turn-taking while a conversation is active

const RECORDING_MIME_TYPE = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4', // Safari
].find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type));

let micStream = null;
let conversationActive = false;

async function ensureMicStream() {
  if (micStream) return micStream;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return null;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    return micStream;
  } catch (err) {
    console.error('[voice] mic permission denied:', err);
    sendJSON({ type: 'voice_error', error: `mic: ${err.message}` });
    return null;
  }
}

// Records exactly one clip on the given (shared, already-open) stream.
function recordClip(stream, durationMs) {
  return new Promise((resolve) => {
    const chunks = [];
    const rec = RECORDING_MIME_TYPE
      ? new MediaRecorder(stream, { mimeType: RECORDING_MIME_TYPE })
      : new MediaRecorder(stream);
    rec.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    rec.onstop = () => resolve(new Blob(chunks, { type: rec.mimeType }));
    rec.start();
    setTimeout(() => {
      if (rec.state === 'recording') rec.stop();
    }, durationMs);
  });
}

// Waits out any window where Pepon is currently speaking, so a
// continuous conversation doesn't pick up its own voice and re-feed it
// back in as if the person had said it (a real risk once there's no
// wake word gating each turn).
function waitWhileTalking() {
  return new Promise((resolve) => {
    (function poll() {
      if (!isTalking) return resolve();
      setTimeout(poll, 150);
    })();
  });
}

const talkBtn = document.getElementById('talk-btn');
talkBtn.addEventListener('click', toggleConversation);

function toggleConversation() {
  if (conversationActive) {
    endConversation();
  } else {
    startConversation();
  }
}

async function startConversation() {
  if (!window.MediaRecorder) {
    sendJSON({ type: 'voice_error', error: 'conversation unsupported' });
    return;
  }
  const stream = await ensureMicStream();
  if (!stream) return;

  // The tap that got us here is real user activation — arm speech
  // synthesis now, before Pepon's first reply ever needs it.
  if ('speechSynthesis' in window) {
    const unlock = new SpeechSynthesisUtterance('');
    unlock.volume = 0;
    speechSynthesis.speak(unlock);
  }

  conversationActive = true;
  talkBtn.classList.add('listening');
  conversationLoop(stream);
}

function endConversation() {
  conversationActive = false;
  talkBtn.classList.remove('listening');
}

async function conversationLoop(stream) {
  while (conversationActive) {
    await waitWhileTalking();
    if (!conversationActive) break;

    sendJSON({ type: 'wake_word' }); // LISTENING feedback for this turn
    const blob = await recordClip(stream, CHUNK_MS);
    if (!conversationActive) break;

    try {
      // Straight to the full pipeline — being in an active conversation
      // already means "this is a command", same as push-to-talk used to.
      const res = await fetch('/api/voice/audio', {
        method: 'POST',
        headers: { 'Content-Type': blob.type },
        body: blob,
      });
      const data = await res.json();
      if (data.transcript) console.log('[voice] heard:', data.transcript);
    } catch (err) {
      console.error('[voice] conversation turn failed:', err);
      sendJSON({ type: 'voice_error', error: `conversation: ${err.message}` });
    }
  }
}
