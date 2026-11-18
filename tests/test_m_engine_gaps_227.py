"""Tests for Task 227: M engine closes key, gzip, Lines and List.Random gaps.

Verifies 51 probe / answer pairs from batch 37 against evaluate_to_text.
Item 43 is UNREPRESENTABLE: asserted that the engine refuses with "not supported by this engine yet".
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # item 0
    ("Binary.ToText(null)",
     "V:null"),
    # item 1
    ("Binary.ToText(null, BinaryEncoding.Hex)",
     "V:null"),
    # item 2
    ("Binary.ToText(Text.ToBinary(\"a\"), null)",
     "V:text:\"YQ==\""),
    # item 3
    ("Binary.ToText(Text.ToBinary(\"a\"), 7)",
     "ERR:Expression.Error: Invalid binary encoding."),
    # item 4
    ("Table.Keys(Table.FillDown(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"K\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 5
    ("Table.Keys(Table.FillDown(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"K\",\"W\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 6
    ("Table.Keys(Table.FillUp(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"W\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 7
    ("Table.Keys(Table.RemoveRows(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),1,0))",
     "V:list:[]"),
    # item 8
    ("Table.Keys(Table.RemoveRows(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),0,2))",
     "V:list:[]"),
    # item 9
    ("Table.Keys(Table.RemoveRows(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),0,1))",
     "V:list:[]"),
    # item 10
    ("Table.Keys(Table.Distinct(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"K\",\"W\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 11
    ("Table.Keys(Table.Distinct(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"K\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 12
    ("Table.Keys(Table.Distinct(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"V\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 13
    ("Table.Keys(Table.TransformColumnTypes(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{{\"K\", type text},{\"W\", type text}}))",
     "V:list:[]"),
    # item 14
    ("Table.Keys(Table.TransformColumnTypes(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{{\"K\", type text}}))",
     "V:list:[]"),
    # item 15
    ("Table.Keys(Table.TransformColumnTypes(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{{\"W\", type number}}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 16
    ("Table.Keys(Table.TransformColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{{\"K\", each _}}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 17
    ("Table.Keys(Table.TransformColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{{\"W\", each _ & \"z\"}}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 18
    ("Table.Keys(Table.TransformColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{{\"W\", each _},{\"V\", each _ + 1}}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 19
    ("Table.Keys(Table.Range(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),0,0))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 20
    ("Table.Keys(Table.Range(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),3,0))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 21
    ("Table.Keys(Table.Range(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),0,2))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 22
    ("Table.Keys(Table.SelectColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"V\",\"K\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 23
    ("Table.Keys(Table.SelectColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"V\",\"Q\"}, MissingField.UseNull))",
     "V:list:[]"),
    # item 24
    ("Table.Keys(Table.SelectColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),{\"K\",\"Q\"}, MissingField.UseNull))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 25
    ("Table.Keys(Table.SelectColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"K\",\"W\"}))",
     "V:list:[]"),
    # item 26
    ("Table.Keys(Table.RemoveColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"W\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\",text:\"V\"],\"Primary\"=true]]"),
    # item 27
    ("Table.Keys(Table.RemoveColumns(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\",\"V\"},true),{\"V\"}))",
     "V:list:[]"),
    # item 28
    ("Table.Keys(Table.ReplaceValue(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),\"x\",\"q\",Replacer.ReplaceText,{\"W\"}))",
     "V:list:[record:[\"Columns\"=list:[text:\"K\"],\"Primary\"=false]]"),
    # item 29
    ("Table.Keys(Table.ReplaceValue(Table.AddKey(#table(type table [K = text, V = Int64.Type, W = text], {{\"a\",1,\"x\"},{\"b\",2,\"x\"},{\"a\",3,\"y\"}}),{\"K\"},false),\"a\",\"q\",Replacer.ReplaceText,{\"K\",\"W\"}))",
     "V:list:[]"),
    # item 30
    ("Binary.ToText(Binary.Decompress(Binary.FromText(\"1f8b0800000000000400f348cdc9c907008289d1f705\", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)",
     "V:text:\"48656c6c6f\""),
    # item 31
    ("Binary.ToText(Binary.Decompress(Binary.FromText(\"1f8b0800000000000400f348cdc9c907008289\", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)",
     "V:text:\"48656c6c6f\""),
    # item 32
    ("Binary.ToText(Binary.Decompress(Binary.FromText(\"1f8b0800000000000400f348cdc9c90700\", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)",
     "V:text:\"48656c6c6f\""),
    # item 33
    ("Binary.ToText(Binary.Decompress(Binary.FromText(\"1f8b0800000000000400\", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)",
     "V:text:\"\""),
    # item 34
    ("Binary.ToText(Binary.Decompress(Binary.FromText(\"1f8b08\", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)",
     "V:text:\"\""),
    # item 35
    ("Binary.ToText(Lines.ToBinary({\"a\"}, null, 12001), BinaryEncoding.Hex)",
     "V:text:\"0000feff000000610000000d0000000a\""),
    # item 36
    ("Binary.ToText(Lines.ToBinary({\"a\"}, null, 12001, true), BinaryEncoding.Hex)",
     "V:text:\"0000feff000000610000000d0000000a\""),
    # item 37
    ("Binary.ToText(Lines.ToBinary({Character.FromNumber(55357)}), BinaryEncoding.Hex)",
     "ERR:Expression.Error: We couldn't convert to Character."),
    # item 38
    ("Binary.ToText(Lines.ToBinary({Character.FromNumber(55357)}, null, 1200), BinaryEncoding.Hex)",
     "ERR:Expression.Error: We couldn't convert to Character."),
    # item 39
    ("Binary.ToText(Lines.ToBinary({\"日\"}, null, 1252), BinaryEncoding.Hex)",
     "V:text:\"3f0d0a\""),
    # item 40
    ("Binary.ToText(Lines.ToBinary({\"日\"}, null, 437), BinaryEncoding.Hex)",
     "V:text:\"3f0d0a\""),
    # item 41
    ("Binary.ToText(Lines.ToBinary({\"😀\"}), BinaryEncoding.Hex)",
     "V:text:\"f09f98800d0a\""),
    # item 42
    ("Binary.ToText(Lines.ToBinary({\"😀\"}, null, 1200), BinaryEncoding.Hex)",
     "V:text:\"3dd800de0d000a00\""),
    # item 44
    ("List.Random(-1, 2147483648)",
     "ERR:Expression.Error: The 'count' argument is out of range."),
    # item 45
    ("List.Random(-1, 1)",
     "ERR:Expression.Error: The 'count' argument is out of range."),
    # item 46
    ("List.Random(1.5, 1)",
     "ERR:Expression.Error: The number is out of range of a 32 bit integer value."),
    # item 47
    ("List.Random(2.5)",
     "ERR:Expression.Error: The number is out of range of a 32 bit integer value."),
    # item 48
    ("List.Count(List.Random(2.5, 3))",
     "ERR:Expression.Error: The number is out of range of a 32 bit integer value."),
    # item 49
    ("List.Random(1, 0)",
     "V:list:[number:0.72624326996795985]"),
    # item 50
    ("List.Random(1, 1)",
     "V:list:[number:0.24866858415709278]"),
]


@pytest.mark.parametrize("probe, expected", PAIRS)
def test_batch37_item(probe, expected):
    actual = evaluate_to_text(probe)
    assert actual == expected


def test_batch37_item_43_unrepresentable_refusal():
    probe = "List.Random(0, 1.5)"
    res = evaluate_to_text(probe)
    assert "not supported by this engine yet" in res
