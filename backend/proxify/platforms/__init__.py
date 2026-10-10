"""
Platforms Package — dynamically includes gitignored extensions directory if present.
"""
from pathlib import Path

# Add local and docker extensions paths to package __path__
_ext_path = Path(__file__).resolve().parent.parent.parent / "extensions"
if _ext_path.exists() and _ext_path.is_dir() and str(_ext_path) not in __path__:
    __path__.append(str(_ext_path))

_docker_path = Path("/app/extensions")
if _docker_path.exists() and _docker_path.is_dir() and str(_docker_path) not in __path__:
    __path__.append(str(_docker_path))

