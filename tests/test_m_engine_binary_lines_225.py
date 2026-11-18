"""Tests for Task 225: Binary compress/buffer/approx-length, Lines.FromBinary/ToBinary,
List.Random, Table.PartitionKey/PartitionValues, and Type.TablePartitionKey.

Verifies probe / answer pairs from batch 34 and batch 35.
"""

import pytest
from analytics_studio.m_engine import evaluate_to_text

PAIRS = [
    # batch34_0
    ('Binary.Length(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64))',
     'V:number:5'),
    # batch34_1
    ('Binary.ApproximateLength(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64))',
     'V:number:5'),
    # batch34_2
    ('Binary.ApproximateLength(Text.ToBinary(""))',
     'V:number:0'),
    # batch34_3
    ('Binary.ApproximateLength(null)',
     'V:null'),
    # batch34_4
    ('Binary.ToText(Binary.Buffer(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64)), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch34_5
    ('Binary.Buffer(null)',
     'V:null'),
    # batch34_6
    ('Binary.Buffer(1)',
     'ERR:Expression.Error: We cannot convert the value 1 to type Binary.'),
    # batch34_7
    ('Binary.ToText(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b0800000000000400f348cdc9c907008289d1f705000000"'),
    # batch34_8
    ('Binary.ToText(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"f348cdc9c90700"'),
    # batch34_9
    ('Binary.ToText(Binary.Decompress(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), Compression.GZip), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch34_10
    ('Binary.ToText(Binary.Decompress(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), Compression.Deflate), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch34_11
    ('Binary.ToText(Binary.Decompress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), Compression.GZip), BinaryEncoding.Hex)',
     'ERR:DataFormat.Error: Found invalid data while decoding.'),
    # batch34_12
    ('Binary.Length(Binary.Compress(Binary.FromText(Text.Repeat("AB", 500), BinaryEncoding.Base64), Compression.GZip))',
     'V:number:29'),
    # batch34_13
    ('Compression.GZip',
     'V:number:0'),
    # batch34_14
    ('Compression.Deflate',
     'V:number:1'),
    # batch34_15
    ('Binary.ToText(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), 5), BinaryEncoding.Hex)',
     "ERR:Expression.Error: We don't support that type of compression in this context."),
    # batch34_16
    ('Binary.ToText(Binary.Compress(Binary.FromText("SGVsbG8=", BinaryEncoding.Base64), null), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value null to type Number.'),
    # batch34_17
    ('Binary.Compress("x", Compression.GZip)',
     'ERR:Expression.Error: We cannot convert the value "x" to type Binary.'),
    # batch34_22
    ('Lines.FromBinary(Text.ToBinary(""))',
     'V:list:[]'),
    # batch34_23
    ('Lines.FromBinary(Text.ToBinary("a#(lf)"))',
     'V:list:[text:"a"]'),
    # batch34_24
    ('Lines.FromBinary(Text.ToBinary("a#(lf)"), true)',
     'ERR:Expression.Error: The specified QuoteStyle is invalid.'),
    # batch34_25
    ('Lines.FromBinary(Text.ToBinary("a#(lf)#(lf)"), true)',
     'ERR:Expression.Error: The specified QuoteStyle is invalid.'),
    # batch34_26
    ('Lines.FromBinary(Text.ToBinary("a"), null, null, TextEncoding.Utf8)',
     'V:list:[text:"a"]'),
    # batch34_27
    ('Lines.FromBinary(Text.ToBinary("a,b"), null, null, 65001)',
     'V:list:[text:"a,b"]'),
    # batch34_28
    ('Lines.FromBinary(Binary.FromText("//5hAAoAYgA=", BinaryEncoding.Base64))',
     'V:list:[text:"a",text:"b"]'),
    # batch34_29
    ('Lines.FromBinary(Binary.FromText("//5hAAoAYgA=", BinaryEncoding.Base64), null, null, TextEncoding.Unicode)',
     'V:list:[text:"a",text:"b"]'),
    # batch34_30
    ('Binary.ToText(Lines.ToBinary({"a","b"}), BinaryEncoding.Hex)',
     'V:text:"610d0a620d0a"'),
    # batch34_31
    ('Binary.ToText(Lines.ToBinary({"a","b"}, "#(cr)#(lf)"), BinaryEncoding.Hex)',
     'V:text:"610d0a620d0a"'),
    # batch34_32
    ('Binary.ToText(Lines.ToBinary({"a","b"}, "|", null, true), BinaryEncoding.Hex)',
     'V:text:"efbbbf617c627c"'),
    # batch34_33
    ('Binary.ToText(Lines.ToBinary({"a","b"}, null, TextEncoding.Utf16), BinaryEncoding.Hex)',
     'V:text:"61000d000a0062000d000a00"'),
    # batch34_34
    ('Binary.ToText(Lines.ToBinary({}), BinaryEncoding.Hex)',
     'V:text:""'),
    # batch34_35
    ('Binary.ToText(Lines.ToBinary({"é"}), BinaryEncoding.Hex)',
     'V:text:"c3a90d0a"'),
    # batch34_36
    ('Binary.ToText(Lines.ToBinary({"é"}, null, TextEncoding.Windows), BinaryEncoding.Hex)',
     'V:text:"e90d0a"'),
    # batch34_37
    ('Binary.ToText(Lines.ToBinary({1}), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value 1 to type Text.'),
    # batch34_38
    ('Binary.ToText(Lines.ToBinary({null,"a"}), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value null to type Text.'),
    # batch34_39
    ('Binary.ToText(Lines.ToBinary("a"), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value "a" to type List.'),
    # batch34_40
    ('Binary.ToText(Lines.ToBinary({"a"}, "", null, true), BinaryEncoding.Hex)',
     'V:text:"efbbbf61"'),
    # batch34_43
    ('Table.PartitionKey(#table({"A"},{{1}}))',
     'V:null'),
    # batch34_44
    ('Table.PartitionValues(#table({"A"},{{1}}))',
     'V:table:cols=[];rows=[list:[]]'),
    # batch34_45
    ('Type.TablePartitionKey(type table [A=number])',
     'V:null'),
    # batch34_54
    ('List.Random(0)',
     'V:list:[]'),
    # batch34_55
    ('List.Random(3, 1)',
     'V:list:[number:0.24866858415709278,number:0.11074397718102856,number:0.46701067987224587]'),
    # batch34_56
    ('List.Random(-1)',
     "ERR:Expression.Error: The 'count' argument is out of range."),
    # batch34_57
    ('List.Random(null)',
     'ERR:Expression.Error: We cannot convert the value null to type Number.'),
    # batch34_58
    ('List.Count(List.Random(5))',
     'V:number:5'),
    # batch34_59
    ('List.Max(List.Random(50)) < 1',
     'V:true'),
    # batch34_60
    ('List.Min(List.Random(50)) >= 0',
     'V:true'),
    # batch34_66
    ('DateTimeZone.FromFileTime(null)',
     'V:null'),
    # batch34_67
    ('DateTimeZone.FromFileTime("x")',
     'ERR:Expression.Error: We cannot convert the value "x" to type Number.'),
    # batch35_0
    ('Binary.ToText(Binary.Compress(Text.ToBinary("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"4b4ca43d0000"'),
    # batch35_1
    ('Binary.ToText(Binary.Compress(Text.ToBinary("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b08000000000004004b4ca43d0000647a70af64000000"'),
    # batch35_2
    ('Binary.ToText(Binary.Compress(Text.ToBinary("abcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabc"), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"4b4c4a4e1c6a0800"'),
    # batch35_3
    ('Binary.ToText(Binary.Compress(Text.ToBinary("abcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabcabc"), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b08000000000004004b4c4a4e1c6a080064353521b4000000"'),
    # batch35_4
    ('Binary.ToText(Binary.Compress(Text.ToBinary("The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. "), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"0bc94855282ccd4cce56482aca2fcf5348cbaf50c82acd2d2856c82f4b2d5228014ae72456552aa4e4a7eb29848c2a26573100"'),
    # batch35_5
    ('Binary.ToText(Binary.Compress(Text.ToBinary("The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog. "), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b08000000000004000bc94855282ccd4cce56482aca2fcf5348cbaf50c82acd2d2856c82f4b2d5228014ae72456552aa4e4a7eb29848c2a26573100bb160fe368010000"'),
    # batch35_6
    ('Binary.ToText(Binary.Compress(Text.ToBinary("jef iahd acbfhdgibjdadgecgcbcjjhccaaddccefdi  dcdgeafgccebfejjaj fbefehfchhcaeafgaigfgjahacjdbdhfifiehbjfeagbdfijfcfeibe fecb cehcabjigadjfeh gca ahfdcjc gbcgfcagechjcihhfheehgcbgic hfcbheiiifbfj aefi eheef cjahief ehei  ffe fgfchfficicdfheb gcjji geji eadcjhj cd c ahdcacbfchdiaghfg jbjddfafgegbifaijebeiifjefcggj ifhccjgjhdcjbf agbfjjicf jgggdhehggcjjeehegafehechab jhdeacgahiiedhadheceehjhi jbaceeifjeiahff jcaaeih b idaggjj  hghg dehbeagje hecchihficgjiabdebb afgbghabbdj bcehccjcgcbjdaib gbeajjbgjcagbf jhhf facecj  ieiijdebideeicdfhgcca fbj abbijhdghhfbiaigacg dbb hdcjgfdefjfggcf e gfiajjdcgbbaacddahh faghejgfhhbdc cbfghciebece dahafffaa hhcb feh dcadajd bjgf echfebhcdc da jgeahah gcaaiijfbbdhbha d ahgaaeghe aadci gdidbfbbicjbdjahifhgjgi caehdibcehbegfccibhdbgj deahdadefbbgfgiae cjahc aagebgicfbecceh feabiiaabacfgejadigcfdffacjjcbeijc chggbffhdhjgcha cihhjabcg adaajdhfghddedeiifdffd ajhgfccdhgabcgbedfh hijbdgabijjjcgaf ajeigihighji aicgfja ideebabfjjgeaedbab efjjidhibbdfigga ggc id jfgfbifdbdeeejbcb gcd bjj  iggdghijdegebjfcgacbejijjcgdfjb fbahcibfdh gdjhbad cbbfcfjbjhfcij bfbbddffch bdgihgabjfc ahgfbheabhfdfgceh bjbegfbigadgde bcebihgcigdbhfcbacfaaeihgibaddhahibej hiaacgigj  j jadaggggacfcedgbfdggdechfea  bchbb gagcd ahfjhchdbfjaacgbec ffdceiibebb gfefhijhdjceaiagcdh aaadgdijdeaidagfaiehhb bfjiejjggecj b hadijgbieifgchfbhajjdjhaabbfcffeehcbeea egc dejhcjcjafibahajh  aajgbgijhjjdibb jbabhe iib  ebgeeheeafi hhgc defjdhbcfb ghji gcdchc ihjfacgejhiidid cgiefejbdegfieh  bbbfbb ejcaigc febgfbebefggbbebcabigbhgbdgajie b iffbhgbcdbjibb  iggbeeihgadicg  cdfibcea hehij ieec ehhgjbcjdhbhdcdc bhejh chbeje faiibdafjjh hijejfaecigegfce daahceg egj hfiifjacjh aihhfadiahbdccid g bgg d ead djbifgjedbfijih aeiacgahaddbchhhheibajjhjjjjda hidbfdbifbcdgaagaedggcbgddcghcgaehid ebdgg  ihddfje adicf bjgfc ecaicgbaihfbhcfaajfhejhfjigcggihadhebibihdb  jfbbfgcffae  bib   bahihdhecgejhjb idebjebgegbcf gbfdf bhfbhfa hajdeeehiifiibijhg djggbcbhfaefgjjbcahceajbjabbe eeg daghecfiijghjhacfhfjbbhef"), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"1d95c761c44008455ba135f240ff05e8211fec9535811f77b364f485a85bbde8b10d8d4e6f37df7deeaa11ee593122e1bcd26a9ead725757cab2f295bfe77aaf74ba7af5a96f58bc9a9a7cb695da16355b5e399652e9269eecb29dd660c59376157d15be2e6ddee5ca286f7ddeab97f998aac785fbece5cc94d58a668d24af4b9c9b87bf3c316e15f770c8ab1a1f0f8e30eed81de9e4572a37bd150f71ee0d3f12fcc568bf6a59b8880253b64de96c1a77d66679f7ca14ec6c2ffbd64ac0579cec25dbddf118f6ae62e86c051c38d484d5a9de4c39194f59e6acd837dca67cbce3d1a33805e6739e984c28f7adc8ebd712d009999bc25e7f03c5de3b6a9166c2b4d65c64b162472f54421aa20ed0d9b86bcdd10ccb2cafa4b8d5397b80b61c31c1104715222bea42afd93076b3da0679195f82ab0e7757646d8114cea56b383fbccd543d42dfe3fc7ec9baf72c5ce0b79f0f447a0aefb5aa5405f3989c01902074438c1d026395f69c7da1b09aacff3da28c5a407cf654b0ee6ba8e21ac1ab8eb63161bc1f7489330460b6473028da1e2b96b8c2c75e40068ca2bd02c40cef8ee66f231c81f9ce6e581cc30325d56654110a4facc6003b0080cc8e3530ad23ba15417adbe82d67dc559c2ce00218b67a1119e7237632fbbe1b2580c02a4b889737cccdf32ce7e21d16e5f4bce9876915b96b554e28d3f31cc464f051f20c186fec92d6ad822eac130442ba228f99b9e61782e3f864c7aafd4e79b0124ed435a27117472da2184c8c55407cec33252a464878b7a47070d9290116c7aaf4c701e19c13a5c8a81a71a630a0cff668b70b7b479e3b8dd53e1d767986d4dff054108d83d2b4c4c2054eea41255981729200302fcf80e860fadf252a9cf73065eb4123405417ea42941ead4e1784c3ba5d48bab2de797a3d756ec743ec1beb88d0cb1b714f2c0bba1d8aaefb4282e7117d6903728abe003cbfefc313c7491165e8639a84f8486658ac542062e1132e61737333bb50e9320f47c2582258edba820e1df2f0ef2f0c63d84f7ee119d371e5bcc571f88f0ac1e8023b34308e815c6686083b4924493906c5b5b81ad8494a8dbf14eeb4bd3e8b81edfaa5ea9e3d6862369e2700714a065e13eab12e35c434618da6804ec8699c7403d20324141c204483a499606f2c143bfe6e4e264e84bed45decb154361c216f5da1122004b88ee746bda27080b558d334d7d2128b7fe93c149da51431cadfa23805ddf9e13b0529e0156619f40a20d80228baa1c947df5707df64d40f8f2c8070fe095a0249e9ca81adbf7840e79732632498395f6e1d3cbcd054fffcbd6d837d03baae8a70033d90907f520a7af38e7e3e99f61a9c709dc0b05c72c6e5a63bbb98955a2096a80917d7b460c66fa494b7884661fb11a6240e9ba524dcc5b5aab361b106dfb5c56c8604f501"'),
    # batch35_7
    ('Binary.ToText(Binary.Compress(Text.ToBinary("jef iahd acbfhdgibjdadgecgcbcjjhccaaddccefdi  dcdgeafgccebfejjaj fbefehfchhcaeafgaigfgjahacjdbdhfifiehbjfeagbdfijfcfeibe fecb cehcabjigadjfeh gca ahfdcjc gbcgfcagechjcihhfheehgcbgic hfcbheiiifbfj aefi eheef cjahief ehei  ffe fgfchfficicdfheb gcjji geji eadcjhj cd c ahdcacbfchdiaghfg jbjddfafgegbifaijebeiifjefcggj ifhccjgjhdcjbf agbfjjicf jgggdhehggcjjeehegafehechab jhdeacgahiiedhadheceehjhi jbaceeifjeiahff jcaaeih b idaggjj  hghg dehbeagje hecchihficgjiabdebb afgbghabbdj bcehccjcgcbjdaib gbeajjbgjcagbf jhhf facecj  ieiijdebideeicdfhgcca fbj abbijhdghhfbiaigacg dbb hdcjgfdefjfggcf e gfiajjdcgbbaacddahh faghejgfhhbdc cbfghciebece dahafffaa hhcb feh dcadajd bjgf echfebhcdc da jgeahah gcaaiijfbbdhbha d ahgaaeghe aadci gdidbfbbicjbdjahifhgjgi caehdibcehbegfccibhdbgj deahdadefbbgfgiae cjahc aagebgicfbecceh feabiiaabacfgejadigcfdffacjjcbeijc chggbffhdhjgcha cihhjabcg adaajdhfghddedeiifdffd ajhgfccdhgabcgbedfh hijbdgabijjjcgaf ajeigihighji aicgfja ideebabfjjgeaedbab efjjidhibbdfigga ggc id jfgfbifdbdeeejbcb gcd bjj  iggdghijdegebjfcgacbejijjcgdfjb fbahcibfdh gdjhbad cbbfcfjbjhfcij bfbbddffch bdgihgabjfc ahgfbheabhfdfgceh bjbegfbigadgde bcebihgcigdbhfcbacfaaeihgibaddhahibej hiaacgigj  j jadaggggacfcedgbfdggdechfea  bchbb gagcd ahfjhchdbfjaacgbec ffdceiibebb gfefhijhdjceaiagcdh aaadgdijdeaidagfaiehhb bfjiejjggecj b hadijgbieifgchfbhajjdjhaabbfcffeehcbeea egc dejhcjcjafibahajh  aajgbgijhjjdibb jbabhe iib  ebgeeheeafi hhgc defjdhbcfb ghji gcdchc ihjfacgejhiidid cgiefejbdegfieh  bbbfbb ejcaigc febgfbebefggbbebcabigbhgbdgajie b iffbhgbcdbjibb  iggbeeihgadicg  cdfibcea hehij ieec ehhgjbcjdhbhdcdc bhejh chbeje faiibdafjjh hijejfaecigegfce daahceg egj hfiifjacjh aihhfadiahbdccid g bgg d ead djbifgjedbfijih aeiacgahaddbchhhheibajjhjjjjda hidbfdbifbcdgaagaedggcbgddcghcgaehid ebdgg  ihddfje adicf bjgfc ecaicgbaihfbhcfaajfhejhfjigcggihadhebibihdb  jfbbfgcffae  bib   bahihdhecgejhjb idebjebgegbcf gbfdf bhfbhfa hajdeeehiifiibijhg djggbcbhfaefgjjbcahceajbjabbe eeg daghecfiijghjhacfhfjbbhef"), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b08000000000004001d95c761c44008455ba135f240ff05e8211fec9535811f77b364f485a85bbde8b10d8d4e6f37df7deeaa11ee593122e1bcd26a9ead725757cab2f295bfe77aaf74ba7af5a96f58bc9a9a7cb695da16355b5e399652e9269eecb29dd660c59376157d15be2e6ddee5ca286f7ddeab97f998aac785fbece5cc94d58a668d24af4b9c9b87bf3c316e15f770c8ab1a1f0f8e30eed81de9e4572a37bd150f71ee0d3f12fcc568bf6a59b8880253b64de96c1a77d66679f7ca14ec6c2ffbd64ac0579cec25dbddf118f6ae62e86c051c38d484d5a9de4c39194f59e6acd837dca67cbce3d1a33805e6739e984c28f7adc8ebd712d009999bc25e7f03c5de3b6a9166c2b4d65c64b162472f54421aa20ed0d9b86bcdd10ccb2cafa4b8d5397b80b61c31c1104715222bea42afd93076b3da0679195f82ab0e7757646d8114cea56b383fbccd543d42dfe3fc7ec9baf72c5ce0b79f0f447a0aefb5aa5405f3989c01902074438c1d026395f69c7da1b09aacff3da28c5a407cf654b0ee6ba8e21ac1ab8eb63161bc1f7489330460b6473028da1e2b96b8c2c75e40068ca2bd02c40cef8ee66f231c81f9ce6e581cc30325d56654110a4facc6003b0080cc8e3530ad23ba15417adbe82d67dc559c2ce00218b67a1119e7237632fbbe1b2580c02a4b889737cccdf32ce7e21d16e5f4bce9876915b96b554e28d3f31cc464f051f20c186fec92d6ad822eac130442ba228f99b9e61782e3f864c7aafd4e79b0124ed435a27117472da2184c8c55407cec33252a464878b7a47070d9290116c7aaf4c701e19c13a5c8a81a71a630a0cff668b70b7b479e3b8dd53e1d767986d4dff054108d83d2b4c4c2054eea41255981729200302fcf80e860fadf252a9cf73065eb4123405417ea42941ead4e1784c3ba5d48bab2de797a3d756ec743ec1beb88d0cb1b714f2c0bba1d8aaefb4282e7117d6903728abe003cbfefc313c7491165e8639a84f8486658ac542062e1132e61737333bb50e9320f47c2582258edba820e1df2f0ef2f0c63d84f7ee119d371e5bcc571f88f0ac1e8023b34308e815c6686083b4924493906c5b5b81ad8494a8dbf14eeb4bd3e8b81edfaa5ea9e3d6862369e2700714a065e13eab12e35c434618da6804ec8699c7403d20324141c204483a499606f2c143bfe6e4e264e84bed45decb154361c216f5da1122004b88ee746bda27080b558d334d7d2128b7fe93c149da51431cadfa23805ddf9e13b0529e0156619f40a20d80228baa1c947df5707df64d40f8f2c8070fe095a0249e9ca81adbf7840e79732632498395f6e1d3cbcd054fffcbd6d837d03baae8a70033d90907f520a7af38e7e3e99f61a9c709dc0b05c72c6e5a63bbb98955a2096a80917d7b460c66fa494b7884661fb11a6240e9ba524dcc5b5aab361b106dfb5c56c8604f50127b6e88ad0070000"'),
    # batch35_8
    ('Binary.ToText(Binary.Compress(Text.ToBinary("x"), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"ab0000"'),
    # batch35_9
    ('Binary.ToText(Binary.Compress(Text.ToBinary("x"), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b0800000000000400ab00008316dc8c01000000"'),
    # batch35_10
    ('Binary.ToText(Binary.Compress(Text.ToBinary("Lq/RTZB13~f[ND87U""xTIA9p4Xoc[0EQ%99uT@y`kva$/gH-LLoM5""&:`%C]d;&=KI=P[#%z09.yH0@)r/kMLAU6CH)S7?}_""H]>(~~h<Rvj-E_%yB![30+@IP?o_!z!lJcSNICr<kFZ4x""lk:>!iG,>?;Rvsk<E~2;60nlo{~m_=YqHyA+m8l\\ft-wrMi]c""G""h6n5tHQD]mnsL29Zghq9.o#`8Ff$:C|5DTC+rNHy/p@#n>DQYA)^S_4Tv}^e(Som&:auBKax7PXoowv5R{{{>iopu(E>V_^d}7\\^_Yqi??J{|=3+0Zt\\ft""w3""_zowz2/&)WY80#KXevcrL|=5`b`uhJ\'lI""`&;9gADG>v?Yv)i`^>KVB<OX!I04?IE?N@F.qh^A0edqC&3v.-YG3f=IJ8&XtWR!/Bd|S,-!IHh\\2}q4OgGD+XWc![^H]-Hc*@W/.k?sapRd9www]ccO:3{$$0pTU""w\\Lh>I`B;>_^A)C+okgF|X&"), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"0dcd8982a1000000d06f29b4da26b57285ee50e44a46a1c314b221390ae1db77df0f3c25c2546dceff213e9bc540ac55a7e05d9339f254d2437781b7c63992bc69ecc309e25516db4aa8a284fd3208d59d9c607a0d88eac9d46891c93d71b2f09070163e63415fe1a61541822755e66d839249e73f1fbfa9c67fd1969d7bf0c082c011561e31a10d3c817dd79d0c64e1dc0cdaf3d21ddc07751ad875be68a6a1c697a0d9fa141b15fcb80fd3cfc1a68c487a70c8a1b65f6eae6872eeef4c17ec807ee558be4a63d13c1c2f4a919c6ffd882c8419a7d6de64ebc2ab2c6a02721e480fecc4668eb4383638d89ad8252d7e5bebfc243c40f5d58defadeed5911e86495c56d334a577e1e9966fd1dfb6e5bdab4bcb36a21dc374d3174520f8fcfaff071302b49f61f22c62103c336a78a6a7af63f7acbca8b2f3e3dcfceeafbd0c3a5083dc7262878e192386778e45f7bef9e6500764bcc4c82d66c0b60b916f71f8da8b0488880ba8d1213694dcad41fa75a60218efbd265f28204bfeb2f88e4ac36d4744f4990b2c2cc94425f7373bc30a0173599d548f4c92c474dd619d48b359fca44dc164a9f8b4ecf00ddab6385840c260db7ee9d03f"'),
    # batch35_11
    ('Binary.ToText(Binary.Compress(Text.ToBinary("Lq/RTZB13~f[ND87U""xTIA9p4Xoc[0EQ%99uT@y`kva$/gH-LLoM5""&:`%C]d;&=KI=P[#%z09.yH0@)r/kMLAU6CH)S7?}_""H]>(~~h<Rvj-E_%yB![30+@IP?o_!z!lJcSNICr<kFZ4x""lk:>!iG,>?;Rvsk<E~2;60nlo{~m_=YqHyA+m8l\\ft-wrMi]c""G""h6n5tHQD]mnsL29Zghq9.o#`8Ff$:C|5DTC+rNHy/p@#n>DQYA)^S_4Tv}^e(Som&:auBKax7PXoowv5R{{{>iopu(E>V_^d}7\\^_Yqi??J{|=3+0Zt\\ft""w3""_zowz2/&)WY80#KXevcrL|=5`b`uhJ\'lI""`&;9gADG>v?Yv)i`^>KVB<OX!I04?IE?N@F.qh^A0edqC&3v.-YG3f=IJ8&XtWR!/Bd|S,-!IHh\\2}q4OgGD+XWc![^H]-Hc*@W/.k?sapRd9www]ccO:3{$$0pTU""w\\Lh>I`B;>_^A)C+okgF|X&"), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"1f8b08000000000004000dcd8982a1000000d06f29b4da26b57285ee50e44a46a1c314b221390ae1db77df0f3c25c2546dceff213e9bc540ac55a7e05d9339f254d2437781b7c63992bc69ecc309e25516db4aa8a284fd3208d59d9c607a0d88eac9d46891c93d71b2f09070163e63415fe1a61541822755e66d839249e73f1fbfa9c67fd1969d7bf0c082c011561e31a10d3c817dd79d0c64e1dc0cdaf3d21ddc07751ad875be68a6a1c697a0d9fa141b15fcb80fd3cfc1a68c487a70c8a1b65f6eae6872eeef4c17ec807ee558be4a63d13c1c2f4a919c6ffd882c8419a7d6de64ebc2ab2c6a02721e480fecc4668eb4383638d89ad8252d7e5bebfc243c40f5d58defadeed5911e86495c56d334a577e1e9966fd1dfb6e5bdab4bcb36a21dc374d3174520f8fcfaff071302b49f61f22c62103c336a78a6a7af63f7acbca8b2f3e3dcfceeafbd0c3a5083dc7262878e192386778e45f7bef9e6500764bcc4c82d66c0b60b916f71f8da8b0488880ba8d1213694dcad41fa75a60218efbd265f28204bfeb2f88e4ac36d4744f4990b2c2cc94425f7373bc30a0173599d548f4c92c474dd619d48b359fca44dc164a9f8b4ecf00ddab6385840c260db7ee9d03f57801841f4010000"'),
    # batch35_12
    ('Binary.ToText(Binary.Compress(Text.ToBinary(""), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:""'),
    # batch35_13
    ('Binary.ToText(Binary.Compress(Text.ToBinary(""), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:""'),

    # batch36_6
    ('List.Random(3, "x")',
     'ERR:Expression.Error: We cannot convert the value "x" to type Number.'),
    # batch36_8
    ('List.Random(3, 0)',
     'V:list:[number:0.72624326996795985,number:0.81732535959096875,number:0.76802268939466345]'),
    # batch36_9
    ('List.Random(3, -5)',
     'V:list:[number:0.33836984091362443,number:0.28441844754126783,number:0.26296264178257561]'),
    # batch36_10
    ('DateTime.FromFileTime(null)',
     'V:null'),
    # batch36_11
    ('DateTime.FromFileTime("x")',
     'ERR:Expression.Error: We cannot convert the value "x" to type Number.'),
    # batch36_12
    ('DateTimeZone.FromFileTime()',
     'ERR:Expression.Error: 0 arguments were passed to a function which expects 1.'),
    # batch36_13
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f705000000", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch36_14
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f805000000", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'ERR:DataFormat.Error: Found invalid data while decoding.'),
    # batch36_15
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f706000000", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'ERR:DataFormat.Error: Found invalid data while decoding.'),
    # batch36_16
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f7", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch36_17
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f7050000001f8b0800000000000400f348cdc9c907008289d1f705000000", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch36_18
    ('Binary.ToText(Binary.Decompress(Binary.FromText("1f8b0800000000000400f348cdc9c907008289d1f705000000ff", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch36_19
    ('Binary.ToText(Binary.Decompress(Binary.FromText("f348cdc9c90700ff", BinaryEncoding.Hex), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"48656c6c6f"'),
    # batch36_20
    ('Binary.ToText(Binary.Decompress(Binary.FromText("f348cdc9", BinaryEncoding.Hex), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:"48656c"'),
    # batch36_21
    ('Binary.ToText(Binary.Decompress(Binary.FromText("", BinaryEncoding.Hex), Compression.GZip), BinaryEncoding.Hex)',
     'V:text:""'),
    # batch36_22
    ('Binary.ToText(Binary.Decompress(Binary.FromText("", BinaryEncoding.Hex), Compression.Deflate), BinaryEncoding.Hex)',
     'V:text:""'),
    # batch36_23
    ('Binary.ToText(Binary.Compress(null, Compression.GZip), BinaryEncoding.Hex)',
     'V:null'),
    # batch36_24
    ('Binary.ToText(Binary.Decompress(null, Compression.GZip), BinaryEncoding.Hex)',
     'V:null'),
    # batch36_25
    ('Binary.ToText(Binary.Compress(Text.ToBinary("a"), 0.5), BinaryEncoding.Hex)',
     "ERR:Expression.Error: The value for a 'Compression.Type' enumeration was not one of the allowed values: 'Compression.None, Compression.GZip, Compression.Deflate, Compression.Snappy, Compression.Brotli, Compression.LZ4, Compression.Zstandard'."),
    # batch36_26
    ('Binary.ToText(Binary.Compress(Text.ToBinary("a"), 1.5), BinaryEncoding.Hex)',
     "ERR:Expression.Error: The value for a 'Compression.Type' enumeration was not one of the allowed values: 'Compression.None, Compression.GZip, Compression.Deflate, Compression.Snappy, Compression.Brotli, Compression.LZ4, Compression.Zstandard'."),
    # batch36_27
    ('Binary.ApproximateLength("abc")',
     'ERR:Expression.Error: We cannot convert the value "abc" to type Binary.'),
    # batch36_28
    ('Binary.ApproximateLength(5)',
     'ERR:Expression.Error: We cannot convert the value 5 to type Binary.'),
    # batch36_29
    ('Lines.FromBinary(null)',
     'ERR:Expression.Error: We cannot convert the value null to type Binary.'),
    # batch36_30
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 1201)',
     'V:list:[text:"愊"]'),
    # batch36_31
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 12000)',
     'V:list:[]'),
    # batch36_32
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 437)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_33
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 28591)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_34
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 20127)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_35
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 1252)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_36
    ('Lines.FromBinary(Text.ToBinary("a#(lf)b"), null, null, 99999)',
     'ERR:Expression.Error: The text encoding is invalid.'),
    # batch36_37
    ('Lines.FromBinary(Binary.FromText("efbbbf610a62", BinaryEncoding.Hex))',
     'V:list:[text:"a",text:"b"]'),
    # batch36_38
    ('Lines.FromBinary(Binary.FromText("efbbbf610a62", BinaryEncoding.Hex), null, null, 65001)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_39
    ('Lines.FromBinary(Binary.FromText("fffe61000a006200", BinaryEncoding.Hex), null, null, 65001)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_40
    ('Lines.FromBinary(Binary.FromText("fffe61000a006200", BinaryEncoding.Hex))',
     'V:list:[text:"a",text:"b"]'),
    # batch36_41
    ('Lines.FromBinary(Binary.FromText("feff0061000a0062", BinaryEncoding.Hex))',
     'V:list:[text:"a",text:"b"]'),
    # batch36_42
    ('Lines.FromBinary(Binary.FromText("610a62", BinaryEncoding.Hex), null, null, 1200)',
     'V:list:[text:"\u0a61"]'),
    # batch36_43
    ('Lines.FromBinary(Binary.FromText("610d0a620d0a", BinaryEncoding.Hex), null, true)',
     'V:list:[text:"a\\r\\n",text:"b\\r\\n"]'),
    # batch36_44
    ('Lines.FromBinary(Binary.FromText("610d0a620d0a", BinaryEncoding.Hex), null, false)',
     'V:list:[text:"a",text:"b"]'),
    # batch36_45
    ('Lines.FromBinary(Binary.FromText("610d620a", BinaryEncoding.Hex))',
     'V:list:[text:"a",text:"b"]'),
    # batch36_46
    ('Lines.FromBinary(Binary.FromText("0a0a610a", BinaryEncoding.Hex))',
     'V:list:[text:"",text:"",text:"a"]'),
    # batch36_47
    ('Lines.FromBinary(Binary.FromText("6120620a", BinaryEncoding.Hex))',
     'V:list:[text:"a b"]'),
    # batch36_48
    ('Lines.FromBinary(Binary.FromText("e9", BinaryEncoding.Hex), null, null, 1252)',
     'V:list:[text:"é"]'),
    # batch36_49
    ('Lines.FromBinary(Binary.FromText("e9", BinaryEncoding.Hex))',
     'V:list:[]'),
    # batch36_50
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 1200, true), BinaryEncoding.Hex)',
     'V:text:"fffe61000d000a00"'),
    # batch36_51
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 1201, true), BinaryEncoding.Hex)',
     'V:text:"feff0061000d000a"'),
    # batch36_52
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 1252, true), BinaryEncoding.Hex)',
     'V:text:"610d0a"'),
    # batch36_53
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 20127, true), BinaryEncoding.Hex)',
     'V:text:"610d0a"'),
    # batch36_54
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 65001, true), BinaryEncoding.Hex)',
     'V:text:"efbbbf610d0a"'),
    # batch36_55
    ('Binary.ToText(Lines.ToBinary({"a"}, null, null, 1), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value 1 to type Logical.'),
    # batch36_56
    ('Binary.ToText(Lines.ToBinary({"a"}, null, null, "x"), BinaryEncoding.Hex)',
     'ERR:Expression.Error: We cannot convert the value "x" to type Logical.'),
    # batch36_57
    ('Binary.ToText(Lines.ToBinary({"a"}, null, null, null), BinaryEncoding.Hex)',
     'V:text:"610d0a"'),
    # batch36_58
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 1201), BinaryEncoding.Hex)',
     'V:text:"0061000d000a"'),
    # batch36_59
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 12000), BinaryEncoding.Hex)',
     'V:text:"fffe0000610000000d0000000a000000"'),
    # batch36_60
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 20127), BinaryEncoding.Hex)',
     'V:text:"610d0a"'),
    # batch36_61
    ('Binary.ToText(Lines.ToBinary({"é"}, null, 20127), BinaryEncoding.Hex)',
     'V:text:"3f0d0a"'),
    # batch36_62
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 437), BinaryEncoding.Hex)',
     'V:text:"610d0a"'),
    # batch36_63
    ('Binary.ToText(Lines.ToBinary({"a"}, null, 99999), BinaryEncoding.Hex)',
     'ERR:Expression.Error: The text encoding is invalid.'),
    # batch36_64
    ('Lines.ToBinary(null)',
     'ERR:Expression.Error: We cannot convert the value null to type List.'),
]

