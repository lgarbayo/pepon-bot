"""PeponBot backend — WebSocket link + state broadcast + camera ingest
+ object detection.

FastAPI serves the phone UI, holds a Pepon state (IDLE / LISTENING /
THINKING / SEARCHING / FOUND / CONFUSED), pushes state/look_at/blink
messages to the phone, receives a live JPEG frame stream from the
phone's camera over the same WebSocket (binary messages), and
periodically runs object detection on the latest frame via
PerceptionService — broadcasting detections back over the WebSocket.
A PersonTracker turns those detections into a smoothed look_at
target so the eyes follow a person without jitter or target-hopping.
A MotionClassifier reads accelerometer/orientation samples pushed by
the phone (text WebSocket messages) and reacts to PHONE_SHAKEN /
PHONE_PICKED_UP / PHONE_STABLE with a state change. A WorldState
keeps the small amount of short-term memory (visible objects, last
known positions, Pepon's own state, phone motion) that ties all of
the above together for a future voice Agent to read. Anything Pepon
*does* (look somewhere, speak, change expression, ...) is expressed
as an Action and carried out by an ActionExecutor — today PhoneExecutor,
rendering over this same WebSocket; a future hardware executor would
plug in without changing any of the code that produces actions.
Voice: the phone does STT (Web Speech API) and sends recognized text
over the WebSocket; intent.parse() turns it into a structured intent
(deterministic, no LLM) and Agent maps that to Action(s) using
WorldState. Each voice command is recorded as one EpisodeRecorder
episode (data/episodes/) — instruction, actions taken, and result —
off the event loop so it never stalls the live demo.
"""
import asyncio
import json
import socket
import subprocess
import time
from collections import deque
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

import actions
import intent
from actions import Action, ActionType, PhoneExecutor
from agent import Agent
from perception import PerceptionService
from proprioception import MotionClassifier
from recorder import EpisodeRecorder
from tracking import PersonTracker
from world_state import WorldState

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
CERT_DIR = BASE_DIR / "certs"

app = FastAPI(title="PeponBot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PeponState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SEARCHING = "SEARCHING"
    FOUND = "FOUND"
    CONFUSED = "CONFUSED"
    SURPRISED = "SURPRISED"


connections: Set[WebSocket] = set()
world_state = WorldState()  # single source of truth for Pepon's current state (world_state.pepon_state)


async def _set_pepon_state(new_state: PeponState) -> None:
    """Single choke point for changing Pepon's state: updates
    world_state and renders it as a SET_EXPRESSION action together, so
    callers can't update one without the other."""
    world_state.set_pepon_state(new_state.value)
    await action_executor.execute(actions.set_expression(new_state.value))


class FrameStats:
    """Rolling camera-ingest metrics (last 2s window for FPS)."""

    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds = window_seconds
        self.timestamps: deque[float] = deque()
        self.frames_received = 0
        self.width = 0
        self.height = 0
        self.last_frame_at: Optional[float] = None

    def record(self, width: int, height: int) -> None:
        now = time.time()
        self.frames_received += 1
        self.width = width
        self.height = height
        self.last_frame_at = now
        self.timestamps.append(now)
        cutoff = now - self.window_seconds
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()

    @property
    def fps(self) -> float:
        if len(self.timestamps) < 2:
            return 0.0
        span = self.timestamps[-1] - self.timestamps[0]
        return round((len(self.timestamps) - 1) / span, 1) if span > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "frames_received": self.frames_received,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "last_frame_at": self.last_frame_at,
            "seconds_since_last_frame": (
                round(time.time() - self.last_frame_at, 1) if self.last_frame_at else None
            ),
        }


frame_stats = FrameStats()
last_frame_jpeg: Optional[bytes] = None

# Detection runs on a timer against whatever the latest frame is, not on
# every incoming frame — a nano model is fast, but there's no reason to
# burn CPU re-detecting frames the phone barely moved between.
DETECTION_INTERVAL_SECONDS = 0.25
perception_service: Optional[PerceptionService] = None
last_detections: list = []
last_detection_at: Optional[float] = None
person_tracker = PersonTracker()
motion_classifier = MotionClassifier()


@app.on_event("startup")
async def load_perception_model():
    global perception_service
    print("[perception] loading YOLOv8n...")
    perception_service = await asyncio.to_thread(PerceptionService)
    print("[perception] model ready")
    asyncio.create_task(_detection_loop())


