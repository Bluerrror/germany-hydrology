# (C) Copyright 2026. Apache-2.0.

"""HydroSHEDS catchments and river network (HydroBASINS / HydroRIVERS).

Nested Pfafstetter catchment polygons (levels 1-12) and the river network
for Europe, clipped to your area of interest. Free for non-commercial and
commercial use with attribution (https://www.hydrosheds.org/page/license)::

    # German catchments at Pfafstetter level 6
    basins = ekd.from_source(
        "hydrosheds", product="basins", level=6, bbox=GERMANY,
    ).to_pandas()

    rivers = ekd.from_source("hydrosheds", product="rivers", bbox=GERMANY).to_pandas()
"""

from earthkit.data.sources import Source

from .common import GeoData, cached_download, read_shapefile_zip

#: Germany-wide bounding box (lon/lat), for convenience.
GERMANY = [5.8, 47.2, 15.1, 55.1]

URLS = {
    "basins": "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_{region}_lev{level:02d}_v1c.zip",
    "rivers": "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{region}_shp.zip",
}


class HydroshedsSource(Source):
    """``from_source('hydrosheds', ...)``.

    Parameters
    ----------
    product : str
        ``'basins'`` (HydroBASINS polygons) or ``'rivers'`` (HydroRIVERS).
    level : int, optional
        Pfafstetter level 1-12 for basins (default 6; higher = smaller
        catchments). Ignored for rivers.
    bbox : sequence, optional
        ``[west, south, east, north]`` in lon/lat to clip while reading.
        Use :data:`GERMANY` for Germany. Default: the whole region file.
    region : str, optional
        HydroSHEDS region code (default ``'eu'`` = Europe & Middle East).
    """

    def __init__(self, product="basins", level=6, bbox=None, region="eu", **kwargs):
        super().__init__(**kwargs)
        if product not in URLS:
            raise ValueError(f"product must be one of {sorted(URLS)}")
        if product == "basins" and not 1 <= int(level) <= 12:
            raise ValueError("level must be between 1 and 12.")
        self.product = product
        self.level = int(level)
        self.bbox = list(bbox) if bbox is not None else None
        self.region = region

    def _build_url(self):
        return URLS[self.product].format(region=self.region, level=self.level)

    def to_data_object(self):
        path = cached_download(self._build_url())
        gdf = read_shapefile_zip(path, bbox=self.bbox)
        gdf.attrs["source"] = "HydroSHEDS (www.hydrosheds.org)"
        return GeoData(gdf)


source = HydroshedsSource
