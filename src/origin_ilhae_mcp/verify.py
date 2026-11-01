"""요청한 값과 Origin에서 다시 읽은 값을 비교한다.

Origin은 잘못된 명령을 에러 없이 무시하는 경우가 많다. 그래서 툴 응답에
"verified / mismatch / unverified" 판정을 넣어 AI가 성공을 과신하지 않게 한다.
"""
from __future__ import annotations

import math
from typing import Any


def _same(a: Any, b: Any, rel: float, abs_: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_)
    return a == b


def compare(requested: dict[str, Any], applied: dict[str, Any] | None,
            rel: float = 1e-3, abs_: float = 1e-9) -> dict[str, Any]:
    req = {k: v for k, v in requested.items() if v is not None}
    if not req:
        return {"status": "verified", "mismatches": []}
    if not applied:
        return {"status": "unverified", "mismatches": [],
                "note": "Origin에서 값을 다시 읽지 못했습니다. graph_preview로 눈으로 확인하세요."}
    mismatches = []
    missing = []
    for k, v in req.items():
        if k not in applied:
            missing.append(k)
            continue
        if not _same(v, applied[k], rel, abs_):
            mismatches.append({"key": k, "requested": v, "applied": applied[k]})
    status = "mismatch" if mismatches else ("partial" if missing else "verified")
    out: dict[str, Any] = {"status": status, "mismatches": mismatches}
    if missing:
        out["unchecked"] = missing
    if mismatches:
        out["note"] = "요청이 Origin에 그대로 반영되지 않았습니다. 값·옵션 이름을 확인하세요."
    return out
