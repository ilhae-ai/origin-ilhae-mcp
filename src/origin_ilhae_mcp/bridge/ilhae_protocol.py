# -*- coding: utf-8 -*-
"""브리지 통신 규약 (MCP 서버 <-> Origin 내장 Python).

Origin 2021~2023 내장 Python(3.8)에서도 돌아야 하므로 3.8 문법만 사용한다.

한 줄에 JSON 하나(UTF-8, 줄바꿈 구분).
  요청: {"id": 1, "token": "...", "op": "ping", "args": {}}
  응답: {"id": 1, "ok": true, "result": {...}}
        {"id": 1, "ok": false, "error": {"code": "...", "message": "...", "recoverable": true}}
"""
import json

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47021
MAX_LINE_BYTES = 64 * 1024 * 1024  # 대용량 워크시트 대비 64MB


def encode(obj):
    """dict -> UTF-8 바이트 한 줄. ensure_ascii=False로 한글을 그대로 보낸다."""
    return (json.dumps(obj, ensure_ascii=False, default=_default) + "\n").encode("utf-8")


def decode(line):
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    return json.loads(line)


def _default(o):
    # numpy 스칼라·배열 등 JSON이 모르는 타입 처리
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def error_payload(code, message, recoverable=True, next_actions=None):
    return {
        "code": code,
        "message": message,
        "recoverable": recoverable,
        "next_actions": next_actions or [],
    }
