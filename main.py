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


class Coordinate(TypedDict):
    """Geographic coordinate with latitude and longitude."""

    latitude: float
    longitude: float


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
                    {"latitude": point.latitude, "longitude": point.longitude}
                )

    if not coordinates:
        for route in gpx.routes:
            for point in route.points:
                coordinates.append(
                    {"latitude": point.latitude, "longitude": point.longitude}
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
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )

    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(value)))


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

            fraction: float = (interval_m - distance_since_sample) / segment_length

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

        waypoint: GPXWaypoint = GPXWaypoint(latitude=lat, longitude=lon)

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


def get_api_key(env_var_name: str = "GOOGLE_MAPS_API_KEY") -> str:
    """Load environment variables and return the API key.

    Args:
        env_var_name: Name of the environment variable containing the API key

    Returns:
        The API key value

    Raises:
        RuntimeError: If the environment variable is not defined
    """
    load_dotenv()

    api_key: str | None = os.environ.get(env_var_name)

    if not api_key:
        raise RuntimeError(f"Environment variable {env_var_name} is not defined.")

    return api_key


def get_googlemap_item_near_gpx(
    gpx_samples: list[Coordinate], radius_km: float, api_key: str, included_types: str
) -> dict[str, dict[str, Any]]:
    """Process sample coordinates and collect campground data.

    Args:
        gpx_samples: List of coordinate samples to process
        radius_km: Search radius in kilometers
        api_key: Google Maps API key
    """

    max_results: int = 20

    responses: dict[str, dict[str, Any]] = {}

    for i, sample in enumerate(gpx_samples, start=1):
        print(f"Processing {included_types} {i}/{len(gpx_samples)}")

        payload: dict[str, Any] = {
            "includedTypes": included_types,
            "maxResultCount": max_results,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": sample["latitude"],
                        "longitude": sample["longitude"],
                    },
                    "radius": radius_km * 1000.0,
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
                response: requests.Response = requests.Session().post(
                    API_URL,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

                response.raise_for_status()

                response_data: dict[str, Any] = response.json()
                break
            except requests.exceptions.SSLError:
                if attempt < max_retries - 1:
                    print(
                        f"SSL error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
            except requests.exceptions.RequestException:
                if attempt < max_retries - 1:
                    print(
                        f"Request error, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise

        for place in response_data.get("places", []):
            place_id: str = place.get("id", "")
            if place_id:
                responses[place_id] = place
        
        # wait  0.2 seconds to avoid rate limiting
        time.sleep(0.2)
    return responses


def save_response_to_gpx(
    responses: dict[str, dict[str, Any]],
    output_file: Path,
) -> None:
    """Convert responses to GPX and save to file.

    Args:
        responses: Dictionary of place data
        output_file: Path to save the GPX file
    """
    gpx: GPX = convert_responses_to_gpx(responses)

    print(gpx.to_xml())
    # create output directory if it doesn't exist
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        f.write(gpx.to_xml())


def get_googlemap_items(
    gpx_file: Path = Path(
        "/Users/petit7268/py/googlemap_camping/files/Portugal Espagne euro velo.gpx"
    ),
    output_path: Path = Path("./files/output/"),
    interval_km: float = 3,
    radius_km: float = 10,
) -> None:
    """Get data from Google Maps API.

    Args:
        gpx_file: Path to the input GPX file
        output_file: Path to save the output GPX file
        interval_km: Sampling interval in kilometers
        radius_km: Search radius in kilometers
    """

    api_key: str = get_api_key()

    coordinates: list[Coordinate] = read_gpx(gpx_file)

    samples: list[Coordinate] = sample_route_at_interval(
        coordinates,
        interval_km * 1000.0,
    )

    search_items: list[str] = [
        "campground",
        "rv_park",
        "convenience_store",
        "supermarket",
    ]
    for search_item in search_items:
        responses: dict[str, dict[str, Any]] = get_googlemap_item_near_gpx(
            gpx_samples=samples,
            radius_km=radius_km,
            api_key=api_key,
            included_types=search_item,
        )

        output_file = output_path / f"{search_item}_from_google.gpx"
        save_response_to_gpx(responses, output_file)


def main() -> None:
    """Main entry point for the campground finder.

    Reads the GPX file, samples coordinates at fixed intervals,
    queries the API for each coordinate, and exports results to a GPX file.
    """
    get_googlemap_items()


if __name__ == "__main__":
    main()
