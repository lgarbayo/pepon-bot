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
let utteranceGeneration = 0;
let activeUtterance = null;
let audioUnlocked = false;

function stopSpeaking() {
  utteranceGeneration++;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  activeUtterance = null;
  isTalking = false;
  voiceNode?.port.postMessage({ type: 'speaking', value: false });
}

function speakText(text, onDone = null) {
  if (!text) return;
  document.getElementById('speech-caption').textContent = text;
  if (!('speechSynthesis' in window) || !audioUnlocked) {
    if (conversationActive) setVoiceState('error', 'TOCA PARA ACTIVAR EL AUDIO');
    return;
  }
  stopSpeaking();
  const generation = utteranceGeneration;
  const utterance = new SpeechSynthesisUtterance(text);
  activeUtterance = utterance; // keep alive until the browser completes TTS
  utterance.lang = 'es-ES';
  isTalking = true;
  voiceNode?.port.postMessage({ type: 'speaking', value: true });
  if (conversationActive) setVoiceState('speaking');
  utterance.onend = () => {
    if (generation !== utteranceGeneration) return;
    isTalking = false;
    activeUtterance = null;
    voiceNode?.port.postMessage({ type: 'speaking', value: false });
    if (conversationActive) setVoiceState('listening');
    if (onDone) onDone();
  };
  utterance.onerror = (event) => {
    if (generation !== utteranceGeneration) return;
    isTalking = false;
    activeUtterance = null;
    voiceNode?.port.postMessage({ type: 'speaking', value: false });
    setVoiceState('error', 'NO PUEDO REPRODUCIR LA VOZ');
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
      audioUnlocked = true;
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
    if (msg.session && (msg.session !== conversationSession || msg.turn !== voiceTurn || !conversationActive)) return;
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
    endConversation('SIN CONEXIÓN · VUELVE A TOCAR');
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
    currentFacingMode = stream.getVideoTracks()[0]?.getSettings().facingMode || facingMode;
    sendJSON({ type: 'camera_changed', facing: currentFacingMode });
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
  cameraSwitchBtn.addEventListener('click', async () => {
    cameraSwitchBtn.disabled = true;
    cameraSwitchBtn.setAttribute('aria-busy', 'true');
    try { await switchCamera(); }
    finally { cameraSwitchBtn.disabled = false; cameraSwitchBtn.removeAttribute('aria-busy'); }
  });
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

// ---------- Voice: local VAD, natural turns, interruption and cancellation ----------
const talkBtn = document.getElementById('talk-btn');
const talkHint = document.getElementById('talk-hint');
const voiceStatus = document.getElementById('voice-status');
let micStream = null;
let audioContext = null;
let micSource = null;
let voiceNode = null;
let conversationActive = false;
let conversationStarting = false;
let conversationSession = null;
let voiceTurn = 0;
let voiceState = 'idle';
let voiceGeneration = 0;
let voiceRequest = null;
let lastVoiceLevel = 0;

function setVoiceState(state, message = '') {
  voiceState = state;
  talkBtn.dataset.voiceState = state;
  talkBtn.classList.toggle('listening', conversationActive);
  talkBtn.setAttribute('aria-pressed', String(conversationActive));
  talkBtn.setAttribute('aria-label', conversationActive || conversationStarting ? 'Terminar conversación' : 'Hablar con Pepon');
  talkHint.textContent = conversationActive || conversationStarting ? 'TOCA PARA TERMINAR' : 'TOCA PARA HABLAR';
  const labels = { idle: '', starting: 'ABRIENDO MICRO', listening: 'TE ESCUCHO', capturing: 'TE ESCUCHO',
    processing: 'PENSANDO', speaking: 'HABLANDO', error: 'VUELVE A INTENTARLO' };
  voiceStatus.textContent = message || labels[state] || '';
  if (conversationSession) sendJSON({ type: 'voice_activity', session: conversationSession, turn: voiceTurn, state });
  if (state === 'capturing' || state === 'listening') Pepon.setState('listening');
  if (state === 'processing') Pepon.setState('thinking');
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true);
  write(8, 'WAVE'); write(12, 'fmt '); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, 'data'); view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, sample)) * (sample < 0 ? 32768 : 32767), true));
  return new Blob([buffer], { type: 'audio/wav' });
}

