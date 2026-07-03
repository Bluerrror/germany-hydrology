# (C) Copyright 2026. Apache-2.0.
"""Germany-Hydrology — Dash web app.

Explore German catchment climate and river gauges and calibrate the HBV-96
rainfall-runoff model live. Uses the package's own vectorised HBV
(``hbv.simulate``) with a fast vectorised random search; ERA5 comes from the
Open-Meteo archive and gauge data from PEGELONLINE, both fetched server-side.

Security posture (matches the PTF app on the same host): no user file input,
no eval, debug off, all outbound requests are built only from validated
numeric coordinates or whitelisted station ids, with timeouts.
"""
import json
import os

os.environ.setdefault("OMP_NUM_THREADS", "2")     # 2-CPU VPS: avoid oversubscribe
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, dcc, html, no_update

import hbv

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
GERMANY = (5.8, 47.2, 15.1, 55.1)            # W,S,E,N — clamp for ERA5 requests
WC = "#2c6e9c"; DEEP = "#183f57"; ACC = "#e0862d"; INK = "#12303c"; GRID = "#d7e0e3"
UA = {"User-Agent": "germany-hydrology-webapp/1.0"}
MAX_ENSEMBLE = 12000       # bounds worst-case calibration time/memory on the VPS

# ---- load bundled catchments -------------------------------------------
EXAMPLES = json.load(open(os.path.join(DATA, "camels_examples.json")))
EX_BY_ID = {e["id"]: e for e in EXAMPLES}
VALID_IDS = set(EX_BY_ID)


@lru_cache(maxsize=16)
def load_catchment(cid):
    """Return (dates, P, T, E, Q) arrays for a bundled catchment id."""
    if cid not in VALID_IDS:                  # whitelist guard
        raise KeyError(cid)
    d = json.load(open(os.path.join(DATA, f"camels_{cid}.json")))
    n = len(d["q"])
    dates = pd.date_range(d["start"], periods=n, freq="D")
    arr = lambda k, fill: np.array([fill if v is None else v for v in d[k]], float)
    return dates, arr("p", 0.0), arr("t", 0.0), arr("pet", 0.0), arr("q", np.nan)


# ---- vectorised random-search calibration ------------------------------
def _rand_params(n, rng):
    p = {k: rng.uniform(lo, hi, n) for k, (lo, hi) in hbv.PARAM_BOUNDS.items()}
    ks = np.sort(np.stack([p["K0"], p["K1"], p["K2"]]), axis=0)   # enforce K0>K1>K2
    p["K2"], p["K1"], p["K0"] = ks[0], ks[1], ks[2]
    return p


def _scores(obs, sim, mask, kind):
    o = obs[mask]; s = sim[:, mask]                              # (m,), (N,m)
    om = o.mean(); os_ = s.mean(1)
    if kind == "nse":
        return 1 - ((o - s) ** 2).sum(1) / ((o - om) ** 2).sum()
    if kind == "rmse":
        return -np.sqrt(((o - s) ** 2).mean(1))
    # kge
    so = o.std(); ss = s.std(1)
    r = ((s - os_[:, None]) * (o - om)).mean(1) / (ss * so + 1e-12)
    return 1 - np.sqrt((r - 1) ** 2 + (ss / so - 1) ** 2 + (os_ / om - 1) ** 2)


def calibrate_fast(P, T, E, Q, train_mask, kind="kge", n=5000, seed=42, batch=600):
    """Vectorised random search over the package's HBV, in memory-bounded
    batches. A full (n, nt) ensemble would be ~0.6 GB for n=5000 over 40 yr;
    batching to `batch` parameter sets keeps peak memory ~150 MB on the VPS.
    """
    n = int(min(max(n, 500), MAX_ENSEMBLE))
    rng = np.random.default_rng(seed)
    best_score, best_params = -np.inf, None
    done = 0
    while done < n:
        b = min(batch, n - done)
        params = _rand_params(b, rng)
        sim = hbv.simulate(P, T, E, params)                     # (b, nt), package model
        sc = _scores(Q, sim, train_mask, kind)
        j = int(np.nanargmax(sc))
        if sc[j] > best_score:
            best_score = float(sc[j])
            best_params = {k: float(params[k][j]) for k in hbv.PARAM_BOUNDS}
        del sim, params
        done += b
    return best_params, hbv.simulate(P, T, E, best_params)      # best params + its sim


