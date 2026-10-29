"""Native editors for local DAX measures and common quick aggregations."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFontDatabase, QKeyEvent, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.measures import (
    DAX_FUNCTION_NAMES,
    MeasureError,
    escape_bracket_name,
    normalize_measure,
)
from analytics_studio.dialog_theme import apply_light_dialog_theme


def _dax_lexical_state(expression: str, position: int) -> tuple[bool, list[list[Any]]]:
    """Track nested function calls while skipping DAX strings and references."""
    stack: list[list[Any]] = []
    quote: str | None = None
    in_column = False
    index = 0
    position = max(0, min(position, len(expression)))
    while index < position:
        character = expression[index]
        if in_column:
            if character == "]":
                if index + 1 < position and expression[index + 1] == "]":
                    index += 2  # a doubled ']' is one ']' of the name
                    continue
                in_column = False
            index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < position and expression[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "[":
            in_column = True
        elif character == "(":
            before = expression[:index]
            match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", before)
            name = match.group(1).upper() if match else ""
            stack.append([
                name if name in DAX_FUNCTION_TEMPLATES else "",
                0,
                index + 1,
            ])
        elif character == "," and stack and stack[-1][0]:
            stack[-1][1] += 1
            stack[-1][2] = index + 1
        elif character == ")" and stack:
            stack.pop()
        index += 1
    return quote is None and not in_column, stack


def _column_argument_completion_context(
    expression: str,
    position: int,
    stack: list[list[Any]],
) -> tuple[str, str, int, int, str | None, bool] | None:
    """Return an unqualified first-argument span for supported column functions."""
    active_call = stack[-1] if stack else None
    if (
        active_call is None
        or not active_call[0]
        or active_call[0] not in _DAX_COLUMN_ARGUMENT_FUNCTIONS
        or int(active_call[1]) != 0
        or len(active_call) < 3
    ):
        return None

    start = max(0, min(int(active_call[2]), position))
    while start < position and expression[start].isspace():
        start += 1
    typed = expression[start:position]
    if typed != typed.rstrip() or any(
        character in "[]'\"(),=<>+-*/&|" for character in typed
    ):
        return None
    if typed and not (typed[0].isalpha() or typed[0] == "_"):
        return None
    return "argument", typed, start, position, None, False


def _dax_completion_span(expression: str, position: int) -> tuple[str, int, int] | None:
    """Return the identifier at the caret unless the caret is inside a literal/reference."""
    safe_context, _stack = _dax_lexical_state(expression, position)
    if not safe_context:
        return None
    position = max(0, min(position, len(expression)))
    start = position
    while start > 0 and (expression[start - 1].isalnum() or expression[start - 1] == "_"):
        start -= 1
    end = position
    while end < len(expression) and (expression[end].isalnum() or expression[end] == "_"):
        end += 1
    token = expression[start:end]
    if not token or not (token[0].isalpha() or token[0] == "_"):
        return None
    return token, start, end


def _dax_reference_completion_context(
    expression: str, position: int
) -> tuple[str, str, int, int, str | None, bool] | None:
    """Return the editable body of an open DAX bracket reference at the caret.

    The tuple is ``(kind, prefix, start, end, table_name, has_closer)``.
    Offsets are Python string offsets, not Qt UTF-16 offsets. Double-quoted
    strings and quoted table names are scanned with DAX escaping.
    """
    position = max(0, min(position, len(expression)))
    quote: str | None = None
    quote_start = -1
    open_bracket = -1
    index = 0
    while index < position:
        character = expression[index]
        if open_bracket >= 0:
            # DAX treats every character through the matching `]` as part of
            # the column reference. An apostrophe here is a legal column-name
            # character, not the start of a quoted table name.
            if character == "]":
                if index + 1 < position and expression[index + 1] == "]":
                    index += 2  # a doubled ']' is one ']' of the name
                    continue
                open_bracket = -1
            index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < position and expression[index + 1] == quote:
                    index += 2
                    continue
                quote = None
                quote_start = -1
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            quote_start = index
        elif character == "[":
            open_bracket = index
        index += 1

    if quote == "'" and quote_start >= 0:
        # An unfinished quoted table name: complete its body, but keep the
        # opening quote and any already typed suffix intact.
        start = quote_start + 1
        end = position
        while end < len(expression):
            if expression[end] == "'":
                if end + 1 < len(expression) and expression[end + 1] == "'":
                    end += 2
                    continue
                break
            end += 1
        has_closing_quote = end < len(expression) and expression[end] == "'"
        if not has_closing_quote:
            end = len(expression)
        prefix = expression[start:position].replace("''", "'")
        return "table", prefix, start, end, None, has_closing_quote

    if quote is not None or open_bracket < 0:
        return None

    table_name: str | None = None
    qualifier = re.search(
        r"(?P<table>'(?:''|[^'])*'|[^\W\d]\w*)\s*$",
        expression[:open_bracket],
        re.UNICODE,
    )
    if qualifier:
        token = qualifier.group("table")
        table_name = (
            token[1:-1].replace("''", "'")
            if token.startswith("'") else token
        )

    start = open_bracket + 1
    end = expression.find("]", position)
    while end >= 0 and expression.startswith("]]", end):
        end = expression.find("]", end + 2)  # a doubled ']' belongs to the name
    if end < 0:
        end = len(expression)
        for offset in range(position, len(expression)):
            if expression[offset] in ")(,=<>+*/&|\n\r":
                end = offset
                break
    has_closing_bracket = end < len(expression) and expression[end] == "]"
    return (
        "reference", expression[start:position].replace("]]", "]"), start, end, table_name,
        has_closing_bracket,
    )


def _dax_field_reference_parts(reference: str) -> tuple[str, str] | None:
    """Read table and column names from the editor's canonical DAX reference."""
    match = re.fullmatch(r"'((?:''|[^'])*)'\[((?:[^\]]|\]\])+)\]", reference)
    if match is None:
        return None
    return match.group(1).replace("''", "'"), match.group(2).replace("]]", "]")


_DAX_COLUMN_ARGUMENT_FUNCTIONS = {
    "AVERAGE", "COUNT", "COUNTA", "DISTINCTCOUNT",
    "DISTINCTCOUNTNOBLANK", "MAX", "MIN", "SUM",
}


def _qt_position_to_python_index(expression: str, position: int) -> int:
    """Translate Qt's UTF-16 cursor offset into a Python string index."""
    target = max(0, position)
    units = 0
    for index, character in enumerate(expression):
        if units >= target:
            return index
        units += 2 if ord(character) > 0xFFFF else 1
    return len(expression)


def _python_index_to_qt_position(expression: str, index: int) -> int:
    """Translate a Python string index into Qt's UTF-16 cursor offset."""
    prefix = expression[:max(0, min(index, len(expression)))]
    return len(prefix.encode("utf-16-le", "surrogatepass")) // 2


