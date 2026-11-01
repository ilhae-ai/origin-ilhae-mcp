"""하이브리드 라우터: 브리지 우선, 실패 시 COM으로 전환. 어떤 경로를 썼는지 기록한다."""
from __future__ import annotations

import sys
from typing import Any

from ..config import Settings
from ..errors import IlhaeError
from .base import Backend

# 요청을 보내기 전에 실패한 경우만 재시도한다(보낸 뒤 끊기면 이중 실행 위험)
_CONNECTION_CODES = {"BRIDGE_UNREACHABLE", "NO_TOKEN"}


def make_backend(settings: Settings) -> Backend:
    if settings.backend == "bridge":
        return _bridge(settings)
    if settings.backend == "com":
        return _com(settings)
    if settings.backend == "fake":
        from .fake import FakeBackend

        return FakeBackend()
    return AutoBackend(settings)


def _bridge(s: Settings) -> Backend:
    from .bridge_client import BridgeBackend

    return BridgeBackend(s.host, s.port, s.token_file, s.timeout, s.auto_dismiss)


def _com(s: Settings) -> Backend:
    from .com_client import ComBackend

    return ComBackend(s.timeout, s.auto_dismiss)


class AutoBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.current: Backend | None = None
        self.attempts: list[dict[str, str]] = []

    @property
    def name(self) -> str:
        return f"auto→{self.current.name}" if self.current else "auto(미연결)"

    def _select(self) -> Backend:
        self.attempts = []
        bridge = _bridge(self.settings)
        try:
            bridge.call("ping", timeout=5)
            self.current = bridge
            return bridge
        except IlhaeError as e:
            self.attempts.append({"route": "bridge", "error": e.message})
        if sys.platform == "win32":
            try:
                com = _com(self.settings)
                com.call("ping", timeout=15)
                self.current = com
                return com
            except IlhaeError as e:
                self.attempts.append({"route": "com", "error": e.message})
        raise IlhaeError("NO_ORIGIN", "Origin에 연결할 수 없습니다(브리지·COM 모두 실패).",
                         detail={"attempts": self.attempts},
                         next_actions=["Origin을 실행하고 브리지를 시작하세요(설치가이드 참고).",
                                       "origin-ilhae-mcp doctor 로 점검하세요."])

    def call(self, op: str, args: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        backend = self.current or self._select()
        try:
            return backend.call(op, args, timeout)
        except IlhaeError as e:
            if e.code not in _CONNECTION_CODES:
                raise
            # 브리지가 끊긴 경우(예: Origin 재시작) 한 번만 경로를 다시 고른다
            self.current = None
            return self._select().call(op, args, timeout)

    def close(self) -> None:
        if self.current:
            self.current.close()
