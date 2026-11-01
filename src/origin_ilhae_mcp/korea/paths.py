"""한글 경로 처리.

Origin 버전·코드페이지에 따라 한글이 든 경로에서 저장·내보내기가 실패할 수 있다(Phase 0에서 확인).
- direct: 그대로 Origin에 넘긴다.
- stage : 영문 임시 폴더에서 Origin이 작업하고, 서버(Python, 유니코드 안전)가 최종 위치로 옮긴다.
- auto  : 경로가 ASCII면 direct. 한글이 있으면 doctor의 '한글 경로 시험'을 통과했을 때만 direct.

한국 환경 함정: Windows 사용자 이름이 한글이면 %TEMP%(C:\\Users\\홍길동\\...)에도 한글이 들어간다.
그래서 임시 폴더가 ASCII가 아니면 C:\\Users\\Public 아래를 쓴다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path


def is_ascii(p: str | Path) -> bool:
    return str(p).isascii()


def stage_dir() -> Path:
    env = os.environ.get("ILHAE_STAGE_DIR")
    if env:
        d = Path(env)
    else:
        d = Path(tempfile.gettempdir()) / "origin-ilhae" / "stage"
        if not is_ascii(d):
            public = os.environ.get("PUBLIC", r"C:\Users\Public")
            d = Path(public) / "origin-ilhae" / "stage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def use_direct(target: Path, mode: str, kr_path_ok: bool) -> bool:
    if is_ascii(target) or mode == "direct":
        return True
    if mode == "stage":
        return False
    return kr_path_ok


def for_write(target: Path, mode: str = "auto", kr_path_ok: bool = False) -> tuple[str, Callable[[], Path], bool]:
    """(Origin에 넘길 경로, 마무리 함수, 우회 여부). 마무리 함수는 Origin 작업 뒤 호출한다."""
    if use_direct(target, mode, kr_path_ok):
        return str(target), (lambda: target), False
    staged = stage_dir() / f"{uuid.uuid4().hex}{target.suffix}"

    def finalize() -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(target))
        return target

    return str(staged), finalize, True


def for_read(source: Path, mode: str = "auto", kr_path_ok: bool = False) -> tuple[str, bool]:
    """Origin이 직접 읽어야 하는 파일(.opju 등)을 영문 경로로 복사한다."""
    if use_direct(source, mode, kr_path_ok):
        return str(source), False
    staged = stage_dir() / f"{uuid.uuid4().hex}{source.suffix}"
    shutil.copy2(source, staged)
    return str(staged), True


def safe_filename(name: str, max_len: int = 80) -> str:
    """Windows 파일명 금지 문자 제거(한글은 유지)."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip().rstrip(".")
    return out[:max_len] or "figure"
