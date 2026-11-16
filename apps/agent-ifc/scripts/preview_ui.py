"""Preview the IFC UI with only Python's standard library, without credentials.

Run: python scripts/preview_ui.py --port 8765
This preview NEVER calls a model or supplies simulated financial recommendations.
"""

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "agent_server" / "static"


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/api/ui-config":
            return self.send_json({"dashboard_url": None, "portfolio_configured": False, "preview": True})
        if self.path.split("?")[0] in ("/", "/dashboard"):
            self.path = "/index.html"
        elif self.path.startswith("/ifc-assets/"):
            self.path = self.path.removeprefix("/ifc-assets")
        super().do_GET()

    def do_POST(self):
        # Consume the body before replying, including on persistent connections.
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_json({"detail": "This is a UI preview. Start the full application and connect your IFC Genie Agent to receive real portfolio analysis."}, 503)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"IFC UI preview: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
