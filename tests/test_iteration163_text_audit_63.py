"""Iteration 163: Task 73 text audit (text-audit-63).

Covers the live Power BI evidence in tools/parity/task73_text_audit_spec.json (Part A: linguistic matching in FIND, SEARCH,
CONTAINSSTRING and CONTAINSSTRINGEXACT; Part B: BLANK as text in REPLACE and SUBSTITUTE) and the focused grid t73b:
- Part A: an expansion in the search text matches its plain letters (FIND("ß","Strasse") is 5); plain letters in the searched
  text match an expansion there (SEARCH("ss","straße") is 5); a compatibility form matches its parts (ǅ matches Dž); a combining
  sequence matches its precomposed letter, and the case-sensitive functions keep case.
- A search text longer than the searched text is no match in the case-sensitive search: "ss" is not found in "ß".
- A match never begins or ends inside an expansion: SUBSTITUTE("straße","s","x") leaves the ß alone.
- Part B: REPLACE of a BLANK text inserts the new text; SUBSTITUTE of an empty text is "" and never BLANK.
- Refused, not guessed: wildcards with expanded text, and a search text that starts with a combining mark.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax

SS_SHARP = "ß"  # ß
DZ_CARON = "Dž"  # Dž
DZ_DIGRAPH = "ǅ"  # ǅ
FI_LIGATURE = "ﬁ"  # ﬁ
AE_LIGATURE = "æ"  # æ
E_ACUTE = "é"  # é, precomposed
E_DECOMPOSED = "é"  # e followed by a combining acute accent


class TestIteration163TextAudit63(unittest.TestCase):
    def assertLocal(self, expr: str, expected: str) -> None:
        with self.subTest(expr=expr):
            self.assertEqual(str(dax.local(expr)), expected)

    def assertRefused(self, expr: str) -> None:
        with self.subTest(expr=expr):
            self.assertTrue(str(dax.local(expr)).startswith("LOCAL-REJECT"), str(dax.local(expr)))

    # Part A: an expansion in the search text
    def test_part_a_expansion_in_search_text_matches_its_letters(self) -> None:
        self.assertLocal(f'FIND("{SS_SHARP}","Strasse",1,-1)', "5")
        self.assertLocal(f'FIND("{SS_SHARP}","ss",1,-1)', "1")
        self.assertLocal(f'SEARCH("{SS_SHARP}","STRASSE",1,-1)', "5")
        self.assertLocal(f'SEARCH("{SS_SHARP}","SS",1,-1)', "1")
        self.assertLocal(f'FIND("{FI_LIGATURE}","fi",1,-1)', "1")
        self.assertLocal(f'SEARCH("{AE_LIGATURE}","ae",1,-1)', "1")
        self.assertLocal(f'SEARCH("{DZ_DIGRAPH}","{DZ_CARON}",1,-1)', "1")

    # Part A: plain letters in the searched text
    def test_part_a_plain_letters_match_an_expansion_in_the_text(self) -> None:
        self.assertLocal(f'FIND("ss","stra{SS_SHARP}e",1,-1)', "5")
        self.assertLocal(f'SEARCH("ss","stra{SS_SHARP}e",1,-1)', "5")
        self.assertLocal(f'SEARCH("Strasse","stra{SS_SHARP}e",1,-1)', "1")
        self.assertLocal(f'CONTAINSSTRINGEXACT("stra{SS_SHARP}e","ss")', "True")
        self.assertLocal(f'CONTAINSSTRING("{SS_SHARP}","ss")', "True")
        self.assertLocal(f'CONTAINSSTRING("{DZ_CARON}","{DZ_DIGRAPH}")', "True")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{DZ_CARON}","{DZ_DIGRAPH}")', "True")

    # Part A: a search text longer than the searched text is no match in the case-sensitive search
    def test_part_a_longer_search_text_is_no_match(self) -> None:
        self.assertLocal(f'CONTAINSSTRINGEXACT("{SS_SHARP}","ss")', "False")
        self.assertLocal(f'FIND("ss","{SS_SHARP}",1,-1)', "-1")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{DZ_DIGRAPH}","{DZ_CARON}")', "False")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{FI_LIGATURE}","fi")', "False")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{AE_LIGATURE}","ae")', "False")

    # Part A: combining sequences and case
    def test_part_a_combining_sequence_matches_its_precomposed_letter(self) -> None:
        self.assertLocal(f'FIND("{E_ACUTE}","{E_DECOMPOSED}",1,-1)', "1")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{E_DECOMPOSED}","{E_ACUTE}")', "True")
        self.assertLocal(f'CONTAINSSTRINGEXACT("{E_ACUTE}","{E_DECOMPOSED}")', "False")
        self.assertLocal(f'FIND("{E_DECOMPOSED}","{E_ACUTE}",1,-1)', "-1")

    def test_part_a_case_sensitivity_by_function(self) -> None:
        self.assertLocal("SEARCH(\"é\",\"É\",1,-1)", "1")
        self.assertLocal("FIND(\"é\",\"É\",1,-1)", "-1")
        self.assertLocal("CONTAINSSTRINGEXACT(\"é\",\"É\")", "False")
        self.assertLocal("CONTAINSSTRING(\"é\",\"É\")", "True")

    def test_part_a_plain_ascii_search_is_unchanged(self) -> None:
        self.assertLocal('FIND("b","abc",1,-1)', "2")
        self.assertLocal('SEARCH("B","abc",1,-1)', "2")
        self.assertLocal('FIND("z","abc",1,-1)', "-1")

    # Part A: a match never begins or ends inside an expansion
    def test_part_a_partial_expansion_is_no_match(self) -> None:
        self.assertLocal(f'SUBSTITUTE("stra{SS_SHARP}e","s","x")', f"xtra{SS_SHARP}e")
        self.assertLocal(f'SUBSTITUTE("ss","s","{SS_SHARP}")', f"{SS_SHARP}{SS_SHARP}")

    # Part B: BLANK as text
    def test_part_b_replace_of_blank_text_inserts_the_new_text(self) -> None:
        self.assertLocal('REPLACE(BLANK(),2,1,"-1.5")', "-1.5")
        self.assertLocal('REPLACE(BLANK(),1,0,"x")', "x")
        self.assertLocal(f'REPLACE(BLANK(),1,0,"{SS_SHARP}")', SS_SHARP)

    def test_part_b_substitute_of_empty_text_is_empty(self) -> None:
        self.assertLocal('SUBSTITUTE("","x",BLANK())', "")
        self.assertLocal(f'SUBSTITUTE("","{SS_SHARP}",BLANK())', "")
        self.assertLocal('SUBSTITUTE("","İ",BLANK())', "")
        self.assertLocal('SUBSTITUTE(BLANK(),"x",BLANK())', "BLANK")

    def test_part_b_substitute_removing_everything_is_blank(self) -> None:
        self.assertLocal('SUBSTITUTE("SS","SS",BLANK())', "BLANK")
        self.assertLocal('SUBSTITUTE("Strasse","Strasse",BLANK())', "BLANK")

    # Part B: the removed length is the length of the search text, from the linguistic position
    def test_part_b_substitute_removes_the_length_of_the_search_text(self) -> None:
        self.assertLocal(f'SUBSTITUTE("stra{SS_SHARP}e","ss",BLANK())', "stra")
        self.assertLocal(f'SUBSTITUTE("ss","{SS_SHARP}",BLANK())', "s")
        self.assertLocal(f'SUBSTITUTE("Strasse","{SS_SHARP}",BLANK())', "Strase")
        self.assertLocal(f'SUBSTITUTE("{SS_SHARP}","ss",BLANK())', SS_SHARP)
        self.assertLocal(f'SUBSTITUTE("STRASSE","{SS_SHARP}",BLANK())', "STRASSE")
        self.assertLocal('SUBSTITUTE("Strasse","ss",BLANK())', "Strae")

    # Refusals: wildcards with expanded text, and a leading combining mark
    def test_refuses_wildcards_with_expanded_text(self) -> None:
        self.assertRefused(f'SEARCH("s*","stra{SS_SHARP}e",1,-1)')
        self.assertRefused(f'CONTAINSSTRING("stra{SS_SHARP}e","s*")')

    def test_refuses_a_search_text_that_starts_with_a_combining_mark(self) -> None:
        self.assertRefused('FIND("́","é",1,-1)')
        self.assertRefused('CONTAINSSTRINGEXACT("é","́")')


if __name__ == "__main__":
    unittest.main()
