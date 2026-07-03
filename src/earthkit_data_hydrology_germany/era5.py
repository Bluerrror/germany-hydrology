# (C) Copyright 2026. Apache-2.0.

"""ERA5 / ERA5-Land point time series via the Open-Meteo historical API.

No API key required. For full gridded ERA5 use earthkit-data's built-in
``cds`` source (needs a Copernicus CDS account); this source covers the
everyday hydrology case: forcing time series at station/catchment locations::

    ds = ekd.from_source(
        "era5-timeseries",
        latitude=51.54, longitude=9.93,          # scalars or equal-length lists
        start="2010-01-01", end="2020-12-31",
        variables=["precipitation_sum", "temperature_2m_mean",
                   "et0_fao_evapotranspiration"],
    )
    df = ds.to_pandas()
"""

from urllib.parse import urlencode

from earthkit.data.sources import Source

from .common import TabularData, cached_download

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"

DEFAULT_DAILY = ["precipitation_sum", "temperature_2m_mean"]
DEFAULT_HOURLY = ["precipitation", "temperature_2m"]
MODELS = ["era5", "era5_land", "best_match", "ecmwf_ifs", "cerra"]


def _as_list(v):
    return list(v) if isinstance(v, (list, tuple)) else [v]


class Era5TimeseriesSource(Source):
    """``from_source('era5-timeseries', ...)``.

    Parameters
    ----------
    latitude, longitude : float or list of float
        One or more points (equal length).
    start, end : str
        ``YYYY-MM-DD``. ERA5 archive reaches back to 1940 with ~5 days delay.
    variables : list of str, optional
        Open-Meteo variable names. Daily defaults:
        ``precipitation_sum, temperature_2m_mean``.
    frequency : str, optional
        ``'daily'`` (default) or ``'hourly'``.
    model : str, optional
        ``'era5'`` (default), ``'era5_land'`` (9 km), ``'best_match'``, ...
    """

    def __init__(
        self,
        latitude=None,
        longitude=None,
        start=None,
        end=None,
        variables=None,
        frequency="daily",
        model="era5",
        **kwargs,
    ):
        super().__init__(**kwargs)
        if latitude is None or longitude is None:
            raise ValueError("latitude and longitude are required.")
        if start is None or end is None:
            raise ValueError("start and end dates (YYYY-MM-DD) are required.")
        if frequency not in ("daily", "hourly"):
            raise ValueError("frequency must be 'daily' or 'hourly'.")
        self.lats = [float(v) for v in _as_list(latitude)]
        self.lons = [float(v) for v in _as_list(longitude)]
        if len(self.lats) != len(self.lons):
            raise ValueError("latitude and longitude must have the same length.")
        self.start, self.end = str(start), str(end)
        self.frequency = frequency
        self.variables = list(variables) if variables else (
            DEFAULT_DAILY if frequency == "daily" else DEFAULT_HOURLY
        )
        self.model = model

    def _build_url(self):
        query = {
            "latitude": ",".join(str(v) for v in self.lats),
            "longitude": ",".join(str(v) for v in self.lons),
            "start_date": self.start,
            "end_date": self.end,
            self.frequency: ",".join(self.variables),
            "models": self.model,
            "timezone": "UTC",
        }
        return f"{ENDPOINT}?{urlencode(query)}"

    def to_data_object(self):
        import json

        import pandas as pd

        with open(cached_download(self._build_url()), encoding="utf-8") as f:
            payload = json.load(f)
        locations = payload if isinstance(payload, list) else [payload]

        frames = []
        units = {}
        for i, loc in enumerate(locations):
            block = loc[self.frequency]
            units.update(loc.get(f"{self.frequency}_units", {}))
            df = pd.DataFrame(block)
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time")
            if len(locations) > 1:
                df["latitude"] = loc["latitude"]
                df["longitude"] = loc["longitude"]
                df["location"] = i
            frames.append(df)
        out = pd.concat(frames)
        out.attrs["units"] = units
        out.attrs["model"] = self.model
        return TabularData(out)


source = Era5TimeseriesSource
