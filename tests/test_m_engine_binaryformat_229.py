"""Tests for Task 229: BinaryFormat family (Power BI answer check).

Verifies probe / answer pairs from batch 43 and batch 44.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # batch43_0
    ('BinaryFormat.UnsignedInteger16(#binary({1,2}))',
     'V:number:258'),
    # batch43_1
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({1,2}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_2
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({1,2}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_3
    ('BinaryFormat.UnsignedInteger16(#binary({255,255}))',
     'V:number:65535'),
    # batch43_4
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_5
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_6
    ('BinaryFormat.UnsignedInteger16(#binary({128,0}))',
     'V:number:32768'),
    # batch43_7
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({128,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_8
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({128,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_9
    ('BinaryFormat.UnsignedInteger16(#binary({0,128}))',
     'V:number:128'),
    # batch43_10
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_11
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_12
    ('BinaryFormat.UnsignedInteger16(#binary({1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read.'),
    # batch43_13
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_14
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_15
    ('BinaryFormat.UnsignedInteger16(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_16
    ('BinaryFormat.UnsignedInteger16(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_17
    ('BinaryFormat.UnsignedInteger16(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_18
    ('BinaryFormat.SignedInteger16(#binary({1,2}))',
     'V:number:258'),
    # batch43_19
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({1,2}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_20
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({1,2}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_21
    ('BinaryFormat.SignedInteger16(#binary({255,255}))',
     'V:number:-1'),
    # batch43_22
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_23
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_24
    ('BinaryFormat.SignedInteger16(#binary({128,0}))',
     'V:number:-32768'),
    # batch43_25
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({128,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_26
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({128,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_27
    ('BinaryFormat.SignedInteger16(#binary({0,128}))',
     'V:number:128'),
    # batch43_28
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_29
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_30
    ('BinaryFormat.SignedInteger16(#binary({1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read.'),
    # batch43_31
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_32
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_33
    ('BinaryFormat.SignedInteger16(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_34
    ('BinaryFormat.SignedInteger16(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_35
    ('BinaryFormat.SignedInteger16(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_36
    ('BinaryFormat.UnsignedInteger32(#binary({1,2,3,4}))',
     'V:number:16909060'),
    # batch43_37
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({1,2,3,4}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_38
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({1,2,3,4}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_39
    ('BinaryFormat.UnsignedInteger32(#binary({255,255,255,255}))',
     'V:number:4294967295'),
    # batch43_40
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_41
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_42
    ('BinaryFormat.UnsignedInteger32(#binary({128,0,0,0}))',
     'V:number:2147483648'),
    # batch43_43
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({128,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_44
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({128,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_45
    ('BinaryFormat.UnsignedInteger32(#binary({0,0,0,128}))',
     'V:number:128'),
    # batch43_46
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_47
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_48
    ('BinaryFormat.UnsignedInteger32(#binary({1,1,1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read.'),
    # batch43_49
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_50
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_51
    ('BinaryFormat.UnsignedInteger32(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_52
    ('BinaryFormat.UnsignedInteger32(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_53
    ('BinaryFormat.UnsignedInteger32(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_54
    ('BinaryFormat.SignedInteger32(#binary({1,2,3,4}))',
     'V:number:16909060'),
    # batch43_55
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({1,2,3,4}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_56
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({1,2,3,4}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_57
    ('BinaryFormat.SignedInteger32(#binary({255,255,255,255}))',
     'V:number:-1'),
    # batch43_58
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_59
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_60
    ('BinaryFormat.SignedInteger32(#binary({128,0,0,0}))',
     'V:number:-2147483648'),
    # batch43_61
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({128,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_62
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({128,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_63
    ('BinaryFormat.SignedInteger32(#binary({0,0,0,128}))',
     'V:number:128'),
    # batch43_64
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_65
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_66
    ('BinaryFormat.SignedInteger32(#binary({1,1,1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read.'),
    # batch43_67
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_68
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_69
    ('BinaryFormat.SignedInteger32(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_70
    ('BinaryFormat.SignedInteger32(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_71
    ('BinaryFormat.SignedInteger32(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_72
    ('BinaryFormat.UnsignedInteger64(#binary({1,2,3,4,5,6,7,8}))',
     'V:number:72623859790382856'),
    # batch43_73
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({1,2,3,4,5,6,7,8}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_74
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({1,2,3,4,5,6,7,8}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_75
    ('BinaryFormat.UnsignedInteger64(#binary({255,255,255,255,255,255,255,255}))',
     'V:number:18446744073709551615'),
    # batch43_76
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({255,255,255,255,255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_77
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({255,255,255,255,255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_78
    ('BinaryFormat.UnsignedInteger64(#binary({128,0,0,0,0,0,0,0}))',
     'V:number:9223372036854775808'),
    # batch43_79
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({128,0,0,0,0,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_80
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({128,0,0,0,0,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_81
    ('BinaryFormat.UnsignedInteger64(#binary({0,0,0,0,0,0,0,128}))',
     'V:number:128'),
    # batch43_82
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({0,0,0,0,0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_83
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({0,0,0,0,0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_84
    ('BinaryFormat.UnsignedInteger64(#binary({1,1,1,1,1,1,1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 7.  The end of the input was reached before the value could be read.'),
    # batch43_85
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({1,1,1,1,1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_86
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({1,1,1,1,1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_87
    ('BinaryFormat.UnsignedInteger64(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_88
    ('BinaryFormat.UnsignedInteger64(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_89
    ('BinaryFormat.UnsignedInteger64(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_90
    ('BinaryFormat.SignedInteger64(#binary({1,2,3,4,5,6,7,8}))',
     'V:number:72623859790382856'),
    # batch43_91
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({1,2,3,4,5,6,7,8}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_92
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({1,2,3,4,5,6,7,8}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_93
    ('BinaryFormat.SignedInteger64(#binary({255,255,255,255,255,255,255,255}))',
     'V:number:-1'),
    # batch43_94
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({255,255,255,255,255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_95
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({255,255,255,255,255,255,255,255}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_96
    ('BinaryFormat.SignedInteger64(#binary({128,0,0,0,0,0,0,0}))',
     'V:number:-9223372036854775808'),
    # batch43_97
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({128,0,0,0,0,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_98
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({128,0,0,0,0,0,0,0}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_99
    ('BinaryFormat.SignedInteger64(#binary({0,0,0,0,0,0,0,128}))',
     'V:number:128'),
    # batch43_100
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({0,0,0,0,0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_101
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({0,0,0,0,0,0,0,128}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_102
    ('BinaryFormat.SignedInteger64(#binary({1,1,1,1,1,1,1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 7.  The end of the input was reached before the value could be read.'),
    # batch43_103
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({1,1,1,1,1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_104
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({1,1,1,1,1,1,1}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_105
    ('BinaryFormat.SignedInteger64(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_106
    ('BinaryFormat.SignedInteger64(ByteOrder.LittleEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_107
    ('BinaryFormat.SignedInteger64(ByteOrder.BigEndian)(#binary({}))',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch43_108
    ('BinaryFormat.Byte(#binary({7}))',
     'V:number:7'),
    # batch43_109
    ('BinaryFormat.Byte(#binary({255,1}))',
     'V:number:255'),
    # batch43_110
    ('BinaryFormat.Byte(#binary({}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read.'),
    # batch43_111
    ('BinaryFormat.Byte(null)',
     'ERR:Expression.Error: We cannot convert the value null to type Binary.'),
    # batch43_112
    ('BinaryFormat.Byte("x")',
     'ERR:Expression.Error: We cannot convert the value "x" to type Binary.'),
    # batch43_113
    ('BinaryFormat.Single(#binary({63,128,0,0}))',
     'V:number:1'),
    # batch43_114
    ('BinaryFormat.Single(ByteOrder.LittleEndian)(#binary({0,0,128,63}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_115
    ('BinaryFormat.Single(#binary({1,2}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 2.  The end of the input was reached before the value could be read.'),
    # batch43_116
    ('BinaryFormat.Double(#binary({63,240,0,0,0,0,0,0}))',
     'V:number:1'),
    # batch43_117
    ('BinaryFormat.Double(ByteOrder.LittleEndian)(#binary({0,0,0,0,0,0,240,63}))',
     'ERR:Expression.Error: We cannot convert the value 0 to type Binary.'),
    # batch43_118
    ('BinaryFormat.Double(#binary({192,0,0,0,0,0,0,0}))',
     'V:number:-2'),
    # batch43_119
    ('BinaryFormat.Single(#binary({127,192,0,0}))',
     'V:number:NaN'),
    # batch43_120
    ('BinaryFormat.Double(#binary({127,240,0,0,0,0,0,0}))',
     'V:number:+Infinity'),
    # batch43_121
    ('BinaryFormat.Decimal(#binary({1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0}))',
     'V:number:1'),
    # batch43_122
    ('BinaryFormat.Decimal(#binary({5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0}))',
     'V:number:5'),
    # batch43_123
    ('BinaryFormat.7BitEncodedUnsignedInteger(#binary({5}))',
     'V:number:5'),
    # batch43_124
    ('BinaryFormat.7BitEncodedUnsignedInteger(#binary({128,1}))',
     'V:number:128'),
    # batch43_125
    ('BinaryFormat.7BitEncodedUnsignedInteger(#binary({255,255,3}))',
     'V:number:65535'),
    # batch43_126
    ('BinaryFormat.7BitEncodedUnsignedInteger(#binary({128}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read.'),
    # batch43_127
    ('BinaryFormat.7BitEncodedSignedInteger(#binary({127}))',
     'V:number:-64'),
    # batch43_128
    ('BinaryFormat.7BitEncodedSignedInteger(#binary({1}))',
     'V:number:-1'),
    # batch43_129
    ('BinaryFormat.7BitEncodedSignedInteger(#binary({255,255,255,255,15}))',
     'V:number:-2147483648'),
    # batch43_130
    ('BinaryFormat.Binary(2)(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'V:binary:AAA='),
    # batch43_131
    ('BinaryFormat.Binary(0)(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'V:binary:'),
    # batch43_132
    ('BinaryFormat.Binary(null)(#binary({2,9,8,7}))',
     'V:binary:AgkIBw=='),
    # batch43_133
    ('BinaryFormat.Binary()(#binary({2,9,8,7}))',
     'V:binary:AgkIBw=='),
    # batch43_134
    ('BinaryFormat.Binary(-1)(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'ERR:Expression.Error: The length cannot be negative.'),
    # batch43_136
    ('BinaryFormat.Binary(2.5)(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'ERR:Expression.Error: The number is out of range of a 32 bit integer value.'),
    # batch43_137
    ('BinaryFormat.Binary("a")(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'ERR:Expression.Error: We cannot convert the value "a" to type Number.'),
    # batch43_138
    ('BinaryFormat.Binary(BinaryFormat.Byte)(#binary({2,9,8,7}))',
     'V:binary:CQg='),
    # batch43_139
    ('BinaryFormat.Binary(BinaryFormat.UnsignedInteger16)(#binary({0,2,9,8,7}))',
     'V:binary:CQg='),
    # batch43_140
    ('BinaryFormat.Length(BinaryFormat.Byte,1)(#binary({7,8}))',
     'V:number:7'),
    # batch43_141
    ('BinaryFormat.Length(BinaryFormat.UnsignedInteger16,1)(#binary({7,8}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read.'),
    # batch43_142
    ('BinaryFormat.Length(BinaryFormat.UnsignedInteger16,3)(#binary({0,7,8}))',
     'V:number:7'),
    # batch43_143
    ('BinaryFormat.Length(BinaryFormat.Byte,5)(#binary({7,8}))',
     'V:number:7'),
    # batch43_144
    ('BinaryFormat.Length(BinaryFormat.Byte,BinaryFormat.Byte)(#binary({1,7,8}))',
     'V:number:7'),
    # batch43_145
    ('BinaryFormat.Text(2)(#binary({65,66,67}))',
     'V:text:"AB"'),
    # batch43_146
    ('BinaryFormat.Text(2,TextEncoding.Utf8)(#binary({65,66,67}))',
     'V:text:"AB"'),
    # batch43_147
    ('BinaryFormat.Text(4,TextEncoding.Utf16)(#binary({65,0,66,0}))',
     'V:text:"AB"'),
    # batch43_148
    ('BinaryFormat.Text(4,TextEncoding.Unicode)(#binary({65,0,66,0}))',
     'V:text:"AB"'),
    # batch43_149
    ('BinaryFormat.Text(4,TextEncoding.BigEndianUnicode)(#binary({0,65,0,66}))',
     'V:text:"AB"'),
    # batch43_150
    ('BinaryFormat.Text(2,TextEncoding.Ascii)(#binary({65,200}))',
     'V:text:"A?"'),
    # batch43_151
    ('BinaryFormat.Text(2,TextEncoding.Windows)(#binary({65,200}))',
     'V:text:"AÈ"'),
    # batch43_152
    ('BinaryFormat.Text(2,TextEncoding.Utf8)(#binary({195,169}))',
     'V:text:"é"'),
    # batch43_153
    ('BinaryFormat.Text(1,TextEncoding.Utf8)(#binary({195,169}))',
     'V:text:"�"'),
    # batch43_154
    ('BinaryFormat.Text(2,1252)(#binary({65,233}))',
     'V:text:"Aé"'),
    # batch43_155
    ('BinaryFormat.Text(2,65001)(#binary({195,169}))',
     'V:text:"é"'),
    # batch43_156
    ('BinaryFormat.Text(0)(#binary({65}))',
     'V:text:""'),
    # batch43_157
    ('BinaryFormat.Text(null)(#binary({1,65,66}))',
     'ERR:Expression.Error: We cannot convert the value null to type Number.'),
    # batch43_158
    ('BinaryFormat.Text(BinaryFormat.Byte)(#binary({2,65,66,67}))',
     'V:text:"AB"'),
    # batch43_159
    ('BinaryFormat.Text(5)(#binary({65,66}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 2.  The end of the input was reached before the value could be read.'),
    # batch43_160
    ('BinaryFormat.Text(3,TextEncoding.Utf8)(#binary({255,254,253}))',
     "ERR:DataFormat.Error: The unicode byte order marks didn't match the specified encoding."),
    # batch43_161
    ('BinaryFormat.List(BinaryFormat.Byte)(#binary({1,2,3}))',
     'V:list:[number:1,number:2,number:3]'),
    # batch43_162
    ('BinaryFormat.List(BinaryFormat.Byte,2)(#binary({1,2,3}))',
     'V:list:[number:1,number:2]'),
    # batch43_163
    ('BinaryFormat.List(BinaryFormat.Byte,0)(#binary({1,2,3}))',
     'V:list:[]'),
    # batch43_165
    ('BinaryFormat.List(BinaryFormat.UnsignedInteger16)(#binary({0,1,0,2}))',
     'V:list:[number:1,number:2]'),
    # batch43_167
    ('BinaryFormat.List(BinaryFormat.Byte,each _ <> 3)(#binary({1,2,3,4}))',
     'V:list:[number:1,number:2,number:3]'),
    # batch43_169
    ('BinaryFormat.List(BinaryFormat.Byte)(#binary({}))',
     'V:list:[]'),
    # batch43_170
    ('BinaryFormat.List(BinaryFormat.Byte,BinaryFormat.Byte)(#binary({2,1,2,3}))',
     'V:list:[number:1,number:2]'),
    # batch43_171
    ('BinaryFormat.List(BinaryFormat.Byte,-1)(#binary({1,2,3}))',
     "ERR:Expression.Error: The 'count' parameter cannot be negative."),
    # batch43_172
    ('BinaryFormat.List(BinaryFormat.Byte,null)(#binary({1,2,3}))',
     'V:list:[number:1,number:2,number:3]'),
    # batch43_173
    ('BinaryFormat.List(BinaryFormat.Byte,1.5)(#binary({1,2,3}))',
     'ERR:Expression.Error: The number is out of range of a 64 bit integer value.'),
    # batch43_174
    ('BinaryFormat.List(BinaryFormat.Byte,"a")(#binary({1,2,3}))',
     "ERR:Expression.Error: The 'countOrCondition' parameter must be either a number or function."),
    # batch43_175
    ('BinaryFormat.Null(#binary({1}))',
     'V:null'),
    # batch43_176
    ('BinaryFormat.Null(#binary({}))',
     'V:null'),
    # batch43_177
    ('BinaryFormat.Null(null)',
     'ERR:Expression.Error: We cannot convert the value null to type Binary.'),
    # batch43_178
    ('BinaryFormat.Transform(BinaryFormat.Byte, each _ * 2)(#binary({5}))',
     'V:number:10'),
    # batch43_179
    ('BinaryFormat.Transform(BinaryFormat.UnsignedInteger16, each _ + 1)(#binary({0,5}))',
     'V:number:6'),
    # batch43_180
    ('BinaryFormat.Transform(BinaryFormat.Byte, null)(#binary({5}))',
     'ERR:Expression.Error: We cannot convert the value null to type Function.'),
    # batch43_181
    ('BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.LittleEndian)(#binary({1,2}))',
     'V:number:513'),
    # batch43_182
    ('BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.BigEndian)(#binary({1,2}))',
     'V:number:258'),
    # batch43_183
    ('BinaryFormat.ByteOrder(BinaryFormat.Byte,ByteOrder.LittleEndian)(#binary({1,2}))',
     'V:number:1'),
    # batch43_184
    ('BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,5)(#binary({1,2}))',
     "ERR:Expression.Error: The value for a 'ByteOrder.Type' enumeration was not one of the allowed values: 'ByteOrder.LittleEndian, ByteOrder.BigEndian'."),
    # batch43_185
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.UnsignedInteger16])(#binary({1,0,2,9}))',
     'V:record:["a"=number:1,"b"=number:2]'),
    # batch43_186
    ('BinaryFormat.Record([])(#binary({1}))',
     'V:record:[]'),
    # batch43_187
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Byte])(#binary({1}))',
     'ERR:DataFormat.Error: There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read.'),
    # batch43_188
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Text(2)])(#binary({1,65,66}))',
     'V:record:["a"=number:1,"b"=text:"AB"]'),
    # batch43_189
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Text(each [a])])(#binary({2,65,66,67}))',
     'ERR:Expression.Error: We cannot convert a value of type Function to type Number.'),
    # batch43_190
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Binary(each [a])])(#binary({2,65,66,67}))',
     'ERR:Expression.Error: We cannot convert a value of type Function to type Number.'),
    # batch43_191
    ('BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.List(BinaryFormat.Byte,each [a])])(#binary({2,65,66,67}))',
     'ERR:Expression.Error: We cannot apply field access to the type Number.'),
    # batch43_192
    ('BinaryFormat.Record([a=1])(#binary({1}))',
     'V:record:["a"=number:1]'),
    # batch43_193
    ('BinaryFormat.Record(null)(#binary({1}))',
     'ERR:Expression.Error: We cannot convert the value null to type Record.'),
    # batch43_194
    ('BinaryFormat.Record({BinaryFormat.Byte})(#binary({1}))',
     'ERR:Expression.Error: We cannot convert a value of type List to type Record.'),
    # batch43_196
    ('BinaryFormat.Choice(BinaryFormat.Byte, each if _ = 1 then BinaryFormat.Byte else BinaryFormat.UnsignedInteger16)(#binary({1,9}))',
     'V:number:9'),
    # batch43_197
    ('BinaryFormat.Choice(BinaryFormat.Byte, each if _ = 1 then BinaryFormat.Byte else BinaryFormat.UnsignedInteger16)(#binary({2,0,9}))',
     'V:number:9'),
    # batch43_198
    ('BinaryFormat.Choice(BinaryFormat.Byte, each BinaryFormat.Null)(#binary({2,0,9}))',
     'V:null'),
    # batch43_199
    ('BinaryFormat.Choice(BinaryFormat.Byte, each BinaryFormat.Byte, type number)(#binary({2,5}))',
     'ERR:Expression.Error: We expected type List, Binary, or Any.'),
    # batch43_200
    ('BinaryFormat.Choice(BinaryFormat.Byte, each 5)(#binary({2,5}))',
     "ERR:Expression.Error: The value isn't a binary format value."),
    # batch44_4
    ('let r = try BinaryFormat.UnsignedInteger16(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch44_5
    ('let r = try BinaryFormat.UnsignedInteger32(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch44_6
    ('let r = try BinaryFormat.Byte(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read."]'),
    # batch44_7
    ('let r = try BinaryFormat.Double(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch44_8
    ('let r = try BinaryFormat.Decimal(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch44_9
    ('let r = try BinaryFormat.Text(5)(#binary({65,66})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 2.  The end of the input was reached before the value could be read."]'),
    # batch44_10
    ('let r = try BinaryFormat.Text(2,TextEncoding.Utf16)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch44_11
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Byte])(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch44_31
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, each BinaryFormat.Byte, type number)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We expected type List, Binary, or Any."]'),
    # batch44_34
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, each BinaryFormat.Byte, type any)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:5'),
    # batch44_35
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, each BinaryFormat.Byte, null)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:5'),
    # batch44_36
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, (n)=>BinaryFormat.List(BinaryFormat.Byte,n), type list)(#binary({2,5,6,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:5,number:6]'),
    # batch44_37
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, (n)=>BinaryFormat.Binary(n))(#binary({2,5,6,7})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:binary:BQY='),
    # batch44_38
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, (n)=>BinaryFormat.Text(n))(#binary({2,65,66,67})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AB"'),
    # batch44_39
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, (n)=>BinaryFormat.Record([x=BinaryFormat.Byte]))(#binary({2,65,66,67})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["x"=number:65]'),
    # batch44_40
    ('let r = try BinaryFormat.Choice(null, each BinaryFormat.Byte)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch44_41
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, null)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch44_42
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte)(#binary({2,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects between 2 and 4."]'),
    # batch44_43
    ('let r = try BinaryFormat.Choice(BinaryFormat.Byte, (n)=>BinaryFormat.Byte)(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read."]'),
    # batch44_44
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte,b=BinaryFormat.Record([c=BinaryFormat.Byte,d=BinaryFormat.Byte])])(#binary({1,2,3,4})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=number:1,"b"=record:["c"=number:2,"d"=number:3]]'),
    # batch44_45
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte,a=BinaryFormat.Byte])(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"Duplicate field named \'a\'."]'),
    # batch44_46
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Null,b=BinaryFormat.Byte])(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=null,"b"=number:1]'),
    # batch44_47
    ('let r = try BinaryFormat.Record([a=BinaryFormat.List(BinaryFormat.Byte,2),b=BinaryFormat.Byte])(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=list:[number:1,number:2],"b"=number:3]'),
    # batch44_48
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte, b=null])(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=number:1,"b"=null]'),
    # batch44_49
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte, b="x"])(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=number:1,"b"=text:"x"]'),
    # batch44_50
    ('let r = try BinaryFormat.Record([a=BinaryFormat.Byte, b=1])(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=number:1,"b"=number:1]'),
    # batch44_51
    ('let r = try BinaryFormat.Length(BinaryFormat.Text(2),3)(#binary({65,66,67})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AB"'),
    # batch44_52
    ('let r = try BinaryFormat.Length(BinaryFormat.Text(5),3)(#binary({65,66,67})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 3.  The end of the input was reached before the value could be read."]'),
    # batch44_53
    ('let r = try BinaryFormat.Length(BinaryFormat.Binary(),3)(#binary({1,66,67})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:binary:AUJD'),
    # batch44_54
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte,0)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read."]'),
    # batch44_55
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte,-1)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The length cannot be negative."]'),
    # batch44_56
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte,null)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Number."]'),
    # batch44_57
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects 2."]'),
    # batch44_58
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte,1.5)(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The number is out of range of a 64 bit integer value."]'),
    # batch44_59
    ('let r = try BinaryFormat.Length(BinaryFormat.Byte,"a")(#binary({7,8})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value \\"a\\" to type Number."]'),
    # batch44_60
    ('let r = try BinaryFormat.Length(BinaryFormat.List(BinaryFormat.Byte),3)(#binary({7,8,9,10})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:7,number:8,number:9]'),
    # batch44_61
    ('let r = try BinaryFormat.Length(BinaryFormat.Null,3)(#binary({7,8,9,10})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:null'),
    # batch44_62
    ('let r = try BinaryFormat.List(BinaryFormat.Text(2),2)(#binary({65,66,67,68,69})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"AB",text:"CD"]'),
    # batch44_63
    ('let r = try BinaryFormat.List(BinaryFormat.Record([a=BinaryFormat.Byte]),2)(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[record:["a"=number:1],record:["a"=number:2]]'),
    # batch44_64
    ('let r = try BinaryFormat.List(BinaryFormat.List(BinaryFormat.Byte,2),2)(#binary({1,2,3,4,5})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[list:[number:1,number:2],list:[number:3,number:4]]'),
    # batch44_65
    ('let r = try BinaryFormat.List(BinaryFormat.Byte,each _ = 1)(#binary({1,1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:1,number:1,number:2]'),
    # batch44_67
    ('let r = try BinaryFormat.List(BinaryFormat.Byte,each false)(#binary({1,1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:1]'),
    # batch44_70
    ('let r = try BinaryFormat.List(null,2)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch44_71
    ('let r = try BinaryFormat.List(1,2)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value 1 to type Function."]'),
    # batch44_72
    ('let r = try BinaryFormat.List(BinaryFormat.Byte,2,3)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"3 arguments were passed to a function which expects between 1 and 2."]'),
    # batch44_73
    ('let r = try BinaryFormat.Transform(BinaryFormat.Byte, (x)=>x*2, 1)(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"3 arguments were passed to a function which expects 2."]'),
    # batch44_74
    ('let r = try BinaryFormat.Transform(null, each _)(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch44_75
    ('let r = try BinaryFormat.Transform(BinaryFormat.Byte, each error "boom")(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"boom"]'),
    # batch44_76
    ('let r = try BinaryFormat.Transform(BinaryFormat.Binary(2), each Binary.Length(_))(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:2'),
    # batch44_77
    ('let r = try BinaryFormat.Transform(BinaryFormat.Text(2), each Text.Upper(_))(#binary({97,98})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AB"'),
    # batch44_78
    ('let r = try BinaryFormat.Text(1,TextEncoding.Utf8)(#binary({239,187,191})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"�"'),
    # batch44_79
    ('let r = try BinaryFormat.Text(3,TextEncoding.Utf8)(#binary({239,187,191})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:""'),
    # batch44_80
    ('let r = try BinaryFormat.Text(4,TextEncoding.Utf8)(#binary({239,187,191,65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_81
    ('let r = try BinaryFormat.Text(2,TextEncoding.Utf16)(#binary({255,254})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:""'),
    # batch44_82
    ('let r = try BinaryFormat.Text(4,TextEncoding.Utf16)(#binary({255,254,65,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_83
    ('let r = try BinaryFormat.Text(4,TextEncoding.Utf16)(#binary({254,255,0,65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"The unicode byte order marks didn\'t match the specified encoding."]'),
    # batch44_84
    ('let r = try BinaryFormat.Text(3,TextEncoding.Utf16)(#binary({65,0,66})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A�"'),
    # batch44_85
    ('let r = try BinaryFormat.Text(2,TextEncoding.Utf8)(#binary({255,66})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"�B"'),
    # batch44_86
    ('let r = try BinaryFormat.Text(2,TextEncoding.Utf8)(#binary({192,128})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"��"'),
    # batch44_87
    ('let r = try BinaryFormat.Text(-1)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The length cannot be negative."]'),
    # batch44_88
    ('let r = try BinaryFormat.Text(1.5)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The number is out of range of a 32 bit integer value."]'),
    # batch44_89
    ('let r = try BinaryFormat.Text(1,99999)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The text encoding is invalid."]'),
    # batch44_90
    ('let r = try BinaryFormat.Text(1,0)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_91
    ('let r = try BinaryFormat.Text(1,"utf-8")(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value \\"utf-8\\" to type Number."]'),
    # batch44_92
    ('let r = try BinaryFormat.Text(1,null)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_93
    ('let r = try BinaryFormat.Text(2,TextEncoding.Utf32)(#binary({65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The import TextEncoding.Utf32 matches no exports. Did you miss a module reference?"]'),
    # batch44_94
    ('let r = try BinaryFormat.Text(4,TextEncoding.Utf7)(#binary({65,66,67,68})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The import TextEncoding.Utf7 matches no exports. Did you miss a module reference?"]'),
    # batch44_95
    ('let r = try BinaryFormat.Text(2,28591)(#binary({65,233})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"Aé"'),
    # batch44_96
    ('let r = try BinaryFormat.Text(2,437)(#binary({65,233})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AΘ"'),
    # batch44_97
    ('let r = try BinaryFormat.Text(2,850)(#binary({65,233})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AÚ"'),
    # batch44_98
    ('let r = try BinaryFormat.Text(4,12000)(#binary({65,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_99
    ('let r = try BinaryFormat.Text(4,12001)(#binary({0,0,0,65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_100
    ('let r = try BinaryFormat.Text(2,1200)(#binary({65,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_101
    ('let r = try BinaryFormat.Text(2,1201)(#binary({0,65})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"A"'),
    # batch44_102
    ('let r = try BinaryFormat.Binary(#binary({1}))(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert a value of type Binary to type Number."]'),
    # batch44_104
    ('let r = try BinaryFormat.Binary(BinaryFormat.Byte)(#binary({0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:binary:'),
    # batch44_105
    ('let r = try BinaryFormat.Binary(BinaryFormat.SignedInteger16)(#binary({255,255,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"The specified binary format value cannot be used to read a length."]'),
    # batch44_106
    ('let r = try BinaryFormat.Binary(true)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value true to type Number."]'),
    # batch44_107
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.SignedInteger32,ByteOrder.LittleEndian)(#binary({1,0,0,128})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-2147483647'),
    # batch44_108
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Double,ByteOrder.LittleEndian)(#binary({0,0,0,0,0,0,240,63})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1'),
    # batch44_109
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Single,ByteOrder.LittleEndian)(#binary({0,0,128,63})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1'),
    # batch44_110
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Decimal,ByteOrder.LittleEndian)(#binary({1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1'),
    # batch44_111
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Decimal,ByteOrder.BigEndian)(#binary({1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1'),
    # batch44_112
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Text(2),ByteOrder.LittleEndian)(#binary({65,66})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:text:"AB"'),
    # batch44_113
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.List(BinaryFormat.UnsignedInteger16,2),ByteOrder.LittleEndian)(#binary({1,0,2,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[number:1,number:2]'),
    # batch44_114
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.Record([a=BinaryFormat.UnsignedInteger16,b=BinaryFormat.UnsignedInteger16]),ByteOrder.LittleEndian)(#binary({1,0,2,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:record:["a"=number:1,"b"=number:2]'),
    # batch44_115
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.BigEndian),ByteOrder.LittleEndian)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:258'),
    # batch44_116
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.LittleEndian),ByteOrder.BigEndian)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:513'),
    # batch44_117
    ('let r = try BinaryFormat.ByteOrder(null,ByteOrder.LittleEndian)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Function."]'),
    # batch44_118
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,null)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Number."]'),
    # batch44_119
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16)(#binary({1,2})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"1 arguments were passed to a function which expects 2."]'),
    # batch44_120
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.LittleEndian)(null) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"Expression.Error",text:"We cannot convert the value null to type Binary."]'),
    # batch44_121
    ('let r = try BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16,ByteOrder.LittleEndian)(#binary({1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 1.  The end of the input was reached before the value could be read."]'),
    # batch44_122
    ('let r = try BinaryFormat.SignedInteger16(#binary({255,255})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-1'),
    # batch44_123
    ('let r = try BinaryFormat.SignedInteger16(#binary({128,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-32768'),
    # batch44_124
    ('let r = try BinaryFormat.SignedInteger32(#binary({255,255,255,255})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-1'),
    # batch44_125
    ('let r = try BinaryFormat.SignedInteger64(#binary({255,255,255,255,255,255,255,255})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-1'),
    # batch44_126
    ('let r = try BinaryFormat.SignedInteger64(#binary({255,255,255,255,255,255,255,254})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-2'),
    # batch44_127
    ('let r = try BinaryFormat.SignedInteger64(#binary({0,0,0,0,0,0,1,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:256'),
    # batch44_128
    ('let r = try BinaryFormat.UnsignedInteger32(#binary({0,0,1,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:256'),
    # batch44_129
    ('let r = try BinaryFormat.UnsignedInteger32(#binary({255,255,255,255})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:4294967295'),
    # batch44_130
    ('let r = try BinaryFormat.UnsignedInteger64(#binary({0,0,0,0,0,1,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:65536'),
    # batch44_131
    ('let r = try BinaryFormat.SignedInteger32(#binary({0,0,0,5,9})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:5'),
    # batch44_132
    ('let r = try BinaryFormat.SignedInteger16(#binary({1,2,3})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:258'),
    # batch44_133
    ('let r = try BinaryFormat.7BitEncodedUnsignedInteger(#binary({255,255,255,255,15})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:4294967295'),
    # batch44_134
    ('let r = try BinaryFormat.7BitEncodedUnsignedInteger(#binary({255,255,255,255,255,255,255,255,255,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:18446744073709551615'),
    # batch44_135
    ('let r = try BinaryFormat.7BitEncodedUnsignedInteger(#binary({255,255,255,255,255,255,255,255,255,255,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format.  The 7-bit encoded integer was greater than 63 bits."]'),
    # batch44_136
    ('let r = try BinaryFormat.7BitEncodedUnsignedInteger(#binary({0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0'),
    # batch44_137
    ('let r = try BinaryFormat.7BitEncodedUnsignedInteger(#binary({})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 0.  The end of the input was reached before the value could be read."]'),
    # batch44_138
    ('let r = try BinaryFormat.7BitEncodedSignedInteger(#binary({0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0'),
    # batch44_139
    ('let r = try BinaryFormat.7BitEncodedSignedInteger(#binary({128,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:64'),
    # batch44_140
    ('let r = try BinaryFormat.7BitEncodedSignedInteger(#binary({255,127})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-8192'),
    # batch44_141
    ('let r = try BinaryFormat.7BitEncodedSignedInteger(#binary({128,128,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:8192'),
    # batch44_142
    ('let r = try BinaryFormat.Single(#binary({255,128,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-Infinity'),
    # batch44_143
    ('let r = try BinaryFormat.Single(#binary({0,0,0,1})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1.4012984643248171E-45'),
    # batch44_144
    ('let r = try BinaryFormat.Single(#binary({63,192,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:1.5'),
    # batch44_145
    ('let r = try BinaryFormat.Single(#binary({64,73,15,219})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:3.1415927410125732'),
    # batch44_146
    ('let r = try BinaryFormat.Double(#binary({64,9,33,251,84,68,45,24})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:3.1415926535897931'),
    # batch44_147
    ('let r = try BinaryFormat.Double(#binary({255,240,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-Infinity'),
    # batch44_148
    ('let r = try BinaryFormat.Double(#binary({127,248,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:NaN'),
    # batch44_149
    ('let r = try BinaryFormat.Double(#binary({128,0,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0'),
    # batch44_150
    ('let r = try BinaryFormat.Decimal(#binary({0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0'),
    # batch44_151
    ('let r = try BinaryFormat.Decimal(#binary({1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,128})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:-1'),
    # batch44_152
    ('let r = try BinaryFormat.Decimal(#binary({1,0,0,0,0,0,0,0,0,0,0,0,0,0,2,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:0.01'),
    # batch44_153
    ('let r = try BinaryFormat.Decimal(#binary({15,39,0,0,0,0,0,0,0,0,0,0,0,0,2,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:number:99.99'),
    # batch44_154
    ('let r = try BinaryFormat.Decimal(#binary({1,0,0,0})) in if r[HasError] then {"E", r[Error][Reason], r[Error][Message]} else r[Value]',
     'V:list:[text:"E",text:"DataFormat.Error",text:"There was a problem reading the binary format at position 4.  The end of the input was reached before the value could be read."]'),
    # Task 229 fix: zero-width List loop refusals
    ('BinaryFormat.List(BinaryFormat.Null)(#binary({1}))',
     'ERR:Expression.Error: The zero-width binary format list item is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Binary(0))(#binary({1}))',
     'ERR:Expression.Error: The zero-width binary format list item is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Text(0))(#binary({1}))',
     'ERR:Expression.Error: The zero-width binary format list item is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Record([]))(#binary({1}))',
     'ERR:Expression.Error: The zero-width binary format list item is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Null, 2000000000)(#binary({1}))',
     'ERR:Expression.Error: The binary format list count exceeds limit is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Null, 9e18)(#binary({1}))',
     'ERR:Expression.Error: The binary format list count exceeds limit is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Null, each true)(#binary({1}))',
     'ERR:Expression.Error: The zero-width binary format list item is not supported by this engine yet.'),
    # Task 229 fix: unmeasured shapes refused
    ('BinaryFormat.List(BinaryFormat.Byte,5)(#binary({1,2,3}))',
     'ERR:Expression.Error: The binary format reading past end of input is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.UnsignedInteger16)(#binary({0,1,0}))',
     'ERR:Expression.Error: The binary format reading past end of input is not supported by this engine yet.'),
    ('BinaryFormat.Binary(20)(#binary({0,0,0,0,0,0,1,2,3,4,5,6,7,8,9,10}))',
     'ERR:Expression.Error: The binary format reading past end of input is not supported by this engine yet.'),
    ('BinaryFormat.Binary(BinaryFormat.Byte)(#binary({5,1,2}))',
     'ERR:Expression.Error: The binary format reading past end of input is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, each true)(#binary({1,1,2,3}))',
     'ERR:Expression.Error: The binary format predicate never turned false is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, each null)(#binary({1,1,2,3}))',
     'ERR:Expression.Error: The binary format predicate never turned false is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, each 1)(#binary({1,1,2,3}))',
     'ERR:Expression.Error: The binary format predicate never turned false is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, each _ <> 9)(#binary({1,2,3,4}))',
     'ERR:Expression.Error: The binary format predicate never turned false is not supported by this engine yet.'),
    ('BinaryFormat.Record([a=each 5])(#binary({1}))',
     'ERR:Expression.Error: The binary format function in record is not supported by this engine yet.'),
    ('BinaryFormat.Choice(BinaryFormat.Text(2), each BinaryFormat.Byte)(#binary({65,66}))',
     'ERR:Expression.Error: The binary format choice length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.Choice(BinaryFormat.Record([]), each BinaryFormat.Byte)(#binary({}))',
     'ERR:Expression.Error: The binary format choice length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.Choice(BinaryFormat.Null, each BinaryFormat.Byte)(#binary({}))',
     'ERR:Expression.Error: The binary format choice length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.Binary(BinaryFormat.Text(2))(#binary({65,66}))',
     'ERR:Expression.Error: The binary format binary length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.Binary(BinaryFormat.Record([]))(#binary({}))',
     'ERR:Expression.Error: The binary format binary length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.Binary(BinaryFormat.Null)(#binary({}))',
     'ERR:Expression.Error: The binary format binary length format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, BinaryFormat.Text(2))(#binary({65,66}))',
     'ERR:Expression.Error: The binary format list count format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, BinaryFormat.Record([]))(#binary({}))',
     'ERR:Expression.Error: The binary format list count format of unsupported kind is not supported by this engine yet.'),
    ('BinaryFormat.List(BinaryFormat.Byte, BinaryFormat.Null)(#binary({}))',
     'ERR:Expression.Error: The binary format list count format of unsupported kind is not supported by this engine yet.'),
    # Task 229 fix: scoped lexer checks
    ('x.1b',
     "ERR:SYNTAX: Unexpected token after the end of the expression, found '.1'"),
    ('a.1e1',
     "ERR:SYNTAX: Unexpected token after the end of the expression, found '.1e1'"),
    ('BinaryFormat.7BitEncodedUnsignedInteger(#binary({1}))',
     'V:number:1'),
    ('BinaryFormat.7BitEncodedSignedInteger(#binary({1}))',
     'V:number:-1'),
]


@pytest.mark.parametrize("probe, expected", PAIRS)
def test_m_engine_binaryformat_229(probe, expected):
    assert evaluate_to_text(probe) == expected
