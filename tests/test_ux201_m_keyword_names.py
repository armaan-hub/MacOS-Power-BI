"""Tests for Task 201: quote M keywords used as names."""

import pytest

from analytics_studio.power_query_m import (
    PowerQueryMScriptError,
    _m_field,
    _m_name_reference,
    _m_reference,
    _parse_name,
    parse_m_script,
    steps_to_m_script,
)


def test_m_reference_quoting_for_keywords() -> None:
    assert _m_reference("each") == '#"each"'
    assert _m_reference("type") == '#"type"'
    assert _m_reference("Let") == "Let"
    assert _m_reference("Source") == "Source"
    assert _m_reference("Changed Type") == '#"Changed Type"'


def test_m_name_reference_quoting_for_keywords() -> None:
    assert _m_name_reference("null") == '#"null"'


def test_parse_name_for_keywords() -> None:
    assert _parse_name('#"let"') == "let"
    with pytest.raises(PowerQueryMScriptError):
        _parse_name("let")


def test_round_trip_with_keyword_step_name() -> None:
    steps = [{"op": "remove_column", "column": "Amount"}]
    script = steps_to_m_script(steps, "Sales Data", step_names=["each"])
    assert '#"each" =' in script or '#"each" = ' in script
    in_line = script.strip().splitlines()[-1].strip()
    assert in_line == '#"each"'
    parsed = parse_m_script(script, "Sales Data")
    assert parsed == steps


def test_bare_keyword_step_name_is_rejected() -> None:
    bare_script = """let
    Source = #"Sales Data",
    each = Table.RemoveColumns(Source, {"Amount"})
in
    each"""
    with pytest.raises(PowerQueryMScriptError):
        parse_m_script(bare_script, "Sales Data")


def test_m_field_allows_bare_keywords() -> None:
    assert _m_field("type") == "[type]"
