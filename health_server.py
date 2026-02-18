#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import time
from typing import Any


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        uptime = int(time.time() - self.server.start_time)  # type: ignore[attr-defined]
        payload = {
            "status": "ok",
            "uptime_seconds": uptime,
            "agent_mode": getattr(self.server, "agent_mode", "unknown"),  # type: ignore[attr-defined]
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HealthServer:
    def __init__(self, port: int = 8080, agent_mode: str = "daemon") -> None:
        requested_port = int(port)
        self.agent_mode = agent_mode
        self._server = HTTPServer(("127.0.0.1", requested_port), _HealthHandler)
        self.port = int(self._server.server_port)
        self._server.start_time = time.time()  # type: ignore[attr-defined]
        self._server.agent_mode = agent_mode  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="health-server")
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def start_health_server(port: int = 8080, agent_mode: str = "daemon") -> HealthServer:
    server = HealthServer(port=port, agent_mode=agent_mode)
    server.start()
    return server
