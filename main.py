"""Google Maps Campground Finder.

This module searches for campgrounds along a GPX route using the Google Places API.
It samples points along the route, searches for nearby campgrounds, and exports
the results to a GPX file with distance information.
"""

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import gpxpy
import gpxpy.gpx
import requests
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point

API_URL: str = "https://places.googleapis.com/v1/places:searchNearby"

MONTHLY_REQUEST_LIMIT: int = 4500
USAGE_FILE: Path = Path.home() / ".google_camping_api_usage.json"

DEFAULT_INTERVAL_KM: float = 5.0
DEFAULT_RADIUS_KM: float = 5.0
MAX_RESULTS: int = 20


type Coordinate = tuple[float, float]  # Latitude, longitude pair


class Campground(TypedDict):
    """Data structure for campground information."""
    name: str
    latitude: float
    longitude: float
    distance_to_route_km: float
    google_place_id: str


class UsageData(TypedDict):
    """Data structure for tracking API usage by month."""
    month: str
    requests: int


def read_gpx(file_path: str | Path) -> list[Coordinate]:
    """Read all track or route coordinates from a GPX file.

    Args:
        file_path: Path to the GPX file to read

    Returns:
        List of (latitude, longitude) coordinate tuples

    Raises:
        ValueError: If the GPX file contains fewer than two points
    """
    path: Path = Path(file_path)

    with path.open(encoding="utf-8") as file:
        gpx: gpxpy.gpx.GPX = gpxpy.parse(file)

    coordinates: list[Coordinate] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                coordinates.append(
                    (point.latitude, point.longitude)
                )

    if not coordinates:
        for route in gpx.routes:
            for point in route.points:
                coordinates.append(
                    (point.latitude, point.longitude)
                )

    if len(coordinates) < 2:
        raise ValueError(
            "The GPX file must contain at least two track or route points."
        )

    return coordinates


def haversine(
    point_a: Coordinate,
    point_b: Coordinate,
) -> float:
    """Calculate approximate distance between coordinates in meters.

    Args:
        point_a: First coordinate as (latitude, longitude)
        point_b: Second coordinate as (latitude, longitude)

    Returns:
        Distance between the two points in meters
    """
    lat1, lon1 = map(math.radians, point_a)
    lat2, lon2 = map(math.radians, point_b)

    delta_lat: float = lat2 - lat1
    delta_lon: float = lon2 - lon1

    value: float = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return 6371000.0 * 2 * math.asin(
        min(1.0, math.sqrt(value))
    )


def sample_route(
    coordinates: list[Coordinate],
    interval_m: float,
) -> list[Coordinate]:
    """Sample coordinates at approximately fixed distances along a route.

    Args:
        coordinates: List of route coordinates as (latitude, longitude)
        interval_m: Desired interval between samples in meters

    Returns:
        List of sampled coordinates at approximately fixed intervals
    """
    samples: list[Coordinate] = [coordinates[0]]

    distance_since_sample: float = 0.0
    previous: Coordinate = coordinates[0]

    for current in coordinates[1:]:
        segment_length: float = haversine(previous, current)

        while distance_since_sample + segment_length >= interval_m:
            if segment_length <= 0:
                break

            fraction: float = (
                (interval_m - distance_since_sample)
                / segment_length
            )

            new_point: Coordinate = (
                previous[0]
                + fraction * (current[0] - previous[0]),
                previous[1]
                + fraction * (current[1] - previous[1]),
            )

            samples.append(new_point)
            previous = new_point
            segment_length = haversine(previous, current)
            distance_since_sample = 0.0

        distance_since_sample += segment_length
        previous = current

    if haversine(samples[-1], coordinates[-1]) > 1.0:
        samples.append(coordinates[-1])

    return samples


