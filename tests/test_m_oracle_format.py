"""Pure checks of tools/m_oracle_diff.py: M text, TMSL, PowerShell embedding, output parsing, batching.

No guest, no network: the guest call is replaced by a stub in every test that reaches the batch runner.
"""
from __future__ import annotations

import base64
import json

import pytest

from tools import m_oracle_diff as mo
from tools.dax_oracle_diff import PS_HEAD


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture
def no_guest(monkeypatch):
    def refuse(script):
        raise AssertionError("the guest must not be called in this test")
    monkeypatch.setattr(mo, "guest", refuse)


def test_chunks_keep_order_and_sizes():
    assert mo.chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert mo.chunks([], 3) == []
    with pytest.raises(ValueError):
        mo.chunks([1], 0)


def test_m_partition_indexes_each_expression_and_keeps_it_verbatim():
    exprs = ['1 + 1', 'Text.Upper("a""b")', '#"Column 1"\n// trailing comment']
    m = mo.m_partition(exprs)
    for index, expr in enumerate(exprs):
        assert f"[I = {index}, A = (" in m
        assert f"r = try (\n{expr}\n    )" in m
    assert "T = Table.FromRecords(Rows, type table [I = Int64.Type, A = text])" in m
    assert m.startswith("let\n") and m.endswith("in\n    T")


def test_m_partition_answer_text_covers_error_value_and_unrepresentable_cases():
    m = mo.m_partition(["1"])
    assert '"ERR:" & r[Error][Reason] & ": " & (r[Error][Message] ?? "")' in m
    assert 'try ("V:" & S(r[Value])) otherwise "UNREPRESENTABLE"' in m
    assert "Json.FromValue" not in m and "V?:" not in m


@pytest.mark.parametrize("count", [1, 2, 5])
def test_serializer_is_placed_exactly_once_per_partition(count):
    exprs = [f"{n} + 1" for n in range(count)]
    m = mo.m_partition(exprs)
    assert m.count(mo.M_SERIALIZER) == 1
    assert m.count("S = (v as any) as text =>") == 1
    assert m.count("S(r[Value])") == count
    assert m.index(mo.M_SERIALIZER) < m.index("Rows = {")
    # the whole partition is one let ... in expression
    assert m.startswith("let\n    S = ") and m.endswith("in\n    T")


def test_serializer_covers_every_type_tag_with_the_agreed_formats():
    m = mo.M_SERIALIZER
    for tag in ('"null"', '"true"', '"false"', '"number:NaN"', '"number:+Infinity"', '"number:-Infinity"',
                '"number:" & Number.ToText(v, "R", "en-US")', '"text:" & Q(v)',
                '"date:" & Date.ToText(v, [Format = "yyyy-MM-dd", Culture = "en-US"])',
                '"time:" & Time.ToText(v, [Format = "HH:mm:ss.fffffff"',
                '"datetime:" & DateTime.ToText(v, [Format = "yyyy-MM-dd\'T\'HH:mm:ss.fffffff"',
                '"datetimezone:" & DateTimeZone.ToText(v, [Format = "yyyy-MM-dd\'T\'HH:mm:ss.fffffffzzz"',
                '"duration:" & Duration.ToText(v)', '"list:["', '"record:["', '"table:cols=["',
                'Binary.ToText(v, BinaryEncoding.Base64)', '"function"', '"type"', "Table.Schema(v)"):
        assert tag in m, tag
    assert m.count("@S(") == 3  # list items, record values, table rows: recursion via @S
    # a datetimezone is tested before a datetime, a table before nothing that could swallow it
    assert m.index("v is datetimezone") < m.index("v is datetime ")


def test_serializer_text_escaping_rules_are_in_the_m_text():
    m = mo.M_SERIALIZER
    # M strings have no escapes: a backslash is "\", a quote is """"
    assert 'if c = "\\" then "\\\\"' in m
    assert 'else if c = """" then "\\"""' in m
    assert 'then "\\n"' in m and 'then "\\r"' in m and 'then "\\t"' in m
    assert 'n < 32 or n = 127 then "\\u" & Number.ToText(n, "X4", "en-US")' in m
    assert 'Q = (t as text) as text => """" & Esc(t) & """"' in m


def test_serializer_is_valid_python_constant_without_leading_or_trailing_space():
    assert mo.M_SERIALIZER == mo.M_SERIALIZER.strip()
    assert mo.M_SERIALIZER.startswith("S = ")


def test_expression_escaping_keeps_quotes_backslashes_and_comments_verbatim():
    exprs = ['"a""b#(lf)"', '"back\\slash"', "1 // comment", "#\"Col \"\"x\"\"\""]
    m = mo.m_partition(exprs)
    for expr in exprs:
        assert f"r = try (\n{expr}\n    )" in m
    # the comment cannot swallow the closing parenthesis: it sits on its own line
    assert "1 // comment\n    )" in m


def test_tmsl_round_trips_quotes_and_newlines_exactly():
    exprs = ['"he said ""hi"" \\ done"', 'let x = 1\n in x // c']
    command = json.loads(mo.tmsl(exprs))["createOrReplace"]
    assert command["object"] == {"database": "__DB__", "table": "MOracle__"}
    table = command["table"]
    assert table["name"] == "MOracle__"
    assert table["columns"] == [
        {"name": "I", "dataType": "int64", "sourceColumn": "I"},
        {"name": "A", "dataType": "string", "sourceColumn": "A"},
    ]
    partition = table["partitions"][0]
    assert partition["source"]["type"] == "m"
    assert partition["source"]["expression"] == mo.m_partition(exprs)
    assert exprs[0] in partition["source"]["expression"]


