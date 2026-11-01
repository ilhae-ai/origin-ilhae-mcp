"""physics 툴: 물리·전자공학 분석. 계산은 physics/analysis.py(numpy/scipy), 그림은 Origin.

데이터 입력은 두 가지 중 하나:
  - path: 측정 파일(CSV 등)을 직접 지정 → 서버가 읽고 Origin에도 원본 워크북을 만든다
  - book(+sheet): 이미 Origin에 있는 워크시트
열(x, y ...)을 생략하면 열 역할(role: voltage, current ...)로 자동 선택한다.
단위(mA, nF, kHz ...)는 SI로 환산해 계산한다.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..app import App, guard
from ..errors import IlhaeError
from ..korea.encoding import read_text
from ..korea.tabular import guess_role, parse_table, si_factor
from ..physics import analysis as A

Col = Annotated[int | str | None, Field(description="열 번호(0부터)·짧은 이름·긴 이름. 생략 시 역할로 자동 선택")]
Src = Annotated[str | None, Field(description="측정 파일 절대 경로(CSV/TXT). book 과 둘 중 하나")]
Book = Annotated[str | None, Field(description="Origin 워크북 이름. path 와 둘 중 하나")]


class _Data:
    """불러온 열 묶음: long_name, units, role, SI 환산 데이터."""

    def __init__(self, cols: list[dict[str, Any]], book: str | None) -> None:
        self.cols = cols
        self.book = book

    def pick(self, col: int | str | None, roles: list[str], label: str) -> tuple[list[float | None], dict[str, Any]]:
        if col is not None:
            if isinstance(col, int) or (isinstance(col, str) and col.isdigit()):
                c = self.cols[int(col)]
            else:
                c = next((c for c in self.cols if c["long_name"] == col), None)
                if c is None:
                    raise IlhaeError("COLUMN_NOT_FOUND", f"{label} 열을 찾을 수 없습니다: {col}",
                                     next_actions=[f"열 목록: {[c['long_name'] for c in self.cols]}"])
        else:
            c = next((c for r in roles for c in self.cols if c["role"] == r), None)
            if c is None:
                raise IlhaeError("COLUMN_AMBIGUOUS", f"{label} 열을 자동으로 고르지 못했습니다(역할 {roles}).",
                                 next_actions=["열을 직접 지정하세요. 열 목록: "
                                               + ", ".join(f"{i}:{c['long_name']}({c['units']})" for i, c in enumerate(self.cols))])
        f = si_factor(c["units"])
        data = [None if v is None else v * f for v in c["data"]]
        return data, {"long_name": c["long_name"], "units": c["units"], "si_factor": f}


def register(mcp: MCPServer, app: App) -> None:
    g = guard(app)

    def load(path: str | None, book: str | None, sheet: str | None) -> _Data:
        if bool(path) == bool(book):
            raise IlhaeError("BAD_INPUT", "path(측정 파일) 또는 book(Origin 워크북) 중 하나만 지정하세요.")
        if path:
            p = app.path(path, "read", must_exist=True)
            text, _enc, _ = read_text(p)
            t = parse_table(text)
            cols = [{"long_name": c.long_name, "units": c.units, "role": c.role, "data": c.data} for c in t.columns]
            res = app.call("worksheet_write", book_long_name=p.stem,
                           columns=[{"data": c["data"], "long_name": c["long_name"], "units": c["units"],
                                     "comments": c["role"]} for c in cols])
            return _Data(cols, res["book"])
        res = app.call("worksheet_read", book=book, sheet=sheet, max_rows=1_000_000)
        cols = [{"long_name": c["long_name"], "units": c["units"], "data": c["data"],
                 "role": guess_role(c["long_name"], c["units"])} for c in res["columns"]]
        return _Data(cols, book)

    def plot(title: str, columns: list[dict[str, Any]], ys: list[int], x_title: str, y_title: str,
             y_scale: str | None = None, plot_type: str = "line_symbol", y2: int | None = None,
             y2_title: str | None = None) -> dict[str, Any]:
        """결과 열을 새 워크북에 쓰고 그래프를 만든다(0번 열이 X). 축 설정은 검증 결과를 함께 돌려준다."""
        w = app.call("worksheet_write", book_long_name=title, columns=columns)
        plots = [{"book": w["book"], "x": 0, "y": y, "layer": 0} for y in ys]
        template = "line"
        if y2 is not None:
            plots.append({"book": w["book"], "x": 0, "y": y2, "layer": 1})
            template = "doubley"
        info = app.call("graph_create", plots=plots, template=template, long_name=title, plot_type=plot_type)
        gname = info["graph"]
        checks = []
        for axis, layer, ttl, scale in (("x", 0, x_title, None), ("y", 0, y_title, y_scale)) + (
                (("y", 1, y2_title, None),) if y2 is not None else ()):
            r = app.call("graph_set_axis", graph=gname, axis=axis, layer=layer, title=ttl, scale=scale)
            checks.append(app.verify({"title": ttl, "scale": scale}, r.get("applied")))
        if y_scale:
            app.call("graph_rescale", graph=gname)
        status = "verified" if all(c["status"] == "verified" for c in checks) else "확인 필요"
        return {"graph": gname, "result_book": w["book"], "axis_verify": status, "axis_checks": checks}

    def col(name: str, units: str, data: list[float], designation: str = "Y") -> dict[str, Any]:
        return {"long_name": name, "units": units, "data": data, "designation": designation}

    # ------------------------------------------------------------ I-V
    @mcp.tool()
    @g
    def iv_diode_analyze(path: Src = None, book: Book = None, sheet: str | None = None,
                         v: Col = None, i: Col = None, temperature_K: float = 300.0,
                         plot_result: bool = True) -> dict[str, Any]:
        """다이오드 I-V 분석: 반로그 기울기로 이상계수 n·포화전류 I0, Cheung 법으로 직렬저항 Rs.
        결과 그래프는 |I|(로그) - V."""
        d = load(path, book, sheet)
        V, vi = d.pick(v, ["voltage", "drain_voltage"], "전압")
        I, ii = d.pick(i, ["current", "drain_current"], "전류")
        r = A.diode_analyze(V, I, temperature_K)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"V": vi, "I": ii}, **r}
        if plot_result:
            out["plot"] = plot("IV_다이오드분석", [col("전압", "V", der["V"], "X"), col("|전류|", "A", der["abs_I"])],
                               [1], "전압 (V)", "|전류| (A)", y_scale="log10", plot_type="scatter")
        return out

    @mcp.tool()
    @g
    def transistor_analyze(path: Src = None, book: Book = None, sheet: str | None = None,
                           vg: Col = None, id: Col = None,
                           mode: Literal["linear", "saturation"] = "linear",
                           vd: Annotated[float | None, Field(description="측정 드레인 전압(V). linear 모드 Vd/2 보정·이동도에 사용")] = None,
                           width: float | None = None, length: float | None = None,
                           cox_F_per_cm2: Annotated[float | None, Field(description="게이트 절연막 정전용량(F/cm²)")] = None,
                           plot_result: bool = True) -> dict[str, Any]:
        """트랜지스터 전달 특성(Id-Vg): 문턱전압 Vth(접선 외삽), gm 최대, SS(mV/dec), on/off 비, (선택) 이동도.
        결과 그래프: 왼쪽 |Id|(로그), 오른쪽 √|Id|(saturation) 또는 gm(linear)."""
        d = load(path, book, sheet)
        VG, gi = d.pick(vg, ["gate_voltage", "voltage"], "게이트 전압")
        ID, di = d.pick(id, ["drain_current", "current"], "드레인 전류")
        r = A.transistor_analyze(VG, ID, mode, vd, width, length, cox_F_per_cm2)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"Vg": gi, "Id": di}, **r}
        if plot_result:
            right = ("√|Id|", "A^1/2", der["sqrt_abs_Id"]) if mode == "saturation" else ("gm", "S", der["gm"])
            out["plot"] = plot("트랜지스터_전달특성",
                               [col("게이트 전압", "V", der["Vg"], "X"), col("|드레인 전류|", "A", der["abs_Id"]),
                                col(right[0], right[1], right[2])],
                               [1], "게이트 전압 (V)", "|드레인 전류| (A)", y_scale="log10", y2=2,
                               y2_title=f"{right[0]} ({right[1]})")
        return out

    # ------------------------------------------------------------ C-V
    @mcp.tool()
    @g
    def cv_mott_schottky(area_cm2: Annotated[float, Field(gt=0, description="전극 면적(cm²)")],
                         eps_r: Annotated[float, Field(gt=0, description="반도체 비유전율(예: Si 11.7, GaN 8.9, TiO2 ~ 수십)")],
                         path: Src = None, book: Book = None, sheet: str | None = None,
                         v: Col = None, c: Col = None, temperature_K: float = 300.0,
                         v_from: float | None = None, v_to: float | None = None,
                         plot_result: bool = True) -> dict[str, Any]:
        """Mott-Schottky 분석: 1/C²-V 직선에서 평탄대전압 Vfb·도핑 농도 N(cm⁻³)·반도체 형(n/p).
        직선 구간은 v_from~v_to 로 지정하거나 생략 시 R²가 가장 높은 구간을 자동 선택."""
        d = load(path, book, sheet)
        V, vi = d.pick(v, ["voltage"], "전압")
        C, ci = d.pick(c, ["capacitance"], "정전용량")
        rng = (v_from, v_to) if v_from is not None and v_to is not None else None
        r = A.mott_schottky(V, C, area_cm2, eps_r, temperature_K, rng)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"V": vi, "C": ci}, **r}
        if plot_result:
            out["plot"] = plot("CV_모트쇼트키", [col("전압", "V", der["V"], "X"), col("1/C²", "F^-2", der["inv_C2"])],
                               [1], "전압 (V)", "1/C² (F⁻²)", plot_type="scatter")
        return out

    # ------------------------------------------------------------ 스펙트럼·신호
    @mcp.tool()
    @g
    def spectrum_fft(path: Src = None, book: Book = None, sheet: str | None = None,
                     t: Col = None, y: Col = None, window: Literal["hann", "none"] = "hann",
                     log_scale: bool = False, plot_result: bool = True) -> dict[str, Any]:
        """시간 신호의 FFT 진폭 스펙트럼(단측). 지배 주파수와 샘플링 간격 균일성을 함께 보고한다."""
        d = load(path, book, sheet)
        T, ti = d.pick(t, ["time"], "시간")
        Y, yi = d.pick(y, ["voltage", "current", "intensity"], "신호")
        r = A.fft_spectrum(T, Y, window)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"t": ti, "y": yi}, **r}
        if r["irregular_sampling"]:
            out["warning"] = "샘플링 간격이 일정하지 않습니다(1% 이상 편차). FFT 결과가 왜곡될 수 있습니다."
        if plot_result:
            out["plot"] = plot("FFT_스펙트럼", [col("주파수", "Hz", der["frequency"], "X"),
                                               col("진폭", yi["units"], der["amplitude"])],
                               [1], "주파수 (Hz)", f"진폭 ({yi['units'] or 'a.u.'})",
                               y_scale="log10" if log_scale else None, plot_type="line")
        return out

    @mcp.tool()
    @g
    def spectrum_peaks_fit(path: Src = None, book: Book = None, sheet: str | None = None,
                           x: Col = None, y: Col = None,
                           model: Literal["gauss", "lorentz", "voigt"] = "gauss",
                           n_peaks: int | None = None,
                           prominence: Annotated[float, Field(gt=0, lt=1, description="(최대-최소) 대비 피크 돌출 비율")] = 0.05,
                           centers: Annotated[list[float] | None, Field(description="피크 위치를 직접 지정할 때")] = None,
                           plot_result: bool = True) -> dict[str, Any]:
        """스펙트럼 피크 찾기 + 다중 피크 피팅(가우시안·로렌츠·보이트, 상수 기준선). 중심·FWHM·면적·R²."""
        d = load(path, book, sheet)
        X, xi = d.pick(x, ["wavelength", "frequency", "voltage", "time"], "X")
        Y, yi = d.pick(y, ["intensity", "current", "gain_db"], "Y")
        r = A.peaks_fit(X, Y, model, n_peaks, prominence, centers)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"x": xi, "y": yi}, **r}
        if plot_result:
            out["plot"] = plot("피크피팅", [col(xi["long_name"], xi["units"], der["x"], "X"),
                                           col("측정", yi["units"], der["y"]), col("피팅", yi["units"], der["fit"])],
                               [1, 2], f"{xi['long_name']} ({xi['units']})", f"{yi['long_name']} ({yi['units'] or 'a.u.'})",
                               plot_type="line")
        return out

    @mcp.tool()
    @g
    def signal_filter(path: Src = None, book: Book = None, sheet: str | None = None,
                      t: Col = None, y: Col = None,
                      kind: Literal["lowpass", "highpass", "bandpass", "savgol"] = "lowpass",
                      cutoff: Annotated[float | list[float] | None, Field(description="차단 주파수(Hz). bandpass는 [저, 고]")] = None,
                      order: int = 4, window_points: int = 11, polyorder: int = 3,
                      plot_result: bool = True) -> dict[str, Any]:
        """노이즈 제거: Butterworth 필터(위상 지연 없음) 또는 Savitzky-Golay 스무딩. 원신호와 함께 그린다."""
        d = load(path, book, sheet)
        T, ti = d.pick(t, ["time"], "시간")
        Y, yi = d.pick(y, ["voltage", "current", "intensity"], "신호")
        r = A.filter_signal(T, Y, kind, cutoff, order, window_points, polyorder)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"t": ti, "y": yi}, **r}
        if plot_result:
            out["plot"] = plot("필터결과", [col("시간", "s", der["t"], "X"), col("원신호", "", der["raw"]),
                                           col("필터", "", der["filtered"])],
                               [1, 2], "시간 (s)", f"{yi['long_name']}", plot_type="line")
        return out

    @mcp.tool()
    @g
    def bode_plot(path: Src = None, book: Book = None, sheet: str | None = None,
                  f: Col = None, gain_db: Col = None, vin: Col = None, vout: Col = None, phase: Col = None,
                  plot_result: bool = True) -> dict[str, Any]:
        """Bode 선도: 이득(dB)-주파수(로그) + 위상(오른쪽 축). gain_db 열이 없으면 vin·vout 으로 계산.
        -3 dB 차단 주파수를 보고한다."""
        d = load(path, book, sheet)
        F, fi = d.pick(f, ["frequency"], "주파수")
        ph = None
        if phase is not None or any(c["role"] == "phase" for c in d.cols):
            ph, _ = d.pick(phase, ["phase"], "위상")
        if gain_db is not None or any(c["role"] == "gain_db" for c in d.cols):
            G, _ = d.pick(gain_db, ["gain_db"], "이득")
            r = A.bode(F, gain_db=G, phase_deg=ph)
        else:
            VI, _ = d.pick(vin, ["voltage"], "입력 전압")
            VO, _ = d.pick(vout, [], "출력 전압")
            r = A.bode(F, vin=VI, vout=VO, phase_deg=ph)
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"f": fi}, **r}
        if plot_result:
            cols = [col("주파수", "Hz", der["frequency"], "X"), col("이득", "dB", der["gain_dB"])]
            if ph is not None:
                cols.append(col("위상", "°", der["phase_deg"]))
            out["plot"] = plot("Bode선도", cols, [1], "주파수 (Hz)", "이득 (dB)",
                               y2=2 if ph is not None else None, y2_title="위상 (°)" if ph is not None else None)
            app.call("graph_set_axis", graph=out["plot"]["graph"], axis="x", layer=0, scale="log10")
        return out

    @mcp.tool()
    @g
    def arrhenius_fit(path: Src = None, book: Book = None, sheet: str | None = None,
                      temperature: Col = None, rate: Col = None,
                      celsius: Annotated[bool, Field(description="온도 열이 섭씨(°C)면 true")] = False,
                      plot_result: bool = True) -> dict[str, Any]:
        """아레니우스 분석: ln(k) - 1/T 직선 기울기로 활성화 에너지 Ea(eV)."""
        d = load(path, book, sheet)
        T, ti = d.pick(temperature, ["temperature"], "온도")
        K, ki = d.pick(rate, ["current", "intensity"], "속도/물리량")
        r = A.arrhenius(T, K, celsius or ti["units"] in ("°C", "℃", "C"))
        der = r.pop("derived")
        out: dict[str, Any] = {"input": {"T": ti, "k": ki}, **r}
        if plot_result:
            out["plot"] = plot("아레니우스", [col("1000/T", "K^-1", der["inv_T_1000"], "X"), col("ln k", "", der["ln_k"])],
                               [1], "1000/T (K⁻¹)", "ln k", plot_type="scatter")
        return out