async function startConversation() {
  if (conversationActive || conversationStarting) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) { setVoiceState('error', 'SIN CONEXIÓN CON PEPÓN'); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext || !window.AudioWorkletNode) {
    setVoiceState('error', 'EL MICRO NECESITA HTTPS Y UN NAVEGADOR COMPATIBLE'); return;
  }
  conversationStarting = true;
  const generation = ++voiceGeneration;
  setVoiceState('starting');
  let stream = null;
  let context = null;
  try {
    // Resume within the tap, before waiting on microphone permission.
    context = new AudioContext({ sampleRate: 16000 });
    audioContext = context;
    await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
    } });
    if (generation !== voiceGeneration) { stream.getTracks().forEach(t => t.stop()); return; }
    micStream = stream;
    await context.audioWorklet.addModule('/static/voice-worklet.js');
    if (generation !== voiceGeneration) return;
    voiceNode = new AudioWorkletNode(context, 'pepon-voice');
    micSource = context.createMediaStreamSource(stream);
    micSource.connect(voiceNode);
    voiceNode.connect(context.destination);
    voiceNode.onprocessorerror = () => endConversation('ERROR DE AUDIO · VUELVE A TOCAR');
    stream.getAudioTracks()[0].onended = () => endConversation('MICRO DESCONECTADO');
    context.onstatechange = () => {
      if (conversationActive && context.state === 'suspended') endConversation('AUDIO EN PAUSA · VUELVE A TOCAR');
    };
    conversationSession = crypto.randomUUID();
    voiceTurn = 0;
    conversationActive = true;
    conversationStarting = false;
    sendJSON({ type: 'conversation', session: conversationSession, active: true });
    setVoiceState('listening');
    voiceNode.port.onmessage = ({ data }) => {
      if (!conversationActive || generation !== voiceGeneration) return;
      lastVoiceLevel = data.level;
      talkBtn.style.setProperty('--voice-level', Math.max(0.12, data.level).toFixed(3));
      if (data.started) {
        voiceRequest?.abort();
        voiceTurn++;
        stopSpeaking();
        setVoiceState('capturing');
      }
      if (data.segment) submitVoice(data.segment, context.sampleRate, generation, voiceTurn);
    };
  } catch (error) {
    if (generation !== voiceGeneration) return;
    const message = error.name === 'NotAllowedError' ? 'PERMITE EL MICRO Y VUELVE A TOCAR' : 'NO PUEDO ABRIR EL MICRO';
    sendJSON({ type: 'voice_error', error: `mic: ${error.message}` });
    endConversation(message);
  } finally {
    if (generation !== voiceGeneration) {
      stream?.getTracks().forEach(t => t.stop());
      if (context && context.state !== 'closed') await context.close().catch(() => {});
    }
  }
}

