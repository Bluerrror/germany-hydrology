# (C) Copyright 2026. Apache-2.0.

"""ESA WorldCover — global 10 m land cover (AWS open data, CC-BY 4.0).

3°x3° COG tiles mosaicked and clipped to your bounding box::

    lc = ekd.from_source("worldcover", bbox=[9.0, 51.0, 10.6, 52.0]).to_xarray()

Class codes are in :data:`CLASSES`.
"""

import math

from earthkit.data.sources import Source

from .common import RasterData, cached_download, merge_and_clip_tiles

BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
VERSIONS = {2020: "v100", 2021: "v200"}

#: WorldCover class codes.
CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}


class WorldCoverSource(Source):
    """``from_source('worldcover', ...)``.

    Parameters
    ----------
    bbox : sequence
        ``[west, south, east, north]`` in lon/lat. Required.
        Tiles are 3°x3° and ~40-90 MB each — keep the box reasonable.
    year : int, optional
        ``2021`` (v200, default) or ``2020`` (v100).
    """

    def __init__(self, bbox=None, year=2021, **kwargs):
        super().__init__(**kwargs)
        if bbox is None or len(bbox) != 4:
            raise ValueError("bbox=[west, south, east, north] is required.")
        if year not in VERSIONS:
            raise ValueError(f"year must be one of {sorted(VERSIONS)}")
        self.bbox = list(bbox)
        self.year = year

    def _tile_urls(self):
        v = VERSIONS[self.year]
        w, s, e, n = self.bbox
        urls = []
        for lat in range(math.floor(s / 3) * 3, math.ceil(n / 3) * 3, 3):
            for lon in range(math.floor(w / 3) * 3, math.ceil(e / 3) * 3, 3):
                ns = "N" if lat >= 0 else "S"
                ew = "E" if lon >= 0 else "W"
                tile = f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"
                urls.append(
                    f"{BASE}/{v}/{self.year}/map/"
                    f"ESA_WorldCover_10m_{self.year}_{v}_{tile}_Map.tif"
                )
        return urls

    def to_data_object(self):
        paths = [cached_download(u) for u in self._tile_urls()]
        da = merge_and_clip_tiles(paths, self.bbox)
        da.name = "landcover"
        da.attrs["classes"] = CLASSES
        da.attrs["source"] = f"ESA WorldCover {self.year} (CC-BY 4.0)"
        return RasterData(da)


source = WorldCoverSource
