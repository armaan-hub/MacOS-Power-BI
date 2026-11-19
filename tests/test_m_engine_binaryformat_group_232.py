"""Tests for Task 232: BinaryFormat.Group and BinaryOccurrence (Power BI answer check).

Verifies probe / answer pairs from batch 48 (all 74), batch 44 (12-30), and batch 45 (all 34).
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # batch48_0
    ('let r = try BinaryOccurrence.Optional in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0'),
    # batch48_1
    ('let r = try BinaryOccurrence.Required in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1'),
    # batch48_2
    ('let r = try BinaryOccurrence.Repeating in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:2'),
    # batch48_3
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_4
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Optional}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_5
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Repeating}})(#binary({0,9,0,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[number:9,number:8]]'),
    # batch48_6
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Repeating}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[number:9]]'),
    # batch48_7
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Required}})(#binary({0,9,1,0,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:7]'),
    # batch48_8
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Required}})(#binary({1,0,7,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:7]'),
    # batch48_9
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Optional}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,null]'),
    # batch48_10
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Optional}})(#binary({0,9,1,0,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:7]'),
    # batch48_11
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Repeating}})(#binary({0,9,1,0,7,1,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,list:[number:7,number:6]]'),
    # batch48_12
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.UnsignedInteger16,BinaryOccurrence.Repeating}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,list:[]]'),
    # batch48_13
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9,0,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_14
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch48_15
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch48_16
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Optional}})(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[null]'),
    # batch48_17
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Repeating}})(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[]]'),
    # batch48_18
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({5,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_19
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{5,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({5,9,0,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:8,number:9]'),
    # batch48_20
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{"a",BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({97,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_21
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({1,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_22
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({1,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_23
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9,1,8,0,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_24
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Optional},{1,BinaryFormat.Byte,BinaryOccurrence.Optional}})(#binary({1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[null,number:8]'),
    # batch48_25
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Optional},{1,BinaryFormat.Byte,BinaryOccurrence.Optional}})(#binary({1,8,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:8]'),
    # batch48_26
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Optional},{1,BinaryFormat.Byte,BinaryOccurrence.Optional}})(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[null,null]'),
    # batch48_27
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Repeating},{1,BinaryFormat.Byte,BinaryOccurrence.Repeating}})(#binary({0,1,1,2,0,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[number:1,number:3],list:[number:2]]'),
    # batch48_28
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Repeating},{1,BinaryFormat.Byte,BinaryOccurrence.Repeating}})(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[],list:[number:2]]'),
    # batch48_29
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.Byte)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_30
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.Byte)(#binary({0,9,7,8,7,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_31
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.Byte)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch48_32
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.Byte.NoSuch)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The import BinaryFormat.Byte.NoSuch matches no exports. Did you miss a module reference?"]'),
    # batch48_33
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.Null)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_34
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>BinaryFormat.UnsignedInteger16)(#binary({0,9,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch48_35
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>k)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value isn\'t a binary format value."]'),
    # batch48_36
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(k)=>null)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value isn\'t a binary format value."]'),
    # batch48_37
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},1)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 1 to type Function."]'),
    # batch48_38
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},"a")(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value \\"a\\" to type Function."]'),
    # batch48_39
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},()=>BinaryFormat.Byte)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects 0."]'),
    # batch48_40
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},(a,b)=>BinaryFormat.Byte)(#binary({0,9,7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects 2."]'),
    # batch48_41
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}},null,1)(#binary({0,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:8]'),
    # batch48_42
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}},null,1)(#binary({0,9,1,8,0,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_43
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}},null,0)(#binary({0,9,1,8,0,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_44
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}},null,9)(#binary({0,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:8]'),
    # batch48_45
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}},null,"x")(#binary({0,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:8]'),
    # batch48_46
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch48_47
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch48_48
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,9}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value for a \'BinaryOccurrence.Type\' enumeration was not one of the allowed values: \'BinaryOccurrence.Optional, BinaryOccurrence.Required, BinaryOccurrence.Repeating\'."]'),
    # batch48_49
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,null}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Number."]'),
    # batch48_50
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,"a"}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value \\"a\\" to type Number."]'),
    # batch48_51
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,5,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value isn\'t a binary format value."]'),
    # batch48_52
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,null,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value isn\'t a binary format value."]'),
    # batch48_53
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{null,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_54
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch48_55
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({1,8,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,number:8]'),
    # batch48_56
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required},{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch48_57
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Text(2),BinaryOccurrence.Required},{1,BinaryFormat.Binary(1),BinaryOccurrence.Required}})(#binary({1,5,0,65,66})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"AB",binary:BQ==]'),
    # batch48_58
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.List(BinaryFormat.Byte,2),BinaryOccurrence.Repeating}})(#binary({0,1,2,0,3,4})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[list:[number:1,number:2],list:[number:3,number:4]]]'),
    # batch48_59
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Record([a=BinaryFormat.Byte]),BinaryOccurrence.Repeating}})(#binary({0,5,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[record:["a"=number:5],record:["a"=number:6]]]'),
    # batch48_60
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},null)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_61
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch48_62
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,null)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type List."]'),
    # batch48_63
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,5)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 5 to type List."]'),
    # batch48_64
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,"a")(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value \\"a\\" to type List."]'),
    # batch48_65
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(null) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Binary."]'),
    # batch48_66
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch48_67
    ('let r = try BinaryFormat.Group(5,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 5 to type Function."]'),
    # batch48_68
    ('let r = try BinaryFormat.Group(null,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch48_69
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects between 2 and 4."]'),
    # batch48_70
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}},null,0,5)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"5 arguments were passed to a function which expects between 2 and 4."]'),
    # batch48_71
    ('let r = try BinaryFormat.Group(BinaryFormat.Text(1),{{"a",BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({97,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_72
    ('let r = try BinaryFormat.Group(BinaryFormat.UnsignedInteger16,{{1,BinaryFormat.Byte,BinaryOccurrence.Required}})(#binary({0,1,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch48_73
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,BinaryOccurrence.Required}})(Binary.FromText("AAk=",BinaryEncoding.Base64)) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch44_12
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_13
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,(x)=>true},{1,BinaryFormat.UnsignedInteger16,(x)=>true}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert a value of type Function to type Number."]'),
    # batch44_14
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}},(k)=>BinaryFormat.Byte)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_15
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}},(k)=>BinaryFormat.Byte)(#binary({5,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_16
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}})(#binary({5,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_17
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}})(#binary({1,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_18
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch44_19
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,null)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type List."]'),
    # batch44_20
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte}},null,7)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_21
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}},null)(#binary({1,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_22
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.UnsignedInteger16}},null,#binary({1}))(#binary({1,0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_23
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},null,1)(#binary({0,9,1,8,1,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_24
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},null,1)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_25
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},(k)=>BinaryFormat.Byte,1)(#binary({0,9,1,8,1,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_26
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,(k)=>k=0}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert a value of type Function to type Number."]'),
    # batch44_27
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{0,BinaryFormat.UnsignedInteger16}})(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_28
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},null,null)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_29
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},null,null)(#binary({0,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch44_30
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte},{1,BinaryFormat.Byte}},null,0)(#binary({0,9,1,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch45_0
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_1
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,null}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Number."]'),
    # batch45_2
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{"a",BinaryFormat.Byte,1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_3
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,2}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_4
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,0}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_5
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_6
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.UnsignedInteger16,1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_7
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1}},null,0)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_8
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1}},null,1)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9]'),
    # batch45_9
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,2}},null,1)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_10
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,2}},(k)=>BinaryFormat.Byte,1)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,list:[number:8]]'),
    # batch45_11
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,2}},(k)=>BinaryFormat.Byte)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:9,list:[number:8]]'),
    # batch45_12
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,-1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value for a \'BinaryOccurrence.Type\' enumeration was not one of the allowed values: \'BinaryOccurrence.Optional, BinaryOccurrence.Required, BinaryOccurrence.Repeating\'."]'),
    # batch45_13
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1.5}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The value for a \'BinaryOccurrence.Type\' enumeration was not one of the allowed values: \'BinaryOccurrence.Optional, BinaryOccurrence.Required, BinaryOccurrence.Repeating\'."]'),
    # batch45_14
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1,2}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_15
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch45_16
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch45_17
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{1})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 1 to type List."]'),
    # batch45_18
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{0})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 0 to type List."]'),
    # batch45_19
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{0,BinaryFormat.Byte,1}})(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format group item was invalid."]'),
    # batch45_20
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,0)(#binary({0,9,1,8,2,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_21
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1}},null,0)(#binary({0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch45_22
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1}},null,0)(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch45_23
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,1)(#binary({0,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch45_24
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,1)(#binary({1,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch45_25
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,1)(#binary({1,9,0,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:5,number:9]'),
    # batch45_26
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,0)(#binary({1,9,0,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:5,number:9]'),
    # batch45_27
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,0)(#binary({1,9,1,5,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_28
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,1)(#binary({1,9,1,5,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_29
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,null)(#binary({1,9,1,5,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_30
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},(k)=>BinaryFormat.Byte,0)(#binary({1,9,1,5,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:6,number:9]'),
    # batch45_31
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},(k)=>BinaryFormat.Byte,0)(#binary({2,9,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An item was expected but didn\'t appear in the input."]'),
    # batch45_32
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,0)(#binary({2,9,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
    # batch45_33
    ('let r = try BinaryFormat.Group(BinaryFormat.Byte,{{0,BinaryFormat.Byte,1},{1,BinaryFormat.Byte,1}},null,0)(#binary({2,9,0,6})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"An unknown item was encountered in the input."]'),
]


@pytest.mark.parametrize("probe, expected", PAIRS)
def test_binary_format_group_pairs(probe: str, expected: str):
    assert evaluate_to_text(probe) == expected
