"""물리 분석 계산을 알려진 정답이 있는 합성 데이터로 검증한다."""
import numpy as np
import pytest

from origin_ilhae_mcp.physics import analysis as A


def test_diode_ideality_and_series_resistance():
    n, i0, rs, T = 1.6, 1e-12, 5.0, 300.0
    vt = A.KB * T / A.Q
    I = np.logspace(-10, -2, 200)
    V = n * vt * np.log(I / i0 + 1) + I * rs  # Shockley + 직렬저항
    r = A.diode_analyze(V.tolist(), I.tolist(), T)
    assert r["semilog"]["ideality_factor"] == pytest.approx(n, rel=0.03)
    assert r["semilog"]["saturation_current_A"] == pytest.approx(i0, rel=0.3)
    assert r["cheung"]["series_resistance_ohm"] == pytest.approx(rs, rel=0.05)
    assert r["cheung"]["ideality_factor"] == pytest.approx(n, rel=0.05)


def test_transistor_linear_vth():
    vth, k, vd = 1.0, 1e-4, 0.1
    vg = np.linspace(0, 5, 251)
    idd = k * vd * np.clip(vg - vth, 0, None) + 1e-12
    r = A.transistor_analyze(vg.tolist(), idd.tolist(), "linear", vd=vd)
    assert r["threshold_voltage_V"] == pytest.approx(vth - vd / 2, abs=0.03)
    assert r["carrier_type"].startswith("n")


def test_transistor_ss_and_onoff_ekv_model():
    # EKV 모델: 문턱 아래 지수(SS = n·vt·ln10), 위는 2차로 매끄럽게 이어진다
    ss_target = 0.080
    nvt = ss_target / np.log(10)
    vg = np.linspace(-1, 3, 401)
    idd = 1e-6 * np.log1p(np.exp((vg - 1.0) / (2 * nvt))) ** 2
    r = A.transistor_analyze(vg.tolist(), idd.tolist(), "saturation")
    assert r["subthreshold_swing_mV_per_dec"] == pytest.approx(80, rel=0.03)
    assert r["on_off_ratio"] > 1e8


def test_transistor_p_type_saturation():
    vg = np.linspace(-5, 2, 300)
    idd = -0.5e-4 * np.clip(-1.0 - vg, 0, None) ** 2 - 1e-12   # p형, Vth=-1
    r = A.transistor_analyze(vg.tolist(), idd.tolist(), "saturation")
    assert r["threshold_voltage_V"] == pytest.approx(-1.0, abs=0.05)
    assert r["carrier_type"].startswith("p")


def test_mott_schottky_doping_and_vfb():
    area, eps, N_cm3, vfb, T = 0.01, 11.7, 1e17, -0.5, 300.0
    a_m2 = area * 1e-4
    slope = 2 / (A.Q * eps * A.EPS0 * a_m2 ** 2 * N_cm3 * 1e6)
    V = np.linspace(-0.3, 1.0, 40)
    inv_c2 = slope * (V - vfb - A.KB * T / A.Q)
    C = 1 / np.sqrt(inv_c2)
    r = A.mott_schottky(V.tolist(), C.tolist(), area, eps, T)
    assert r["doping_cm3"] == pytest.approx(N_cm3, rel=0.01)
    assert r["flat_band_voltage_V"] == pytest.approx(vfb, abs=0.01)
    assert r["semiconductor_type"] == "n형"


def test_fft_dominant_frequency():
    t = np.arange(0, 1, 1e-4)
    y = 2.0 * np.sin(2 * np.pi * 50 * t) + 0.3 * np.sin(2 * np.pi * 400 * t)
    r = A.fft_spectrum(t.tolist(), y.tolist())
    assert r["dominant_frequency_Hz"] == pytest.approx(50, abs=1)
    assert r["dominant_amplitude"] == pytest.approx(2.0, rel=0.05)
    assert r["irregular_sampling"] is False


@pytest.mark.parametrize("model", ["gauss", "lorentz", "voigt"])
def test_two_peak_fit(model):
    x = np.linspace(400, 600, 801)
    s = 6.0
    y = 100 * np.exp(-((x - 480) ** 2) / (2 * s ** 2)) + 60 * np.exp(-((x - 530) ** 2) / (2 * s ** 2)) + 5
    r = A.peaks_fit(x.tolist(), y.tolist(), model=model, n_peaks=2)
    centers = sorted(p["center"] for p in r["peaks"])
    assert centers == pytest.approx([480, 530], abs=0.5)
    if model == "gauss":
        assert r["peaks"][0]["fwhm"] == pytest.approx(2.3548 * s, rel=0.01)
        assert r["r2"] > 0.9999


def test_bode_rc_cutoff():
    fc = 1000.0
    f = np.logspace(1, 5, 200)
    gain = 20 * np.log10(1 / np.sqrt(1 + (f / fc) ** 2))
    phase = -np.degrees(np.arctan(f / fc))
    r = A.bode(f.tolist(), gain_db=gain.tolist(), phase_deg=phase.tolist())
    assert r["cutoff_frequency_Hz"] == pytest.approx(fc, rel=0.03)
    assert len(r["derived"]["phase_deg"]) == len(f)


def test_bode_from_vin_vout_with_missing_values():
    f = [10, 100, None, 1000, 10000]
    r = A.bode(f, vin=[1, 1, 1, 1, 1], vout=[1, 0.99, 0.5, 0.7, 0.1], phase_deg=[0, -5, -30, -45, None])
    assert len(r["derived"]["frequency"]) == len(r["derived"]["phase_deg"]) == 3


def test_arrhenius_activation_energy():
    ea = 0.45
    T = np.linspace(300, 450, 10)
    k = 1e9 * np.exp(-ea / (A.KB_EV * T))
    r = A.arrhenius(T.tolist(), k.tolist())
    assert r["activation_energy_eV"] == pytest.approx(ea, rel=1e-6)
    r2 = A.arrhenius((T - 273.15).tolist(), k.tolist(), celsius=True)
    assert r2["activation_energy_eV"] == pytest.approx(ea, rel=1e-6)


def test_lowpass_filter_removes_high_frequency():
    t = np.arange(0, 1, 1e-3)
    clean = np.sin(2 * np.pi * 5 * t)
    noisy = clean + 0.5 * np.sin(2 * np.pi * 200 * t)
    r = A.filter_signal(t.tolist(), noisy.tolist(), "lowpass", cutoff=30)
    err = np.max(np.abs(np.array(r["derived"]["filtered"]) - clean)[50:-50])
    assert err < 0.05
    with pytest.raises(ValueError, match="나이퀴스트"):
        A.filter_signal(t.tolist(), noisy.tolist(), "lowpass", cutoff=600)