def nse(o, s): return float(1 - np.sum((o - s) ** 2) / np.sum((o - o.mean()) ** 2))
def kge(o, s):
    r = np.corrcoef(o, s)[0, 1]
    return float(1 - np.sqrt((r - 1) ** 2 + (s.std() / o.std() - 1) ** 2 + (s.mean() / o.mean() - 1) ** 2))


# ---- figures ------------------------------------------------------------
def base_layout(title, h=330):
    return dict(title=title, height=h, margin=dict(t=42, r=14, b=34, l=52),
                paper_bgcolor="#fff", plot_bgcolor="#fff", hovermode="x unified",
                font=dict(family="Inter, sans-serif", color=INK, size=12),
                xaxis=dict(gridcolor=GRID, zeroline=False),
                yaxis=dict(gridcolor=GRID, zeroline=False))


def map_figure():
    lats = [e["lat"] for e in EXAMPLES]; lons = [e["lon"] for e in EXAMPLES]
    txt = [f"{e['name']} · {e['area_km2']} km²" for e in EXAMPLES]
    fig = go.Figure(go.Scattermapbox(
        lat=lats, lon=lons, mode="markers",
        marker=dict(size=13, color=WC), text=txt,
        customdata=[e["id"] for e in EXAMPLES],
        hovertemplate="%{text}<extra></extra>", name="catchments"))
    fig.update_layout(mapbox=dict(style="open-street-map", center=dict(lat=51.1, lon=10.3), zoom=5),
                      margin=dict(l=0, r=0, t=0, b=0), height=560, showlegend=False)
    return fig


def empty_fig(msg):
    f = go.Figure(); f.update_layout(base_layout(""), annotations=[dict(
        text=msg, showarrow=False, font=dict(color="#7c9098", size=14))],
        xaxis=dict(visible=False), yaxis=dict(visible=False), height=330)
    return f


