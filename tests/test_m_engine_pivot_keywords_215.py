"""Task 215: Table.Pivot without aggregation keeps a repeated pair as an error cell, and record literal field names
may be keywords. Expected answers are Power BI's own answers (Power BI answer check, 2026-11-17, live Power BI,
headless M answer check)."""
from analytics_studio.m_engine import evaluate_to_text


def test_pivot_repeated_pair_is_error_cell_row_by_row():
    expr = ('let p = Table.Pivot(#table({"K","A","V"},{{1,"x",10},{1,"x",20},{2,"y",5}}), {"x","y"}, "A", "V"), '
            'q = Table.AddColumn(p, "e", each let r = try [x] in if r[HasError] then r[Error][Reason] & "|" & '
            'r[Error][Message] else Text.From(r[Value])) in Table.RemoveColumns(q, {"x"})')
    expected = ('V:table:cols=["K":"any","y":"any","e":"any"];rows=[list:[number:1,null,text:"Expression.Error|'
                'There were too many elements in the enumeration to complete the operation."],list:[number:2,number:5,null]]')
    assert evaluate_to_text(expr) == expected


def test_pivot_null_repeat_is_error_cell():
    expr = ('let p = Table.Pivot(#table({"K","A","V"},{{1,"x",10},{1,"x",null},{2,"y",5}}), {"x","y"}, "A", "V"), '
            'q = Table.AddColumn(p, "e", each let r = try [x] in if r[HasError] then r[Error][Message] else '
            'Text.From(r[Value])) in Table.RemoveColumns(q, {"x"})')
    expected = ('V:table:cols=["K":"any","y":"any","e":"any"];rows=[list:[number:1,null,text:"There were too many '
                'elements in the enumeration to complete the operation."],list:[number:2,number:5,null]]')
    assert evaluate_to_text(expr) == expected


def test_pivot_double_repeat_both_cells_error():
    expr = ('let p = Table.Pivot(#table({"K","A","V"},{{1,"x",10},{1,"x",20},{1,"y",7},{1,"y",8},{2,"y",5}}), '
            '{"x","y"}, "A", "V"), q = Table.AddColumn(p, "e", each (try Text.From([x]) otherwise "ERR") & "/" & '
            '(try Text.From([y]) otherwise "ERR")) in Table.RemoveColumns(q, {"x","y"})')
    expected = ('V:table:cols=["K":"any","e":"any"];rows=[list:[number:1,text:"ERR/ERR"],list:[number:2,null]]')
    assert evaluate_to_text(expr) == expected


def test_pivot_repeat_table_shape():
    row_count = ('let p = Table.Pivot(#table({"K","A","V"},{{1,"x",10},{1,"x",20},{2,"y",5}}), {"x","y"}, "A", "V") '
                 'in Table.RowCount(p)')
    assert evaluate_to_text(row_count) == "V:number:2"
    names = ('let p = Table.Pivot(#table({"K","A","V"},{{1,"x",10},{1,"x",20},{2,"y",5}}), {"x","y"}, "A", "V") '
             'in Table.ColumnNames(p)')
    assert evaluate_to_text(names) == 'V:list:[text:"K",text:"x",text:"y"]'


def test_record_keyword_field_names():
    assert evaluate_to_text('[let = 1][let]') == "V:number:1"
    assert evaluate_to_text('[if = 1][if]') == "V:number:1"
    assert evaluate_to_text('[type = 1, each = 2, #"let" = 3]') == (
        'V:record:["type"=number:1,"each"=number:2,"let"=number:3]')
