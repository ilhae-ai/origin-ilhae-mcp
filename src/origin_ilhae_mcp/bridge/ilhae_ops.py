# -*- coding: utf-8 -*-
"""Origin 조작 모음 — 브리지(Origin 내장 Python)와 COM 경로(외부 originpro)가 공유한다.

규칙
- Python 3.8 문법만 사용 (Origin 2021~2023 내장 Python).
- 모든 함수는 키워드 인자만 받고 JSON 직렬화 가능한 dict를 돌려준다.
- 상태를 바꾸는 함수는 실행 후 값을 다시 읽어 "applied"로 돌려준다.
  (명령이 에러 없이 무시되는 Origin 특성 때문. 판정은 서버의 verify.py가 한다)
- 대화상자를 띄우는 API(messagebox, file_dialog, asksave=True)는 쓰지 않는다.

[PoC 필요] 표시가 붙은 부분은 Windows 실기에서 동작을 확인해야 한다.
docs/설계서.md 의 "Phase 0 검증 항목" 참고.
"""
import os
import sys
import tempfile

try:
    from . import ilhae_protocol as P  # 패키지로 import될 때 (COM 경로)
except ImportError:  # Origin 안에서 단독 모듈로 import될 때 (브리지)
    import ilhae_protocol as P  # noqa: F401

_OP = None
_EXTERNAL = False

# Origin 내부 버전 번호 -> 제품명
ORIGIN_RELEASES = [
    (9.80, "2021"), (9.85, "2021b"), (9.90, "2022"), (9.95, "2022b"),
    (10.00, "2023"), (10.05, "2023b"), (10.10, "2024"), (10.15, "2024b"),
    (10.20, "2025"), (10.25, "2025b"), (10.30, "2026"), (10.35, "2026b"),
]

AXIS_SCALES = {"linear": 1, "log10": 2, "ln": 8, "log2": 9, "reciprocal": 5}
AXIS_SCALES_REV = dict((v, k) for k, v in AXIS_SCALES.items())
PLOT_TYPES = {"line": "l", "scatter": "s", "line_symbol": "y", "column": "c"}


