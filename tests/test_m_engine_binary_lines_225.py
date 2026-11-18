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

def test_lines_to_binary_bom_and_separators():
    # Additional check for unseeded List.Random bounds
    assert evaluate_to_text("List.Count(List.Random(10))") == "V:number:10"
    assert evaluate_to_text("List.Max(List.Random(20)) < 1") == "V:true"
    assert evaluate_to_text("List.Min(List.Random(20)) >= 0") == "V:true"
