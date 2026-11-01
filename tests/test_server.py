"""MCP 툴 단위의 통합 테스트(가짜 Origin)."""
import asyncio
from pathlib import Path

import numpy as np
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from origin_ilhae_mcp.config import Settings
from origin_ilhae_mcp.physics import analysis as A
from origin_ilhae_mcp.server import build_server
from origin_ilhae_mcp.transport.fake import FakeBackend


def make(tmp_path: Path, ignore=None, **kw):
    s = Settings(backend="fake", allowed_roots=[tmp_path], state_file=tmp_path / "state.json",
                 backup_dir=tmp_path / "backups", **kw)
    fake = FakeBackend(ignore=ignore)
    return build_server(s, fake), fake


def call(mcp, name, **args):
    r = asyncio.run(mcp.call_tool(name, args))
    assert not r.is_error, r.content
    return r.structured_content if r.structured_content is not None else r


def names(mcp):
    return {t.name for t in asyncio.run(mcp.list_tools())}


@pytest.fixture(autouse=True)
def _stage(monkeypatch, tmp_path):
    monkeypatch.setenv("ILHAE_STAGE_DIR", str(tmp_path / "_stage"))


def test_toolsets_and_labtalk_default_off(tmp_path):
    mcp, _ = make(tmp_path)
    n = names(mcp)
    assert {"import_data_file", "kr_apply_preset", "iv_diode_analyze"} <= n
    assert "labtalk_run" not in n
    mcp2, _ = make(tmp_path, toolsets=("core",))
    assert "kr_apply_font" not in names(mcp2) and "transistor_analyze" not in names(mcp2)


def test_import_cp949_korean_path(tmp_path):
    mcp, fake = make(tmp_path)
    p = tmp_path / "측정데이터" / "다이오드.csv"
    p.parent.mkdir()
    p.write_bytes("전압(V),전류(mA)\n0,0.001\n0.5,1.5\n".encode("cp949"))
    r = call(mcp, "import_data_file", path=str(p))
    assert r["encoding"] == "cp949"
    assert [c["long_name"] for c in r["columns"]] == ["전압", "전류"]
    assert r["verify"]["status"] == "verified"
    book = fake.books[r["book"]]
    assert book["long_name"] == "다이오드"


def test_path_outside_allowed_rejected(tmp_path):
    mcp, _ = make(tmp_path / "only")
    with pytest.raises(ToolError, match="PATH_NOT_ALLOWED"):
        asyncio.run(mcp.call_tool("import_data_file", {"path": str(tmp_path / "x.csv")}))


def _graph(mcp):
    w = call(mcp, "worksheet_create", columns=[{"data": [1, 2, 3], "long_name": "전압", "units": "V"},
                                               {"data": [1, 4, 9], "long_name": "전류", "units": "A"}])
    g = call(mcp, "graph_create", plots=[{"book": w["book"], "x": "전압", "y": "전류"}])
    assert g["verify"]["status"] == "verified"
    return g["graph"]


def test_axis_verify_detects_silent_ignore(tmp_path):
    mcp, _ = make(tmp_path)
    g = _graph(mcp)
    r = call(mcp, "graph_set_axis", graph=g, axis="y", scale="log10", title="전류 (A)")
    assert r["verify"]["status"] == "verified"

    mcp2, _ = make(tmp_path, ignore={"axis.scale"})
    g2 = _graph(mcp2)
    r2 = call(mcp2, "graph_set_axis", graph=g2, axis="y", scale="log10")
    assert r2["verify"]["status"] == "mismatch"
    assert r2["verify"]["mismatches"][0]["applied"] == "linear"


def test_graph_options_rejects_unknown(tmp_path):
    mcp, _ = make(tmp_path)
    g = _graph(mcp)
    with pytest.raises(ToolError, match="UNKNOWN_OPTION"):
        asyncio.run(mcp.call_tool("graph_set_options", {"graph": g, "options": {"glow": 1}}))
    r = call(mcp, "graph_set_options", graph=g, options={"symbol_size": 6, "legend_show": False})
    assert r["verify"]["status"] == "verified"


def test_project_new_requires_confirm(tmp_path):
    mcp, _ = make(tmp_path)
    with pytest.raises(ToolError, match="CONFIRM_REQUIRED"):
        asyncio.run(mcp.call_tool("project_new", {}))
    assert call(mcp, "project_new", confirm=True)["ok"] is True


