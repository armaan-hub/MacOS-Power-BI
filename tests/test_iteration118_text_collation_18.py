"""Iteration 118: tests for Task 28 text-collation-18 (ordering and comparing non-ASCII text)."""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration118TextCollation18(unittest.TestCase):
    def test_special_expansions_and_ligatures(self) -> None:
        self.assertEqual(dax.local('"ǅ"="dž"'), "True")
        self.assertEqual(dax.local('"ǆ"<"dž"'), "False")
        self.assertEqual(dax.local('"æ"="ae"'), "True")
        self.assertEqual(dax.local('"Straße"="STRASSE"'), "True")
        self.assertEqual(dax.local('"þ"<"u"'), "True")  # thorn expands to th
        self.assertEqual(dax.local('"J"<"þ"'), "True")

    def test_special_letters_diacritics_and_base_ordering(self) -> None:
        # đ (d with stroke)
        self.assertEqual(dax.local('"D"<"đ"'), "True")
        self.assertEqual(dax.local('"đ"<"j"'), "True")
        self.assertEqual(dax.local('"abž"<="đbc"'), "True")
        self.assertEqual(dax.local('"cafđ">="cafe"'), "False")

        # ł (l with stroke)
        self.assertEqual(dax.local('"facade"<"łacade"'), "True")
        self.assertEqual(dax.local('"ł"<"s"'), "True")

        # ø (o with stroke)
        self.assertEqual(dax.local('"ōaive"<"øaive"'), "True")
        self.assertEqual(dax.local('"niné"<"ninø"'), "True")

        # ð (eth)
        self.assertEqual(dax.local('"čûúï"<"ð"'), "True")
        self.assertEqual(dax.local('"ð"<"q"'), "True")

        # ı (dotless i)
        self.assertEqual(dax.local('"ı"<"ì"'), "True")
        self.assertEqual(dax.local('"I"="ı"'), "False")

        # ŀ (l with middle dot)
        self.assertEqual(dax.local('"e"<"ŀ"'), "True")
        self.assertEqual(dax.local('"ŀ"<"õ"'), "True")

        # ŉ (n preceded by apostrophe)
        self.assertEqual(dax.local('"i"<"ŉ"'), "True")
        self.assertEqual(dax.local('"ŉ"<="ť"'), "True")

    def test_long_s_ordering_and_inequality(self) -> None:
        self.assertEqual(dax.local('"s"<>"ſ"'), "True")
        self.assertEqual(dax.local('"s"="ſ"'), "False")
        self.assertEqual(dax.local('"SS"<"ſs"'), "True")
        self.assertEqual(dax.local('"STRASSE"<="ſs"'), "True")
        self.assertEqual(dax.local('"ſs"<="sz"'), "False")
        self.assertEqual(dax.local('"z"<"ſ"'), "False")

    def test_stacked_combining_marks_order_independence(self) -> None:
        self.assertEqual(dax.local('"ò̌"="ǒ̀"'), "True")  # grave + caron
        self.assertEqual(dax.local('"k̂̊"="k̊̂"'), "True")  # circumflex + ring
        self.assertEqual(dax.local('"w̧̃"="w̧̃"'), "True")  # cedilla + tilde
        self.assertEqual(dax.local('"b̀̋"="b̋̀"'), "True")  # grave + double acute
        self.assertEqual(dax.local('"ò̌"<"ǒ̀"'), "False")
        self.assertEqual(dax.local('"ò̌"<="ǒ̀"'), "True")

    def test_modifier_apostrophe_ignored_at_level1(self) -> None:
        self.assertEqual(dax.local('"A"<"ʼn"'), "True")
        self.assertEqual(dax.local('"ʼn"<"ô"'), "True")
        self.assertEqual(dax.local('"ʼn">="J"'), "True")
        self.assertEqual(dax.local('"ʼn"<="Ì"'), "False")

    def test_unclassifiable_scripts_refusal(self) -> None:
        # Greek, Cyrillic, CJK remain strictly refused
        self.assertTrue(dax.local('"α"<"β"').startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local('"д"<"ж"').startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local('"中"="文"').startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
