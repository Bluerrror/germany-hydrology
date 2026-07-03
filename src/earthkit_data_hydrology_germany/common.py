# (C) Copyright 2026. Apache-2.0.

"""Shared plumbing for all sources in this package.

Static/heavy files (DWD zips, shapefile archives, ERA5 archive responses)
go through earthkit's cached ``url`` source; live JSON APIs (PEGELONLINE)
are fetched directly so results are never stale.
"""

import json
import urllib.request

USER_AGENT = "earthkit-data-hydrology-germany/0.1"


def cached_download(url):
    """Download ``url`` through earthkit's caching machinery; return local path."""
    from earthkit.data.sources import get_source

    return get_source("url", url).path


def fetch_json(url):
    """GET a live JSON endpoint (no caching)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_text(url):
    """GET a small live text page (no caching), e.g. a directory listing."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def extract_shapefile_zip(zip_path):
    """Extract a zipped shapefile next to the cached zip; return the .shp path.

    Spatial-index sidecars (``.sbn``/``.sbx``) are dropped: HydroSHEDS ships
    ones GDAL cannot parse, and they are only an optimisation.
    """
    import glob
    import os
    import zipfile

    dest = str(zip_path) + ".extracted"
    if not os.path.isdir(dest):
        with zipfile.ZipFile(zip_path) as z:
            members = [m for m in z.namelist()
                       if not m.lower().endswith((".sbn", ".sbx"))]
            z.extractall(dest, members=members)
    return sorted(glob.glob(os.path.join(dest, "**", "*.shp"), recursive=True))[0]


def read_shapefile_zip(zip_path, bbox=None):
    """Read a zipped shapefile (see :func:`extract_shapefile_zip`)."""
    import geopandas as gpd

    shp = extract_shapefile_zip(zip_path)
    return gpd.read_file(shp, bbox=tuple(bbox) if bbox is not None else None)


class TabularData:
    """Data object wrapping a DataFrame (time series / station tables)."""

    def __init__(self, df):
        self._df = df

    def to_pandas(self, **kwargs):
        return self._df

    def to_xarray(self, **kwargs):
        return self._df.to_xarray()

    def __repr__(self):
        return f"{self.__class__.__name__}({self._df.shape[0]} rows x {self._df.shape[1]} cols)"


class GeoData(TabularData):
    """Data object wrapping a GeoDataFrame (basins, rivers, soil polygons)."""

    def to_geopandas(self, **kwargs):
        return self._df

    def to_xarray(self, **kwargs):
        raise NotImplementedError("Vector data: use to_pandas()/to_geopandas().")
