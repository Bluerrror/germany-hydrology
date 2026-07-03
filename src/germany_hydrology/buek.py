# (C) Copyright 2026. Apache-2.0.

"""BÜK1000 — the German 1:1,000,000 soil map (BGR).

Soil-unit polygons for all of Germany with pedological legend units,
downloaded once from BGR and cached. © BGR, Hannover; reuse per
GeoNutzV with attribution::

    soils = ekd.from_source("buek1000", bbox=[9.5, 51.3, 10.2, 51.7]).to_pandas()

The shapefile is published in ETRS89 / LCC (EPSG:3034); a lon/lat ``bbox``
is reprojected for filtering, and ``to_crs='EPSG:4326'`` (default) returns
the polygons in lon/lat.
"""

from earthkit.data.sources import Source

from .common import GeoData, cached_download, extract_shapefile_zip

URL = "https://download.bgr.de/bgr/boden/buek1000de/shp/buek1000de_v21.zip"


class Buek1000Source(Source):
    """``from_source('buek1000', ...)``.

    Parameters
    ----------
    bbox : sequence, optional
        ``[west, south, east, north]`` in lon/lat. Default: all of Germany
        (~8 MB download, a few thousand polygons).
    to_crs : str or None, optional
        CRS of the returned GeoDataFrame, default ``'EPSG:4326'``.
        Pass ``None`` to keep the native projection.
    """

    def __init__(self, bbox=None, to_crs="EPSG:4326", **kwargs):
        super().__init__(**kwargs)
        self.bbox = list(bbox) if bbox is not None else None
        self.to_crs = to_crs

    def to_data_object(self):
        import geopandas as gpd
        import pyogrio

        shp = extract_shapefile_zip(cached_download(URL))
        bbox = None
        if self.bbox is not None:
            from pyproj import Transformer

            # express the lon/lat box in the layer's projected CRS
            t = Transformer.from_crs("EPSG:4326", pyogrio.read_info(shp)["crs"],
                                     always_xy=True)
            w, s, e, n = self.bbox
            xs, ys = t.transform([w, w, e, e], [s, n, s, n])
            bbox = (min(xs), min(ys), max(xs), max(ys))
        gdf = gpd.read_file(shp, bbox=bbox)
        if self.to_crs:
            gdf = gdf.to_crs(self.to_crs)
        gdf.attrs["source"] = "BÜK1000 © BGR, Hannover"
        return GeoData(gdf)


source = Buek1000Source
