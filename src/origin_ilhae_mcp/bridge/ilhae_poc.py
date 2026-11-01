# -*- coding: utf-8 -*-
"""Phase 0 실기 검증 스크립트 — Origin 스크립트 창에서 실행한다(MCP 서버 불필요).

    run -pyf "<설치폴더>\\ilhae_poc.py";

코드에서 [PoC 필요]로 표시한 동작과 한글 처리를 Origin 버전별로 확인하고,
결과를 문서 폴더의 origin-ilhae-poc-<버전>.json 으로 저장한다. 이 파일을 개발자에게 보내면 된다.
Python 3.8 문법만 사용.
"""
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import originpro as op  # noqa: E402
import ilhae_ops as ops  # noqa: E402

results = []


def probe(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        ok = bool(detail.pop("ok", True)) if isinstance(detail, dict) else True
        results.append({"name": name, "ok": ok, "detail": detail, "sec": round(time.time() - t0, 2)})
    except Exception as e:  # noqa: BLE001
        results.append({"name": name, "ok": False, "error": "%s: %s" % (type(e).__name__, e),
                        "trace": traceback.format_exc()[-800:], "sec": round(time.time() - t0, 2)})
    r = results[-1]
    print(u"%s %s" % (u"✓" if r["ok"] else u"✗", name))


def _sample_graph():
    wks = op.new_sheet("w", lname=u"PoC")
    wks.from_list(0, [1.0, 2.0, 3.0, 4.0], lname=u"전압", units="V")
    wks.from_list(1, [1.0, 4.0, 9.0, 16.0], lname=u"전류", units="A")
    wks.from_list(2, [0.1, 0.2, 0.3, 0.4], lname=u"오차", units="A")
    gp = op.new_graph(template="line")
    return wks, gp


def p_add_plot_yerr():
    wks, gp = _sample_graph()
    plot = gp[0].add_plot(wks, coly=1, colx=0, colyerr=2)
    return {"ok": plot is not None, "plots": len(gp[0].plot_list())}


def p_line_width():
    wks, gp = _sample_graph()
    pl = gp[0].add_plot(wks, coly=1, colx=0)
    pl.set_cmd("-w 1000")
    ops._activate_layer(gp, 0)
    return {"note": u"선 굵기가 2pt로 보이는지 눈으로 확인", "graph": gp.name}


def p_font():
    a, m, missing = ops._lt_num("font(Arial)"), ops._lt_num("font(Malgun Gothic)"), ops._lt_num("font(NoSuchFont123)")
    return {"ok": a != m, "arial": a, "malgun": m, "missing_font": missing}


def p_page_size():
    _wks, gp = _sample_graph()
    before = ops.page_size_read(gp)
    after = ops.page_set_size(graph=gp.name, width_mm=120, height_mm=90)["applied"]
    ok = abs(after.get("width_mm", 0) - 120) < 1 and abs(after.get("height_mm", 0) - 90) < 1
    return {"ok": ok, "before": before, "after": after, "resx": ops._lt_num("page.resx")}


def p_save_fig_width():
    _wks, gp = _sample_graph()
    gp[0].add_plot(_wks, coly=1, colx=0)
    path = os.path.join(tempfile.gettempdir(), "ilhae_poc_w.png")
    if os.path.exists(path):
        os.remove(path)
    try:
        gp.save_fig(path, width=1000)
        how = "width 인자 지원"
    except TypeError:
        gp.save_fig(path)
        how = "width 인자 미지원"
    return {"ok": os.path.isfile(path), "how": how, "bytes": os.path.getsize(path) if os.path.isfile(path) else 0}


def p_nlfit():
    wks = op.new_sheet("w", lname="PoCFit")
    xs = [i * 0.1 for i in range(-50, 51)]
    import math
    ys = [3.0 * math.exp(-(x - 0.5) ** 2 / (2 * 0.8 ** 2)) + 0.1 for x in xs]
    wks.from_list(0, xs)
    wks.from_list(1, ys)
    r = ops.fit_nlfit(book=wks.get_book().name, x=0, y=1, function="Gauss", init={"xc": 0.4})
    return {"result": r["result"]}


def p_axis_roundtrip():
    wks, gp = _sample_graph()
    gp[0].add_plot(wks, coly=1, colx=0)
    r = ops.graph_set_axis(graph=gp.name, axis="y", scale="log10", start=0.5, end=20, title=u"전류 (A)")
    a = r["applied"]
    return {"ok": a["scale"] == "log10" and a["title"] == u"전류 (A)", "applied": a}


def p_timer_pump():
    # 브리지 timer 방식이 다른 timer 사용과 충돌하는지 사람이 확인해야 하는 항목
    return {"note": u"브리지 시작 후 Origin 조작(창 이동·메뉴)이 느려지지 않는지, 기존 timer 매크로가 덮어써지는지 확인"}


def main():
    info = ops.ping()
    print(u"[origin-ilhae PoC] Origin %s / Python %s" % (info["origin_release"], info["python"]))
    workdir = os.path.join(os.path.expanduser("~"), "Documents", "origin-ilhae-poc")
    probe("kr_roundtrip", lambda: (lambda r: {"ok": r["all_ok"], "checks": r["checks"]})(ops.kr_roundtrip(workdir=workdir)))
    probe("add_plot_colyerr", p_add_plot_yerr)
    probe("line_width_set_cmd", p_line_width)
    probe("font_function", p_font)
    probe("page_size_mm", p_page_size)
    probe("save_fig_width", p_save_fig_width)
    probe("nlfit_set_param", p_nlfit)
    probe("axis_log_korean_title", p_axis_roundtrip)
    probe("timer_pump_manual", p_timer_pump)
    out = os.path.join(os.path.expanduser("~"), "Documents",
                       "origin-ilhae-poc-%s.json" % info["origin_release"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"origin": info, "results": results}, f, ensure_ascii=False, indent=2)
    failed = [r["name"] for r in results if not r["ok"]]
    print(u"결과 저장: %s" % out)
    print(u"실패: %s" % (", ".join(failed) if failed else u"없음"))


main()
