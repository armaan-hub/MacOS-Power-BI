"""Tests for Task 219: M engine keeps and combines typed columns like Power BI.

Tests Table.ColumnsOfType, Table.Combine, Table.Join, Table.NestedJoin, and Value.ReplaceType.
Includes all 32 probe / answer pairs from batch 16 and batch 17 as exact string matches,
plus additional robustness cases.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

BATCH16_PAIRS = [
    (
        'Table.Schema(Value.ReplaceType(#table({"a","b"}, {{1, 2}}), type table [a = Int64.Type, b = Currency.Type]))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"a",text:"Int64.Type"],list:[text:"b",text:"Currency.Type"]]',
    ),
    (
        'Table.ColumnNames(Table.SelectColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {Int64.Type})))',
        'V:list:[text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {type number})',
        'V:list:[text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {Currency.Type})',
        'V:list:[text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Int64.Type], {{"c", 3}}), #table(type table [K = text, W = Int64.Type], {{"c", 3}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Int64.Type], {{"c", 3}}), #table(type table [K = text, W = number], {{"d", 4.5}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Join(#table(type table [K = text, W = Int64.Type], {{"c", 3}}), "K", #table(type table [K = text, V = Int64.Type], {{"c", 9}}), "K"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"V",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.TransformColumnTypes(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {{"W", Currency.Type}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Currency.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.AddColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), "Z", each [W] * 2, Int64.Type))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"Z",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.RenameColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {{"W", "W2"}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.SelectRows(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), each [W] > 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.Sort(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {{"W", Order.Descending}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.ReorderColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {"C", "W", "N", "K"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"C",text:"Currency.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"K",text:"Text.Type"]]',
    ),
    (
        'Table.Schema(Table.Distinct(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}})))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.RemoveColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {"K"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.FirstN(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"]]',
    ),
]

BATCH17_PAIRS = [
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {type text})',
        'V:list:[text:"K"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {type nullable number})',
        'V:list:[text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {type any})',
        'V:list:[text:"K",text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {Text.Type})',
        'V:list:[text:"K"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {Int64.Type, type text})',
        'V:list:[text:"K",text:"W",text:"N",text:"C"]',
    ),
    (
        'Table.ColumnsOfType(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type], {{"a", 1, 1.5, 2.25}, {"b", 2, 2.5, 3.5}}), {})',
        'V:list:[]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Int64.Type], {{"c", 3}}), #table(type table [K = text, W = Currency.Type], {{"d", 4.5}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Currency.Type], {{"d", 4.5}}), #table(type table [K = text, W = Int64.Type], {{"c", 3}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Int64.Type], {{"c", 3}}), #table(type table [K = text, W = text], {{"e", "x"}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Any.Type"]]',
    ),
    (
        'Table.Schema(Table.Join(#table(type table [K = text, W = Int64.Type], {{"c", 3}}), "W", #table(type table [W = Currency.Type, V = text], {{3, "q"}}), "W"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"V",text:"Text.Type"]]',
    ),
    (
        'Table.Schema(Table.NestedJoin(#table(type table [K = text, W = Int64.Type], {{"c", 3}}), {"K"}, #table(type table [K = text, V = Int64.Type], {{"c", 9}}), {"K"}, "J", JoinKind.Inner))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"J",text:"Table.Type"]]',
    ),
    (
        'Value.ReplaceType(#table({"a"}, {{"x"}}), type table [a = Int64.Type])',
        'V:table:cols=["a":"number"];rows=[list:[text:"x"]]',
    ),
    (
        'Value.Type(Value.ReplaceType({1, 2}, type {Int64.Type})) = type {Int64.Type}',
        'V:false',
    ),
    (
        'Value.ReplaceType(#table({"a"}, {{1}}), type table [a = Int64.Type, b = text])',
        'ERR:Expression.Error: We cannot convert the specified value to the specified type.',
    ),
    (
        'Table.Schema(Value.ReplaceType(#table({"a"}, {{1}}), type table [a = nullable Int64.Type]))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"a",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.Combine({#table(type table [K = text, W = Int64.Type], {{"c", 3}}), #table(type table [K = text, W = Int32.Type], {{"f", 5}})}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"]]',
    ),
]


@pytest.mark.parametrize("probe,expected", BATCH16_PAIRS)
def test_batch16_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected


@pytest.mark.parametrize("probe,expected", BATCH17_PAIRS)
def test_batch17_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected


def test_table_combine_three_tables_distinct_facets_does_not_crash() -> None:
    expr = """Table.Combine({
        #table(type table [W = Int64.Type], {{1}}),
        #table(type table [W = Currency.Type], {{2.5}}),
        #table(type table [W = number], {{3.0}})
    })"""
    res = evaluate_to_text(expr)
    assert res == 'V:table:cols=["W":"number"];rows=[list:[number:1],list:[number:2.5],list:[number:3]]'


def test_value_replace_type_table_with_null_cells_does_not_crash() -> None:
    expr = 'Value.ReplaceType(#table({"a"}, {{null}}), type table [a = Int64.Type])'
    res = evaluate_to_text(expr)
    assert res == 'V:table:cols=["a":"number"];rows=[list:[null]]'


def test_type_table_used_in_replace_type_and_transform_column_types() -> None:
    expr1 = 'Table.Schema(Value.ReplaceType(#table({"W"}, {{10}}), type table [W = Int64.Type]))[[Name],[TypeName]]'
    assert evaluate_to_text(expr1) == 'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"]]'

    expr2 = 'Table.Schema(Table.TransformColumnTypes(#table(type table [W = Int64.Type], {{1}}), {{"W", Currency.Type}}))[[Name],[TypeName]]'
    assert evaluate_to_text(expr2) == 'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Currency.Type"]]'
