# (C) Copyright 2026. Apache-2.0.

"""HBV rainfall-runoff model with Optuna calibration.

The classic HBV-96 structure (Bergström/Lindström): degree-day snow routine,
beta-function soil moisture accounting, two-box response routine and a
triangular MAXBAS routing filter. The simulation is vectorised over
parameter sets, so Monte-Carlo ensembles are one call.

    from germany_hydrology import hbv

    sim = hbv.simulate(precip, temp, pet, hbv.DEFAULT_PARAMS)

    result = hbv.calibrate(
        precip, temp, pet, q_obs,
        objective="kge",                    # "nse", "kge", "log_nse" or a callable
        calibration_period=("1971", "2000"),
        validation_period=("2001", "2020"),
        n_trials=200,
    )
    result["best_params"], result["validation_score"], result["simulation"]

Forcing and discharge are daily and in mm/day (specific discharge);
temperature in °C.
"""

import numpy as np
import pandas as pd

__all__ = ["PARAM_BOUNDS", "DEFAULT_PARAMS", "simulate", "calibrate"]

#: Standard HBV calibration ranges.
PARAM_BOUNDS = {
    "TT":     (-2.5, 2.5),    # snow/rain threshold temperature (degC)
    "CFMAX":  (0.5, 10.0),    # degree-day melt factor (mm/degC/day)
    "SFCF":   (0.4, 1.4),     # snowfall correction factor (-)
    "CFR":    (0.0, 0.1),     # refreezing coefficient (-)
    "CWH":    (0.0, 0.2),     # water holding capacity of snow (-)
    "FC":     (50.0, 700.0),  # field capacity (mm)
    "LP":     (0.2, 1.0),     # ET reduction threshold (fraction of FC)
    "BETA":   (1.0, 6.0),     # shape of recharge function (-)
    "K0":     (0.05, 0.9),    # near-surface recession (1/day)
    "K1":     (0.01, 0.5),    # upper-zone recession (1/day)
    "K2":     (0.001, 0.2),   # lower-zone recession (1/day)
    "UZL":    (0.0, 100.0),   # threshold for K0 outflow (mm)
    "PERC":   (0.0, 6.0),     # percolation to lower zone (mm/day)
    "MAXBAS": (1.0, 7.0),     # routing filter length (days)
}

#: A reasonable mid-range parameter set (for smoke tests / starting points).
DEFAULT_PARAMS = {
    "TT": 0.0, "CFMAX": 3.5, "SFCF": 0.9, "CFR": 0.05, "CWH": 0.1,
    "FC": 250.0, "LP": 0.7, "BETA": 2.5, "K0": 0.3, "K1": 0.1, "K2": 0.05,
    "UZL": 30.0, "PERC": 2.0, "MAXBAS": 2.5,
}


def _maxbas_weights(maxbas):
    """Triangular unit hydrograph for a (possibly fractional) MAXBAS."""
    n = int(np.ceil(maxbas))
    edges = np.arange(n + 1, dtype=float)
    # integral of the triangle with base maxbas over each unit interval
    def cdf(t):
        t = np.clip(t, 0.0, maxbas)
        half = maxbas / 2.0
        area = np.where(
            t <= half, 2.0 * t**2 / maxbas**2, 1.0 - 2.0 * (maxbas - t) ** 2 / maxbas**2
        )
        return area
    w = cdf(edges[1:]) - cdf(edges[:-1])
    return w / w.sum()


