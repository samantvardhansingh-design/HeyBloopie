"""HeyBloopie Local HTTP Backend Server.

Provides a fast, zero-dependency HTTP server on port 8000 using Python's built-in
http.server module. Supports both /run and /api/tauri endpoints with full CORS headers.
"""

import asyncio
import dataclasses
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging
import sys
import threading
from typing import Any, Dict, List

from python import core, memory

logger = logging.getLogger("heybloopie.server")
PORT = 8000


class HeyBloopieHandler(BaseHTTPRequestHandler):
    """HTTP request handler for HeyBloopie backend."""

    def _set_cors_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_cors_headers(200)

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self._set_cors_headers(200)
            self.wfile.write(json.dumps({"status": "ok", "app": "HeyBloopie", "port": PORT}).encode("utf-8"))
        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"

        try:
            payload = json.loads(body or "{}")
        except Exception:
            payload = {}

        captured_events: List[Dict[str, Any]] = []

        def event_collector(ev_payload: Any) -> None:
            captured_events.append({"event": "speak-sentence", "payload": ev_payload})

        core.add_event_listener("speak-sentence", event_collector)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            if self.path == "/run":
                user_req = payload.get("request") or payload.get("input") or ""
                print(f"[Server] Received /run request: {user_req}")
                report = loop.run_until_complete(core.run(user_req))
                result_data = dataclasses.asdict(report)

                self._set_cors_headers(200)
                resp = {"result": result_data, "events": captured_events}
                self.wfile.write(json.dumps(resp).encode("utf-8"))

            elif self.path == "/api/tauri":
                cmd = payload.get("cmd")
                args = payload.get("args") or {}
                print(f"[Server] Received /api/tauri command: {cmd}")

                if cmd == "run_core":
                    user_req = args.get("request", "")
                    report = loop.run_until_complete(core.run(user_req))
                    result_data = dataclasses.asdict(report)
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({"result": result_data, "events": captured_events}).encode("utf-8"))

                elif cmd == "check_onboarding_needed":
                    val = memory.get_preference("active_provider")
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({"result": False if val else True}).encode("utf-8"))

                elif cmd == "get_preferences":
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({"result": memory.get_all_preferences()}).encode("utf-8"))

                elif cmd in ("set_tray_ready", "start_wake_word"):
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({"result": True}).encode("utf-8"))

                else:
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({"result": None}).encode("utf-8"))

            else:
                self._set_cors_headers(404)
                self.wfile.write(json.dumps({"error": f"Unknown path: {self.path}"}).encode("utf-8"))

            loop.close()
        except Exception as e:
            self._set_cors_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        finally:
            core.remove_event_listener("speak-sentence", event_collector)


def start_server(port: int = PORT) -> HTTPServer:
    """Starts the HTTP server on the given port."""
    server = HTTPServer(("0.0.0.0", port), HeyBloopieHandler)
    print(f"HeyBloopie Python backend server listening on http://127.0.0.1:{port}")
    return server


if __name__ == "__main__":
    server = start_server(PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()
