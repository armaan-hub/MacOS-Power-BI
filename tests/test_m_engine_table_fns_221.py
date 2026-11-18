"""Tests for Task 221: M engine 21 table/guid functions with Power BI measured behaviour.

Verifies all 59 probe / answer pairs from batch 27 against evaluate_to_text.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    ("Table.TransformRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), each [K] & \"x\")", "V:list:[text:\"ax\",text:\"bx\",text:\"cx\",text:\"dx\",text:\"ex\"]"),
    ("Table.TransformRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), each _[V] * 2)", "V:list:[number:2,number:4,number:6,number:8,number:10]"),
    ("Table.TransformRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), (r) => r)", "V:list:[record:[\"K\"=text:\"a\",\"V\"=number:1,\"W\"=number:1.5],record:[\"K\"=text:\"b\",\"V\"=number:2,\"W\"=null],record:[\"K\"=text:\"c\",\"V\"=number:3,\"W\"=number:3.5],record:[\"K\"=text:\"d\",\"V\"=number:4,\"W\"=number:4.5],record:[\"K\"=text:\"e\",\"V\"=number:5,\"W\"=number:5.5]]"),
    ("Table.TransformRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), each error \"e\")", "UNREPRESENTABLE"),
    ("Table.TransformRows(#table({\"A\"},{}), each 1)", "V:list:[]"),
    ("Table.TransformRows({1,2}, each _)", "ERR:Expression.Error: We cannot convert a value of type List to type Table."),
    ("Table.SingleRow(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}),1))", "V:record:[\"K\"=text:\"a\",\"V\"=number:1,\"W\"=number:1.5]"),
    ("Table.SingleRow(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}))", "ERR:Expression.Error: There were too many elements in the enumeration to complete the operation."),
    ("Table.SingleRow(Table.FirstN(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}),0))", "ERR:Expression.Error: There weren't enough elements in the enumeration to complete the operation."),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 0, 1, 1)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\"];rows=[list:[text:\"b\",number:2,null],list:[text:\"d\",number:4,number:4.5]]"),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 1, 1, 2)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\"];rows=[list:[text:\"a\",number:1,number:1.5],list:[text:\"c\",number:3,number:3.5],list:[text:\"d\",number:4,number:4.5]]"),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 0, 2, 1)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\"];rows=[list:[text:\"c\",number:3,number:3.5]]"),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 9, 1, 1)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\"];rows=[list:[text:\"a\",number:1,number:1.5],list:[text:\"b\",number:2,null],list:[text:\"c\",number:3,number:3.5],list:[text:\"d\",number:4,number:4.5],list:[text:\"e\",number:5,number:5.5]]"),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 0, 0, 1)", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\"];rows=[list:[text:\"a\",number:1,number:1.5],list:[text:\"b\",number:2,null],list:[text:\"c\",number:3,number:3.5],list:[text:\"d\",number:4,number:4.5],list:[text:\"e\",number:5,number:5.5]]"),
    ("Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), -1, 1, 1)", "ERR:Expression.Error: The 'offset' argument is out of range."),
    ("Table.Schema(Table.AlternateRows(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), 0, 1, 1))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"K\",text:\"Text.Type\",false],list:[text:\"V\",text:\"Int64.Type\",false],list:[text:\"W\",text:\"Number.Type\",true]]"),
    ("Table.ExpandListColumn(#table({\"K\",\"L\"},{{\"a\",{1,2}},{\"b\",{}},{\"c\",null},{\"d\",{3}}}),\"L\")", "V:table:cols=[\"K\":\"any\",\"L\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"a\",number:2],list:[text:\"b\",null],list:[text:\"c\",null],list:[text:\"d\",number:3]]"),
    ("Table.ExpandListColumn(#table({\"K\",\"L\"},{{\"a\",1}}),\"L\")", "UNREPRESENTABLE"),
    ("Table.ExpandListColumn(#table({\"K\"},{{\"a\"}}),\"L\")", "ERR:Expression.Error: The column 'L' of the table wasn't found."),
    ("Table.Schema(Table.ExpandListColumn(#table(type table [K = text, L = list], {{\"a\",{1,2}}}),\"L\"))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"K\",text:\"Text.Type\",false],list:[text:\"L\",text:\"Any.Type\",true]]"),
    ("Table.ReplaceRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 1, 1, {[K=\"x\",V=9]})", "V:table:cols=[\"K\":\"any\",\"V\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"x\",number:9],list:[text:\"c\",number:3]]"),
    ("Table.ReplaceRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 1, 1, {[K=\"x\",V=9],[K=\"y\",V=8]})", "V:table:cols=[\"K\":\"any\",\"V\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"x\",number:9],list:[text:\"y\",number:8],list:[text:\"c\",number:3]]"),
    ("Table.ReplaceRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 1, 0, {[K=\"x\",V=9]})", "V:table:cols=[\"K\":\"any\",\"V\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"x\",number:9],list:[text:\"b\",number:2],list:[text:\"c\",number:3]]"),
    ("Table.ReplaceRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 5, 1, {[K=\"x\",V=9]})", "UNREPRESENTABLE"),
    ("Table.ReplaceMatchingRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"a\",V=1]}, [K=\"z\",V=0])", "ERR:Expression.Error: We expected a ListReplacementOperations value."),
    ("Table.ReplaceMatchingRows(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"q\",V=1]}, [K=\"z\",V=0])", "ERR:Expression.Error: We expected a ListReplacementOperations value."),
    ("List.Transform(Table.Split(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 2), each Table.ToRows(_))", "V:list:[list:[list:[text:\"a\",number:1],list:[text:\"b\",number:2]],list:[list:[text:\"c\",number:3]]]"),
    ("Table.Split(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 0)", "ERR:Expression.Error: The 'pageSize' argument is out of range."),
    ("List.Transform(Table.SplitAt(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 1), each Table.ToRows(_))", "V:list:[list:[list:[text:\"a\",number:1]],list:[list:[text:\"b\",number:2],list:[text:\"c\",number:3]]]"),
    ("List.Transform(Table.SplitAt(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), 9), each Table.RowCount(_))", "V:list:[number:3,number:0]"),
    ("List.Transform(Table.Partition(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), \"V\", 2, each _ - 1), each Table.ToRows(_))", "V:list:[list:[list:[text:\"a\",number:1],list:[text:\"c\",number:3]],list:[list:[text:\"b\",number:2]]]"),
    ("Table.FromPartitions(\"V\", {{1, #table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}})}, {2, Table.FirstN(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}),1)}})", "ERR:Expression.Error: The field 'V' already exists in the record."),
    ("Table.AddRankColumn(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), \"R\", {\"V\", Order.Descending})", "V:table:cols=[\"K\":\"text\",\"V\":\"number\",\"W\":\"number\",\"R\":\"number\"];rows=[list:[text:\"e\",number:5,number:5.5,number:1],list:[text:\"d\",number:4,number:4.5,number:2],list:[text:\"c\",number:3,number:3.5,number:3],list:[text:\"b\",number:2,null,number:4],list:[text:\"a\",number:1,number:1.5,number:5]]"),
    ("Table.AddRankColumn(#table({\"A\"},{{1},{1},{2}}), \"R\", {\"A\", Order.Ascending})", "V:table:cols=[\"A\":\"any\",\"R\":\"number\"];rows=[list:[number:1,number:1],list:[number:1,number:1],list:[number:2,number:3]]"),
    ("Table.AddRankColumn(#table({\"A\"},{{1},{1},{2}}), \"R\", {\"A\", Order.Ascending}, [RankKind = RankKind.Dense])", "V:table:cols=[\"A\":\"any\",\"R\":\"number\"];rows=[list:[number:1,number:1],list:[number:1,number:1],list:[number:2,number:2]]"),
    ("Table.AddRankColumn(#table({\"A\"},{{1},{1},{2}}), \"R\", {\"A\", Order.Ascending}, [RankKind = RankKind.Ordinal])", "V:table:cols=[\"A\":\"any\",\"R\":\"number\"];rows=[list:[number:1,number:1],list:[number:1,number:2],list:[number:2,number:3]]"),
    ("Table.AddRankColumn(#table({\"A\"},{{1},{1},{2}}), \"R\", {\"A\", Order.Ascending}, [RankKind = RankKind.Competition])", "V:table:cols=[\"A\":\"any\",\"R\":\"number\"];rows=[list:[number:1,number:1],list:[number:1,number:1],list:[number:2,number:3]]"),
    ("Table.Schema(Table.AddRankColumn(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), \"R\", {\"V\", Order.Descending}))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"K\",text:\"Text.Type\",false],list:[text:\"V\",text:\"Int64.Type\",false],list:[text:\"W\",text:\"Number.Type\",true],list:[text:\"R\",text:\"Int64.Type\",true]]"),
    ("Table.TransformColumnNames(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), Text.Lower)", "V:table:cols=[\"k\":\"any\",\"v\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"b\",number:2],list:[text:\"c\",number:3]]"),
    ("Table.TransformColumnNames(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), each \"x\")", "V:table:cols=[\"x\":\"any\",\"x1\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"b\",number:2],list:[text:\"c\",number:3]]"),
    ("Table.TransformColumnNames(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), each \"p_\" & _)", "V:table:cols=[\"p_K\":\"any\",\"p_V\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"b\",number:2],list:[text:\"c\",number:3]]"),
    ("Table.FirstValue(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}))", "V:text:\"a\""),
    ("Table.FirstValue(Table.FirstN(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}),0), \"d\")", "V:text:\"d\""),
    ("Table.ContainsAll(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"a\",V=1]})", "V:true"),
    ("Table.ContainsAll(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"a\",V=1],[K=\"q\",V=1]})", "V:false"),
    ("Table.PositionOfAny(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"b\",V=2],[K=\"c\",V=3]})", "V:number:1"),
    ("Table.PositionOfAny(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"b\",V=2],[K=\"c\",V=3]}, Occurrence.Last)", "V:number:2"),
    ("Table.PositionOfAny(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), {[K=\"b\",V=2],[K=\"c\",V=3]}, Occurrence.All)", "V:list:[number:1,number:2]"),
    ("Table.CombineColumnsToRecord(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), \"R\", {\"K\",\"V\"})", "V:table:cols=[\"R\":\"record\"];rows=[list:[record:[\"K\"=text:\"a\",\"V\"=number:1]],list:[record:[\"K\"=text:\"b\",\"V\"=number:2]],list:[record:[\"K\"=text:\"c\",\"V\"=number:3]]]"),
    ("Table.Schema(Table.CombineColumnsToRecord(#table(type table [K = text, V = Int64.Type, W = nullable number], {{\"a\",1,1.5},{\"b\",2,null},{\"c\",3,3.5},{\"d\",4,4.5},{\"e\",5,5.5}}), \"R\", {\"K\",\"V\"}))[[Name],[TypeName],[IsNullable]]", "V:table:cols=[\"Name\":\"text\",\"TypeName\":\"text\",\"IsNullable\":\"logical\"];rows=[list:[text:\"R\",text:\"Record.Type\",false],list:[text:\"W\",text:\"Number.Type\",true]]"),
    ("Table.AggregateTableColumn(#table({\"K\",\"T\"},{{\"a\",#table({\"X\"},{{1},{2}})},{\"b\",#table({\"X\"},{{5}})}}), \"T\", {{\"X\", List.Sum, \"SumX\"}})", "V:table:cols=[\"K\":\"any\",\"SumX\":\"any\"];rows=[list:[text:\"a\",number:3],list:[text:\"b\",number:5]]"),
    ("Table.AddJoinColumn(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}), \"K\", #table({\"K\",\"Z\"},{{\"a\",7}}), \"K\", \"J\")", "V:table:cols=[\"K\":\"any\",\"V\":\"any\",\"J\":\"table\"];rows=[list:[text:\"a\",number:1,table:cols=[\"K\":\"any\",\"Z\":\"any\"];rows=[list:[text:\"a\",number:7]]],list:[text:\"b\",number:2,table:cols=[\"K\":\"any\",\"Z\":\"any\"];rows=[]],list:[text:\"c\",number:3,table:cols=[\"K\":\"any\",\"Z\":\"any\"];rows=[]]]"),
    ("Guid.From(\"{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}\")", "V:text:\"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\""),
    ("Guid.From(\"aaaaaaaabbbbccccddddeeeeeeeeeeee\")", "V:text:\"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\""),
    ("Guid.From(\"bad\")", "ERR:DataFormat.Error: We couldn't convert to a guid."),
    ("Guid.From(null)", "V:null"),
    ("Guid.From(1)", "ERR:Expression.Error: We cannot convert the value 1 to type Text."),
    ("Table.ApproximateRowCount(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}))", "V:number:3"),
    ("Table.StopFolding(#table({\"K\",\"V\"}, {{\"a\",1},{\"b\",2},{\"c\",3}}))", "V:table:cols=[\"K\":\"any\",\"V\":\"any\"];rows=[list:[text:\"a\",number:1],list:[text:\"b\",number:2],list:[text:\"c\",number:3]]"),
]

@pytest.mark.parametrize("probe, expected", PAIRS)
def test_m_engine_table_fns_221(probe: str, expected: str) -> None:
    actual = evaluate_to_text(probe)
    assert actual == expected


def test_fix1_from_partitions_no_clash() -> None:
    # Clashing column raises _exists (measured answer check); non-clashing column refuses as unsupported.
    res = evaluate_to_text('Table.FromPartitions("p", {{1,#table({"A"},{{1}})}})')
    assert res == "ERR:Expression.Error: The Table.FromPartitions is not supported by this engine yet."


def test_fix2_replace_matching_rows_optional_criteria() -> None:
    # 2-arg call is accepted by arity; valid unmeasured replacement list refuses as unsupported.
    res2 = evaluate_to_text('Table.ReplaceMatchingRows(#table({"id"},{{1}}), {{[id=1],[id=9]}})')
    assert res2 == "ERR:Expression.Error: The Table.ReplaceMatchingRows is not supported by this engine yet."
    # 3-arg call is also accepted by arity.
    res3 = evaluate_to_text('Table.ReplaceMatchingRows(#table({"id"},{{1}}), {{[id=1],[id=9]}}, "id")')
    assert res3 == "ERR:Expression.Error: The Table.ReplaceMatchingRows is not supported by this engine yet."


def test_fix3_combine_columns_to_record_clashing_name() -> None:
    # New column name that clashes with a remaining column raises _exists duplicate-column error.
    res = evaluate_to_text('Table.CombineColumnsToRecord(#table({"id","nm"},{{1,2}}),"id",{"nm"})')
    assert res == "ERR:Expression.Error: The field 'id' already exists in the record."


def test_fix4_partition_hash_out_of_range() -> None:
    # Hash results outside 0..groups-1 refuse as unsupported.
    res_neg = evaluate_to_text('Table.Partition(#table({"K","V"}, {{"a",1}}), "V", 2, each -1)')
    assert res_neg == "ERR:Expression.Error: The hash result outside 0..groups-1 is not supported by this engine yet."
    res_out = evaluate_to_text('Table.Partition(#table({"id"}, {{1}}), "id", 2, each 5)')
    assert res_out == "ERR:Expression.Error: The hash result outside 0..groups-1 is not supported by this engine yet."


def test_fix5_partition_hash_equal_to_groups_wraps() -> None:
    # Measured in Power BI: hash 2 with 2 groups wraps to bucket 0.
    res = evaluate_to_text('List.Transform(Table.Partition(#table({"id"},{{1},{2}}),"id",2,each 2), each Table.RowCount(_))')
    assert res == "V:list:[number:2,number:0]"


def test_fix5_partition_hash_groups_minus_one_works() -> None:
    res = evaluate_to_text('List.Transform(Table.Partition(#table({"id"},{{1},{2}}),"id",2,each 1), each Table.RowCount(_))')
    assert res == "V:list:[number:0,number:2]"


def test_fix5_partition_zero_groups_refuses_cleanly() -> None:
    res = evaluate_to_text('Table.Partition(#table({"id"},{{1}}),"id",0,each 0)')
    assert res.startswith("ERR:")
    assert "not supported by this engine yet" in res
    assert "ZeroDivisionError" not in res