@pytest.mark.parametrize("probe, expected", PAIRS)
def test_m_engine_binary_lines_225(probe, expected):
    actual = evaluate_to_text(probe)
    assert actual == expected

def test_clock_refusal_datetimezone_from_file_time():
    # Numbers refuse with clock/timezone refusal
    res = evaluate_to_text("DateTimeZone.FromFileTime(0)")
    assert res.startswith("ERR:Expression.Error: The DateTimeZone.FromFileTime (depends on the clock"), res
    res_dt = evaluate_to_text("DateTime.FromFileTime(0)")
    assert res_dt.startswith("ERR:Expression.Error: The DateTime.FromFileTime (depends on the clock"), res_dt

def test_list_random_unseeded_bounds():
    # Check unseeded List.Random bounds
    assert evaluate_to_text("List.Count(List.Random(10))") == "V:number:10"
    assert evaluate_to_text("List.Max(List.Random(20)) < 1") == "V:true"
    assert evaluate_to_text("List.Min(List.Random(20)) >= 0") == "V:true"

def test_list_random_1000_prefix():
    # Items 0 and 1: test the first 100 values of each against the measured Power BI answers
    act0 = evaluate_to_text("List.Random(1000, 7)")
    prefix0 = 'V:list:[number:0.38322046929189024,number:0.87125568272138743,number:0.66093862273774051,number:0.052261705534654534,number:0.36643333237917786,number:0.67616944139644941,number:0.042423949131008214,number:0.95396869301515108,number:0.843566656039826,number:0.85496214118551561,number:0.4490199803602975,number:0.93231581660561069,number:0.44481648478881292,number:0.11129876324501763,number:0.88195431320087725,number:0.40201326478366428,number:0.80488364482525909,number:0.33534237059547678,number:0.86667385365193428,number:0.025025969848514521,number:0.74700167623674574,number:0.56540866595013473,number:0.17493724784578069,number:0.47804635366333942,number:0.38598197809699086,number:0.028565215891490324,number:0.95237340543063986,number:0.024876000371238216,number:0.48030640626340471,number:0.7186270848469003,number:0.77136876563139667,number:0.29717494002411837,number:0.11203963081913051,number:0.16403814366275357,number:0.086947837884979243,number:0.066329704628479536,number:0.82883943609373623,number:0.15149623255780723,number:0.54190520734614933,number:0.93207671583261187,number:0.87900083180470434,number:0.66073937558603446,number:0.12398461956716357,number:0.065599488590657479,number:0.59774979324906585,number:0.95924514763022084,number:0.71870968012079117,number:0.56687005170009563,number:0.83068100494829988,number:0.14650033700582588,number:0.22332884614510873,number:0.87363001186104028,number:0.7071329838163839,number:0.91405643658435742,number:0.59652107795538434,number:0.81781180334175552,number:0.69631843487560674,number:0.182892269074401,number:0.66627972743766373,number:0.3378681164876875,number:0.72379603596580966,number:0.017547948759769998,number:0.47366228675174632,number:0.12493957119292559,number:0.083593375554118943,number:0.1518450403361791,number:0.82027618578648021,number:0.28077834112605932,number:0.024350925360038377,number:0.81562460857239771,number:0.573173828689928,number:0.65338741226745178,number:0.79343716324932745,number:0.93459713781932241,number:0.1460251380438102,number:0.0862623006507113,number:0.44142404638297111,number:0.10933775925512321,number:0.88029656041427351,number:0.42673683046677,number:0.30985553577069919,number:0.38550335373054417,number:0.19419499542293836,number:0.33380606925757883,number:0.49529823870179163,number:0.89773875377035639,number:0.59004195620773447,number:0.19798319423477315,number:0.56751706570736926,number:0.26913603454322371,number:0.37001126975287274,number:0.64594716701933519,number:0.48521650512014353,number:0.20403709085846183,number:0.20828067986680227,number:0.86145288304493428,number:0.18707708883428811,number:0.999045048374238,number:0.98200611303653851,number:0.44590475291288678'
    assert act0.startswith(prefix0), act0[:100]

    act1 = evaluate_to_text("List.Random(1000, 12345)")
    prefix1 = 'V:list:[number:0.066746934813795109,number:0.070159508879370752,number:0.77476513514982781,number:0.51113926875923721,number:0.79749055849271389,number:0.827308291023275,number:0.16595879530811627,number:0.73613062348967917,number:0.26021636475818993,number:0.5060048510814108,number:0.23027372231254062,number:0.38714044326317515,number:0.21598061510174563,number:0.020810884898906055,number:0.13483360229750796,number:0.740831733560577,number:0.19509106790418321,number:0.88703956589430555,number:0.861100613540551,number:0.35886506380460459,number:0.10370226022959791,number:0.52958305158167285,number:0.35875501686649164,number:0.707505481181436,number:0.58047483189984916,number:0.6205483226201256,number:0.73249663167283718,number:0.74788273998903243,number:0.39625106071878741,number:0.24525723990297749,number:0.68634507231709785,number:0.21054619374244762,number:0.51753758663196936,number:0.48539096512151464,number:0.25280545291155831,number:0.77077884914855421,number:0.002578939312407253,number:0.48391211427930375,number:0.44795790335534041,number:0.48646042658316924,number:0.71157739065195313,number:0.45124772584589556,number:0.26995235694104447,number:0.28304051388196672,number:0.635241387242098,number:0.29477864610719434,number:0.36953359626677518,number:0.8526806765481274,number:0.17566556398554964,number:0.852200557874609,number:0.6443545756136787,number:0.61583341453961726,number:0.44152083547856696,number:0.49669684306564593,number:0.030103534939747087,number:0.53716388323212227,number:0.71140449201287914,number:0.067259653968391772,number:0.93066443685938816,number:0.17694223587258823,number:0.09481165935043788,number:0.41807605531908387,number:0.33987956277089171,number:0.014959124855212461,number:0.819659778764313,number:0.019727528570092995,number:0.86960285663120584,number:0.730589649980231,number:0.76800543198734772,number:0.3640547531489538,number:0.7382527942481697,number:0.71117895362487948,number:0.43908166253896508,number:0.37464018695738177,number:0.64728767315265145,number:0.65245453438370238,number:0.25963069464062838,number:0.075714502984524937,number:0.072264093939337928,number:0.28569618579265482,number:0.25101472635335043,number:0.87981595512470978,number:0.57221717600348276,number:0.54405050284417833,number:0.60090266428929873,number:0.070511657777480627,number:0.76902535826388063,number:0.020840743566323417,number:0.45528743018176754,number:0.715641569679436,number:0.059374357135675085,number:0.93531928534401543,number:0.55324767741991565,number:0.27101566748275219,number:0.39164876723273134,number:0.29350133533286926,number:0.11136816307500384,number:0.254993232085832,number:0.46338073511765371,number:0.615513858672005'
    assert act1.startswith(prefix1), act1[:100]

