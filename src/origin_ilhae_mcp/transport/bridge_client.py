"""브리지(Origin 내장 Python) TCP 클라이언트. 호출마다 짧게 연결한다(127.0.0.1이라 비용이 작다)."""
from __future__ import annotations

import itertools
import socket
from pathlib import Path
from typing import Any

from ..bridge import ilhae_protocol as P
from ..errors import IlhaeError
from . import watchdog


class BridgeBackend:
    name = "bridge"

    def __init__(self, host: str, port: int, token_file: Path, timeout: float = 60.0,
                 auto_dismiss: bool = False) -> None:
        self.host = host
        self.port = port
        self.token_file = token_file
        self.timeout = timeout
        self.auto_dismiss = auto_dismiss
        self._ids = itertools.count(1)

    def _token(self) -> str:
        try:
            return self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise IlhaeError("NO_TOKEN", f"브리지 토큰 파일이 없습니다: {self.token_file}",
                             next_actions=["Origin에서 브리지를 먼저 시작하세요(설치가이드 3단계)."]) from None

    def call(self, op: str, args: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        t = timeout or self.timeout
        req = {"id": next(self._ids), "token": self._token(), "op": op, "args": args or {}}
        try:
            sock = socket.create_connection((self.host, self.port), timeout=3.0)
        except OSError:
            raise IlhaeError("BRIDGE_UNREACHABLE",
                             f"Origin 브리지({self.host}:{self.port})에 연결할 수 없습니다.",
                             next_actions=["Origin이 켜져 있는지, 브리지를 시작했는지 확인하세요.",
                                           "origin_status 툴로 상태를 확인하세요."]) from None
        try:
            sock.settimeout(t)
            sock.sendall(P.encode(req))
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(1 << 20)
                if not chunk:
                    raise IlhaeError("BRIDGE_CLOSED", "브리지가 응답 없이 연결을 끊었습니다.")
                buf += chunk
                if len(buf) > P.MAX_LINE_BYTES:
                    raise IlhaeError("RESPONSE_TOO_LARGE", "응답이 너무 큽니다. max_rows를 줄이세요.")
        except socket.timeout:
            raise self._timeout_error(op, t) from None
        finally:
            sock.close()
        resp = P.decode(buf.split(b"\n", 1)[0])
        if resp.get("ok"):
            return resp.get("result") or {}
        raise IlhaeError.from_payload(resp.get("error") or {})

    def _timeout_error(self, op: str, t: float) -> IlhaeError:
        dialogs = watchdog.find_blocking_dialogs()
        closed = watchdog.dismiss(dialogs) if self.auto_dismiss else 0
        actions = ["Origin 화면에서 열린 대화상자를 닫은 뒤 다시 시도하세요."]
        if closed:
            actions = [f"대화상자 {closed}개를 자동으로 닫았습니다. 결과를 확인한 뒤 다시 시도하세요."]
        return IlhaeError("TIMEOUT", f"'{op}' 작업이 {t:.0f}초 안에 끝나지 않았습니다. "
                          + watchdog.describe(dialogs),
                          next_actions=actions, detail={"dialogs": dialogs, "dismissed": closed})

    def close(self) -> None:
        pass