# ---- app ----------------------------------------------------------------
app = Dash(__name__, title="Germany-Hydrology", update_title=None,
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
server = app.server                                             # gunicorn entrypoint

CLIM_VARS = [("p", "Precipitation (mm)"), ("t", "Mean temp (°C)"),
             ("pet", "PET (mm)"), ("q", "Discharge (mm)")]

app.layout = html.Div([
  dcc.Store(id="sel"),
  html.Header([
    html.Div([html.H1("💧 Germany-Hydrology"),
      html.Div("Explore German catchment climate and gauges, then calibrate an HBV "
               "rainfall-runoff model live — powered by the germany-hydrology Python package.",
               className="tag")], className="brand"),
    html.Div([
      html.A("GitHub ↗", href="https://github.com/Bluerrror/germany-hydrology", target="_blank", className="badge solid"),
      html.A("Docs", href="https://github.com/Bluerrror/germany-hydrology#readme", target="_blank", className="badge"),
      html.A("More apps", href="https://bluerror.com/apps.html", target="_blank", className="badge"),
    ], className="links")]),

  html.Main([
    html.Div([dcc.Graph(id="map", figure=map_figure(), config={"displayModeBar": False}),
      html.Div("Click a blue marker to load a CAMELS-DE catchment (25–40 yr of daily "
               "discharge & forcing).", className="maphint")], className="card"),

    html.Div([
      dcc.Tabs(id="tabs", value="catch", className="tabs", children=[
        dcc.Tab(label="Catchment", value="catch", className="tab", selected_className="tab-sel"),
        dcc.Tab(label="Climate", value="clim", className="tab", selected_className="tab-sel"),
        dcc.Tab(label="HBV model", value="hbv", className="tab", selected_className="tab-sel"),
        dcc.Tab(label="Live gauge", value="gauge", className="tab", selected_className="tab-sel"),
      ]),
      html.Div(id="tabbody", className="tabbody"),
    ], className="card panel"),
  ]),

  html.Footer("Data © providers, reused with attribution: DWD · WSV PEGELONLINE · HydroSHEDS · "
              "CAMELS-DE (Loritz et al. 2024, CC-BY 4.0) · ERA5 via Open-Meteo (CC-BY 4.0). "
              "App & package Apache-2.0."),
])


# ---- select catchment from map -----------------------------------------
@app.callback(Output("sel", "data"), Input("map", "clickData"))
def on_click(cd):
    if not cd:
        return no_update
    cid = cd["points"][0].get("customdata")
    return cid if cid in VALID_IDS else no_update


# ---- tab router ---------------------------------------------------------
@app.callback(Output("tabbody", "children"), Input("tabs", "value"), Input("sel", "data"))
def render_tab(tab, cid):
    meta = EX_BY_ID.get(cid)
    if tab == "catch":
        return catch_body(meta)
    if tab == "clim":
        return clim_body(meta)
    if tab == "hbv":
        return hbv_body(meta)
    if tab == "gauge":
        return gauge_body()
    return no_update


def stat(k, v):
    return html.Div([html.Div(k, className="k"), html.Div(v, className="v")], className="stat")


def catch_body(meta):
    if not meta:
        return html.Div("Pick a catchment on the map to see its climate and enable the model.",
                        className="hint")
    dates, P, T, E, Q = load_catchment(meta["id"])
    yrs = len(Q) / 365.25
    meanP = np.nanmean(P) * 365.25; meanT = np.nanmean(T); meanQ = np.nanmean(Q)
    rr = (np.nanmean(Q) / np.nanmean(P)) if np.nanmean(P) else float("nan")
    # monthly regime
    dfp = pd.DataFrame({"m": dates.month, "P": P, "T": T})
    ny = dates.year.nunique()
    mp = dfp.groupby("m")["P"].sum() / ny
    mt = dfp.groupby("m")["T"].mean()
    mon = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    fig = go.Figure([
        go.Bar(x=mon, y=mp.values, name="Precip", marker_color=WC),
        go.Scatter(x=mon, y=mt.values, name="Temp", yaxis="y2", mode="lines+markers",
                   line=dict(color=ACC, width=2))])
    fig.update_layout(base_layout("Mean monthly regime"), hovermode="x",
                      yaxis=dict(title="mm/month", gridcolor=GRID),
                      yaxis2=dict(title="°C", overlaying="y", side="right"),
                      legend=dict(orientation="h", y=-0.2))
    return html.Div([
        html.Div("Selected catchment", className="eyebrow"),
        html.H2(f"{meta['name']} · {meta.get('water','')}"),
        html.Div(f"CAMELS-DE gauge {meta['id']} · {dates[0].year}–{dates[-1].year}", className="hint"),
        html.Div([stat("Area (km²)", f"{meta['area_km2']:.0f}"), stat("Record (yr)", f"{yrs:.0f}"),
                  stat("Mean P (mm/yr)", f"{meanP:.0f}"), stat("Mean T (°C)", f"{meanT:.1f}"),
                  stat("Mean Q (mm/d)", f"{meanQ:.2f}"), stat("Runoff ratio", f"{rr:.2f}")],
                 className="statrow"),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ])


def clim_body(meta):
    return html.Div([
        html.Div("Daily climate", className="eyebrow"),
        html.Div([
            html.Div([html.Label("Variable"), dcc.Dropdown(
                id="clv", options=[{"label": l, "value": k} for k, l in CLIM_VARS],
                value="p", clearable=False, style={"width": "220px"})], className="field"),
            html.Div([html.Label("Resolution"), dcc.Dropdown(
                id="clr", options=[{"label": x, "value": v} for x, v in
                                   [("daily", "D"), ("monthly", "M"), ("annual", "Y")]],
                value="M", clearable=False, style={"width": "150px"})], className="field"),
        ], className="controls"),
        dcc.Graph(id="clfig", config={"displayModeBar": False}),
        html.Div("From the catchment's CAMELS-DE record. In Python: "
                 "from_source(\"camels-de\", gauge=…) / \"era5-timeseries\".", className="note"),
    ]) if meta else html.Div("Select a catchment first.", className="hint")


@app.callback(Output("clfig", "figure"), Input("clv", "value"), Input("clr", "value"),
              State("sel", "data"))
def draw_clim(var, res, cid):
    meta = EX_BY_ID.get(cid)
    if not meta:
        return empty_fig("Select a catchment.")
    dates, P, T, E, Q = load_catchment(meta["id"])
    series = {"p": P, "t": T, "pet": E, "q": Q}[var]
    s = pd.Series(series, index=dates)
    label = dict(CLIM_VARS)[var]
    flux = var in ("p", "pet", "q")
    if res != "D":
        s = (s.resample("MS" if res == "M" else "YS").sum() if flux
             else s.resample("MS" if res == "M" else "YS").mean())
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines",
                    line=dict(color=WC, width=1.3), fill="tozeroy" if flux else None,
                    fillcolor="rgba(44,110,156,.12)"))
    fig.update_layout(base_layout(label, 340), yaxis=dict(title=label, gridcolor=GRID))
    return fig


