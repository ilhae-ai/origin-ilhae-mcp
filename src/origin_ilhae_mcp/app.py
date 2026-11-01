"""툴들이 공유하는 실행 환경: 설정, Origin 연결, 상태 파일, 경로 검사, 백업, 오류 변환."""
from __future__ import annotations

import functools
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

from .config import Settings
from .errors import IlhaeError
from .korea import paths as kpaths
from .security import resolve_path
from .transport.base import Backend
from .transport.router import make_backend
from .verify import compare

F = TypeVar("F", bound=Callable[..., Any])


class App:
    def __init__(self, settings: Settings, backend: Backend | None = None) -> None:
        self.settings = settings
        self._backend = backend
        self.lock = threading.RLock()  # Origin 작업은 한 번에 하나씩

    # ------------------------------------------------------------ 연결
    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = make_backend(self.settings)
        return self._backend

    def call(self, op: str, timeout: float | None = None, **args: Any) -> dict[str, Any]:
        return self.backend.call(op, args, timeout)

    # ------------------------------------------------------------ 상태 파일(doctor 결과 등)
    def state(self) -> dict[str, Any]:
        try:
            return json.loads(self.settings.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, **updates: Any) -> None:
        st = self.state()
        st.update(updates)
        self.settings.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings.state_file.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def kr_path_ok(self) -> bool:
        return bool(self.state().get("kr_path_ok"))

    # ------------------------------------------------------------ 경로
    def path(self, p: str, kind: str = "read", must_exist: bool = False) -> Path:
        return resolve_path(p, self.settings.allowed_roots, kind, must_exist)

    def export_to(self, graph: str, target: Path, width_px: int | None, overwrite: bool) -> dict[str, Any]:
        """한글 경로면 영문 임시 폴더로 내보낸 뒤 옮긴다(kr_path_mode 설정에 따름)."""
        if target.exists() and not overwrite:
            raise IlhaeError("FILE_EXISTS", f"이미 파일이 있습니다: {target}",
                             next_actions=["overwrite=true 로 다시 호출하거나 다른 파일명을 쓰세요."])
        origin_path, finalize, staged = kpaths.for_write(target, self.settings.kr_path_mode, self.kr_path_ok)
        res = self.call("graph_export", graph=graph, path=origin_path, width_px=width_px,
                        overwrite=overwrite or staged)
        if staged:
            if target.exists():
                target.unlink()
            finalize()
        res.update({"path": str(target), "exists": target.is_file(),
                    "bytes": target.stat().st_size if target.is_file() else 0,
                    "korean_path_staged": staged})
        if not res["exists"]:
            raise IlhaeError("EXPORT_FAILED", f"내보내기 명령은 끝났지만 파일이 만들어지지 않았습니다: {target}",
                             next_actions=["origin_doctor 로 한글 경로 시험을 실행하세요.",
                                           "ILHAE_KR_PATH_MODE=stage 로 설정해 보세요."])
        return res

    # ------------------------------------------------------------ 백업
    def backup(self) -> dict[str, Any] | None:
        if not self.settings.auto_backup:
            return None
        try:
            return self.call("backup_project", folder=str(self.settings.backup_dir),
                             stamp=time.strftime("%Y%m%d-%H%M%S"))
        except IlhaeError as e:
            return {"backed_up": False, "reason": e.message}

    # ------------------------------------------------------------ 검증
    @staticmethod
    def verify(requested: dict[str, Any], applied: dict[str, Any] | None) -> dict[str, Any]:
        return compare(requested, applied)


def guard(app: App) -> Callable[[F], F]:
    """IlhaeError·ValueError 를 한국어 ToolError 로 바꾸고, Origin 작업을 직렬화한다."""

    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                with app.lock:
                    return fn(*args, **kwargs)
            except IlhaeError as e:
                msg = f"[{e.code}] {e.message}"
                if e.next_actions:
                    msg += "\n다음 조치: " + " / ".join(e.next_actions)
                if e.detail:
                    msg += "\n상세: " + json.dumps(e.detail, ensure_ascii=False, default=str)[:1500]
                raise ToolError(msg) from e
            except ValueError as e:
                raise ToolError(f"[BAD_INPUT] {e}") from e

        return wrapper  # type: ignore[return-value]

    return deco