def test_labtalk_enabled_still_blocks(tmp_path):
    mcp, fake = make(tmp_path, enable_labtalk=True)
    assert "labtalk_run" in names(mcp)
    with pytest.raises(ToolError, match="CONFIRM_REQUIRED"):
        asyncio.run(mcp.call_tool("labtalk_run", {"code": "layer.x.from=0;"}))
    with pytest.raises(ToolError, match="LABTALK_BLOCKED"):
        asyncio.run(mcp.call_tool("labtalk_run", {"code": 'run -pyf "a.py";', "confirm": True}))
    call(mcp, "labtalk_run", code="layer.x.from=0;", confirm=True)
    assert fake.labtalk_log == ["layer.x.from=0;"]


def test_kr_font_and_preset(tmp_path):
    mcp, _ = make(tmp_path)
    g = _graph(mcp)
    r = call(mcp, "kr_apply_font", graph=g, font="맑은 고딕")
    assert r["family"] == "Malgun Gothic" and r["verify"]["status"] == "verified"
    p = call(mcp, "kr_apply_preset", graph=g, preset="thesis_a4")
    assert p["overall"] == "verified"
    assert p["steps"]["page"]["applied"] == {"width_mm": 120, "height_mm": 90}
    assert "초깃값" in p["warning"]

    mcp2, _ = make(tmp_path, ignore={"font"})
    g2 = _graph(mcp2)
    assert call(mcp2, "kr_apply_font", graph=g2, font="나눔고딕")["verify"]["status"] == "mismatch"


def test_export_for_hwp_korean_filename(tmp_path):
    mcp, _ = make(tmp_path)
    g = _graph(mcp)
    folder = tmp_path / "보고서 그림"
    r = call(mcp, "kr_export_for_hwp", graph=g, folder=str(folder), figure_no=3, title="소자 전달특성")
    out = Path(r["path"])
    assert out.name == "그림3_소자 전달특성.emf" and out.is_file()
    assert r["korean_path_staged"] is True        # doctor 전이므로 영문 임시 폴더 경유
    assert r["caption_suggestion"] == "그림 3. 소자 전달특성"
    with pytest.raises(ToolError, match="FILE_EXISTS"):
        asyncio.run(mcp.call_tool("kr_export_for_hwp", {"graph": g, "folder": str(folder), "figure_no": 3,
                                                        "title": "소자 전달특성"}))


def test_doctor_sets_kr_path_state(tmp_path):
    mcp, _ = make(tmp_path)
    r = call(mcp, "origin_doctor")
    assert r["summary"] == "모든 한글 시험 통과"


def test_graph_preview_returns_image(tmp_path):
    mcp, _ = make(tmp_path)
    g = _graph(mcp)
    r = asyncio.run(mcp.call_tool("graph_preview", {"graph": g}))
    assert not r.is_error and r.content[0].type == "image"


def test_iv_diode_from_file_end_to_end(tmp_path):
    mcp, fake = make(tmp_path)
    n, i0, vt = 1.8, 1e-11, A.KB * 300 / A.Q
    I = np.logspace(-9, -3, 60)
    V = n * vt * np.log(I / i0 + 1)
    p = tmp_path / "IV측정.csv"
    p.write_text("전압(V),전류(mA)\n" + "\n".join(f"{v:.6g},{i * 1e3:.6g}" for v, i in zip(V, I)), encoding="utf-8")
    r = call(mcp, "iv_diode_analyze", path=str(p))
    assert r["input"]["I"]["si_factor"] == pytest.approx(1e-3)     # mA → A 환산 확인
    assert r["semilog"]["ideality_factor"] == pytest.approx(n, rel=0.03)
    assert r["plot"]["axis_verify"] == "verified"
    layer = fake.graphs[r["plot"]["graph"]]["layers"][0]
    assert layer["y"]["scale"] == "log10" and layer["y"]["title"] == "|전류| (A)"


def test_transistor_from_origin_book(tmp_path):
    mcp, fake = make(tmp_path)
    vg = np.linspace(-1, 3, 81)
    idd = 1e-4 * np.clip(vg - 1, 0, None) ** 2 + 1e-12
    w = call(mcp, "worksheet_create", columns=[{"data": vg.tolist(), "long_name": "Vg", "units": "V"},
                                               {"data": idd.tolist(), "long_name": "Id", "units": "A"}])
    r = call(mcp, "transistor_analyze", book=w["book"], mode="saturation")
    assert r["threshold_voltage_V"] == pytest.approx(1.0, abs=0.05)
    assert len(fake.graphs[r["plot"]["graph"]]["layers"]) == 2      # 이중 Y축


def test_physics_ambiguous_column_message(tmp_path):
    mcp, _ = make(tmp_path)
    w = call(mcp, "worksheet_create", columns=[{"data": [1, 2, 3], "long_name": "가"},
                                               {"data": [1, 2, 3], "long_name": "나"}])
    with pytest.raises(ToolError, match="COLUMN_AMBIGUOUS"):
        asyncio.run(mcp.call_tool("iv_diode_analyze", {"book": w["book"]}))