class OpError(Exception):
    def __init__(self, code, message, recoverable=True, next_actions=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.next_actions = next_actions or []


# ---------------------------------------------------------------- 공통 도우미

def init_external():
    """COM 경로: 외부 Python에서 이미 실행 중인 Origin에 붙는다."""
    global _EXTERNAL
    _EXTERNAL = True
    op = _op()
    try:
        op.attach()  # 실행 중인 Origin 인스턴스에 연결 [PoC 필요]
    except Exception:
        pass
    try:
        op.set_show(True)
    except Exception:
        pass
    return {"attached": True}


def _op():
    global _OP
    if _OP is None:
        try:
            import originpro as op
        except ImportError:
            raise OpError("ORIGINPRO_MISSING",
                          "originpro 모듈을 찾을 수 없습니다. Origin 2021 이상 또는 "
                          "'pip install originpro'가 필요합니다.", recoverable=False)
        _OP = op
    return _OP


def _lt(cmd):
    _op().lt_exec(cmd)


def _lt_str(expr):
    """LabTalk 문자열 식을 읽는다. 따옴표 문제를 피하려고 임시 문자열 변수를 거친다."""
    _lt("ilhae_s$ = %s;" % expr)
    return _op().get_lt_str("ilhae_s")


def _set_lt_text(target, text):
    """텍스트 객체(xb, yl 등)에 문자열 지정. 한글이 LabTalk 소스 코드를 거치지 않도록
    Python API(set_lt_str)로 변수에 넣은 뒤 대입한다."""
    _op().set_lt_str("ilhae_s", text)
    _lt("%s.text$ = ilhae_s$;" % target)


def _lt_num(expr):
    return _op().lt_float(expr)


def _version_name(v):
    name = None
    for num, label in ORIGIN_RELEASES:
        if v + 1e-6 >= num:
            name = label
    return name or ("unknown(%s)" % v)


def _find_sheet(book, sheet=None):
    op = _op()
    ref = "[%s]%s" % (book, sheet) if sheet else book
    wks = op.find_sheet("w", ref)
    if wks is None and sheet is None:
        b = op.find_book("w", book)
        if b is not None:
            wks = b[0]
    if wks is None:
        raise OpError("SHEET_NOT_FOUND", "워크시트를 찾을 수 없습니다: %s" % ref,
                      next_actions=["project_info 로 책(book)·시트 이름을 확인하세요."])
    return wks


def _find_graph(graph):
    gp = _op().find_graph(graph)
    if gp is None:
        raise OpError("GRAPH_NOT_FOUND", "그래프를 찾을 수 없습니다: %s" % graph,
                      next_actions=["project_info 로 그래프 이름을 확인하세요."])
    return gp


def _layer(gp, layer):
    try:
        return gp[int(layer)]
    except Exception:
        raise OpError("LAYER_NOT_FOUND", "레이어 %s 가 없습니다." % layer)


def _activate_layer(gp, layer):
    _lt("win -a %s;" % gp.name)
    _lt("page.active = %d;" % (int(layer) + 1))


def _col_index(wks, col):
    """열 지정: 0부터 시작하는 번호, 짧은 이름(A), 긴 이름(전압) 모두 허용."""
    if isinstance(col, int):
        return col
    s = str(col)
    if s.isdigit():
        return int(s)
    lnames = list(wks.get_labels("L"))
    if s in lnames:
        return lnames.index(s)
    # 짧은 이름(A, B ...) 비교 — 시트를 활성화한 상태에서 LabTalk로 읽는다
    for i in range(wks.cols):
        try:
            wks.lt_exec("ilhae_s$ = wks.col%d.name$;" % (i + 1))
            if _op().get_lt_str("ilhae_s") == s:
                return i
        except Exception:
            break
    raise OpError("COLUMN_NOT_FOUND", "열을 찾을 수 없습니다: %s (긴 이름 목록: %s)" % (s, lnames))


def _clean(values):
    out = []
    for v in values:
        if v is None:
            out.append(None)
        elif isinstance(v, float) and v != v:  # NaN
            out.append(None)
        else:
            out.append(v)
    return out


# ---------------------------------------------------------------- 연결/정보

def ping():
    op = _op()
    v = op.org_ver()
    return {
        "pong": True,
        "origin_version": v,
        "origin_release": _version_name(v),
        "python": sys.version.split()[0],
        "external": _EXTERNAL,
        "protocol": P.PROTOCOL_VERSION,
    }


def project_info():
    op = _op()
    books, graphs = [], []
    for b in op.pages("w"):
        sheets = []
        for s in b:
            sheets.append({"name": s.name, "rows": s.rows, "cols": s.cols,
                           "long_names": list(s.get_labels("L"))})
        books.append({"name": b.name, "long_name": b.lname, "sheets": sheets})
    for g in op.pages("g"):
        graphs.append({"name": g.name, "long_name": g.lname, "layers": len(list(g))})
    return {"project_path": _lt_str("system.project.path$") + _lt_str("system.project.name$"),
            "books": books, "graphs": graphs}


# ---------------------------------------------------------------- 프로젝트

def project_new():
    _op().new(asksave=False)
    return {"ok": True}


def project_open(path, readonly=False):
    if not os.path.isfile(path):
        raise OpError("FILE_NOT_FOUND", "프로젝트 파일이 없습니다: %s" % path)
    ok = _op().open(file=path, readonly=readonly, asksave=False)
    return {"opened": bool(ok), "path": path}


def project_save(path=None):
    op = _op()
    if path:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)  # 폴더가 없으면 Origin이 대화상자를 띄울 수 있어 미리 만든다
        ok = op.save(path)
    else:
        ok = op.save()
    saved = path if path else None
    return {"saved": bool(ok), "path": saved, "exists": bool(saved and os.path.isfile(saved))}


def backup_project(folder, stamp):
    """현재 프로젝트를 덮어쓰지 않는 사본으로 백업. 경로가 없는(저장 안 된) 프로젝트는 건너뛴다."""
    import shutil
    cur = _lt_str("system.project.path$") + _lt_str("system.project.name$")
    if not cur or not os.path.isfile(cur):
        return {"backed_up": False, "reason": "프로젝트가 아직 파일로 저장되지 않았습니다."}
    _op().save()
    if not os.path.isdir(folder):
        os.makedirs(folder)
    base, ext = os.path.splitext(os.path.basename(cur))
    dst = os.path.join(folder, "%s_%s%s" % (base, stamp, ext))
    shutil.copy2(cur, dst)
    return {"backed_up": True, "path": dst}


