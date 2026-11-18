"""
Finite-Fault Rupture Distance (Rrup) Calculator.

Computes the closest three-dimensional distance from an observation site to the
earthquake rupture surface (Rrup) using USGS ShakeMap finite-fault rupture geometry (rupture.json).

Seismological & Methodological Foundations:
1. Definition: Rrup is defined as the minimum 3D Euclidean distance from the observation site
   (typically at Earth's surface, depth = 0.0 km) to any point on the fault rupture surface
   (NGA-West2 GMPE standard; Abrahamson et al., 2014; Boore et al., 2014).
2. Geometry: ShakeMap rupture.json describes finite faults as polygon rings (top edge trace
   followed by down-dip bottom edge trace). Consecutive points form quadrilaterals, which are
   triangulated into planar triangular facets approximating the 3D rupture surface.
3. Coordinate Projection: Geodetic coordinates (lon, lat in degrees, depth in km positive down)
   are projected into a local East-North-Up (ENU) tangent-plane Cartesian frame centered at the
   rupture centroid to preserve Euclidean distance accuracy over regional scales.
4. Distance Algorithm: Exact 3D point-to-triangle distance (Ericson, 2005, 'Real-Time Collision Detection').
5. Scientific Guardrails:
   - NEVER substitute epicentral distance (Repi) for Rrup while calling it Rrup.
   - If finite-fault geometry is unavailable, preserve rrup_km: null and provide separately labeled repi_km.
   - NEVER substitute the event epicenter for a missing observation site.
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional, Tuple, Union

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

EARTH_RADIUS_KM = 6371.0088  # Mean Earth radius (IUGG standard)


def geodetic_to_enu_point(
    lon: float, lat: float, depth_km: float, lon0: float, lat0: float
) -> Tuple[float, float, float]:
    """
    Project geodetic coordinates (lon, lat in degrees, depth in km positive down)
    into a local Cartesian East-North-Up (ENU) frame (in km) centered at (lon0, lat0).
    Up is negative depth (Earth interior is -Z).
    """
    lat0_rad = math.radians(lat0)
    dlon_rad = math.radians(lon - lon0)
    dlat_rad = math.radians(lat - lat0)

    east = EARTH_RADIUS_KM * math.cos(lat0_rad) * dlon_rad
    north = EARTH_RADIUS_KM * dlat_rad
    up = -depth_km
    return (east, north, up)


def point_triangle_distance_3d(
    p: Tuple[float, float, float],
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
    c: Tuple[float, float, float],
) -> float:
    """
    Compute the minimum Euclidean distance from a 3D point p to a 3D triangle defined by vertices (a, b, c).
    Uses Ericson (2005) 'Real-Time Collision Detection' Section 5.1.5 (Voronoi region partition).
    """
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])

    d1 = ab[0] * ap[0] + ab[1] * ap[1] + ab[2] * ap[2]
    d2 = ac[0] * ap[0] + ac[1] * ap[1] + ac[2] * ap[2]
    if d1 <= 0.0 and d2 <= 0.0:
        return math.sqrt((p[0] - a[0])**2 + (p[1] - a[1])**2 + (p[2] - a[2])**2)

    bp = (p[0] - b[0], p[1] - b[1], p[2] - b[2])
    d3 = ab[0] * bp[0] + ab[1] * bp[1] + ab[2] * bp[2]
    d4 = ac[0] * bp[0] + ac[1] * bp[1] + ac[2] * bp[2]
    if d3 >= 0.0 and d4 <= d3:
        return math.sqrt((p[0] - b[0])**2 + (p[1] - b[1])**2 + (p[2] - b[2])**2)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        closest = (a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2])
        return math.sqrt((p[0] - closest[0])**2 + (p[1] - closest[1])**2 + (p[2] - closest[2])**2)

    cp = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
    d5 = ab[0] * cp[0] + ab[1] * cp[1] + ab[2] * cp[2]
    d6 = ac[0] * cp[0] + ac[1] * cp[1] + ac[2] * cp[2]
    if d6 >= 0.0 and d5 <= d6:
        return math.sqrt((p[0] - c[0])**2 + (p[1] - c[1])**2 + (p[2] - c[2])**2)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        closest = (a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2])
        return math.sqrt((p[0] - closest[0])**2 + (p[1] - closest[1])**2 + (p[2] - closest[2])**2)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        closest = (b[0] + w * (c[0] - b[0]), b[1] + w * (c[1] - b[1]), b[2] + w * (c[2] - b[2]))
        return math.sqrt((p[0] - closest[0])**2 + (p[1] - closest[1])**2 + (p[2] - closest[2])**2)

    # Closest point lies in triangle interior face
    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    closest = (
        a[0] + ab[0] * v + ac[0] * w,
        a[1] + ab[1] * v + ac[1] * w,
        a[2] + ab[2] * v + ac[2] * w,
    )
    return math.sqrt((p[0] - closest[0])**2 + (p[1] - closest[1])**2 + (p[2] - closest[2])**2)


def extract_rupture_mesh_triangles(
    rupture_geojson: Dict[str, Any]
) -> Tuple[List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]], float, float]:
    """
    Parse a ShakeMap rupture.json GeoJSON FeatureCollection and convert all fault ribbons
    into a local Cartesian ENU triangulated mesh.

    Returns:
        (triangles_enu, lon0, lat0)
    """
    rings: List[List[List[float]]] = []

    features = rupture_geojson.get("features", [])
    for feat in features:
        geom = feat.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "MultiPolygon":
            # coordinates: [ [ [ring1], [ring2] ], ... ]
            for poly in coords:
                for ring in poly:
                    rings.append(ring)
        elif gtype == "Polygon":
            # coordinates: [ [ring1], ... ]
            for ring in coords:
                rings.append(ring)
        elif gtype == "LineString":
            # Some simplified rupture models provide a 1D fault line string [lon, lat, depth]
            # Convert line string to zero-width ribbon for distance calculations
            rings.append(coords)

    if not rings:
        return ([], 0.0, 0.0)

    # Establish origin at metadata hypocenter or centroid of first ring
    meta = rupture_geojson.get("metadata", {})
    if "lon" in meta and "lat" in meta:
        lon0 = float(meta["lon"])
        lat0 = float(meta["lat"])
    else:
        all_lons = [pt[0] for r in rings for pt in r]
        all_lats = [pt[1] for r in rings for pt in r]
        lon0 = sum(all_lons) / len(all_lons)
        lat0 = sum(all_lats) / len(all_lats)

    triangles_enu: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = []

    for ring in rings:
        pts = list(ring)
        if len(pts) < 3:
            continue

        # Drop duplicate closing point if identical to first
        if len(pts) > 3 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
            pts = pts[:-1]

        n_total = len(pts)
        if n_total >= 4 and n_total % 2 == 0:
            # Standard USGS ShakeMap fault ribbon: top edge forward, bottom edge backward
            n = n_total // 2
            top_edge = pts[:n]
            bottom_edge = list(reversed(pts[n:]))

            for i in range(n - 1):
                p0_geo = top_edge[i]
                p1_geo = top_edge[i + 1]
                p2_geo = bottom_edge[i + 1]
                p3_geo = bottom_edge[i]

                p0 = geodetic_to_enu_point(p0_geo[0], p0_geo[1], p0_geo[2] if len(p0_geo) > 2 else 0.0, lon0, lat0)
                p1 = geodetic_to_enu_point(p1_geo[0], p1_geo[1], p1_geo[2] if len(p1_geo) > 2 else 0.0, lon0, lat0)
                p2 = geodetic_to_enu_point(p2_geo[0], p2_geo[1], p2_geo[2] if len(p2_geo) > 2 else 0.0, lon0, lat0)
                p3 = geodetic_to_enu_point(p3_geo[0], p3_geo[1], p3_geo[2] if len(p3_geo) > 2 else 0.0, lon0, lat0)

                triangles_enu.append((p0, p1, p2))
                triangles_enu.append((p0, p2, p3))
        else:
            # Generic polygon ring triangulation (fan from point 0)
            pts_enu = [
                geodetic_to_enu_point(pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0, lon0, lat0)
                for pt in pts
            ]
            for i in range(1, len(pts_enu) - 1):
                triangles_enu.append((pts_enu[0], pts_enu[i], pts_enu[i + 1]))

    return (triangles_enu, lon0, lat0)


class RrupCalculator:
    """
    Calculates Rrup, Repi, and Rhypo for observation sites.
    """

    def __init__(
        self,
        rupture_geojson: Optional[Dict[str, Any]] = None,
        epicenter: Optional[Tuple[float, float, Optional[float]]] = None,
        origin_lat: Optional[float] = None,
        origin_lon: Optional[float] = None,
        origin_depth_km: Optional[float] = 10.0,
    ):
        self.rupture_geojson = rupture_geojson
        self.triangles_enu: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = []
        self.lon0 = 0.0
        self.lat0 = 0.0
        self.has_rupture_mesh = False

        if rupture_geojson:
            self._build_mesh(rupture_geojson)

        self.epicenter_lat: Optional[float] = None
        self.epicenter_lon: Optional[float] = None
        self.hypocenter_depth_km: Optional[float] = None

        if origin_lat is not None and origin_lon is not None:
            self.epicenter_lat = float(origin_lat)
            self.epicenter_lon = float(origin_lon)
            self.hypocenter_depth_km = float(origin_depth_km) if origin_depth_km is not None else 10.0
        elif epicenter:
            self.epicenter_lat = float(epicenter[0])
            self.epicenter_lon = float(epicenter[1])
            self.hypocenter_depth_km = float(epicenter[2]) if len(epicenter) > 2 and epicenter[2] is not None else 10.0
        elif rupture_geojson and "metadata" in rupture_geojson:
            meta = rupture_geojson["metadata"]
            if "lat" in meta and "lon" in meta:
                self.epicenter_lat = float(meta["lat"])
                self.epicenter_lon = float(meta["lon"])
                self.hypocenter_depth_km = float(meta.get("depth", 10.0))

    @property
    def has_rupture(self) -> bool:
        """Alias for has_rupture_mesh."""
        return self.has_rupture_mesh

    @property
    def mesh_triangles(self) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]]:
        """Return triangulated mesh facets in local ENU frame."""
        return self.triangles_enu

    def _build_mesh(self, rupture_geojson: Dict[str, Any]) -> None:
        triangles, lon0, lat0 = extract_rupture_mesh_triangles(rupture_geojson)
        self.triangles_enu = triangles
        self.lon0 = lon0
        self.lat0 = lat0
        self.has_rupture_mesh = len(triangles) > 0

    def calculate_rrup(
        self,
        lat: Optional[float],
        lon: Optional[float],
        depth_km: float = 0.0,
        site_depth_km: Optional[float] = None,
    ) -> Optional[float]:
        """
        Calculate minimum 3D distance Rrup (km) from observation site (lat, lon, depth_km)
        to the finite-fault rupture surface.

        Returns None if coordinates are missing or rupture geometry is unavailable.
        NEVER substitutes epicentral distance for Rrup.
        """
        if lat is None or lon is None:
            return None

        if not self.has_rupture_mesh or not self.triangles_enu:
            return None

        effective_depth = site_depth_km if site_depth_km is not None else depth_km
        site_enu = geodetic_to_enu_point(lon, lat, effective_depth, self.lon0, self.lat0)

        min_dist = float("inf")
        for a, b, c in self.triangles_enu:
            d = point_triangle_distance_3d(site_enu, a, b, c)
            if d < min_dist:
                min_dist = d

        return round(min_dist, 3)

    def calculate_repi(
        self,
        lat: Optional[float],
        lon: Optional[float],
    ) -> Optional[float]:
        """
        Calculate horizontal epicentral distance Repi (km) using Haversine formula.
        Returns None if site coordinates or epicenter coordinates are unavailable.
        """
        if lat is None or lon is None or self.epicenter_lat is None or self.epicenter_lon is None:
            return None

        lat1_rad = math.radians(lat)
        lon1_rad = math.radians(lon)
        lat2_rad = math.radians(self.epicenter_lat)
        lon2_rad = math.radians(self.epicenter_lon)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2.0)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0)**2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(EARTH_RADIUS_KM * c, 3)

    def calculate_rhypo(
        self,
        lat: Optional[float],
        lon: Optional[float],
        depth_km: float = 0.0,
    ) -> Optional[float]:
        """
        Calculate slant hypocentral distance Rhypo (km).
        Rhypo = sqrt(Repi^2 + (depth_site - depth_hypo)^2).
        """
        repi = self.calculate_repi(lat, lon)
        if repi is None or self.hypocenter_depth_km is None:
            return None

        dz = depth_km - self.hypocenter_depth_km
        return round(math.sqrt(repi**2 + dz**2), 3)

    def calculate_distances(
        self,
        lat: Optional[float],
        lon: Optional[float],
        depth_km: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Compute complete suite of seismological distances with full provenance.
        """
        rrup = self.calculate_rrup(lat, lon, depth_km)
        repi = self.calculate_repi(lat, lon)
        rhypo = self.calculate_rhypo(lat, lon, depth_km)

        if rrup is not None:
            source = "finite_fault_mesh"
            primary_dist = rrup
            primary_type = "rrup_km"
        elif repi is not None:
            source = "hypocenter_alternative"
            primary_dist = repi
            primary_type = "repi_km"
        else:
            source = "unavailable"
            primary_dist = None
            primary_type = "none"

        return {
            "rrup_km": rrup,
            "repi_km": repi,
            "rhypo_km": rhypo,
            "primary_distance_km": primary_dist,
            "primary_distance_type": primary_type,
            "distance_source": source,
            "has_finite_fault": self.has_rupture_mesh,
            "triangle_count": len(self.triangles_enu),
        }
