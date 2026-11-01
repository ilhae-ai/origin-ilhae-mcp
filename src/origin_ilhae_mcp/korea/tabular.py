"""측정 데이터 파일(CSV/TSV/공백 구분) 해석.

장비 파일은 앞부분에 메타데이터, 그다음 헤더(와 단위 행), 그다음 숫자 데이터가 오는 경우가 많다.
- 숫자 행이 연속으로 시작되는 위치를 데이터 시작으로 본다.
- 그 바로 위의 텍스트 행을 헤더로, 헤더와 데이터 사이의 짧은 행을 단위 행으로 본다.
- "전압(V)", "Current [mA]", "I / A" 같은 헤더는 긴 이름과 단위로 나눈다.
- 열의 물리량 역할(voltage, current ...)을 추정해 물리 분석 툴이 열을 자동으로 고르게 한다.

Origin 대신 서버(Python)가 파일을 읽으므로, 한글 경로·CP949 문제가 Origin까지 가지 않는다.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

# ---------------------------------------------------------------- 헤더 -> 이름/단위

_PAREN = re.compile(r"^(.*?)\s*[\(\[]\s*([^()\[\]]{1,15}?)\s*[\)\]]\s*$")
_SLASH = re.compile(r"^(.*?\S)\s+/\s+(\S{1,10})$")


def split_header(h: str) -> tuple[str, str]:
    h = h.strip().strip('"').strip("'").strip()
    m = _PAREN.match(h)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    m = _SLASH.match(h)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return h, ""


# ---------------------------------------------------------------- 단위 -> SI 배율

_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0,
           "k": 1e3, "M": 1e6, "G": 1e9}
_BASE_UNITS = ("V", "A", "F", "Hz", "s", "Ω", "ohm", "W", "S")


def si_factor(units: str) -> float:
    """'mA' -> 1e-3, 'V' -> 1, 'kHz' -> 1e3. 모르는 단위는 1."""
    u = units.strip()
    for base in sorted(_BASE_UNITS, key=len, reverse=True):
        if u.endswith(base):
            pre = u[: -len(base)]
            if pre in _PREFIX:
                return _PREFIX[pre]
    return 1.0


# ---------------------------------------------------------------- 물리량 역할 추정

_ROLE_RULES: list[tuple[str, list[str], set[str]]] = [
    # (역할, 이름 키워드(소문자, 공백·_ 제거 후 일치/접두), 단위)
    ("gate_voltage", ["vg", "vgs", "gatevoltage", "게이트전압"], set()),
    ("drain_voltage", ["vd", "vds", "drainvoltage", "드레인전압"], set()),
    ("drain_current", ["id", "ids", "draincurrent", "드레인전류"], set()),
    ("gate_current", ["ig", "igs", "gatecurrent", "게이트전류", "누설전류"], set()),
    ("voltage", ["v", "voltage", "bias", "전압", "인가전압", "vin", "vout"], {"V", "mV", "kV", "uV", "µV"}),
    ("current", ["i", "current", "전류"], {"A", "mA", "uA", "µA", "nA", "pA"}),
    ("capacitance", ["c", "cap", "capacitance", "cp", "정전용량", "커패시턴스"], {"F", "pF", "nF", "uF", "µF"}),
    ("frequency", ["f", "freq", "frequency", "주파수"], {"Hz", "kHz", "MHz", "GHz"}),
    ("time", ["t", "time", "시간", "sec"], {"s", "ms", "us", "µs", "ns"}),
    ("temperature", ["temp", "temperature", "온도"], {"K", "°C", "℃", "C"}),
    ("phase", ["phase", "위상"], {"deg", "°", "rad"}),
    ("gain_db", ["gain", "이득", "magnitude", "mag"], {"dB"}),
    ("wavelength", ["wavelength", "lambda", "파장"], {"nm", "um", "µm"}),
    ("intensity", ["intensity", "counts", "세기", "강도", "signal", "신호"], {"a.u.", "counts", "cps"}),
]


def guess_role(name: str, units: str) -> str:
    key = re.sub(r"[\s_\-\.]", "", name).lower()
    for role, names, _ in _ROLE_RULES:
        if key in names:
            return role
    u = units.strip()
    for role, _, unit_set in _ROLE_RULES:
        if u and u in unit_set:
            return role
    for role, names, _ in _ROLE_RULES:
        if any(len(n) >= 3 and key.startswith(n) for n in names):
            return role
    return ""


# ---------------------------------------------------------------- 장비 프로필

@dataclass
class Profile:
    id: str
    name: str
    match_any: list[str] = field(default_factory=list)
    delimiter: str | None = None
    row_prefix: dict[str, str] | None = None  # 예: B1500 {"header": "DataName", "data": "DataValue"}
    notes: str = ""


def load_profiles() -> list[Profile]:
    out = []
    pkg = resources.files("origin_ilhae_mcp") / "instruments"
    for f in sorted(pkg.iterdir(), key=lambda p: p.name):
        if f.name.endswith(".json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(Profile(**d))
    # 형식이 뚜렷한(행 표지가 있는) 프로필을 먼저 검사해 일반 프로필에 가로채이지 않게 한다
    out.sort(key=lambda p: (p.row_prefix is None, p.id))
    return out


def detect_profile(lines: list[str], profiles: list[Profile] | None = None) -> Profile | None:
    head = "\n".join(lines[:40]).lower()
    for p in profiles if profiles is not None else load_profiles():
        if p.match_any and any(k.lower() in head for k in p.match_any):
            return p
    return None


# ---------------------------------------------------------------- 해석

@dataclass
class Column:
    long_name: str
    units: str
    data: list[float | None]
    role: str = ""
    raw_header: str = ""


@dataclass
class Table:
    columns: list[Column]
    meta: dict[str, str]
    delimiter: str
    profile: str | None
    header_line: int | None
    data_start: int
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"columns": [{"index": i, "long_name": c.long_name, "units": c.units, "role": c.role,
                             "rows": len(c.data)} for i, c in enumerate(self.columns)],
                "meta": self.meta, "delimiter": {"\t": "탭", ",": "쉼표", ";": "세미콜론", "ws": "공백"}.get(
                    self.delimiter, self.delimiter), "profile": self.profile, "warnings": self.warnings}


def _num(s: str) -> float | None:
    s = s.strip().strip('"')
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        if s.lower() in ("nan", "inf", "-inf", "+inf"):
            return float(s)
        raise


def _is_num(s: str) -> bool:
    try:
        return _num(s) is not None
    except ValueError:
        return False


def _split(line: str, delim: str) -> list[str]:
    if delim == "ws":
        return line.split()
    row = next(csv.reader(io.StringIO(line), delimiter=delim), [])
    while row and row[-1].strip() == "":
        row.pop()
    return [c.strip() for c in row]


def _numeric_row(fields: list[str]) -> bool:
    vals = [f for f in fields if f.strip() != ""]
    if not vals:
        return False
    return _is_num(fields[0]) and sum(_is_num(v) for v in vals) / len(vals) >= 0.8


def _sniff(lines: list[str]) -> str:
    sample = [l for l in lines if l.strip()][:200]
    best, best_score = "ws", 0
    for d in ("\t", ",", ";"):
        counts = [l.count(d) for l in sample if l.count(d) > 0]
        if not counts:
            continue
        mode = max(set(counts), key=counts.count)
        score = counts.count(mode) * (mode > 0)
        if score > best_score:
            best, best_score = d, score
    return best


_BRACKETED = re.compile(r"^[\(\[]\s*[^()\[\]]{0,10}\s*[\)\]]$")
_OTHER_UNITS = {"K", "°C", "℃", "%", "dB", "deg", "°", "rad", "a.u.", "au", "counts", "cps", "nm", "um", "µm",
                "mm", "cm", "m", "min", "h", "Ohm", "ohm", "Ω", "kΩ", "MΩ", "W", "mW", "S", "A/cm2", "F/cm2"}


def _is_unit_token(f: str) -> bool:
    """괄호로 감싼 값이거나 실제 단위 이름일 때만 단위로 본다('Vg', 'Id' 같은 열 이름과 구분)."""
    if _BRACKETED.match(f):
        return True
    if f in _OTHER_UNITS:
        return True
    for base in sorted(_BASE_UNITS, key=len, reverse=True):
        if f.endswith(base) and f[: -len(base)] in _PREFIX:
            return True
    return False


def _looks_like_units(fields: list[str]) -> bool:
    vals = [f for f in fields if f]
    return bool(vals) and all(_is_unit_token(f) for f in vals)


def parse_table(text: str, delimiter: str | None = None, profile: str | None = "auto") -> Table:
    lines = text.splitlines()
    prof: Profile | None = None
    if profile == "auto":
        prof = detect_profile(lines)
    elif profile:
        prof = next((p for p in load_profiles() if p.id == profile), None)
    delim = delimiter or (prof.delimiter if prof and prof.delimiter else None) or _sniff(lines)
    rows = [_split(l, delim) if l.strip() else [] for l in lines]
    warnings: list[str] = []

    # B1500 처럼 각 행 앞에 'DataName'/'DataValue' 표지가 붙는 형식
    if prof and prof.row_prefix:
        rows = _strip_prefix(rows, prof.row_prefix.get("header"), prof.row_prefix.get("data"))

    start = None
    for i, r in enumerate(rows):
        if r and _numeric_row(r):
            nxt = next((rows[j] for j in range(i + 1, min(i + 4, len(rows))) if rows[j]), None)
            if nxt is None or (_numeric_row(nxt) and len(nxt) == len(r)):
                start = i
                break
    if start is None:
        raise ValueError("숫자 데이터 행을 찾지 못했습니다. 구분자나 파일 형식을 확인하세요.")
    ncols = len(rows[start])

    data_rows: list[list[str]] = []
    for r in rows[start:]:
        if not r:
            if data_rows:
                break
            continue
        if not _numeric_row(r):
            warnings.append(f"데이터 뒤에 숫자가 아닌 행이 있어 거기서 읽기를 멈췄습니다: {','.join(r)[:60]}")
            break
        data_rows.append(r)

    # 헤더·단위 행 찾기
    above = [i for i in range(start - 1, max(-1, start - 6), -1) if rows[i]]
    header_idx = units_idx = None
    cand = [i for i in above[:2] if len(rows[i]) >= ncols and not _numeric_row(rows[i])]
    if len(cand) == 2 and _looks_like_units(rows[cand[0]][:ncols]):
        units_idx, header_idx = cand[0], cand[1]
    elif cand:
        header_idx = cand[0]
    header = rows[header_idx][:ncols] if header_idx is not None else [f"Col{j + 1}" for j in range(ncols)]
    units_row = rows[units_idx][:ncols] if units_idx is not None else None

    meta: dict[str, str] = {}
    meta_end = header_idx if header_idx is not None else start
    for r in rows[:meta_end]:
        if len(r) >= 2 and r[0]:
            meta[r[0].rstrip(":").strip()] = ", ".join(x for x in r[1:] if x)
        elif len(r) == 1 and ":" in r[0]:
            k, v = r[0].split(":", 1)
            meta[k.strip()] = v.strip()

    cols: list[Column] = []
    for j in range(ncols):
        name, unit = split_header(header[j]) if j < len(header) else (f"Col{j + 1}", "")
        if units_row is not None and j < len(units_row) and units_row[j]:
            unit = units_row[j].strip("()[] ")
        vals: list[float | None] = []
        for r in data_rows:
            try:
                vals.append(_num(r[j]) if j < len(r) else None)
            except ValueError:
                vals.append(None)
        cols.append(Column(long_name=name or f"Col{j + 1}", units=unit, data=vals,
                           role=guess_role(name, unit), raw_header=header[j] if j < len(header) else ""))
    short = [len(r) for r in data_rows if len(r) < ncols]
    if short:
        warnings.append(f"열 개수가 모자란 행 {len(short)}개는 빈 값으로 채웠습니다.")
    return Table(cols, meta, delim, prof.id if prof else None, header_idx, start, warnings)


def _strip_prefix(rows: list[list[str]], hp: str | None, dp: str | None) -> list[list[str]]:
    """표지가 있는 행은 첫 칸을 떼고, 표지 없는 행은 메타데이터(텍스트)일 때만 남긴다."""
    out = []
    for r in rows:
        if r and r[0] in (hp, dp):
            out.append(r[1:])
        elif r and _numeric_row(r):
            out.append([])  # 표지 없는 숫자 행은 데이터로 오인하지 않게 버린다
        else:
            out.append(r)
    return out
