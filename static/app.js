// ---------- Pepon's virtual eyes ----------
// Frontend API: Pepon.setState(name), Pepon.lookAt(x, y), Pepon.blink()
// x/y are normalized to [-1, 1] (left/up = -1, right/down = 1).

const VALID_STATES = ['idle', 'listening', 'thinking', 'searching', 'found', 'confused'];
const MAX_GAZE_OFFSET_PX = 30; // how far pupils can travel from eye center

const face = document.getElementById('face');
const stateLabel = document.getElementById('state-label');
const eyes = [document.getElementById('eye-left'), document.getElementById('eye-right')];
const eyeInners = eyes.map((eye) => eye.querySelector('.eye-inner'));
const pupilWraps = eyes.map((eye) => eye.querySelector('.pupil-wrap'));

eyeInners.forEach((el) => {
  el.addEventListener('animationend', () => el.classList.remove('blinking'));
});
eyes.forEach((eye) => {
  eye.addEventListener('animationend', () => eye.classList.remove('pop'));
});

let currentState = 'idle';
let manualGaze = null; // set by an explicit lookAt() call; overrides auto motion
let lastBlinkAt = 0;
let nextBlinkDelay = randomBlinkDelay();

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

  if (state === 'found') {
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

  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

window.Pepon = { setState, lookAt, blink };

// ---------- WebSocket link ----------

const statusBar = document.getElementById('status-bar');
const statusText = document.getElementById('status-text');

let ws;
let reconnectDelay = 1000;

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