@app.on_event("startup")
async def start_recorder():
    recorder.start()


async def _detection_loop():
    global last_detections, last_detection_at
    while True:
        await asyncio.sleep(DETECTION_INTERVAL_SECONDS)
        if perception_service is None or last_frame_jpeg is None:
            continue
        try:
            detections = await asyncio.to_thread(perception_service.detect, last_frame_jpeg)
        except Exception as exc:
            print(f"[perception] detection failed: {exc}")
            continue
        last_detections = [d.as_dict() for d in detections]
        last_detection_at = time.time()
        world_state.update_detections(last_detections)
        await broadcast({"type": "detections", "objects": last_detections})
        await agent.check_active_target()

        gaze = person_tracker.update(last_detections)
        if gaze is not None:
            await action_executor.execute(actions.look_at(gaze[0], gaze[1], target="person"))


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/debug")
async def debug_page():
    return FileResponse(STATIC_DIR / "debug.html")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.add(websocket)
    await websocket.send_json({"type": "state", "value": world_state.pepon_state})
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            frame_bytes = message.get("bytes")
            if frame_bytes is not None:
                _ingest_frame(frame_bytes)
                continue
            text = message.get("text")
            if text is not None:
                await _handle_text_message(text)
    except WebSocketDisconnect:
        connections.discard(websocket)


async def _handle_text_message(text: str) -> None:
    try:
        payload = json.loads(text)
    except ValueError:
        return
    msg_type = payload.get("type")
    if msg_type == "motion":
        await _handle_motion(payload)
    elif msg_type == "wake_word":
        await _handle_wake_word()
    elif msg_type == "voice_command":
        await _handle_voice_command(payload.get("text", ""))


async def _handle_motion(payload: dict) -> None:
    event = motion_classifier.update(payload.get("accel_gravity"), payload.get("orientation"))
    if event is None:
        return
    world_state.set_phone_motion(motion_classifier.phase, event)
    await broadcast({"type": "motion_event", "event": event})

    if event == "PHONE_SHAKEN":
        await _set_pepon_state(PeponState.CONFUSED)
        await broadcast({"type": "dizzy"})
    elif event == "PHONE_PICKED_UP":
        await _set_pepon_state(PeponState.SURPRISED)
    elif event == "PHONE_STABLE" and world_state.pepon_state in (PeponState.CONFUSED, PeponState.SURPRISED):
        # Only clear reactions we caused ourselves — don't stomp on a state
        # the voice Agent might have set (e.g. LISTENING, SEARCHING).
        await _set_pepon_state(PeponState.IDLE)
    # PHONE_TILTED: informational only for v0.1 — a phone tilts constantly
    # while just being held, so we don't force a face reaction on it here.


async def _handle_wake_word() -> None:
    await _set_pepon_state(PeponState.LISTENING)


async def _handle_voice_command(text: str) -> None:
    if not text:
        return
    parsed = intent.parse(text)
    await agent.handle(parsed, transcript=text)


def _ingest_frame(data: bytes) -> None:
    global last_frame_jpeg
    try:
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
    except Exception:
        return  # corrupt/partial frame, drop it
    frame_stats.record(width, height)
    last_frame_jpeg = data


@app.get("/api/camera/stats")
async def camera_stats():
    return frame_stats.as_dict()


@app.get("/api/camera/frame.jpg")
async def camera_frame():
    if last_frame_jpeg is None:
        raise HTTPException(status_code=404, detail="no frame received yet")
    return Response(content=last_frame_jpeg, media_type="image/jpeg")


@app.get("/api/detections")
async def get_detections():
    return {"objects": last_detections, "last_detection_at": last_detection_at}


class StateUpdate(BaseModel):
    state: PeponState


@app.post("/api/state")
async def set_state(update: StateUpdate):
    await _set_pepon_state(update.state)
    return {"ok": True, "state": world_state.pepon_state}


@app.get("/api/state")
async def get_state():
    return {"state": world_state.pepon_state}


@app.get("/api/motion")
async def get_motion():
    return {
        "phase": world_state.phone_motion_phase,
        "last_event": world_state.last_motion_event,
        "last_event_at": world_state.last_motion_event_at,
    }


