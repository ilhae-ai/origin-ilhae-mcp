from __future__ import annotations

from typing import Any, Protocol


class Backend(Protocol):
    """Origin에 작업(op)을 보내는 경로. 모든 경로가 같은 op 이름(bridge/ilhae_ops.OPS)을 쓴다."""

    name: str

    def call(self, op: str, args: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        """성공하면 result dict, 실패하면 IlhaeError."""
        ...

    def close(self) -> None: ...
