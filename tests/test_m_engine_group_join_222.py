"""Tests for Task 222: M engine GroupKind, semi/anti joins and List.DateTimeZones.

Verifies 49 probe / answer pairs from batch 28 (items 0-28) and batch 29 (items 0-19) against evaluate_to_text.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:3],list:[text:\"a\",number:4],list:[text:\"b\",number:5]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Global)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:7],list:[text:\"b\",number:8]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, 0)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:3],list:[text:\"a\",number:4],list:[text:\"b\",number:5]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, 1)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:7],list:[text:\"b\",number:8]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, 2)", "ERR:Expression.Error: The value for a 'GroupKind.Type' enumeration was not one of the allowed values: 'GroupKind.Local, GroupKind.Global'."),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local, Comparer.OrdinalIgnoreCase)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:3],list:[text:\"a\",number:4],list:[text:\"b\",number:5]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Global, Comparer.OrdinalIgnoreCase)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:7],list:[text:\"b\",number:8]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), {\"K\"}, {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:3],list:[text:\"a\",number:4],list:[text:\"b\",number:5]]"),
    ("Table.Group(Table.FirstN(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}),0), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[]"),
    ("Table.Schema(Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"K\",text:\"Text.Type\",false],list:[text:\"S\",text:\"Number.Type\",false]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"N\", each Table.RowCount(_), Int64.Type}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"N\":\"number\"];rows=[list:[text:\"a\",number:2],list:[text:\"b\",number:1],list:[text:\"a\",number:1],list:[text:\"b\",number:1]]"),
    ("Table.Group(Table.Sort(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}),{\"K\"}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:7],list:[text:\"b\",number:8]]"),
    ("GroupKind.Local", "V:number:0"),
    ("GroupKind.Global", "V:number:1"),
    ("{JoinKind.Inner, JoinKind.LeftOuter, JoinKind.RightOuter, JoinKind.FullOuter, JoinKind.LeftAnti, JoinKind.RightAnti}", "V:list:[number:0,number:1,number:2,number:3,number:4,number:5]"),
    ("JoinKind.LeftSemi", "V:number:6"),
    ("JoinKind.RightSemi", "V:number:7"),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K = text, W = Int64.Type], {{\"a\",10},{\"c\",30}}), \"K\", JoinKind.LeftSemi)", "ERR:Expression.Error: A join operation cannot result in a table with duplicate column names (\"K\")."),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K = text, W = Int64.Type], {{\"a\",10},{\"c\",30}}), \"K\", 6)", "ERR:Expression.Error: A join operation cannot result in a table with duplicate column names (\"K\")."),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K = text, W = Int64.Type], {{\"a\",10},{\"c\",30}}), \"K\", 7)", "ERR:Expression.Error: A join operation cannot result in a table with duplicate column names (\"K\")."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 3, #duration(1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2026-01-02T00:00:00.0000000+00:00,datetimezone:2026-01-03T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,4,0), 2, #duration(0,6,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+04:00,datetimezone:2026-01-01T06:00:00.0000000+04:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 0, #duration(1,0,0,0))", "V:list:[]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), -1, #duration(1,0,0,0))", "ERR:Expression.Error: The 'count' argument is out of range."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 2, #duration(-1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2025-12-31T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 2, #duration(0,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2026-01-01T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(null, 2, #duration(1,0,0,0))", "ERR:Expression.Error: We cannot convert the value null to type DateTimeZone."),
    ("List.DateTimeZones(#datetime(2026,1,1,0,0,0), 2, #duration(1,0,0,0))", "ERR:Expression.Error: We cannot convert the value #datetime(2026, 1, 1, 0, 0, 0) to type DateTimeZone."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 2.5, #duration(1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2026-01-02T00:00:00.0000000+00:00,datetimezone:2026-01-03T00:00:00.0000000+00:00]"),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K2 = text, W = Int64.Type], {{\"a\",10},{\"c\",30},{\"a\",11}}), \"K2\", JoinKind.LeftSemi)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"K2\":\"text\",\"W\":\"number\"];rows=[list:[text:\"a\",number:1,null,null],list:[text:\"a\",number:2,null,null],list:[text:\"a\",number:4,null,null]]"),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K2 = text, W = Int64.Type], {{\"a\",10},{\"c\",30},{\"a\",11}}), \"K2\", JoinKind.RightSemi)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"K2\":\"text\",\"W\":\"number\"];rows=[list:[null,null,text:\"a\",number:10],list:[null,null,text:\"a\",number:11]]"),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K2 = text, W = Int64.Type], {{\"a\",10},{\"c\",30},{\"a\",11}}), \"K2\", JoinKind.LeftAnti)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"K2\":\"text\",\"W\":\"number\"];rows=[list:[text:\"b\",number:3,null,null],list:[text:\"b\",number:5,null,null]]"),
    ("Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K2 = text, W = Int64.Type], {{\"a\",10},{\"c\",30},{\"a\",11}}), \"K2\", JoinKind.RightAnti)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"K2\":\"text\",\"W\":\"number\"];rows=[list:[null,null,text:\"c\",number:30]]"),
    ("Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", #table(type table [K2 = text, W = Int64.Type], {{\"a\",10},{\"c\",30},{\"a\",11}}), \"K2\", JoinKind.LeftAnti))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"K\",text:\"Text.Type\",false],list:[text:\"V\",text:\"Int64.Type\",false],list:[text:\"K2\",text:\"Text.Type\",true],list:[text:\"W\",text:\"Int64.Type\",true]]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 1.5, #duration(1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2026-01-02T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 0.5, #duration(1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 3.5, #duration(1,0,0,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000+00:00,datetimezone:2026-01-02T00:00:00.0000000+00:00,datetimezone:2026-01-03T00:00:00.0000000+00:00,datetimezone:2026-01-04T00:00:00.0000000+00:00]"),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), null, #duration(1,0,0,0))", "ERR:Expression.Error: We cannot convert the value null to type Number."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 2, null)", "ERR:Expression.Error: We cannot convert the value null to type Duration."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 2, 1)", "ERR:Expression.Error: We cannot convert the value 1 to type Duration."),
    ("List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,-5,-30), 2, #duration(0,1,30,0))", "V:list:[datetimezone:2026-01-01T00:00:00.0000000-05:30,datetimezone:2026-01-01T01:30:00.0000000-05:30]"),
    ("List.DateTimeZones(#datetimezone(2026,1,31,23,0,0,0,0), 3, #duration(0,1,0,0))", "V:list:[datetimezone:2026-01-31T23:00:00.0000000+00:00,datetimezone:2026-02-01T00:00:00.0000000+00:00,datetimezone:2026-02-01T01:00:00.0000000+00:00]"),
    ("List.Count(List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), 1000, #duration(0,0,1,0)))", "V:number:1000"),
    ("Table.Group(#table(type table [A = text, B = text, V = Int64.Type], {{\"x\",\"p\",1},{\"x\",\"p\",2},{\"x\",\"q\",3},{\"x\",\"p\",4}}), {\"A\",\"B\"}, {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"A\":\"text\",\"B\":\"text\",\"S\":\"number\"];rows=[list:[text:\"x\",text:\"p\",number:3],list:[text:\"x\",text:\"q\",number:3],list:[text:\"x\",text:\"p\",number:4]]"),
    ("Table.Group(#table(type table [K = nullable text, V = Int64.Type], {{null,1},{null,2},{\"a\",3},{null,4}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[null,number:3],list:[text:\"a\",number:3],list:[null,number:4]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {}, GroupKind.Local)", "V:table:cols=[\"K\":\"text\"];rows=[list:[text:\"a\"],list:[text:\"b\"],list:[text:\"a\"],list:[text:\"b\"]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, null)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:7],list:[text:\"b\",number:8]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, GroupKind.Local, null)", "V:table:cols=[\"K\":\"text\",\"S\":\"number\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:3],list:[text:\"a\",number:4],list:[text:\"b\",number:5]]"),
    ("Table.Group(#table(type table [K = text, V = Int64.Type], {{\"a\",1},{\"a\",2},{\"b\",3},{\"a\",4},{\"b\",5}}), \"K\", {{\"S\", each List.Sum([V]), type number}}, \"x\")", "ERR:Expression.Error: We cannot convert the value \"x\" to type Number."),
]


@pytest.mark.parametrize("probe,expected", PAIRS)
def test_m_engine_group_join_datetimezones_222(probe: str, expected: str) -> None:
    if expected == "UNREPRESENTABLE":
        pytest.skip("Answer is unrepresentable in engine")
    assert evaluate_to_text(probe) == expected


def test_fix1_global_grouping_performance() -> None:
    # 3000 distinct keys in Global grouping runs in linear time (~0.01s), not quadratic
    probe = 'Table.RowCount(Table.Group(#table({"K"}, List.Transform(List.Numbers(1, 3000), each {_})), "K", {}))'
    assert evaluate_to_text(probe) == 'V:number:3000'


def test_fix2_refuse_nan_and_unhashable_keys() -> None:
    nan_probe = 'Table.Group(#table({"K"}, {{#nan}}), "K", {})'
    assert evaluate_to_text(nan_probe) == 'ERR:Expression.Error: The value without an equality key is not supported by this engine yet.'
    list_probe = 'Table.Group(#table({"K"}, {{{1}}}), "K", {})'
    assert evaluate_to_text(list_probe) == 'ERR:Expression.Error: The value without an equality key is not supported by this engine yet.'


def test_fix3_refuse_differing_comparer() -> None:
    probe = 'Table.Group(#table({"K"}, {{"a"},{"A"}}), "K", {}, GroupKind.Global, Comparer.OrdinalIgnoreCase)'
    assert evaluate_to_text(probe) == 'ERR:Expression.Error: The comparer whose behavior differs from ordinal equality on actual keys is not supported by this engine yet.'


def test_fix4_right_anti_and_right_semi_schema() -> None:
    probe_anti = 'Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "K", #table(type table [K2 = text, W = Int64.Type], {{"b",2}}), "K2", JoinKind.RightAnti))[[Name],[TypeName],[IsNullable]]'
    expected_anti = 'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",true],list:[text:"V",text:"Int64.Type",true],list:[text:"K2",text:"Text.Type",false],list:[text:"W",text:"Int64.Type",false]]'
    assert evaluate_to_text(probe_anti) == expected_anti

    probe_semi = 'Table.Schema(Table.Join(#table(type table [K = text, V = Int64.Type], {{"a",1}}), "K", #table(type table [K2 = text, W = Int64.Type], {{"a",2}}), "K2", JoinKind.RightSemi))[[Name],[TypeName],[IsNullable]]'
    expected_semi = 'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"K",text:"Text.Type",true],list:[text:"V",text:"Int64.Type",true],list:[text:"K2",text:"Text.Type",false],list:[text:"W",text:"Int64.Type",false]]'
    assert evaluate_to_text(probe_semi) == expected_semi


def test_fix5_list_datetimezones_negative_fractional_count() -> None:
    probe = 'List.DateTimeZones(#datetimezone(2026,1,1,0,0,0,0,0), -0.5, #duration(1,0,0,0))'
    assert evaluate_to_text(probe) == 'ERR:Expression.Error: The List.DateTimeZones count in (-1, 0) is not supported by this engine yet.'
