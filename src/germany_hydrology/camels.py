# (C) Copyright 2026. Apache-2.0.

"""CAMELS-DE — hydrometeorological time series and attributes for 1582
German catchments (Loritz et al. 2024, CC-BY 4.0).

Daily discharge, forcing and static attributes, 1951-2020::

    # all static attributes (topography + soil + climate + ... joined)
    attrs = ekd.from_source("camels-de", path=CAMELS_DIR).to_pandas()

    # daily time series for one gauge
    ts = ekd.from_source("camels-de", gauge="DE110000", path=CAMELS_DIR).to_pandas()

    # catchment polygons
    shapes = ekd.from_source("camels-de", table="catchments", path=CAMELS_DIR).to_pandas()

``path`` points at an extracted copy of the dataset. Without it, the 2.2 GB
archive is downloaded from Zenodo once and cached (doi:10.5281/zenodo.13837553).
"""

import os
import zipfile

from earthkit.data.sources import Source

from .common import GeoData, TabularData, cached_download

ZENODO_ZIP = "https://zenodo.org/records/13837553/files/camels_de.zip"

ATTRIBUTE_TABLES = [
    "topographic", "soil", "landcover", "hydrogeology", "hydrologic",
    "climatic", "humaninfluence", "simulation_benchmark",
]


class CamelsDeSource(Source):
    """``from_source('camels-de', ...)``.

    Parameters
    ----------
    gauge : str, optional
        CAMELS-DE gauge id (e.g. ``'DE110000'``) — returns its daily time
        series (``table='timeseries'``, default) or simulated benchmark
        (``table='simulated'``).
    table : str, optional
        Without ``gauge``: ``'attributes'`` (default; all attribute tables
        joined on ``gauge_id``), a single table name
        (``'topographic'``, ``'soil'``, ...), ``'catchments'`` or
        ``'stations'`` (GeoDataFrames).
    path : str, optional
        Directory of an extracted CAMELS-DE copy. Default: download from
        Zenodo (2.2 GB, one-time, cached).
    """

    def __init__(self, gauge=None, table=None, path=None, **kwargs):
        super().__init__(**kwargs)
        self.gauge = gauge
        self.table = table or ("timeseries" if gauge else "attributes")
        self.path = path
        valid = set(ATTRIBUTE_TABLES) | {
            "attributes", "timeseries", "simulated", "catchments", "stations",
        }
        if self.table not in valid:
            raise ValueError(f"table must be one of {sorted(valid)}")
        if self.table in ("timeseries", "simulated") and not gauge:
            raise ValueError(f"table={self.table!r} needs a gauge id.")

    # -- file access (extracted directory or the Zenodo zip) ---------------
    def _root(self):
        if self.path:
            return str(self.path)
        return cached_download(ZENODO_ZIP)

    def _member(self, relpath):
        """Return a file-like handle for ``relpath`` inside the dataset."""
        root = self._root()
        if os.path.isdir(root):
            return open(os.path.join(root, relpath), "rb")
        z = zipfile.ZipFile(root)
        names = z.namelist()
        for candidate in (relpath, f"camels_de/{relpath}"):
            candidate = candidate.replace(os.sep, "/")
            if candidate in names:
                return z.open(candidate)
        raise FileNotFoundError(f"{relpath} not found in {root}")

    def _read_csv(self, relpath, **kwargs):
        import pandas as pd

        with self._member(relpath) as f:
            return pd.read_csv(f, **kwargs)

    def _read_geo(self, name):
        import geopandas as gpd

        rel = f"CAMELS_DE_catchment_boundaries/{name}/CAMELS_DE_{name}.gpkg"
        root = self._root()
        if os.path.isdir(root):
            return gpd.read_file(os.path.join(root, rel))
        # extract the single geopackage next to the cached zip, once
        dest = root + ".extracted"
        target = os.path.join(dest, rel)
        if not os.path.isfile(target):
            with zipfile.ZipFile(root) as z:
                member = next(n for n in z.namelist() if n.endswith(f"CAMELS_DE_{name}.gpkg"))
                z.extract(member, dest)
                target = os.path.join(dest, member)
        else:
            target = target
        return gpd.read_file(target)

    # -- tables -------------------------------------------------------------
    def _attributes(self, tables):
        import functools

        import pandas as pd

        frames = [
            self._read_csv(f"CAMELS_DE_{t}_attributes.csv"
                           if t != "simulation_benchmark"
                           else "CAMELS_DE_simulation_benchmark.csv").set_index("gauge_id")
            for t in tables
        ]
        return functools.reduce(
            lambda a, b: a.join(b, how="outer", rsuffix="_dup"), frames
        )

    def _timeseries(self):
        rel = (f"timeseries/CAMELS_DE_hydromet_timeseries_{self.gauge}.csv"
               if self.table == "timeseries"
               else f"timeseries_simulated/CAMELS_DE_discharge_sim_{self.gauge}.csv")
        df = self._read_csv(rel, parse_dates=["date"], index_col="date")
        df.attrs["gauge"] = self.gauge
        df.attrs["source"] = "CAMELS-DE (doi:10.5281/zenodo.13837553), CC-BY 4.0"
        return df

    def to_data_object(self):
        if self.table in ("timeseries", "simulated"):
            return TabularData(self._timeseries())
        if self.table in ("catchments", "stations"):
            name = "catchments" if self.table == "catchments" else "gauging_stations"
            return GeoData(self._read_geo(name))
        tables = ATTRIBUTE_TABLES if self.table == "attributes" else [self.table]
        return TabularData(self._attributes(tables))


source = CamelsDeSource
