"""MCP 서버 조립: 설정된 툴 묶음(core / korea / physics)만 등록한다."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .app import App
from .config import Settings
from .transport.base import Backend

INSTRUCTIONS = """\
Origin(OriginLab) 제어 MCP — 한국어 환경·물리/전자공학 최적화.
- 사용자는 한국어로 지시한다. 한국어 표현→툴 매핑은 리소스 ilhae://glossary 참고.
- 처음이거나 오류가 나면 origin_status, 설치 직후에는 origin_doctor.
- 측정 파일은 import_data_file(한글 경로·CP949 자동 처리) 또는 물리 분석 툴의 path 인자로 바로 읽는다.
- 상태를 바꾸는 툴은 verify.status 를 돌려준다. verified 가 아니면 반영 실패 가능성을 사용자에게 알리고
  graph_preview 로 실제 그림을 확인한다. 성공을 추측해서 보고하지 않는다.
- 축 제목은 '물리량 (단위)' 형식. 한글이 깨지면 kr_apply_font.
- 논문·보고서 규격은 kr_list_presets → kr_apply_preset, HWP용 그림은 kr_export_for_hwp.
- 파일 경로는 허용 폴더 안의 절대 경로만 쓸 수 있다(origin_status 에서 확인).
"""


def build_server(settings: Settings | None = None, backend: Backend | None = None) -> MCPServer:
    settings = settings or Settings.from_env()
    app = App(settings, backend)
    mcp = MCPServer("origin-ilhae", title="Origin 일해 MCP", instructions=INSTRUCTIONS, version=__version__)
    from .tools import core

    core.register(mcp, app)
    if "korea" in settings.toolsets:
        from .tools import korea

        korea.register(mcp, app)
    if "physics" in settings.toolsets:
        from .tools import physics

        physics.register(mcp, app)
    mcp._ilhae_app = app  # type: ignore[attr-defined]  # 테스트에서 접근
    return mcp
