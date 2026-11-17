"""Task 217: a type context accepts a type value such as Int64.Type (type table [W = Int64.Type]).

The probes and answers below are Power BI Desktop's answers (headless M answer check, 2026-11-17), pasted verbatim.
"""

import pytest

from analytics_studio.m_engine.evaluator import evaluate_to_text


PROBES = [
    'Table.Schema(#table(type table [K = text, W = Int64.Type, N = number, C = Currency.Type, D = date, T = text], {{"a", 1, 1.5, 2.25, #date(2024,1,1), "p"}}))[[Name],[TypeName],[Kind]]',
    '#table(type table [W = Int64.Type, P = Percentage.Type], {{1, 0.5}})',
    'Table.Schema(#table(type table [W = Int64.Type, P = Percentage.Type, X = Int32.Type, Y = Decimal.Type, Z = Double.Type], {{1, 0.5, 2, 3.5, 4.5}}))[[Name],[TypeName],[Kind]]',
    'Value.Type(#table(type table [W = Int64.Type], {{1}})) = type table [W = number]',
    'Type.Is(Type.TableColumn(Value.Type(#table(type table [W = Int64.Type], {{1}})), "W"), Int64.Type)',
    'Table.Schema(Table.Group(#table(type table [K = text, W = Int64.Type], {{"a",1},{"a",2}}), {"K"}, {{"Count", each Table.RowCount(_), Int64.Type}, {"S", each List.Sum([W]), type number}}))[[Name],[TypeName],[Kind]]',
    '#table(type table [W = Int64.Type], {{1.5}})',
]

ANSWERS = [
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"K",text:"Text.Type",text:"text"],list:[text:"W",text:"Int64.Type",text:"number"],list:[text:"N",text:"Number.Type",text:"number"],list:[text:"C",text:"Currency.Type",text:"number"],list:[text:"D",text:"Date.Type",text:"date"],list:[text:"T",text:"Text.Type",text:"text"]]',
    'V:table:cols=["W":"number","P":"number"];rows=[list:[number:1,number:0.5]]',
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"W",text:"Int64.Type",text:"number"],list:[text:"P",text:"Percentage.Type",text:"number"],list:[text:"X",text:"Int32.Type",text:"number"],list:[text:"Y",text:"Decimal.Type",text:"number"],list:[text:"Z",text:"Double.Type",text:"number"]]',
    'V:false',
    'V:true',
    'V:table:cols=["Name":"text","TypeName":"text","Kind":"text"];rows=[list:[text:"K",text:"Text.Type",text:"text"],list:[text:"Count",text:"Int64.Type",text:"number"],list:[text:"S",text:"Number.Type",text:"number"]]',
    'V:table:cols=["W":"number"];rows=[list:[number:1.5]]',
]


@pytest.mark.parametrize("index", range(len(PROBES)))
def test_power_bi_answer(index):
    assert evaluate_to_text(PROBES[index]) == ANSWERS[index]


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
