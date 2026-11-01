"""보안 규칙: 허용 폴더 검사와 LabTalk 차단 목록.

차단 목록은 "사고 방지"용이지 완벽한 샌드박스가 아니다. 그래서 LabTalk 실행 툴 자체를
기본으로 꺼 두고, 켤 때도 confirm=True 를 요구한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import IlhaeError

ALLOWED_EXTS = {
    "read": {".csv", ".txt", ".dat", ".tsv", ".xls", ".xlsx", ".opju", ".opj"},
    "project": {".opju", ".opj"},
    "export": {".png", ".emf", ".pdf", ".svg", ".tif", ".tiff", ".jpg", ".eps"},
}

# 파이썬 실행, 외부 프로그램 실행, 파일 삭제·이동, 시스템 설정 변경 등
_LABTALK_DENY = [
    (r"\brun\s+-py", "Python 코드 실행(run -py*)"),
    (r"\bpy\.\w*", "Python 실행(py.*)"),
    (r"\bpython\s*\(", "Python 실행"),
    (r"\b(exec|system\.exec)\b", "외부 프로그램 실행"),
    (r"\bdel\s+-f\b|\bfile\s*\.\s*(delete|remove)|\bfdelete\b", "파일 삭제"),
    (r"\bdos\b|\bcmd\s*/c|\bshellexecute\b|\bwinexec\b", "운영체제 명령 실행"),
    (r"\bsystem\.[\w.$]+\s*=(?!=)", "시스템 설정 변경"),
    (r"\bdll\b|\bloaddll\b|\bocompile\b|\brun\.loadoc\b", "외부 코드(DLL/OC) 로드"),
    (r"\bdoc\s+-s\b", "변경 사항 버리기(doc -s)"),
    (r"\bexit\b", "Origin 종료"),
]


def check_labtalk(code: str) -> None:
    lowered = code.lower()
    for pat, why in _LABTALK_DENY:
        if re.search(pat, lowered):
            raise IlhaeError("LABTALK_BLOCKED", f"차단된 LabTalk 명령이 포함되어 있습니다: {why}",
                             recoverable=False,
                             next_actions=["전용 툴(graph_set_axis 등)로 같은 작업을 할 수 있는지 확인하세요."])


def resolve_path(path: str, roots: list[Path], kind: str = "read", must_exist: bool = False) -> Path:
    """사용자가 준 경로를 절대 경로로 바꾸고 허용 폴더·확장자를 검사한다."""
    if not path or "\x00" in path:
        raise IlhaeError("BAD_PATH", "경로가 비어 있거나 잘못되었습니다.")
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise IlhaeError("BAD_PATH", "상위 폴더 이동(..)이 들어간 경로는 쓸 수 없습니다.")
    if not raw.is_absolute():
        raise IlhaeError("BAD_PATH", f"절대 경로를 지정해 주세요: {path}",
                         next_actions=[f"허용 폴더 예: {', '.join(str(r) for r in roots[:3])}"])
    p = raw.resolve(strict=False)
    if not any(_is_within(p, r) for r in roots):
        raise IlhaeError("PATH_NOT_ALLOWED", f"허용된 폴더 밖의 경로입니다: {p}",
                         recoverable=False,
                         next_actions=["ILHAE_ALLOWED_ROOTS 환경 변수에 폴더를 추가하세요.",
                                       f"현재 허용 폴더: {', '.join(str(r) for r in roots)}"])
    exts = ALLOWED_EXTS.get(kind)
    if exts and p.suffix.lower() not in exts:
        raise IlhaeError("BAD_EXTENSION", f"허용되지 않은 확장자입니다({p.suffix}). 가능: {', '.join(sorted(exts))}")
    if must_exist and not p.exists():
        raise IlhaeError("FILE_NOT_FOUND", f"파일이 없습니다: {p}")
    return p


def _is_within(p: Path, root: Path) -> bool:
    try:
        root_r = root.expanduser().resolve(strict=False)
    except OSError:
        return False
    # Windows 는 대소문자를 구분하지 않으므로 소문자로 비교
    a, b = str(p).lower(), str(root_r).lower()
    return a == b or a.startswith(b.rstrip("\\/") + ("\\" if "\\" in b else "/"))
