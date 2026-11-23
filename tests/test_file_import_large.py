"""Large-file import: ImportLimitError, the CSV parser split (frozen baseline results), and parse_head."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from analytics_studio import file_import
from analytics_studio.file_import import (
    FileImportError,
    ImportLimitError,
    normalize_options,
    parse_file,
    parse_head,
)

# Results of the CSV parser before the B4b split (commit 8eb35af), frozen once.
# Each case: the file bytes (base64), the options passed to normalize_options,
# and either the headers/rows/notices/options or the FileImportError message.
_FROZEN_CSV_CASES_JSON = r'''[{"name":"plain_lf","data":"YSxiCjEsMgozLDQK","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"plain_crlf","data":"YSxiDQoxLDINCjMsNA0K","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"plain_cr","data":"YSxiDTEsMg0zLDQN","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"no_trailing_newline","data":"YSxiCjEsMgozLDQ=","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_only","data":"YSxiCg==","options":{},"expected":{"headers":["a","b"],"rows":[],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_only_no_newline","data":"YSxi","options":{},"expected":{"headers":["a","b"],"rows":[],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"empty","data":"","options":{},"expected":{"error":"case.csv is empty and has no header row."}},{"name":"empty_no_header","data":"","options":{"has_header":false},"expected":{"error":"case.csv is empty and has no header row."}},{"name":"only_newlines","data":"CgoK","options":{},"expected":{"error":"case.csv is empty and has no header row."}},{"name":"only_newlines_nohdr","data":"CgoK","options":{"has_header":false},"expected":{"error":"case.csv is empty and has no header row."}},{"name":"no_header_option","data":"MSwyCjMsNAo=","options":{"has_header":false},"expected":{"headers":["Column 1","Column 2"],"rows":[[["Column 1","1"],["Column 2","2"]],[["Column 1","3"],["Column 2","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":false}}},{"name":"quoted_comma","data":"YSxiCiJ4LHkiLDIK","options":{},"expected":{"headers":["a","b"],"rows":[[["a","x,y"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"quoted_quote","data":"YSxiCiJoZSBzYWlkICIiaGkiIiIsMgo=","options":{},"expected":{"headers":["a","b"],"rows":[[["a","he said \"hi\""],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"embedded_lf","data":"YSxiCiJsCm0iLDIKMyw0Cg==","options":{},"expected":{"headers":["a","b"],"rows":[[["a","l\nm"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"embedded_crlf_in_crlf_file","data":"YSxiDQoibA0KbSIsMg0K","options":{},"expected":{"headers":["a","b"],"rows":[[["a","l\r\nm"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"embedded_lf_in_crlf","data":"YSwibAptIg0KYixjDQo=","options":{},"expected":{"headers":["a","l\nm"],"rows":[[["a","b"],["l\nm","c"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"embedded_cr","data":"YSxiCiJ4DXkiLDIK","options":{},"expected":{"headers":["a","b"],"rows":[[["a","x\ry"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"unterminated_quote_end","data":"YSxiCiJhYmMsMgo=","options":{},"expected":{"error":"Could not parse case.csv as CSV: unexpected end of data"}},{"name":"unterminated_quote_mid","data":"YSxiCiJhYmMsMgozLDQKNSw2Cg==","options":{},"expected":{"error":"Could not parse case.csv as CSV: unexpected end of data"}},{"name":"ragged_short","data":"YSxiLGMKMSwyCjMsNCw1Cg==","options":{},"expected":{"headers":["a","b","c"],"rows":[[["a","1"],["b","2"],["c",""]],[["a","3"],["b","4"],["c","5"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"ragged_long","data":"YSxiCjEsMiwzCjQK","options":{},"expected":{"headers":["a","b","Column 3"],"rows":[[["a","1"],["b","2"],["Column 3","3"]],[["a","4"],["b",""],["Column 3",""]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"ragged_wide_late","data":"YSxiCjEsMgozLDQsNSw2LDcK","options":{},"expected":{"headers":["a","b","Column 3","Column 4","Column 5"],"rows":[[["a","1"],["b","2"],["Column 3",""],["Column 4",""],["Column 5",""]],[["a","3"],["b","4"],["Column 3","5"],["Column 4","6"],["Column 5","7"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"ragged_wide_late_nohdr","data":"MSwyCjMsNCw1LDYsNwo=","options":{"has_header":false},"expected":{"headers":["Column 1","Column 2","Column 3","Column 4","Column 5"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3",""],["Column 4",""],["Column 5",""]],[["Column 1","3"],["Column 2","4"],["Column 3","5"],["Column 4","6"],["Column 5","7"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":false}}},{"name":"blank_lines_between","data":"YSxiCgoxLDIKCgozLDQKCg==","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"blank_lines_nohdr","data":"CjEsMgoKMyw0Cg==","options":{"has_header":false},"expected":{"headers":["Column 1","Column 2"],"rows":[[["Column 1","1"],["Column 2","2"]],[["Column 1","3"],["Column 2","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":false}}},{"name":"delim_only_first_record","data":"LCwKMSwyLDMK","options":{},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3","3"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"delim_only_first_record_nohdr","data":"LCwKMSwyLDMK","options":{"has_header":false},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3","3"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":false}}},{"name":"delim_only_then_blank","data":"LCwKCiwsLAoxLDIsMwo=","options":{},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3","3"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"quoted_empty_first","data":"IiIKLCwKMSwyLDMK","options":{},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3","3"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"many_blank_before_header","data":"IiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKIiIKLCwKYSxiLGMK","options":{},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","a"],["Column 2","b"],["Column 3","c"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"all_empty_overwide_skipped","data":"YSxiCjEsMgosLCwsLCwsLAo=","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"all_empty_overwide_mid","data":"YSxiCiwsLCwsCjEsMgo=","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_blank_cells","data":"YSwsYwoxLDIsMwo=","options":{},"expected":{"headers":["a","Column 2","c"],"rows":[[["a","1"],["Column 2","2"],["c","3"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_duplicates","data":"QSxhCjEsMgo=","options":{},"expected":{"headers":["A","a"],"rows":[[["A","1"],["a","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_newline","data":"ImEKYiIsYwoxLDIK","options":{},"expected":{"headers":["a\nb","c"],"rows":[[["a\nb","1"],["c","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_tab","data":"YQliLGMKMSwyCg==","options":{},"expected":{"headers":["a\tb","c"],"rows":[[["a\tb","1"],["c","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_underscore_rn","data":"X19ybixjCjEsMgo=","options":{},"expected":{"headers":["__rn","c"],"rows":[[["__rn","1"],["c","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"header_nul","data":"YQBiLGMKMSwyCg==","options":{},"expected":{"headers":["a\u0000b","c"],"rows":[[["a\u0000b","1"],["c","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"bom_utf8_default","data":"77u/YSxiCjEsMgo=","options":{"encoding":"utf-8"},"expected":{"headers":["\ufeffa","b"],"rows":[[["\ufeffa","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8","has_header":true}}},{"name":"bom_utf8_sig","data":"77u/YSxiCjEsMgo=","options":{"encoding":"utf-8-sig"},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"utf8_nobom","data":"YSxiCjEsMgo=","options":{"encoding":"utf-8"},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8","has_header":true}}},{"name":"utf8_unicode","data":"YSxiCm5hw692ZSzml6XmnKwK4oKsLMOpCg==","options":{"encoding":"utf-8"},"expected":{"headers":["a","b"],"rows":[[["a","na\u00efve"],["b","\u65e5\u672c"]],[["a","\u20ac"],["b","\u00e9"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8","has_header":true}}},{"name":"utf16_bom","data":"//5hACwAYgANAAoAIgDpAKwgLAAxACIALADlZSxnDQAKAA==","options":{"encoding":"utf-16"},"expected":{"headers":["a","b"],"rows":[[["a","\u00e9\u20ac,1"],["b","\u65e5\u672c"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-16","has_header":true}}},{"name":"utf16_le_nobom","data":"YQAsAGIADQAKAOkALAAxAA0ACgA=","options":{"encoding":"utf-16"},"expected":{"headers":["a","b"],"rows":[[["a","\u00e9"],["b","1"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-16","has_header":true}}},{"name":"utf16_odd_trailing","data":"//5hACwAYgAKADEALAAyAAoAAA==","options":{"encoding":"utf-16"},"expected":{"error":"Could not decode case.csv as utf-16."}},{"name":"cp1252_text","data":"YSxiDQqA6Swik3iUIg0K","options":{"encoding":"cp1252"},"expected":{"headers":["a","b"],"rows":[[["a","\u20ac\u00e9"],["b","\u201cx\u201d"]]],"notices":[],"options":{"delimiter":",","encoding":"cp1252","has_header":true}}},{"name":"cp1252_undefined_byte","data":"YQqBCg==","options":{"encoding":"cp1252"},"expected":{"error":"Could not decode case.csv as cp1252."}},{"name":"bad_utf8","data":"YSxiCv/+LHgK","options":{},"expected":{"error":"Could not decode case.csv as utf-8-sig."}},{"name":"semicolon","data":"YTtiCjE7Mgo=","options":{"delimiter":";"},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":";","encoding":"utf-8-sig","has_header":true}}},{"name":"tab","data":"YQliCjEJMgo=","options":{"delimiter":"\t"},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":"\t","encoding":"utf-8-sig","has_header":true}}},{"name":"pipe_quoted","data":"YXxiCiJ4fHkifDIK","options":{"delimiter":"|"},"expected":{"headers":["a","b"],"rows":[[["a","x|y"],["b","2"]]],"notices":[],"options":{"delimiter":"|","encoding":"utf-8-sig","has_header":true}}},{"name":"pipe_nohdr_ragged","data":"MXwyfDMKNHw1Cg==","options":{"delimiter":"|","has_header":false},"expected":{"headers":["Column 1","Column 2","Column 3"],"rows":[[["Column 1","1"],["Column 2","2"],["Column 3","3"]],[["Column 1","4"],["Column 2","5"],["Column 3",""]]],"notices":[],"options":{"delimiter":"|","encoding":"utf-8-sig","has_header":false}}},{"name":"lone_cr_quote","data":"YSwiYiINMSwyDQ==","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"mixed_eol","data":"YSxiDTEsMgozLDQN","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]],[["a","3"],["b","4"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"trailing_delim","data":"YSxiLAoxLDIsCjMsNCw1Cg==","options":{},"expected":{"headers":["a","b","Column 3"],"rows":[[["a","1"],["b","2"],["Column 3",""]],[["a","3"],["b","4"],["Column 3","5"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"nul_in_cell","data":"YSxiCjEAeCwyCg==","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1\u0000x"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"sentinel_like","data":"YSxiCgFOVUxMASx4Cg==","options":{},"expected":{"headers":["a","b"],"rows":[[["a","\u0001NULL\u0001"],["b","x"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"quote_then_text","data":"YSxiCiJ4InksMgo=","options":{},"expected":{"error":"Could not parse case.csv as CSV: ',' expected after '\"'"}},{"name":"field_5k","data":"YSxiCiJ4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eCIsMQo=","options":{},"expected":{"headers":["a","b"],"rows":[[["a","xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],["b","1"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"cols_512","data":"aDAsaDEsaDIsaDMsaDQsaDUsaDYsaDcsaDgsaDksaDEwLGgxMSxoMTIsaDEzLGgxNCxoMTUsaDE2LGgxNyxoMTgsaDE5LGgyMCxoMjEsaDIyLGgyMyxoMjQsaDI1LGgyNixoMjcsaDI4LGgyOSxoMzAsaDMxLGgzMixoMzMsaDM0LGgzNSxoMzYsaDM3LGgzOCxoMzksaDQwLGg0MSxoNDIsaDQzLGg0NCxoNDUsaDQ2LGg0NyxoNDgsaDQ5LGg1MCxoNTEsaDUyLGg1MyxoNTQsaDU1LGg1NixoNTcsaDU4LGg1OSxoNjAsaDYxLGg2MixoNjMsaDY0LGg2NSxoNjYsaDY3LGg2OCxoNjksaDcwLGg3MSxoNzIsaDczLGg3NCxoNzUsaDc2LGg3NyxoNzgsaDc5LGg4MCxoODEsaDgyLGg4MyxoODQsaDg1LGg4NixoODcsaDg4LGg4OSxoOTAsaDkxLGg5MixoOTMsaDk0LGg5NSxoOTYsaDk3LGg5OCxoOTksaDEwMCxoMTAxLGgxMDIsaDEwMyxoMTA0LGgxMDUsaDEwNixoMTA3LGgxMDgsaDEwOSxoMTEwLGgxMTEsaDExMixoMTEzLGgxMTQsaDExNSxoMTE2LGgxMTcsaDExOCxoMTE5LGgxMjAsaDEyMSxoMTIyLGgxMjMsaDEyNCxoMTI1LGgxMjYsaDEyNyxoMTI4LGgxMjksaDEzMCxoMTMxLGgxMzIsaDEzMyxoMTM0LGgxMzUsaDEzNixoMTM3LGgxMzgsaDEzOSxoMTQwLGgxNDEsaDE0MixoMTQzLGgxNDQsaDE0NSxoMTQ2LGgxNDcsaDE0OCxoMTQ5LGgxNTAsaDE1MSxoMTUyLGgxNTMsaDE1NCxoMTU1LGgxNTYsaDE1NyxoMTU4LGgxNTksaDE2MCxoMTYxLGgxNjIsaDE2MyxoMTY0LGgxNjUsaDE2NixoMTY3LGgxNjgsaDE2OSxoMTcwLGgxNzEsaDE3MixoMTczLGgxNzQsaDE3NSxoMTc2LGgxNzcsaDE3OCxoMTc5LGgxODAsaDE4MSxoMTgyLGgxODMsaDE4NCxoMTg1LGgxODYsaDE4NyxoMTg4LGgxODksaDE5MCxoMTkxLGgxOTIsaDE5MyxoMTk0LGgxOTUsaDE5NixoMTk3LGgxOTgsaDE5OSxoMjAwLGgyMDEsaDIwMixoMjAzLGgyMDQsaDIwNSxoMjA2LGgyMDcsaDIwOCxoMjA5LGgyMTAsaDIxMSxoMjEyLGgyMTMsaDIxNCxoMjE1LGgyMTYsaDIxNyxoMjE4LGgyMTksaDIyMCxoMjIxLGgyMjIsaDIyMyxoMjI0LGgyMjUsaDIyNixoMjI3LGgyMjgsaDIyOSxoMjMwLGgyMzEsaDIzMixoMjMzLGgyMzQsaDIzNSxoMjM2LGgyMzcsaDIzOCxoMjM5LGgyNDAsaDI0MSxoMjQyLGgyNDMsaDI0NCxoMjQ1LGgyNDYsaDI0NyxoMjQ4LGgyNDksaDI1MCxoMjUxLGgyNTIsaDI1MyxoMjU0LGgyNTUsaDI1NixoMjU3LGgyNTgsaDI1OSxoMjYwLGgyNjEsaDI2MixoMjYzLGgyNjQsaDI2NSxoMjY2LGgyNjcsaDI2OCxoMjY5LGgyNzAsaDI3MSxoMjcyLGgyNzMsaDI3NCxoMjc1LGgyNzYsaDI3NyxoMjc4LGgyNzksaDI4MCxoMjgxLGgyODIsaDI4MyxoMjg0LGgyODUsaDI4NixoMjg3LGgyODgsaDI4OSxoMjkwLGgyOTEsaDI5MixoMjkzLGgyOTQsaDI5NSxoMjk2LGgyOTcsaDI5OCxoMjk5LGgzMDAsaDMwMSxoMzAyLGgzMDMsaDMwNCxoMzA1LGgzMDYsaDMwNyxoMzA4LGgzMDksaDMxMCxoMzExLGgzMTIsaDMxMyxoMzE0LGgzMTUsaDMxNixoMzE3LGgzMTgsaDMxOSxoMzIwLGgzMjEsaDMyMixoMzIzLGgzMjQsaDMyNSxoMzI2LGgzMjcsaDMyOCxoMzI5LGgzMzAsaDMzMSxoMzMyLGgzMzMsaDMzNCxoMzM1LGgzMzYsaDMzNyxoMzM4LGgzMzksaDM0MCxoMzQxLGgzNDIsaDM0MyxoMzQ0LGgzNDUsaDM0NixoMzQ3LGgzNDgsaDM0OSxoMzUwLGgzNTEsaDM1MixoMzUzLGgzNTQsaDM1NSxoMzU2LGgzNTcsaDM1OCxoMzU5LGgzNjAsaDM2MSxoMzYyLGgzNjMsaDM2NCxoMzY1LGgzNjYsaDM2NyxoMzY4LGgzNjksaDM3MCxoMzcxLGgzNzIsaDM3MyxoMzc0LGgzNzUsaDM3NixoMzc3LGgzNzgsaDM3OSxoMzgwLGgzODEsaDM4MixoMzgzLGgzODQsaDM4NSxoMzg2LGgzODcsaDM4OCxoMzg5LGgzOTAsaDM5MSxoMzkyLGgzOTMsaDM5NCxoMzk1LGgzOTYsaDM5NyxoMzk4LGgzOTksaDQwMCxoNDAxLGg0MDIsaDQwMyxoNDA0LGg0MDUsaDQwNixoNDA3LGg0MDgsaDQwOSxoNDEwLGg0MTEsaDQxMixoNDEzLGg0MTQsaDQxNSxoNDE2LGg0MTcsaDQxOCxoNDE5LGg0MjAsaDQyMSxoNDIyLGg0MjMsaDQyNCxoNDI1LGg0MjYsaDQyNyxoNDI4LGg0MjksaDQzMCxoNDMxLGg0MzIsaDQzMyxoNDM0LGg0MzUsaDQzNixoNDM3LGg0MzgsaDQzOSxoNDQwLGg0NDEsaDQ0MixoNDQzLGg0NDQsaDQ0NSxoNDQ2LGg0NDcsaDQ0OCxoNDQ5LGg0NTAsaDQ1MSxoNDUyLGg0NTMsaDQ1NCxoNDU1LGg0NTYsaDQ1NyxoNDU4LGg0NTksaDQ2MCxoNDYxLGg0NjIsaDQ2MyxoNDY0LGg0NjUsaDQ2NixoNDY3LGg0NjgsaDQ2OSxoNDcwLGg0NzEsaDQ3MixoNDczLGg0NzQsaDQ3NSxoNDc2LGg0NzcsaDQ3OCxoNDc5LGg0ODAsaDQ4MSxoNDgyLGg0ODMsaDQ4NCxoNDg1LGg0ODYsaDQ4NyxoNDg4LGg0ODksaDQ5MCxoNDkxLGg0OTIsaDQ5MyxoNDk0LGg0OTUsaDQ5NixoNDk3LGg0OTgsaDQ5OSxoNTAwLGg1MDEsaDUwMixoNTAzLGg1MDQsaDUwNSxoNTA2LGg1MDcsaDUwOCxoNTA5LGg1MTAsaDUxMQowLDEsMiwzLDQsNSw2LDcsOCw5LDEwLDExLDEyLDEzLDE0LDE1LDE2LDE3LDE4LDE5LDIwLDIxLDIyLDIzLDI0LDI1LDI2LDI3LDI4LDI5LDMwLDMxLDMyLDMzLDM0LDM1LDM2LDM3LDM4LDM5LDQwLDQxLDQyLDQzLDQ0LDQ1LDQ2LDQ3LDQ4LDQ5LDUwLDUxLDUyLDUzLDU0LDU1LDU2LDU3LDU4LDU5LDYwLDYxLDYyLDYzLDY0LDY1LDY2LDY3LDY4LDY5LDcwLDcxLDcyLDczLDc0LDc1LDc2LDc3LDc4LDc5LDgwLDgxLDgyLDgzLDg0LDg1LDg2LDg3LDg4LDg5LDkwLDkxLDkyLDkzLDk0LDk1LDk2LDk3LDk4LDk5LDEwMCwxMDEsMTAyLDEwMywxMDQsMTA1LDEwNiwxMDcsMTA4LDEwOSwxMTAsMTExLDExMiwxMTMsMTE0LDExNSwxMTYsMTE3LDExOCwxMTksMTIwLDEyMSwxMjIsMTIzLDEyNCwxMjUsMTI2LDEyNywxMjgsMTI5LDEzMCwxMzEsMTMyLDEzMywxMzQsMTM1LDEzNiwxMzcsMTM4LDEzOSwxNDAsMTQxLDE0MiwxNDMsMTQ0LDE0NSwxNDYsMTQ3LDE0OCwxNDksMTUwLDE1MSwxNTIsMTUzLDE1NCwxNTUsMTU2LDE1NywxNTgsMTU5LDE2MCwxNjEsMTYyLDE2MywxNjQsMTY1LDE2NiwxNjcsMTY4LDE2OSwxNzAsMTcxLDE3MiwxNzMsMTc0LDE3NSwxNzYsMTc3LDE3OCwxNzksMTgwLDE4MSwxODIsMTgzLDE4NCwxODUsMTg2LDE4NywxODgsMTg5LDE5MCwxOTEsMTkyLDE5MywxOTQsMTk1LDE5NiwxOTcsMTk4LDE5OSwyMDAsMjAxLDIwMiwyMDMsMjA0LDIwNSwyMDYsMjA3LDIwOCwyMDksMjEwLDIxMSwyMTIsMjEzLDIxNCwyMTUsMjE2LDIxNywyMTgsMjE5LDIyMCwyMjEsMjIyLDIyMywyMjQsMjI1LDIyNiwyMjcsMjI4LDIyOSwyMzAsMjMxLDIzMiwyMzMsMjM0LDIzNSwyMzYsMjM3LDIzOCwyMzksMjQwLDI0MSwyNDIsMjQzLDI0NCwyNDUsMjQ2LDI0NywyNDgsMjQ5LDI1MCwyNTEsMjUyLDI1MywyNTQsMjU1LDI1NiwyNTcsMjU4LDI1OSwyNjAsMjYxLDI2MiwyNjMsMjY0LDI2NSwyNjYsMjY3LDI2OCwyNjksMjcwLDI3MSwyNzIsMjczLDI3NCwyNzUsMjc2LDI3NywyNzgsMjc5LDI4MCwyODEsMjgyLDI4MywyODQsMjg1LDI4NiwyODcsMjg4LDI4OSwyOTAsMjkxLDI5MiwyOTMsMjk0LDI5NSwyOTYsMjk3LDI5OCwyOTksMzAwLDMwMSwzMDIsMzAzLDMwNCwzMDUsMzA2LDMwNywzMDgsMzA5LDMxMCwzMTEsMzEyLDMxMywzMTQsMzE1LDMxNiwzMTcsMzE4LDMxOSwzMjAsMzIxLDMyMiwzMjMsMzI0LDMyNSwzMjYsMzI3LDMyOCwzMjksMzMwLDMzMSwzMzIsMzMzLDMzNCwzMzUsMzM2LDMzNywzMzgsMzM5LDM0MCwzNDEsMzQyLDM0MywzNDQsMzQ1LDM0NiwzNDcsMzQ4LDM0OSwzNTAsMzUxLDM1MiwzNTMsMzU0LDM1NSwzNTYsMzU3LDM1OCwzNTksMzYwLDM2MSwzNjIsMzYzLDM2NCwzNjUsMzY2LDM2NywzNjgsMzY5LDM3MCwzNzEsMzcyLDM3MywzNzQsMzc1LDM3NiwzNzcsMzc4LDM3OSwzODAsMzgxLDM4MiwzODMsMzg0LDM4NSwzODYsMzg3LDM4OCwzODksMzkwLDM5MSwzOTIsMzkzLDM5NCwzOTUsMzk2LDM5NywzOTgsMzk5LDQwMCw0MDEsNDAyLDQwMyw0MDQsNDA1LDQwNiw0MDcsNDA4LDQwOSw0MTAsNDExLDQxMiw0MTMsNDE0LDQxNSw0MTYsNDE3LDQxOCw0MTksNDIwLDQyMSw0MjIsNDIzLDQyNCw0MjUsNDI2LDQyNyw0MjgsNDI5LDQzMCw0MzEsNDMyLDQzMyw0MzQsNDM1LDQzNiw0MzcsNDM4LDQzOSw0NDAsNDQxLDQ0Miw0NDMsNDQ0LDQ0NSw0NDYsNDQ3LDQ0OCw0NDksNDUwLDQ1MSw0NTIsNDUzLDQ1NCw0NTUsNDU2LDQ1Nyw0NTgsNDU5LDQ2MCw0NjEsNDYyLDQ2Myw0NjQsNDY1LDQ2Niw0NjcsNDY4LDQ2OSw0NzAsNDcxLDQ3Miw0NzMsNDc0LDQ3NSw0NzYsNDc3LDQ3OCw0NzksNDgwLDQ4MSw0ODIsNDgzLDQ4NCw0ODUsNDg2LDQ4Nyw0ODgsNDg5LDQ5MCw0OTEsNDkyLDQ5Myw0OTQsNDk1LDQ5Niw0OTcsNDk4LDQ5OSw1MDAsNTAxLDUwMiw1MDMsNTA0LDUwNSw1MDYsNTA3LDUwOCw1MDksNTEwLDUxMQo=","options":{},"expected":{"headers":["h0","h1","h2","h3","h4","h5","h6","h7","h8","h9","h10","h11","h12","h13","h14","h15","h16","h17","h18","h19","h20","h21","h22","h23","h24","h25","h26","h27","h28","h29","h30","h31","h32","h33","h34","h35","h36","h37","h38","h39","h40","h41","h42","h43","h44","h45","h46","h47","h48","h49","h50","h51","h52","h53","h54","h55","h56","h57","h58","h59","h60","h61","h62","h63","h64","h65","h66","h67","h68","h69","h70","h71","h72","h73","h74","h75","h76","h77","h78","h79","h80","h81","h82","h83","h84","h85","h86","h87","h88","h89","h90","h91","h92","h93","h94","h95","h96","h97","h98","h99","h100","h101","h102","h103","h104","h105","h106","h107","h108","h109","h110","h111","h112","h113","h114","h115","h116","h117","h118","h119","h120","h121","h122","h123","h124","h125","h126","h127","h128","h129","h130","h131","h132","h133","h134","h135","h136","h137","h138","h139","h140","h141","h142","h143","h144","h145","h146","h147","h148","h149","h150","h151","h152","h153","h154","h155","h156","h157","h158","h159","h160","h161","h162","h163","h164","h165","h166","h167","h168","h169","h170","h171","h172","h173","h174","h175","h176","h177","h178","h179","h180","h181","h182","h183","h184","h185","h186","h187","h188","h189","h190","h191","h192","h193","h194","h195","h196","h197","h198","h199","h200","h201","h202","h203","h204","h205","h206","h207","h208","h209","h210","h211","h212","h213","h214","h215","h216","h217","h218","h219","h220","h221","h222","h223","h224","h225","h226","h227","h228","h229","h230","h231","h232","h233","h234","h235","h236","h237","h238","h239","h240","h241","h242","h243","h244","h245","h246","h247","h248","h249","h250","h251","h252","h253","h254","h255","h256","h257","h258","h259","h260","h261","h262","h263","h264","h265","h266","h267","h268","h269","h270","h271","h272","h273","h274","h275","h276","h277","h278","h279","h280","h281","h282","h283","h284","h285","h286","h287","h288","h289","h290","h291","h292","h293","h294","h295","h296","h297","h298","h299","h300","h301","h302","h303","h304","h305","h306","h307","h308","h309","h310","h311","h312","h313","h314","h315","h316","h317","h318","h319","h320","h321","h322","h323","h324","h325","h326","h327","h328","h329","h330","h331","h332","h333","h334","h335","h336","h337","h338","h339","h340","h341","h342","h343","h344","h345","h346","h347","h348","h349","h350","h351","h352","h353","h354","h355","h356","h357","h358","h359","h360","h361","h362","h363","h364","h365","h366","h367","h368","h369","h370","h371","h372","h373","h374","h375","h376","h377","h378","h379","h380","h381","h382","h383","h384","h385","h386","h387","h388","h389","h390","h391","h392","h393","h394","h395","h396","h397","h398","h399","h400","h401","h402","h403","h404","h405","h406","h407","h408","h409","h410","h411","h412","h413","h414","h415","h416","h417","h418","h419","h420","h421","h422","h423","h424","h425","h426","h427","h428","h429","h430","h431","h432","h433","h434","h435","h436","h437","h438","h439","h440","h441","h442","h443","h444","h445","h446","h447","h448","h449","h450","h451","h452","h453","h454","h455","h456","h457","h458","h459","h460","h461","h462","h463","h464","h465","h466","h467","h468","h469","h470","h471","h472","h473","h474","h475","h476","h477","h478","h479","h480","h481","h482","h483","h484","h485","h486","h487","h488","h489","h490","h491","h492","h493","h494","h495","h496","h497","h498","h499","h500","h501","h502","h503","h504","h505","h506","h507","h508","h509","h510","h511"],"rows":[[["h0","0"],["h1","1"],["h2","2"],["h3","3"],["h4","4"],["h5","5"],["h6","6"],["h7","7"],["h8","8"],["h9","9"],["h10","10"],["h11","11"],["h12","12"],["h13","13"],["h14","14"],["h15","15"],["h16","16"],["h17","17"],["h18","18"],["h19","19"],["h20","20"],["h21","21"],["h22","22"],["h23","23"],["h24","24"],["h25","25"],["h26","26"],["h27","27"],["h28","28"],["h29","29"],["h30","30"],["h31","31"],["h32","32"],["h33","33"],["h34","34"],["h35","35"],["h36","36"],["h37","37"],["h38","38"],["h39","39"],["h40","40"],["h41","41"],["h42","42"],["h43","43"],["h44","44"],["h45","45"],["h46","46"],["h47","47"],["h48","48"],["h49","49"],["h50","50"],["h51","51"],["h52","52"],["h53","53"],["h54","54"],["h55","55"],["h56","56"],["h57","57"],["h58","58"],["h59","59"],["h60","60"],["h61","61"],["h62","62"],["h63","63"],["h64","64"],["h65","65"],["h66","66"],["h67","67"],["h68","68"],["h69","69"],["h70","70"],["h71","71"],["h72","72"],["h73","73"],["h74","74"],["h75","75"],["h76","76"],["h77","77"],["h78","78"],["h79","79"],["h80","80"],["h81","81"],["h82","82"],["h83","83"],["h84","84"],["h85","85"],["h86","86"],["h87","87"],["h88","88"],["h89","89"],["h90","90"],["h91","91"],["h92","92"],["h93","93"],["h94","94"],["h95","95"],["h96","96"],["h97","97"],["h98","98"],["h99","99"],["h100","100"],["h101","101"],["h102","102"],["h103","103"],["h104","104"],["h105","105"],["h106","106"],["h107","107"],["h108","108"],["h109","109"],["h110","110"],["h111","111"],["h112","112"],["h113","113"],["h114","114"],["h115","115"],["h116","116"],["h117","117"],["h118","118"],["h119","119"],["h120","120"],["h121","121"],["h122","122"],["h123","123"],["h124","124"],["h125","125"],["h126","126"],["h127","127"],["h128","128"],["h129","129"],["h130","130"],["h131","131"],["h132","132"],["h133","133"],["h134","134"],["h135","135"],["h136","136"],["h137","137"],["h138","138"],["h139","139"],["h140","140"],["h141","141"],["h142","142"],["h143","143"],["h144","144"],["h145","145"],["h146","146"],["h147","147"],["h148","148"],["h149","149"],["h150","150"],["h151","151"],["h152","152"],["h153","153"],["h154","154"],["h155","155"],["h156","156"],["h157","157"],["h158","158"],["h159","159"],["h160","160"],["h161","161"],["h162","162"],["h163","163"],["h164","164"],["h165","165"],["h166","166"],["h167","167"],["h168","168"],["h169","169"],["h170","170"],["h171","171"],["h172","172"],["h173","173"],["h174","174"],["h175","175"],["h176","176"],["h177","177"],["h178","178"],["h179","179"],["h180","180"],["h181","181"],["h182","182"],["h183","183"],["h184","184"],["h185","185"],["h186","186"],["h187","187"],["h188","188"],["h189","189"],["h190","190"],["h191","191"],["h192","192"],["h193","193"],["h194","194"],["h195","195"],["h196","196"],["h197","197"],["h198","198"],["h199","199"],["h200","200"],["h201","201"],["h202","202"],["h203","203"],["h204","204"],["h205","205"],["h206","206"],["h207","207"],["h208","208"],["h209","209"],["h210","210"],["h211","211"],["h212","212"],["h213","213"],["h214","214"],["h215","215"],["h216","216"],["h217","217"],["h218","218"],["h219","219"],["h220","220"],["h221","221"],["h222","222"],["h223","223"],["h224","224"],["h225","225"],["h226","226"],["h227","227"],["h228","228"],["h229","229"],["h230","230"],["h231","231"],["h232","232"],["h233","233"],["h234","234"],["h235","235"],["h236","236"],["h237","237"],["h238","238"],["h239","239"],["h240","240"],["h241","241"],["h242","242"],["h243","243"],["h244","244"],["h245","245"],["h246","246"],["h247","247"],["h248","248"],["h249","249"],["h250","250"],["h251","251"],["h252","252"],["h253","253"],["h254","254"],["h255","255"],["h256","256"],["h257","257"],["h258","258"],["h259","259"],["h260","260"],["h261","261"],["h262","262"],["h263","263"],["h264","264"],["h265","265"],["h266","266"],["h267","267"],["h268","268"],["h269","269"],["h270","270"],["h271","271"],["h272","272"],["h273","273"],["h274","274"],["h275","275"],["h276","276"],["h277","277"],["h278","278"],["h279","279"],["h280","280"],["h281","281"],["h282","282"],["h283","283"],["h284","284"],["h285","285"],["h286","286"],["h287","287"],["h288","288"],["h289","289"],["h290","290"],["h291","291"],["h292","292"],["h293","293"],["h294","294"],["h295","295"],["h296","296"],["h297","297"],["h298","298"],["h299","299"],["h300","300"],["h301","301"],["h302","302"],["h303","303"],["h304","304"],["h305","305"],["h306","306"],["h307","307"],["h308","308"],["h309","309"],["h310","310"],["h311","311"],["h312","312"],["h313","313"],["h314","314"],["h315","315"],["h316","316"],["h317","317"],["h318","318"],["h319","319"],["h320","320"],["h321","321"],["h322","322"],["h323","323"],["h324","324"],["h325","325"],["h326","326"],["h327","327"],["h328","328"],["h329","329"],["h330","330"],["h331","331"],["h332","332"],["h333","333"],["h334","334"],["h335","335"],["h336","336"],["h337","337"],["h338","338"],["h339","339"],["h340","340"],["h341","341"],["h342","342"],["h343","343"],["h344","344"],["h345","345"],["h346","346"],["h347","347"],["h348","348"],["h349","349"],["h350","350"],["h351","351"],["h352","352"],["h353","353"],["h354","354"],["h355","355"],["h356","356"],["h357","357"],["h358","358"],["h359","359"],["h360","360"],["h361","361"],["h362","362"],["h363","363"],["h364","364"],["h365","365"],["h366","366"],["h367","367"],["h368","368"],["h369","369"],["h370","370"],["h371","371"],["h372","372"],["h373","373"],["h374","374"],["h375","375"],["h376","376"],["h377","377"],["h378","378"],["h379","379"],["h380","380"],["h381","381"],["h382","382"],["h383","383"],["h384","384"],["h385","385"],["h386","386"],["h387","387"],["h388","388"],["h389","389"],["h390","390"],["h391","391"],["h392","392"],["h393","393"],["h394","394"],["h395","395"],["h396","396"],["h397","397"],["h398","398"],["h399","399"],["h400","400"],["h401","401"],["h402","402"],["h403","403"],["h404","404"],["h405","405"],["h406","406"],["h407","407"],["h408","408"],["h409","409"],["h410","410"],["h411","411"],["h412","412"],["h413","413"],["h414","414"],["h415","415"],["h416","416"],["h417","417"],["h418","418"],["h419","419"],["h420","420"],["h421","421"],["h422","422"],["h423","423"],["h424","424"],["h425","425"],["h426","426"],["h427","427"],["h428","428"],["h429","429"],["h430","430"],["h431","431"],["h432","432"],["h433","433"],["h434","434"],["h435","435"],["h436","436"],["h437","437"],["h438","438"],["h439","439"],["h440","440"],["h441","441"],["h442","442"],["h443","443"],["h444","444"],["h445","445"],["h446","446"],["h447","447"],["h448","448"],["h449","449"],["h450","450"],["h451","451"],["h452","452"],["h453","453"],["h454","454"],["h455","455"],["h456","456"],["h457","457"],["h458","458"],["h459","459"],["h460","460"],["h461","461"],["h462","462"],["h463","463"],["h464","464"],["h465","465"],["h466","466"],["h467","467"],["h468","468"],["h469","469"],["h470","470"],["h471","471"],["h472","472"],["h473","473"],["h474","474"],["h475","475"],["h476","476"],["h477","477"],["h478","478"],["h479","479"],["h480","480"],["h481","481"],["h482","482"],["h483","483"],["h484","484"],["h485","485"],["h486","486"],["h487","487"],["h488","488"],["h489","489"],["h490","490"],["h491","491"],["h492","492"],["h493","493"],["h494","494"],["h495","495"],["h496","496"],["h497","497"],["h498","498"],["h499","499"],["h500","500"],["h501","501"],["h502","502"],["h503","503"],["h504","504"],["h505","505"],["h506","506"],["h507","507"],["h508","508"],["h509","509"],["h510","510"],["h511","511"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}},{"name":"cols_513","data":"aDAsaDEsaDIsaDMsaDQsaDUsaDYsaDcsaDgsaDksaDEwLGgxMSxoMTIsaDEzLGgxNCxoMTUsaDE2LGgxNyxoMTgsaDE5LGgyMCxoMjEsaDIyLGgyMyxoMjQsaDI1LGgyNixoMjcsaDI4LGgyOSxoMzAsaDMxLGgzMixoMzMsaDM0LGgzNSxoMzYsaDM3LGgzOCxoMzksaDQwLGg0MSxoNDIsaDQzLGg0NCxoNDUsaDQ2LGg0NyxoNDgsaDQ5LGg1MCxoNTEsaDUyLGg1MyxoNTQsaDU1LGg1NixoNTcsaDU4LGg1OSxoNjAsaDYxLGg2MixoNjMsaDY0LGg2NSxoNjYsaDY3LGg2OCxoNjksaDcwLGg3MSxoNzIsaDczLGg3NCxoNzUsaDc2LGg3NyxoNzgsaDc5LGg4MCxoODEsaDgyLGg4MyxoODQsaDg1LGg4NixoODcsaDg4LGg4OSxoOTAsaDkxLGg5MixoOTMsaDk0LGg5NSxoOTYsaDk3LGg5OCxoOTksaDEwMCxoMTAxLGgxMDIsaDEwMyxoMTA0LGgxMDUsaDEwNixoMTA3LGgxMDgsaDEwOSxoMTEwLGgxMTEsaDExMixoMTEzLGgxMTQsaDExNSxoMTE2LGgxMTcsaDExOCxoMTE5LGgxMjAsaDEyMSxoMTIyLGgxMjMsaDEyNCxoMTI1LGgxMjYsaDEyNyxoMTI4LGgxMjksaDEzMCxoMTMxLGgxMzIsaDEzMyxoMTM0LGgxMzUsaDEzNixoMTM3LGgxMzgsaDEzOSxoMTQwLGgxNDEsaDE0MixoMTQzLGgxNDQsaDE0NSxoMTQ2LGgxNDcsaDE0OCxoMTQ5LGgxNTAsaDE1MSxoMTUyLGgxNTMsaDE1NCxoMTU1LGgxNTYsaDE1NyxoMTU4LGgxNTksaDE2MCxoMTYxLGgxNjIsaDE2MyxoMTY0LGgxNjUsaDE2NixoMTY3LGgxNjgsaDE2OSxoMTcwLGgxNzEsaDE3MixoMTczLGgxNzQsaDE3NSxoMTc2LGgxNzcsaDE3OCxoMTc5LGgxODAsaDE4MSxoMTgyLGgxODMsaDE4NCxoMTg1LGgxODYsaDE4NyxoMTg4LGgxODksaDE5MCxoMTkxLGgxOTIsaDE5MyxoMTk0LGgxOTUsaDE5NixoMTk3LGgxOTgsaDE5OSxoMjAwLGgyMDEsaDIwMixoMjAzLGgyMDQsaDIwNSxoMjA2LGgyMDcsaDIwOCxoMjA5LGgyMTAsaDIxMSxoMjEyLGgyMTMsaDIxNCxoMjE1LGgyMTYsaDIxNyxoMjE4LGgyMTksaDIyMCxoMjIxLGgyMjIsaDIyMyxoMjI0LGgyMjUsaDIyNixoMjI3LGgyMjgsaDIyOSxoMjMwLGgyMzEsaDIzMixoMjMzLGgyMzQsaDIzNSxoMjM2LGgyMzcsaDIzOCxoMjM5LGgyNDAsaDI0MSxoMjQyLGgyNDMsaDI0NCxoMjQ1LGgyNDYsaDI0NyxoMjQ4LGgyNDksaDI1MCxoMjUxLGgyNTIsaDI1MyxoMjU0LGgyNTUsaDI1NixoMjU3LGgyNTgsaDI1OSxoMjYwLGgyNjEsaDI2MixoMjYzLGgyNjQsaDI2NSxoMjY2LGgyNjcsaDI2OCxoMjY5LGgyNzAsaDI3MSxoMjcyLGgyNzMsaDI3NCxoMjc1LGgyNzYsaDI3NyxoMjc4LGgyNzksaDI4MCxoMjgxLGgyODIsaDI4MyxoMjg0LGgyODUsaDI4NixoMjg3LGgyODgsaDI4OSxoMjkwLGgyOTEsaDI5MixoMjkzLGgyOTQsaDI5NSxoMjk2LGgyOTcsaDI5OCxoMjk5LGgzMDAsaDMwMSxoMzAyLGgzMDMsaDMwNCxoMzA1LGgzMDYsaDMwNyxoMzA4LGgzMDksaDMxMCxoMzExLGgzMTIsaDMxMyxoMzE0LGgzMTUsaDMxNixoMzE3LGgzMTgsaDMxOSxoMzIwLGgzMjEsaDMyMixoMzIzLGgzMjQsaDMyNSxoMzI2LGgzMjcsaDMyOCxoMzI5LGgzMzAsaDMzMSxoMzMyLGgzMzMsaDMzNCxoMzM1LGgzMzYsaDMzNyxoMzM4LGgzMzksaDM0MCxoMzQxLGgzNDIsaDM0MyxoMzQ0LGgzNDUsaDM0NixoMzQ3LGgzNDgsaDM0OSxoMzUwLGgzNTEsaDM1MixoMzUzLGgzNTQsaDM1NSxoMzU2LGgzNTcsaDM1OCxoMzU5LGgzNjAsaDM2MSxoMzYyLGgzNjMsaDM2NCxoMzY1LGgzNjYsaDM2NyxoMzY4LGgzNjksaDM3MCxoMzcxLGgzNzIsaDM3MyxoMzc0LGgzNzUsaDM3NixoMzc3LGgzNzgsaDM3OSxoMzgwLGgzODEsaDM4MixoMzgzLGgzODQsaDM4NSxoMzg2LGgzODcsaDM4OCxoMzg5LGgzOTAsaDM5MSxoMzkyLGgzOTMsaDM5NCxoMzk1LGgzOTYsaDM5NyxoMzk4LGgzOTksaDQwMCxoNDAxLGg0MDIsaDQwMyxoNDA0LGg0MDUsaDQwNixoNDA3LGg0MDgsaDQwOSxoNDEwLGg0MTEsaDQxMixoNDEzLGg0MTQsaDQxNSxoNDE2LGg0MTcsaDQxOCxoNDE5LGg0MjAsaDQyMSxoNDIyLGg0MjMsaDQyNCxoNDI1LGg0MjYsaDQyNyxoNDI4LGg0MjksaDQzMCxoNDMxLGg0MzIsaDQzMyxoNDM0LGg0MzUsaDQzNixoNDM3LGg0MzgsaDQzOSxoNDQwLGg0NDEsaDQ0MixoNDQzLGg0NDQsaDQ0NSxoNDQ2LGg0NDcsaDQ0OCxoNDQ5LGg0NTAsaDQ1MSxoNDUyLGg0NTMsaDQ1NCxoNDU1LGg0NTYsaDQ1NyxoNDU4LGg0NTksaDQ2MCxoNDYxLGg0NjIsaDQ2MyxoNDY0LGg0NjUsaDQ2NixoNDY3LGg0NjgsaDQ2OSxoNDcwLGg0NzEsaDQ3MixoNDczLGg0NzQsaDQ3NSxoNDc2LGg0NzcsaDQ3OCxoNDc5LGg0ODAsaDQ4MSxoNDgyLGg0ODMsaDQ4NCxoNDg1LGg0ODYsaDQ4NyxoNDg4LGg0ODksaDQ5MCxoNDkxLGg0OTIsaDQ5MyxoNDk0LGg0OTUsaDQ5NixoNDk3LGg0OTgsaDQ5OSxoNTAwLGg1MDEsaDUwMixoNTAzLGg1MDQsaDUwNSxoNTA2LGg1MDcsaDUwOCxoNTA5LGg1MTAsaDUxMSxoNTEyCjAsMSwyLDMsNCw1LDYsNyw4LDksMTAsMTEsMTIsMTMsMTQsMTUsMTYsMTcsMTgsMTksMjAsMjEsMjIsMjMsMjQsMjUsMjYsMjcsMjgsMjksMzAsMzEsMzIsMzMsMzQsMzUsMzYsMzcsMzgsMzksNDAsNDEsNDIsNDMsNDQsNDUsNDYsNDcsNDgsNDksNTAsNTEsNTIsNTMsNTQsNTUsNTYsNTcsNTgsNTksNjAsNjEsNjIsNjMsNjQsNjUsNjYsNjcsNjgsNjksNzAsNzEsNzIsNzMsNzQsNzUsNzYsNzcsNzgsNzksODAsODEsODIsODMsODQsODUsODYsODcsODgsODksOTAsOTEsOTIsOTMsOTQsOTUsOTYsOTcsOTgsOTksMTAwLDEwMSwxMDIsMTAzLDEwNCwxMDUsMTA2LDEwNywxMDgsMTA5LDExMCwxMTEsMTEyLDExMywxMTQsMTE1LDExNiwxMTcsMTE4LDExOSwxMjAsMTIxLDEyMiwxMjMsMTI0LDEyNSwxMjYsMTI3LDEyOCwxMjksMTMwLDEzMSwxMzIsMTMzLDEzNCwxMzUsMTM2LDEzNywxMzgsMTM5LDE0MCwxNDEsMTQyLDE0MywxNDQsMTQ1LDE0NiwxNDcsMTQ4LDE0OSwxNTAsMTUxLDE1MiwxNTMsMTU0LDE1NSwxNTYsMTU3LDE1OCwxNTksMTYwLDE2MSwxNjIsMTYzLDE2NCwxNjUsMTY2LDE2NywxNjgsMTY5LDE3MCwxNzEsMTcyLDE3MywxNzQsMTc1LDE3NiwxNzcsMTc4LDE3OSwxODAsMTgxLDE4MiwxODMsMTg0LDE4NSwxODYsMTg3LDE4OCwxODksMTkwLDE5MSwxOTIsMTkzLDE5NCwxOTUsMTk2LDE5NywxOTgsMTk5LDIwMCwyMDEsMjAyLDIwMywyMDQsMjA1LDIwNiwyMDcsMjA4LDIwOSwyMTAsMjExLDIxMiwyMTMsMjE0LDIxNSwyMTYsMjE3LDIxOCwyMTksMjIwLDIyMSwyMjIsMjIzLDIyNCwyMjUsMjI2LDIyNywyMjgsMjI5LDIzMCwyMzEsMjMyLDIzMywyMzQsMjM1LDIzNiwyMzcsMjM4LDIzOSwyNDAsMjQxLDI0MiwyNDMsMjQ0LDI0NSwyNDYsMjQ3LDI0OCwyNDksMjUwLDI1MSwyNTIsMjUzLDI1NCwyNTUsMjU2LDI1NywyNTgsMjU5LDI2MCwyNjEsMjYyLDI2MywyNjQsMjY1LDI2NiwyNjcsMjY4LDI2OSwyNzAsMjcxLDI3MiwyNzMsMjc0LDI3NSwyNzYsMjc3LDI3OCwyNzksMjgwLDI4MSwyODIsMjgzLDI4NCwyODUsMjg2LDI4NywyODgsMjg5LDI5MCwyOTEsMjkyLDI5MywyOTQsMjk1LDI5NiwyOTcsMjk4LDI5OSwzMDAsMzAxLDMwMiwzMDMsMzA0LDMwNSwzMDYsMzA3LDMwOCwzMDksMzEwLDMxMSwzMTIsMzEzLDMxNCwzMTUsMzE2LDMxNywzMTgsMzE5LDMyMCwzMjEsMzIyLDMyMywzMjQsMzI1LDMyNiwzMjcsMzI4LDMyOSwzMzAsMzMxLDMzMiwzMzMsMzM0LDMzNSwzMzYsMzM3LDMzOCwzMzksMzQwLDM0MSwzNDIsMzQzLDM0NCwzNDUsMzQ2LDM0NywzNDgsMzQ5LDM1MCwzNTEsMzUyLDM1MywzNTQsMzU1LDM1NiwzNTcsMzU4LDM1OSwzNjAsMzYxLDM2MiwzNjMsMzY0LDM2NSwzNjYsMzY3LDM2OCwzNjksMzcwLDM3MSwzNzIsMzczLDM3NCwzNzUsMzc2LDM3NywzNzgsMzc5LDM4MCwzODEsMzgyLDM4MywzODQsMzg1LDM4NiwzODcsMzg4LDM4OSwzOTAsMzkxLDM5MiwzOTMsMzk0LDM5NSwzOTYsMzk3LDM5OCwzOTksNDAwLDQwMSw0MDIsNDAzLDQwNCw0MDUsNDA2LDQwNyw0MDgsNDA5LDQxMCw0MTEsNDEyLDQxMyw0MTQsNDE1LDQxNiw0MTcsNDE4LDQxOSw0MjAsNDIxLDQyMiw0MjMsNDI0LDQyNSw0MjYsNDI3LDQyOCw0MjksNDMwLDQzMSw0MzIsNDMzLDQzNCw0MzUsNDM2LDQzNyw0MzgsNDM5LDQ0MCw0NDEsNDQyLDQ0Myw0NDQsNDQ1LDQ0Niw0NDcsNDQ4LDQ0OSw0NTAsNDUxLDQ1Miw0NTMsNDU0LDQ1NSw0NTYsNDU3LDQ1OCw0NTksNDYwLDQ2MSw0NjIsNDYzLDQ2NCw0NjUsNDY2LDQ2Nyw0NjgsNDY5LDQ3MCw0NzEsNDcyLDQ3Myw0NzQsNDc1LDQ3Niw0NzcsNDc4LDQ3OSw0ODAsNDgxLDQ4Miw0ODMsNDg0LDQ4NSw0ODYsNDg3LDQ4OCw0ODksNDkwLDQ5MSw0OTIsNDkzLDQ5NCw0OTUsNDk2LDQ5Nyw0OTgsNDk5LDUwMCw1MDEsNTAyLDUwMyw1MDQsNTA1LDUwNiw1MDcsNTA4LDUwOSw1MTAsNTExLDUxMgo=","options":{},"expected":{"error":"The file exceeds the 512-column import limit."}},{"name":"cols_600_empty_skipped","data":"YSxiCiwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLAoxLDIK","options":{},"expected":{"headers":["a","b"],"rows":[[["a","1"],["b","2"]]],"notices":[],"options":{"delimiter":",","encoding":"utf-8-sig","has_header":true}}}]'''

_SHOWING = "Showing the first"


def _frozen_cases() -> list[dict]:
    return json.loads(_FROZEN_CSV_CASES_JSON)


def _pairs(rows):
    return [[[key, value] for key, value in row.items()] for row in rows]


def _write(tmp_path: Path, data: bytes, name: str = "case.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _csv_rows(count: int) -> str:
    return "id,name,note\n" + "".join(f"{i},name{i},note {i}\n" for i in range(count))


def _write_parquet(tmp_path: Path, table: pa.Table, name: str = "data.parquet", row_group_size: int | None = None) -> Path:
    path = tmp_path / name
    pq.write_table(table, path, row_group_size=row_group_size)
    return path


# ---- ImportLimitError -------------------------------------------------------

def test_import_limit_error_is_file_import_error_with_kind() -> None:
    error = ImportLimitError("too big", limit_kind="rows")
    assert isinstance(error, FileImportError)
    assert error.limit_kind == "rows"
    assert str(error) == "too big"


def test_csv_row_cell_and_byte_limits_raise_import_limit_error(tmp_path: Path, monkeypatch) -> None:
    path = _write(tmp_path, _csv_rows(10).encode("utf-8"))

    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 5)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "rows"
    assert str(info.value) == "The file exceeds the 5-row import limit."
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 100_000)

    monkeypatch.setattr(file_import, "MAX_CELLS", 10)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "cells"
    assert str(info.value) == "The file exceeds the 10-cell import limit."
    monkeypatch.setattr(file_import, "MAX_CELLS", 500_000)

    monkeypatch.setattr(file_import, "MAX_SOURCE_BYTES", 50)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "bytes"
    assert str(info.value) == f"{path.name} is larger than the 0 MiB import limit."


def test_column_limit_stays_a_plain_file_import_error(tmp_path: Path) -> None:
    header = ",".join(f"h{i}" for i in range(513))
    values = ",".join(str(i) for i in range(513))
    path = _write(tmp_path, f"{header}\n{values}\n".encode("utf-8"))
    with pytest.raises(FileImportError) as info:
        parse_file(path)
    assert type(info.value) is FileImportError
    assert str(info.value) == "The file exceeds the 512-column import limit."


def test_parquet_limits_raise_import_limit_error(tmp_path: Path, monkeypatch) -> None:
    table = pa.table({"id": list(range(10)), "name": ["x" * 40] * 10})
    path = _write_parquet(tmp_path, table)

    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 5)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "rows"
    assert str(info.value) == "The file exceeds the 5-row import limit."
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 100_000)

    monkeypatch.setattr(file_import, "MAX_PARQUET_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "uncompressed"
    assert str(info.value) == (
        f"{path.name} expands beyond the 0 MiB Parquet data limit."
    )
    monkeypatch.setattr(file_import, "MAX_PARQUET_UNCOMPRESSED_BYTES", 80 * 1024 * 1024)

    monkeypatch.setattr(file_import, "MAX_PARQUET_TEXT_BYTES", 10)
    with pytest.raises(ImportLimitError) as info:
        parse_file(path)
    assert info.value.limit_kind == "text"
    assert str(info.value) == "Converted Parquet text exceeds the 0 MiB result limit."


# ---- CSV parser split: frozen baseline comparison ----------------------------

@pytest.mark.parametrize("case", _frozen_cases(), ids=lambda case: case["name"])
def test_csv_parser_matches_frozen_baseline(tmp_path: Path, case: dict) -> None:
    path = _write(tmp_path, base64.b64decode(case["data"]))
    options = normalize_options("csv", case["options"])
    expected = case["expected"]
    if "error" in expected:
        with pytest.raises(FileImportError) as info:
            file_import._parse_csv(path, options, None)
        assert str(info.value) == expected["error"]
        return
    candidate = file_import._parse_csv(path, options, None)
    assert candidate.headers == expected["headers"]
    assert _pairs(candidate.rows) == expected["rows"]
    assert candidate.notices == expected["notices"]
    assert candidate.options == expected["options"]


# ---- parse_head -------------------------------------------------------------

@pytest.mark.parametrize("case", _frozen_cases(), ids=lambda case: case["name"])
def test_parse_head_equals_first_rows_of_full_parse(tmp_path: Path, case: dict) -> None:
    path = _write(tmp_path, base64.b64decode(case["data"]))
    expected = case["expected"]
    if "error" in expected:
        with pytest.raises(FileImportError) as info:
            parse_head(path, case["options"], rows=1000)
        assert str(info.value) == expected["error"]
        return
    full = file_import._parse_csv(path, normalize_options("csv", case["options"]), None)
    for rows_wanted in (1000, 3):
        head = parse_head(path, case["options"], rows=rows_wanted)
        assert head.headers == full.headers
        assert _pairs(head.rows) == _pairs(full.rows[:rows_wanted])
        has_notice = any(note.startswith(_SHOWING) for note in head.notices)
        assert has_notice == (len(full.rows) > rows_wanted)


def test_parse_head_drops_partial_record_at_prefix_cut(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(file_import, "HEAD_PREFIX_BYTES", 4096)
    path = _write(tmp_path, _csv_rows(20_000).encode("utf-8"), name="big.csv")
    full = file_import._parse_csv(path, normalize_options("csv", None), None)
    assert len(full.rows) == 20_000

    head = parse_head(path, None, rows=1000)
    shown = len(head.rows)
    assert 0 < shown < 1000
    assert _pairs(head.rows) == _pairs(full.rows[:shown])
    assert all(row["note"] == f"note {row['id']}" for row in head.rows)
    assert any(note.startswith(_SHOWING) for note in head.notices)

    small = parse_head(path, None, rows=3)
    assert _pairs(small.rows) == _pairs(full.rows[:3])
    assert small.notices == [
        "Showing the first 3 of a large file.",
        "Column count taken from the first part of the file.",
    ]


def test_parse_head_utf8_character_straddles_prefix_cut(tmp_path: Path, monkeypatch) -> None:
    cut = 4096
    monkeypatch.setattr(file_import, "HEAD_PREFIX_BYTES", cut)
    head_bytes = ("a,b\n" + "1,2\n" * 10).encode("utf-8")
    pad = cut - 1 - len(head_bytes) - 2  # the two-byte "é" starts at byte cut-1
    data = head_bytes + b"3," + b"z" * pad + "é".encode("utf-8") + b",9\n" + b"4,5\n" * 2000
    path = _write(tmp_path, data)
    head = parse_head(path, None, rows=1000)
    assert _pairs(head.rows) == _pairs(file_import._parse_csv(
        _write(tmp_path, head_bytes + b"\n", name="ten.csv"), normalize_options("csv", None), None
    ).rows)
    assert len(head.rows) == 10
    assert all(value == "" or value in {"1", "2"} for row in head.rows for value in row.values())


def test_parse_head_utf16_surrogate_pair_straddles_prefix_cut(tmp_path: Path, monkeypatch) -> None:
    cut = 4096
    monkeypatch.setattr(file_import, "HEAD_PREFIX_BYTES", cut)
    head_text = "a,b\n" + "1,2\n" * 10
    # BOM (2 bytes) + head + "3," + z's puts the emoji's high surrogate at bytes cut-2 and cut-1.
    z_count = (cut - 2 - 2 - 2 * len(head_text) - 4) // 2
    text = head_text + "3," + "z" * z_count + "\U0001F600" + ",9\n" + "4,5\n" * 2000
    data = b"\xff\xfe" + text.encode("utf-16-le")
    path = _write(tmp_path, data)
    head = parse_head(path, {"encoding": "utf-16"}, rows=1000)
    assert len(head.rows) == 10
    assert _pairs(head.rows) == _pairs(file_import._parse_csv(
        _write(tmp_path, ("a,b\n" + "1,2\n" * 10).encode("utf-16"), name="ten16.csv"),
        normalize_options("csv", {"encoding": "utf-16"}), None,
    ).rows)


def test_parse_head_quoted_newline_straddling_cut_is_dropped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(file_import, "HEAD_PREFIX_BYTES", 4096)
    data = ("a,b\n" + "1,2\n" * 10 + '3,"' + "x\n" * 3000 + '",9\n').encode("utf-8")
    path = _write(tmp_path, data)
    head = parse_head(path, None, rows=1000)
    assert len(head.rows) == 10
    assert all(row["a"] != "3" for row in head.rows)


def test_parse_head_small_file_has_no_notice(tmp_path: Path) -> None:
    path = _write(tmp_path, _csv_rows(5).encode("utf-8"), name="five.csv")
    head = parse_head(path, None, rows=1000)
    assert head.notices == []
    assert _pairs(head.rows) == _pairs(file_import._parse_csv(path, normalize_options("csv", None), None).rows)


def test_parse_head_header_only_file(tmp_path: Path) -> None:
    path = _write(tmp_path, b"a,b\n", name="header.csv")
    head = parse_head(path, None, rows=3)
    assert head.headers == ["a", "b"]
    assert head.rows == []
    assert head.notices == []


def test_parse_head_empty_file_raises_same_error_as_full_parse(tmp_path: Path) -> None:
    path = _write(tmp_path, b"", name="empty.csv")
    with pytest.raises(FileImportError) as full:
        file_import._parse_csv(path, normalize_options("csv", None), None)
    with pytest.raises(FileImportError) as head:
        parse_head(path, None, rows=3)
    assert str(head.value) == str(full.value) == "empty.csv is empty and has no header row."


def test_parse_head_ignores_row_and_cell_limits(tmp_path: Path, monkeypatch) -> None:
    path = _write(tmp_path, _csv_rows(10).encode("utf-8"), name="ten.csv")
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 5)
    monkeypatch.setattr(file_import, "MAX_CELLS", 4)
    monkeypatch.setattr(file_import, "MAX_SOURCE_BYTES", 40)
    head = parse_head(path, None, rows=3)
    assert len(head.rows) == 3
    assert head.notices == ["Showing the first 3 of a large file."]


_WIDTH_NOTICE = "Column count taken from the first part of the file."


def test_parse_head_width_notice_only_for_truncated_prefix(tmp_path: Path, monkeypatch) -> None:
    # A row wider than the head rows appears after the cut: its extra column is not in the head.
    body = "a,b\n" + "1,2\n" * 50 + "3,4,5\n"
    small = _write(tmp_path, body.encode("utf-8"), name="wide.csv")
    head = parse_head(small, None, rows=3)
    assert _WIDTH_NOTICE not in head.notices
    assert len(head.headers) == 3

    monkeypatch.setattr(file_import, "HEAD_PREFIX_BYTES", 40)
    cut_head = parse_head(small, None, rows=3)
    assert _WIDTH_NOTICE in cut_head.notices
    assert any(note.startswith(_SHOWING) for note in cut_head.notices)


def test_parse_head_rejects_other_kinds(tmp_path: Path) -> None:
    excel = _write(tmp_path, b"not really a workbook", name="book.xlsx")
    with pytest.raises(FileImportError) as info:
        parse_head(excel)
    assert str(info.value) == "A head preview is only available for CSV and Parquet files."
    with pytest.raises(FileImportError, match="only available for CSV and Parquet"):
        parse_head(_write(tmp_path, b"{}", name="data.json"))


def test_parse_head_rejects_non_positive_rows(tmp_path: Path) -> None:
    path = _write(tmp_path, _csv_rows(3).encode("utf-8"), name="three.csv")
    with pytest.raises(FileImportError, match="at least one row"):
        parse_head(path, None, rows=0)


# ---- parse_head on Parquet ----------------------------------------------------

def _parquet_table(count: int) -> pa.Table:
    return pa.table({
        "id": pa.array(range(count), type=pa.int64()),
        "name": pa.array([f"name {i}" for i in range(count)]),
        "price": pa.array([i / 4 for i in range(count)], type=pa.float64()),
        "flag": pa.array([i % 2 == 0 for i in range(count)]),
        "when": pa.array([i for i in range(count)], type=pa.timestamp("s")),
    })


def test_parquet_head_equals_first_rows_of_full_parse(tmp_path: Path) -> None:
    path = _write_parquet(tmp_path, _parquet_table(2500), row_group_size=700)
    options = normalize_options("parquet", None)
    full = file_import._parse_parquet(path, options, None)
    assert len(full.rows) == 2500
    for rows_wanted in (3, 1000, 3000):
        head = parse_head(path, None, rows=rows_wanted)
        assert head.headers == full.headers
        assert _pairs(head.rows) == _pairs(full.rows[:rows_wanted])
        has_notice = any(note.startswith(_SHOWING) for note in head.notices)
        assert has_notice == (2500 > rows_wanted)
    assert parse_head(path, None, rows=1).rows == full.rows[:1]


def test_parquet_head_refuses_nested_types_like_full_parse(tmp_path: Path) -> None:
    table = pa.table({"x": pa.array([[1, 2], [3]], type=pa.list_(pa.int64()))})
    path = _write_parquet(tmp_path, table, name="nested.parquet")
    options = normalize_options("parquet", None)
    with pytest.raises(FileImportError) as full:
        file_import._parse_parquet(path, options, None)
    with pytest.raises(FileImportError) as head:
        parse_head(path, None, rows=3)
    assert str(head.value) == str(full.value)
    assert "nested and binary types are not supported" in str(head.value)


def test_parse_file_still_reads_parquet_and_csv_unchanged(tmp_path: Path) -> None:
    path = _write_parquet(tmp_path, _parquet_table(4))
    candidate = parse_file(path)
    assert candidate.row_count == 4
    csv_path = _write(tmp_path, b"a,b\n1,2\n")
    assert parse_file(csv_path).rows[0] == {"a": "1", "b": "2"}
