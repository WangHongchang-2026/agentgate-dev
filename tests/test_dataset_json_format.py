import json

import pytest

from agentgate.dataset.formats.json import dump, parse


def envelope() -> dict[str, object]:
    return {
        "format": "agentgate.dataset",
        "format_version": 1,
        "dataset": {"id": "dataset", "name": "中文数据集"},
        "version": {"id": "version", "cases": []},
    }


def test_parse_accepts_text_bytes_and_mapping() -> None:
    document = envelope()
    encoded = json.dumps(document, ensure_ascii=False)

    assert parse(document) == document
    assert parse(encoded) == document
    assert parse(encoded.encode("utf-8")) == document


def test_dump_is_deterministic_compact_utf8() -> None:
    first = dump(envelope())
    second = dump(dict(reversed(tuple(envelope().items()))))

    assert first == second
    assert b" " not in first
    assert "中文数据集".encode() in first
    assert parse(first) == envelope()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"format": "other"}, "unsupported Dataset format"),
        ({"format_version": "1"}, "must be an integer"),
        ({"format_version": 2}, "unsupported Dataset format version"),
        ({"dataset": []}, "'dataset' must be an object"),
        ({"version": []}, "'version' must be an object"),
    ],
)
def test_envelope_rejects_invalid_fields(
    change: dict[str, object], message: str
) -> None:
    document = {**envelope(), **change}

    with pytest.raises(ValueError, match=message):
        parse(document)


def test_envelope_rejects_missing_and_unexpected_fields() -> None:
    missing = envelope()
    del missing["dataset"]
    with pytest.raises(ValueError, match="missing: dataset"):
        parse(missing)

    with pytest.raises(ValueError, match="unexpected fields: extra"):
        parse({**envelope(), "extra": True})


def test_parse_rejects_non_object_and_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="document must be an object"):
        parse("[]")
    with pytest.raises(ValueError, match="duplicate JSON object key: id"):
        parse(
            '{"format":"agentgate.dataset","format_version":1,'
            '"dataset":{"id":"one","id":"two"},"version":{}}'
        )


def test_dump_rejects_non_finite_numbers() -> None:
    document = envelope()
    document["dataset"] = {"score": float("nan")}

    with pytest.raises(ValueError, match="Out of range float values"):
        dump(document)
