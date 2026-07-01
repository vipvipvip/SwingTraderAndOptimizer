import warnings
import numpy as np
from scipy import signal as sp_signal

DETREND_PERIOD = 30
SMOOTHING = 5

def detrend(prices, period=20):
    n = len(prices)
    sma = np.convolve(prices, np.ones(period) / period, mode='same')
    sma[:period // 2] = prices[:period // 2]
    sma[-(period // 2):] = prices[-(period // 2):]
    return prices - sma, sma


def smooth_ema(x, period=3):
    alpha = 2.0 / (period + 1)
    out = np.full_like(x, np.nan)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def fft_dominant_cycles(prices, min_period=10, max_period=120, top_n=2):
    n = len(prices)
    if n < max_period + 1:
        return []

    detrended = prices - np.mean(prices)
    windowed = detrended * np.hanning(n)
    fft_vals = np.fft.rfft(windowed)
    fft_mag = np.abs(fft_vals)
    freqs = np.fft.rfftfreq(n, d=1)
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', r'divide by zero encountered in divide')
        periods = np.where(freqs > 0, 1.0 / freqs, np.inf)

    valid = (periods >= min_period) & (periods <= max_period)
    valid_idx = np.where(valid)[0]

    if len(valid_idx) == 0:
        return []

    sorted_idx = valid_idx[np.argsort(fft_mag[valid_idx])[::-1]][:top_n]

    results = []
    for idx in sorted_idx:
        phase = np.angle(fft_vals[idx])
        results.append({
            'period': round(periods[idx], 1),
            'magnitude': float(fft_mag[idx]),
            'phase_deg': float(np.degrees(phase) % 360),
        })
    return results


def hilbert_cycle(prices, detrend_period=20):
    dt, trend = detrend(prices, detrend_period)
    analytic = sp_signal.hilbert(dt)
    phase_rad = np.unwrap(np.angle(analytic))
    phase_deg = np.degrees(phase_rad) % 360
    sine_wave = np.sin(phase_rad)
    lead_sine = np.cos(phase_rad)
    return phase_deg, sine_wave, lead_sine, trend


def adaptive_period(phase_rad):
    n = len(phase_rad)
    period = np.full(n, np.nan)
    dphase = np.diff(phase_rad)
    for i in range(1, n):
        dp = dphase[i - 1]
        if abs(dp) > 0.01:
            p = abs(2 * np.pi / dp)
            period[i] = np.clip(p, 6, 60)
    return period


def dominant_cycle(prices, detrend_period=None):
    if detrend_period is None:
        detrend_period = DETREND_PERIOD
    phase_deg, sine_wave, lead_sine, trend = hilbert_cycle(prices, detrend_period)
    smoothed_sine = smooth_ema(sine_wave, SMOOTHING)
    smoothed_lead = smooth_ema(lead_sine, SMOOTHING)
    phase_rad = np.arctan2(sine_wave, lead_sine)
    adp = adaptive_period(np.unwrap(phase_rad))
    median_period = float(np.nanmedian(adp)) if np.any(~np.isnan(adp)) else 20.0
    fft_cycles = fft_dominant_cycles(prices, top_n=2)
    return {
        'phase_deg': phase_deg,
        'sine': sine_wave,
        'lead_sine': lead_sine,
        'sine_smoothed': smoothed_sine,
        'lead_smoothed': smoothed_lead,
        'adaptive_period': adp,
        'median_period': round(median_period, 1),
        'fft_cycles': fft_cycles,
        'trend': trend,
    }


def detect_signals(sine, lead):
    n = len(sine)
    buys = np.zeros(n, dtype=bool)
    sells = np.zeros(n, dtype=bool)
    for i in range(1, n):
        s0, s1 = sine[i - 1], sine[i]
        l0, l1 = lead[i - 1], lead[i]
        if s0 < l0 and s1 >= l1:
            buys[i] = True
        elif s0 > l0 and s1 <= l1:
            sells[i] = True
    return buys, sells
