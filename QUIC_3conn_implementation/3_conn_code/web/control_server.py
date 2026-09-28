"""
Minimal HTTP control server for server-side bottleneck overrides.

Runs as a daemon thread inside the server container, listening on :9001
(internal Docker network only — not exposed to the host).

The clients container POSTs slider commands to http://192.168.200.10:9001/control,
so bandwidth changes affect the server-egress (download) bottleneck.

Why this exists
---------------
Under docker-compose the two directions of traffic are shaped by different
containers: the clients container shapes upload, the server container shapes
download. A bandwidth change made in the dashboard therefore has to reach both,
but the dashboard only runs alongside the clients. This endpoint is the relay
that lets it reach the server container's bottleneck as well.

    browser -> dashboard (clients container) -> local bottleneck (upload)
                                             -> POST :9001 -> this server
                                                           -> bottleneck (download)

Implemented on `http.server` rather than FastAPI deliberately: it carries two
trivial routes inside a container that need not depend on the web stack, and
runs on a daemon thread so it cannot delay process exit.

    GET  /health   reports whether a bottleneck is currently active
    POST /control  applies a network override, or releases one

Security note: bound to the internal Docker network only and never published to
the host. It performs no authentication, so it must not be exposed publicly.

Connections
-----------
Imports from : standard library only (json, http.server, threading, typing)
Imported by  : main.py (lazily, in server mode)
Controls     : the server container's ProcessOrchestrator bottleneck
Paired with  : simulation.process_orchestrator._forward_to_server (the caller)
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional

_orchestrator_ref = None


class _ControlHandler(BaseHTTPRequestHandler):
    """Handle POST /control and GET /health."""

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok",
                                "has_bottleneck": _orchestrator_ref is not None and
                                                  getattr(_orchestrator_ref, "bottleneck", None) is not None})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/control":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, {"success": False, "error": "bad JSON"})
            return

        if _orchestrator_ref is None:
            self._respond(200, {"success": False, "error": "no orchestrator"})
            return

        try:
            if body.get("release"):
                success = _orchestrator_ref.release_network_override()
                self._respond(200, {"success": success, "mode": "auto"})
            else:
                success = _orchestrator_ref.update_network_conditions(
                    bandwidth_mbps=float(body["bandwidth_mbps"]),
                    delay_ms=int(body["delay_ms"]),
                    jitter_ms=int(body["jitter_ms"]),
                    loss_pct=float(body["loss_pct"]),
                )
                self._respond(200, {"success": success, "mode": "manual"})
        except Exception as e:
            self._respond(200, {"success": False, "error": str(e)})

    def _respond(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Suppress per-request logs to keep stdout clean


def start_control_server(orchestrator, port: int = 9001) -> Optional[HTTPServer]:
    """
    Start the bottleneck control server in a background daemon thread.

    Args:
        orchestrator: ProcessOrchestrator instance (holds the bottleneck ref)
        port: TCP port to listen on (default 9001)

    Returns:
        The HTTPServer instance (already running in background thread).
    """
    global _orchestrator_ref
    _orchestrator_ref = orchestrator

    try:
        server = HTTPServer(("0.0.0.0", port), _ControlHandler)
    except OSError as e:
        print(f"[ControlServer] Could not bind to port {port}: {e}")
        return None

    thread = Thread(target=server.serve_forever, daemon=True, name="control-server")
    thread.start()
    print(f"[ControlServer] Listening on :{port} (internal)")
    return server