# ---------------------------------------------------------------- 워크시트

def worksheet_write(columns, book=None, sheet=None, book_long_name=None, start_col=0):
    """columns: [{"data": [...], "long_name": "전압", "units": "V", "comments": "",
                  "designation": "X"|"Y"|"E"|"" }]"""
    op = _op()
    if book:
        wks = _find_sheet(book, sheet)
    else:
        wks = op.new_sheet("w", lname=book_long_name or "")
    need = int(start_col) + len(columns)
    if wks.cols < need:
        wks.cols = need
    for i, c in enumerate(columns):
        idx = int(start_col) + i
        wks.from_list(idx, _clean(c.get("data", [])), lname=c.get("long_name", ""),
                      units=c.get("units", ""), comments=c.get("comments", ""),
                      axis=c.get("designation", ""))
    b = wks.get_book()
    return {
        "book": b.name, "sheet": wks.name, "rows": wks.rows, "cols": wks.cols,
        "applied": {"long_names": list(wks.get_labels("L")),
                    "units": list(wks.get_labels("U"))},
    }


def worksheet_read(book, sheet=None, max_rows=1000, cols=None):
    wks = _find_sheet(book, sheet)
    idxs = [_col_index(wks, c) for c in cols] if cols else list(range(wks.cols))
    lnames = list(wks.get_labels("L"))
    units = list(wks.get_labels("U"))
    out = []
    for i in idxs:
        data = list(wks.to_list(i))
        total = len(data)
        out.append({"index": i, "long_name": lnames[i] if i < len(lnames) else "",
                    "units": units[i] if i < len(units) else "",
                    "rows": total, "data": _clean(data[:int(max_rows)]),
                    "truncated": total > int(max_rows)})
    return {"book": wks.get_book().name, "sheet": wks.name, "columns": out}


# ---------------------------------------------------------------- 그래프

def graph_create(plots, template="line", long_name="", plot_type="line"):
    """plots: [{"book","sheet","x","y","yerr"(선택),"layer"(선택, 0/1), "type"(선택)}]
    이중 Y축은 template="doubley" 와 layer=1 로 지정."""
    op = _op()
    gp = op.new_graph(template=template, lname=long_name or "")
    added = []
    for p in plots:
        wks = _find_sheet(p["book"], p.get("sheet"))
        gl = _layer(gp, p.get("layer", 0))
        ptype = PLOT_TYPES.get(p.get("type") or plot_type, "l")
        kw = {}
        if p.get("yerr") is not None:
            kw["colyerr"] = _col_index(wks, p["yerr"])  # [PoC 필요] add_plot 인자 이름
        plot = gl.add_plot(wks, coly=_col_index(wks, p["y"]), colx=_col_index(wks, p["x"]),
                           type=ptype, **kw)
        added.append({"layer": p.get("layer", 0), "ok": plot is not None})
    for gl in gp:
        gl.rescale()
    info = graph_info(graph=gp.name)
    info["added"] = added
    return info


def graph_info(graph):
    gp = _find_graph(graph)
    layers = []
    for i, gl in enumerate(gp):
        _activate_layer(gp, i)
        layer = {"index": i, "plots": []}
        for ax in ("x", "y"):
            layer[ax] = {
                "from": _lt_num("layer.%s.from" % ax),
                "to": _lt_num("layer.%s.to" % ax),
                "step": _lt_num("layer.%s.inc" % ax),
                "scale": AXIS_SCALES_REV.get(int(_lt_num("layer.%s.type" % ax)), "other"),
                "tick_font_size": _lt_num("layer.%s.label.pt" % ax),
            }
        layer["x"]["title"] = _lt_str("xb.text$")
        layer["y"]["title"] = _lt_str("yl.text$")
        for pl in gl.plot_list():
            try:
                layer["plots"].append({"name": pl.name, "color": str(pl.color)})
            except Exception:
                layer["plots"].append({"name": getattr(pl, "name", "?")})
        layers.append(layer)
    return {"graph": gp.name, "long_name": gp.lname, "layers": layers,
            "page": page_size_read(gp)}


