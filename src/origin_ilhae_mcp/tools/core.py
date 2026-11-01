"""core 툴: 연결·프로젝트·워크시트·그래프·스타일·피팅·내보내기."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from ..app import App, guard
from ..errors import IlhaeError
from ..korea import paths as kpaths
from ..korea.encoding import read_text
from ..korea.presets import width_px
from ..korea.tabular import parse_table
from ..security import check_labtalk

RO = ToolAnnotations(read_only_hint=True)
DESTRUCTIVE = ToolAnnotations(destructive_hint=True)


class ColumnIn(BaseModel):
    data: list[float | None] = Field(description="열 데이터(빈 값은 null)")
    long_name: str = Field("", description="긴 이름(한글 가능). 예: 전압")
    units: str = Field("", description="단위. 예: V, mA")
    comments: str = Field("", description="주석")
    designation: Literal["X", "Y", "E", "Z", ""] = Field("", description="열 역할(X축, Y축, 오차 E)")


class PlotIn(BaseModel):
    book: str = Field(description="워크북 이름(project_info 의 name)")
    sheet: str | None = Field(None, description="시트 이름. 생략 시 첫 시트")
    x: int | str = Field(description="X 열: 0부터 번호, 짧은 이름(A), 긴 이름(전압) 중 하나")
    y: int | str = Field(description="Y 열")
    yerr: int | str | None = Field(None, description="Y 오차 열(오차막대)")
    layer: int = Field(0, description="레이어. 이중 Y축(template='doubley')의 오른쪽 축은 1")
    type: Literal["line", "scatter", "line_symbol", "column"] | None = None


GRAPH_OPTION_KEYS = {
    "line_width": "선 굵기(pt)", "symbol_size": "점 크기", "colors": "플롯별 색 목록(예: ['#1f77b4', 'red'])",
    "legend_show": "범례 표시 여부", "legend_font_size": "범례 글자 크기(pt)", "title_font_size": "축 제목 글자 크기(pt)",
}


def register(mcp: MCPServer, app: App) -> None:
    g = guard(app)
    s = app.settings

    # ------------------------------------------------------------ 연결·점검
    @mcp.tool(annotations=RO)
    @g
    def origin_status() -> dict[str, Any]:
        """Origin 연결 상태와 보안 설정을 보여준다. 다른 툴이 실패하면 가장 먼저 호출한다."""
        info: dict[str, Any] = {
            "backend": app.backend.name, "toolsets": list(s.toolsets),
            "allowed_roots": [str(r) for r in s.allowed_roots], "labtalk_enabled": s.enable_labtalk,
            "auto_backup": s.auto_backup, "kr_path_mode": s.kr_path_mode, "kr_path_ok": app.kr_path_ok,
        }
        try:
            info["origin"] = app.call("ping", timeout=10)
            info["connected"] = True
        except IlhaeError as e:
            info["connected"] = False
            info["error"] = e.to_dict()
        info["backend"] = app.backend.name
        return info

    @mcp.tool()
    @g
    def origin_doctor(korean_test: bool = True,
                      workdir: Annotated[str | None, Field(description="한글 경로 시험용 폴더(허용 폴더 안). 생략 시 첫 허용 폴더 아래")] = None) -> dict[str, Any]:
        """연결과 한글 처리(문자열·열 이름·축 제목·글꼴·한글 경로)를 점검한다. 설치 직후 한 번 실행 권장.
        결과의 한글 경로 시험이 통과하면 이후 내보내기에서 한글 경로를 직접 쓴다."""
        out: dict[str, Any] = {"origin": app.call("ping", timeout=15)}
        if korean_test:
            base = app.path(workdir, "dir") if workdir else s.allowed_roots[0] / "origin-ilhae-doctor"
            base.mkdir(parents=True, exist_ok=True)
            kr = app.call("kr_roundtrip", timeout=120, workdir=str(base))
            out["korean"] = kr
            path_check = next((c for c in kr["checks"] if c["name"] == "export_korean_path"), None)
            app.save_state(kr_path_ok=bool(path_check and path_check["ok"]),
                           last_doctor=kr.get("origin", {}).get("origin_release"))
            failed = [c["name"] for c in kr["checks"] if not c["ok"]]
            out["summary"] = ("모든 한글 시험 통과" if not failed else
                              f"실패 항목: {', '.join(failed)} — docs/설계서.md 'Phase 0 검증 항목'의 대응 방법 참고")
        return out

    # ------------------------------------------------------------ 프로젝트
    @mcp.tool(annotations=RO)
    @g
    def project_info() -> dict[str, Any]:
        """열린 프로젝트의 워크북·시트·열 긴 이름·그래프 목록."""
        return app.call("project_info")

    @mcp.tool(annotations=DESTRUCTIVE)
    @g
    def project_new(confirm: Annotated[bool, Field(description="저장 안 된 변경을 버리고 새 프로젝트를 만든다면 true")] = False) -> dict[str, Any]:
        """새 프로젝트를 연다. 현재 프로젝트의 저장 안 된 내용은 사라지므로 confirm=true 가 필요하다(사전 자동 백업)."""
        if not confirm:
            raise IlhaeError("CONFIRM_REQUIRED", "저장하지 않은 작업이 사라질 수 있습니다. 사용자 확인 후 confirm=true 로 호출하세요.")
        return {"backup": app.backup(), **app.call("project_new")}

    @mcp.tool()
    @g
    def project_open(path: Annotated[str, Field(description=".opju/.opj 절대 경로(한글 가능)")]) -> dict[str, Any]:
        """프로젝트 파일을 연다(현재 프로젝트는 사전 자동 백업)."""
        p = app.path(path, "project", must_exist=True)
        origin_path, staged = kpaths.for_read(p, s.kr_path_mode, app.kr_path_ok)
        backup = app.backup()
        res = app.call("project_open", path=origin_path)
        res.update({"path": str(p), "korean_path_staged": staged, "backup": backup})
        if staged:
            res["note"] = "한글 경로라 영문 임시 사본을 열었습니다. 저장할 때는 project_save(path=원래 경로)를 쓰세요."
        return res

    @mcp.tool()
    @g
    def project_save(path: Annotated[str | None, Field(description="다른 이름으로 저장할 절대 경로. 생략 시 현재 파일에 저장")] = None) -> dict[str, Any]:
        """프로젝트 저장. 한글 경로는 필요 시 영문 임시 폴더를 거쳐 저장한다."""
        if not path:
            return app.call("project_save")
        target = app.path(path, "project")
        origin_path, finalize, staged = kpaths.for_write(target, s.kr_path_mode, app.kr_path_ok)
        res = app.call("project_save", path=origin_path)
        if staged:
            if target.exists():
                target.unlink()
            finalize()
        res.update({"path": str(target), "exists": target.is_file(), "korean_path_staged": staged})
        return res

    # ------------------------------------------------------------ 워크시트
    @mcp.tool()
    @g
    def worksheet_create(columns: list[ColumnIn],
                         book_long_name: Annotated[str, Field(description="새 워크북 긴 이름(한글 가능)")] = "") -> dict[str, Any]:
        """새 워크북을 만들고 열 데이터를 쓴다. 긴 이름·단위가 실제로 들어갔는지 다시 읽어 확인한다."""
        cols = [c.model_dump() for c in columns]
        res = app.call("worksheet_write", columns=cols, book_long_name=book_long_name)
        res["verify"] = app.verify({"long_names": [c["long_name"] for c in cols]},
                                   {"long_names": res["applied"]["long_names"][:len(cols)]})
        return res

    @mcp.tool(annotations=RO)
    @g
    def worksheet_read(book: str, sheet: str | None = None,
                       columns: Annotated[list[int | str] | None, Field(description="읽을 열(번호/이름). 생략 시 전체")] = None,
                       max_rows: Annotated[int, Field(ge=1, le=100000)] = 200) -> dict[str, Any]:
        """워크시트 데이터를 읽는다. 큰 데이터는 max_rows 로 잘라 읽는다(truncated 표시)."""
        return app.call("worksheet_read", book=book, sheet=sheet, cols=columns, max_rows=max_rows)

    @mcp.tool()
    @g
    def import_data_file(path: Annotated[str, Field(description="CSV/TXT/DAT/TSV 절대 경로(한글 경로 가능)")],
                         book_long_name: str | None = None,
                         encoding: Annotated[str | None, Field(description="생략 시 자동 판별(UTF-8/CP949)")] = None,
                         delimiter: Annotated[str | None, Field(description="생략 시 자동(쉼표·탭·세미콜론·공백)")] = None,
                         profile: Annotated[str, Field(description="장비 프로필 id 또는 'auto'")] = "auto") -> dict[str, Any]:
        """측정 데이터 파일을 Origin 워크북으로 불러온다.
        서버가 파일을 직접 읽으므로 한글 경로·CP949 인코딩이 문제되지 않는다.
        헤더의 '전압(V)'는 긴 이름 '전압', 단위 'V'로 나누고, 열의 물리량 역할(role)을 추정해 알려준다."""
        p = app.path(path, "read", must_exist=True)
        text, enc, why = read_text(p, encoding)
        table = parse_table(text, delimiter, profile)
        cols = [{"data": c.data, "long_name": c.long_name, "units": c.units,
                 "comments": c.role, "designation": "X" if i == 0 else "Y"} for i, c in enumerate(table.columns)]
        res = app.call("worksheet_write", columns=cols, book_long_name=book_long_name or p.stem)
        return {"book": res["book"], "sheet": res["sheet"], "rows": res["rows"], "file": str(p),
                "encoding": enc, "encoding_reason": why, **table.summary(),
                "verify": app.verify({"long_names": [c["long_name"] for c in cols]},
                                     {"long_names": res["applied"]["long_names"][:len(cols)]})}

    # ------------------------------------------------------------ 그래프
    @mcp.tool()
    @g
    def graph_create(plots: list[PlotIn],
                     plot_type: Literal["line", "scatter", "line_symbol", "column"] = "line",
                     template: Annotated[str, Field(description="Origin 그래프 템플릿. 이중 Y축은 'doubley'")] = "line",
                     long_name: str = "") -> dict[str, Any]:
        """워크시트 열로 그래프를 만든다. 생성 후 레이어·플롯 수와 축 범위를 다시 읽어 돌려준다."""
        info = app.call("graph_create", plots=[p.model_dump() for p in plots], template=template,
                        long_name=long_name, plot_type=plot_type)
        n_plots = sum(len(l["plots"]) for l in info["layers"])
        info["verify"] = app.verify({"plots": len(plots)}, {"plots": n_plots})
        return info

    @mcp.tool(annotations=RO)
    @g
    def graph_info(graph: str) -> dict[str, Any]:
        """그래프의 레이어별 축 범위·스케일·제목·플롯 목록과 페이지 크기(mm)."""
        return app.call("graph_info", graph=graph)

    @mcp.tool()
    @g
    def graph_set_axis(graph: str, axis: Literal["x", "y"], layer: int = 0,
                       start: float | None = None, end: float | None = None, step: float | None = None,
                       scale: Literal["linear", "log10", "ln", "log2", "reciprocal"] | None = None,
                       title: Annotated[str | None, Field(description="축 제목(한글 가능). 예: '전압 (V)'")] = None,
                       tick_font_size: float | None = None) -> dict[str, Any]:
        """축 범위·눈금 간격·스케일(로그 등)·제목을 설정하고, 실제 반영 여부를 verify 로 돌려준다."""
        res = app.call("graph_set_axis", graph=graph, axis=axis, layer=layer, start=start, end=end,
                       step=step, scale=scale, title=title, tick_font_size=tick_font_size)
        res["verify"] = app.verify({"from": start, "to": end, "step": step, "scale": scale, "title": title,
                                    "tick_font_size": tick_font_size}, res.get("applied"))
        return res

    @mcp.tool()
    @g
    def graph_rescale(graph: str, layer: int | None = None) -> dict[str, Any]:
        """데이터에 맞게 축 범위를 자동 조정한다."""
        return app.call("graph_rescale", graph=graph, layer=layer)

    @mcp.tool()
    @g
    def graph_set_options(graph: str,
                          options: Annotated[dict[str, Any], Field(description="허용 키: " + ", ".join(
                              f"{k}({v})" for k, v in GRAPH_OPTION_KEYS.items()))],
                          layer: int = 0) -> dict[str, Any]:
        """선 굵기·점 크기·색·범례·제목 글자 크기를 한 번에 설정한다. 모르는 옵션 이름은 거부한다."""
        unknown = sorted(set(options) - set(GRAPH_OPTION_KEYS))
        if unknown:
            raise IlhaeError("UNKNOWN_OPTION", f"지원하지 않는 옵션: {', '.join(unknown)}",
                             next_actions=[f"허용 옵션: {', '.join(GRAPH_OPTION_KEYS)}"])
        res = app.call("graph_set_options", graph=graph, layer=layer, **options)
        req = {k: options.get(k) for k in ("symbol_size", "legend_font_size", "title_font_size")}
        if "legend_show" in options:
            req["legend_exists"] = options["legend_show"]
        res["verify"] = app.verify(req, res.get("applied"))
        return res

    # ------------------------------------------------------------ 분석
    @mcp.tool()
    @g
    def fit_curve(book: str, x: int | str, y: int | str,
                  function: Annotated[str, Field(description="Origin 내장 함수명: Line, Gauss, Lorentz, Voigt, ExpDec1, Allometric1, Boltzmann ...")] = "Gauss",
                  sheet: str | None = None, init: dict[str, float] | None = None,
                  fixed: dict[str, float] | None = None) -> dict[str, Any]:
        """Origin 내장 비선형 피팅(NLFit). 파라미터·오차·R² 등 결과 사전을 돌려준다."""
        return app.call("fit_nlfit", timeout=max(s.timeout, 120), book=book, x=x, y=y, function=function,
                        sheet=sheet, init=init, fixed=fixed)

    # ------------------------------------------------------------ 내보내기·미리보기
    @mcp.tool()
    @g
    def graph_export(graph: str,
                     path: Annotated[str, Field(description="저장 절대 경로. 확장자로 형식 결정(.png .emf .pdf .svg .tif .jpg .eps)")],
                     width_mm: Annotated[float | None, Field(description="래스터(PNG/TIF/JPG) 출력 폭(mm)")] = None,
                     dpi: int = 300, overwrite: bool = False) -> dict[str, Any]:
        """그래프를 그림 파일로 내보낸다. 한글 경로·폴더 자동 생성·덮어쓰기 대화상자 예방을 처리한다."""
        target = app.path(path, "export")
        px = width_px(width_mm, dpi) if width_mm and target.suffix.lower() in (".png", ".tif", ".tiff", ".jpg") else None
        return app.export_to(graph, target, px, overwrite)

    @mcp.tool(annotations=RO)
    @g
    def graph_preview(graph: str, width_px: Annotated[int, Field(ge=200, le=2000)] = 800) -> Image:
        """그래프를 PNG 이미지로 돌려준다. 스타일 변경 후 실제 모습을 눈으로 확인할 때 쓴다."""
        tmp = kpaths.stage_dir() / f"preview_{os.getpid()}_{graph}.png"
        app.call("graph_export", graph=graph, path=str(tmp), width_px=width_px, overwrite=True)
        try:
            return Image(data=Path(tmp).read_bytes(), format="png")
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ------------------------------------------------------------ LabTalk (기본 꺼짐)
    if s.enable_labtalk:
        @mcp.tool(annotations=DESTRUCTIVE)
        @g
        def labtalk_run(code: Annotated[str, Field(description="LabTalk 스크립트")],
                        confirm: Annotated[bool, Field(description="사용자가 실행을 승인했다면 true")] = False) -> dict[str, Any]:
            """[고급] LabTalk 스크립트를 실행한다. 전용 툴로 안 되는 작업에만 쓰고, 사용자 승인(confirm) 필요.
            Python 실행·파일 삭제·외부 프로그램 실행 등은 차단된다. 실행 전 자동 백업."""
            if not confirm:
                raise IlhaeError("CONFIRM_REQUIRED", "LabTalk 실행은 사용자 승인 후 confirm=true 로 호출하세요.")
            check_labtalk(code)
            return {"backup": app.backup(), **app.call("labtalk_run", code=code)}

        @mcp.tool(annotations=RO)
        @g
        def labtalk_get(name: str, kind: Literal["str", "num"] = "num") -> dict[str, Any]:
            """[고급] LabTalk 변수·식 값을 읽는다(문자열 변수는 kind='str')."""
            check_labtalk(name)
            return app.call("labtalk_get", name=name, kind=kind)