def simulate(precip, temp, pet, params, return_states=False):
    """Run HBV. Scalars in ``params`` give one run; equal-length arrays give
    an ensemble (vectorised over parameter sets).

    Parameters
    ----------
    precip, temp, pet : array-like
        Daily precipitation (mm), temperature (degC), potential ET (mm).
    params : dict
        Keys of :data:`PARAM_BOUNDS`; values scalar or 1-D arrays (n sets).
    return_states : bool
        Also return a dict of state time series (snowpack, soil moisture, ...).

    Returns
    -------
    ndarray of shape ``(T,)`` (scalars) or ``(n, T)`` (ensemble) — discharge
    in mm/day — or ``(q, states)`` if ``return_states``.
    """
    P = np.asarray(precip, dtype=float)
    T = np.asarray(temp, dtype=float)
    E = np.asarray(pet, dtype=float)
    nt = len(P)

    p = {k: np.atleast_1d(np.asarray(params[k], dtype=float)) for k in PARAM_BOUNDS}
    n = max(v.size for v in p.values())
    p = {k: np.broadcast_to(v, (n,)).astype(float) for k, v in p.items()}

    snow = np.zeros(n)      # dry snowpack (mm)
    liquid = np.zeros(n)    # liquid water in snowpack (mm)
    sm = p["FC"] * 0.5      # soil moisture (mm)
    suz = np.zeros(n)       # upper zone storage (mm)
    slz = np.zeros(n)       # lower zone storage (mm)

    q = np.empty((n, nt))
    states = {k: np.empty((n, nt)) for k in ("snowpack", "soil_moisture", "suz", "slz", "aet")} \
        if return_states else None

    for t in range(nt):
        rain = np.where(T[t] >= p["TT"], P[t], 0.0)
        snowfall = np.where(T[t] < p["TT"], P[t], 0.0) * p["SFCF"]

        # snow routine
        snow = snow + snowfall
        melt = np.minimum(p["CFMAX"] * np.maximum(T[t] - p["TT"], 0.0), snow)
        snow -= melt
        liquid += melt
        refreeze = np.minimum(p["CFR"] * p["CFMAX"] * np.maximum(p["TT"] - T[t], 0.0), liquid)
        snow += refreeze
        liquid -= refreeze
        max_liquid = p["CWH"] * snow
        outflow = np.maximum(liquid - max_liquid, 0.0)
        liquid = liquid - outflow
        water_in = rain + outflow

        # soil routine
        recharge = water_in * (sm / p["FC"]) ** p["BETA"]
        sm = sm + water_in - recharge
        excess = np.maximum(sm - p["FC"], 0.0)
        sm -= excess
        recharge += excess
        aet = E[t] * np.clip(sm / (p["LP"] * p["FC"]), 0.0, 1.0)
        aet = np.minimum(aet, sm)
        sm -= aet

        # response routine
        suz = suz + recharge
        perc = np.minimum(p["PERC"], suz)
        suz -= perc
        slz += perc
        q0 = p["K0"] * np.maximum(suz - p["UZL"], 0.0)
        q1 = p["K1"] * suz
        q2 = p["K2"] * slz
        suz = suz - q0 - q1
        slz -= q2
        q[:, t] = q0 + q1 + q2

        if return_states:
            states["snowpack"][:, t] = snow + liquid
            states["soil_moisture"][:, t] = sm
            states["suz"][:, t] = suz
            states["slz"][:, t] = slz
            states["aet"][:, t] = aet

    # routing: convolve each ensemble member with its triangular filter
    routed = np.empty_like(q)
    for i in range(n):
        w = _maxbas_weights(p["MAXBAS"][i])
        routed[i] = np.convolve(q[i], w)[:nt]

    scalar_input = all(np.isscalar(v) or np.ndim(v) == 0 for v in params.values())
    out = routed[0] if scalar_input else routed
    if return_states:
        if scalar_input:
            states = {k: v[0] for k, v in states.items()}
        return out, states
    return out


_OBJECTIVES = {
    "nse": lambda o, s: _nse(o, s),
    "kge": lambda o, s: _kge(o, s),
    "log_nse": lambda o, s: _nse(np.log(o + 0.01), np.log(s + 0.01)),
}


def _nse(obs, sim):
    return 1.0 - np.sum((obs - sim) ** 2) / np.sum((obs - obs.mean()) ** 2)


def _kge(obs, sim):
    r = np.corrcoef(obs, sim)[0, 1]
    return 1.0 - np.sqrt((r - 1) ** 2 + (sim.std() / obs.std() - 1) ** 2
                         + (sim.mean() / obs.mean() - 1) ** 2)


