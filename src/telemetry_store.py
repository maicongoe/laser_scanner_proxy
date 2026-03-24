from __future__ import annotations

import threading
import time
from typing import Optional

from nanoscan_parser import NanoScanSnapshot


class TelemetryStore:
    def __init__(self, scanner_names: list[str]) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, object]] = {
            name: {
                "scanner_name": name,
                "packets_interpreted": 0,
                "parse_errors": 0,
                "last_error": None,
                "updated_at_unix": None,
                "snapshot": None,
            }
            for name in scanner_names
        }

    def update_snapshot(self, scanner_name: str, snapshot: NanoScanSnapshot) -> None:
        now = time.time()
        with self._lock:
            scanner_state = self._state.get(scanner_name)
            if scanner_state is None:
                return
            scanner_state["packets_interpreted"] = int(scanner_state["packets_interpreted"]) + 1
            scanner_state["updated_at_unix"] = now
            scanner_state["snapshot"] = snapshot.to_dict()

    def mark_parse_error(self, scanner_name: str, error_message: str) -> None:
        now = time.time()
        with self._lock:
            scanner_state = self._state.get(scanner_name)
            if scanner_state is None:
                return
            scanner_state["parse_errors"] = int(scanner_state["parse_errors"]) + 1
            scanner_state["last_error"] = error_message
            scanner_state["updated_at_unix"] = now

    def get_scanner(self, scanner_name: str) -> Optional[dict[str, object]]:
        with self._lock:
            scanner_state = self._state.get(scanner_name)
            if scanner_state is None:
                return None
            return dict(scanner_state)

    def get_all(self) -> dict[str, object]:
        with self._lock:
            scanners = [dict(value) for value in self._state.values()]
        return {
            "scanners": scanners,
            "total_scanners": len(scanners),
            "timestamp_unix": time.time(),
        }