def load_usage() -> UsageData:
    """Read the request count for the current UTC calendar month.

    Returns:
        UsageData dictionary with month and request count
    """
    current_month: str = datetime.now(
        timezone.utc
    ).strftime("%Y-%m")

    if USAGE_FILE.exists():
        data: UsageData = json.loads(
            USAGE_FILE.read_text(encoding="utf-8")
        )

        if data.get("month") == current_month:
            return data

    return {
        "month": current_month,
        "requests": 0,
    }


def reserve_request() -> int:
    """Reserve one request before calling Google Places.

    Returns:
        The new request count after incrementing

    Raises:
        RuntimeError: If monthly request limit is exceeded
    """
    usage: UsageData = load_usage()

    if usage["requests"] >= MONTHLY_REQUEST_LIMIT:
        raise RuntimeError(
            "Monthly request safety limit reached: "
            f"{MONTHLY_REQUEST_LIMIT}"
        )

    usage["requests"] += 1

    USAGE_FILE.write_text(
        json.dumps(usage, indent=2),
        encoding="utf-8",
    )

    return usage["requests"]


def search_campgrounds(
    session: requests.Session,
    latitude: float,
    longitude: float,
    radius_m: float,
    api_key: str,
) -> list[dict[str, Any]]:
    """Search for campgrounds using Google Places Nearby Search (New).

    Args:
        session: Requests session for HTTP calls
        latitude: Center latitude for search
        longitude: Center longitude for search
        radius_m: Search radius in meters
        api_key: Google Maps API key

    Returns:
        List of place dictionaries from Google Places API

    Raises:
        requests.HTTPError: If the API request fails
    """
    payload: dict[str, Any] = {
        "includedTypes": ["campground"],
        "maxResultCount": MAX_RESULTS,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_m,
            }
        },
    }

    headers: dict[str, str] = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.location"
        ),
        "Content-Type": "application/json",
    }

    reserve_request()

    response: requests.Response = session.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    data: dict[str, Any] = response.json()

    return data.get("places", [])


def create_transformer(
    coordinates: list[Coordinate],
) -> Transformer:
    """Create a local metric projection for distance calculations.

    Args:
        coordinates: List of coordinates to center the projection on

    Returns:
        PyProj Transformer object for coordinate conversion
    """
    average_latitude: float = sum(
        point[0] for point in coordinates
    ) / len(coordinates)

    average_longitude: float = sum(
        point[1] for point in coordinates
    ) / len(coordinates)

    local_crs: CRS = CRS.from_proj4(
        f"+proj=aeqd "
        f"+lat_0={average_latitude} "
        f"+lon_0={average_longitude} "
        "+datum=WGS84 +units=m +no_defs"
    )

    return Transformer.from_crs(
        "EPSG:4326",
        local_crs,
        always_xy=True,
    )


def export_campgrounds_to_gpx(
    campgrounds: dict[str, Campground],
    output_file: str | Path,
) -> None:
    """Export campgrounds as GPX waypoints.

    Args:
        campgrounds: Dictionary of campgrounds keyed by place ID
        output_file: Path for the output GPX file
    """
    gpx: gpxpy.gpx.GPX = gpxpy.gpx.GPX()

    for campground in campgrounds.values():
        place_id: str = campground["google_place_id"]

        google_maps_url: str = (
            "https://www.google.com/maps/search/"
            f"?api=1&query=Google&query_place_id={place_id}"
        )

        description: str = (
            f"Distance from route: "
            f"{campground['distance_to_route_km']:.2f} km\n"
            f"Google Maps: {google_maps_url}\n"
            f"Google Place ID: {place_id}"
        )

        waypoint: gpxpy.gpx.GPXWaypoint = (
            gpxpy.gpx.GPXWaypoint(
                latitude=campground["latitude"],
                longitude=campground["longitude"],
                name=campground["name"],
                description=description,
                type="campground",
            )
        )

        gpx.waypoints.append(waypoint)

    output_path: Path = Path(output_file)

    output_path.write_text(
        gpx.to_xml(),
        encoding="utf-8",
    )

    print(
        f"Exported {len(gpx.waypoints)} campgrounds "
        f"to {output_path}"
    )


