# (C) Copyright 2026. Apache-2.0.

"""earthkit-data source plugins and tools for German hydrology."""

from . import hbv, network, signatures
from .buek import Buek1000Source
from .camels import CamelsDeSource
from .dem import CopernicusDemSource
from .dwd import DwdObservationsSource
from .dwd_grids import DwdGridsSource
from .era5 import Era5TimeseriesSource
from .hydrosheds import GERMANY, HydroshedsSource
from .landcover import WorldCoverSource
from .pegelonline import PegelonlineSource

__version__ = "0.2.0"

__all__ = [
    "Buek1000Source",
    "CamelsDeSource",
    "CopernicusDemSource",
    "DwdGridsSource",
    "DwdObservationsSource",
    "Era5TimeseriesSource",
    "GERMANY",
    "HydroshedsSource",
    "PegelonlineSource",
    "WorldCoverSource",
    "hbv",
    "network",
    "signatures",
]
