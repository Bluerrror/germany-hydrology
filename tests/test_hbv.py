# (C) Copyright 2026. Apache-2.0.

"""Offline tests for the HBV model and its Optuna calibration."""

import numpy as np
import pandas as pd
import pytest

from germany_hydrology import hbv


def _synthetic_forcing(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2000-01-01", periods=n)
    doy = idx.dayofyear.to_numpy()
    temp = 10 + 12 * np.sin(2 * np.pi * (doy - 100) / 365) + rng.normal(0, 2, n)
    precip = rng.gamma(0.5, 6, n) * (rng.random(n) < 0.4)
    pet = np.clip(1.5 + 1.5 * np.sin(2 * np.pi * (doy - 100) / 365), 0.1, None)
    return idx, precip, temp, pet


def test_simulate_shapes_and_nonnegative():
    _, P, T, E = _synthetic_forcing()
    q = hbv.simulate(P, T, E, hbv.DEFAULT_PARAMS)
    assert q.shape == P.shape
    assert (q >= 0).all() and np.isfinite(q).all()


def test_simulate_ensemble_vectorised():
    _, P, T, E = _synthetic_forcing(400)
    params = {k: np.full(5, v) for k, v in hbv.DEFAULT_PARAMS.items()}
    params["FC"] = np.linspace(100, 500, 5)
    q = hbv.simulate(P, T, E, params)
    assert q.shape == (5, 400)
    assert not np.allclose(q[0], q[-1])  # FC actually matters


def test_mass_balance_closes():
    _, P, T, E = _synthetic_forcing(3000)
    T = np.full_like(T, 15.0)  # no snow: SFCF plays no role
    q, states = hbv.simulate(P, T, E, hbv.DEFAULT_PARAMS, return_states=True)
    storage = (states["soil_moisture"][-1] - states["soil_moisture"][0]
               + states["suz"][-1] + states["slz"][-1])
    # routing tail truncation loses a little; 2% closure is plenty strict
    balance = P.sum() - q.sum() - states["aet"].sum() - storage
    assert abs(balance) / P.sum() < 0.02


def test_maxbas_weights_sum_to_one():
    for mb in (1.0, 2.5, 4.0, 6.7):
        w = hbv._maxbas_weights(mb)
        assert w.sum() == pytest.approx(1.0)
        assert (w >= 0).all()


def test_calibrate_recovers_synthetic_truth():
    optuna = pytest.importorskip("optuna")  # noqa: F841
    idx, P, T, E = _synthetic_forcing(2000)
    truth = dict(hbv.DEFAULT_PARAMS)
    q_true = pd.Series(hbv.simulate(P, T, E, truth), index=idx)

    result = hbv.calibrate(
        pd.Series(P, index=idx), pd.Series(T, index=idx), pd.Series(E, index=idx),
        q_true, objective="nse", n_trials=60, warmup=365, seed=1,
        fixed={"CFR": truth["CFR"], "CWH": truth["CWH"]},
    )
    # with the true model in the search space, a decent NSE must be reachable
    assert result["best_score"] > 0.85
    assert set(hbv.PARAM_BOUNDS) == set(result["best_params"])
    assert len(result["simulation"]) == len(idx)


def test_calibrate_validation_and_custom_objective():
    pytest.importorskip("optuna")
    idx, P, T, E = _synthetic_forcing(2000)
    q_true = pd.Series(hbv.simulate(P, T, E, hbv.DEFAULT_PARAMS), index=idx)

    def neg_rmse(obs, sim):
        return -float(np.sqrt(np.mean((obs - sim) ** 2)))

    result = hbv.calibrate(
        pd.Series(P, index=idx), pd.Series(T, index=idx), pd.Series(E, index=idx),
        q_true, objective=neg_rmse, n_trials=20, warmup=365,
        calibration_period=("2001", "2003"), validation_period=("2004", "2005"),
    )
    assert "validation_score" in result and np.isfinite(result["validation_score"])
