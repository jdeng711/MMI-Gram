"""
Base cartography and spatial map generation interface.
Allows interchangeable rendering backends (e.g. GMT, Python GIS / GeoPandas).
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any, Optional


class MapRendererInterface(ABC):
    """Abstract interface for earthquake intensity map rendering."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the underlying mapping engine is installed and operational."""
        pass

    @abstractmethod
    def render_shakemap(
        self,
        observation_points: List[Tuple[float, float, float]],  # (lon, lat, mmi)
        output_file_path: str,
        title: str = "Earthquake Intensity Map",
        bounds: Optional[Tuple[float, float, float, float]] = None,  # min_lon, max_lon, min_lat, max_lat
    ) -> str:
        """
        Interpolate observations and generate a rendered image file.
        Returns the path to the generated map image.
        """
        pass
