# (C) Copyright 2026. Apache-2.0.

"""Navigate HydroSHEDS networks (in the spirit of PyNHD's navigation).

HydroBASINS and HydroRIVERS both encode their topology in a ``NEXT_DOWN``
column (0 = outlet/sink), so the same graph walk serves catchments and
river reaches::

    from germany_hydrology import network

    weser = network.upstream(basins, outlet_id)     # all upstream polygons
    path = network.downstream(rivers, reach_id)     # reach -> sea
"""

__all__ = ["upstream", "downstream", "headwaters"]


def _columns(gdf):
    for id_col in ("HYBAS_ID", "HYRIV_ID"):
        if id_col in gdf.columns:
            return id_col, "NEXT_DOWN"
    raise ValueError(
        "No HYBAS_ID/HYRIV_ID column — is this a HydroBASINS/HydroRIVERS frame?"
    )


def upstream(gdf, outlet, include_outlet=True):
    """All features draining to (and including) ``outlet``.

    Parameters
    ----------
    gdf : GeoDataFrame
        HydroBASINS or HydroRIVERS features (must contain the outlet and
        everything upstream of it — fetch a generous bbox).
    outlet : int
        ``HYBAS_ID`` / ``HYRIV_ID`` of the outlet feature.
    """
    id_col, down_col = _columns(gdf)
    children = {}
    for fid, down in zip(gdf[id_col], gdf[down_col]):
        children.setdefault(down, []).append(fid)
    selected, stack = set(), [int(outlet)]
    while stack:
        fid = stack.pop()
        if fid in selected:
            continue
        selected.add(fid)
        stack.extend(children.get(fid, []))
    if not include_outlet:
        selected.discard(int(outlet))
    return gdf[gdf[id_col].isin(selected)]


def downstream(gdf, start):
    """The chain of features from ``start`` down to the outlet/sink."""
    id_col, down_col = _columns(gdf)
    down_of = dict(zip(gdf[id_col], gdf[down_col]))
    path, fid = [], int(start)
    while fid and fid in down_of and fid not in path:
        path.append(fid)
        fid = down_of[fid]
    out = gdf[gdf[id_col].isin(path)].copy()
    order = {fid: i for i, fid in enumerate(path)}
    return out.sort_values(id_col, key=lambda s: s.map(order))


def headwaters(gdf):
    """Features nothing drains into (first-order catchments / source reaches)."""
    id_col, down_col = _columns(gdf)
    has_inflow = set(gdf[down_col]) - {0}
    return gdf[~gdf[id_col].isin(has_inflow)]
