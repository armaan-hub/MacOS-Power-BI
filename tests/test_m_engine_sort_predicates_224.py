"""Tests for Task 224: Table.Sort text and function criteria, and predicate Skip/FirstN/LastN.

Verifies probe / answer pairs from batch 33 (items 0-34).
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # batch 33 item 0
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),"K"))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"a",number:4,text:"z"],list:[text:"b",number:3,text:"x"],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"]]'),
    # batch 33 item 1
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),"V"))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"b",number:3,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 2
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{"K", Order.Descending}))',
     'V:list:[list:[text:"c",number:2,text:"x"],list:[text:"b",number:3,text:"x"],list:[text:"b",number:1,text:"y"],list:[text:"a",number:1,null],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 3
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{{"K", Order.Descending}}))',
     'V:list:[list:[text:"c",number:2,text:"x"],list:[text:"b",number:3,text:"x"],list:[text:"b",number:1,text:"y"],list:[text:"a",number:1,null],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 4
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{{"K", Order.Ascending},{"V", Order.Descending}}))',
     'V:list:[list:[text:"a",number:4,text:"z"],list:[text:"a",number:1,null],list:[text:"b",number:3,text:"x"],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"]]'),
    # batch 33 item 5
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{"K","V"}))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"a",number:4,text:"z"],list:[text:"b",number:1,text:"y"],list:[text:"b",number:3,text:"x"],list:[text:"c",number:2,text:"x"]]'),
    # batch 33 item 6
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{"K",Order.Descending,"V"}))',
     'ERR:Expression.Error: The specified sort criteria is invalid.'),
    # batch 33 item 7
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),"Q"))',
     'ERR:Expression.Error: The specified sort criteria is invalid.'),
    # batch 33 item 8
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),null))',
     'ERR:Expression.Error: The specified sort criteria is invalid.'),
    # batch 33 item 9
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{}))',
     "ERR:Expression.Error: 'Table.Sort' requires at least one sort criterion."),
    # batch 33 item 10
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),"W"))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:3,text:"x"],list:[text:"c",number:2,text:"x"],list:[text:"b",number:1,text:"y"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 11
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{"W", Order.Descending}))',
     'V:list:[list:[text:"a",number:4,text:"z"],list:[text:"b",number:1,text:"y"],list:[text:"b",number:3,text:"x"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:1,null]]'),
    # batch 33 item 12
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),each [V]))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"b",number:3,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 13
    ('Table.ToRows(Table.Sort(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}),{"V", 5}))',
     'ERR:Expression.Error: The specified sort criteria is invalid.'),
    # batch 33 item 14
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] > 2))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 15
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] < 3))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 16
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each true))',
     'V:list:[]'),
    # batch 33 item 17
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each false))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 18
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each null))',
     'UNREPRESENTABLE'),
    # batch 33 item 19
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each 1))',
     'UNREPRESENTABLE'),
    # batch 33 item 20
    ('Table.ToRows(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] > 2))',
     'V:list:[list:[text:"b",number:3,text:"x"]]'),
    # batch 33 item 21
    ('Table.ToRows(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] < 5))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 22
    ('Table.ToRows(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each true))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 23
    ('Table.ToRows(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each false))',
     'V:list:[]'),
    # batch 33 item 24
    ('Table.ToRows(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each null))',
     'UNREPRESENTABLE'),
    # batch 33 item 25
    ('Table.ToRows(Table.RemoveFirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] > 2))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 26
    ('Table.ToRows(Table.RemoveFirstN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each false))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 27
    ('Table.ToRows(Table.LastN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] < 3))',
     'V:list:[]'),
    # batch 33 item 28
    ('Table.ToRows(Table.LastN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each true))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 29
    ('Table.ToRows(Table.RemoveLastN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] < 3))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 30
    ('Table.ToRows(Table.RemoveLastN(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each false))',
     'V:list:[list:[text:"b",number:3,text:"x"],list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 31
    ('Table.Schema(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [V] > 2))[[Name],[TypeName],[IsNullable]]',
     'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",false],list:[text:"V",text:"Int64.Type",false],list:[text:"W",text:"Text.Type",true]]'),
    # batch 33 item 32
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), (r) => r[K] = "b"))',
     'V:list:[list:[text:"a",number:1,null],list:[text:"b",number:1,text:"y"],list:[text:"c",number:2,text:"x"],list:[text:"a",number:4,text:"z"]]'),
    # batch 33 item 33
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), (r, i) => true))',
     'UNREPRESENTABLE'),
    # batch 33 item 34
    ('Table.ToRows(Table.Skip(#table(type table [K = text, V = Int64.Type, W = nullable text], {{"b",3,"x"},{"a",1,null},{"b",1,"y"},{"c",2,"x"},{"a",4,"z"}}), each [Q] > 1))',
     'UNREPRESENTABLE'),
]

@pytest.mark.parametrize("expr, expected", PAIRS)
def test_m_engine_sort_predicates_pairs(expr: str, expected: str):
    actual = evaluate_to_text(expr)
    if expected == "UNREPRESENTABLE":
        assert actual == "UNREPRESENTABLE" or actual.startswith("ERR:"), (
            f"Expected UNREPRESENTABLE or error refusal for expr: {expr}\nActual: {actual}"
        )
    else:
        assert actual == expected, (
            f"Result mismatch for expr: {expr}\nExpected: {expected}\nActual:   {actual}"
        )


ADD_RANK_COLUMN_OLD_SHAPES = [
    # text criterion -> old convert error
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", "V")',
     'ERR:Expression.Error: We cannot convert the value "V" to type List.'),
    # function criterion -> old convert error
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", each [V])',
     'ERR:Expression.Error: We cannot convert a value of type Function to type List.'),
    # empty list -> old accepted empty sort
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", {})',
     'V:table:cols=["K":"text","V":"number","R":"number"];rows=[list:[text:"a",number:1,number:1]]'),
    # null -> old convert error
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", null)',
     'ERR:Expression.Error: We cannot convert the value null to type List.'),
    # single text list -> old accepted
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", {"V"})',
     'V:table:cols=["K":"text","V":"number","R":"number"];rows=[list:[text:"a",number:1,number:1]]'),
    # pair list -> old accepted
    ('Table.AddRankColumn(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "R", {{"V", Order.Descending}})',
     'V:table:cols=["K":"text","V":"number","R":"number"];rows=[list:[text:"a",number:1,number:1]]'),
]


@pytest.mark.parametrize("expr, expected", ADD_RANK_COLUMN_OLD_SHAPES)
def test_add_rank_column_retains_old_behavior(expr: str, expected: str):
    assert evaluate_to_text(expr) == expected


TABLE_SORT_UNMEASURED_AND_OLD_SHAPES = [
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"K", true})',
     'ERR:Expression.Error: We cannot convert the value true to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"K", null})',
     'ERR:Expression.Error: We cannot convert the value null to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"K", 0.5})',
     'ERR:Expression.Error: The sort order is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {{"K"}})',
     'ERR:Expression.Error: The sort criteria is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {{"K", Order.Ascending, 1}})',
     'ERR:Expression.Error: The sort criteria is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {{null, Order.Ascending}})',
     'ERR:Expression.Error: The sort criteria is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {{"K", Order.Descending}, {"V"}})',
     'ERR:Expression.Error: The sort criteria is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {1, 2})',
     'ERR:Expression.Error: We cannot convert the value 1 to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"V", 2})',
     'ERR:Expression.Error: The sort order is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"V", -1})',
     'ERR:Expression.Error: The sort order is not supported by this engine yet.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {"K", Comparer.OrdinalIgnoreCase})',
     'ERR:Expression.Error: We cannot convert a value of type Function to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {each [V], Order.Descending})',
     'ERR:Expression.Error: We cannot convert a value of type Function to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), (a, b) => 0)',
     'ERR:Expression.Error: We cannot convert a value of type Function to type List.'),
    ('Table.Sort(#table(type table [K = text, V = Int64.Type], {{"b",1},{"a",2}}), {{"K", null}})',
     'V:table:cols=["K":"text","V":"number"];rows=[list:[text:"a",number:2],list:[text:"b",number:1]]'),
]


@pytest.mark.parametrize("expr, expected", TABLE_SORT_UNMEASURED_AND_OLD_SHAPES)
def test_table_sort_unmeasured_and_old_shapes(expr: str, expected: str):
    assert evaluate_to_text(expr) == expected


def test_key_function_sort_decorate_undecorate_efficiency():
    # Decorate-sort-undecorate verifies key function is invoked O(n) times, stable, and correctly orders nulls
    expr = (
        'Table.ToRows(Table.Sort(#table(type table [K = text, V = nullable number], '
        '{{"c", 2}, {"a", null}, {"b", 1}, {"d", null}, {"e", 1}}), each [V]))'
    )
    # nulls first ascending, equal values stable
    expected = (
        'V:list:[list:[text:"a",null],list:[text:"d",null],'
        'list:[text:"b",number:1],list:[text:"e",number:1],list:[text:"c",number:2]]'
    )
    assert evaluate_to_text(expr) == expected

