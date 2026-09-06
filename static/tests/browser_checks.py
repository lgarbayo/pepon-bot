# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""Headless UI integration with real AudioWorklet and synthetic microphone.
Run from repository root: python3 static/tests/browser_checks.py
No GPU models or physical recording; HTTP/WS/TTS are controlled fixtures.
"""
import io
import json
from pathlib import Path
import wave
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
INIT = r'''
window.fixture = { sent: [], streams: [], contexts: [], cancelled: 0, deny: false, delay: 0 };
class Socket {
  static OPEN = 1;
  constructor() { this.readyState = 1; window.fixture.socket = this; setTimeout(() => this.onopen?.(), 0); }
  send(data) { if (typeof data === 'string') fixture.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
}
window.WebSocket = Socket;
Object.defineProperty(window, 'speechSynthesis', { value: {
  cancel() { fixture.cancelled++; }, getVoices() { return []; },
  speak(utterance) { fixture.utterance = utterance; utterance.onstart?.(); },
} });
Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async (constraints) => {
  if (!constraints.audio) throw new Error('No camera in browser fixture');
  if (fixture.deny) throw new DOMException('Denied', 'NotAllowedError');
  const ctx = new AudioContext({ sampleRate: 16000 }); await ctx.resume();
  const oscillator = ctx.createOscillator(); oscillator.frequency.value = 220;
  const gain = ctx.createGain(); gain.gain.value = 0;
  const destination = ctx.createMediaStreamDestination();
  oscillator.connect(gain); gain.connect(destination); oscillator.start();
  fixture.gain = gain; fixture.streams.push(destination.stream); fixture.contexts.push(ctx);
  if (fixture.delay) await new Promise(resolve => setTimeout(resolve, fixture.delay));
  return destination.stream;
} });
'''

class Assets(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Assets)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f'http://localhost:{server.server_port}/'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
    page = browser.new_page(viewport={'width': 393, 'height': 851})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: print('BROWSER:', message.type, message.text, flush=True) if message.type == 'error' else None)
    page.on('requestfailed', lambda request: print('REQUEST FAILED:', request.url, request.failure, flush=True))
    page.add_init_script(INIT)
    page.route('https://fonts.googleapis.com/**', lambda route: route.fulfill(body='', content_type='text/css'))
    def static(route):
        name = route.request.url.split('/static/', 1)[1]
        path = ROOT / 'static' / name
        route.fulfill(path=path, content_type='text/css' if name.endswith('.css') else 'application/javascript')
    page.route('**/static/**', static)
    page.route(BASE, lambda route: route.fulfill(path=ROOT / 'static/index.html', content_type='text/html'))
    assistant = {'quiet': False, 'watches': [], 'notifications': []}
    page.route('**/api/assistant', lambda route: route.fulfill(json=assistant))
    def prefs(route):
        assistant.update(route.request.post_data_json)
        route.fulfill(json=assistant)
    page.route('**/api/assistant/preferences', prefs)
    clips = []
    def audio(route):
        raw = route.request.post_data_buffer
        with wave.open(io.BytesIO(raw)) as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == 16000
            assert wav.getnframes() > 8000
        clips.append(raw)
        session = route.request.headers['x-conversation-id']
        turn = int(route.request.headers['x-turn-id'])
        route.fulfill(json={'transcript': '¿Ves una botella?', 'response': 'Veo la botella.'})
        page.evaluate('(message) => fixture.socket.onmessage({ data: JSON.stringify(message) })',
                      {'type': 'speak', 'text': 'Veo la botella.', 'session': session, 'turn': turn})
    page.route('**/api/voice/audio', audio)
    page.goto(BASE)
    page.get_by_role('button', name='Hablar con Pepon', exact=True).click()
    page.wait_for_function("voiceState === 'listening' || voiceState === 'error'")
    assert page.evaluate('voiceState') == 'listening', page.evaluate('({state:voiceState, status:voiceStatus.textContent, sent:fixture.sent})')
    page.wait_for_timeout(300)
    assert not clips
    page.evaluate('fixture.gain.gain.value = .2')
    page.wait_for_function("voiceState === 'capturing'")
    assert float(page.locator('#talk-btn').evaluate("el => el.style.getPropertyValue('--voice-level')")) > .1
    page.wait_for_timeout(500)
    page.evaluate('fixture.gain.gain.value = 0')
    page.wait_for_function("voiceState === 'speaking'")
    assert len(clips) == 1
    page.screenshot(path='/tmp/pepon-natural-speaking.png')
    cancelled = page.evaluate('fixture.cancelled')
    page.evaluate('fixture.gain.gain.value = .2')
    page.wait_for_function("voiceState === 'capturing'")
    assert page.evaluate('fixture.cancelled') > cancelled
    assert page.evaluate('voiceTurn') == 2
    page.evaluate('fixture.gain.gain.value = 0')
    page.wait_for_function("voiceState === 'speaking'")
    page.evaluate('fixture.utterance.onend()')
    assert page.evaluate('voiceState') == 'listening'
    assert page.locator('#state-label').inner_text() == 'LISTENING'
    page.get_by_role('button', name='Terminar conversación', exact=True).click()
    page.wait_for_function("micStream === null && audioContext === null")
    assert page.evaluate("fixture.streams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")
    assert page.locator('#talk-btn').get_attribute('aria-pressed') == 'false'
    page.evaluate("fixture.socket.onmessage({data: JSON.stringify({type:'speak', text:'STALE', session:'old', turn:1})})")
    assert page.locator('#speech-caption').inner_text() != 'STALE'
    # Stop while permission is pending; late microphone must still be released.
    page.evaluate('fixture.delay = 500')
    page.get_by_role('button', name='Hablar con Pepon', exact=True).click()
    page.get_by_role('button', name='Terminar conversación', exact=True).click()
    page.wait_for_timeout(700)
    assert page.evaluate("fixture.streams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")
    page.evaluate('fixture.delay = 0; fixture.deny = true')
    page.get_by_role('button', name='Hablar con Pepon', exact=True).click()
    page.wait_for_function("voiceState === 'error'")
    assert 'PERMITE EL MICRO' in page.locator('#voice-status').inner_text()
    assert page.evaluate('audioContext === null')
    page.evaluate('fixture.deny = false')
    page.get_by_role('button', name='Hablar con Pepon', exact=True).click()
    page.wait_for_function("voiceState === 'listening'")
    page.evaluate('fixture.socket.close()')
    assert page.evaluate('micStream === null && !conversationActive')
    page.locator('#companion-panel summary').click()
    page.locator('#quiet-toggle').check()
    page.wait_for_function('assistantState.quiet === true')
    page.locator('#companion-panel summary').click()
    page.evaluate('setVoiceState("idle"); document.getElementById("speech-caption").textContent = ""')
    for width, height in [(393, 851), (320, 640), (851, 393)]:
        page.set_viewport_size({'width': width, 'height': height})
        for selector in ['#talk-btn', '#camera-switch-btn', '#talk-hint', '#voice-status']:
            box = page.locator(selector).bounding_box()
            assert box['x'] >= 0 and box['y'] >= 0 and box['x'] + box['width'] <= width and box['y'] + box['height'] <= height, (selector, box)
        page.screenshot(path=f'/tmp/pepon-natural-{width}.png')
    page.emulate_media(reduced_motion='reduce')
    page.evaluate('conversationActive = true; setVoiceState("processing")')
    assert page.locator('.orb-shell').evaluate('el => getComputedStyle(el).animationName') == 'none'
    assert not errors, errors
    browser.close()
server.shutdown()
server.server_close()
print('Browser passed: real AudioWorklet, WAV delivery, live meter, interruption, stop/release, late permission, denial, disconnect, stale replies, quiet toggle, responsive layout, reduced motion.')