def graph_set_axis(graph, axis="x", layer=0, start=None, end=None, step=None,
                   scale=None, title=None, tick_font_size=None):
    gp = _find_graph(graph)
    _activate_layer(gp, layer)
    ax = axis.lower()
    if ax not in ("x", "y"):
        raise OpError("BAD_AXIS", "axis 는 'x' 또는 'y' 입니다.")
    if scale is not None:
        if scale not in AXIS_SCALES:
            raise OpError("BAD_SCALE", "지원 스케일: %s" % ", ".join(AXIS_SCALES))
        _lt("layer.%s.type = %d;" % (ax, AXIS_SCALES[scale]))
    if start is not None:
        _lt("layer.%s.from = %r;" % (ax, float(start)))
    if end is not None:
        _lt("layer.%s.to = %r;" % (ax, float(end)))
    if step is not None:
        _lt("layer.%s.inc = %r;" % (ax, float(step)))
    if title is not None:
        _set_lt_text("xb" if ax == "x" else "yl", title)
    if tick_font_size is not None:
        _lt("layer.%s.label.pt = %r;" % (ax, float(tick_font_size)))
    applied = {
        "from": _lt_num("layer.%s.from" % ax), "to": _lt_num("layer.%s.to" % ax),
        "step": _lt_num("layer.%s.inc" % ax),
        "scale": AXIS_SCALES_REV.get(int(_lt_num("layer.%s.type" % ax)), "other"),
        "title": _lt_str("xb.text$" if ax == "x" else "yl.text$"),
        "tick_font_size": _lt_num("layer.%s.label.pt" % ax),
    }
    return {"graph": gp.name, "layer": layer, "axis": ax, "applied": applied}


def graph_rescale(graph, layer=None):
    gp = _find_graph(graph)
    targets = [_layer(gp, layer)] if layer is not None else list(gp)
    for gl in targets:
        gl.rescale()
    return {"graph": gp.name, "rescaled": len(targets)}


def graph_set_options(graph, layer=0, line_width=None, symbol_size=None, colors=None,
                      legend_show=None, legend_font_size=None, title_font_size=None):
    """스타일 일괄 설정. 옵션 이름 검증은 서버 쪽에서 끝낸 뒤 호출된다."""
    gp = _find_graph(graph)
    gl = _layer(gp, layer)
    _activate_layer(gp, layer)
    plots = gl.plot_list()
    for i, pl in enumerate(plots):
        if line_width is not None:
            pl.set_cmd("-w %d" % int(float(line_width) * 500))  # LabTalk: 1pt = 500 [PoC 필요]
        if symbol_size is not None:
            pl.symbol_size = float(symbol_size)
        if colors and i < len(colors):
            pl.color = colors[i]
    if title_font_size is not None:
        _lt("xb.fsize = %r; yl.fsize = %r;" % (float(title_font_size), float(title_font_size)))
    if legend_show is not None:
        if legend_show:
            _lt("legend -r;")
        else:
            _lt("label -r legend;")
    if legend_font_size is not None:
        _lt("legend.fsize = %r;" % float(legend_font_size))
    applied = {"plots": len(plots),
               "title_font_size": _lt_num("xb.fsize"),
               "legend_exists": bool(_lt_num("exist(legend)"))}
    if legend_font_size is not None and applied["legend_exists"]:
        applied["legend_font_size"] = _lt_num("legend.fsize")
    if plots and symbol_size is not None:
        try:
            applied["symbol_size"] = float(plots[0].symbol_size)
        except Exception:
            pass
    return {"graph": gp.name, "layer": layer, "applied": applied}


def graph_set_font(graph, family, size=None):
    """그래프의 축 제목·눈금 라벨·범례 글꼴을 한 번에 바꾼다(한글 글꼴 적용용)."""
    gp = _find_graph(graph)
    want = _lt_num("font(%s)" % family)  # [PoC 필요] 미설치 글꼴일 때 반환값
    results = []
    for i, _gl in enumerate(gp):
        _activate_layer(gp, i)
        cmds = ["xb.font = font(%s);" % family, "yl.font = font(%s);" % family,
                "layer.x.label.font = font(%s);" % family,
                "layer.y.label.font = font(%s);" % family]
        if _lt_num("exist(yr)"):
            cmds.append("yr.font = font(%s);" % family)
        if _lt_num("exist(legend)"):
            cmds.append("legend.font = font(%s);" % family)
        for c in cmds:
            _lt(c)
        if size is not None:
            _lt("xb.fsize = %r; yl.fsize = %r;" % (float(size), float(size)))
        results.append({"layer": i, "title_font": _lt_num("xb.font"),
                        "tick_font": _lt_num("layer.x.label.font")})
    ok = all(r["title_font"] == want and r["tick_font"] == want for r in results)
    return {"graph": gp.name, "family": family, "font_id": want,
            "applied": {"all_match": ok, "layers": results}}


