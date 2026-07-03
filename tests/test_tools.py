# (C) Copyright 2026. Apache-2.0.

"""Offline tests: new sources' URL/tile math, signatures, network navigation."""

import numpy as np
import pandas as pd
import pytest

from germany_hydrology import network, signatures as hs
from germany_hydrology.camels import CamelsDeSource
from germany_hydrology.dem import CopernicusDemSource
from germany_hydrology.dwd_grids import DwdGridsSource
from germany_hydrology.landcover import WorldCoverSource


# -- tile math ---------------------------------------------------------------

def test_dem_tiles_cover_bbox():
    src = CopernicusDemSource(bbox=[9.2, 51.3, 10.6, 52.0])
    urls = src._tile_urls()
    assert len(urls) == 2  # N51E009, N51E010
    assert any("N51_00_E009" in u for u in urls)
    assert any("N51_00_E010" in u for u in urls)
    assert all("COG_10" in u for u in urls)


def test_dem_90m_and_negative_coords():
    src = CopernicusDemSource(bbox=[-1.5, -0.5, -0.9, 0.5], resolution=90)
    urls = src._tile_urls()
    assert any("S01_00_W002" in u for u in urls)
    assert any("N00_00_W002" in u for u in urls)
    assert all("COG_30" in u and "dem-90m" in u for u in urls)


def test_worldcover_tiles_are_3deg():
    src = WorldCoverSource(bbox=[9.0, 51.0, 10.6, 52.0])
    urls = src._tile_urls()
    assert urls == [
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N51E009_Map.tif"
    ]


def test_dwd_grids_validation():
    with pytest.raises(ValueError):
        DwdGridsSource(variable="nope", years=2020)
    with pytest.raises(ValueError):
        DwdGridsSource(variable="precipitation")  # years missing


def test_camels_validation():
    with pytest.raises(ValueError):
        CamelsDeSource(table="timeseries")  # needs gauge
    with pytest.raises(ValueError):
        CamelsDeSource(table="nope")


# -- signatures ----------------------------------------------------------------

def test_nse_kge_perfect():
    q = pd.Series(np.sin(np.linspace(0, 10, 500)) + 2)
    assert hs.nse(q, q) == pytest.approx(1.0)
    assert hs.kge(q, q) == pytest.approx(1.0)
    assert hs.pbias(q, q) == pytest.approx(0.0)


def test_nse_mean_benchmark_is_zero():
    rng = np.random.default_rng(0)
    q = rng.gamma(2, 2, 1000)
    assert hs.nse(q, np.full_like(q, q.mean())) == pytest.approx(0.0)


def test_fdc_monotone_and_slope_positive():
    rng = np.random.default_rng(1)
    q = pd.Series(rng.lognormal(0, 1, 2000))
    fdc = hs.flow_duration_curve(q)
    assert (np.diff(fdc.values) <= 1e-12).all()  # decreasing with exceedance
    assert hs.fdc_slope(q) > 0


def test_baseflow_bounds():
    idx = pd.date_range("2000-01-01", periods=730)
    rng = np.random.default_rng(2)
    q = pd.Series(rng.gamma(2, 3, 730) + 1, index=idx)
    b = hs.baseflow(q)
    assert (b <= q + 1e-9).all() and (b >= 0).all()
    assert 0 < hs.baseflow_index(q) < 1


def test_flashiness_constant_flow_is_zero():
    assert hs.richards_baker_flashiness(np.full(100, 5.0)) == 0.0


def test_runoff_ratio():
    assert hs.runoff_ratio([1, 1], [2, 2]) == pytest.approx(0.5)


# -- network navigation --------------------------------------------------------

@pytest.fixture
def toy_basins():
    import geopandas as gpd
    from shapely.geometry import Point

    #     1 -> 3 -> 4(outlet, NEXT_DOWN=0)
    #     2 -> 3
    #     5 -> 4
    return gpd.GeoDataFrame({
        "HYBAS_ID": [1, 2, 3, 4, 5],
        "NEXT_DOWN": [3, 3, 4, 0, 4],
        "geometry": [Point(i, i) for i in range(5)],
    })


def test_upstream(toy_basins):
    up = network.upstream(toy_basins, 3)
    assert set(up["HYBAS_ID"]) == {1, 2, 3}
    up_no = network.upstream(toy_basins, 3, include_outlet=False)
    assert set(up_no["HYBAS_ID"]) == {1, 2}


def test_downstream_order(toy_basins):
    path = network.downstream(toy_basins, 1)
    assert list(path["HYBAS_ID"]) == [1, 3, 4]


def test_headwaters(toy_basins):
    assert set(network.headwaters(toy_basins)["HYBAS_ID"]) == {1, 2, 5}
