# AI Agent Guidelines for OSM Project

## Project Overview
This project is an OSM (OpenStreetMap) data extraction tool focused on camping and points of interest. It includes functionality for:
- Scraping camping data from Caravanya API
- Converting data to GPX format
- Categorizing and organizing by country
- PyQt6 UI for data visualization

## Python Version
- Target Python 3.14+ (project uses Python 3.14)
- Use modern Python features available in 3.14+

## Code Style Guidelines

### Type Annotations
- Use modern Python type annotations with built-in types
- Use `list` instead of `List` from typing module
- Use `dict` instead of `Dict` from typing module
- Use `tuple` instead of `Tuple` from typing module
- Use `X | None` instead of `Optional[X]` for nullable types
- Use function parameter and return type annotations
- Add `from __future__ import annotations` at the top of files when using modern type annotations
- Use `typing.Protocol` for structural subtyping when needed

```python
# Good
def process_data(items: list[dict]) -> dict[str, str]:
    return {"result": "processed"}

# Bad
from typing import List, Dict
def process_data(items: List[Dict]) -> Dict[str, str]:
    return {"result": "processed"}
```

### Import Organization
Organize imports in this order:
1. Standard library imports
2. Third-party imports
3. Local imports (from this project)

Separate each group with a blank line.
Sort imports alphabetically within each import group to satisfy Ruff I001 lint rule.
Use absolute imports for project modules: `from src.classes.point import Point`

```python
# Good
import json
import os
import re
from collections import defaultdict

from curl_cffi import requests
from gpxpy.gpx import GPX, GPXWaypoint

from src.function.reverse_geo import get_country_from_gpx_point
```

### Code Formatting
- Follow PEP 8 standards
- Maximum line length: 88 characters (black default)
- Use `black` formatter if configured in pyproject.toml

### Docstrings
- Use triple double quotes `"""` for docstrings
- Use docstrings for all functions
- Include Args and Returns sections for functions with parameters
- Include Raises sections when applicable
- Keep descriptions concise but informative

```python
def split_gpx_by_category(gpx: GPX) -> dict[str, GPX]:
    """
    Splits GPX waypoints by category extracted from descriptions.
    
    Args:
        gpx: GPX object containing waypoints with category information
    
    Returns:
        Dictionary mapping category names to GPX objects
    """
```

### Dataclasses
- Use `@dataclass` decorator for simple data containers
- Use `@dataclass(frozen=True)` for immutable data
- Prefer dataclasses over regular classes for data storage
- Use dataclasses for configuration instead of global variables

### Error Handling
- Use specific exception types
- Include helpful error messages
- Use context managers (`with` statements) for resource management
- Do not catch blind `Exception` - use specific exceptions like `requests.RequestException`, `ValueError`, etc.

### File Paths
- Use `pathlib.Path` instead of `os.path` for file path operations
- Path is more readable and object-oriented
- Example: `Path("folder") / "file.txt"` instead of `os.path.join("folder", "file.txt")`
- Use `Path.exists()`, `Path.is_file()`, `Path.is_dir()` for path checks
- Use `Path.mkdir(parents=True, exist_ok=True)` for directory creation

### AI-Specific Guidelines
- When modifying existing code, match the existing style
- Prefer minimal, focused edits
- Add comments only when the logic is complex or non-obvious
- Use meaningful variable and function names
- Avoid magic numbers; use named constants instead

## Project Structure

```
src/function/
├── caravan.py          # Caravanya API scraping and GPX conversion
├── reverse_geo.py      # Country detection from coordinates
├── gpx_country_splitter.py  # GPX file splitting by country
├── file_operation.py   # File I/O operations
├── osm.py              # OSM data extraction
├── gpx_tools.py        # GPX manipulation tools
└── format_convertion.py # Format conversion utilities

ui/
├── main_page.py        # Main PyQt6 UI
├── menu_config.py      # Menu configuration
├── tool_page.py        # Tool page implementation
└── widget_definition.py # UI widget definitions

files/
├── caravanya_data/     # Caravanya output files
└── osm_output/         # OSM data output

data/                   # Country boundary data cache
```

## Key Functions and Modules

### Caravan Module (`src/function/caravan.py`)
- `caravan_scan_planet()`: Global scanning of Caravanya API
- `convert_json_to_gpx_with_library()`: JSON to GPX conversion
- `split_gpx_by_category()`: Split GPX by category
- `get_country_for_categorized_gpx()`: Organize categorized GPX by country
- `save_country_category_gpx_files()`: Save organized GPX files by country

### Reverse Geo Module (`src/function/reverse_geo.py`)
- `get_country_from_gpx_point()`: Get country name from coordinates
- Uses offline country boundary data cached in `data/` directory

### OSM Module (`src/function/osm.py`)
- `find_points_in_osm()`: Extract OSM data by bounding box
- `find_points_in_land_tiles()`: Extract OSM data from land tiles cache
- `osm_query()`: Query Overpass API with retry logic

## Development Workflow

### Running the Application
- Main entry point: `main.py`
- Debug configuration: Press F5 to debug `main.py`
- Uses Python 3.14+ with uv package manager

### Adding New Features
1. Add type annotations to all new functions
2. Follow import organization rules
3. Add docstrings for documentation
4. Test with existing data files when possible
5. Use dataclasses for configuration instead of global variables

### Testing
- Test data files are available in `files/` directories
- GPX files can be used for testing coordinate processing
- Country detection requires initial data download (one-time)

### Git Conventions
- Write clear, descriptive commit messages
- Use imperative mood in commit messages (e.g., "Add feature" not "Added feature")
- Keep commits focused on a single change
- Always `git pull` before starting work on different computers

## Common Patterns

### Configuration Management
- Use dataclasses for configuration instead of global variables
- Group related configuration values in dataclass fields
- Create default configuration instances for convenience
- Pass configuration objects to functions rather than relying on global state
- This improves testability and makes dependencies explicit

```python
# Good
@dataclass
class CaravanConfig:
    graphql_url: str = "https://app.caravanya.com/graphql/"
    output_dir: str = "files/caravanya_data"
    headers: dict = field(default_factory=lambda: {...})

DEFAULT_CONFIG = CaravanConfig()

def fetch_grid_area(config: CaravanConfig, ...):
    url = config.graphql_url
    ...

# Bad
GRAPHQL_URL = "https://app.caravanya.com/graphql/"
OUTPUT_DIR = "files/caravanya_data"

def fetch_grid_area(...):
    url = GRAPHQL_URL
    ...
```

### Error Handling
- Use specific exception handling where possible
- Include error logging for debugging
- Return None or empty results for non-critical failures
- Use context managers for resource management

### File Operations
- Use `pathlib.Path` for cross-platform path handling
- Create directories with `Path.mkdir(parents=True, exist_ok=True)`
- Use UTF-8 encoding for file operations

### Progress Tracking
- Print progress updates for long-running operations
- Use percentage-based progress for batch operations
- Include timestamp information in output files

## Dependencies
- PyQt6: UI framework
- gpxpy: GPX file handling
- geopandas: Geographic data processing
- curl_cffi: HTTP requests with browser impersonation
- requests: HTTP client
- Other geographic and data processing libraries

## Notes
- The project uses coordinate-based country detection
- GPX files are the primary data format
- Categorization is based on description text parsing
- UI is built with PyQt6 for desktop application
- Uses uv package manager for dependency management
