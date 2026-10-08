"""Shared pytest fixtures for the code-compass test suite."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Return a fresh temporary directory that acts as a fake repository root.

    The directory is empty on creation — individual tests populate it with
    whatever files and sub-directories they need.
    """
    return tmp_path


@pytest.fixture()
def simple_py_file(tmp_repo: Path) -> Path:
    """Write a trivial Python source file into *tmp_repo* and return its path."""
    f = tmp_repo / "hello.py"
    f.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    return f
