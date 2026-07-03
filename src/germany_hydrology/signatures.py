# (C) Copyright 2026. Apache-2.0.

"""Hydrological signatures and model-evaluation metrics.

Plain functions on pandas Series / numpy arrays (in the spirit of HyRiver's
HydroSignatures). Discharge series are expected at daily resolution; NaNs
are dropped pairwise where two series are compared.

    from germany_hydrology import signatures as hs

    hs.nse(obs, sim), hs.kge(obs, sim)
    hs.baseflow_index(q), hs.fdc_slope(q), hs.runoff_ratio(q_mm, p_mm)
"""

import numpy as np
import pandas as pd

__all__ = [
    "nse", "kge", "pbias", "rmse",
    "flow_duration_curve", "fdc_slope", "high_q_freq", "low_q_freq",
    "baseflow", "baseflow_index", "richards_baker_flashiness",
    "runoff_ratio", "half_flow_date",
]


def _pair(obs, sim):
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(sim)
    return obs[ok], sim[ok]


# -- model evaluation --------------------------------------------------------

def nse(obs, sim):
    """Nash-Sutcliffe efficiency (1 = perfect, 0 = mean benchmark)."""
    obs, sim = _pair(obs, sim)
    return 1.0 - np.sum((obs - sim) ** 2) / np.sum((obs - obs.mean()) ** 2)


def kge(obs, sim):
    """Kling-Gupta efficiency (Gupta et al. 2009). 1 = perfect."""
    obs, sim = _pair(obs, sim)
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim.std() / obs.std()
    beta = sim.mean() / obs.mean()
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def pbias(obs, sim):
    """Percent bias; positive = overestimation."""
    obs, sim = _pair(obs, sim)
    return 100.0 * (sim - obs).sum() / obs.sum()


def rmse(obs, sim):
    obs, sim = _pair(obs, sim)
    return float(np.sqrt(np.mean((obs - sim) ** 2)))


# -- flow-regime signatures --------------------------------------------------

def flow_duration_curve(q, quantiles=None):
    """Exceedance-probability curve. Returns a Series indexed by exceedance %."""
    q = pd.Series(q).dropna()
    ex = np.linspace(0.1, 99.9, 199) if quantiles is None else np.asarray(quantiles)
    return pd.Series(np.quantile(q, 1 - ex / 100.0), index=pd.Index(ex, name="exceedance_%"))


def fdc_slope(q, lower=33, upper=66):
    """Slope of the log flow-duration curve between two exceedance points."""
    q = pd.Series(q).dropna()
    q33 = np.quantile(q, 1 - lower / 100.0)
    q66 = np.quantile(q, 1 - upper / 100.0)
    return (np.log(q33) - np.log(q66)) / ((upper - lower) / 100.0)


def high_q_freq(q, factor=9.0):
    """Fraction of days with flow > ``factor`` x median flow."""
    q = pd.Series(q).dropna()
    return float((q > factor * q.median()).mean())


def low_q_freq(q, factor=0.2):
    """Fraction of days with flow < ``factor`` x mean flow."""
    q = pd.Series(q).dropna()
    return float((q < factor * q.mean()).mean())


def baseflow(q, alpha=0.925, passes=3):
    """Baseflow separation with the Lyne-Hollick digital filter.

    Standard 3-pass (forward/backward/forward) recursive filter with the
    conventional ``alpha`` = 0.925 for daily data.
    """
    q = pd.Series(q).astype(float)
    values = q.dropna().to_numpy()
    b = values.copy()
    for p in range(passes):
        x = b if p == 0 else b[::-1]
        quick = np.zeros_like(x)
        quick[0] = x[0] / 2.0
        for i in range(1, len(x)):
            quick[i] = alpha * quick[i - 1] + (1 + alpha) / 2.0 * (x[i] - x[i - 1])
        base = x - np.clip(quick, 0.0, None)
        base = np.clip(base, 0.0, x)
        b = base if p == 0 else base[::-1]
    out = pd.Series(np.nan, index=q.index, dtype=float)
    out[q.dropna().index] = b
    return out


def baseflow_index(q, **kwargs):
    """BFI: long-term baseflow volume / total flow volume (0-1)."""
    q = pd.Series(q).dropna()
    return float(baseflow(q, **kwargs).sum() / q.sum())


def richards_baker_flashiness(q):
    """Richards-Baker flashiness index: sum |dQ| / sum Q (0 = constant flow)."""
    q = pd.Series(q).dropna().to_numpy()
    return float(np.abs(np.diff(q)).sum() / q[1:].sum())


def runoff_ratio(q_mm, p_mm):
    """Long-term runoff / precipitation (both in mm over the same period)."""
    q_mm, p_mm = _pair(q_mm, p_mm)
    return float(q_mm.sum() / p_mm.sum())


def half_flow_date(q):
    """Mean day-of-hydrological-year (Nov 1 start) by which half the annual
    flow has passed. Needs a DatetimeIndex."""
    q = pd.Series(q).dropna()
    hyear = q.index.year + (q.index.month >= 11)
    days = []
    for _, qy in q.groupby(hyear):
        cum = qy.cumsum()
        half = cum.searchsorted(cum.iloc[-1] / 2.0)
        days.append(half)
    return float(np.mean(days))