def test_script_embeds_tmsl_and_always_deletes_in_finally(no_guest):
    script = mo._script(["1 + 1"], "51234")
    assert "__PORT__" not in script
    assert script.startswith(PS_HEAD.replace("__PORT__", "51234"))
    assert "$t=@'\n" + mo.tmsl(["1 + 1"]) + "\n'@" in script
    assert "try{" in script and "finally{" in script
    finally_block = script[script.index("finally{"):]
    assert '"delete"' in finally_block and "MOracle__" in finally_block
    assert "EVALUATE MOracle__" in script
    assert "Replace('\"__DB__\"'" in script


def test_delete_is_judged_by_whether_the_table_is_still_there():
    finally_block = mo._BODY[mo._BODY.index("finally{"):mo._BODY.index("if($failed)")]
    # a failing delete is caught and remembered, then the model is asked for the table
    assert "catch{ $dropMsg=" in finally_block
    assert 'EVALUATE FILTER(INFO.TABLES(), [Name]="MOracle__")' in finally_block
    # DROP_ERR only when the table is still present (or cannot be checked); a missing table is DROPPED
    assert "if($left -gt 0){ 'DROP_ERR table still present" in finally_block
    assert "else{ 'DROPPED' }" in finally_block.replace("}else{", "else{")
    assert finally_block.count("'DROP_ERR") == 2


def test_run_batch_warns_only_when_the_guest_reports_a_leftover_table(monkeypatch, capsys):
    clean = "R|0|" + _b64("V:number:1") + "\nDROPPED"
    monkeypatch.setattr(mo, "guest", lambda script: clean)
    assert mo._run_batch(["1"], "51234") == (["V:number:1"], None)
    assert "WARNING" not in capsys.readouterr().out
    failed_create = "FAIL|" + _b64("syntax") + "\nDROPPED"
    monkeypatch.setattr(mo, "guest", lambda script: failed_create)
    assert mo._run_batch(["1 +"], "51234") == (None, "syntax")
    assert "WARNING" not in capsys.readouterr().out
    leftover = "R|0|" + _b64("V:number:1") + "\nDROP_ERR table still present: locked"
    monkeypatch.setattr(mo, "guest", lambda script: leftover)
    assert mo._run_batch(["1"], "51234") == (["V:number:1"], None)
    assert "WARNING: could not delete scratch table MOracle__" in capsys.readouterr().out


def test_parse_output_decodes_multiline_answers_in_index_order():
    output = "\n".join([
        "DROPPED",
        "R|1|" + _b64('V:"line one\nline two"'),
        "R|0|" + _b64("ERR:Expression.Error: boom"),
    ])
    assert mo.parse_output(output, 2) == (['ERR:Expression.Error: boom', 'V:"line one\nline two"'], None)


def test_parse_output_unicode_answers_survive_base64():
    output = "R|0|" + _b64("V:\"café ✓\"") + "\nDROPPED"
    assert mo.parse_output(output, 1) == (['V:"café ✓"'], None)


def test_parse_output_short_or_empty_output_asks_again():
    assert mo.parse_output("", 2) == (None, None)
    assert mo.parse_output("R|0|" + _b64("V:1") + "\nDROPPED", 2) == (None, None)
    assert mo.parse_output("R|0|" + _b64("V:1") + "\nR|0|" + _b64("V:1") + "\n", 2) == (None, None)


def test_parse_output_reports_partition_failure_message():
    output = "FAIL|" + _b64("Syntax error at line 3\nexpected ')'") + "\nDROPPED"
    assert mo.parse_output(output, 3) == (None, "Syntax error at line 3\nexpected ')'")


def test_run_batch_retries_short_output_then_accepts(monkeypatch):
    calls = []
    outputs = ["", "R|0|" + _b64("V:1") + "\nR|1|" + _b64("V:2") + "\nDROPPED"]

    def fake_guest(script):
        calls.append(script)
        return outputs[len(calls) - 1]

    monkeypatch.setattr(mo, "guest", fake_guest)
    assert mo._run_batch(["1", "2"], "51234") == (["V:1", "V:2"], None)
    assert len(calls) == 2


def test_run_batch_gives_up_after_three_short_answers(monkeypatch):
    calls = []
    monkeypatch.setattr(mo, "guest", lambda script: calls.append(script) or "")
    with pytest.raises(RuntimeError):
        mo._run_batch(["1"], "51234")
    assert len(calls) == mo.TRIES == 3


def test_power_query_isolates_a_failing_expression_with_partition_error(monkeypatch):
    seen = []

    def fake_batch(batch, port_):
        seen.append(list(batch))
        if "bad" in batch:
            return None, "Syntax error"
        return [f"V:{expr}" for expr in batch], None

    monkeypatch.setattr(mo, "_run_batch", fake_batch)
    answers = mo.power_query(["1", "bad", "3"], "51234", chunk=100)
    assert answers == ["V:1", "ERR:PARTITION: Syntax error", "V:3"]
    assert seen == [["1", "bad", "3"], ["1"], ["bad"], ["3"]]


def test_power_query_splits_into_chunks_and_keeps_order(monkeypatch):
    sizes = []

    def fake_batch(batch, port_):
        sizes.append(len(batch))
        return [f"V:{expr}" for expr in batch], None

    monkeypatch.setattr(mo, "_run_batch", fake_batch)
    answers = mo.power_query([str(n) for n in range(5)], "51234", chunk=2)
    assert answers == [f"V:{n}" for n in range(5)]
    assert sizes == [2, 2, 1]


def test_power_query_empty_input_makes_no_guest_call(no_guest):
    assert mo.power_query([], "51234") == []
