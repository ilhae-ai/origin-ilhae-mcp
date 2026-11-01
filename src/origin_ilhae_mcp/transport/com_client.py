"""COM 대체 경로: 외부 originpro로 실행 중인 Origin에 붙는다(Windows 전용).

브리지와 같은 ilhae_ops 코드를 그대로 쓴다. COM 호출은 스레드 아파트먼트 문제를 피하려고
전용 스레드 하나에서만 실행하고, 시간 초과 시 그 스레드가 풀릴 때까지 새 요청을 막는다.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
from typing import Any

from ..errors import IlhaeError
from . import watchdog


def _com_init() -> None:
    try:
        import pythoncom  # pywin32

        pythoncom.CoInitialize()
    except ImportError:
        pass


class ComBackend:
    name = "com"

    def __init__(self, timeout: float = 60.0, auto_dismiss: bool = False) -> None:
        if sys.platform != "win32":
            raise IlhaeError("COM_UNAVAILABLE", "COM 경로는 Windows에서만 쓸 수 있습니다.", recoverable=False)
        try:
            import originpro  # noqa: F401
        except ImportError:
            raise IlhaeError("ORIGINPRO_MISSING", "COM 경로에 필요한 originpro가 설치되어 있지 않습니다.",
                             next_actions=["uv pip install \"origin-ilhae-mcp[windows]\""]) from None
        self.timeout = timeout
        self.auto_dismiss = auto_dismiss
        self._pool = cf.ThreadPoolExecutor(max_workers=1, initializer=_com_init,
                                           thread_name_prefix="ilhae-com")
        self._busy: cf.Future | None = None
        from ..bridge import ilhae_ops

        self._ops = ilhae_ops
        self._submit("init_external", {}).result(timeout=30)

    def _submit(self, op: str, args: dict[str, Any]) -> cf.Future:
        return self._pool.submit(self._ops.dispatch, op, args)

    def call(self, op: str, args: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        if self._busy is not None and not self._busy.done():
            raise IlhaeError("COM_BUSY", "이전 작업이 아직 Origin에서 끝나지 않았습니다.",
                             next_actions=["Origin 화면의 대화상자를 닫거나 작업이 끝날 때까지 기다리세요."])
        t = timeout or self.timeout
        fut = self._submit(op, args or {})
        try:
            resp = fut.result(timeout=t)
        except cf.TimeoutError:
            self._busy = fut
            dialogs = watchdog.find_blocking_dialogs()
            closed = watchdog.dismiss(dialogs) if self.auto_dismiss else 0
            raise IlhaeError("TIMEOUT", f"'{op}' 작업이 {t:.0f}초 안에 끝나지 않았습니다. "
                             + watchdog.describe(dialogs),
                             detail={"dialogs": dialogs, "dismissed": closed},
                             next_actions=["Origin 화면에서 열린 대화상자를 닫은 뒤 다시 시도하세요."]) from None
        if resp.get("ok"):
            return resp.get("result") or {}
        raise IlhaeError.from_payload(resp.get("error") or {})

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