def hbv_body(meta):
    if not meta:
        return html.Div("Select a CAMELS-DE catchment — the model needs its discharge record.",
                        className="hint")
    dates, *_ = load_catchment(meta["id"])
    y0, y1 = dates[0].year + 2, dates[-1].year
    return html.Div([
        html.Div("HBV-96 · vectorised random-search calibration", className="eyebrow"),
        html.Div([
            html.Div([html.Label("Training years (end)"),
                dcc.Slider(id="split", min=y0 + 1, max=y1 - 1, step=1,
                           value=int(y0 + (y1 - y0) * 0.6),
                           marks={y: str(y) for y in range(y0 + 1, y1, max(1, (y1 - y0) // 6))},
                           tooltip={"placement": "bottom", "always_visible": True})],
                className="field", style={"flex": "1", "minWidth": "260px"}),
            html.Div([html.Label("Objective"), dcc.Dropdown(id="obj", clearable=False,
                options=[{"label": o.upper(), "value": o} for o in ("kge", "nse", "rmse")],
                value="kge", style={"width": "130px"})], className="field"),
            html.Div([html.Label("Samples"), dcc.Input(id="nsamp", type="number", value=5000,
                min=500, max=MAX_ENSEMBLE, step=500, style={"width": "100px"})], className="field"),
            html.Button("Calibrate", id="run", className="act"),
        ], className="controls"),
        dcc.Loading(html.Div(id="hbvout"), type="default", color=WC),
        html.Div("Same HBV-96 as the package (germany_hydrology.hbv.simulate): snow, soil "
                 "moisture, two response boxes, MAXBAS routing. Blue = training span, amber = "
                 "test. For the reference Optuna 70-yr study see the calibration notebook.",
                 className="note"),
    ])


@app.callback(Output("hbvout", "children"), Input("run", "n_clicks"),
              State("split", "value"), State("obj", "value"), State("nsamp", "value"),
              State("sel", "data"), prevent_initial_call=True)
def run_calibration(_, split, obj, nsamp, cid):
    meta = EX_BY_ID.get(cid)
    if not meta:
        return html.Div("Select a catchment first.", className="hint")
    dates, P, T, E, Q = load_catchment(meta["id"])
    years = dates.year.values
    warmup = dates[0].year + 2
    valid = np.isfinite(Q)
    train = (years >= warmup) & (years <= int(split)) & valid
    test = (years > int(split)) & valid
    if train.sum() < 365:
        return html.Div("Training window too short — move the split later.", className="hint")
    obj = obj if obj in ("kge", "nse", "rmse") else "kge"
    Qf = np.where(valid, Q, 0.0)
    bp, sim = calibrate_fast(P, T, E, Qf, train, kind=obj, n=int(nsamp or 5000))

    mtr = dict(nse=nse(Q[train], sim[train]), kge=kge(Q[train], sim[train]))
    has_test = test.sum() >= 3
    mte = dict(nse=nse(Q[test], sim[test]), kge=kge(Q[test], sim[test])) if has_test else None

    # hydrograph
    start = np.argmax(years >= warmup)
    x = dates[start:]; yo = np.where(valid, Q, np.nan)[start:]; ys = sim[start:]
    splitdate = pd.Timestamp(int(split) + 1, 1, 1)
    fig = go.Figure([
        go.Scatter(x=x, y=yo, name="observed", line=dict(color=INK, width=1.3)),
        go.Scatter(x=x, y=ys, name="HBV simulated", line=dict(color=WC, width=1.3))])
    fig.update_layout(base_layout("Observed vs HBV-simulated discharge (mm/day)", 360),
        legend=dict(orientation="h", y=-0.16), yaxis=dict(title="Q (mm/day)", gridcolor=GRID),
        shapes=[dict(type="rect", xref="x", yref="paper", x0=x[0], x1=splitdate, y0=0, y1=1,
                     fillcolor=WC, opacity=0.06, line_width=0),
                dict(type="rect", xref="x", yref="paper", x0=splitdate, x1=x[-1], y0=0, y1=1,
                     fillcolor=ACC, opacity=0.07, line_width=0)])

    def sbox(k, v, good):
        return html.Div([html.Div(k, className="k"), html.Div(f"{v:.2f}", className="v")],
                        className="stat " + ("good" if good else "warn"))
    stats = [sbox("Train NSE", mtr["nse"], mtr["nse"] > 0.5),
             sbox("Train KGE", mtr["kge"], mtr["kge"] > 0.5)]
    if mte:
        stats += [sbox("Test NSE", mte["nse"], mte["nse"] > 0.5),
                  sbox("Test KGE", mte["kge"], mte["kge"] > 0.5)]
    params = [html.Div([n, html.B(f"{bp[n]:.3g}")], className="p") for n in hbv.PARAM_NAMES]
    msg = f"Calibrated on {warmup}–{split} ({train.sum()} days), tested on {int(split)+1}–{dates[-1].year}."
    return html.Div([html.Div(stats, className="statrow"),
                     dcc.Graph(figure=fig, config={"displayModeBar": False}),
                     html.Div(params, className="paramgrid"),
                     html.Div(msg, className="hint")])


# ---- live gauge (PEGELONLINE) ------------------------------------------
@lru_cache(maxsize=1)
def gauge_index():
    r = requests.get("https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json"
                     "?includeTimeseries=true", headers=UA, timeout=25)
    rows = r.json()
    out = {}
    for s in rows:
        if not s.get("longitude"):
            continue
        ts = {t["shortname"] for t in s.get("timeseries", [])}
        out[s["shortname"]] = {"name": s["longname"], "water": (s.get("water") or {}).get("longname", ""), "ts": ts}
    return out


def gauge_body():
    try:
        idx = gauge_index()
    except Exception as e:
        return html.Div(f"Gauge list unavailable right now ({e}).", className="hint")
    opts = [{"label": f"{sh} — {v['name']} ({v['water']})", "value": sh}
            for sh, v in sorted(idx.items())]
    first = opts[0]["value"] if opts else None
    return html.Div([
        html.Div("Live river gauge · PEGELONLINE (WSV)", className="eyebrow"),
        html.Div([
            html.Div([html.Label("Gauge"), dcc.Dropdown(id="gsel", options=opts, value=first,
                clearable=False, style={"width": "340px"})], className="field"),
            html.Div([html.Label("Series"), dcc.Dropdown(id="gpar", clearable=False,
                options=[{"label": "water level", "value": "W"}, {"label": "discharge", "value": "Q"}],
                value="W", style={"width": "150px"})], className="field"),
        ], className="controls"),
        dcc.Loading(dcc.Graph(id="gfig", config={"displayModeBar": False}), color=WC),
        html.Div("Raw operational values, last ~30 days. In Python: "
                 "from_source(\"pegelonline\", station=…).", className="note"),
    ])


@app.callback(Output("gfig", "figure"), Input("gsel", "value"), Input("gpar", "value"))
def draw_gauge(sh, par):
    idx = gauge_index()
    if sh not in idx or par not in ("W", "Q"):        # whitelist + enum guard
        return empty_fig("Pick a gauge.")
    base = f"https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/{requests.utils.quote(sh)}"
    try:
        meta = requests.get(f"{base}/{par}.json", headers=UA, timeout=20).json()
        rows = requests.get(f"{base}/{par}/measurements.json?start=P30D", headers=UA, timeout=25).json()
    except Exception as e:
        return empty_fig(f"No {par} at this gauge ({e}).")
    x = [r["timestamp"] for r in rows]; y = [r["value"] for r in rows]
    unit = meta.get("unit", "")
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines", line=dict(color=WC, width=1.2)))
    fig.update_layout(base_layout(f"{sh} — {meta.get('shortname', par)} [{unit}]", 360),
                      yaxis=dict(title=f"{meta.get('shortname', par)} [{unit}]", gridcolor=GRID))
    return fig


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