def _template_arguments(template: str) -> list[str]:
    """Split the displayed top-level template arguments for inline help."""
    opening = template.find("(")
    closing = template.rfind(")")
    if opening < 0 or closing <= opening + 1:
        return []
    body = template[opening + 1:closing]
    result: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    in_column = False
    index = 0
    while index < len(body):
        character = body[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif in_column:
            if character == "]":
                if index + 1 < len(body) and body[index + 1] == "]":
                    index += 2  # a doubled ']' is one ']' of the name
                    continue
                in_column = False
        elif character in {"'", '"'}:
            quote = character
        elif character == "[":
            in_column = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            result.append(body[start:index].strip())
            start = index + 1
        index += 1
    final = body[start:].strip()
    if final:
        result.append(final)
    return result


DAX_FUNCTION_TEMPLATES: dict[str, tuple[str, str | None]] = {
    "ABS": ("ABS(number)", "number"),
    "ALL": ("ALL('Table')", "'Table'"),
    "ALLEXCEPT": ("ALLEXCEPT('Table', 'Table'[Column])", "'Table'"),
    "ALLNOBLANKROW": ("ALLNOBLANKROW('Table')", "'Table'"),
    "ALLSELECTED": ("ALLSELECTED('Table')", "'Table'"),
    "AND": ("AND(condition1, condition2)", "condition1"),
    "AVERAGE": ("AVERAGE([Column])", "[Column]"),
    "AVERAGEX": ("AVERAGEX('Table', row_expression)", "'Table'"),
    "BLANK": ("BLANK()", None),
    "CALCULATE": ("CALCULATE(expression, filter)", "expression"),
    "CROSSFILTER": (
        "CROSSFILTER('Table'[Column], 'Table'[Column], BOTH)", "'Table'[Column]"
    ),
    "COUNT": ("COUNT([Column])", "[Column]"),
    "COUNTAX": ("COUNTAX('Table', row_expression)", "'Table'"),
    "COUNTA": ("COUNTA([Column])", "[Column]"),
    "COUNTROWS": ("COUNTROWS('Table')", "'Table'"),
    "COUNTX": ("COUNTX('Table', row_expression)", "'Table'"),
    "COALESCE": ("COALESCE(expression1, expression2)", "expression1"),
    "DATEADD": ("DATEADD('Calendar'[Date], intervals, MONTH)", "'Calendar'[Date]"),
    "DATESBETWEEN": (
        "DATESBETWEEN('Calendar'[Date], start_date, end_date)", "'Calendar'[Date]"
    ),
    "DATESINPERIOD": (
        "DATESINPERIOD('Calendar'[Date], end_date, intervals, MONTH)", "'Calendar'[Date]"
    ),
    "DATESMTD": ("DATESMTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DATESQTD": ("DATESQTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DATESYTD": ("DATESYTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DISTINCT": ("DISTINCT('Table'[Column])", "'Table'[Column]"),
    "DISTINCTCOUNT": ("DISTINCTCOUNT([Column])", "[Column]"),
    "DISTINCTCOUNTNOBLANK": ("DISTINCTCOUNTNOBLANK([Column])", "[Column]"),
    "DIVIDE": ("DIVIDE(numerator, denominator)", "numerator"),
    "FALSE": ("FALSE()", None),
    "FILTER": ("FILTER('Table', condition)", "'Table'"),
    "FIRSTDATE": ("FIRSTDATE('Calendar'[Date])", "'Calendar'[Date]"),
    "LASTDATE": ("LASTDATE('Calendar'[Date])", "'Calendar'[Date]"),
    **{
        f"{edge}OF{unit}": (f"{edge}OF{unit}('Calendar'[Date])", "'Calendar'[Date]")
        for edge in ("START", "END") for unit in ("MONTH", "QUARTER", "YEAR")
    },
    **{
        f"{way}BALANCE{unit}": (f"{way}BALANCE{unit}(expression, 'Calendar'[Date])", "expression")
        for way in ("OPENING", "CLOSING") for unit in ("MONTH", "QUARTER", "YEAR")
    },
    "IF": ("IF(condition, value_if_true, value_if_false)", "condition"),
    "KEEPFILTERS": ("KEEPFILTERS(filter)", "filter"),
    "MAX": ("MAX([Column])", "[Column]"),
    "MAXX": ("MAXX('Table', row_expression)", "'Table'"),
    "MIN": ("MIN([Column])", "[Column]"),
    "MINX": ("MINX('Table', row_expression)", "'Table'"),
    "NEXTDAY": ("NEXTDAY('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTMONTH": ("NEXTMONTH('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTQUARTER": ("NEXTQUARTER('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTYEAR": ("NEXTYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "NOT": ("NOT(condition)", "condition"),
    "OR": ("OR(condition1, condition2)", "condition1"),
    "PARALLELPERIOD": (
        "PARALLELPERIOD('Calendar'[Date], intervals, MONTH)", "'Calendar'[Date]"
    ),
    "PREVIOUSDAY": ("PREVIOUSDAY('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSMONTH": ("PREVIOUSMONTH('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSQUARTER": ("PREVIOUSQUARTER('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSYEAR": ("PREVIOUSYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "REMOVEFILTERS": ("REMOVEFILTERS()", None),
    "RELATED": ("RELATED('Related table'[Column])", "'Related table'[Column]"),
    "RELATEDTABLE": ("RELATEDTABLE('Related table')", "'Related table'"),
    "ROUND": ("ROUND(number, digits)", "number"),
    "EXP": ("EXP(number)", "number"),
    "INT": ("INT(number)", "number"),
    "LN": ("LN(number)", "number"),
    "MOD": ("MOD(number, divisor)", "number"),
    "POWER": ("POWER(number, power)", "number"),
    "SIGN": ("SIGN(number)", "number"),
    "SQRT": ("SQRT(number)", "number"),
    "TRUNC": ("TRUNC(number, digits)", "number"),
    "CEILING": ("CEILING(number, significance)", "number"),
    "FLOOR": ("FLOOR(number, significance)", "number"),
    "ISBLANK": ("ISBLANK(value)", "value"),
    "IFERROR": ("IFERROR(value, value_if_error)", "value"),
    "SWITCH": ("SWITCH(expression, value, result, else)", "expression"),
    "MEDIAN": ("MEDIAN('Table'[Column])", "'Table'[Column]"),
    "PRODUCT": ("PRODUCT('Table'[Column])", "'Table'[Column]"),
    "COUNTBLANK": ("COUNTBLANK('Table'[Column])", "'Table'[Column]"),
    "SAMEPERIODLASTYEAR": ("SAMEPERIODLASTYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "SUM": ("SUM([Column])", "[Column]"),
    "SUMX": ("SUMX('Table', row_expression)", "'Table'"),
    "TRUE": ("TRUE()", None),
    "TOTALMTD": ("TOTALMTD(expression, 'Calendar'[Date])", "expression"),
    "TOTALQTD": ("TOTALQTD(expression, 'Calendar'[Date])", "expression"),
    "TOTALYTD": ("TOTALYTD(expression, 'Calendar'[Date])", "expression"),
    "USERELATIONSHIP": (
        "USERELATIONSHIP('Table'[Column], 'Table'[Column])", "'Table'[Column]"
    ),
}
DAX_FUNCTION_TEMPLATES.update({
    "CONCATENATE": ("CONCATENATE(text1, text2)", "text1"),
    "EXACT": ("EXACT(text1, text2)", "text1"),
    "FIND": ("FIND(find_text, within_text)", "find_text"),
    "FIXED": ("FIXED(number, 2)", "number"),
    "FORMAT": ('FORMAT(value, "0.00")', "value"),
    "ISERROR": ("ISERROR(value)", "value"),
    "ISLOGICAL": ("ISLOGICAL(value)", "value"),
    "ISNONTEXT": ("ISNONTEXT(value)", "value"),
    "ISNUMBER": ("ISNUMBER(value)", "value"),
    "ISTEXT": ("ISTEXT(value)", "value"),
    "ISINTEGER": ("ISINTEGER(value)", "value"),
    "ISINT64": ("ISINT64(value)", "value"),
    "ISDOUBLE": ("ISDOUBLE(value)", "value"),
    "ISDECIMAL": ("ISDECIMAL(value)", "value"),
    "ISCURRENCY": ("ISCURRENCY(value)", "value"),
    "LEFT": ("LEFT(text, 1)", "text"),
    "LEN": ("LEN(text)", "text"),
    "LOWER": ("LOWER(text)", "text"),
    "MID": ("MID(text, 1, 1)", "text"),
    "REPLACE": ("REPLACE(old_text, 1, 1, new_text)", "old_text"),
    "REPT": ("REPT(text, 2)", "text"),
    "RIGHT": ("RIGHT(text, 1)", "text"),
    "SEARCH": ("SEARCH(find_text, within_text)", "find_text"),
    "SUBSTITUTE": ("SUBSTITUTE(text, old_text, new_text)", "text"),
    "TRIM": ("TRIM(text)", "text"),
    "UNICHAR": ("UNICHAR(number)", "number"),
    "UNICODE": ("UNICODE(text)", "text"),
    "UPPER": ("UPPER(text)", "text"),
    "VALUE": ("VALUE(text)", "text"),
    "CONCATENATEX": ("CONCATENATEX('Table', expression, \", \")", "'Table'"),
    "XNPV": ("XNPV('Table', values, dates, rate)", "'Table'"),
    "CONVERT": ("CONVERT(expression, INTEGER)", "expression"),
    "DATE": ("DATE(2024, 1, 31)", "2024"),
    "DATEDIFF": ("DATEDIFF(start_date, end_date, DAY)", "start_date"),
    "DATEVALUE": ('DATEVALUE("2024-01-31")', '"2024-01-31"'),
    "DAY": ("DAY(date)", "date"),
    "EDATE": ("EDATE(date, 1)", "date"),
    "EOMONTH": ("EOMONTH(date, 0)", "date"),
    "HASONEVALUE": ("HASONEVALUE('Table'[Column])", "'Table'[Column]"),
    "HOUR": ("HOUR(datetime)", "datetime"),
    "MINUTE": ("MINUTE(datetime)", "datetime"),
    "MONTH": ("MONTH(date)", "date"),
    "NOW": ("NOW()", None),
    "QUARTER": ("QUARTER(date)", "date"),
    "SECOND": ("SECOND(datetime)", "datetime"),
    "SELECTEDVALUE": ("SELECTEDVALUE('Table'[Column], alternate_result)", "'Table'[Column]"),
    "TIME": ("TIME(hour, minute, second)", "hour"),
    "TIMEVALUE": ('TIMEVALUE("13:30")', '"13:30"'),
    "TODAY": ("TODAY()", None),
    "VALUES": ("VALUES('Table'[Column])", "'Table'[Column]"),
    "WEEKDAY": ("WEEKDAY(date)", "date"),
    "WEEKNUM": ("WEEKNUM(date)", "date"),
    "YEAR": ("YEAR(date)", "date"),
    "IF.EAGER": ("IF.EAGER(condition, value_if_true, value_if_false)", "condition"),
    "ERROR": ('ERROR("message")', '"message"'),
    "CUSTOMDATA": ("CUSTOMDATA()", None),
    "ISAFTER": ("ISAFTER(val1, val2, order)", "val1"),
    "NAMEOF": ("NAMEOF('Table'[Column])", "'Table'[Column]"),
    "TABLEOF": ("TABLEOF('Table'[Column])", "'Table'[Column]"),
    "EVALUATEANDLOG": ("EVALUATEANDLOG(value)", "value"),
    "ALLCROSSFILTERED": ("ALLCROSSFILTERED('Table')", "'Table'"),
    "TOCSV": ("TOCSV('Table', max_rows, delimiter, include_headers)", "'Table'"),
    "TOJSON": ("TOJSON('Table', max_rows)", "'Table'"),
    "LINEST": ("LINEST('Table'[ColumnY], 'Table'[ColumnX1])", "'Table'[ColumnY]"),
    "LINESTX": ("LINESTX('Table', expressionY, expressionX1)", "'Table'"),
    "SUBSTITUTEWITHINDEX": ("SUBSTITUTEWITHINDEX('Table', \"IndexColumnName\", 'IndexTable', 'Table'[OrderByColumn])", "'Table'"),
    "ADDMISSINGITEMS": ("ADDMISSINGITEMS('Table'[ShowAllColumn], 'Table', 'Table'[GroupByColumn])", "'Table'[ShowAllColumn]"),
    "ROLLUP": ("ROLLUP('Table'[Column1], 'Table'[Column2])", "'Table'[Column1]"),
    "ROLLUPGROUP": ("ROLLUPGROUP('Table'[Column1], 'Table'[Column2])", "'Table'[Column1]"),
    "ROLLUPADDISSUBTOTAL": ("ROLLUPADDISSUBTOTAL('Table'[Column1], \"SubtotalName\")", "'Table'[Column1]"),
    "ROLLUPISSUBTOTAL": ("ROLLUPISSUBTOTAL('Table'[Column1], [SubtotalColumn])", "'Table'[Column1]"),
    "ISSUBTOTAL": ("ISSUBTOTAL('Table'[Column1])", "'Table'[Column1]"),
})


def _add_generated_templates() -> None:
    """Fill the catalog entries for the function families whose argument shape is regular."""
    from analytics_studio import dax_math
    from analytics_studio.measures import _LOOKUP_ARITY, _TYPED_ARITY

    for name, (low, _high) in _TYPED_ARITY.items():
        if name not in DAX_FUNCTION_TEMPLATES:
            arguments = ["number", "number2", "number3"][:low] if low else []
            DAX_FUNCTION_TEMPLATES[name] = (f"{name}({', '.join(arguments)})", arguments[0] if arguments else None)
    lookup_templates = {
        "CONTAINS": ("CONTAINS('Table', 'Table'[Column], value)", "'Table'"),
        "CONTAINSROW": ("CONTAINSROW({1, 2, 3}, value)", "value"),
        "LOOKUPVALUE": ("LOOKUPVALUE('Table'[Result], 'Table'[Search], value)", "'Table'[Result]"),
        "ISEMPTY": ("ISEMPTY('Table')", "'Table'"),
        "ISFILTERED": ("ISFILTERED('Table'[Column])", "'Table'[Column]"),
        "ISCROSSFILTERED": ("ISCROSSFILTERED('Table'[Column])", "'Table'[Column]"),
        "HASONEFILTER": ("HASONEFILTER('Table'[Column])", "'Table'[Column]"),
        "ISINSCOPE": ("ISINSCOPE('Table'[Column])", "'Table'[Column]"),
        "COMBINEVALUES": ('COMBINEVALUES(", ", value1, value2)', "value1"),
        "USERNAME": ("USERNAME()", None),
        "USERPRINCIPALNAME": ("USERPRINCIPALNAME()", None),
        "FIRSTNONBLANK": ("FIRSTNONBLANK('Table'[Column], expression)", "'Table'[Column]"),
        "LASTNONBLANK": ("LASTNONBLANK('Table'[Column], expression)", "'Table'[Column]"),
        "FIRSTNONBLANKVALUE": ("FIRSTNONBLANKVALUE('Table'[Column], expression)", "'Table'[Column]"),
        "LASTNONBLANKVALUE": ("LASTNONBLANKVALUE('Table'[Column], expression)", "'Table'[Column]"),
        "GENERATESERIES": ("GENERATESERIES(1, 10)", "1"),
        "ROW": ('ROW("Name", expression)', '"Name"'),
        "SUMMARIZE": ("SUMMARIZE('Table', 'Table'[Column])", "'Table'"),
        "ADDCOLUMNS": ('ADDCOLUMNS(\'Table\', "Name", expression)', "'Table'"),
        "SELECTCOLUMNS": ('SELECTCOLUMNS(\'Table\', "Name", expression)', "'Table'"),
        "CROSSJOIN": ("CROSSJOIN('Table1', 'Table2')", "'Table1'"),
        "UNION": ("UNION('Table1', 'Table2')", "'Table1'"),
        "INTERSECT": ("INTERSECT('Table1', 'Table2')", "'Table1'"),
        "EXCEPT": ("EXCEPT('Table1', 'Table2')", "'Table1'"),
        "TOPN": ("TOPN(n, 'Table', expression)", "n"),
        "RANKX": ("RANKX('Table', expression)", "'Table'"),
        "RANK.EQ": ("RANK.EQ(value, 'Table'[Column])", "value"),
        "CALCULATETABLE": ("CALCULATETABLE('Table', filter)", "'Table'"),
        "EARLIER": ("EARLIER('Table'[Column])", "'Table'[Column]"),
        "EARLIEST": ("EARLIEST('Table'[Column])", "'Table'[Column]"),
        "SUMMARIZECOLUMNS": ('SUMMARIZECOLUMNS(\'Table\'[Column], "Name", expression)', "'Table'[Column]"),
        "GROUPBY": ('GROUPBY(\'Table\', \'Table\'[Column], "Name", SUMX(CURRENTGROUP(), expression))', "'Table'"),
        "CURRENTGROUP": ("CURRENTGROUP()", None),
        "TREATAS": ("TREATAS({value}, 'Table'[Column])", "value"),
        "NATURALINNERJOIN": ("NATURALINNERJOIN('Table1', 'Table2')", "'Table1'"),
        "NATURALLEFTOUTERJOIN": ("NATURALLEFTOUTERJOIN('Table1', 'Table2')", "'Table1'"),
        "GENERATE": ("GENERATE('Table1', 'Table2')", "'Table1'"),
        "GENERATEALL": ("GENERATEALL('Table1', 'Table2')", "'Table1'"),
        "SAMPLE": ("SAMPLE(n, 'Table', expression)", "n"),
        "TOPNSKIP": ("TOPNSKIP(n, skip, 'Table', expression)", "n"),
        "DATATABLE": ('DATATABLE("Name", INTEGER, {{1}, {2}})', '"Name"'),
        "CALENDAR": ("CALENDAR(DATE(2024, 1, 1), DATE(2024, 12, 31))", "DATE(2024, 1, 1)"),
        "FILTERS": ("FILTERS('Table'[Column])", "'Table'[Column]"),
        "IGNORE": ("IGNORE(expression)", "expression"),
        "NONVISUAL": ("NONVISUAL(expression)", "expression"),
        "INDEX": ("INDEX(1, ALL('Table'[Column]), ORDERBY('Table'[Column], ASC))", "1"),
        "OFFSET": ("OFFSET(-1, ALL('Table'[Column]), ORDERBY('Table'[Column], ASC))", "-1"),
        "WINDOW": ("WINDOW(1, ABS, 0, REL, ALL('Table'[Column]), ORDERBY('Table'[Column], ASC))", "1"),
        "RANK": ("RANK(DENSE, ALL('Table'[Column]), ORDERBY('Table'[Column], ASC))", "DENSE"),
        "ROWNUMBER": ("ROWNUMBER(ALL('Table'[Column]), ORDERBY('Table'[Column], ASC))", "ALL('Table'[Column])"),
        "ORDERBY": ("ORDERBY('Table'[Column], ASC)", "'Table'[Column]"),
        "PARTITIONBY": ("PARTITIONBY('Table'[Column])", "'Table'[Column]"),
        "MATCHBY": ("MATCHBY('Table'[Column])", "'Table'[Column]"),
    }
    for name in sorted(set(_LOOKUP_ARITY) | set(lookup_templates)):
        DAX_FUNCTION_TEMPLATES.setdefault(name, lookup_templates.get(name, (f"{name}()", None)))
    for name in dax_math.STAT_COLUMN_FUNCTIONS:
        DAX_FUNCTION_TEMPLATES.setdefault(name, (f"{name}([Column])", "[Column]"))
    for name in dax_math.STAT_PERCENTILE_COLUMN:
        DAX_FUNCTION_TEMPLATES.setdefault(name, (f"{name}([Column], 0.5)", "[Column]"))
    for name in dax_math.STAT_ITERATORS:
        extra = ", 0.5" if name.startswith("PERCENTILEX") else ""
        DAX_FUNCTION_TEMPLATES.setdefault(name, (f"{name}('Table', row_expression{extra})", "'Table'"))


_add_generated_templates()


class MeasureDialog(QDialog):
    """Collect one measure definition; computation is performed by the controller."""

    def __init__(
        self,
        headers: list[str],
        existing_names: list[str],
        *,
        quick: bool = False,
        quick_table_name: str | None = None,
        quick_table_display_name: str | None = None,
        home_table_id: str | None = None,
        home_table_name: str | None = None,
        home_table_display_name: str | None = None,
        default_column: str | None = None,
        initial_measure: dict[str, Any] | None = None,
        field_references: list[tuple[str, str]] | None = None,
        measure_references: list[str] | None = None,
        preview_callback: Callable[[str, str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.quick = quick
        self._quick_table_name = (
            quick_table_name
            if isinstance(quick_table_name, str) and quick_table_name.strip()
            else ""
        )
        self._quick_table_display_name = (
            quick_table_display_name
            if isinstance(quick_table_display_name, str)
            and quick_table_display_name.strip()
            else self._quick_table_name
        )
        self._home_table_id = (
            str(initial_measure.get("home_table_id", ""))
            if initial_measure and initial_measure.get("home_table_id")
            else str(home_table_id or "")
        )
        self._home_table_name = str(home_table_name or "")
        self._headers = list(headers)
        self._field_references = list(field_references or [])
        self._measure_references = list(measure_references or [])
        self._inline_reference_context: tuple[
            str, str, int, int, str | None, bool
        ] | None = None
        self._inline_completion_expression = ""
        self._inline_completion_position = 0
        self._editing_name = (
            str(initial_measure.get("name", "")) if initial_measure else ""
        )
        self._existing_names = {
            name.casefold() for name in existing_names
            if name.casefold() != self._editing_name.casefold()
        }
        self._accepted_measure: dict[str, Any] | None = None
        self._preview_callback = preview_callback
        editing = initial_measure is not None
        self.setWindowTitle(
            "Quick measure" if quick else "Edit measure" if editing else "New measure"
        )
        self.setMinimumWidth(560 if quick else 700)
        self.resize(640 if quick else 780, 470 if quick else 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel(
            "Edit a local DAX measure" if editing else "Create a local DAX measure"
        )
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        self.content_scroll_area = QScrollArea(self)
        self.content_scroll_area.setObjectName("daxMeasureContentScrollArea")
        self.content_scroll_area.setWidgetResizable(True)
        self.content_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(self.content_scroll_area)
        content.setObjectName("daxMeasureContent")
        content_palette = content.palette()
        content_palette.setColor(
            QPalette.ColorRole.Window, QColor("#f4f6f8")
        )
        content.setPalette(content_palette)
        content.setAutoFillBackground(True)
        viewport = self.content_scroll_area.viewport()
        viewport_palette = viewport.palette()
        viewport_palette.setColor(
            QPalette.ColorRole.Window, QColor("#f4f6f8")
        )
        viewport_palette.setColor(
            QPalette.ColorRole.Base, QColor("#f4f6f8")
        )
        viewport.setPalette(viewport_palette)
        viewport.setAutoFillBackground(True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        self.content_scroll_area.setWidget(content)
        layout.addWidget(self.content_scroll_area, 1)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(120)
        if initial_measure:
            self.name_edit.setText(str(initial_measure.get("name", "")))
        form.addRow("Measure name", self.name_edit)
        if not quick and self._home_table_id:
            self.home_table_label = QLabel(
                str(home_table_display_name or self._home_table_id)
            )
            self.home_table_label.setObjectName("daxMeasureHomeTable")
            self.home_table_label.setStyleSheet("color: #526477;")
            self.home_table_label.setToolTip(
                "Unqualified columns and COUNTROWS() use this measure's home table."
            )
            form.addRow("Home table", self.home_table_label)
        self.expression_edit = QPlainTextEdit()
        self.expression_edit.setPlaceholderText(
            "Enter a DAX expression, or insert a function, field, or measure below."
        )
        self.expression_edit.setMinimumHeight(128)
        self.expression_edit.setMaximumHeight(160)
        self.expression_edit.setObjectName("daxMeasureExpression")
        formula_font = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont
        )
        formula_font.setPointSize(11)
        self.expression_edit.setFont(formula_font)
        self.expression_edit.setStyleSheet(
            "QPlainTextEdit { background: #ffffff; color: #182b3a; "
            "border: 1px solid #9eacb7; border-radius: 4px; padding: 8px; "
            "selection-background-color: #cde8f6; }"
        )
        if initial_measure:
            self.expression_edit.setPlainText(str(initial_measure.get("expression", "")))
        self.expression_edit.setVisible(not quick)
        if quick:
            self.function_combo = QComboBox()
            for label, function in (
                ("Sum", "SUM"), ("Average", "AVERAGE"), ("Minimum", "MIN"),
                ("Maximum", "MAX"), ("Count numbers", "COUNT"),
                ("Count non-empty", "COUNTA"), ("Distinct count", "DISTINCTCOUNT"),
                ("Distinct count without blank", "DISTINCTCOUNTNOBLANK"),
            ):
                self.function_combo.addItem(label, function)
            self.column_combo = QComboBox()
            self.column_combo.addItems(headers)
            if default_column in headers:
                self.column_combo.setCurrentText(default_column)
            form.addRow("Calculation", self.function_combo)
            self.quick_table_context = QLabel(
                f"Using table: {self._quick_table_display_name or 'unavailable'}"
            )
            self.quick_table_context.setObjectName("quickMeasureTableContext")
            self.quick_table_context.setWordWrap(True)
            self.quick_table_context.setAccessibleName("Quick measure source table")
            form.addRow(self.quick_table_context)
            form.addRow("Column", self.column_combo)
            self.function_combo.currentIndexChanged.connect(self._refresh_error)
            self.function_combo.currentIndexChanged.connect(
                lambda _index: self._update_quick_name(self.column_combo.currentText())
            )
            self.column_combo.currentIndexChanged.connect(self._refresh_error)
            if headers:
                self.name_edit.setText(f"Sum of {self.column_combo.currentText()}")
            self.column_combo.currentTextChanged.connect(self._update_quick_name)
        else:
            formula_panel = QWidget()
            formula_panel.setObjectName("daxFormulaPanel")
            formula_layout = QVBoxLayout(formula_panel)
            formula_layout.setContentsMargins(0, 0, 0, 0)
            formula_layout.setSpacing(5)
            formula_layout.addWidget(self.expression_edit)
            self.inline_function_suggestions = QListWidget()
            self.inline_function_suggestions.setObjectName(
                "daxInlineFunctionSuggestions"
            )
            self.inline_function_suggestions.setMaximumHeight(86)
            self.inline_function_suggestions.setSelectionMode(
                QListWidget.SelectionMode.SingleSelection
            )
            self.inline_function_suggestions.setStyleSheet(
                "QListWidget { background: #f7fafc; border: 1px solid #d6e0e7; "
                "border-radius: 4px; padding: 2px; } "
                "QListWidget::item { padding: 3px 6px; color: #344b5b; } "
                "QListWidget::item:selected { background: #dcecf5; color: #18394d; }"
            )
            self.inline_function_suggestions.setVisible(False)
            self.inline_function_suggestions.itemClicked.connect(
                self._accept_inline_completion
            )
            formula_layout.addWidget(self.inline_function_suggestions)
            self.inline_help_label = QLabel(
                "Type a supported function name; suggestions stay optional until you select one."
            )
            self.inline_help_label.setObjectName("daxInlineArgumentHelp")
            self.inline_help_label.setWordWrap(True)
            self.inline_help_label.setMinimumHeight(34)
            self.inline_help_label.setStyleSheet(
                "padding: 6px 8px; background: #f1f6f9; color: #425768; "
                "border: 1px solid #dbe4ea; border-radius: 4px;"
            )
            formula_layout.addWidget(self.inline_help_label)
            form.addRow("DAX expression", formula_panel)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("daxMeasureDescription")
        self.description_edit.setPlaceholderText("Describe what this measure represents")
        self.description_edit.setMaximumHeight(62)
        if initial_measure:
            self.description_edit.setPlainText(str(initial_measure.get("description", "")))
        form.addRow("Description", self.description_edit)
        self.display_folder_edit = QLineEdit()
        self.display_folder_edit.setObjectName("daxMeasureDisplayFolder")
        self.display_folder_edit.setMaxLength(400)
        self.display_folder_edit.setPlaceholderText("Optional model display folder")
        if initial_measure:
            self.display_folder_edit.setText(str(initial_measure.get("display_folder", "")))
        form.addRow("Display folder", self.display_folder_edit)
        self.hidden_checkbox = QCheckBox("Hide from report field lists")
        self.hidden_checkbox.setObjectName("daxMeasureHidden")
        self.hidden_checkbox.setChecked(bool(initial_measure and initial_measure.get("is_hidden", False)))
        form.addRow("Visibility", self.hidden_checkbox)
        content_layout.addLayout(form)

        if not quick:
            self.function_combo = self._search_combo("Search supported function names")
            self.function_combo.setObjectName("daxFunctionPicker")
            self.function_combo.addItems(DAX_FUNCTION_NAMES)
            self.function_combo.setCurrentIndex(-1)
            self.function_signature_label = QLabel(
                "Choose a recognized function to see its local syntax template."
            )
            self.function_signature_label.setObjectName("daxFunctionSignatureHint")
            self.function_signature_label.setWordWrap(True)
            self.function_signature_label.setMinimumHeight(32)
            self.function_signature_label.setStyleSheet("color: #526477;")
            self.function_combo.currentTextChanged.connect(
                self._update_function_signature
            )
            self.insert_function_button = QPushButton("Insert function")
            self.insert_function_button.setObjectName("insertDaxFunctionButton")
            self.insert_function_button.clicked.connect(self._insert_function)
            function_row = QHBoxLayout()
            function_row.addWidget(self.function_combo, 1)
            function_row.addWidget(self.insert_function_button)
            form.addRow("Function", function_row)
            form.addRow("Syntax", self.function_signature_label)

            self.field_combo = self._search_combo("Search loaded table fields")
            self.field_combo.setObjectName("daxFieldPicker")
            for label, reference in self._field_references:
                self.field_combo.addItem(label, reference)
            self.field_combo.setCurrentIndex(-1)
            self.insert_field_button = QPushButton("Insert field")
            self.insert_field_button.setObjectName("insertDaxFieldButton")
            self.insert_field_button.clicked.connect(self._insert_field_reference)
            field_row = QHBoxLayout()
            field_row.addWidget(self.field_combo, 1)
            field_row.addWidget(self.insert_field_button)
            form.addRow("Model field", field_row)

            self.measure_combo = self._search_combo("Search saved measures")
            self.measure_combo.setObjectName("daxMeasurePicker")
            for measure_name in self._measure_references:
                self.measure_combo.addItem(measure_name, f"[{escape_bracket_name(measure_name)}]")
            self.measure_combo.setCurrentIndex(-1)
            self.insert_measure_button = QPushButton("Insert measure")
            self.insert_measure_button.setObjectName("insertDaxMeasureButton")
            self.insert_measure_button.clicked.connect(self._insert_measure_reference)
            measure_row = QHBoxLayout()
            measure_row.addWidget(self.measure_combo, 1)
            measure_row.addWidget(self.insert_measure_button)
            form.addRow("Measure", measure_row)

            self.local_scope_help = QLabel(
                "MAXX and MINX are available in the local DAX measure form only; "
                "they are not Quick Measure templates or calculated columns. "
                "The table argument must be a loaded table or a supported ALL, "
                "ALLNOBLANKROW, or ALLSELECTED table/column expression, and the row expression must return a numeric or "
                "BLANK() result. Variant mode, text/date/Boolean row results, arbitrary "
                "table expressions, and calculated-column use are not supported."
            )
            self.local_scope_help.setObjectName("daxLocalScopeHelp")
            self.local_scope_help.setWordWrap(True)
            self.local_scope_help.setAccessibleName("MAXX and MINX local measure limits")
            self.local_scope_help.setAccessibleDescription(
                self.local_scope_help.text()
            )
            self.local_scope_help.setToolTip(self.local_scope_help.text())
            self.local_scope_help.setBuddy(self.expression_edit)
            self.local_scope_help.setStyleSheet(
                "padding: 6px 8px; background: #f1f6f9; color: #425768; "
                "border: 1px solid #dbe4ea; border-radius: 4px;"
            )
            form.addRow(self.local_scope_help)

        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("Validate / preview")
        self.preview_button.setObjectName("previewDaxMeasureButton")
        self.preview_button.setVisible(preview_callback is not None)
        self.preview_button.setEnabled(preview_callback is not None)
        self.preview_button.clicked.connect(self._preview_measure)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("daxMeasurePreview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #526477;")
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.preview_label, 1)
        content_layout.addLayout(preview_row)

        help_label = QLabel(
            "This editor evaluates the supported local DAX subset shown in the function picker. "
            "Suggestions appear when you type a supported function prefix; press Tab or Enter "
            "to insert the selected template. Use Validate / preview to check the expression "
            "against the current loaded model and report filters. Qualified fields use "
            "'Table Name'[Column]."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        self.function_help_label = help_label
        help_label.setObjectName("daxFunctionHelp")
        content_layout.addWidget(help_label)
        catalog_label = QLabel(
            'This editor evaluates a partial local DAX subset. Microsoft documents '
            '<a href="https://learn.microsoft.com/en-us/dax/dax-function-reference">'
            '250+ DAX functions</a>; functions outside this picker are not evaluated here.'
        )
        catalog_label.setObjectName("daxFunctionCatalogBoundary")
        catalog_label.setWordWrap(True)
        catalog_label.setOpenExternalLinks(True)
        catalog_label.setStyleSheet("color: #526477;")
        content_layout.addWidget(catalog_label)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.save_button.setText("Save measure" if editing else "Create measure")
        self.buttons.accepted.connect(self._accept_measure)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self._refresh_error)
        self.expression_edit.textChanged.connect(self._refresh_error)
        self.description_edit.textChanged.connect(self._refresh_error)
        self.display_folder_edit.textChanged.connect(self._refresh_error)
        if not quick:
            self.expression_edit.textChanged.connect(self._refresh_inline_editor_help)
            self.expression_edit.cursorPositionChanged.connect(
                self._refresh_inline_editor_help
            )
            self.expression_edit.installEventFilter(self)
            self.inline_function_suggestions.installEventFilter(self)
            self._refresh_inline_editor_help()
        self._refresh_error()

    def _update_quick_name(self, column: str) -> None:
        if not self.quick:
            return
        prefixes = {
            "SUM": "Sum of",
            "AVERAGE": "Average of",
            "MIN": "Minimum of",
            "MAX": "Maximum of",
            "COUNT": "Count of",
            "COUNTA": "Count non-empty of",
            "DISTINCTCOUNT": "Distinct count of",
            "DISTINCTCOUNTNOBLANK": "Distinct count without blank of",
        }
        old_prefixes = tuple(prefix + " " for prefix in prefixes.values())
        current_name = self.name_edit.text()
        if any(current_name.startswith(prefix) for prefix in old_prefixes):
            function = str(self.function_combo.currentData())
            self.name_edit.setText(f"{prefixes.get(function, 'Measure of')} {column}")

    @staticmethod
    def _search_combo(placeholder: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMaxVisibleItems(16)
        combo.completer().setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.lineEdit().setPlaceholderText(placeholder)
        return combo

    def _insert_text(
        self,
        text: str,
        *,
        cursor_offset: int | None = None,
        selection: tuple[int, int] | None = None,
    ) -> None:
        cursor = self.expression_edit.textCursor()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(text)
        if selection is not None:
            cursor.setPosition(start + selection[0])
            cursor.setPosition(
                start + selection[0] + selection[1],
                QTextCursor.MoveMode.KeepAnchor,
            )
        elif cursor_offset is not None:
            cursor.setPosition(start + cursor_offset)
        self.expression_edit.setTextCursor(cursor)
        self.expression_edit.setFocus()

    def _insert_function(self) -> None:
        function = self.function_combo.currentText().strip().upper()
        if function not in DAX_FUNCTION_NAMES:
            self.preview_label.setText("Choose a function from the supported local list.")
            return
        self._insert_function_named(function)

    def _insert_function_named(self, function: str) -> None:
        if function not in DAX_FUNCTION_TEMPLATES:
            return
        insertion, selection_text = DAX_FUNCTION_TEMPLATES[function]
        if selection_text is not None:
            self._insert_text(
                insertion,
                selection=(insertion.index(selection_text), len(selection_text)),
            )
        else:
            self._insert_text(insertion, cursor_offset=insertion.index("(") + 1)

    def _reference_completion_rows(
        self,
        context: tuple[str, str, int, int, str | None, bool],
        stack: list[list[Any]],
    ) -> tuple[list[tuple[str, str, str, str]], str]:
        """Return bounded model-token suggestions and context help."""
        kind, prefix, _start, _end, table_name, _has_closer = context
        prefix_key = prefix.casefold()
        rows: list[tuple[str, str, str, str]] = []

        if kind == "table":
            seen: set[str] = set()
            for label, reference in self._field_references:
                parts = _dax_field_reference_parts(str(reference))
                if parts is None:
                    continue
                candidate = parts[0]
                key = candidate.casefold()
                if key in seen or not key.startswith(prefix_key):
                    continue
                seen.add(key)
                label_text = str(label)
                suffix = f"[{parts[1]}]"  # the column may itself contain '[' or ']'
                display = label_text[:-len(suffix)] if label_text.endswith(suffix) else label_text.rsplit("[", 1)[0]
                rows.append((
                    "table", display, candidate,
                    f"Complete the loaded table name {candidate!r}.",
                ))
            return rows[:8], "Type a loaded table name or choose a suggestion."

        if table_name is not None:
            seen_columns: set[str] = set()
            for _label, reference in self._field_references:
                parts = _dax_field_reference_parts(str(reference))
                if parts is None or parts[0].casefold() != table_name.casefold():
                    continue
                column = parts[1]
                key = column.casefold()
                if key in seen_columns or not key.startswith(prefix_key):
                    continue
                seen_columns.add(key)
                rows.append((
                    "column", column, column,
                    f"Loaded column from {table_name!r}.",
                ))
            if rows:
                return rows[:8], f"Type a loaded column from {table_name!r}."
            return [], f"No matching loaded columns in table {table_name!r}."

        active_call = stack[-1] if stack and stack[-1][0] else None
        column_expected = bool(
            active_call
            and active_call[0] in _DAX_COLUMN_ARGUMENT_FUNCTIONS
            and int(active_call[1]) == 0
        )
        if column_expected:
            seen_columns = set()
            if self._home_table_name:
                for _label, reference in self._field_references:
                    parts = _dax_field_reference_parts(str(reference))
                    if parts is None or parts[0].casefold() != self._home_table_name.casefold():
                        continue
                    column = parts[1]
                    key = column.casefold()
                    if key in seen_columns or not key.startswith(prefix_key):
                        continue
                    seen_columns.add(key)
                    rows.append((
                        "column", column, column,
                        f"Column from this measure's home table {self._home_table_name!r}.",
                    ))
            else:
                for column_value in self._headers:
                    column = str(column_value)
                    key = column.casefold()
                    if not column or key in seen_columns or not key.startswith(prefix_key):
                        continue
                    seen_columns.add(key)
                    rows.append((
                        "column", column, column,
                        "Column from this measure's home table.",
                    ))
            if rows:
                return rows[:8], "Type a column from this measure's home table."
            return [], "No matching loaded columns in this measure's home table."

        seen_measures: set[str] = set()
        for measure_name in self._measure_references:
            name = str(measure_name)
            key = name.casefold()
            if not name or key in seen_measures or not key.startswith(prefix_key):
                continue
            seen_measures.add(key)
            rows.append((
                "measure", name, name,
                f"Saved measure {name!r}.",
            ))
        if rows:
            return rows[:8], "Type a saved measure name or choose a suggestion."
        return [], "No matching saved measures."

    def _accept_inline_completion(
        self, item: QListWidgetItem | None = None
    ) -> None:
        if item is None:
            item = self.inline_function_suggestions.currentItem()
        if item is None:
            return
        value = str(item.data(Qt.ItemDataRole.UserRole) or "")
        kind = str(item.data(Qt.ItemDataRole.UserRole + 1) or "function")
        expression = self.expression_edit.toPlainText()
        qt_position = self.expression_edit.textCursor().position()
        python_position = _qt_position_to_python_index(expression, qt_position)
        if kind in {"table", "column", "measure"}:
            context = self._inline_reference_context
            context_kind = context[0] if context is not None else None
            valid_context = (
                (kind == "table" and context_kind == "table")
                or (kind == "column" and context_kind in {"reference", "argument"})
                or (kind == "measure" and context_kind == "reference")
            )
            if (
                context is None
                or expression != self._inline_completion_expression
                or python_position != self._inline_completion_position
                or not valid_context
            ):
                return
            _context_kind, _prefix, start, end, _table_name, has_closer = context
            if context_kind == "argument":
                insertion = f"[{escape_bracket_name(value)}]"
            else:
                insertion = value.replace("'", "''") if kind == "table" else escape_bracket_name(value)
            if not has_closer and context_kind != "argument":
                insertion += "'" if kind == "table" else "]"
            cursor = self.expression_edit.textCursor()
            cursor.setPosition(_python_index_to_qt_position(expression, start))
            cursor.setPosition(
                _python_index_to_qt_position(expression, end),
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.insertText(insertion)
            if has_closer:
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
            self.expression_edit.setTextCursor(cursor)
            self.expression_edit.setFocus()
            self.inline_function_suggestions.setVisible(False)
            self._inline_reference_context = None
            return

        span = _dax_completion_span(
            expression,
            python_position,
        )
        if kind != "function" or value not in DAX_FUNCTION_TEMPLATES or span is None:
            return
        _prefix, start, end = span
        cursor = self.expression_edit.textCursor()
        cursor.setPosition(_python_index_to_qt_position(expression, start))
        cursor.setPosition(
            _python_index_to_qt_position(expression, end),
            QTextCursor.MoveMode.KeepAnchor,
        )
        self.expression_edit.setTextCursor(cursor)
        self._insert_function_named(value)
        self.function_combo.setCurrentText(value)

    def _refresh_inline_editor_help(self, *_args: object) -> None:
        if self.quick or not hasattr(self, "inline_function_suggestions"):
            return
        expression = self.expression_edit.toPlainText()
        position = _qt_position_to_python_index(
            expression, self.expression_edit.textCursor().position()
        )
        safe_context, stack = _dax_lexical_state(expression, position)
        reference_context = _dax_reference_completion_context(
            expression, position
        )
        span = _dax_completion_span(expression, position)
        active_call = stack[-1] if stack and stack[-1][0] else None
        function_at_caret = (
            str(active_call[0])
            if active_call is not None
            else span[0].upper()
            if span is not None and span[0].upper() in DAX_FUNCTION_TEMPLATES
            else ""
        )
        self._set_function_signature(function_at_caret)
        self.inline_function_suggestions.clear()
        self._inline_reference_context = reference_context
        self._inline_completion_expression = expression
        self._inline_completion_position = position

        if reference_context is not None:
            rows, help_text = self._reference_completion_rows(
                reference_context, stack
            )
            for kind, label, value, tooltip in rows:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setData(Qt.ItemDataRole.UserRole + 1, kind)
                item.setToolTip(tooltip)
                self.inline_function_suggestions.addItem(item)
            if rows:
                self.inline_function_suggestions.setCurrentRow(0)
            self.inline_function_suggestions.setVisible(bool(rows))
            self.inline_help_label.setText(help_text)
            return

        column_argument_context = _column_argument_completion_context(
            expression, position, stack
        )
        if column_argument_context is not None:
            rows, help_text = self._reference_completion_rows(
                column_argument_context, stack
            )
            self._inline_reference_context = column_argument_context
            for kind, label, value, tooltip in rows:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setData(Qt.ItemDataRole.UserRole + 1, kind)
                item.setToolTip(tooltip)
                self.inline_function_suggestions.addItem(item)
            if rows:
                self.inline_function_suggestions.setCurrentRow(0)
            self.inline_function_suggestions.setVisible(bool(rows))
            function = str(active_call[0])
            template = DAX_FUNCTION_TEMPLATES.get(function, ("", None))[0]
            arguments = _template_arguments(template)
            argument_help = (
                f"{function} · argument 1 of {len(arguments)}: "
                f"{arguments[0]}. "
                if arguments else f"{function} · "
            )
            self.inline_help_label.setText(
                f"{argument_help}{help_text} Select a field to insert it as [Column]."
            )
            return

        if span is not None:
            prefix = span[0].upper()
            matches = [
                name for name in DAX_FUNCTION_NAMES
                if name.startswith(prefix)
            ][:8]
            for name in matches:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setData(Qt.ItemDataRole.UserRole + 1, "function")
                item.setToolTip(
                    "Insert this supported local function and select its first argument."
                )
                self.inline_function_suggestions.addItem(item)
            if matches:
                self.inline_function_suggestions.setCurrentRow(0)
        self.inline_function_suggestions.setVisible(
            span is not None and self.inline_function_suggestions.count() > 0
        )

        if not safe_context:
            self.inline_help_label.setText(
                "Suggestions pause inside text strings and bracketed column references."
            )
        elif active_call is not None:
            function = str(active_call[0])
            argument_index = int(active_call[1])
            template = DAX_FUNCTION_TEMPLATES.get(function, ("", None))[0]
            arguments = _template_arguments(template)
            if function == "COUNTROWS":
                self.inline_help_label.setText(
                    "COUNTROWS · the table argument is optional; omit it to count "
                    "rows in this measure's home table. For an explicit table, "
                    "the local subset accepts a loaded table or supported ALL, "
                    "ALLNOBLANKROW, or ALLSELECTED table/column expression."
                )
            elif argument_index < len(arguments):
                argument = arguments[argument_index]
                self.inline_help_label.setText(
                    f"{function} · argument {argument_index + 1} of {len(arguments)}: "
                    f"{argument}. Use the local syntax template as a guide."
                )
            else:
                self.inline_help_label.setText(
                    f"{function} · argument {argument_index + 1}. "
                    "The local template does not describe another argument here."
                )
        else:
            self.inline_help_label.setText(
                "Type a supported function name; choose a suggestion to insert its local template. "
                "Argument guidance follows the caret in nested calls."
            )

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if not getattr(self, "quick", False) and event.type() == QEvent.Type.KeyPress:
            key_event = event  # type: ignore[assignment]
            if watched is self.expression_edit and isinstance(key_event, QKeyEvent):
                suggestions_visible = self.inline_function_suggestions.isVisible()
                if suggestions_visible:
                    if key_event.key() in {
                        Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter,
                    } and self.inline_function_suggestions.currentItem() is not None:
                        self._accept_inline_completion()
                        return True
                    if key_event.key() == Qt.Key.Key_Escape:
                        self.inline_function_suggestions.setVisible(False)
                        self.expression_edit.setFocus()
                        return True
                    if key_event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                        current_row = self.inline_function_suggestions.currentRow()
                        offset = -1 if key_event.key() == Qt.Key.Key_Up else 1
                        next_row = max(
                            0,
                            min(
                                self.inline_function_suggestions.count() - 1,
                                current_row + offset,
                            ),
                        )
                        self.inline_function_suggestions.setCurrentRow(next_row)
                        return True
            if watched is self.inline_function_suggestions and isinstance(key_event, QKeyEvent):
                if key_event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._accept_inline_completion()
                    self.expression_edit.setFocus()
                    return True
                if key_event.key() == Qt.Key.Key_Escape:
                    self.inline_function_suggestions.setVisible(False)
                    self.expression_edit.setFocus()
                    return True
        return super().eventFilter(watched, event)

    def _update_function_signature(self, function: str) -> None:
        self._set_function_signature(function)

    def _set_function_signature(self, function: str) -> None:
        function = function.strip().upper()
        if function not in DAX_FUNCTION_TEMPLATES:
            self.function_signature_label.setText(
                "Choose a function or place the caret inside a supported DAX call."
            )
            return
        template, _selection = DAX_FUNCTION_TEMPLATES[function]
        optional_argument_help = (
            " · table argument is optional; uses this measure's home table"
            if function == "COUNTROWS" else ""
        )
        self.function_signature_label.setText(
            f"Local syntax: {template}{optional_argument_help}."
        )

    def _insert_reference(self, combo: QComboBox) -> None:
        reference = combo.currentData()
        if not isinstance(reference, str) or not reference:
            self.preview_label.setText("Choose a loaded field or saved measure first.")
            return
        self._insert_text(reference)

    def _insert_field_reference(self) -> None:
        self._insert_reference(self.field_combo)

    def _insert_measure_reference(self) -> None:
        self._insert_reference(self.measure_combo)

    def _preview_measure(self) -> None:
        if self._preview_callback is None:
            return
        try:
            measure = self._current_measure()
            value = self._preview_callback(measure["name"], measure["expression"])
        except (MeasureError, TypeError, ValueError) as exc:
            self.preview_label.setStyleSheet("color: #a4262c;")
            self.preview_label.setText(str(exc))
            return
        self.preview_label.setStyleSheet("color: #107c10;")
        self.preview_label.setText(f"Current report-context result: {value}")

    @property
    def measure(self) -> dict[str, Any] | None:
        return dict(self._accepted_measure) if self.result() == QDialog.DialogCode.Accepted and self._accepted_measure else None

    def _current_measure(self) -> dict[str, Any]:
        name = self.name_edit.text().strip()
        if self.quick:
            if not self._quick_table_name:
                raise MeasureError(
                    "Quick measures require an active loaded model table."
                )
            column = self.column_combo.currentText()
            if not column:
                raise MeasureError("Choose a column for the quick measure.")
            function = str(self.function_combo.currentData())
            escaped_table = self._quick_table_name.replace("'", "''")
            expression = f"{function}('{escaped_table}'[{escape_bracket_name(column)}])"
        else:
            expression = self.expression_edit.toPlainText()
        measure = normalize_measure(
            name,
            expression,
            description=self.description_edit.toPlainText(),
            display_folder=self.display_folder_edit.text(),
            is_hidden=self.hidden_checkbox.isChecked(),
            home_table_id=self._home_table_id or None,
        )
        if measure["name"].casefold() in self._existing_names:
            raise MeasureError(f"A measure named {measure['name']!r} already exists.")
        return measure

    def _refresh_error(self, *_args: object) -> None:
        if hasattr(self, "preview_label"):
            self.preview_label.clear()
            self.preview_label.setStyleSheet("color: #526477;")
        try:
            self._current_measure()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.save_button.setEnabled(False)
            return
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.save_button.setEnabled(True)

    def _accept_measure(self) -> None:
        self._accepted_measure = None
        self.setResult(QDialog.DialogCode.Rejected)
        try:
            measure = self._current_measure()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        if self._preview_callback is not None:
            try:
                value = self._preview_callback(
                    measure["name"], measure["expression"]
                )
            except (MeasureError, TypeError, ValueError) as exc:
                self.preview_label.setStyleSheet("color: #a4262c;")
                self.preview_label.setText(str(exc))
                return
            self.preview_label.setStyleSheet("color: #107c10;")
            self.preview_label.setText(f"Current report-context result: {value}")
        self._accepted_measure = measure
        super().accept()

    def reject(self) -> None:
        self._accepted_measure = None
        super().reject()
