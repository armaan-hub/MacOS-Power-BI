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