def page_size_read(gp):
    """페이지 크기(mm). page.width/height 는 page.resx(dpi) 기준 픽셀로 가정 [PoC 필요]"""
    try:
        _lt("win -a %s;" % gp.name)
        res = _lt_num("page.resx") or 300.0
        return {"width_mm": round(_lt_num("page.width") / res * 25.4, 2),
                "height_mm": round(_lt_num("page.height") / res * 25.4, 2)}
    except Exception:
        return {}


def page_set_size(graph, width_mm, height_mm):
    gp = _find_graph(graph)
    _lt("win -a %s;" % gp.name)
    res = _lt_num("page.resx") or 300.0
    _lt("page.width = %d; page.height = %d;" % (round(width_mm / 25.4 * res),
                                                 round(height_mm / 25.4 * res)))
    return {"graph": gp.name, "applied": page_size_read(gp)}


def graph_export(graph, path, fmt=None, width_px=None, overwrite=False):
    gp = _find_graph(graph)
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)  # 대화상자 예방
    if os.path.exists(path):
        if not overwrite:
            raise OpError("FILE_EXISTS", "이미 파일이 있습니다: %s" % path,
                          next_actions=["overwrite=true 로 다시 호출하거나 다른 파일명을 쓰세요."])
        os.remove(path)  # 덮어쓰기 확인 대화상자 예방
    try:
        if width_px:
            gp.save_fig(path, width=int(width_px))
        else:
            gp.save_fig(path)
    except TypeError:
        gp.save_fig(path)
    ok = os.path.isfile(path)
    return {"graph": gp.name, "path": path, "exists": ok,
            "bytes": os.path.getsize(path) if ok else 0}


# ---------------------------------------------------------------- 분석

def fit_nlfit(book, x, y, function="Gauss", sheet=None, init=None, fixed=None):
    """Origin 내장 비선형 피팅(NLFit). 함수 이름은 Origin 내장 함수명(Gauss, Lorentz, Line, ExpDec1 ...)."""
    op = _op()
    wks = _find_sheet(book, sheet)
    f = op.NLFit(function)
    f.set_data(wks, _col_index(wks, y), _col_index(wks, x))
    for name, val in (fixed or {}).items():
        f.fix_param(name, val)
    for name, val in (init or {}).items():
        try:
            f.set_param(name, val)  # [PoC 필요] 버전별 메서드 이름
        except Exception:
            _lt("nlfn.p.%s = %r;" % (name, float(val)))
    f.fit()
    r = f.result()
    return {"function": function, "result": r}


# ---------------------------------------------------------------- LabTalk (서버에서 허용·차단 검사 후에만 호출)

def labtalk_run(code):
    _lt(code)
    return {"executed": True}


def labtalk_get(name, kind="str"):
    if kind == "str":
        return {"name": name, "value": _op().get_lt_str(name.rstrip("$"))}
    return {"name": name, "value": _lt_num(name)}


# ---------------------------------------------------------------- 한글 왕복 시험 (doctor / Phase 0 PoC)

KR_SAMPLE = u"한글 테스트 ① 전압 µA Ω"


