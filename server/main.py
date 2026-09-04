"""PeponBot backend — milestone 1: WebSocket link + state broadcast.

No AI yet. Just: FastAPI serves the phone UI, holds a Pepon state
(IDLE / LISTENING / THINKING), and pushes state changes to every
connected phone over a WebSocket.
"""
import socket
from enum import Enum
from pathlib import Path
from typing import Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="PeponBot")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PeponState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"


current_state: PeponState = PeponState.IDLE
connections: Set[WebSocket] = set()


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.add(websocket)
    await websocket.send_json({"type": "state", "value": current_state.value})
    try:
        while True:
            # Nothing consumed yet in this milestone; just keep the socket alive
            # and detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.discard(websocket)


class StateUpdate(BaseModel):
    state: PeponState


@app.post("/api/state")
async def set_state(update: StateUpdate):
    global current_state
    current_state = update.state
    await broadcast_state()
    return {"ok": True, "state": current_state.value}


@app.get("/api/state")
async def get_state():
    return {"state": current_state.value}


async def broadcast_state():
    dead = set()
    for ws in connections:
        try:
            await ws.send_json({"type": "state", "value": current_state.value})
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


if __name__ == "__main__":
    ip = _lan_ip()
    print(f"\nPeponBot running.\n  On this PC:  http://localhost:8000\n  On the LAN:  http://{ip}:8000  <- open this on the phone\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
