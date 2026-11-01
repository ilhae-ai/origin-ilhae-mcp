"""korea 툴: 한글 글꼴·국내 규격 프리셋·HWP용 내보내기·용어 사전."""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ..app import App, guard
from ..korea import glossary
from ..korea.fonts import korean_capable, resolve_font
from ..korea.paths import safe_filename
from ..korea.presets import get_preset, load_presets, width_px
from ..korea.tabular import load_profiles


def register(mcp: MCPServer, app: App) -> None:
    g = guard(app)

    @mcp.tool()
    @g
    def kr_apply_font(graph: str,
                      font: Annotated[str, Field(description="한글 이름도 가능: 맑은 고딕, 나눔고딕, 본고딕, 바탕, 함초롬바탕 ...")] = "맑은 고딕",
                      size: float | None = None) -> dict[str, Any]:
        """그래프의 축 제목·눈금·범례 글꼴을 한글 글꼴로 바꾼다(한글이 네모로 깨질 때).
        적용 후 글꼴 번호를 다시 읽어 모든 레이어에 반영됐는지 확인한다."""
        family = resolve_font(font)
        res = app.call("graph_set_font", graph=graph, family=family, size=size)
        res["verify"] = app.verify({"all_match": True}, res.get("applied"))
        if not korean_capable(family):
            res["warning"] = f"'{family}'는 한글 글리프가 없을 수 있습니다. 맑은 고딕 등을 권장합니다."
        return res

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    @g
    def kr_list_presets() -> dict[str, Any]:
        """국내 규격 그림 프리셋 목록(학위논문, 학회지 1단·2단, HWP 보고서, 발표)."""
        return {"presets": [p.as_dict() for p in load_presets().values()],
                "note": "verified=false 프리셋은 일반 관행 기반 초깃값입니다. 투고 규정으로 확인 후 presets/*.json 을 수정하세요."}

    @mcp.tool()
    @g
    def kr_apply_preset(graph: str, preset: Annotated[str, Field(description="kr_list_presets 의 id")]) -> dict[str, Any]:
        """프리셋에 맞게 페이지 크기(mm)·글꼴·글자 크기·선 굵기·점 크기를 한 번에 적용하고 항목별로 검증한다."""
        p = get_preset(preset)
        steps: dict[str, Any] = {}
        r = app.call("page_set_size", graph=graph, width_mm=p.width_mm, height_mm=p.height_mm)
        steps["page"] = {**r, "verify": app.verify({"width_mm": p.width_mm, "height_mm": p.height_mm},
                                                   r.get("applied"))}
        r = app.call("graph_set_font", graph=graph, family=resolve_font(p.font), size=p.title_font_size)
        steps["font"] = {**r, "verify": app.verify({"all_match": True}, r.get("applied"))}
        info = app.call("graph_info", graph=graph)
        for layer in info["layers"]:
            i = layer["index"]
            r = app.call("graph_set_options", graph=graph, layer=i, line_width=p.line_width,
                         symbol_size=p.symbol_size, legend_font_size=p.legend_font_size,
                         title_font_size=p.title_font_size)
            steps[f"layer{i}_options"] = {**r, "verify": app.verify(
                {"symbol_size": p.symbol_size, "title_font_size": p.title_font_size}, r.get("applied"))}
            for ax in ("x", "y"):
                r = app.call("graph_set_axis", graph=graph, axis=ax, layer=i, tick_font_size=p.tick_font_size)
                steps[f"layer{i}_{ax}_ticks"] = app.verify({"tick_font_size": p.tick_font_size}, r.get("applied"))
        statuses = [v["verify"]["status"] if isinstance(v, dict) and "verify" in v else v.get("status")
                    for v in steps.values()]
        out = {"graph": graph, "preset": p.as_dict(), "steps": steps,
               "overall": "verified" if all(st == "verified" for st in statuses) else "확인 필요"}
        if not p.verified:
            out["warning"] = f"'{p.name_ko}' 수치는 초깃값입니다({p.source}). {p.notes}"
        return out

    @mcp.tool()
    @g
    def kr_export_for_hwp(graph: str,
                          folder: Annotated[str, Field(description="저장 폴더 절대 경로(한글 가능)")],
                          figure_no: Annotated[int, Field(ge=1, description="그림 번호")],
                          title: Annotated[str, Field(description="그림 제목(파일명에 사용, 한글 가능)")],
                          preset: str = "report_hwp",
                          fmt: Literal["emf", "png"] | None = None,
                          overwrite: bool = False) -> dict[str, Any]:
        """한글(HWP) 문서에 넣을 그림을 '그림{번호}_{제목}.emf' 형식으로 내보낸다.
        EMF는 HWP에서 확대해도 선명하다. PNG는 프리셋 dpi·폭으로 출력한다.
        HWP에서는 [입력]-[그림]으로 넣고, 크기는 프리셋 폭(mm)에 맞춘다."""
        p = get_preset(preset)
        ext = fmt or ("emf" if p.export_format == "emf" else "png")
        name = safe_filename(f"그림{figure_no}_{title}") + "." + ext
        target = app.path(str(app.path(folder, "dir") / name), "export")
        px = width_px(p.width_mm, p.dpi) if ext == "png" else None
        res = app.export_to(graph, target, px, overwrite)
        res.update({"hwp_insert_width_mm": p.width_mm, "caption_suggestion": f"그림 {figure_no}. {title}"})
        return res

    # ------------------------------------------------------------ 리소스·프롬프트
    @mcp.resource("ilhae://glossary", name="한국어 용어 사전", mime_type="text/markdown")
    def glossary_resource() -> str:
        return glossary.to_markdown()

    @mcp.resource("ilhae://presets", name="국내 규격 그림 프리셋", mime_type="application/json")
    def presets_resource() -> str:
        return json.dumps([p.as_dict() for p in load_presets().values()], ensure_ascii=False, indent=2)

    @mcp.resource("ilhae://instruments", name="장비 CSV 프로필", mime_type="application/json")
    def instruments_resource() -> str:
        return json.dumps([vars(p) for p in load_profiles()], ensure_ascii=False, indent=2)

    @mcp.prompt(name="측정데이터_논문그림", description="측정 파일 → 분석 → 규격 그림 → HWP용 내보내기 표준 흐름")
    def paper_figure_flow(file_path: str, preset: str = "thesis_a4") -> str:
        return (
            f"다음 순서로 진행해 주세요.\n"
            f"1. import_data_file(path='{file_path}') 로 불러오고, 열 이름·단위·role 을 확인해 사용자에게 요약\n"
            f"2. 데이터 성격에 맞는 분석 툴 선택(I-V면 iv_diode_analyze, 전달특성이면 transistor_analyze 등). "
            f"애매하면 사용자에게 질문\n"
            f"3. kr_apply_preset(preset='{preset}') 로 규격 적용 후 verify 결과 확인\n"
            f"4. graph_preview 로 결과 그림을 확인하고 축 제목은 '물리량 (단위)' 형식의 한글로 정리\n"
            f"5. kr_export_for_hwp 로 저장하고 파일 경로·캡션 제안을 보고\n"
            f"각 단계의 verify.status 가 verified 가 아니면 그 사실을 숨기지 말고 알려주세요."
        )
