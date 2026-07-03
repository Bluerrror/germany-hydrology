# Germany-Hydrology

**All the data a German rainfall–runoff model needs, through one interface.**

[![tests](https://github.com/Bluerrror/germany-hydrology/actions/workflows/tests.yml/badge.svg)](https://github.com/Bluerrror/germany-hydrology/actions/workflows/tests.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![earthkit-data](https://img.shields.io/badge/earthkit--data-%E2%89%A51.0-green.svg)](https://earthkit-data.readthedocs.io/)

Nine data sources and two analysis toolkits for hydrology in Germany —
forcing, observations, river gauges, catchments, rivers, terrain, land cover
and soil — all as [earthkit-data](https://earthkit-data.readthedocs.io/)
`from_source(...)` calls, all free, no API keys. Inspired by the
[HyRiver](https://github.com/hyriver) suite, built on the German/European
open-data equivalents.

### Data sources

| source | what you get | returns |
|--------|--------------|---------|
| `era5-timeseries`  | ERA5 / ERA5-Land point time series (1940→, via [Open-Meteo](https://open-meteo.com/)) | DataFrame |
| `dwd-observations` | DWD station observations: daily/hourly/monthly climate + station catalogue | DataFrame |
| `dwd-grids`        | DWD **HYRAS** gridded daily climate (1 km NetCDF: precipitation, temperature, humidity, radiation) | Dataset |
| `pegelonline`      | live water level / discharge at ~660 federal waterway gauges (WSV) | DataFrame |
| `camels-de`        | **CAMELS-DE**: 70-year daily series + attributes + boundaries for 1582 German catchments | DataFrame / GeoDataFrame |
| `hydrosheds`       | HydroBASINS catchments (Pfafstetter 1–12) + HydroRIVERS river network | GeoDataFrame |
| `buek1000`         | BÜK1000 German soil map polygons (BGR) | GeoDataFrame |
| `copernicus-dem`   | Copernicus GLO-30 / GLO-90 elevation, mosaicked + clipped to your bbox | DataArray |
| `worldcover`       | ESA WorldCover 10 m land cover, mosaicked + clipped | DataArray |

### Toolkits (in the spirit of HydroSignatures / PyNHD)

| module | what it does |
|--------|--------------|
| `germany_hydrology.hbv` | full HBV-96 rainfall–runoff model (snow, soil moisture, two-box response, MAXBAS routing), vectorised over parameter sets, with **Optuna calibration**: user-selectable objective (`nse`/`kge`/`log_nse`/callable), calibration & validation periods, bounds and fixed parameters |
| `germany_hydrology.signatures` | NSE, KGE, PBIAS, flow-duration curve + slope, Lyne–Hollick baseflow + BFI, Richards–Baker flashiness, runoff ratio, half-flow date, high/low-flow frequency |
| `germany_hydrology.network` | navigate HydroBASINS/HydroRIVERS topology: `upstream()`, `downstream()`, `headwaters()` |

```python
from germany_hydrology import hbv

result = hbv.calibrate(
    precip, temp, pet, q_obs,               # daily Series, mm/day & °C
    objective="nse",                        # or "kge", "log_nse", any callable
    calibration_period=("1971", "2000"),
    validation_period=("2001", "2020"),
    n_trials=300,
)
result["best_params"], result["validation_score"], result["simulation"]
```

On CAMELS-DE gauge DE110000 this reaches **validation NSE 0.80** (1971–2000
calibration, 2001–2020 test) — see
[`examples/hbv_calibration.ipynb`](examples/hbv_calibration.ipynb)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Bluerrror/germany-hydrology/blob/main/examples/hbv_calibration.ipynb),
which also compares against the published CAMELS-DE HBV/LSTM benchmarks,
plots Optuna parameter importances, and derives a top-50-trial uncertainty
band. Optuna is optional: `pip install germany-hydrology[models]`.

```python
import earthkit.data as ekd
from germany_hydrology import GERMANY, network, signatures as hs

# ERA5 forcing at a catchment centroid — no CDS account needed
forcing = ekd.from_source(
    "era5-timeseries", latitude=51.54, longitude=9.93,
    start="1990-01-01", end="2023-12-31",
    variables=["precipitation_sum", "temperature_2m_mean",
               "et0_fao_evapotranspiration"],
).to_pandas()

# CAMELS-DE: 70 years of discharge + forcing, and hydrological signatures
ts = ekd.from_source("camels-de", gauge="DE110000", path=CAMELS_DIR).to_pandas()
print(hs.baseflow_index(ts["discharge_vol_obs"]), hs.fdc_slope(ts["discharge_vol_obs"]))

# the whole Weser catchment upstream of a basin, from HydroBASINS topology
basins = ekd.from_source("hydrosheds", product="basins", level=7, bbox=GERMANY).to_pandas()
weser = network.upstream(basins, outlet_id)

# terrain, land cover, soil for the model domain
dem = ekd.from_source("copernicus-dem", bbox=[9.0, 51.0, 10.6, 52.0]).to_xarray()
lc  = ekd.from_source("worldcover", bbox=[9.0, 51.0, 10.6, 52.0]).to_xarray()
soil = ekd.from_source("buek1000", bbox=[9.0, 51.0, 10.6, 52.0]).to_pandas()

# HYRAS gridded daily precipitation over the same box
pr = ekd.from_source("dwd-grids", variable="precipitation", years=[2019, 2020],
                     bbox=[9.0, 51.0, 10.6, 52.0]).to_xarray()
```

<p align="center">
  <img src="docs/weser_map.png" alt="Weser headwaters: HydroBASINS catchments, HydroRIVERS network and PEGELONLINE gauges" width="620">
</p>

### Notebooks

- 📓 [`examples/quickstart.ipynb`](examples/quickstart.ipynb)
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Bluerrror/germany-hydrology/blob/main/examples/quickstart.ipynb)
  — one catchment, all datasets: map, gauges, DWD vs ERA5, terrain, land
  cover, soil.
- 🗺️ [`examples/basin_explorer.ipynb`](examples/basin_explorer.ipynb)
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Bluerrror/germany-hydrology/blob/main/examples/basin_explorer.ipynb)
  — **interactive**: click a basin on the map (or pick a gauge), choose the
  climate/land-cover/soil/hydrology source per domain, press Fetch — the
  basin's data lands in one dict, previews included.

Gridded **soil properties** (pH, texture, SOC, …) live in the companion plugin
[earthkit-data-soilgrids](https://github.com/Bluerrror/earthkit-data-soilgrids).

## Install

```bash
pip install git+https://github.com/Bluerrror/germany-hydrology
```

Dependencies: `earthkit-data>=1.0`, `pandas`, `geopandas`, `pyproj`,
`rioxarray`, `h5netcdf`. On **Windows**, install `earthkit-data` first with
`--no-deps` (its ecCodes dependency has no Windows wheels and is only needed
for GRIB — see the
[soilgrids README](https://github.com/Bluerrror/earthkit-data-soilgrids#install)
for the exact commands).

## Sources in detail

### `era5-timeseries`

| argument | default | notes |
|----------|---------|-------|
| `latitude`, `longitude` | — | scalars or equal-length lists (multi-point) |
| `start`, `end` | — | `YYYY-MM-DD`; archive reaches back to 1940, ~5 days behind real time |
| `variables` | `precipitation_sum, temperature_2m_mean` | any [Open-Meteo historical variables](https://open-meteo.com/en/docs/historical-weather-api) |
| `frequency` | `"daily"` | or `"hourly"` |
| `model` | `"era5"` | `"era5_land"` (9 km), `"best_match"`, `"cerra"`, ... |

Units land in `df.attrs["units"]`. For full gridded ERA5 use earthkit-data's
built-in `cds` source with a Copernicus account.

### `dwd-observations`

| argument | default | notes |
|----------|---------|-------|
| `station` | `None` | DWD id (`44` or `"00044"`); omit for the station catalogue with coordinates |
| `resolution` / `dataset` | `"daily"` / `"kl"` | also `daily/more_precip`, `hourly/precipitation`, `hourly/air_temperature`, `monthly/kl` |
| `period` | `"recent"` | `"recent"` (~last 500 days), `"historical"`, `"all"` (merged) |

Column names are DWD's (`RSK` precipitation, `TMK` mean temperature, `TXK`/`TNK`
max/min, ...); `-999` is masked to NaN.

### `dwd-grids` (HYRAS)

| argument | default | notes |
|----------|---------|-------|
| `variable` | `"precipitation"` | `air_temperature_mean/max/min`, `humidity`, `radiation_global` |
| `years` | — | int or list; ~40–130 MB per year, cached |
| `bbox` | all of Germany | `[W, S, E, N]` lon/lat crop |

### `pegelonline`

| argument | default | notes |
|----------|---------|-------|
| `station` | `None` | shortname (`"HANN.MUENDEN"`), uuid or number; omit for the catalogue |
| `parameter` | `"W"` | water level; `"Q"` discharge where offered |
| `start` | `"P15D"` | ISO-8601 period or timestamp; the API keeps ~31 days |

Live operational values, never cached. For long records use `camels-de` or GRDC.

### `camels-de`

| argument | default | notes |
|----------|---------|-------|
| `gauge` | `None` | e.g. `'DE110000'` → daily time series 1951–2020 |
| `table` | auto | `'attributes'` (all attribute tables joined), a single table (`'soil'`, `'topographic'`, ...), `'simulated'` (LSTM/HBV benchmarks), `'catchments'`, `'stations'` |
| `path` | Zenodo download | directory of an existing extracted CAMELS-DE copy (recommended — the archive is 2.2 GB) |

### `hydrosheds`

| argument | default | notes |
|----------|---------|-------|
| `product` | `"basins"` | or `"rivers"` |
| `level` | `6` | Pfafstetter level 1–12 (basins only) |
| `bbox` | whole region | `[W, S, E, N]` lon/lat; `GERMANY` constant provided |
| `region` | `"eu"` | HydroSHEDS region code |

### `buek1000`

| argument | default | notes |
|----------|---------|-------|
| `bbox` | all of Germany | `[W, S, E, N]` in lon/lat |
| `to_crs` | `"EPSG:4326"` | output CRS; `None` keeps native |

### `copernicus-dem`

| argument | default | notes |
|----------|---------|-------|
| `bbox` | — | required, `[W, S, E, N]` lon/lat |
| `resolution` | `30` | metres; `90` for the lighter GLO-90 (~4 MB/tile) |

### `worldcover`

| argument | default | notes |
|----------|---------|-------|
| `bbox` | — | required; tiles are 3°×3°, ~40–90 MB each |
| `year` | `2021` | v200; `2020` = v100 |

Class codes: `germany_hydrology.landcover.CLASSES`.

## Caching

Static files (DWD zips/NetCDFs, HydroSHEDS/BÜK/CAMELS archives, DEM and land
cover tiles, ERA5 archive responses) go through earthkit's cache — set
`ekd.config.set("cache-policy", "user")` to keep them between sessions.
PEGELONLINE is live data and is never cached.

## Development

```bash
pip install -e ".[test]"
pytest        # offline: URL/tile math, parsers, signatures, network navigation
```

## Licenses & attribution

This package is Apache-2.0. The **data** have their own terms — cite/attribute
when you publish:

- **ERA5** via Open-Meteo: contains modified Copernicus Climate Change Service
  information; Open-Meteo under CC-BY 4.0 ([Zippenfenig 2023](https://doi.org/10.5281/zenodo.7970649),
  [Hersbach et al. 2020](https://doi.org/10.1002/qj.3803)).
- **DWD** (observations & HYRAS): © Deutscher Wetterdienst,
  [CC-BY 4.0 / GeoNutzV](https://www.dwd.de/EN/service/copyright/copyright_artikel.html) — "Quelle: Deutscher Wetterdienst".
- **PEGELONLINE**: © WSV, raw un-validated operational values, [GeoNutzV](https://www.pegelonline.wsv.de/gast/impressum).
- **CAMELS-DE**: CC-BY 4.0 — cite [Loritz et al. (2024)](https://doi.org/10.5194/essd-16-5625-2024)
  and [doi:10.5281/zenodo.13837553](https://doi.org/10.5281/zenodo.13837553).
- **HydroSHEDS / HydroBASINS / HydroRIVERS**: free with attribution per the
  [HydroSHEDS license](https://www.hydrosheds.org/page/license); cite
  [Lehner & Grill (2013)](https://doi.org/10.1002/hyp.9740).
- **BÜK1000**: © BGR, Hannover.
- **Copernicus DEM**: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH,
  provided under COPERNICUS by the European Union and ESA.
- **ESA WorldCover**: © ESA WorldCover project / CC-BY 4.0.
