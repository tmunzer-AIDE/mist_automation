import pytest

from app.modules.digital_twin.services.label_resolver import (
    format_object_label,
    _count_by_type,
)


def test_single_object_formats_as_type_and_name():
    label = format_object_label(
        object_types=["networktemplates"],
        object_names_by_type={"networktemplates": ["default-campus"]},
    )
    assert label == "networktemplates: default-campus"


def test_multiple_same_type_formats_as_count():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "networktemplates"],
        object_names_by_type={"networktemplates": ["a", "b", "c"]},
    )
    assert label == "3 networktemplates"


def test_multiple_mixed_types_formats_as_mixed_summary():
    label = format_object_label(
        object_types=["networktemplates", "networktemplates", "wlans"],
        object_names_by_type={"networktemplates": ["a", "b"], "wlans": ["guest"]},
    )
    assert label == "3 objects: 2 networktemplates, 1 wlans"


def test_empty_object_types_returns_none():
    assert format_object_label(object_types=[], object_names_by_type={}) is None


def test_count_by_type():
    counts = _count_by_type(["a", "a", "b", "c", "a"])
    assert counts == {"a": 3, "b": 1, "c": 1}
