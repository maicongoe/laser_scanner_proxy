from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from models import WebConfig
from telemetry_store import TelemetryStore


def _build_index_html() -> str:
    return """<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>nanoScan3 Telemetria</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 18px; background: #f5f7fb; color: #1f2937; }
    h1 { margin: 0 0 12px; font-size: 24px; }
    .card { background: #fff; border: 1px solid #dce3ef; border-radius: 10px; padding: 14px; margin: 12px 0; }
    .muted { color: #6b7280; font-size: 13px; }
    table { border-collapse: collapse; width: 100%; margin-top: 8px; }
    th, td { border: 1px solid #e5e7eb; padding: 8px; font-size: 13px; text-align: left; }
    th { background: #f3f4f6; }
    .ok { color: #047857; font-weight: bold; }
    .err { color: #b91c1c; font-weight: bold; }
  </style>
</head>
<body>
  <h1>nanoScan3 - Telemetria UDP</h1>
  <div class="muted">Atualizacao automatica a cada 1 segundo.</div>
  <div id="content"></div>
  <script>
    function fmt(v) { return (v === null || v === undefined) ? "-" : v; }
    function statusClass(errors) { return errors > 0 ? "err" : "ok"; }
    function render(data) {
      const root = document.getElementById("content");
      const scanners = data.scanners || [];
      if (scanners.length === 0) {
        root.innerHTML = "<div class='card'>Nenhum scanner cadastrado.</div>";
        return;
      }
      let html = "";
      for (const item of scanners) {
        const snap = item.snapshot;
        html += "<div class='card'>";
        html += `<div><strong>${item.scanner_name}</strong> `;
        html += `<span class='${statusClass(item.parse_errors)}'>parse_errors=${item.parse_errors}</span></div>`;
        html += `<div class='muted'>packets_interpreted=${item.packets_interpreted} | updated_at_unix=${fmt(item.updated_at_unix)}</div>`;
        if (!snap) {
          html += "<div class='muted'>Sem dados interpretados ainda.</div></div>";
          continue;
        }
        html += "<table>";
        html += "<tr><th>Campo</th><th>Valor</th></tr>";
        html += `<tr><td>scan_number</td><td>${fmt(snap.scan_number)}</td></tr>`;
        html += `<tr><td>sequence_number</td><td>${fmt(snap.sequence_number)}</td></tr>`;
        html += `<tr><td>number_of_beams</td><td>${fmt(snap.number_of_beams)}</td></tr>`;
        html += `<tr><td>valid_beams</td><td>${fmt(snap.valid_beams)}</td></tr>`;
        html += `<tr><td>infinite_beams</td><td>${fmt(snap.infinite_beams)}</td></tr>`;
        html += `<tr><td>start_angle_deg</td><td>${fmt(snap.start_angle_deg)}</td></tr>`;
        html += `<tr><td>angular_beam_resolution_deg</td><td>${fmt(snap.angular_beam_resolution_deg)}</td></tr>`;
        html += `<tr><td>min_range_m / max_range_m</td><td>${fmt(snap.min_range_m)} / ${fmt(snap.max_range_m)}</td></tr>`;
        html += `<tr><td>sample_points</td><td>${(snap.sample_angles_deg || []).length}</td></tr>`;
        html += "</table></div>";
      }
      root.innerHTML = html;
    }
    async function tick() {
      try {
        const res = await fetch("/api/scanners");
        const data = await res.json();
        render(data);
      } catch (e) {
        document.getElementById("content").innerHTML = "<div class='card err'>Falha ao consultar /api/scanners</div>";
      }
    }
    setInterval(tick, 1000);
    tick();
  </script>
</body>
</html>
"""


class _TelemetryRequestHandler(BaseHTTPRequestHandler):
    store: TelemetryStore

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_html(_build_index_html())
            return
        if path == "/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/scanners":
            self._send_json(self.store.get_all())
            return
        if path.startswith("/api/scanners/"):
            scanner_name = unquote(path.split("/api/scanners/", 1)[1])
            scanner_data = self.store.get_scanner(scanner_name)
            if scanner_data is None:
                self._send_json({"error": "scanner_not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(scanner_data)
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, obj: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class TelemetryWebServer:
    def __init__(self, config: WebConfig, store: TelemetryStore, logger) -> None:
        self._config = config
        self._store = store
        self._logger = logger
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._config.enabled:
            return
        if self._server is not None:
            return

        handler_cls = type(
            "TelemetryHandler",
            (_TelemetryRequestHandler,),
            {"store": self._store},
        )
        self._server = ThreadingHTTPServer((self._config.host, self._config.port), handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._logger.info(
            "Servidor web de telemetria iniciado em http://%s:%d",
            self._config.host,
            self._config.port,
        )

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
