"""한국 환경 처리: 인코딩·측정 파일 해석·한글 경로·글꼴·프리셋."""
from pathlib import Path

import pytest

from origin_ilhae_mcp.errors import IlhaeError
from origin_ilhae_mcp.korea import paths as kp
from origin_ilhae_mcp.korea.encoding import detect_encoding, read_text
from origin_ilhae_mcp.korea.fonts import resolve_font
from origin_ilhae_mcp.korea.presets import get_preset, load_presets, width_px
from origin_ilhae_mcp.korea.tabular import guess_role, parse_table, si_factor, split_header

KR_CSV = "측정일,2026-10-31\n시료,다이오드#3\n\n전압(V),전류(mA),온도(℃)\n0.0,0.001,25\n0.1,0.010,25\n0.2,0.100,25\n"


def test_detect_cp949_and_utf8():
    assert detect_encoding(KR_CSV.encode("cp949"))[0] == "cp949"
    assert detect_encoding(KR_CSV.encode("utf-8"))[0] == "utf-8"
    assert detect_encoding(b"\xef\xbb\xbf" + KR_CSV.encode("utf-8"))[0] == "utf-8-sig"


def test_read_text_cp949_file(tmp_path: Path):
    p = tmp_path / "한글폴더" / "측정.csv"
    p.parent.mkdir()
    p.write_bytes(KR_CSV.encode("cp949"))
    text, enc, _ = read_text(p)
    assert enc == "cp949" and "전압" in text


@pytest.mark.parametrize("h,expected", [
    ("전압(V)", ("전압", "V")), ("Current [mA]", ("Current", "mA")), ("I / A", ("I", "A")),
    ("드레인 전류 (µA)", ("드레인 전류", "µA")), ("Vg", ("Vg", "")), ('"온도 (℃)"', ("온도", "℃")),
])
def test_split_header(h, expected):
    assert split_header(h) == expected


@pytest.mark.parametrize("name,units,role", [
    ("전압", "V", "voltage"), ("Vg", "", "gate_voltage"), ("Id", "A", "drain_current"),
    ("전류", "mA", "current"), ("Capacitance", "pF", "capacitance"), ("주파수", "Hz", "frequency"),
    ("Time", "s", "time"), ("온도", "℃", "temperature"), ("이름없음", "nA", "current"),
])
def test_guess_role(name, units, role):
    assert guess_role(name, units) == role


def test_si_factor():
    assert si_factor("mA") == pytest.approx(1e-3)
    assert si_factor("µA") == pytest.approx(1e-6)
    assert si_factor("kHz") == pytest.approx(1e3)
    assert si_factor("V") == 1.0
    assert si_factor("a.u.") == 1.0


def test_parse_korean_csv_with_metadata():
    t = parse_table(KR_CSV)
    assert [c.long_name for c in t.columns] == ["전압", "전류", "온도"]
    assert [c.units for c in t.columns] == ["V", "mA", "℃"]
    assert [c.role for c in t.columns] == ["voltage", "current", "temperature"]
    assert t.columns[1].data == [0.001, 0.010, 0.100]
    assert t.meta["시료"] == "다이오드#3"
    assert t.profile == "kr_generic"


def test_parse_separate_units_row_and_tabs():
    text = "Vg\tId\n(V)\t(A)\n-1\t1e-12\n0\t1e-9\n1\t1e-6\n"
    t = parse_table(text)
    assert t.delimiter == "\t"
    assert [(c.long_name, c.units) for c in t.columns] == [("Vg", "V"), ("Id", "A")]
    assert [c.role for c in t.columns] == ["gate_voltage", "drain_current"]


def test_parse_b1500_rowprefix():
    text = ("SetupTitle, I/V Sweep\nPrimitiveTest, I/V Sweep\nTestParameter, Channel.Unit, SMU1\n"
            "DataName, Vg, Id\nDataValue, -1, 1e-12\nDataValue, 0, 2e-9\nDataValue, 1, 3e-6\n")
    t = parse_table(text)
    assert t.profile == "keysight_b1500"
    assert [c.long_name for c in t.columns] == ["Vg", "Id"]
    assert t.columns[1].data == [1e-12, 2e-9, 3e-6]


def test_parse_whitespace_and_trailing_text():
    text = "# 시간 신호\nt V\n0 0.0\n0.001 0.5\n0.002 1.0\n끝\n"
    t = parse_table(text)
    assert len(t.columns[0].data) == 3
    assert t.warnings


def test_parse_no_numbers_raises():
    with pytest.raises(ValueError, match="숫자 데이터"):
        parse_table("이름,값\n가,나\n")


def test_stage_dir_avoids_korean_temp(monkeypatch, tmp_path: Path):
    kr_tmp = tmp_path / "홍길동" / "Temp"
    kr_tmp.mkdir(parents=True)
    public = tmp_path / "Public"
    monkeypatch.delenv("ILHAE_STAGE_DIR", raising=False)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(kr_tmp))
    monkeypatch.setenv("PUBLIC", str(public))
    d = kp.stage_dir()
    assert str(d).startswith(str(public))


def test_for_write_stages_korean_target(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ILHAE_STAGE_DIR", str(tmp_path / "stage"))
    target = tmp_path / "결과" / "그림1.png"
    origin_path, finalize, staged = kp.for_write(target, "auto", kr_path_ok=False)
    assert staged and origin_path.isascii() or "stage" in origin_path
    Path(origin_path).write_bytes(b"png")
    assert finalize() == target and target.read_bytes() == b"png"
    # doctor 통과 후에는 직접 사용
    assert kp.for_write(target, "auto", kr_path_ok=True)[2] is False
    assert kp.for_write(tmp_path / "a.png", "stage", kr_path_ok=False)[2] is False  # ASCII 경로


def test_safe_filename():
    assert kp.safe_filename('그림1_I/V: "특성"?') == "그림1_I_V_ _특성__"


def test_resolve_font():
    assert resolve_font("맑은 고딕") == "Malgun Gothic"
    assert resolve_font("함초롬바탕") == "HCR Batang"
    assert resolve_font("Arial") == "Arial"
    with pytest.raises(IlhaeError):
        resolve_font("Arial); exit;")


def test_presets_load():
    presets = load_presets()
    assert {"thesis_a4", "kr_journal_single", "kr_journal_double", "report_hwp", "presentation_169"} <= set(presets)
    p = get_preset("report_hwp")
    assert p.width_mm == 150 and p.export_format == "emf"
    assert width_px(85, 600) == 2008
    with pytest.raises(IlhaeError):
        get_preset("없는프리셋")
