"""사용자(와 AI)가 다음 행동을 고를 수 있게 한국어 메시지·복구 가능 여부·다음 조치를 담는 오류."""
from __future__ import annotations

from typing import Any


class IlhaeError(Exception):
    def __init__(self, code: str, message: str, *, recoverable: bool = True,
                 next_actions: list[str] | None = None, detail: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.next_actions = next_actions or []
        self.detail = detail

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IlhaeError":
        return cls(payload.get("code", "ORIGIN_ERROR"), payload.get("message", "알 수 없는 오류"),
                   recoverable=payload.get("recoverable", True),
                   next_actions=payload.get("next_actions") or [])

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message,
                             "recoverable": self.recoverable, "next_actions": self.next_actions}
        if self.detail is not None:
            d["detail"] = self.detail
        return d
