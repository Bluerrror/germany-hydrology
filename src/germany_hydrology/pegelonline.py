# (C) Copyright 2026. Apache-2.0.

"""PEGELONLINE — live water level/discharge at German federal waterway gauges.

REST API of the Wasserstraßen- und Schifffahrtsverwaltung (WSV). Data are
raw, un-checked live values and reach back at most ~31 days::

    # all ~660 gauges with coordinates and river name
    stations = ekd.from_source("pegelonline").to_pandas()

    # water level of the last 15 days at one gauge
    df = ekd.from_source(
        "pegelonline", station="HANN.MUENDEN", parameter="W", start="P15D",
    ).to_pandas()

Fetched live on every call (no caching) — these are operational data.
"""

from urllib.parse import quote

from earthkit.data.sources import Source

from .common import TabularData, fetch_json

BASE = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"


class PegelonlineSource(Source):
    """``from_source('pegelonline', ...)``.

    Parameters
    ----------
    station : str, optional
        Gauge shortname (e.g. ``'HANN.MUENDEN'``), uuid or number. Omit to
        get the station catalogue.
    parameter : str, optional
        Timeseries shortname: ``'W'`` water level (default), ``'Q'``
        discharge (where available), and others exposed by the station.
    start : str, optional
        ISO-8601 period (``'P15D'``, default) or timestamp. The API serves
        at most ~31 days of history.
    """

    def __init__(self, station=None, parameter="W", start="P15D", **kwargs):
        super().__init__(**kwargs)
        self.station = station
        self.parameter = parameter
        self.start = start

    def _stations(self):
        import pandas as pd

        rows = fetch_json(f"{BASE}/stations.json?includeTimeseries=true")
        df = pd.json_normalize(rows)
        df["timeseries"] = [
            ",".join(t["shortname"] for t in r) if isinstance(r, list) else ""
            for r in df.get("timeseries", [])
        ]
        keep = ["uuid", "number", "shortname", "longname", "km", "agency",
                "longitude", "latitude", "water.shortname", "timeseries"]
        df = df[[c for c in keep if c in df.columns]]
        return df.rename(columns={"water.shortname": "water"}).set_index("shortname")

    def _measurements(self):
        import pandas as pd

        sid = quote(str(self.station), safe="")
        meta = fetch_json(f"{BASE}/stations/{sid}/{self.parameter}.json")
        rows = fetch_json(
            f"{BASE}/stations/{sid}/{self.parameter}/measurements.json"
            f"?start={quote(str(self.start), safe='')}"
        )
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        name = f"{meta.get('shortname', self.parameter)} [{meta.get('unit', '?')}]"
        df = df.set_index("timestamp").rename(columns={"value": name})
        df.attrs["station"] = self.station
        df.attrs["unit"] = meta.get("unit")
        df.attrs["gauge_zero"] = (meta.get("gaugeZero") or {}).get("value")
        df.attrs["source"] = "PEGELONLINE / WSV (raw operational values)"
        return df

    def to_data_object(self):
        return TabularData(self._stations() if self.station is None else self._measurements())


source = PegelonlineSource
