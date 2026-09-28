"""
FastAPI server for the QUIC 3-Connection Dashboard.
Provides REST API and WebSocket for real-time updates.

Serves the browser dashboard and exposes the running simulation for live
observation and control.

    GET  /                static dashboard (index.html, dashboard.js, styles.css)
    WS   /ws              pushes metrics for all three connections as they arrive
    POST parameter route  adjusts one CUBIC parameter on one connection
    POST network route    overrides bandwidth, delay, jitter and loss

WebSocket rather than polling: metrics arrive every 100ms from three
connections, and a push channel avoids both the latency and the request
overhead that polling at that rate would incur. `ConnectionManager` tracks the
set of live sockets and broadcasts to all of them, so several browser tabs can
observe one run.

Requests are validated by pydantic models (`ParameterUpdate`,
`NetworkOverride`) before reaching the orchestrator, which applies its own
PARAM_BOUNDS check as the authoritative validation.

Connections
-----------
Imports from : fastapi, pydantic
Imported by  : web/__init__.py, main.py (lazily, only with --ui)
Serves       : web/static/ (index.html, dashboard.js, styles.css)
Controls     : the live ProcessOrchestrator instance
"""

import asyncio
import json
from pathlib import Path
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class ParameterUpdate(BaseModel):
    """Request model for parameter updates."""
    connection_id: int
    param_name: str
    value: float


class NetworkOverride(BaseModel):
    """Request model for manual network condition overrides."""
    bandwidth_mbps: float   # 1.0 – 50.0
    delay_ms: int           # 5 – 80
    jitter_ms: int          # 1 – 25
    loss_pct: float         # 0.0 – 15.0
    release: bool = False   # If True, release override and resume auto variation


class ConnectionManager:
    """Manages WebSocket connections for broadcasting updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        if not self.active_connections:
            return
        data = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.active_connections.discard(conn)


def create_app(orchestrator, settling_time: float = 2.0) -> FastAPI:
    """Create FastAPI application with orchestrator reference."""

    app = FastAPI(title="QUIC 3-Connection Dashboard")
    manager = ConnectionManager()

    # Store orchestrator reference
    app.state.orchestrator = orchestrator
    app.state.manager = manager

    # Serve static files (HTML, CSS, JS)
    static_path = Path(__file__).parent / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        """Serve the main dashboard HTML."""
        html_path = Path(__file__).parent / "static" / "index.html"
        if html_path.exists():
            return html_path.read_text()
        return "<html><body><h1>Dashboard not found</h1></body></html>"

    @app.get("/api/status")
    async def get_status():
        """Get current status of all connections."""
        return {
            "metrics": orchestrator.get_latest_metrics(),
            "buffers": orchestrator.get_buffer_states(),
            "params": orchestrator.get_current_params(),
            "running": orchestrator.is_running(),
            "settling_time": settling_time,
            "qlearning_history": orchestrator.get_qlearning_history(),
            "qlearning_summary": orchestrator.get_qlearning_summary(),
            "total_throughput": orchestrator.get_total_throughput(),
            "scenario_config": orchestrator.get_scenario_config(),
        }

    @app.post("/api/params")
    async def update_params(update: ParameterUpdate):
        """Update a parameter for a specific connection."""
        success = orchestrator.update_parameter(
            update.connection_id,
            update.param_name,
            update.value
        )
        return {"success": success, "connection_id": update.connection_id}

    @app.post("/api/network")
    async def update_network(override: NetworkOverride):
        """Apply or release a manual network condition override from the UI sliders."""
        if override.release:
            success = orchestrator.release_network_override()
            return {"success": success, "mode": "auto"}

        success = orchestrator.update_network_conditions(
            bandwidth_mbps=override.bandwidth_mbps,
            delay_ms=override.delay_ms,
            jitter_ms=override.jitter_ms,
            loss_pct=override.loss_pct,
        )
        return {
            "success": success,
            "mode": "manual",
            "applied": {
                "bandwidth_mbps": override.bandwidth_mbps,
                "delay_ms": override.delay_ms,
                "jitter_ms": override.jitter_ms,
                "loss_pct": override.loss_pct,
            },
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await manager.connect(websocket)
        try:
            while True:
                # Send updates every 100ms
                await asyncio.sleep(0.1)
                data = {
                    "type": "update",
                    "metrics": orchestrator.get_latest_metrics(),
                    "buffers": orchestrator.get_buffer_states(),
                    "params": orchestrator.get_current_params(),
                    "qlearning_history": orchestrator.get_qlearning_history(),
                    "qlearning_summary": orchestrator.get_qlearning_summary(),
                    "total_throughput": orchestrator.get_total_throughput(),
                    "scenario_config": orchestrator.get_scenario_config(),
                }
                await websocket.send_json(data)
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except asyncio.CancelledError:
            # Gracefully handle shutdown - don't log error
            manager.disconnect(websocket)
        except Exception:
            # Handle any other unexpected errors during shutdown
            manager.disconnect(websocket)

    return app


async def run_server(orchestrator, host: str = "0.0.0.0", port: int = 8000, settling_time: float = 2.0, _server_holder: list = None):
    """Run the FastAPI server."""
    import uvicorn

    app = create_app(orchestrator, settling_time=settling_time)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    if _server_holder is not None:
        _server_holder.append(server)
    await server.serve()
