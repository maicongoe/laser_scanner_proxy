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
    .canvas-wrap { margin-top: 10px; background: #0f172a; border-radius: 8px; padding: 8px; }
    canvas { width: 100%; max-width: 760px; height: 380px; display: block; border: 1px solid #334155; border-radius: 6px; background: #020617; }
  </style>
</head>
<body>
  <h1>nanoScan3 - Telemetria UDP</h1>
  <div class="muted">Atualizacao automatica a cada 1 segundo.</div>
  <div id="content"></div>
  <script>
    const FOV_START_DEG = -47.5;
    const FOV_END_DEG = 222.5;
    const FOV_CENTER_DEG = (FOV_START_DEG + FOV_END_DEG) / 2.0;
    const zoomByScanner = {};
    const panByScanner = {};
    const dragByScanner = {};

    function fmt(v) { return (v === null || v === undefined) ? "-" : v; }
    function statusClass(errors) { return errors > 0 ? "err" : "ok"; }
    function scannerCanvasId(name) {
      return "scan_canvas_" + String(name).replace(/[^a-zA-Z0-9_]/g, "_");
    }
    function normalizeAroundCenter(angleDeg) {
      let a = angleDeg;
      while ((a - FOV_CENTER_DEG) > 180.0) a -= 360.0;
      while ((a - FOV_CENTER_DEG) < -180.0) a += 360.0;
      return a;
    }
    function isInFov(angleDeg) {
      const a = normalizeAroundCenter(angleDeg);
      return a >= FOV_START_DEG && a <= FOV_END_DEG;
    }
    function finiteRanges(values) {
      const out = [];
      for (const v of values || []) {
        if (v !== null && v !== undefined && Number.isFinite(v) && v > 0) {
          out.push(v);
        }
      }
      return out;
    }
    function drawBackground(ctx, cx, cy, radiusPx) {
      const startRad = (FOV_START_DEG * Math.PI) / 180.0;
      const endRad = (FOV_END_DEG * Math.PI) / 180.0;

      ctx.strokeStyle = "#1e293b";
      ctx.lineWidth = 1;

      for (let i = 1; i <= 4; i++) {
        const r = (radiusPx * i) / 4;
        ctx.beginPath();
        ctx.arc(cx, cy, r, -endRad, -startRad, false);
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + radiusPx * Math.cos(startRad), cy - radiusPx * Math.sin(startRad));
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + radiusPx * Math.cos(endRad), cy - radiusPx * Math.sin(endRad));
      ctx.stroke();
    }
    function drawScan(canvas, scannerName, snap) {
      if (!canvas || !snap) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      const cssW = canvas.clientWidth || 760;
      const cssH = canvas.clientHeight || 380;
      canvas.width = Math.floor(cssW * dpr);
      canvas.height = Math.floor(cssH * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      ctx.clearRect(0, 0, cssW, cssH);
      ctx.fillStyle = "#020617";
      ctx.fillRect(0, 0, cssW, cssH);

      const pan = panByScanner[scannerName] || { x: 0, y: 0 };
      const cx = (cssW * 0.5) + pan.x;
      const cy = (cssH * 0.72) + pan.y;
      const radiusPx = Math.min(cssW * 0.46, cssH * 0.80);
      const zoom = zoomByScanner[scannerName] || 1.0;

      const ranges = finiteRanges(snap.sample_ranges_m);
      const maxData = ranges.length > 0 ? Math.max(...ranges) : 1.0;
      const maxRange = Math.max(0.5, maxData * 1.05);
      const scale = (radiusPx / maxRange) * zoom;

      drawBackground(ctx, cx, cy, radiusPx);

      const angles = snap.sample_angles_deg || [];
      const sampleRanges = snap.sample_ranges_m || [];
      const points = [];
      const rayStride = angles.length > 700 ? 4 : 1;

      ctx.strokeStyle = "#0ea5e9";
      ctx.lineWidth = 0.7;
      for (let i = 0; i < angles.length; i++) {
        const angleDeg = angles[i];
        if (!isInFov(angleDeg)) continue;
        const range = sampleRanges[i];
        if (range === null || range === undefined || !Number.isFinite(range) || range <= 0) {
          continue;
        }
        const rad = (angleDeg * Math.PI) / 180.0;
        const x = cx + (range * scale) * Math.cos(rad);
        const y = cy - (range * scale) * Math.sin(rad);
        points.push([x, y]);
        if (i % rayStride === 0) {
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(x, y);
          ctx.stroke();
        }
      }

      if (points.length > 1) {
        ctx.strokeStyle = "#22d3ee";
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(points[0][0], points[0][1]);
        for (let i = 1; i < points.length; i++) {
          ctx.lineTo(points[i][0], points[i][1]);
        }
        ctx.stroke();
      }

      ctx.fillStyle = "#f59e0b";
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
      ctx.fill();

      ctx.fillStyle = "#cbd5e1";
      ctx.font = "12px Arial";
      ctx.fillText(`maxRange=${maxRange.toFixed(2)}m`, 10, 18);
      ctx.fillText(`pontos=${angles.length}`, 10, 34);
      ctx.fillText(`zoom=${zoom.toFixed(2)}x`, 10, 50);
      ctx.fillText(`fov=${FOV_START_DEG}°..${FOV_END_DEG}°`, 10, 66);
      ctx.fillText(`pan=(${pan.x.toFixed(0)}, ${pan.y.toFixed(0)})`, 10, 82);
    }
    function attachInteractions(canvas, scannerName) {
      if (!canvas) return;
      if (zoomByScanner[scannerName] === undefined) {
        zoomByScanner[scannerName] = 1.0;
      }
      if (panByScanner[scannerName] === undefined) {
        panByScanner[scannerName] = { x: 0, y: 0 };
      }
      if (canvas.dataset.interactionsAttached === "1") {
        return;
      }
      canvas.dataset.interactionsAttached = "1";

      canvas.addEventListener("wheel", (ev) => {
        ev.preventDefault();
        const current = zoomByScanner[scannerName] || 1.0;
        const next = ev.deltaY < 0 ? current * 1.15 : current / 1.15;
        zoomByScanner[scannerName] = Math.min(200.0, Math.max(0.10, next));
      }, { passive: false });
      canvas.addEventListener("dblclick", () => {
        zoomByScanner[scannerName] = 1.0;
        panByScanner[scannerName] = { x: 0, y: 0 };
      });

      canvas.addEventListener("mousedown", (ev) => {
        dragByScanner[scannerName] = {
          active: true,
          startX: ev.clientX,
          startY: ev.clientY,
          panX: panByScanner[scannerName].x,
          panY: panByScanner[scannerName].y,
        };
      });
      canvas.addEventListener("mousemove", (ev) => {
        const drag = dragByScanner[scannerName];
        if (!drag || !drag.active) return;
        const dx = ev.clientX - drag.startX;
        const dy = ev.clientY - drag.startY;
        panByScanner[scannerName] = { x: drag.panX + dx, y: drag.panY + dy };
      });
      const endDrag = () => {
        const drag = dragByScanner[scannerName];
        if (!drag) return;
        drag.active = false;
      };
      canvas.addEventListener("mouseup", endDrag);
      canvas.addEventListener("mouseleave", endDrag);
    }
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
        const canvasId = scannerCanvasId(item.scanner_name);
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
        html += "</table>";
        html += `<div class='canvas-wrap'><canvas id='${canvasId}'></canvas></div>`;
        html += "</div>";
      }
      root.innerHTML = html;
      for (const item of scanners) {
        const snap = item.snapshot;
        if (!snap) continue;
        const scannerName = item.scanner_name;
        const canvas = document.getElementById(scannerCanvasId(scannerName));
        attachInteractions(canvas, scannerName);
        drawScan(canvas, scannerName, snap);
      }
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
