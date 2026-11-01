"""테스트·데모용 가짜 Origin(메모리 안에서 동작). ILHAE_BACKEND=fake 로 macOS에서도 서버를 돌려볼 수 있다.

ignore 에 키를 넣으면 Origin이 명령을 '조용히 무시'하는 상황을 흉내 낸다
(예: {"axis.scale"} -> 축 스케일 변경이 반영되지 않음). verify.py 테스트에 쓴다.
"""
from __future__ import annotations

import copy
import os
import struct
import zlib
from typing import Any

from ..errors import IlhaeError

FONT_IDS = {"Arial": 1, "Malgun Gothic": 21, "NanumGothic": 22, "Noto Sans KR": 23,
            "Batang": 24, "HCR Batang": 25, "HCR Dotum": 26, "Times New Roman": 2, "Gulim": 27}


def _tiny_png() -> bytes:
    raw = b"\x00\xff\xff\xff"
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _axis() -> dict[str, Any]:
    return {"from": 0.0, "to": 10.0, "step": 2.0, "scale": "linear", "title": "", "tick_font_size": 22.0}


class FakeBackend:
    name = "fake"

    def __init__(self, ignore: set[str] | None = None) -> None:
        self.ignore = ignore or set()
        self.books: dict[str, dict[str, Any]] = {}
        self.graphs: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.labtalk_log: list[str] = []

    # ------------------------------------------------------------ 공통
    def call(self, op: str, args: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        args = copy.deepcopy(args or {})
        self.calls.append((op, args))
        fn = getattr(self, "op_" + op, None)
        if fn is None:
            raise IlhaeError("UNKNOWN_OP", f"알 수 없는 작업: {op}", recoverable=False)
        return fn(**args)

    def close(self) -> None:
        pass

    def _sheet(self, book: str, sheet: str | None = None) -> dict[str, Any]:
        b = self.books.get(book)
        if b is None:
            raise IlhaeError("SHEET_NOT_FOUND", f"워크시트를 찾을 수 없습니다: {book}")
        name = sheet or next(iter(b["sheets"]))
        if name not in b["sheets"]:
            raise IlhaeError("SHEET_NOT_FOUND", f"워크시트를 찾을 수 없습니다: [{book}]{name}")
        return b["sheets"][name]

    def _col(self, sh: dict[str, Any], col: Any) -> int:
        if isinstance(col, int) or (isinstance(col, str) and col.isdigit()):
            return int(col)
        names = [c["long_name"] for c in sh["columns"]]
        if col in names:
            return names.index(col)
        letters = [chr(65 + i) for i in range(len(names))]
        if col in letters:
            return letters.index(col)
        raise IlhaeError("COLUMN_NOT_FOUND", f"열을 찾을 수 없습니다: {col} (긴 이름 목록: {names})")

    def _graph(self, g: str) -> dict[str, Any]:
        if g not in self.graphs:
            raise IlhaeError("GRAPH_NOT_FOUND", f"그래프를 찾을 수 없습니다: {g}")
        return self.graphs[g]

    # ------------------------------------------------------------ ops
    def op_ping(self) -> dict[str, Any]:
        return {"pong": True, "origin_version": 10.25, "origin_release": "2025b(fake)",
                "python": "3.11.0", "external": False, "protocol": 1}

    def op_project_info(self) -> dict[str, Any]:
        return {"project_path": "",
                "books": [{"name": n, "long_name": b["long_name"],
                           "sheets": [{"name": sn, "rows": max((len(c["data"]) for c in s["columns"]), default=0),
                                       "cols": len(s["columns"]),
                                       "long_names": [c["long_name"] for c in s["columns"]]}
                                      for sn, s in b["sheets"].items()]}
                          for n, b in self.books.items()],
                "graphs": [{"name": n, "long_name": g["long_name"], "layers": len(g["layers"])}
                           for n, g in self.graphs.items()]}

    def op_project_new(self) -> dict[str, Any]:
        self.books.clear()
        self.graphs.clear()
        return {"ok": True}

    def op_project_open(self, path: str, readonly: bool = False) -> dict[str, Any]:
        return {"opened": os.path.isfile(path), "path": path}

    def op_project_save(self, path: str | None = None) -> dict[str, Any]:
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"FAKE-OPJU")
        return {"saved": True, "path": path, "exists": bool(path and os.path.isfile(path))}

    def op_backup_project(self, folder: str, stamp: str) -> dict[str, Any]:
        return {"backed_up": False, "reason": "가짜 백엔드"}

    def op_worksheet_write(self, columns: list[dict[str, Any]], book: str | None = None,
                           sheet: str | None = None, book_long_name: str | None = None,
                           start_col: int = 0) -> dict[str, Any]:
        if book:
            sh = self._sheet(book, sheet)
        else:
            book = f"Book{len(self.books) + 1}"
            self.books[book] = {"long_name": book_long_name or "", "sheets": {"Sheet1": {"columns": []}}}
            sh = self.books[book]["sheets"]["Sheet1"]
            sheet = "Sheet1"
        cols = sh["columns"]
        while len(cols) < start_col + len(columns):
            cols.append({"long_name": "", "units": "", "comments": "", "data": [], "designation": ""})
        for i, c in enumerate(columns):
            cols[start_col + i] = {"long_name": c.get("long_name", ""), "units": c.get("units", ""),
                                   "comments": c.get("comments", ""), "data": list(c.get("data", [])),
                                   "designation": c.get("designation", "")}
        return {"book": book, "sheet": sheet or next(iter(self.books[book]["sheets"])),
                "rows": max((len(c["data"]) for c in cols), default=0), "cols": len(cols),
                "applied": {"long_names": [c["long_name"] for c in cols], "units": [c["units"] for c in cols]}}

    def op_worksheet_read(self, book: str, sheet: str | None = None, max_rows: int = 1000,
                          cols: list[Any] | None = None) -> dict[str, Any]:
        sh = self._sheet(book, sheet)
        idxs = [self._col(sh, c) for c in cols] if cols else range(len(sh["columns"]))
        out = []
        for i in idxs:
            c = sh["columns"][i]
            out.append({"index": i, "long_name": c["long_name"], "units": c["units"], "rows": len(c["data"]),
                        "data": c["data"][:max_rows], "truncated": len(c["data"]) > max_rows})
        return {"book": book, "sheet": sheet or next(iter(self.books[book]["sheets"])), "columns": out}

    def op_graph_create(self, plots: list[dict[str, Any]], template: str = "line", long_name: str = "",
                        plot_type: str = "line") -> dict[str, Any]:
        name = f"Graph{len(self.graphs) + 1}"
        n_layers = 2 if template == "doubley" else 1
        layers = [{"x": _axis(), "y": _axis(), "plots": [], "font": 1, "title_font_size": 22.0,
                   "legend": True, "legend_font_size": 18.0, "symbol_size": 9.0} for _ in range(n_layers)]
        for p in plots:
            sh = self._sheet(p["book"], p.get("sheet"))
            xi, yi = self._col(sh, p["x"]), self._col(sh, p["y"])
            layer = layers[p.get("layer", 0)]
            layer["plots"].append({"name": f"{p['book']}_{sh['columns'][yi]['long_name'] or yi}",
                                   "color": "#000000", "type": p.get("type") or plot_type})
            xs = [v for v in sh["columns"][xi]["data"] if v is not None]
            ys = [v for v in sh["columns"][yi]["data"] if v is not None]
            if xs and ys:
                layer["x"].update({"from": min(xs), "to": max(xs)})
                layer["y"].update({"from": min(ys), "to": max(ys)})
        self.graphs[name] = {"long_name": long_name, "layers": layers, "page": {"width_mm": 162.0, "height_mm": 122.0}}
        info = self.op_graph_info(name)
        info["added"] = [{"layer": p.get("layer", 0), "ok": True} for p in plots]
        return info

    def op_graph_info(self, graph: str) -> dict[str, Any]:
        g = self._graph(graph)
        return {"graph": graph, "long_name": g["long_name"], "page": dict(g["page"]),
                "layers": [{"index": i, "x": dict(l["x"]), "y": dict(l["y"]),
                            "plots": [dict(p) for p in l["plots"]]} for i, l in enumerate(g["layers"])]}

    def op_graph_set_axis(self, graph: str, axis: str = "x", layer: int = 0, start: float | None = None,
                          end: float | None = None, step: float | None = None, scale: str | None = None,
                          title: str | None = None, tick_font_size: float | None = None) -> dict[str, Any]:
        ax = self._graph(graph)["layers"][layer][axis]
        for key, val in (("from", start), ("to", end), ("step", step), ("scale", scale),
                         ("title", title), ("tick_font_size", tick_font_size)):
            if val is not None and f"axis.{key}" not in self.ignore:
                ax[key] = val
        return {"graph": graph, "layer": layer, "axis": axis, "applied": dict(ax)}

    def op_graph_rescale(self, graph: str, layer: int | None = None) -> dict[str, Any]:
        return {"graph": graph, "rescaled": len(self._graph(graph)["layers"]) if layer is None else 1}

    def op_graph_set_options(self, graph: str, layer: int = 0, line_width: float | None = None,
                             symbol_size: float | None = None, colors: list[str] | None = None,
                             legend_show: bool | None = None, legend_font_size: float | None = None,
                             title_font_size: float | None = None) -> dict[str, Any]:
        l = self._graph(graph)["layers"][layer]
        if symbol_size is not None and "symbol_size" not in self.ignore:
            l["symbol_size"] = symbol_size
        if title_font_size is not None:
            l["title_font_size"] = title_font_size
        if legend_show is not None:
            l["legend"] = legend_show
        if legend_font_size is not None:
            l["legend_font_size"] = legend_font_size
        for i, c in enumerate(colors or []):
            if i < len(l["plots"]):
                l["plots"][i]["color"] = c
        applied: dict[str, Any] = {"plots": len(l["plots"]), "title_font_size": l["title_font_size"],
                                   "legend_exists": l["legend"], "symbol_size": l["symbol_size"]}
        if l["legend"]:
            applied["legend_font_size"] = l["legend_font_size"]
        return {"graph": graph, "layer": layer, "applied": applied}

    def op_graph_set_font(self, graph: str, family: str, size: float | None = None) -> dict[str, Any]:
        g = self._graph(graph)
        want = FONT_IDS.get(family, 1)
        res = []
        for i, l in enumerate(g["layers"]):
            if "font" not in self.ignore:
                l["font"] = want
            if size is not None:
                l["title_font_size"] = size
            res.append({"layer": i, "title_font": l["font"], "tick_font": l["font"]})
        return {"graph": graph, "family": family, "font_id": want,
                "applied": {"all_match": all(r["title_font"] == want for r in res), "layers": res}}

    def op_page_set_size(self, graph: str, width_mm: float, height_mm: float) -> dict[str, Any]:
        g = self._graph(graph)
        g["page"] = {"width_mm": round(width_mm, 2), "height_mm": round(height_mm, 2)}
        return {"graph": graph, "applied": dict(g["page"])}

    def op_graph_export(self, graph: str, path: str, fmt: str | None = None, width_px: int | None = None,
                        overwrite: bool = False) -> dict[str, Any]:
        self._graph(graph)
        if os.path.exists(path) and not overwrite:
            raise IlhaeError("FILE_EXISTS", f"이미 파일이 있습니다: {path}")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(_tiny_png())
        return {"graph": graph, "path": path, "exists": True, "bytes": os.path.getsize(path)}

    def op_fit_nlfit(self, book: str, x: Any, y: Any, function: str = "Gauss", sheet: str | None = None,
                     init: dict[str, float] | None = None, fixed: dict[str, float] | None = None) -> dict[str, Any]:
        sh = self._sheet(book, sheet)
        self._col(sh, x), self._col(sh, y)
        return {"function": function, "result": {"note": "가짜 백엔드 — 피팅하지 않음"}}

    def op_labtalk_run(self, code: str) -> dict[str, Any]:
        self.labtalk_log.append(code)
        return {"executed": True}

    def op_labtalk_get(self, name: str, kind: str = "str") -> dict[str, Any]:
        return {"name": name, "value": "" if kind == "str" else 0.0}

    def op_kr_roundtrip(self, workdir: str | None = None) -> dict[str, Any]:
        checks = [{"name": n, "ok": True, "expected": "한글", "actual": "한글", "note": "fake"}
                  for n in ("labtalk_var_via_api", "labtalk_literal", "column_long_name",
                            "axis_title", "font_malgun_gothic")]
        return {"all_ok": True, "checks": checks, "origin": self.op_ping()}