def kr_roundtrip(workdir=None):
    """한글이 Origin 안팎을 오갈 때 깨지는지 항목별로 검사한다."""
    op = _op()
    checks = []

    def add(name, expected, actual, note=""):
        checks.append({"name": name, "ok": expected == actual,
                       "expected": expected, "actual": actual, "note": note})

    # 1) Python API로 LabTalk 문자열 변수 왕복
    op.set_lt_str("ilhae_t", KR_SAMPLE)
    add("labtalk_var_via_api", KR_SAMPLE, op.get_lt_str("ilhae_t"))

    # 2) LabTalk 소스 코드 안의 한글 리터럴 (lt_exec 경로의 코드페이지 영향 확인)
    op.lt_exec(u'ilhae_u$ = "한글 리터럴";')
    add("labtalk_literal", u"한글 리터럴", op.get_lt_str("ilhae_u"))

    # 3) 워크시트 긴 이름·단위·주석
    wks = op.new_sheet("w", lname=u"일해_한글시험")
    wks.from_list(0, [1.0, 2.0, 3.0], lname=u"전압", units=u"V", comments=u"한글 주석")
    add("column_long_name", u"전압", list(wks.get_labels("L"))[0])
    add("column_units", u"V", list(wks.get_labels("U"))[0])
    add("column_comments", u"한글 주석", list(wks.get_labels("C"))[0])
    add("book_long_name", u"일해_한글시험", wks.get_book().lname)

    # 4) 그래프 축 제목
    wks.from_list(1, [2.0, 4.0, 6.0], lname=u"전류", units=u"A")
    gp = op.new_graph(template="line")
    gp[0].add_plot(wks, coly=1, colx=0)
    _activate_layer(gp, 0)
    _set_lt_text("xb", u"전압 (V)")
    add("axis_title", u"전압 (V)", _lt_str("xb.text$"))

    # 5) 한글 글꼴 인식 여부
    default_id = _lt_num("font(Arial)")
    malgun = _lt_num("font(Malgun Gothic)")
    checks.append({"name": "font_malgun_gothic", "ok": malgun not in (default_id, -1, 0),
                   "expected": "Arial과 다른 글꼴 번호", "actual": malgun,
                   "note": "같으면 미설치이거나 font() 동작 확인 필요"})

    # 6) 한글 경로 저장·내보내기
    if workdir:
        kdir = os.path.join(workdir, u"한글폴더")
        if not os.path.isdir(kdir):
            os.makedirs(kdir)
        png = os.path.join(kdir, u"그림_테스트.png")
        if os.path.exists(png):
            os.remove(png)
        try:
            gp.save_fig(png)
        except Exception as e:  # noqa: BLE001
            checks.append({"name": "export_korean_path", "ok": False, "expected": png,
                           "actual": repr(e), "note": ""})
        else:
            add("export_korean_path", True, os.path.isfile(png), png)

    # 정리
    for obj in (gp, wks.get_book()):
        try:
            obj.destroy()
        except Exception:
            pass
    return {"all_ok": all(c["ok"] for c in checks), "checks": checks,
            "origin": ping()}


# ---------------------------------------------------------------- 디스패치

OPS = {
    "ping": ping, "init_external": init_external, "project_info": project_info,
    "project_new": project_new, "project_open": project_open, "project_save": project_save,
    "backup_project": backup_project,
    "worksheet_write": worksheet_write, "worksheet_read": worksheet_read,
    "graph_create": graph_create, "graph_info": graph_info, "graph_set_axis": graph_set_axis,
    "graph_rescale": graph_rescale, "graph_set_options": graph_set_options,
    "graph_set_font": graph_set_font, "page_set_size": page_set_size,
    "graph_export": graph_export, "fit_nlfit": fit_nlfit,
    "labtalk_run": labtalk_run, "labtalk_get": labtalk_get, "kr_roundtrip": kr_roundtrip,
}


def dispatch(name, args):
    """{"ok": True, "result": ...} 또는 {"ok": False, "error": ...}"""
    fn = OPS.get(name)
    if fn is None:
        return {"ok": False, "error": P.error_payload("UNKNOWN_OP", "알 수 없는 작업: %s" % name,
                                                      recoverable=False)}
    try:
        return {"ok": True, "result": fn(**(args or {}))}
    except OpError as e:
        return {"ok": False, "error": P.error_payload(e.code, e.message, e.recoverable,
                                                      e.next_actions)}
    except TypeError as e:
        return {"ok": False, "error": P.error_payload("BAD_ARGS", "인자 오류: %s" % e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": P.error_payload(
            "ORIGIN_ERROR", "Origin 작업 중 오류: %s: %s" % (type(e).__name__, e),
            next_actions=["origin_status 로 연결 상태를 확인하세요."])}


def temp_dir():
    d = os.path.join(tempfile.gettempdir(), "origin-ilhae")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d
