# (C) Copyright 2026. Apache-2.0.

"""DWD Climate Data Center (CDC) station observations.

Germany's national weather service publishes quality-controlled station
observations at https://opendata.dwd.de (license: CC-BY 4.0 / GeoNutzV,
attribution "Quelle: Deutscher Wetterdienst")::

    # which stations exist?
    stations = ekd.from_source("dwd-observations", dataset="kl").to_pandas()

    # data for one station
    df = ekd.from_source(
        "dwd-observations", station=44, resolution="daily", dataset="kl",
        period="historical",
    ).to_pandas()
"""

import re
import zipfile

from earthkit.data.sources import Source

from .common import TabularData, cached_download, fetch_text

BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate"

# (resolution, dataset) -> (zip prefix, station description file)
CATALOG = {
    ("daily", "kl"): ("tageswerte_KL", "KL_Tageswerte_Beschreibung_Stationen.txt"),
    ("daily", "more_precip"): ("tageswerte_RR", "RR_Tageswerte_Beschreibung_Stationen.txt"),
    ("monthly", "kl"): ("monatswerte_KL", "KL_Monatswerte_Beschreibung_Stationen.txt"),
    ("hourly", "precipitation"): ("stundenwerte_RR", "RR_Stundenwerte_Beschreibung_Stationen.txt"),
    ("hourly", "air_temperature"): ("stundenwerte_TU", "TU_Stundenwerte_Beschreibung_Stationen.txt"),
}

STATION_COLUMNS = [
    "station_id", "from_date", "to_date", "elevation",
    "latitude", "longitude", "name", "state", "access",
]


def _station_id(value):
    return f"{int(value):05d}"


class DwdObservationsSource(Source):
    """``from_source('dwd-observations', ...)``.

    Parameters
    ----------
    station : int or str, optional
        DWD station id (e.g. ``44`` or ``'00044'``). Omit to get the
        station catalogue (id, coordinates, elevation, period, name).
    resolution : str, optional
        ``'daily'`` (default), ``'hourly'`` or ``'monthly'``.
    dataset : str, optional
        ``'kl'`` (climate, default), ``'more_precip'``, ``'precipitation'``,
        ``'air_temperature'`` — see :data:`CATALOG` for valid combinations.
    period : str, optional
        ``'recent'`` (default, last ~500 days), ``'historical'``, or
        ``'all'`` (both, concatenated and de-duplicated).
    """

    def __init__(self, station=None, resolution="daily", dataset="kl",
                 period="recent", **kwargs):
        super().__init__(**kwargs)
        if (resolution, dataset) not in CATALOG:
            raise ValueError(
                f"Unsupported (resolution, dataset)=({resolution!r}, {dataset!r}). "
                f"Available: {sorted(CATALOG)}"
            )
        if period not in ("recent", "historical", "all"):
            raise ValueError("period must be 'recent', 'historical' or 'all'.")
        self.station = None if station is None else _station_id(station)
        self.resolution = resolution
        self.dataset = dataset
        self.period = period

    # -- URL construction --------------------------------------------------
    def _dir(self, period):
        return f"{BASE}/{self.resolution}/{self.dataset}/{period}"

    def _recent_url(self):
        prefix, _ = CATALOG[(self.resolution, self.dataset)]
        return f"{self._dir('recent')}/{prefix}_{self.station}_akt.zip"

    def _historical_url(self):
        # historical file names embed the data span -> resolve via the listing
        prefix, _ = CATALOG[(self.resolution, self.dataset)]
        listing = fetch_text(self._dir("historical") + "/")
        m = re.search(rf'({prefix}_{self.station}_\d+_\d+_hist\.zip)', listing)
        if not m:
            raise FileNotFoundError(
                f"No historical file for station {self.station} under "
                f"{self._dir('historical')}/"
            )
        return f"{self._dir('historical')}/{m.group(1)}"

    # -- parsing ------------------------------------------------------------
    def _stations(self):
        import pandas as pd

        _, desc = CATALOG[(self.resolution, self.dataset)]
        path = cached_download(f"{self._dir('recent')}/{desc}")
        with open(path, encoding="latin-1") as f:
            lines = f.read().splitlines()
        # Rows are whitespace-separated: 6 numeric fields, then the station
        # name (may contain spaces), then Bundesland and access flag (never do).
        records = []
        for line in lines[2:]:
            t = line.split()
            if len(t) < 8:
                continue
            trailing = 2 if t[-1].lower() == "frei" else 1
            row = t[:6] + [" ".join(t[6:-trailing])] + t[-trailing:]
            records.append(row + [None] * (9 - len(row)))
        df = pd.DataFrame(records, columns=STATION_COLUMNS)
        df["station_id"] = df["station_id"].map(_station_id)
        for c in ("from_date", "to_date"):
            df[c] = pd.to_datetime(df[c], format="%Y%m%d", errors="coerce")
        for c in ("elevation", "latitude", "longitude"):
            df[c] = pd.to_numeric(df[c])
        return df.set_index("station_id")

    @staticmethod
    def _read_zip(path):
        import pandas as pd

        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.startswith("produkt_"))
            with z.open(member) as f:
                df = pd.read_csv(f, sep=";", na_values=[-999, "-999"],
                                 skipinitialspace=True)
        df.columns = [c.strip() for c in df.columns]
        df = df.drop(columns=[c for c in df.columns if c == "eor"], errors="ignore")
        for c in df.columns:
            if c.startswith("MESS_DATUM"):
                s = df[c].astype(str).str.strip()
                fmt = {8: "%Y%m%d", 10: "%Y%m%d%H", 12: "%Y%m%d%H%M"}.get(len(s.iloc[0]))
                df[c] = pd.to_datetime(s, format=fmt)
        if "MESS_DATUM" in df.columns:
            df = df.set_index("MESS_DATUM")
        return df

    def to_data_object(self):
        import pandas as pd

        if self.station is None:
            return TabularData(self._stations())

        urls = []
        if self.period in ("historical", "all"):
            urls.append(self._historical_url())
        if self.period in ("recent", "all"):
            urls.append(self._recent_url())
        frames = [self._read_zip(cached_download(u)) for u in urls]
        df = pd.concat(frames)
        df = df[~df.index.duplicated(keep="first")].sort_index()
        df.attrs["source"] = "Deutscher Wetterdienst (DWD), CDC open data"
        return TabularData(df)


source = DwdObservationsSource