async function submitVoice(samples, sampleRate, generation, turn) {
  const controller = new AbortController();
  voiceRequest = controller;
  const session = conversationSession;
  setVoiceState('processing');
  const timeout = setTimeout(() => controller.abort('timeout'), 45000);
  try {
    const response = await fetch('/api/voice/audio', {
      method: 'POST', headers: { 'Content-Type': 'audio/wav', 'X-Conversation-ID': session, 'X-Turn-ID': String(turn) },
      body: encodeWav(samples, sampleRate), signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (generation !== voiceGeneration || turn !== voiceTurn) return;
    if (data.cancelled) { endConversation('SESIÓN FINALIZADA · VUELVE A TOCAR'); return; }
    if (data.transcript) console.log('[voice] heard:', data.transcript);
    if (!isTalking) setVoiceState('listening', data.transcript ? '' : 'NO TE HE ENTENDIDO · REPITE');
  } catch (error) {
    if (generation !== voiceGeneration || turn !== voiceTurn) return;
    // A failed request may still finish on the server: invalidate its turn.
    voiceTurn++;
    setVoiceState('error', error.name === 'AbortError' ? 'LA RESPUESTA TARDA · REPITE' : 'ERROR DE CONEXIÓN · REPITE');
    sendJSON({ type: 'voice_error', error: `conversation: ${error.message}` });
  } finally {
    clearTimeout(timeout);
    if (voiceRequest === controller) voiceRequest = null;
  }
}

function endConversation(message = '') {
  voiceGeneration++;
  conversationStarting = false;
  conversationActive = false;
  voiceRequest?.abort();
  voiceRequest = null;
  stopSpeaking();
  if (conversationSession) sendJSON({ type: 'conversation', session: conversationSession, active: false });
  conversationSession = null;
  if (voiceNode) { voiceNode.port.onmessage = null; voiceNode.disconnect(); voiceNode = null; }
  if (micSource) { micSource.disconnect(); micSource = null; }
  micStream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
  micStream = null;
  if (audioContext) { audioContext.onstatechange = null; audioContext.close().catch(() => {}); audioContext = null; }
  talkBtn.style.setProperty('--voice-level', '0.12');
  Pepon.setState('idle');
  setVoiceState(message ? 'error' : 'idle', message);
}

talkBtn.addEventListener('click', () => {
  audioUnlocked = true;
  if (conversationActive || conversationStarting) endConversation();
  else startConversation();
});
window.addEventListener('pagehide', () => endConversation());
document.addEventListener('visibilitychange', () => { if (document.hidden) endConversation(); });

// Persistent errands and quiet mode. Notices wait until audio has been
// unlocked and no user turn is being captured/processed/spoken.
let assistantState = { quiet: false, watches: [], notifications: [] };
let activeNotice = null;
const completedNotices = new Set();
const quietToggle = document.getElementById('quiet-toggle');
const noticeButton = document.getElementById('notice-btn');

async function refreshAssistant() {
  try {
    const response = await fetch('/api/assistant');
    if (!response.ok) return;
    assistantState = await response.json();
    quietToggle.checked = assistantState.quiet;
    const list = document.getElementById('watch-list');
    list.replaceChildren();
    document.getElementById('watch-count').textContent = `${assistantState.watches.length} ENCARGOS`;
    for (const watch of assistantState.watches) {
      const item = document.createElement('li');
      const description = document.createElement('span');
      description.textContent = watch.label || watch.object;
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.textContent = '×';
      cancel.setAttribute('aria-label', `Cancelar: ${description.textContent}`);
      cancel.onclick = async () => {
        try {
          const result = await fetch(`/api/assistant/watches/${watch.id}`, { method: 'DELETE' });
          if (!result.ok) throw new Error('cancel');
          refreshAssistant();
        } catch { voiceStatus.textContent = 'NO SE HA PODIDO CANCELAR'; }
      };
      item.append(description, cancel); list.append(item);
    }
    if (!assistantState.watches.length) {
      const item = document.createElement('li'); item.textContent = 'SIN ENCARGOS PENDIENTES'; list.append(item);
    }
    playNextNotice();
  } catch { /* WebSocket handles the connection indicator. */ }
}

function playNextNotice() {
  const pending = assistantState.notifications.filter(n => !completedNotices.has(n.id) &&
    (n.kind !== 'social' || (!assistantState.quiet && Date.now() / 1000 - n.at < 20)));
  noticeButton.hidden = !pending.length;
  noticeButton.textContent = pending.length ? `ESCUCHAR AVISO (${pending.length})` : '';
  if (activeNotice && !isTalking) activeNotice = null; // interrupted: keep pending
  if (!audioUnlocked || isTalking || activeNotice || document.hidden || ['capturing', 'processing', 'starting'].includes(voiceState)) return;
  const notice = pending[0];
  if (!notice) return;
  activeNotice = notice.id;
  speakText(notice.text, async () => {
    activeNotice = null;
    completedNotices.add(notice.id);
    try {
      const response = await fetch(`/api/assistant/notifications/${notice.id}/ack`, { method: 'POST' });
      if (!response.ok) completedNotices.delete(notice.id);
    } catch { completedNotices.delete(notice.id); }
    refreshAssistant();
  });
}

quietToggle.addEventListener('change', async () => {
  quietToggle.disabled = true;
  try {
    const response = await fetch('/api/assistant/preferences', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ quiet: quietToggle.checked }),
    });
    if (!response.ok) throw new Error('preferences');
    await refreshAssistant();
  } catch { quietToggle.checked = assistantState.quiet; voiceStatus.textContent = 'NO SE HA PODIDO GUARDAR'; }
  finally { quietToggle.disabled = false; }
});
noticeButton.addEventListener('click', () => { audioUnlocked = true; playNextNotice(); });
setInterval(refreshAssistant, 3000);
refreshAssistant();
