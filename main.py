"""Google Maps Campground Finder.

This module searches for campgrounds along a GPX route using the Google Places API.
It samples points along the route, searches for nearby campgrounds, and exports
the results to a GPX file with distance information.
"""

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import gpxpy
import gpxpy.gpx
import requests
from dotenv import load_dotenv

API_URL: str = "https://places.googleapis.com/v1/places:searchNearby"

MONTHLY_REQUEST_LIMIT: int = 4500
USAGE_FILE: Path = Path.home() / ".google_camping_api_usage.json"

DEFAULT_INTERVAL_KM: float = 3.0
DEFAULT_RADIUS_KM: float = 5.0
MAX_RESULTS: int = 20


class Coordinate(TypedDict):
    """Geographic coordinate with latitude and longitude."""
    latitude: float
    longitude: float


class UsageData(TypedDict):
    """Data structure for tracking API usage by month."""
    month: str
    requests: int


def read_gpx(file_path: str | Path) -> list[Coordinate]:
    """Read all track or route coordinates from a GPX file.

    Args:
        file_path: Path to the GPX file to read

    Returns:
        List of Coordinate dictionaries with latitude and longitude

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
                    {
                        "latitude": point.latitude,
                        "longitude": point.longitude
                    }
                )

    if not coordinates:
        for route in gpx.routes:
            for point in route.points:
                coordinates.append(
                    {
                        "latitude": point.latitude,
                        "longitude": point.longitude
                    }
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
        point_a: First coordinate as Coordinate dictionary
        point_b: Second coordinate as Coordinate dictionary

    Returns:
        Distance between the two points in meters
    """
    lat1, lon1 = math.radians(point_a["latitude"]), math.radians(point_a["longitude"])
    lat2, lon2 = math.radians(point_b["latitude"]), math.radians(point_b["longitude"])

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


def sample_route_at_interval(
    coordinates: list[Coordinate],
    interval_m: float,
) -> list[Coordinate]:
    """Sample coordinates at approximately fixed distances along a route.

    Args:
        coordinates: List of route coordinates as Coordinate dictionaries
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

            new_point: Coordinate = {
                "latitude": previous["latitude"]
                + fraction * (current["latitude"] - previous["latitude"]),
                "longitude": previous["longitude"]
                + fraction * (current["longitude"] - previous["longitude"]),
            }

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
        UTC
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


def request_campground_data(
    session: requests.Session,
    latitude: float,
    longitude: float,
    radius_m: float,
    api_key: str,
) -> dict[str, Any]:
    """Request campground data from Google Places API and return raw JSON.

    Args:
        session: Requests session for HTTP calls
        latitude: Center latitude for search
        longitude: Center longitude for search
        radius_m: Search radius in meters
        api_key: Google Maps API key

    Returns:
        Full JSON response from Google Places API

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
            "places.id,"
            "places.displayName,"
            "places.location,"
            "places.formattedAddress,"
            "places.nationalPhoneNumber,"
            "places.websiteUri,"
            "places.rating,"
            "places.internationalPhoneNumber,"
            "places.currentOpeningHours"
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

    return response.json()


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
    data: dict[str, Any] = request_campground_data(
        session,
        latitude,
        longitude,
        radius_m,
        api_key,
    )

    return data.get("places", [])


def main() -> None:
    """Main entry point for the campground finder.

    Reads the GPX file, samples coordinates at fixed intervals,
    queries the API for each coordinate, and exports results to a GPX file.
    """
    load_dotenv()

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

    print(f"GPX points: {len(coordinates)}")

    samples: list[Coordinate] = sample_route_at_interval(
        coordinates,
        interval_km * 1000.0,
    )

    print(f"Sampled coordinates: {len(samples)}")

    for sample in samples:
        print(f"Sample: {sample}")
        response = request_campground_data(
            session=requests.Session(),
            latitude=sample["latitude"],
            longitude=sample["longitude"],
            radius_m=radius_km * 1000.0,
            api_key=api_key,
        )
        print(f"Response: {response}")
        break



    print(
        "Monthly API requests counted: "
        f"{load_usage()['requests']}"
    )


if __name__ == "__main__":
    main()