def test_list_random_unrepresentable_refusal():
    # Items 2, 3, 4, 5, 7 refuse with "not supported by this engine yet"
    for probe in [
        "List.Random(3, 2147483648)",
        "List.Random(3, -2147483649)",
        "List.Random(3, 4294967296)",
        "List.Random(3, 1.5)",
        "List.Random(3, 0.5)",
    ]:
        res = evaluate_to_text(probe)
        assert "not supported by this engine yet" in res, (probe, res)

def test_lines_to_binary_bom_and_separators():
    # Real BOM and separator test
    # UTF-8 with BOM and CRLF
    res_utf8_bom = evaluate_to_text('Binary.ToText(Lines.ToBinary({"hello", "world"}, null, 65001, true), BinaryEncoding.Hex)')
    assert res_utf8_bom == 'V:text:"efbbbf68656c6c6f0d0a776f726c640d0a"'
    # UTF-16 LE with BOM and comma separator
    res_utf16_bom = evaluate_to_text('Binary.ToText(Lines.ToBinary({"a", "b"}, ",", 1200, true), BinaryEncoding.Hex)')
    assert res_utf16_bom == 'V:text:"fffe61002c0062002c00"'
    # UTF-8 with custom delimiter and no BOM
    res_delim = evaluate_to_text('Binary.ToText(Lines.ToBinary({"x", "y"}, "|", 65001, false), BinaryEncoding.Hex)')
    assert res_delim == 'V:text:"787c797c"'
