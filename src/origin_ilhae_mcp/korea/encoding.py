"""측정 파일 인코딩 자동 판별. 국내 장비·한글 Excel이 내보낸 CSV는 CP949(EUC-KR 확장)가 흔하다.

순서: BOM → UTF-8 엄격 디코딩 → CP949 → (있으면) charset-normalizer → latin-1
UTF-8을 먼저 시도하는 이유: UTF-8 한글 바이트열은 CP949로도 '디코딩은 되는' 경우가 있어
CP949를 먼저 하면 글자가 깨진 채 성공해 버린다.
"""
from __future__ import annotations

from pathlib import Path

_BOMS = [
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
]


def detect_encoding(raw: bytes) -> tuple[str, str]:
    """(인코딩, 판별 근거) 반환."""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return enc, "BOM"
    try:
        raw.decode("utf-8")
        return "utf-8", "UTF-8로 오류 없이 해석됨"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp949")
        return "cp949", "UTF-8 해석 실패, CP949로 해석됨(한국어 Windows 기본)"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            return best.encoding, "charset-normalizer 추정"
    except ImportError:
        pass
    return "latin-1", "판별 실패 — latin-1로 강제 해석(글자가 깨질 수 있음)"


def read_text(path: Path, encoding: str | None = None) -> tuple[str, str, str]:
    """(본문, 인코딩, 근거). encoding을 주면 그대로 쓴다."""
    raw = Path(path).read_bytes()
    if encoding:
        return raw.decode(encoding), encoding, "사용자 지정"
    enc, why = detect_encoding(raw)
    return raw.decode(enc, errors="replace"), enc, why
