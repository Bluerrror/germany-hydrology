# (C) Copyright 2026. Apache-2.0.

"""DWD HYRAS — gridded daily climate over Germany (1 km, NetCDF).

Quality-controlled gridded observations (1931/1951 → today), one file per
variable and year, © DWD (CC-BY 4.0)::

    pr = ekd.from_source(
        "dwd-grids", variable="precipitation", years=[2019, 2020],
        bbox=[9.0, 51.0, 10.6, 52.0],
    ).to_xarray()
"""

import re

from earthkit.data.sources import Source

from .common import RasterData, cached_download, fetch_text

BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de"

VARIABLES = [
    "precipitation", "air_temperature_mean", "air_temperature_max",
    "air_temperature_min", "humidity", "radiation_global",
]


class DwdGridsSource(Source):
    """``from_source('dwd-grids', ...)``.

    Parameters
    ----------
    variable : str
        One of :data:`VARIABLES`.
    years : int or list of int
        Year(s) to fetch (~40-130 MB per year, cached).
    bbox : sequence, optional
        ``[west, south, east, north]`` in lon/lat to crop (the HYRAS grid is
        projected; cropping uses its 2-D lat/lon coordinates).
    """

    def __init__(self, variable="precipitation", years=None, bbox=None, **kwargs):
        super().__init__(**kwargs)
        if variable not in VARIABLES:
            raise ValueError(f"variable must be one of {VARIABLES}")
        if years is None:
            raise ValueError("years is required, e.g. years=2020 or [2015, 2016].")
        self.variable = variable
        self.years = [int(y) for y in (years if isinstance(years, (list, tuple)) else [years])]
        self.bbox = list(bbox) if bbox is not None else None

    def _urls(self):
        # file names embed a version suffix (v6-0, v6-1, ...) -> resolve via
        # the directory listing and prefer the newest version per year
        listing = fetch_text(f"{BASE}/{self.variable}/")
        urls = []
        for year in self.years:
            names = re.findall(rf'href="(\w+_hyras_\d+_{year}_v[\d-]+_de\.nc)"', listing)
            if not names:
                raise FileNotFoundError(
                    f"No HYRAS file for {self.variable} {year} under "
                    f"{BASE}/{self.variable}/"
                )
            urls.append(f"{BASE}/{self.variable}/{sorted(set(names))[-1]}")
        return urls

    def to_data_object(self):
        import xarray as xr

        paths = [cached_download(u) for u in self._urls()]
        ds = xr.concat(
            [xr.open_dataset(p, engine="h5netcdf") for p in paths], dim="time"
        )
        if self.bbox is not None:
            w, s, e, n = self.bbox
            mask = ((ds.lon >= w) & (ds.lon <= e)
                    & (ds.lat >= s) & (ds.lat <= n))
            ds = ds.where(mask.compute(), drop=True)
        ds.attrs["source"] = "DWD HYRAS (CC-BY 4.0), Quelle: Deutscher Wetterdienst"
        return RasterData(ds)


source = DwdGridsSource
