"""한글 글꼴 이름 정리. Origin LabTalk의 font() 함수는 영문 글꼴 이름(Family name)을 받는다."""
from __future__ import annotations

from ..errors import IlhaeError

# 한국어 이름·흔한 표기 -> Windows 영문 글꼴 이름
KR_FONTS: dict[str, str] = {
    "맑은 고딕": "Malgun Gothic", "맑은고딕": "Malgun Gothic", "malgun": "Malgun Gothic",
    "나눔고딕": "NanumGothic", "나눔 고딕": "NanumGothic",
    "나눔명조": "NanumMyeongjo", "나눔 명조": "NanumMyeongjo",
    "본고딕": "Noto Sans KR", "노토산스": "Noto Sans KR", "noto sans kr": "Noto Sans KR",
    "본명조": "Noto Serif KR", "noto serif kr": "Noto Serif KR",
    "바탕": "Batang", "바탕체": "BatangChe", "굴림": "Gulim", "돋움": "Dotum",
    "함초롬바탕": "HCR Batang", "함초롬 바탕": "HCR Batang",
    "함초롬돋움": "HCR Dotum", "함초롬 돋움": "HCR Dotum",
    "프리텐다드": "Pretendard",
}
KOREAN_CAPABLE = {"Malgun Gothic", "NanumGothic", "NanumMyeongjo", "Noto Sans KR", "Noto Serif KR",
                  "Batang", "BatangChe", "Gulim", "Dotum", "HCR Batang", "HCR Dotum", "Pretendard"}
DEFAULT_SANS = "Malgun Gothic"   # Windows 기본 설치
DEFAULT_SERIF = "Batang"         # Windows 기본 설치 (학위논문 본문과 어울림)


def resolve_font(name: str | None) -> str:
    if not name:
        return DEFAULT_SANS
    n = name.strip()
    family = KR_FONTS.get(n) or KR_FONTS.get(n.lower()) or n
    # LabTalk font(...) 인자에 들어가므로 괄호·세미콜론·따옴표를 막는다
    if any(c in family for c in "();\"'$"):
        raise IlhaeError("BAD_FONT", f"글꼴 이름에 쓸 수 없는 문자가 있습니다: {name}")
    return family


def korean_capable(family: str) -> bool:
    return family in KOREAN_CAPABLE