@app.get("/api/world")
async def get_world():
    return world_state.as_dict()


@app.get("/api/world/describe/{cls}")
async def describe_object(cls: str):
    return {"class": cls, "text": world_state.describe(cls)}


class LookAt(BaseModel):
    x: float  # normalized, -1 (left) .. 1 (right)
    y: float  # normalized, -1 (up) .. 1 (down)


@app.post("/api/look_at")
async def look_at(target: LookAt):
    await action_executor.execute(actions.look_at(target.x, target.y))
    return {"ok": True}


@app.post("/api/blink")
async def trigger_blink():
    # BLINK isn't one of Pepon's 6 action types (it's a phone-only visual
    # tic, not something a future hardware body would need) — still just
    # a direct WebSocket message, not routed through the executor.
    await broadcast({"type": "blink"})
    return {"ok": True}


@app.get("/api/intent/parse")
async def parse_intent(text: str):
    """Read-only: run the IntentParser without triggering the Agent —
    for iterating on intent.py's patterns without side effects."""
    return intent.parse(text)


class VoiceCommand(BaseModel):
    text: str


@app.post("/api/voice_command")
async def post_voice_command(cmd: VoiceCommand):
    """Full pipeline for manual testing without needing the phone's mic:
    text -> IntentParser -> Agent -> Action(s). Mirrors exactly what the
    phone sends after hearing the wake word."""
    parsed = intent.parse(cmd.text)
    await agent.handle(parsed, transcript=cmd.text)
    return {"intent": parsed}


@app.post("/api/action")
async def post_action(payload: Dict[str, Any]):
    """Generic action trigger for manual testing — accepts exactly the
    structured shape an Agent would produce, e.g.
    {"type": "LOOK_AT", "target": "bottle", "x": 0.61, "y": -0.1}."""
    try:
        action_type = ActionType(payload["type"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="missing or invalid 'type'")
    params = {k: v for k, v in payload.items() if k != "type"}
    await action_executor.execute(Action(action_type, params))
    return {"ok": True}


async def broadcast(payload: dict):
    dead = set()
    for ws in connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    connections.difference_update(dead)


action_executor = PhoneExecutor(broadcast)
recorder = EpisodeRecorder()
agent = Agent(world_state, action_executor, recorder=recorder, frame_provider=lambda: last_frame_jpeg)


@app.get("/api/episodes")
async def list_episodes(limit: int = 20):
    """Most recent episodes with their metadata, newest first — for
    manually eyeballing what got recorded."""

    def _read():
        dirs = sorted(recorder.base_dir.glob("episode_*"), reverse=True)[:limit]
        results = []
        for d in dirs:
            try:
                results.append(json.loads((d / "metadata.json").read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return results

    return await asyncio.to_thread(_read)


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _ensure_self_signed_cert(lan_ip: str) -> tuple[Path, Path]:
    """Chrome refuses getUserMedia on a non-localhost http:// origin, so the
    phone needs to hit us over https. Generate a throw-away self-signed cert
    on first run (regenerated if the LAN IP changes) — the phone just has to
    accept the browser warning once."""
    CERT_DIR.mkdir(exist_ok=True)
    cert_path = CERT_DIR / "cert.pem"
    key_path = CERT_DIR / "key.pem"
    marker_path = CERT_DIR / f".{lan_ip}"
    if cert_path.exists() and key_path.exists() and marker_path.exists():
        return cert_path, key_path

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-sha256", "-days", "365", "-nodes",
            "-keyout", str(key_path), "-out", str(cert_path),
            "-subj", "/CN=peponbot",
            "-addext", f"subjectAltName=IP:{lan_ip},IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    for old_marker in CERT_DIR.glob(".*"):
        old_marker.unlink()
    marker_path.touch()
    return cert_path, key_path


if __name__ == "__main__":
    ip = _lan_ip()
    cert_path, key_path = _ensure_self_signed_cert(ip)
    print(
        f"\nPeponBot running (self-signed HTTPS).\n"
        f"  On this PC:  https://localhost:8000\n"
        f"  On the LAN:  https://{ip}:8000  <- open this on the phone\n"
        f"  Debug page:  https://{ip}:8000/debug\n"
        f"  Your browser/phone will warn about the certificate — accept it once.\n"
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
