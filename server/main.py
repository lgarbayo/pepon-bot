"""PeponBot backend — WebSocket link + state broadcast + camera ingest
+ object detection.

FastAPI serves the phone UI, holds a Pepon state (IDLE / LISTENING /
THINKING / SEARCHING / FOUND / CONFUSED), pushes state/look_at/blink
messages to the phone, receives a live JPEG frame stream from the
phone's camera over the same WebSocket (binary messages), and
periodically runs object detection on the latest frame via
PerceptionService — broadcasting detections back over the WebSocket.
"""
import asyncio
import socket
import subprocess
import time
from collections import deque
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Optional, Set

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from perception import PerceptionService

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


current_state: PeponState = PeponState.IDLE
connections: Set[WebSocket] = set()


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
DETECTION_INTERVAL_SECONDS = 0.4
perception_service: Optional[PerceptionService] = None
last_detections: list = []
last_detection_at: Optional[float] = None


@app.on_event("startup")
async def load_perception_model():
    global perception_service
    print("[perception] loading YOLOv8n...")
    perception_service = await asyncio.to_thread(PerceptionService)
    print("[perception] model ready")
    asyncio.create_task(_detection_loop())


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
        await broadcast({"type": "detections", "objects": last_detections})


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
    await websocket.send_json({"type": "state", "value": current_state.value})
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            frame_bytes = message.get("bytes")
            if frame_bytes is not None:
                _ingest_frame(frame_bytes)
            # Text messages from the phone aren't used yet.
    except WebSocketDisconnect:
        connections.discard(websocket)


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
    global current_state
    current_state = update.state
    await broadcast({"type": "state", "value": current_state.value})
    return {"ok": True, "state": current_state.value}


@app.get("/api/state")
async def get_state():
    return {"state": current_state.value}


class LookAt(BaseModel):
    x: float  # normalized, -1 (left) .. 1 (right)
    y: float  # normalized, -1 (up) .. 1 (down)


@app.post("/api/look_at")
async def look_at(target: LookAt):
    await broadcast({"type": "look_at", "x": target.x, "y": target.y})
    return {"ok": True}


@app.post("/api/blink")
async def trigger_blink():
    await broadcast({"type": "blink"})
    return {"ok": True}


async def broadcast(payload: dict):
    dead = set()
    for ws in connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    connections.difference_update(dead)


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
