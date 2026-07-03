# (C) Copyright 2026. Apache-2.0.

"""earthkit-data source plugins for German hydrology datasets."""

from .buek import Buek1000Source
from .dwd import DwdObservationsSource
from .era5 import Era5TimeseriesSource
from .hydrosheds import GERMANY, HydroshedsSource
from .pegelonline import PegelonlineSource

__version__ = "0.1.0"

__all__ = [
    "Buek1000Source",
    "DwdObservationsSource",
    "Era5TimeseriesSource",
    "GERMANY",
    "HydroshedsSource",
    "PegelonlineSource",
]
