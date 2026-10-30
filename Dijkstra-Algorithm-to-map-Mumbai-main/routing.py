"""
Real road-following routing, via OSRM (Open Source Routing Machine).

OSRM's public demo server has real-world OpenStreetMap road data and
returns the actual road-snapped path between coordinates — unlike a
straight line drawn directly between two lat/lon points, this follows
real streets, turns, and curves, the same way Google Maps does.

No API key required. For production use at scale, consider self-hosting
OSRM (it's open source and Docker-friendly) or switching to a commercial
provider (Google Directions API, Mapbox, OpenRouteService) — the public
demo server is rate-limited and meant for light/demo use.
"""

import requests

OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving/"
TIMEOUT_SECONDS = 5


def get_route_geometry(waypoints):
    """
    waypoints: list of (lat, lon) tuples, in the order they should be
               visited (e.g. the Dijkstra path's stops).

    Returns a list of (lat, lon) points tracing the actual road route
    through all waypoints in order, or None if the routing request
    fails for any reason (network issue, no road route found, etc.) —
    callers should fall back to a straight line in that case.
    """
    if len(waypoints) < 2:
        return None

    # OSRM expects "lon,lat;lon,lat;..." — note lon comes first.
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    url = f"{OSRM_BASE_URL}{coord_str}"

    try:
        response = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            return None

        # GeoJSON coordinates come as [lon, lat] pairs — flip them for folium.
        coordinates = data["routes"][0]["geometry"]["coordinates"]
        return [(lat, lon) for lon, lat in coordinates]

    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None