def calibrate(
    precip, temp, pet, q_obs,
    objective="nse",
    calibration_period=None,
    validation_period=None,
    n_trials=200,
    warmup=730,
    bounds=None,
    fixed=None,
    sampler=None,
    seed=42,
    show_progress=False,
):
    """Calibrate HBV with Optuna (TPE by default).

    Parameters
    ----------
    precip, temp, pet, q_obs : pandas Series
        Daily forcing and observed specific discharge (mm/day), sharing a
        DatetimeIndex. NaNs in ``q_obs`` are ignored in the objective.
    objective : str or callable
        ``'nse'``, ``'kge'``, ``'log_nse'`` or ``f(obs, sim) -> float``
        (maximised).
    calibration_period, validation_period : tuple of str, optional
        ``(start, end)`` labels, e.g. ``("1971", "2000")``. Default
        calibration: everything after warmup.
    warmup : int
        Days at the start of the record excluded from the objective (states
        spin-up); the simulation itself always starts at the record start.
    bounds : dict, optional
        Overrides for :data:`PARAM_BOUNDS` entries.
    fixed : dict, optional
        Parameters to hold constant (excluded from search), e.g.
        ``{"CFR": 0.05, "CWH": 0.1}``.
    sampler : optuna sampler, optional
        Defaults to ``TPESampler(seed=seed)``.

    Returns
    -------
    dict with ``best_params``, ``best_score``, ``validation_score`` (if a
    validation period was given), ``simulation`` (best-parameter Series over
    the whole record), and the optuna ``study``.
    """
    try:
        import optuna
    except ImportError as e:  # pragma: no cover - dependency guard
        raise ImportError(
            "Calibration needs optuna: pip install optuna "
            "(or germany-hydrology[models])."
        ) from e

    idx = q_obs.index
    P, T, E = (s.reindex(idx).to_numpy(dtype=float) for s in (precip, temp, pet))
    Q = q_obs.to_numpy(dtype=float)

    space = dict(PARAM_BOUNDS)
    space.update(bounds or {})
    fixed = dict(fixed or {})
    obj_fn = _OBJECTIVES[objective] if isinstance(objective, str) else objective

    def _mask(period):
        m = np.zeros(len(idx), dtype=bool)
        if period is None:
            m[warmup:] = True
        else:
            sel = idx.slice_indexer(str(period[0]), str(period[1]))
            m[sel] = True
            m[:warmup] = False
        return m & np.isfinite(Q)

    cal_mask = _mask(calibration_period)
    if cal_mask.sum() < 10:
        raise ValueError("Calibration period has under 10 days of valid data.")
    if cal_mask.sum() < 365:
        import logging

        logging.getLogger(__name__).warning(
            "Calibrating on only %d days — parameters will be poorly "
            "constrained; treat results as a demo.", int(cal_mask.sum()),
        )

    def _run(params):
        return simulate(P, T, E, params)

    def _objective(trial):
        params = dict(fixed)
        for name, (lo, hi) in space.items():
            if name not in params:
                params[name] = trial.suggest_float(name, lo, hi)
        if not (params["K0"] > params["K1"] > params["K2"]):
            return -9.99  # non-physical recession ordering
        sim = _run(params)
        score = obj_fn(Q[cal_mask], sim[cal_mask])
        return score if np.isfinite(score) else -9.99

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = sampler or optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(_objective, n_trials=n_trials,
                   show_progress_bar=show_progress)

    best = dict(fixed)
    best.update(study.best_params)
    sim = pd.Series(_run(best), index=idx, name="hbv_sim")

    result = {
        "best_params": best,
        "best_score": study.best_value,
        "simulation": sim,
        "study": study,
    }
    if validation_period is not None:
        val_mask = _mask(validation_period)
        result["validation_score"] = float(
            obj_fn(Q[val_mask], sim.to_numpy()[val_mask]))
    return result
