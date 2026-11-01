"""환경 변수 기반 설정. Claude Desktop/Code 의 MCP 설정 "env" 에서 지정한다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .bridge import ilhae_protocol as P

ALL_TOOLSETS = ("core", "korea", "physics")


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "예")


def _default_roots() -> list[Path]:
    home = Path.home()
    return [home / "Documents", home / "Desktop", home / "Downloads"]


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".origin-ilhae") / "origin-ilhae"


@dataclass
class Settings:
    backend: str = "auto"                       # auto | bridge | com | fake
    host: str = P.DEFAULT_HOST
    port: int = P.DEFAULT_PORT
    token_file: Path = field(default_factory=lambda: app_dir() / "token")
    timeout: float = 60.0                       # 툴 1회 기본 시간 제한(초)
    toolsets: tuple[str, ...] = ALL_TOOLSETS
    allowed_roots: list[Path] = field(default_factory=_default_roots)
    enable_labtalk: bool = False                # 임의 LabTalk 실행은 기본 꺼짐
    auto_dismiss: bool = False                  # 시간 초과 시 대화상자 자동 닫기
    auto_backup: bool = True                    # 위험 작업 전 프로젝트 백업
    backup_dir: Path = field(default_factory=lambda: app_dir() / "backups")
    kr_path_mode: str = "auto"                  # auto | direct | stage (한글 경로 처리)
    state_file: Path = field(default_factory=lambda: app_dir() / "state.json")

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        s.backend = os.environ.get("ILHAE_BACKEND", s.backend).lower()
        s.host = os.environ.get("ILHAE_BRIDGE_HOST", s.host)
        s.port = int(os.environ.get("ILHAE_BRIDGE_PORT", s.port))
        if os.environ.get("ILHAE_TOKEN_FILE"):
            s.token_file = Path(os.environ["ILHAE_TOKEN_FILE"])
        s.timeout = float(os.environ.get("ILHAE_TIMEOUT", s.timeout))
        ts = os.environ.get("ILHAE_TOOLSETS")
        if ts:
            names = [t.strip().lower() for t in ts.split(",") if t.strip()]
            s.toolsets = ALL_TOOLSETS if "all" in names else tuple(n for n in names if n in ALL_TOOLSETS)
        roots = os.environ.get("ILHAE_ALLOWED_ROOTS")
        if roots:
            s.allowed_roots = [Path(r).expanduser() for r in roots.split(os.pathsep) if r.strip()]
        s.enable_labtalk = _bool("ILHAE_ENABLE_LABTALK", s.enable_labtalk)
        s.auto_dismiss = _bool("ILHAE_AUTO_DISMISS", s.auto_dismiss)
        s.auto_backup = _bool("ILHAE_AUTO_BACKUP", s.auto_backup)
        if os.environ.get("ILHAE_BACKUP_DIR"):
            s.backup_dir = Path(os.environ["ILHAE_BACKUP_DIR"])
        s.kr_path_mode = os.environ.get("ILHAE_KR_PATH_MODE", s.kr_path_mode).lower()
        return s
