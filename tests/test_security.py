from pathlib import Path

import pytest

from origin_ilhae_mcp.errors import IlhaeError
from origin_ilhae_mcp.security import check_labtalk, resolve_path
from origin_ilhae_mcp.verify import compare


def test_resolve_path_allowed_and_denied(tmp_path: Path):
    roots = [tmp_path / "허용"]
    roots[0].mkdir()
    ok = resolve_path(str(roots[0] / "측정.csv"), roots, "read")
    assert ok.name == "측정.csv"
    with pytest.raises(IlhaeError, match="허용된 폴더 밖"):
        resolve_path(str(tmp_path / "다른곳" / "a.csv"), roots, "read")
    with pytest.raises(IlhaeError, match=r"\.\."):
        resolve_path(str(roots[0] / ".." / "a.csv"), roots, "read")
    with pytest.raises(IlhaeError, match="절대 경로"):
        resolve_path("상대경로.csv", roots, "read")
    with pytest.raises(IlhaeError, match="확장자"):
        resolve_path(str(roots[0] / "a.exe"), roots, "export")
    with pytest.raises(IlhaeError, match="파일이 없습니다"):
        resolve_path(str(roots[0] / "없음.csv"), roots, "read", must_exist=True)


def test_prefix_trick_is_rejected(tmp_path: Path):
    roots = [tmp_path / "data"]
    with pytest.raises(IlhaeError):
        resolve_path(str(tmp_path / "data_evil" / "a.csv"), roots, "read")


@pytest.mark.parametrize("code", [
    'run -pyf "x.py";', "py.exec(1)", "del -f c:\\a.txt", "exit;", "system.path.program$ = 1",
    "dll -a my.dll", 'run -py "import os"',
])
def test_labtalk_blocked(code):
    with pytest.raises(IlhaeError, match="차단"):
        check_labtalk(code)


@pytest.mark.parametrize("code", ["layer.x.from = 0;", "legend -r;", 'xb.text$ = "전압 (V)";'])
def test_labtalk_allowed(code):
    check_labtalk(code)


def test_verify_compare():
    assert compare({"from": 1.0, "scale": "log10"}, {"from": 1.0000001, "scale": "log10"})["status"] == "verified"
    r = compare({"scale": "log10"}, {"scale": "linear"})
    assert r["status"] == "mismatch" and r["mismatches"][0]["applied"] == "linear"
    assert compare({"title": "x"}, None)["status"] == "unverified"
    assert compare({"title": "x", "foo": 1}, {"title": "x"})["status"] == "partial"
    assert compare({"title": None}, {})["status"] == "verified"
