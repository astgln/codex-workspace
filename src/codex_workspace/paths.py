"""Explicit installation paths, independent of package location and process cwd."""
import os
from pathlib import Path


def state_directory():
    value = os.environ.get('CODEX_WORKSPACE_STATE')
    return Path(value).expanduser().resolve() if value else Path.home()/'.local/state/codex-workspace'


def source_directory():
    value = os.environ.get('CODEX_WORKSPACE_SOURCE')
    if not value:
        raise RuntimeError('Set CODEX_WORKSPACE_SOURCE to the release checkout')
    path = Path(value).expanduser().resolve()
    if not (path/'pyproject.toml').is_file():
        raise RuntimeError('Invalid release checkout')
    return path
