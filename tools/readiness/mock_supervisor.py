"""Local service-discovery fixture. It never proxies requests or records secrets."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        with Path("/evidence/supervisor.jsonl").open("a") as stream:
            stream.write(json.dumps({"method": "GET", "path": self.path}) + "\n")
        if self.path != "/services/mqtt":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer SYNTHETIC_SUPERVISOR_TOKEN":
            self.send_error(401)
            return
        body = json.dumps(
            {
                "result": "ok",
                "data": {
                    "host": "mqtt",
                    "port": 1883,
                    "ssl": False,
                    "protocol": "3.1.1",
                    "username": "synthetic-mqtt",
                    "password": "SYNTHETIC_MQTT_PASSWORD",
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
