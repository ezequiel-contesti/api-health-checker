#!/usr/bin/env python3
"""demo_server: a tiny API to try api-health-checker against.

Serves:
  /ok     -> 200, fast
  /slow   -> 200, ~1.2s delay (trips the latency warning)
  /error  -> 500
  anything else -> 404

Standard library only. Not for production use.
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ok":
            self._send(200, {"status": "ok"})
        elif self.path == "/slow":
            time.sleep(1.2)
            self._send(200, {"status": "ok", "note": "slow backend"})
        elif self.path == "/error":
            self._send(500, {"status": "error"})
        else:
            self._send(404, {"status": "not found"})

    def log_message(self, *args):  # keep the console clean
        pass


def main():
    ap = argparse.ArgumentParser(description="Demo API for api-health-checker.")
    ap.add_argument("--port", type=int, default=8901)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("demo-api listening on 127.0.0.1:%d" % server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
