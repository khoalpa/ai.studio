from __future__ import annotations

import tomllib
from pathlib import Path

from audio_story.persistence.migrations import migration_directory


def test_source_checkout_migrations_are_available() -> None:
    directory = migration_directory()
    assert len(list(directory.glob("[0-9][0-9][0-9]_*.sql"))) == 9


def test_wheel_configuration_includes_runtime_migrations() -> None:
    root = Path(__file__).parents[2]
    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["migrations"] == "audio_story/migrations"
