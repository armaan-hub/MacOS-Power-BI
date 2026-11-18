"""Tests for Task 220: M engine Unpivot, ReplaceValue and PrefixColumns column types follow Power BI.

Tests Table.Unpivot, Table.UnpivotOtherColumns, Table.ReplaceValue and Table.PrefixColumns.
Includes all 42 probe / answer pairs from batch 19 and batch 20, plus all 22 probe / answer
pairs from batch 21 and batch 22, as exact string matches, plus two no-crash cases Power BI
did not answer.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

BATCH19_PAIRS = [
    (
        'Table.Schema(Table.Transpose(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}})))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"Column1",text:"Any.Type"],list:[text:"Column2",text:"Any.Type"]]',
    ),
    (
        'Table.Schema(Table.AddIndexColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "Idx", 0, 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"Idx",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Buffer(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}})))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"W","N","C"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"D",text:"Date.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.UnpivotOtherColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"K","D"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"D",text:"Date.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Pivot(Table.AddColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "G", each "x"), {"x"}, "G", "W"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"x",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.ExpandRecordColumn(Table.AddColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "R", each [p = 1, q = "t"]), "R", {"p","q"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"p",text:"Any.Type"],list:[text:"q",text:"Any.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 1, 5, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.FillDown(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"W"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.TransformColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {{"W", each _ + 1}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Any.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.TransformColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {{"W", each _ + 1, Int64.Type}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.DuplicateColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "W", "W2"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"W2",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.PrefixColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "p"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"p.K",text:"Text.Type"],list:[text:"p.W",text:"Int64.Type"],list:[text:"p.N",text:"Number.Type"],list:[text:"p.C",text:"Currency.Type"],list:[text:"p.D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.RemoveRowsWithErrors(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}})))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.Skip(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.Range(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 0, 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.InsertRows(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 0, {[K = "z", W = 9, N = 1, C = 1, D = #date(2024,3,1)]}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.RemoveFirstN(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 1))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.Repeat(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), 2))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.SplitColumn(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), "K", Splitter.SplitTextByDelimiter("-"), {"K1","K2"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K1",text:"Text.Type"],list:[text:"K2",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"]]',
    ),
    (
        'Table.Schema(Table.CombineColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"K","D"}, Combiner.CombineTextByDelimiter("-"), "KD"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"KD",text:"Text.Type"]]',
    ),
    (
        'Table.Schema(Table.SelectColumns(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"W","N"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"],list:[text:"N",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Group(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"K"}, {{"M", each List.Min([W]), Int64.Type}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"M",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.Group(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date], {{"a", 1, 1.5, 2.25, #date(2024,1,1)}, {"b", 2, 2.5, 3.5, #date(2024,2,1)}}), {"W"}, {{"M", each List.Max([N])}}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"],list:[text:"M",text:"Any.Type"]]',
    ),
]

BATCH20_PAIRS = [
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"W","K"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Any.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"W","W2"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"N","C"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"W","I"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"W"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Int64.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"C"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Currency.Type"]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), {"K","D"}, "A", "V"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"I",text:"Int32.Type"],list:[text:"A",text:"Text.Type"],list:[text:"V",text:"Any.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 1, 5, Replacer.ReplaceValue, {"C"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Number.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 1.5, 5, Replacer.ReplaceValue, {"N"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), "a", "z", Replacer.ReplaceText, {"K"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 99, 5, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 1, null, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 1, 5, Replacer.ReplaceValue, {"W","C","N"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Number.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), null, 0, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Number.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), #date(2024,1,1), #date(2025,1,1), Replacer.ReplaceValue, {"D"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), 4, 6, Replacer.ReplaceValue, {"I"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Number.Type"]]',
    ),
    (
        'Table.Schema(Table.PrefixColumns(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), "x y"))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"x y.K",text:"Text.Type"],list:[text:"x y.W",text:"Int64.Type"],list:[text:"x y.W2",text:"Int64.Type"],list:[text:"x y.N",text:"Number.Type"],list:[text:"x y.C",text:"Currency.Type"],list:[text:"x y.D",text:"Date.Type"],list:[text:"x y.I",text:"Int32.Type"]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [K = text, W = Int64.Type, W2 = Int64.Type, N = number, C = Currency.Type, D = date, I = Int32.Type], {{"a", 1, 3, 1.5, 2.25, #date(2024,1,1), 4}, {"b", 2, 4, 2.5, 3.5, #date(2024,2,1), 5}}), "", null, Replacer.ReplaceValue, {"K"}))[[Name],[TypeName]]',
        'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"K",text:"Text.Type"],list:[text:"W",text:"Int64.Type"],list:[text:"W2",text:"Int64.Type"],list:[text:"N",text:"Number.Type"],list:[text:"C",text:"Currency.Type"],list:[text:"D",text:"Date.Type"],list:[text:"I",text:"Int32.Type"]]',
    ),
]


@pytest.mark.parametrize("probe,expected", BATCH19_PAIRS)
def test_batch19_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected


@pytest.mark.parametrize("probe,expected", BATCH20_PAIRS)
def test_batch20_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected


def test_unpivot_int64_number_currency_does_not_crash() -> None:
    """Not a Power BI answer: unpivoting Int64 + number + Currency must build a table, not crash."""
    expr = ('Table.Schema(Table.Unpivot(#table(type table [K = text, W = Int64.Type, N = number, '
            'C = Currency.Type], {{"a", 1, 1.5, 2.25}}), {"W","N","C"}, "A", "V"))[[Name],[TypeName]]')
    res = evaluate_to_text(expr)
    assert res.startswith("V:")


def test_replace_value_date_column_with_null_replacement() -> None:
    """Not a Power BI answer: a null replacement on a date column may stay refused, but must not crash."""
    expr = ('Table.Schema(Table.ReplaceValue(#table(type table [D = date], {{#date(2024,1,1)}}), '
            '#date(2024,1,1), null, Replacer.ReplaceValue, {"D"}))[[Name],[TypeName]]')
    res = evaluate_to_text(expr)
    assert res.startswith("V:") or res.startswith("ERR:Expression.Error:")


BATCH21_PAIRS = [
    (
        'Type.IsNullable(Type.TableColumn(Value.Type(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), 1, 5, Replacer.ReplaceValue, {"W"})), "W"))',
        'V:true',
    ),
    (
        'Type.IsNullable(Type.TableColumn(Value.Type(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), 1, 5, Replacer.ReplaceValue, {"X"})), "X"))',
        'V:false',
    ),
    (
        'Type.IsNullable(Type.TableColumn(Value.Type(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), 1, null, Replacer.ReplaceValue, {"X"})), "X"))',
        'V:true',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), {"D","DT"}, "A2", "V"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"A2",text:"Text.Type",false],list:[text:"V",text:"Any.Type",true]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), {"X","A"}, "A2", "V"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"K",text:"Text.Type",false],list:[text:"A2",text:"Text.Type",false],list:[text:"V",text:"Any.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), {"X","W"}, "A2", "V"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"A2",text:"Text.Type",false],list:[text:"V",text:"Int64.Type",false]]',
    ),
    (
        'Table.ColumnNames(Table.PrefixColumns(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), ""))',
        'V:list:[text:".W",text:".X",text:".D",text:".DT",text:".A",text:".K"]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), #date(2024,1,1), null, Replacer.ReplaceValue, {"D"}))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",true],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), 1, 5, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Number.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, K = text], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, "k"}, {null, 2, #date(2024,2,1), #datetime(2024,2,1,0,0,0), 8, "m"}}), {"X"}, "A2", "V"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"A2",text:"Text.Type",false],list:[text:"V",text:"Int64.Type",false]]',
    ),
]

BATCH22_PAIRS = [
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"X","K"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",true]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"X","D"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",true]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"A","K"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A2",text:"Any.Type",true],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"A","A2"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"W","K"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",true]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"K","NK"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Text.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"X","NK"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",true]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"D","A"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"N2","A"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Any.Type",false]]',
    ),
    (
        'Table.Schema(Table.Unpivot(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), {"X","W"}, "Atr", "Val"))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false],list:[text:"Atr",text:"Text.Type",false],list:[text:"Val",text:"Int64.Type",false]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), #date(2024,1,1), null, Replacer.ReplaceValue, {"D"}))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Int64.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",true],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false]]',
    ),
    (
        'Table.Schema(Table.ReplaceValue(#table(type table [W = nullable Int64.Type, X = Int64.Type, D = date, DT = datetime, A = any, A2 = any, K = text, NK = nullable text, N2 = number], {{1, 1, #date(2024,1,1), #datetime(2024,1,1,0,0,0), 7, 8, "k", "z", 1.5}}), 1, 5, Replacer.ReplaceValue, {"W"}))[[Name],[TypeName],[IsNullable]]',
        'V:table:cols=["Name":"text","TypeName":"text","IsNullable":"logical"];rows=[list:[text:"W",text:"Number.Type",true],list:[text:"X",text:"Int64.Type",false],list:[text:"D",text:"Date.Type",false],list:[text:"DT",text:"DateTime.Type",false],list:[text:"A",text:"Any.Type",true],list:[text:"A2",text:"Any.Type",true],list:[text:"K",text:"Text.Type",false],list:[text:"NK",text:"Text.Type",true],list:[text:"N2",text:"Number.Type",false]]',
    ),
]


@pytest.mark.parametrize("probe,expected", BATCH21_PAIRS)
def test_batch21_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected


@pytest.mark.parametrize("probe,expected", BATCH22_PAIRS)
def test_batch22_power_bi_answers(probe: str, expected: str) -> None:
    assert evaluate_to_text(probe) == expected
