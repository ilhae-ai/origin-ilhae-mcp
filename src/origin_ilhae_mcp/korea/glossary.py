"""한국어 지시 -> 툴·옵션 매핑 사전. MCP 리소스(ilhae://glossary)와 서버 안내문에 쓴다."""
from __future__ import annotations

GLOSSARY: list[tuple[str, str]] = [
    ("로그 스케일 / 로그축 / 로그로", "graph_set_axis(scale='log10')"),
    ("선형축 / 리니어", "graph_set_axis(scale='linear')"),
    ("축 범위 / ~부터 ~까지", "graph_set_axis(start, end)"),
    ("눈금 간격", "graph_set_axis(step)"),
    ("축 제목 / 축 이름 / 라벨", "graph_set_axis(title='전압 (V)')"),
    ("이중 Y축 / 오른쪽 Y축 / 보조축", "graph_create(template='doubley', plots[..., layer=1])"),
    ("오차막대 / 에러바 / 표준편차 막대", "graph_create(plots[{yerr: 열}])"),
    ("점 그래프 / 산점도", "graph_create(plot_type='scatter')"),
    ("선+점", "graph_create(plot_type='line_symbol')"),
    ("선 굵기 / 두께", "graph_set_options(line_width=pt)"),
    ("점 크기 / 심볼 크기", "graph_set_options(symbol_size)"),
    ("범례 숨기기 / 보이기", "graph_set_options(legend_show)"),
    ("한글 깨짐 / 네모로 나옴 / 맑은 고딕", "kr_apply_font(font='맑은 고딕')"),
    ("논문용 / 학위논문 규격 / 학회지 규격", "kr_apply_preset(preset=...) — kr_list_presets 로 목록 확인"),
    ("한글(HWP) 문서에 넣을 그림 / 보고서용", "kr_export_for_hwp"),
    ("그림 저장 / 내보내기 / PNG / EMF / PDF", "graph_export"),
    ("그래프 보여줘 / 미리보기", "graph_preview"),
    ("피팅 / 커브 피팅 / 가우시안 / 로렌츠", "fit_curve 또는 spectrum_peaks_fit"),
    ("I-V / 다이오드 / 이상계수 / 직렬저항", "iv_diode_analyze"),
    ("문턱전압 / Vth / 온오프비 / SS / 전달특성", "transistor_analyze"),
    ("C-V / 모트-쇼트키 / 도핑농도 / 평탄대전압", "cv_mott_schottky"),
    ("FFT / 주파수 분석 / 스펙트럼", "spectrum_fft"),
    ("필터 / 노이즈 제거 / 스무딩", "signal_filter"),
    ("보드 선도 / 주파수 응답 / 이득·위상", "bode_plot"),
    ("아레니우스 / 활성화 에너지", "arrhenius_fit"),
    ("CSV 불러오기 / 측정 파일 열기 / 엑셀 데이터", "import_data_file"),
]


def to_markdown() -> str:
    lines = ["| 한국어 표현 | 사용할 툴 |", "|---|---|"]
    lines += [f"| {k} | `{v}` |" for k, v in GLOSSARY]
    return "\n".join(lines)
