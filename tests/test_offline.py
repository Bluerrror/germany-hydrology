# (C) Copyright 2026. Apache-2.0.

"""Offline unit tests: URL construction, validation, parsers. No network."""

import io
import zipfile

import pandas as pd
import pytest

from earthkit_data_hydrology_germany.buek import Buek1000Source
from earthkit_data_hydrology_germany.dwd import DwdObservationsSource
from earthkit_data_hydrology_germany.era5 import Era5TimeseriesSource
from earthkit_data_hydrology_germany.hydrosheds import GERMANY, HydroshedsSource
from earthkit_data_hydrology_germany.pegelonline import PegelonlineSource


# -- era5-timeseries -------------------------------------------------------

def test_era5_url():
    src = Era5TimeseriesSource(
        latitude=51.5, longitude=9.9, start="2020-01-01", end="2020-12-31",
        variables=["precipitation_sum"],
    )
    url = src._build_url()
    assert url.startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "latitude=51.5" in url and "longitude=9.9" in url
    assert "daily=precipitation_sum" in url
    assert "models=era5" in url and "timezone=UTC" in url


def test_era5_multi_point_and_hourly():
    src = Era5TimeseriesSource(
        latitude=[51.5, 52.0], longitude=[9.9, 10.5],
        start="2020-01-01", end="2020-01-02", frequency="hourly",
        model="era5_land",
    )
    url = src._build_url()
    assert "latitude=51.5%2C52.0" in url
    assert "hourly=" in url and "models=era5_land" in url


def test_era5_validation():
    with pytest.raises(ValueError):
        Era5TimeseriesSource(latitude=51.5, longitude=9.9)  # missing dates
    with pytest.raises(ValueError):
        Era5TimeseriesSource(latitude=[1, 2], longitude=[1],
                             start="2020-01-01", end="2020-01-02")


# -- dwd-observations ------------------------------------------------------

def test_dwd_recent_url():
    src = DwdObservationsSource(station=44)
    assert src._recent_url() == (
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
        "climate/daily/kl/recent/tageswerte_KL_00044_akt.zip"
    )


def test_dwd_station_id_padding():
    assert DwdObservationsSource(station="433").station == "00433"


def test_dwd_invalid_dataset():
    with pytest.raises(ValueError):
        DwdObservationsSource(resolution="daily", dataset="nope")


def test_dwd_zip_parser(tmp_path):
    txt = (
        "STATIONS_ID;MESS_DATUM;QN_3;RSK;TMK;eor\n"
        "44;20200101;10;0.0;2.5;eor\n"
        "44;20200102;10;-999;3.1;eor\n"
    )
    p = tmp_path / "tageswerte_KL_00044_akt.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("produkt_klima_tag_20200101_20200102_00044.txt", txt)
    df = DwdObservationsSource._read_zip(p)
    assert df.index.name == "MESS_DATUM"
    assert df.index[0] == pd.Timestamp("2020-01-01")
    assert pd.isna(df["RSK"].iloc[1])  # -999 -> NaN
    assert "eor" not in df.columns


# -- pegelonline -----------------------------------------------------------

def test_pegelonline_defaults():
    src = PegelonlineSource(station="HANN.MUENDEN")
    assert src.parameter == "W" and src.start == "P15D"


# -- hydrosheds --------------------------------------------------------------

def test_hydrosheds_urls():
    b = HydroshedsSource(product="basins", level=6)
    assert b._build_url().endswith("hybas_eu_lev06_v1c.zip")
    r = HydroshedsSource(product="rivers")
    assert r._build_url().endswith("HydroRIVERS_v10_eu_shp.zip")


def test_hydrosheds_validation():
    with pytest.raises(ValueError):
        HydroshedsSource(product="lakes")
    with pytest.raises(ValueError):
        HydroshedsSource(product="basins", level=0)


def test_germany_bbox_sane():
    w, s, e, n = GERMANY
    assert w < e and s < n and 5 < w < 7 and 54 < n < 56


# -- entry points ------------------------------------------------------------

def test_entry_points_registered():
    from importlib.metadata import entry_points

    eps = entry_points(group="earthkit.data.sources")
    names = {e.name for e in eps}
    for name in ("era5-timeseries", "dwd-observations", "pegelonline",
                 "hydrosheds", "buek1000"):
        assert name in names, f"entry point {name} missing"


def test_buek_defaults():
    src = Buek1000Source()
    assert src.bbox is None and src.to_crs == "EPSG:4326"