def find_campgrounds(
    coordinates: list[Coordinate],
    interval_km: float,
    radius_km: float,
    api_key: str,
) -> dict[str, Campground]:
    """Find and deduplicate campgrounds along the GPX route.

    Args:
        coordinates: List of route coordinates as (latitude, longitude)
        interval_km: Distance between search points in kilometers
        radius_km: Maximum distance from route to search in kilometers
        api_key: Google Maps API key

    Returns:
        Dictionary of unique campgrounds keyed by Google Place ID
    """
    samples: list[Coordinate] = sample_route(
        coordinates,
        interval_km * 1000.0,
    )

    transformer: Transformer = create_transformer(
        coordinates
    )

    route: LineString = LineString([
        transformer.transform(lon, lat)
        for lat, lon in coordinates
    ])

    campgrounds: dict[str, Campground] = {}

    print(f"GPX points: {len(coordinates)}")
    print(f"Google searches planned: {len(samples)}")
    print(
        "Monthly requests already counted: "
        f"{load_usage()['requests']}"
    )

    with requests.Session() as session:
        for index, (latitude, longitude) in enumerate(
            samples,
            start=1,
        ):
            print(
                f"Search {index}/{len(samples)}",
                end=" ",
                flush=True,
            )

            places: list[dict[str, Any]] = (
                search_campgrounds(
                    session=session,
                    latitude=latitude,
                    longitude=longitude,
                    radius_m=radius_km * 1000.0,
                    api_key=api_key,
                )
            )

            print(f"- {len(places)} results")

            for place in places:
                place_id: str = place.get("id", "")
                location: dict[str, Any] = place.get(
                    "location", {}
                )

                if not place_id:
                    continue

                if (
                    "latitude" not in location
                    or "longitude" not in location
                ):
                    continue

                camp_lat: float = float(
                    location["latitude"]
                )
                camp_lon: float = float(
                    location["longitude"]
                )

                projected_x, projected_y = (
                    transformer.transform(
                        camp_lon,
                        camp_lat,
                    )
                )

                distance_m: float = route.distance(
                    Point(projected_x, projected_y)
                )

                if distance_m > radius_km * 1000.0:
                    continue

                campground: Campground = {
                    "name": place.get(
                        "displayName", {}
                    ).get("text", "Unnamed campground"),
                    "latitude": camp_lat,
                    "longitude": camp_lon,
                    "distance_to_route_km": round(
                        distance_m / 1000.0,
                        2,
                    ),
                    "google_place_id": place_id,
                }

                if place_id not in campgrounds:
                    campgrounds[place_id] = campground

            time.sleep(0.2)

    return campgrounds


def main() -> None:
    """Main entry point for the campground finder.

    Reads the GPX file, searches for campgrounds along the route,
    and exports results to a GPX file with hardcoded parameters.
    """
    gpx_file: Path = Path("/Users/petit7268/py/googlemap_camping/files/Portugal Espagne euro velo.gpx")
    output_file: Path = Path("campgrounds_from_google.gpx")
    interval_km: float = DEFAULT_INTERVAL_KM
    radius_km: float = DEFAULT_RADIUS_KM

    api_key: str | None = os.environ.get(
        "GOOGLE_MAPS_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "Environment variable "
            "GOOGLE_MAPS_API_KEY is not defined."
        )

    coordinates: list[Coordinate] = read_gpx(
        gpx_file
    )

    campgrounds: dict[str, Campground] = (
        find_campgrounds(
            coordinates=coordinates,
            interval_km=interval_km,
            radius_km=radius_km,
            api_key=api_key,
        )
    )

    export_campgrounds_to_gpx(
        campgrounds,
        output_file,
    )

    print(
        "Monthly API requests counted: "
        f"{load_usage()['requests']}"
    )


if __name__ == "__main__":
    main()
