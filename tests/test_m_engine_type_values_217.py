"""Task 217: a type context accepts a type value such as Int64.Type (type table [W = Int64.Type]), and type
equality follows Power BI (primitive types by value with facet and nullability, constructed types by identity).

The probes and answers below are Power BI Desktop's answers (headless M answer check, 2026-11-17 and 2026-11-18),
pasted verbatim.
"""

import pytest

from analytics_studio.m_engine.evaluator import evaluate_to_text


PROBES_12 = [
    'Table.Schema(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date, T = text], {{"a", 1, 1.5, 2.25, #date(2024,1,1), "p"}}))[[Name],[TypeName],[Kind]]',
    '#table(type table [W = Int64.Type, P = Percentage.Type], {{1, 0.5}})',
    'Table.Schema(#table(type table [W = Int64.Type, P = Percentage.Type, X = Int32.Type, Y = Decimal.Type, Z = Double.Type], {{1, 0.5, 2, 3.5, 4.5}}))[[Name],[TypeName],[Kind]]',
    'Value.Type(#table(type table [W = Int64.Type], {{1}})) = type table [W = number]',
    'Type.Is(Type.TableColumn(Value.Type(#table(type table [W = Int64.Type], {{1}})), "W"), Int64.Type)',
    'Table.Schema(Table.Group(#table(type table [K = text, W = Int64.Type], {{"a",1},{"a",2}}), {"K"}, {{"Count", each Table.RowCount(_), Int64.Type}, {"S", each List.Sum([W]), type number}}))[[Name],[TypeName],[Kind]]',
    '#table(type table [W = Int64.Type], {{1.5}})',
]

ANSWERS_12 = [
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"K",text:"Text.Type",text:"text"],list:[text:"W",text:"Int64.Type",text:"number"],list:[text:"N",text:"Number.Type",text:"number"],list:[text:"C",text:"Currency.Type",text:"number"],list:[text:"D",text:"Date.Type",text:"date"],list:[text:"T",text:"Text.Type",text:"text"]]',
    'V:table:cols=["W":"number","P":"number"];rows=[list:[number:1,number:0.5]]',
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"W",text:"Int64.Type",text:"number"],list:[text:"P",text:"Percentage.Type",text:"number"],list:[text:"X",text:"Int32.Type",text:"number"],list:[text:"Y",text:"Decimal.Type",text:"number"],list:[text:"Z",text:"Double.Type",text:"number"]]',
    'V:false',
    'V:true',
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"K",text:"Text.Type",text:"text"],list:[text:"Count",text:"Int64.Type",text:"number"],list:[text:"S",text:"Number.Type",text:"number"]]',
    'V:table:cols=["W":"number"];rows=[list:[number:1.5]]',
]

PROBES_13 = [
    'Int64.Type = Number.Type',
    'Int64.Type = type number',
    'type number = type number',
    'Int64.Type = Int64.Type',
    'Currency.Type = Int64.Type',
    'type table [a = number] = type table [a = number]',
    'Value.Type(#table({"a"},{{1}})) = type table [a = any]',
    'type text = Text.Type',
    '(type nullable number) = type number',
    'type {number} = type {number}',
    'Type.Is(Int64.Type, type number)',
    'Type.Is(type number, Int64.Type)',
]

ANSWERS_13 = [
    'V:false',
    'V:false',
    'V:true',
    'V:true',
    'V:false',
    'V:false',
    'V:false',
    'V:true',
    'V:false',
    'V:false',
    'V:true',
    'V:true',
]

PROBES_14 = [
    'let t = type table [a = number] in t = t',
    'let t = type {number} in t = t',
    'let t = type [a = number] in t = t',
    'type [a = number] = type [a = number]',
    'type function (x as number) as number = type function (x as number) as number',
    'let x = #table({"a"},{{1}}) in Value.Type(x) = Value.Type(x)',
    'type table [a = number] <> type table [a = number]',
    'type nullable number = type nullable number',
    'type any = type any',
    'type table = type table',
    'type list = type list',
]

ANSWERS_14 = [
    'V:true',
    'V:true',
    'V:true',
    'V:false',
    'V:false',
    'V:true',
    'V:true',
    'V:true',
    'V:true',
    'V:true',
    'V:true',
]


PROBES_15 = [
    'Number.Type = type number',
    'Value.Type(1) = Number.Type',
    'Value.Type(1) = type number',
    'Text.Type = type text',
    'Type.TableColumn(Value.Type(Table.FromRows({{1}}, {"a"})), "a") = type any',
    'Type.TableColumn(Value.Type(#table({"a"},{{1}})), "a") = type any',
    'Value.Type(#table({"a"},{{1}})) = type table',
    'let t = #table({"a"},{{1}}) in Value.Type(t meta [x=1]) = Value.Type(t)',
    'Int64.Type = Int64.Type',
    'Value.Type(Int64.From(1)) = Int64.Type',
    'Value.Type(Int64.From(1)) = type number',
    'Type.Is(Value.Type(1), Number.Type)',
]


ANSWERS_15 = [
    'V:true',
    'V:true',
    'V:true',
    'V:true',
    'V:true',
    'V:true',
    'V:false',
    'V:true',
    'V:true',
    'V:false',
    'V:true',
    'V:true',
]


_CASES = [
    (probe, answer)
    for probes, answers in ((PROBES_12, ANSWERS_12), (PROBES_13, ANSWERS_13), (PROBES_14, ANSWERS_14),
                            (PROBES_15, ANSWERS_15))
    for probe, answer in zip(probes, answers)
]


@pytest.mark.parametrize("probe,answer", _CASES)
def test_power_bi_answer(probe, answer):
    assert evaluate_to_text(probe) == answer


def test_facet_type_argument_of_transform_column_types_still_works():
    text = evaluate_to_text(
        'Table.Schema(Table.TransformColumnTypes(#table(type table [W = Int64.Type], {{1}}), {{"W", Int64.Type}}))'
        '[[Name],[TypeName]]')
    assert text == 'V:table:cols=["Name":"text","TypeName":"text"];rows=[list:[text:"W",text:"Int64.Type"]]'


@pytest.mark.parametrize("source", [
    "type table [W = 1]",
    '#table(type table [W = "text"], {{1}})',
])
def test_expression_that_is_not_a_type_in_type_context_errors(source):
    assert evaluate_to_text(source).startswith("ERR:")
