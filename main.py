"""Google Maps Campground Finder.

This module searches for campgrounds along a GPX route using the Google Places API.
It samples points along the route, searches for nearby campgrounds, and exports
the results to a GPX file with distance information.
"""


import math
import os
import time
from pathlib import Path
from typing import Any, TypedDict

import gpxpy
import requests
from dotenv import load_dotenv
from gpxpy.gpx import GPX, GPXWaypoint

API_URL: str = "https://places.googleapis.com/v1/places:searchNearby"

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
        gpx: GPX = gpxpy.parse(file)

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


def get_distance_using_haversine(
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
        segment_length: float = get_distance_using_haversine(previous, current)

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
            segment_length = get_distance_using_haversine(previous, current)
            distance_since_sample = 0.0

        distance_since_sample += segment_length
        previous = current

    if get_distance_using_haversine(samples[-1], coordinates[-1]) > 1.0:
        samples.append(coordinates[-1])

    return samples


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
        "includedTypes": ["campground", "rv_park"],
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



    max_retries: int = 3
    retry_delay: float = 1.0

    for attempt in range(max_retries):
        try:
            response: requests.Response = session.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()

            return response.json()
        except requests.exceptions.SSLError:
            if attempt < max_retries - 1:
                print(f"SSL error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise
        except requests.exceptions.RequestException:
            if attempt < max_retries - 1:
                print(f"Request error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise


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


def convert_responses_to_gpx(responses: dict[str, dict[str, Any]]) -> GPX:
    """Convert Google Places API responses to a GPX object with waypoints.

    Args:
        responses: Dictionary mapping place IDs to place data

    Returns:
        GPX object containing waypoints for each place
    """
    gpx: GPX = GPX()

    for place in responses.values():
        location: dict[str, float] = place.get("location", {})
        lat: float = location.get("latitude", 0.0)
        lon: float = location.get("longitude", 0.0)

        if lat == 0.0 and lon == 0.0:
            continue

        waypoint: GPXWaypoint = GPXWaypoint(
            latitude=lat,
            longitude=lon
        )

        # Set name from displayName
        display_name: dict[str, str] = place.get("displayName", {})
        waypoint.name = display_name.get("text", "Unknown")

        # Build description with available information
        description_parts: list[str] = []

        address: str = place.get("formattedAddress", "")
        if address:
            description_parts.append(f"Address: {address}")

        phone: str = place.get("internationalPhoneNumber", "") or place.get(
            "nationalPhoneNumber", ""
        )
        if phone:
            description_parts.append(f"Phone: {phone}")

        website: str = place.get("websiteUri", "")
        if website:
            description_parts.append(f"Website: {website}")

        rating: float = place.get("rating", 0.0)
        if rating > 0.0:
            description_parts.append(f"Rating: {rating}")

        # Add opening hours if available
        opening_hours: dict[str, Any] = place.get("currentOpeningHours", {})
        if opening_hours:
            weekday_descriptions: list[str] = opening_hours.get(
                "weekdayDescriptions", []
            )
            if weekday_descriptions:
                description_parts.extend(weekday_descriptions)

        if description_parts:
            waypoint.description = "\n".join(description_parts)

        gpx.waypoints.append(waypoint)

    return gpx


def main() -> None:
    """Main entry point for the campground finder.

    Reads the GPX file, samples coordinates at fixed intervals,
    queries the API for each coordinate, and exports results to a GPX file.
    """
    load_dotenv()

    gpx_file: Path = Path("/Users/petit7268/py/googlemap_camping/files/Portugal Espagne euro velo.gpx")
    output_file: Path = Path("./files/campgrounds_from_google.gpx")
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

    samples: list[Coordinate] = sample_route_at_interval(
        coordinates,
        interval_km * 1000.0,
    )

    responses: dict[str, dict[str, Any]] = {}

    for i, sample in enumerate(samples, start=1):
        print(f"Processing {i}/{len(samples)}")
        response = request_campground_data(
            session=requests.Session(),
            latitude=sample["latitude"],
            longitude=sample["longitude"],
            radius_m=radius_km * 1000.0,
            api_key=api_key,
        )

        for place in response.get("places", []):
            place_id: str = place.get("id", "")
            if place_id:
                responses[place_id] = place

    # format the responses to a GPX file
    gpx: GPX = convert_responses_to_gpx(responses)

    # Print the GPX file
    print(gpx.to_xml())

    # save to file
    with output_file.open("w", encoding="utf-8") as f:
        f.write(gpx.to_xml())


if __name__ == "__main__":
    main()
