# (C) Copyright 2026. Apache-2.0.

"""Copernicus GLO-30 / GLO-90 digital elevation model (AWS open data).

Global DEM tiles (1°x1° COGs), mosaicked and clipped to your bounding box.
No key required. © DLR/Airbus/Copernicus (free use with attribution)::

    dem = ekd.from_source(
        "copernicus-dem", bbox=[9.0, 51.0, 10.6, 52.0], resolution=30,
    ).to_xarray()
"""

import math

from earthkit.data.sources import Source

from .common import RasterData, cached_download, merge_and_clip_tiles

BUCKETS = {
    30: ("https://copernicus-dem-30m.s3.amazonaws.com", 10),
    90: ("https://copernicus-dem-90m.s3.amazonaws.com", 30),
}


def _tile_name(lat, lon, arcsec):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (f"Copernicus_DSM_COG_{arcsec}_{ns}{abs(lat):02d}_00_"
            f"{ew}{abs(lon):03d}_00_DEM")


class CopernicusDemSource(Source):
    """``from_source('copernicus-dem', ...)``.

    Parameters
    ----------
    bbox : sequence
        ``[west, south, east, north]`` in lon/lat. Required.
    resolution : int, optional
        ``30`` m (default, ~30 MB per 1° tile) or ``90`` m (~4 MB per tile).
    """

    def __init__(self, bbox=None, resolution=30, **kwargs):
        super().__init__(**kwargs)
        if bbox is None or len(bbox) != 4:
            raise ValueError("bbox=[west, south, east, north] is required.")
        if resolution not in BUCKETS:
            raise ValueError(f"resolution must be one of {sorted(BUCKETS)}")
        self.bbox = list(bbox)
        self.resolution = resolution

    def _tile_urls(self):
        base, arcsec = BUCKETS[self.resolution]
        w, s, e, n = self.bbox
        urls = []
        for lat in range(math.floor(s), math.ceil(n)):
            for lon in range(math.floor(w), math.ceil(e)):
                name = _tile_name(lat, lon, arcsec)
                urls.append(f"{base}/{name}/{name}.tif")
        return urls

    def to_data_object(self):
        paths = [cached_download(u) for u in self._tile_urls()]
        da = merge_and_clip_tiles(paths, self.bbox)
        da.name = "elevation"
        da.attrs["units"] = "m"
        da.attrs["source"] = f"Copernicus GLO-{self.resolution} DEM"
        return RasterData(da)


source = CopernicusDemSource
