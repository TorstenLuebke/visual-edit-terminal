"""Experimental subprocess transport for a *real* external engine binary.

Wire protocol: line-delimited JSON requests/responses. Feed bytes are base64 encoded.
No implicit fallback, no production PTY mutation, no mocked terminal implementation.
The executable is supplied explicitly, and must implement the documented protocol.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path
import subprocess
import threading
from shelldeck_engine_contract_240 import CursorSnapshot, ScreenSnapshot


class EngineProtocolError(RuntimeError):
    pass


class WezTermProcessAdapter:
    def __init__(self, rows: int = 24, columns: int = 80, *, executable: str | Path):
        if rows < 1 or columns < 1:
            raise ValueError("invalid dimensions")
        path = Path(executable).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        self._process = subprocess.Popen([str(path)], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._lock = threading.RLock()
        try:
            result = self._request({"op": "initialize", "rows": rows, "columns": columns})
            if result.get("engine") != "wezterm-term" or result.get("ready") is not True:
                raise EngineProtocolError("process did not identify as a ready wezterm-term engine")
        except BaseException:
            self.close()
            raise

    def _request(self, data: dict) -> dict:
        with self._lock:
            if self._process.poll() is not None:
                raise EngineProtocolError("engine process terminated")
            try:
                self._process.stdin.write((json.dumps(data) + "\n").encode("utf-8"))
                self._process.stdin.flush()
                line = self._process.stdout.readline()
                if not line:
                    raise EngineProtocolError("unexpected engine EOF")
                response = json.loads(line)
            except (OSError, ValueError, TypeError) as exc:
                raise EngineProtocolError("invalid engine response") from exc
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise EngineProtocolError("engine rejected request: " + repr(response))
            return response

    def feed(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("feed requires raw bytes")
        self._request({"op": "feed", "data_base64": base64.b64encode(data).decode("ascii")})

    def resize(self, rows: int, columns: int) -> None:
        if min(rows, columns) < 1:
            raise ValueError("invalid dimensions")
        self._request({"op": "resize", "rows": rows, "columns": columns})

    def snapshot(self) -> ScreenSnapshot:
        state = self._request({"op": "snapshot"})["snapshot"]
        cur = state["cursor"]
        return ScreenSnapshot(rows=state["rows"], columns=state["columns"],
                              lines=tuple(state["lines"]),
                              cursor=CursorSnapshot(row=cur["row"], column=cur["column"],
                                                    hidden=cur.get("hidden", False)),
                              alternate=state.get("alternate", False))

    def transcript(self) -> str:
        return self._request({"op": "transcript"})["text"]

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
