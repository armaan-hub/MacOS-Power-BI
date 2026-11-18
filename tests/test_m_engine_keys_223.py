"""Tests for Task 223: M engine Table.AddKey, ReplaceKeys, Keys, key propagation, and comparer speed.

Verifies probe / answer pairs from batch 28 (items 29-37), batch 29 (items 20-24),
and batch 30 (items 0-4), plus regression, review fixes, and boundary tests.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # batch 28 item 29
    ('Table.Keys(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false))',
     'V:list:[record:["Columns"=list:[text:"K"],"Primary"=false]]'),
    # batch 28 item 30
    ('Table.Keys(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K","V"}, true))',
     'V:list:[record:["Columns"=list:[text:"K",text:"V"],"Primary"=true]]'),
    # batch 28 item 31
    ('Table.Keys(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}))',
     'V:list:[]'),
    # batch 28 item 32
    ('Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"Q"}, false)',
     "ERR:Expression.Error: The column 'Q' of the table wasn't found."),
    # batch 28 item 33
    ('Table.RowCount(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, true))',
     'V:number:5'),
    # batch 28 item 34
    ('Table.Schema(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"V"}, true))[[Name],[TypeName],[IsNullable]]',
     'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",false],list:[text:"V",text:"Int64.Type",false]]'),
    # batch 28 item 35
    ('Table.Keys(Table.ReplaceKeys(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {[Columns={"K"}, Primary=false]}))',
     'V:list:[record:["Columns"=list:[text:"K"],"Primary"=false]]'),
    # batch 28 item 36
    ('Table.Keys(Table.ReplaceKeys(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false), {}))',
     'V:list:[]'),
    # batch 28 item 37
    ('Table.ReplaceKeys(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"})',
     'ERR:Expression.Error: We cannot convert the value "K" to type Record.'),
    # batch 29 item 20
    ('Table.Keys(Table.Sort(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false), {"V"}))',
     'V:list:[record:["Columns"=list:[text:"K"],"Primary"=false]]'),
    # batch 29 item 21
    ('Table.Keys(Table.SelectRows(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false), each [V] > 1))',
     'V:list:[record:["Columns"=list:[text:"K"],"Primary"=false]]'),
    # batch 29 item 22
    ('Table.Keys(Table.RenameColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false), {{"K","Z"}}))',
     'V:list:[record:["Columns"=list:[text:"Z"],"Primary"=false]]'),
    # batch 29 item 23
    ('Table.Keys(Table.RemoveColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, false), {"K"}))',
     'V:list:[]'),
    # batch 29 item 24
    ('Table.Keys(Table.AddColumn(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), {"K"}, true), "N", each 1))',
     'V:list:[record:["Columns"=list:[text:"K"],"Primary"=true]]'),
    # batch 30 item 0
    ('Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), "K", #table(type table [K2 = text, W = Int64.Type], {{"a",10},{"c",30},{"a",11}}), "K2", JoinKind.RightAnti))[[Name],[TypeName],[IsNullable]]',
     'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",true],list:[text:"V",text:"Int64.Type",true],list:[text:"K2",text:"Text.Type",false],list:[text:"W",text:"Int64.Type",false]]'),
    # batch 30 item 1
    ('Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), "K", #table(type table [K2 = text, W = Int64.Type], {{"a",10},{"c",30},{"a",11}}), "K2", JoinKind.LeftSemi))[[Name],[TypeName],[IsNullable]]',
     'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",false],list:[text:"V",text:"Int64.Type",false],list:[text:"K2",text:"Text.Type",true],list:[text:"W",text:"Int64.Type",true]]'),
    # batch 30 item 2
    ('Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), "K", #table(type table [K2 = text, W = Int64.Type], {{"a",10},{"c",30},{"a",11}}), "K2", JoinKind.RightSemi))[[Name],[TypeName],[IsNullable]]',
     'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",true],list:[text:"V",text:"Int64.Type",true],list:[text:"K2",text:"Text.Type",false],list:[text:"W",text:"Int64.Type",false]]'),
    # batch 30 item 3
    ('Table.Join(#table(type table [K2 = text, W = Int64.Type], {{"a",10},{"c",30},{"a",11}}), "K2", #table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), "K", JoinKind.LeftSemi)',
     'V:table:cols=["K2":"text","W":"number","K":"text","V":"number"];rows=[list:[text:"a",number:10,null,null],list:[text:"a",number:11,null,null]]'),
    # batch 30 item 4
    ('Table.Join(#table(type table [K2 = text, W = Int64.Type], {{"a",10},{"c",30},{"a",11}}), "K2", #table(type table [K = text, V = Int64.Type], {{"a",1},{"a",2},{"b",3},{"a",4},{"b",5}}), "K", JoinKind.RightAnti)',
     'V:table:cols=["K2":"text","W":"number","K":"text","V":"number"];rows=[list:[null,null,text:"b",number:3],list:[null,null,text:"b",number:5]]'),
]


@pytest.mark.parametrize("probe,expected", PAIRS)
def test_m_engine_keys_and_schema_pairs(probe: str, expected: str):
    assert evaluate_to_text(probe) == expected


def test_unmeasured_key_propagation_refusal():
    # Calling an unmeasured table function on a table with keys sets keys_unmeasured
    # Calling Table.Keys on such a table must refuse with _unsupported
    probe = 'Table.Keys(Table.Buffer(Table.AddKey(#table(type table [K = text, V = Int64.Type], {{"a",1}}), {"K"}, false)))'
    assert evaluate_to_text(probe) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'


def test_comparer_speed_and_refusal():
    # Local grouping with 3,000 items and Comparer.Ordinal runs fast (linear)
    local_probe = 'Table.RowCount(Table.Group(#table({"K"}, List.Transform(List.Numbers(1, 3000), each {Text.From(_)})), "K", {{"N", each Table.RowCount(_)}}, GroupKind.Local, Comparer.Ordinal))'
    assert evaluate_to_text(local_probe) == 'V:number:3000'

    # Global grouping with Comparer.Ordinal works beyond 500 items (Finding 6)
    global_ordinal_over_500 = 'Table.RowCount(Table.Group(#table({"K"}, List.Transform(List.Numbers(1, 600), each {Text.From(_)})), "K", {{"N", each Table.RowCount(_)}}, GroupKind.Global, Comparer.Ordinal))'
    assert evaluate_to_text(global_ordinal_over_500) == 'V:number:600'

    # Comparer.OrdinalIgnoreCase on actual divergent keys a/A must refuse
    global_divergent = 'Table.Group(#table(type table [K = text, V = Int64.Type], {{"a",1},{"A",2},{"b",3}}), "K", {{"S", each List.Sum([V]), type number}}, GroupKind.Global, Comparer.OrdinalIgnoreCase)'
    assert evaluate_to_text(global_divergent) == 'ERR:Expression.Error: The comparer whose behavior differs from ordinal equality on actual keys is not supported by this engine yet.'

    local_divergent = 'Table.Group(#table(type table [K = text, V = Int64.Type], {{"a",1},{"A",2},{"b",3}}), "K", {{"S", each List.Sum([V]), type number}}, GroupKind.Local, Comparer.OrdinalIgnoreCase)'
    assert evaluate_to_text(local_divergent) == 'ERR:Expression.Error: The comparer whose behavior differs from ordinal equality on actual keys is not supported by this engine yet.'

    # Non-ordinal comparer with > 500 distinct keys refuses
    global_non_ordinal_over_500 = 'Table.RowCount(Table.Group(#table({"K"}, List.Transform(List.Numbers(1, 600), each {Text.From(_)})), "K", {{"N", each Table.RowCount(_)}}, GroupKind.Global, Comparer.OrdinalIgnoreCase))'
    assert evaluate_to_text(global_non_ordinal_over_500) == 'ERR:Expression.Error: The Table.Group with comparer on more than 500 distinct keys is not supported by this engine yet.'


def test_review_fix_nested_and_operator_unmeasured():
    # Finding 1: Table.Combine({keyed})
    p_combine = 'Table.Keys(Table.Combine({Table.AddKey(#table({"A"}, {{1}}), {"A"}, false)}))'
    assert evaluate_to_text(p_combine) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'

    # Finding 1: & operator on tables
    p_concat = 'Table.Keys(Table.AddKey(#table({"A"}, {{1}}), {"A"}, false) & #table({"A"}, {{2}}))'
    assert evaluate_to_text(p_concat) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'

    # Finding 1: Results that are lists of tables
    p_split = 'Table.Keys(Table.Split(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), 1){0})'
    assert evaluate_to_text(p_split) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'

    p_split_at = 'Table.Keys(Table.SplitAt(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), 1){0})'
    assert evaluate_to_text(p_split_at) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'

    p_partition = 'Table.Keys(Table.Partition(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), "A", 2, each 0){0})'
    assert evaluate_to_text(p_partition) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'


def test_review_fix_value_replace_type():
    # Finding 2: Value.ReplaceType preserves keys on clean keyed table
    p_repl = 'Table.Keys(Value.ReplaceType(Table.AddKey(#table({"A"}, {{1}}), {"A"}, false), type table [A = text]))'
    assert evaluate_to_text(p_repl) == 'V:list:[record:["Columns"=list:[text:"A"],"Primary"=false]]'

    # Preserves unmeasured status if input was unmeasured
    p_repl_unmeasured = 'Table.Keys(Value.ReplaceType(Table.Skip(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), 1), type table [A = text]))'
    assert evaluate_to_text(p_repl_unmeasured) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'


def test_review_fix_add_key_replace_keys_unmeasured_propagation():
    # Finding 3: AddKey / ReplaceKeys on unmeasured table keeps unmeasured flag
    p_add_after_skip = 'Table.Keys(Table.AddKey(Table.Skip(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), 1), {"A"}, false))'
    assert evaluate_to_text(p_add_after_skip) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'

    p_rep_after_skip = 'Table.Keys(Table.ReplaceKeys(Table.Skip(Table.AddKey(#table({"A"}, {{1},{2}}), {"A"}, false), 1), {[Columns={"A"}, Primary=false]}))'
    assert evaluate_to_text(p_rep_after_skip) == 'ERR:Expression.Error: The Table.Keys on a table with unmeasured key propagation is not supported by this engine yet.'


def test_review_fix_add_key_unmeasured_shapes():
    # Finding 4: AddKey refuses unmeasured argument shapes
    assert evaluate_to_text('Table.AddKey(#table({"A"}, {{1}}), "A", false)') == 'ERR:Expression.Error: The AddKey with non-list columns argument is not supported by this engine yet.'
    assert evaluate_to_text('Table.AddKey(#table({"A"}, {{1}}), {}, false)') == 'ERR:Expression.Error: The AddKey with empty column list is not supported by this engine yet.'
    assert evaluate_to_text('Table.AddKey(#table({"A"}, {{1}}), {1}, false)') == 'ERR:Expression.Error: The AddKey with non-text column in list is not supported by this engine yet.'
    assert evaluate_to_text('Table.AddKey(#table({"A"}, {{1}}), {"A", "A"}, false)') == 'ERR:Expression.Error: The AddKey with duplicate column name in list is not supported by this engine yet.'
    assert evaluate_to_text('Table.AddKey(#table({"A"}, {{1}}), null, false)') == 'ERR:Expression.Error: The AddKey with null argument is not supported by this engine yet.'


def test_review_fix_replace_keys_unmeasured_shapes():
    # Finding 5: ReplaceKeys refuses unmeasured argument shapes
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={"Z"}, Primary=false]})') == 'ERR:Expression.Error: The key record Columns naming column not in table is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={}, Primary=false]})') == 'ERR:Expression.Error: The key record with empty Columns is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns="A", Primary=false]})') == 'ERR:Expression.Error: The key record Columns that is not a list is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={"A"}, Primary=false, Extra=1]})') == 'ERR:Expression.Error: The key record without exactly Columns and Primary fields is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={"A"}]})') == 'ERR:Expression.Error: The key record without exactly Columns and Primary fields is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={"A"}, Primary=1]})') == 'ERR:Expression.Error: The key record Primary that is not logical is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), {[Columns={"A"}, Primary=false], [Columns={"A"}, Primary=false]})') == 'ERR:Expression.Error: The two identical keys in ReplaceKeys is not supported by this engine yet.'
    assert evaluate_to_text('Table.ReplaceKeys(#table({"A"}, {{1}}), null)') == 'ERR:Expression.Error: The ReplaceKeys with null keys argument is not supported by this engine yet.'
