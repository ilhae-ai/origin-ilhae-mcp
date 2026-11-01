"""브리지 TCP 규약: Origin 없이 가짜 디스패처로 실제 소켓 통신을 검증한다."""
import ast
import threading
import time
from pathlib import Path

import pytest

from origin_ilhae_mcp.bridge import ilhae_bridge
from origin_ilhae_mcp.errors import IlhaeError
from origin_ilhae_mcp.transport.bridge_client import BridgeBackend

BRIDGE_DIR = Path(__file__).parents[1] / "src" / "origin_ilhae_mcp" / "bridge"


def _dispatcher(op, args):
    if op == "echo":
        return {"ok": True, "result": {"echo": args.get("text")}}
    if op == "slow":
        time.sleep(1.5)
        return {"ok": True, "result": {}}
    if op == "fail":
        return {"ok": False, "error": {"code": "SHEET_NOT_FOUND", "message": "워크시트 없음",
                                       "recoverable": True, "next_actions": ["project_info"]}}
    return {"ok": False, "error": {"code": "UNKNOWN_OP", "message": op, "recoverable": False}}


@pytest.fixture
def bridge(tmp_path):
    token_file = tmp_path / "token"
    token = ilhae_bridge.load_or_create_token(str(token_file))
    b = ilhae_bridge.Bridge(token, _dispatcher, port=0)
    port = b.start()
    stop = threading.Event()

    def loop():  # Origin의 LabTalk timer 대신 pump()를 반복 호출
        while not stop.is_set():
            b.pump(0.02)

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    yield port, token_file
    stop.set()
    th.join(1)
    b.stop()


def test_roundtrip_korean(bridge):
    port, tf = bridge
    c = BridgeBackend("127.0.0.1", port, tf, timeout=5)
    assert c.call("echo", {"text": "전압 (V) ① µA"}) == {"echo": "전압 (V) ① µA"}


def test_error_payload_becomes_ilhae_error(bridge):
    port, tf = bridge
    c = BridgeBackend("127.0.0.1", port, tf, timeout=5)
    with pytest.raises(IlhaeError) as e:
        c.call("fail")
    assert e.value.code == "SHEET_NOT_FOUND" and e.value.next_actions == ["project_info"]


def test_wrong_token_rejected(bridge, tmp_path):
    port, _ = bridge
    bad = tmp_path / "bad"
    bad.write_text("wrong", encoding="utf-8")
    with pytest.raises(IlhaeError) as e:
        BridgeBackend("127.0.0.1", port, bad, timeout=5).call("echo", {"text": "x"})
    assert e.value.code == "AUTH_FAILED"


def test_timeout_reports_korean(bridge):
    port, tf = bridge
    with pytest.raises(IlhaeError) as e:
        BridgeBackend("127.0.0.1", port, tf, timeout=0.5).call("slow")
    assert e.value.code == "TIMEOUT" and "초 안에" in e.value.message


def test_unreachable(tmp_path):
    tf = tmp_path / "t"
    tf.write_text("x", encoding="utf-8")
    with pytest.raises(IlhaeError) as e:
        BridgeBackend("127.0.0.1", 1, tf, timeout=1).call("ping")
    assert e.value.code == "BRIDGE_UNREACHABLE"


def test_token_file_created_and_reused(tmp_path):
    p = tmp_path / "sub" / "token"
    t1 = ilhae_bridge.load_or_create_token(str(p))
    assert len(t1) >= 32 and ilhae_bridge.load_or_create_token(str(p)) == t1


@pytest.mark.parametrize("name", ["ilhae_protocol.py", "ilhae_ops.py", "ilhae_bridge.py", "ilhae_start.py", "ilhae_poc.py"])
def test_bridge_files_are_python38_compatible(name):
    """Origin 2021~2023 내장 Python 3.8 에서 문법 오류가 나지 않아야 한다."""
    src = (BRIDGE_DIR / name).read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for banned in ("match ", "str | None", "dict[str", "list[str", ":= "):
        assert banned not in src, f"{name}: 3.8 비호환 가능 구문 '{banned}'"


def test_ops_dispatch_without_originpro():
    """originpro 가 없는 환경에서도 dispatch 는 예외 대신 한국어 오류를 돌려준다."""
    from origin_ilhae_mcp.bridge import ilhae_ops

    r = ilhae_ops.dispatch("없는작업", {})
    assert r["ok"] is False and r["error"]["code"] == "UNKNOWN_OP"
    r = ilhae_ops.dispatch("ping", {})
    assert r["ok"] is False and r["error"]["code"] in ("ORIGINPRO_MISSING", "ORIGIN_ERROR")
