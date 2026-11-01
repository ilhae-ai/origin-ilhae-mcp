"""국내 규격 그림 프리셋(presets/*.json) 로더.

수치는 일반적인 관행을 바탕으로 한 초깃값이다. verified=false 인 프리셋은
해당 학회·학교의 투고 규정으로 확인한 뒤 JSON을 고쳐 쓰도록 응답에 안내한다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from importlib import resources

from ..errors import IlhaeError


@dataclass
class Preset:
    id: str
    name_ko: str
    width_mm: float
    height_mm: float
    font: str
    title_font_size: float
    tick_font_size: float
    legend_font_size: float
    line_width: float
    symbol_size: float
    dpi: int
    export_format: str
    verified: bool
    source: str
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def load_presets() -> dict[str, Preset]:
    out: dict[str, Preset] = {}
    pkg = resources.files("origin_ilhae_mcp") / "presets"
    for f in sorted(pkg.iterdir(), key=lambda p: p.name):
        if f.name.endswith(".json"):
            p = Preset(**json.loads(f.read_text(encoding="utf-8")))
            out[p.id] = p
    return out


def get_preset(pid: str) -> Preset:
    presets = load_presets()
    if pid not in presets:
        raise IlhaeError("PRESET_NOT_FOUND", f"프리셋이 없습니다: {pid}",
                         next_actions=[f"사용 가능: {', '.join(presets)}"])
    return presets[pid]


def width_px(width_mm: float, dpi: int) -> int:
    return round(width_mm / 25.4 * dpi)
