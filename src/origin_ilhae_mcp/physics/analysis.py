"""물리·전자공학 분석 계산(순수 numpy/scipy). Origin은 그림만 그리고 계산은 여기서 한다.
→ macOS에서도 단위 테스트로 수치를 검증할 수 있다. 입력은 SI 단위(V, A, F, Hz, s, K).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

Q = 1.602176634e-19        # 기본 전하 [C]
KB = 1.380649e-23          # 볼츠만 상수 [J/K]
KB_EV = 8.617333262e-5     # 볼츠만 상수 [eV/K]
EPS0 = 8.8541878128e-12    # 진공 유전율 [F/m]


@dataclass
class LinFit:
    slope: float
    intercept: float
    r2: float
    i0: int = 0
    i1: int = 0

    def as_dict(self) -> dict[str, float]:
        return {"slope": self.slope, "intercept": self.intercept, "r2": self.r2,
                "index_from": self.i0, "index_to": self.i1}


def _arr(*xs: Any) -> list[np.ndarray]:
    out = [np.asarray([np.nan if v is None else v for v in x], dtype=float) for x in xs]
    mask = np.all([np.isfinite(a) for a in out], axis=0)
    return [a[mask] for a in out]


def linfit(x: np.ndarray, y: np.ndarray) -> LinFit:
    if len(x) < 2:
        raise ValueError("직선 피팅에는 점이 2개 이상 필요합니다.")
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return LinFit(float(slope), float(intercept), r2, 0, len(x) - 1)


def best_window(x: np.ndarray, y: np.ndarray, min_points: int, prefer: str = "r2",
                r2_min: float = 0.995) -> LinFit:
    """구간 직선 피팅 자동 선택. prefer='slope' 이면 R²≥r2_min 중 기울기(절댓값)가 가장 큰 구간."""
    n = len(x)
    if n < max(min_points, 2):
        raise ValueError(f"자동 구간 선택에 필요한 점이 부족합니다({n} < {min_points}).")
    best: LinFit | None = None
    for i0 in range(0, n - min_points + 1):
        f = linfit(x[i0:i0 + min_points], y[i0:i0 + min_points])
        f.i0, f.i1 = i0, i0 + min_points - 1
        if best is None:
            best = f
        elif prefer == "slope":
            ok_new, ok_old = f.r2 >= r2_min, best.r2 >= r2_min
            if (ok_new and not ok_old) or (ok_new == ok_old and
                                           (abs(f.slope) > abs(best.slope) if ok_new else f.r2 > best.r2)):
                best = f
        elif f.r2 > best.r2:
            best = f
    assert best is not None
    return best


# ---------------------------------------------------------------- I-V (다이오드)

def diode_analyze(v: list[float], i: list[float], temperature: float = 300.0,
                  window_points: int | None = None) -> dict[str, Any]:
    """이상계수(n), 포화전류(I0) — 반로그 기울기법 / 직렬저항(Rs), n — Cheung 법."""
    V, I = _arr(v, i)
    fwd = (V > 0) & (I > 0)
    Vf, If = V[fwd], I[fwd]
    if len(Vf) < 6:
        raise ValueError("순방향(V>0, I>0) 데이터 점이 6개 미만입니다.")
    order = np.argsort(Vf)
    Vf, If = Vf[order], If[order]
    lnI = np.log(If)
    w = window_points or max(5, len(Vf) // 5)
    semi = best_window(Vf, lnI, w, prefer="slope")
    vt = KB * temperature / Q
    n_semi = 1.0 / (semi.slope * vt)
    i0 = float(np.exp(semi.intercept))

    out: dict[str, Any] = {
        "temperature_K": temperature,
        "semilog": {"ideality_factor": n_semi, "saturation_current_A": i0,
                    "fit": semi.as_dict(), "V_range": [float(Vf[semi.i0]), float(Vf[semi.i1])]},
    }
    # Cheung: dV/d(lnI) = I·Rs + n·kT/q  (전류가 큰 순방향 영역)
    hi = If >= np.max(If) * 0.1
    if np.count_nonzero(hi) >= 5:
        dv_dlni = np.gradient(Vf[hi], lnI[hi])
        ok = np.isfinite(dv_dlni)
        if np.count_nonzero(ok) >= 3:
            ch = linfit(If[hi][ok], dv_dlni[ok])
            out["cheung"] = {"series_resistance_ohm": ch.slope, "ideality_factor": ch.intercept / vt,
                             "fit": ch.as_dict()}
    out["derived"] = {"V": Vf.tolist(), "abs_I": If.tolist(), "ln_I": lnI.tolist()}
    return out


# ---------------------------------------------------------------- 트랜지스터 전달 특성

def transistor_analyze(vg: list[float], id_: list[float], mode: str = "linear", vd: float | None = None,
                       width: float | None = None, length: float | None = None,
                       cox: float | None = None) -> dict[str, Any]:
    """문턱전압(Vth), 최대 gm, SS(mV/dec), on/off 비, (선택) 이동도.
    mode='linear': |Id|-Vg 접선 외삽(Vd/2 보정), mode='saturation': √|Id|-Vg 접선 외삽.
    이동도: width·length 같은 단위, cox [F/cm²] → μ [cm²/V·s]."""
    Vg, Id = _arr(vg, id_)
    order = np.argsort(Vg)
    Vg, Id = Vg[order], Id[order]
    absI = np.abs(Id)
    if len(Vg) < 5:
        raise ValueError("데이터 점이 5개 미만입니다.")
    if mode == "saturation":
        y = np.sqrt(absI)
    elif mode == "linear":
        y = absI
    else:
        raise ValueError("mode 는 'linear' 또는 'saturation' 입니다.")
    dy = np.gradient(y, Vg)
    k = int(np.argmax(np.abs(dy)))
    vth = float(Vg[k] - y[k] / dy[k])
    if mode == "linear" and vd is not None:
        vth -= vd / 2.0
    carrier = "n형(전자)" if dy[k] > 0 else "p형(정공)"
    gm = np.gradient(absI, Vg)
    pos = absI > 0
    logI = np.full_like(absI, np.nan)
    logI[pos] = np.log10(absI[pos])
    dlog = np.gradient(logI, Vg)
    finite = np.isfinite(dlog) & (np.abs(dlog) > 0)
    ss = float(1000.0 / np.max(np.abs(dlog[finite]))) if np.any(finite) else None
    out: dict[str, Any] = {
        "mode": mode, "carrier_type": carrier, "threshold_voltage_V": vth,
        "tangent_point": {"Vg": float(Vg[k]), "value": float(y[k]), "slope": float(dy[k])},
        "gm_max_S": float(np.max(np.abs(gm))),
        "subthreshold_swing_mV_per_dec": ss,
        "on_off_ratio": float(np.max(absI) / np.min(absI[pos])) if np.any(pos) else None,
    }
    if width and length and cox:
        if mode == "linear" and vd:
            out["mobility_cm2_per_Vs"] = float(length / (width * cox * abs(vd)) * out["gm_max_S"])
        elif mode == "saturation":
            out["mobility_cm2_per_Vs"] = float(2 * length / (width * cox) * dy[k] ** 2)
    out["derived"] = {"Vg": Vg.tolist(), "abs_Id": absI.tolist(), "gm": np.abs(gm).tolist(),
                      "sqrt_abs_Id": np.sqrt(absI).tolist()}
    return out


# ---------------------------------------------------------------- C-V (Mott-Schottky)

def mott_schottky(v: list[float], c: list[float], area_cm2: float, eps_r: float,
                  temperature: float = 300.0, v_range: tuple[float, float] | None = None) -> dict[str, Any]:
    """1/C² - V 직선에서 평탄대전압(Vfb)과 도핑 농도(N, cm⁻³). C는 [F](소자 전체)."""
    V, C = _arr(v, c)
    order = np.argsort(V)
    V, C = V[order], C[order]
    y = 1.0 / C ** 2
    if v_range:
        m = (V >= min(v_range)) & (V <= max(v_range))
        fit = linfit(V[m], y[m])
        idx = np.nonzero(m)[0]
        fit.i0, fit.i1 = int(idx[0]), int(idx[-1])
    else:
        fit = best_window(V, y, max(5, len(V) * 3 // 10))
    a_m2 = area_cm2 * 1e-4
    n_m3 = 2.0 / (Q * eps_r * EPS0 * a_m2 ** 2 * abs(fit.slope))
    vfb = -fit.intercept / fit.slope - KB * temperature / Q
    return {
        "flat_band_voltage_V": float(vfb),
        "doping_cm3": float(n_m3 * 1e-6),
        "semiconductor_type": "n형" if fit.slope > 0 else "p형",
        "fit": fit.as_dict(), "V_range": [float(V[fit.i0]), float(V[fit.i1])],
        "derived": {"V": V.tolist(), "inv_C2": y.tolist()},
    }


# ---------------------------------------------------------------- 스펙트럼·신호

def fft_spectrum(t: list[float], y: list[float], window: str = "hann") -> dict[str, Any]:
    T, Y = _arr(t, y)
    dt = np.diff(T)
    step = float(np.median(dt))
    irregular = bool(np.max(np.abs(dt - step)) > 0.01 * step)
    w = np.hanning(len(Y)) if window == "hann" else np.ones(len(Y))
    spec = np.fft.rfft((Y - np.mean(Y)) * w)
    amp = 2.0 * np.abs(spec) / np.sum(w)
    f = np.fft.rfftfreq(len(Y), step)
    k = int(np.argmax(amp[1:]) + 1) if len(amp) > 1 else 0
    return {"sample_interval_s": step, "sampling_rate_Hz": 1.0 / step, "irregular_sampling": irregular,
            "dominant_frequency_Hz": float(f[k]), "dominant_amplitude": float(amp[k]),
            "window": window, "derived": {"frequency": f.tolist(), "amplitude": amp.tolist()}}


def _gauss(x, a, c, s):  # noqa: ANN001
    return a * np.exp(-((x - c) ** 2) / (2 * s ** 2))


def _lorentz(x, a, c, g):  # noqa: ANN001
    return a * g ** 2 / ((x - c) ** 2 + g ** 2)


def _voigt(x, area, c, s, g):  # noqa: ANN001
    from scipy.special import voigt_profile

    return area * voigt_profile(x - c, abs(s), abs(g))


def peaks_fit(x: list[float], y: list[float], model: str = "gauss", n_peaks: int | None = None,
              prominence: float = 0.05, centers: list[float] | None = None) -> dict[str, Any]:
    """피크 찾기 + 다중 피크 피팅(+ 상수 기준선). prominence는 (최대-최소) 대비 비율."""
    from scipy.optimize import curve_fit
    from scipy.signal import find_peaks, peak_widths

    X, Y = _arr(x, y)
    order = np.argsort(X)
    X, Y = X[order], Y[order]
    span = float(np.max(Y) - np.min(Y)) or 1.0
    if centers:
        idx = [int(np.argmin(np.abs(X - c))) for c in centers]
    else:
        found, props = find_peaks(Y, prominence=prominence * span)
        idx = [int(i) for i in found[np.argsort(props["prominences"])[::-1]]]
        if n_peaks:
            idx = idx[:n_peaks]
    if not idx:
        raise ValueError("피크를 찾지 못했습니다. prominence를 낮추거나 centers를 지정하세요.")
    idx.sort()
    dx = float(np.median(np.diff(X)))
    widths = peak_widths(Y, idx, rel_height=0.5)[0] * dx
    base0 = float(np.min(Y))
    p0: list[float] = []
    for i, wid in zip(idx, widths):
        h = float(Y[i] - base0)
        sig = max(wid / 2.3548, dx)
        if model == "gauss":
            p0 += [h, float(X[i]), sig]
        elif model == "lorentz":
            p0 += [h, float(X[i]), max(wid / 2, dx)]
        elif model == "voigt":
            p0 += [h * sig * 2.5066, float(X[i]), sig / 2, max(wid / 4, dx)]
        else:
            raise ValueError("model 은 gauss, lorentz, voigt 중 하나입니다.")
    p0.append(base0)
    npar = {"gauss": 3, "lorentz": 3, "voigt": 4}[model]
    fn = {"gauss": _gauss, "lorentz": _lorentz, "voigt": _voigt}[model]

    def total(xx, *p):  # noqa: ANN001
        out = np.full_like(xx, p[-1], dtype=float)
        for j in range(len(idx)):
            out += fn(xx, *p[j * npar:(j + 1) * npar])
        return out

    popt, pcov = curve_fit(total, X, Y, p0=p0, maxfev=20000)
    perr = np.sqrt(np.clip(np.diag(pcov), 0, None))
    fitted = total(X, *popt)
    ss_res = float(np.sum((Y - fitted) ** 2))
    ss_tot = float(np.sum((Y - np.mean(Y)) ** 2))
    peaks = []
    for j in range(len(idx)):
        p = popt[j * npar:(j + 1) * npar]
        e = perr[j * npar:(j + 1) * npar]
        if model == "gauss":
            fwhm, area, height = 2.3548 * abs(p[2]), p[0] * abs(p[2]) * np.sqrt(2 * np.pi), p[0]
        elif model == "lorentz":
            fwhm, area, height = 2 * abs(p[2]), p[0] * np.pi * abs(p[2]), p[0]
        else:
            fg, fl = 2.3548 * abs(p[2]), 2 * abs(p[3])
            fwhm = 0.5346 * fl + np.sqrt(0.2166 * fl ** 2 + fg ** 2)
            area, height = p[0], float(_voigt(np.array([p[1]]), *p)[0])
        peaks.append({"center": float(p[1]), "center_err": float(e[1]), "fwhm": float(fwhm),
                      "height": float(height), "area": float(area)})
    return {"model": model, "baseline": float(popt[-1]), "r2": 1 - ss_res / ss_tot if ss_tot else 1.0,
            "peaks": peaks, "derived": {"x": X.tolist(), "y": Y.tolist(), "fit": fitted.tolist()}}


def filter_signal(t: list[float], y: list[float], kind: str = "lowpass", cutoff: float | list[float] | None = None,
                  order: int = 4, window_points: int = 11, polyorder: int = 3) -> dict[str, Any]:
    """lowpass/highpass/bandpass(Butterworth, 위상 지연 없는 filtfilt) 또는 savgol(스무딩)."""
    from scipy.signal import butter, filtfilt, savgol_filter

    T, Y = _arr(t, y)
    if kind == "savgol":
        wl = window_points if window_points % 2 else window_points + 1
        out = savgol_filter(Y, wl, polyorder)
    else:
        if cutoff is None:
            raise ValueError("cutoff(Hz)를 지정하세요. bandpass는 [저, 고] 두 값.")
        fs = 1.0 / float(np.median(np.diff(T)))
        nyq = fs / 2
        wn = [c / nyq for c in cutoff] if isinstance(cutoff, (list, tuple)) else cutoff / nyq
        if np.any(np.asarray(wn) >= 1):
            raise ValueError(f"cutoff가 나이퀴스트 주파수({nyq:g} Hz) 이상입니다.")
        b, a = butter(order, wn, btype=kind)
        out = filtfilt(b, a, Y)
    return {"kind": kind, "derived": {"t": T.tolist(), "raw": Y.tolist(), "filtered": out.tolist()}}


def bode(f: list[float], gain_db: list[float] | None = None, vin: list[float] | None = None,
         vout: list[float] | None = None, phase_deg: list[float] | None = None) -> dict[str, Any]:
    """이득(dB)과 -3 dB 차단 주파수(첫 점 이득 기준, 로그 주파수 보간)."""
    ph_in = phase_deg if phase_deg is not None else [0.0] * len(f)
    if gain_db is None:
        if vin is None or vout is None:
            raise ValueError("gain_db 또는 vin·vout 을 주세요.")
        F, VI, VO, PH = _arr(f, vin, vout, ph_in)
        G = 20 * np.log10(np.abs(VO) / np.abs(VI))
    else:
        F, G, PH = _arr(f, gain_db, ph_in)
    order = np.argsort(F)
    F, G, PH = F[order], G[order], PH[order]
    ref = float(G[0])
    target = ref - 3.0
    fc = None
    below = np.nonzero(G <= target)[0]
    if len(below) and below[0] > 0:
        j = below[0]
        lf = np.interp(target, [G[j], G[j - 1]], [np.log10(F[j]), np.log10(F[j - 1])])
        fc = float(10 ** lf)
    out: dict[str, Any] = {"reference_gain_dB": ref, "cutoff_frequency_Hz": fc,
                           "derived": {"frequency": F.tolist(), "gain_dB": G.tolist()}}
    if phase_deg is not None:
        out["derived"]["phase_deg"] = PH.tolist()
    return out


def arrhenius(temperature: list[float], rate: list[float], celsius: bool = False) -> dict[str, Any]:
    """ln(k) - 1/T 직선 기울기로 활성화 에너지 Ea [eV]."""
    T, K = _arr(temperature, rate)
    if celsius:
        T = T + 273.15
    m = (T > 0) & (K > 0)
    fit = linfit(1.0 / T[m], np.log(K[m]))
    return {"activation_energy_eV": float(-fit.slope * KB_EV), "prefactor": float(np.exp(fit.intercept)),
            "fit": fit.as_dict(),
            "derived": {"inv_T_1000": (1000.0 / T[m]).tolist(), "ln_k": np.log(K[m]).tolist()}}
