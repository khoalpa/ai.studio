from __future__ import annotations

import pytest

from audio_story.validation.errors import ValidationError
from audio_story.validation.files import FileSetContract, validate_file_set
from audio_story.validation.schemas import SCHEMAS, validate_schema
from audio_story.validation.strict_json import parse_json_bytes


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_schema_has_valid_and_three_invalid_fixtures(name: str) -> None:
    spec = SCHEMAS[name]
    fields = spec.root_order or ("schema_version",)
    source = (
        "{"
        + ",".join(
            f'"{field}":' + (f'"{spec.version}"' if field == "schema_version" else "null")
            for field in fields
        )
        + "}"
    )
    valid = parse_json_bytes(source.encode(), name).value
    if spec.root_order is None:
        assert validate_schema(valid, name, spec.phases[0], name) == "NOT_VERIFIED"
    else:
        assert validate_schema(valid, name, spec.phases[0], name) == "IMPLEMENTED"
    invalid = [b"{}", b'{"schema_version":"wrong"}', b"[]"]
    for fixture in invalid:
        with pytest.raises(ValidationError):
            validate_schema(parse_json_bytes(fixture, name).value, name, spec.phases[0], name)


def test_file_set_exact_missing_extra_and_normalized_duplicate() -> None:
    contract = FileSetContract(
        required=frozenset({"story.json"}),
        forbidden=frozenset({"debug.tmp"}),
        exact_count=1,
    )
    assert validate_file_set(["story.json"], contract, "package") == ("story.json",)
    for paths, code in [
        ([], "DF003_MISSING_FILE"),
        (["story.json", "debug.tmp"], "DF004_FORBIDDEN_FILE"),
        (["story.json", "other.json"], "DF005_FILE_COUNT"),
        (["a/b", "a\\b"], "DF001_DUPLICATE_NORMALIZED_PATH"),
        (["../escape"], "DF002_INVALID_RELATIVE_PATH"),
    ]:
        with pytest.raises(ValidationError) as caught:
            validate_file_set(paths, contract, "package")
        assert caught.value.finding.code == code
