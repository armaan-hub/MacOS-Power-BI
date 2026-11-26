"""The one door between the app and the large-table DAX path (Stage C2a).

`route_measure` is the ONLY function the controller calls to get a measure value from a store table. It builds
every input fresh from the project and the store on each call (no cache of a plan, its stamps or a result),
plans the measure with dax_sql, runs it under a time budget and returns either a `StoreAnswer` or a
`RouteRefusal` with one plain sentence for the user.

Rule for the whole stage: a store table is answered by the store, or refused with a reason. It is never
answered by the in-memory engine (a store table has no rows in memory), and this module never imports that
engine.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from analytics_studio import dax_dates
from analytics_studio.large_table_error import LargeTableError
from analytics_studio.measures import MeasureError, parse_expression
from analytics_studio.store import dax_sql, dax_whitelist
from analytics_studio.store.base import StoreBusyError, StoreError
from analytics_studio.store.dax_sql import (
    ColumnMeta,
    Refusal,
    column_decimal_meta,
    plan_group_by,
    plan_measure,
)

# Codes of a RouteRefusal
CODE_SHAPE = "shape"
CODE_WHITELIST = "whitelist"
CODE_PLAN = "plan"
CODE_STALE = "stale"
CODE_BUSY = "busy"
CODE_TIMEOUT = "timeout"
CODE_CLOSED = "closed"

DEFAULT_BUDGET_S = 0.5
DEFAULT_REFRESH_BUDGET_S = 1.5
# Source kinds a store table can come from; the planner takes the first, and refuses the second on its own.
S1_SOURCE_KINDS = frozenset({"csv", "parquet"})

GENERIC_SENTENCE = "This measure cannot be computed on a large table yet."
MIXED_MODEL_REASON = "Large tables can only be combined with other tables in a later release."
BUSY_MESSAGE = "The large table is busy with another operation; try again when it finishes."
DEADLINE_MESSAGE = (
    "Not computed: the refresh took too long. Large-table calculations run in the background in a later release."
)
_RE_REINTERRUPT_S = 0.05


@dataclass(frozen=True)
class StoreAnswer:
    """What the store computed. kind is "scalar" (value) or "grouped" (rows, SQL order, not yet app order)."""

    kind: str
    value: Decimal | dax_dates.DaxDateTime | None = None
    rows: list[tuple[str, Decimal | dax_dates.DaxDateTime | None]] = field(default_factory=list)
    elapsed_s: float = 0.0
    table: str = ""


@dataclass(frozen=True)
class RouteRefusal:
    """The store cannot answer. `message` is one plain sentence for the user; `reason` is for tests and logs."""

    message: str
    reason: str
    code: str


@dataclass(frozen=True)
class StoreShape:
    """The project shape. ok is True for S1 (see `store_shape`); otherwise `reason` says why not, in one sentence."""

    ok: bool
    reason: str = ""
    table: str = ""


# ---------------------------------------------------------------------------------------------------------
# Reason text to one plain fragment. The message is "<measure> cannot be computed on a large table yet: <fragment>."
# Every REASON_* constant of dax_sql and dax_whitelist has an entry in FRAGMENTS (tests/test_dax_route.py checks).
# ---------------------------------------------------------------------------------------------------------
_W = dax_whitelist
_S = dax_sql
FRAGMENTS: dict[str, str] = {
    _W.REASON_DEFAULT_REFUSE: "this kind of formula is not available for large tables",
    _W.REASON_MAX_DEPTH_EXCEEDED: "its measures refer to each other too many levels deep",
    _W.REASON_NESTED_CALCULATE: "it nests one CALCULATE inside another",
    _W.REASON_DISTINCTCOUNTNOBLANK: "it uses DISTINCTCOUNTNOBLANK",
    _W.REASON_LOGICAL_AND: "it combines filters with &&",
    _W.REASON_ARITHMETIC: "it does arithmetic that large tables do not support yet",
    _W.REASON_LET: "it uses VAR and RETURN",
    _W.REASON_TWO_COLUMNS: "it compares one column with another column",
    _W.REASON_BLANK_COMPARISON: "it compares a value with BLANK()",
    _W.REASON_BOOLEAN_LITERAL: "it uses TRUE or FALSE inside a filter",
    _W.REASON_NO_TABLES: "it does not refer to any table",
    _W.REASON_LITERAL_LEFT: "a filter must have the column on the left and the value on the right",
    _W.REASON_TEXT_ORDERING: "it compares text with < or >, whose order may differ from Power BI",
    _W.REASON_COMPOSITE: "it uses NOT or || in a filter that is not a whole-number comparison",
    _W.REASON_OR_SAME_COLUMN: "the parts of an || filter are not all on the same column",
    _W.REASON_TOO_DEEP: "it is nested too deeply",
    _W.REASON_CAP_OR_TERMS: "it has a very long || chain",
    _W.REASON_CAP_PREDICATES: "it has too many filter arguments in one CALCULATE",
    _W.REASON_CAP_IN_ITEMS: "an IN list holds too many items",
    _W.REASON_CAP_NESTING: "its brackets are nested too deeply",
    _W.REASON_CAP_TOKENS: "the formula is too long",
    _W.REASON_TEXT_IN_FOLD: "a text IN list holds accented or special letters that may be compared differently from Power BI",
    _W.REASON_TEXT_NON_ASCII_SPACE: "a text value holds a special space character that may be compared differently from Power BI",
    _W.REASON_FILTER_CONTEXT_OTHER_TABLE: "a slicer or filter belongs to another table",
    _W.REASON_FILTER_CONTEXT_EMPTY: "a slicer or filter is empty",
    _W.REASON_SLICER_SAME_COLUMN: "a slicer filters the same column as the formula, which is not checked yet",
    _W.REASON_IN_NUMERIC_MIX: "it mixes a text IN list with a comparison on a number column",
    _W.REASON_IN_FOLD_EQ_MIX: "it mixes a text IN list with an equality on special letters",
    _W.REASON_UNEXPECTED: "the formula could not be checked",
    _W.REASON_DISTINCTCOUNT_NUMERIC: "it counts distinct values of a number column, which may differ from Power BI",
    _W.REASON_PARQUET_COUNTA: "COUNTA on a Parquet table may differ from Power BI",
    _W.REASON_DECIMAL_DIGITS: "a number column holds more than 38 digits",
    _S.PARQUET_PLAN_REASON: "tables loaded from Parquet files cannot compute measures yet",
    _S.PARQUET_COUNTA_REFUSAL_REASON: "COUNTA on a Parquet table may differ from Power BI",
    _S.REASON_IN_NON_ASCII_COLUMN: "a column used in a text IN list holds accented or special letters",
    _S.REASON_DATE_UNREADABLE: "a date column holds text that is not a plain date",
    _S.REASON_PLAN_STALE: "the table changed while the value was prepared",
    _S.REASON_DECIMAL_LITERAL_FIT: "a number in a filter does not fit the column's precision",
    _S.REASON_GROUP_NON_ASCII_SPACE: "the grouping column holds a special space character",
    _S.REASON_GROUP_BY_SHAPE: "the grouping must be one column",
    _S.REASON_GROUP_OWN_FILTER: "it filters the same column the result is grouped by",
    _S.REASON_GROUP_BY_TYPE: "results can only be grouped by a text, date or true/false column",
}

_PLAIN_WORDS = {
    "whole_number": "whole number", "decimal_number": "decimal number", "string": "text", "text": "text",
    "number": "number", "date": "date", "boolean": "true/false", "datetime": "date and time", "fixed": "fixed decimal",
}


def _plain(word: str) -> str:
    """An internal type name in plain words (the user never sees whole_number, decimal_number, string)."""
    return _PLAIN_WORDS.get(word, word.replace("_", " "))


# Reasons that say what is WRONG with the formula (a missing column, a syntax error): a full sentence, not worded
# as "cannot be computed on a large table yet", because a large table is not the cause.
_PROBLEMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^unknown column '(.*)' in table '(.*)'$"), "Column '{0}' was not found in table {1}."),
    (re.compile(r"^unknown column '(.*)'$"), "Column '{0}' was not found."),
    (re.compile(r"^unknown column or measure '(.*)'$"), "'{0}' is not a column or a measure of this model."),
    (re.compile(r"^unknown measure '(.*)'$"), "Measure '{0}' was not found."),
    (re.compile(r"^unknown table '(.*)'$"), "Table '{0}' was not found."),
    (re.compile(r"^unknown home table '(.*)'$"), "Table '{0}' was not found."),
    (re.compile(r"^cycle detected in measure reference '(.*)'$"), "Measure '{0}' refers to itself, directly or through other measures."),
    (re.compile(r"^The DAX expression ends unexpectedly\.?$"), "The formula is not finished: it ends unexpectedly."),
    (re.compile(r"^Unexpected token '(.*)'\.?$"), "The formula has an unexpected '{0}'."),
    (re.compile(r"^(\S+) needs one column reference, such as .*$"), "{0} needs one column, such as {0}([Amount])."),
    (re.compile(r"^CALCULATE needs an expression\.?$"), "CALCULATE needs an expression to calculate."),
    (re.compile(r"^COUNTROWS needs no argument or one loaded table"), "COUNTROWS needs a table, such as COUNTROWS(Sales)."),
    (re.compile(r"^Enter a DAX expression\.?$"), "Enter a formula."),
    (re.compile(r"^IN needs a table or at least one value"), "IN needs at least one value; an empty list is not allowed."),
    (re.compile(r"^NOT needs one logical expression\.?$"), "NOT needs exactly one condition."),
    (re.compile(r"^Unsupported character at position (\d+)\.?$"), "The formula has a character that is not allowed (position {0})."),
    (re.compile(r"^an empty table constructor \{\} is not accepted\.?$"), "IN needs at least one value; an empty list is not allowed."),
]

# Reasons that carry a name or a number: (pattern, fragment template). First match wins.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^function (\S+) is not on the store whitelist$"), "it uses the function {0}, which large tables do not support yet"),
    (re.compile(r"^operator (\S+) is not on the store whitelist for (\S+) columns$"), "it uses the operator {0} on a {1} column"),
    (re.compile(r"^operator (\S+) is not on the store whitelist$"), "it uses the operator {0}"),
    (re.compile(r"^node kind (\S+) is not on the store whitelist$"), "it uses a formula part ({0}) that large tables do not support yet"),
    (re.compile(r"^measure references multiple tables: (.*)$"), "it refers to more than one table ({0})"),
    (re.compile(r"^reference to '(.*)' is not a valid measure expression$"), "it uses {0} in a way large tables do not support yet"),
    (re.compile(r"^(\S+) not supported on (\S+) column$"), "{0} does not work on a {1} column"),
    (re.compile(r"^(\S+) requires exactly one argument$"), "{0} needs exactly one argument"),
    (re.compile(r"^(\S+) argument must be a column reference$"), "{0} must be given a column"),
    (re.compile(r"^COUNTROWS argument must be a table$"), "COUNTROWS must be given a table"),
    (re.compile(r"^CALCULATE requires at least one argument$"), "CALCULATE needs at least one argument"),
    (re.compile(r"^comparison must involve a column reference$"), "a filter must compare a column with a value"),
    (re.compile(r"^literal type (\S+) does not fit (\S+) column$"), "a filter compares a {1} column with a {0} value"),
    (re.compile(r"^unexpected error while classifying(?:: .*)?$"), "the formula could not be checked"),
    (re.compile(r"^ALL is supported only"), "it uses ALL in a way large tables do not support yet"),
    (re.compile(r"^BLANK\(\) is supported only"), "it uses BLANK() in a place large tables do not support yet"),
    (re.compile(r"^CALCULATE filters must be column comparisons"), "a CALCULATE filter must compare a column with a value"),
    (re.compile(r"^FILTER is supported only"), "it uses FILTER in a way large tables do not support yet"),
    (re.compile(r"^Engine bug: date IN filter"), "an IN filter on a date column meets blank cells, which Power BI treats as an error"),
    (re.compile(r"^Engine bug: numeric IN"), "an IN or && filter on a number column meets blank cells, which Power BI treats as an error"),
    (re.compile(r"^not a column reference$"), "a filter must name a column"),
    (re.compile(r"^operator (\S+) is not supported$"), "it uses the operator {0}"),
    (re.compile(r"^predicate on a (\S+) column is not supported$"), "a filter on a {0} column is not supported"),
    (re.compile(r"^text literal cannot be sent to the store$"), "a text value in a filter cannot be used"),
    (re.compile(r"^text literal contains U\+0000$"), "a text value in a filter holds a character that cannot be used"),
    (re.compile(r"^unsupported (?:IN |date |decimal |text |whole-number )?predicate$"), "a filter of this kind is not supported"),
    (re.compile(r"^unary operator on non-number literal"), "a minus sign is used on something that is not a number"),
    (re.compile(r"^invalid literal node$"), "a filter value is not valid"),
    (re.compile(r"^node kind (\S+) is not a valid literal$"), "a filter value must be a plain number, text or date"),
    (re.compile(r"^measure names '.*' and '.*' collide"), "two measure names differ only by letter case"),
    (re.compile(r"^measure reference '.*' not expected in column context$"), "a measure is used where a column is expected"),
    (re.compile(r"^boolean column comparison not supported on store$"), "it compares a true/false column"),
    (re.compile(r"^(?:unknown )?column type '(.*?)' is not on the store whitelist.*$"), "a column has the type '{0}', which large tables do not support yet"),
    (re.compile(r"^unknown column type"), "a column has a type that large tables do not support yet"),
    (re.compile(r"^call NOT requires exactly one argument$"), "NOT needs exactly one argument"),
    (re.compile(r"^left side of IN must be a column reference$"), "the left side of IN must be a column"),
    (re.compile(r"^IN filter not supported on (\S+) column$"), "IN does not work on a {0} column"),
    (re.compile(r"^right side of IN must be a table constructor"), "the right side of IN must be a list of text values"),
    (re.compile(r"^IN (?:needs at least one|values must be) string literal"), "IN must list text values"),
    (re.compile(r"^numeric literal"), "a number in a filter is not valid or too long"),
    (re.compile(r"^whole-number (?:column needs|literal is outside)"), "a number in a filter does not fit a whole-number column"),
    (re.compile(r"^DATE "), "a date in a filter is not a valid date"),
    (re.compile(r"^table names '.*' collide"), "two table names differ only by letter case"),
    (re.compile(r"^column names '.*' collide"), "two column names differ only by letter case"),
    (re.compile(r"^unknown source kind"), "the table comes from a source that large tables do not support yet"),
    (re.compile(r"^a filter context is a tuple"), "a slicer or filter is not in a readable form"),
    (re.compile(r"^max_digits for "), "a column's digit count is not readable"),
    (re.compile(r"^no decimal metadata for column '(.*)'$"), "the number column '{0}' could not be read"),
    (re.compile(r"^no store table for '(.*)'$"), "the table '{0}' is not in the large-data store"),
    (re.compile(r"^no SQL for (\S+)$"), "{0} is not available for large tables yet"),
    (re.compile(r"^no group-by SQL for (\S+)$"), "{0} cannot be grouped on a large table yet"),
    (re.compile(r"^unsupported base expression$"), "the formula is not a single total over a column"),
    (re.compile(r"^the whitelist gave no table$"), "the formula does not refer to a table"),
    (re.compile(r"^refused by the whitelist$"), "this kind of formula is not available for large tables"),
    (re.compile(r"^filter context refused by the whitelist$"), "a slicer or filter is not available for large tables"),
    (re.compile(r"^the group-by column is on table '(.*)', the measure on '(.*)'$"), "the grouping column and the formula are on different tables"),
]

# Reasons that come from the planner or the data checks (not from the whitelist): code "plan".
_PLAN_CODE_REASONS = frozenset({
    _S.PARQUET_PLAN_REASON,
    _S.REASON_IN_NON_ASCII_COLUMN,
    _S.REASON_DATE_UNREADABLE,
    _S.REASON_DECIMAL_LITERAL_FIT,
    _S.REASON_GROUP_NON_ASCII_SPACE,
    _S.REASON_GROUP_BY_SHAPE,
    _S.REASON_GROUP_OWN_FILTER,
    _S.REASON_GROUP_BY_TYPE,
    _W.REASON_IN_FOLD_EQ_MIX,
})
_PLAN_CODE_PATTERNS = (
    re.compile(r"^no decimal metadata for column"),
    re.compile(r"^no store table for"),
    re.compile(r"^no SQL for"),
    re.compile(r"^no group-by SQL for"),
    re.compile(r"^unsupported base expression$"),
    re.compile(r"^the group-by column is on table"),
)


_TYPE_NAMES = frozenset({"whole_number", "decimal_number", "string"})


def problem_for_reason(reason: str) -> str | None:
    """The full sentence for a reason that says what is wrong with the formula, or None."""
    text = reason.strip()
    for pattern, template in _PROBLEMS:
        match = pattern.match(text)
        if match is not None:
            return template.format(*match.groups())
    return None


def fragment_for_reason(reason: str) -> str | None:
    """The plain fragment for ONE reason text, or None when the reason has no entry."""
    text = reason.strip()
    fixed = FRAGMENTS.get(text)
    if fixed is not None:
        return fixed
    for pattern, template in _PATTERNS:
        match = pattern.match(text)
        if match is not None:
            return template.format(*(_plain(g) if g in _TYPE_NAMES else g for g in match.groups()))
    return None


def reason_is_mapped(reason: str) -> bool:
    return fragment_for_reason(reason) is not None or problem_for_reason(reason) is not None


def _split_reasons(reason: str) -> list[str]:
    """Split Refusal.reason into its reasons, in order. The reasons are joined with '; '.

    A known reason text that itself holds '; ' (the text-ordering reason) is taken whole first, longest first;
    everything else is cut at '; ' and each part is mapped on its own, so one reason never hides another.
    """
    joined = sorted((text for text in FRAGMENTS if "; " in text), key=len, reverse=True)
    parts: list[str] = []
    rest = reason.strip()
    while rest:
        for text in joined:
            if rest.startswith(text):
                parts.append(text)
                rest = rest[len(text):]
                break
        else:
            head, _, rest = rest.partition("; ")
            parts.append(head.strip())
            continue
        rest = rest[2:] if rest.startswith("; ") else rest.lstrip()
    return [part for part in parts if part] or [reason]


def message_for_reason(name: str, reason: str) -> str:
    """One plain sentence for the user, every distinct reason once, in order.

    A reason that says what is wrong (missing column, syntax error) gives that sentence. A reason that the large
    table cannot handle gives '<name> cannot be computed on a large table yet: <fragment>.'. An unknown reason
    gives the generic sentence and the raw reason after a dash.
    """
    fragments: list[str] = []
    problems: list[str] = []
    unknown: list[str] = []
    for item in _split_reasons(reason):
        problem = problem_for_reason(item)
        fragment = None if problem is not None else fragment_for_reason(item)
        if problem is not None:
            if problem not in problems:
                problems.append(problem)
        elif fragment is None:
            if item not in unknown:
                unknown.append(item)
        elif fragment not in fragments:
            fragments.append(fragment)
    sentences: list[str] = []
    if problems:
        sentences.append(" ".join(problems) if name == "This measure" else f"{name}: {' '.join(problems)}")
    if fragments:
        joined = fragments[0] if len(fragments) == 1 else f"{', '.join(fragments[:-1])} and {fragments[-1]}"
        sentences.append(f"{name} cannot be computed on a large table yet: {joined}.")
    if sentences and not unknown:
        return " ".join(sentences)
    raw = "; ".join(unknown) if sentences else reason.strip()
    raw = raw.rstrip(".")
    if sentences:
        return " ".join(sentences + [f"{name} also has: {raw}."])
    if name == "This measure":
        return f"{GENERIC_SENTENCE} - {raw}."
    return f"{name} cannot be computed on a large table yet - {raw}."


def _code_for_reason(reason: str) -> str:
    if reason == _S.REASON_PLAN_STALE:
        return CODE_STALE
    if reason in _PLAN_CODE_REASONS:
        return CODE_PLAN
    if any(pattern.match(reason) for pattern in _PLAN_CODE_PATTERNS):
        return CODE_PLAN
    return CODE_WHITELIST


def _refusal(name: str, reason: str, code: str | None = None) -> RouteRefusal:
    return RouteRefusal(message_for_reason(name, reason), reason, code or _code_for_reason(reason))


# ---------------------------------------------------------------------------------------------------------
# Project shape
# ---------------------------------------------------------------------------------------------------------
def _model(project: Mapping[str, Any]) -> Mapping[str, Any]:
    model = project.get("model", {}) if isinstance(project, Mapping) else {}
    return model if isinstance(model, Mapping) else {}


def _store_info_by_source(project: Mapping[str, Any], candidates: Mapping[str, Any] | None) -> dict[str, tuple[str, str]]:
    """{source_id: (physical store table, source kind)} for every store-backed source.

    With `candidates` (the controller's loaded candidates) the store-backed ones are those that say
    `is_store_backed`; without, the sources whose project record carries a `store` entry.
    """
    out: dict[str, tuple[str, str]] = {}
    if candidates is not None:
        for source_id, candidate in candidates.items():
            if getattr(candidate, "is_store_backed", False):
                out[str(source_id)] = (str(getattr(candidate, "store_table", "")), str(getattr(candidate, "kind", "")))
        return out
    for source in project.get("data_sources", []) if isinstance(project, Mapping) else []:
        if not isinstance(source, Mapping):
            continue
        store = source.get("store")
        if isinstance(store, Mapping) and store.get("table"):
            out[str(source.get("id", ""))] = (str(store["table"]), str(source.get("kind", "")))
    return out


def route_is_available(project: Mapping[str, Any], candidates: Mapping[str, Any] | None = None) -> bool:
    """True when the project has at least one store table: the controller then takes the store path or refuses.

    There is no third outcome: a project with a store table never reaches the in-memory engine.
    """
    return bool(_store_info_by_source(project, candidates))


def store_shape(project: Mapping[str, Any], candidates: Mapping[str, Any] | None = None) -> StoreShape:
    """Decide the project shape. Only S1 is wired: ALL of

    (i) every model table is a store table, or the model has exactly one table and it is a store table (these are
        one rule: "no ordinary in-memory table sits beside a store table");
    (ii) the model has no relationships;
    (iii) the table has no calculated columns (the store drops them);
    (iv) the table's source kind is one the planner takes (csv, parquet).
    Anything else with a store table is refused whole.
    """
    store_info = _store_info_by_source(project, candidates)
    if not store_info:
        return StoreShape(False, "The project has no large table.")
    model = _model(project)
    tables = [t for t in model.get("tables", []) if isinstance(t, Mapping)]
    if not tables:
        return StoreShape(False, "The project has no large table.")
    for table in tables:
        source_id = str(table.get("source_id") or table.get("id") or "")
        if source_id not in store_info:
            return StoreShape(False, MIXED_MODEL_REASON)
    if len(tables) != 1 and len({str(t.get("source_id") or t.get("id")) for t in tables}) != len(tables):
        return StoreShape(False, MIXED_MODEL_REASON)
    if len(tables) != 1:
        # Two store tables with no relationship: the whitelist works on one home table; refuse whole in C2.
        return StoreShape(False, MIXED_MODEL_REASON)
    if model.get("relationships"):
        return StoreShape(False, MIXED_MODEL_REASON)
    table = tables[0]
    if table.get("calculated_columns"):
        return StoreShape(False, "Large tables cannot have calculated columns yet.")
    source_id = str(table.get("source_id") or table.get("id") or "")
    physical, kind = store_info[source_id]
    if not physical or kind not in S1_SOURCE_KINDS:
        return StoreShape(False, "This kind of large table cannot compute measures yet.")
    return StoreShape(True, "", str(table.get("name", "")))


# ---------------------------------------------------------------------------------------------------------
# Inputs, rebuilt on every call
# ---------------------------------------------------------------------------------------------------------
def _measure_map(project: Mapping[str, Any], override: Mapping[str, str] | None) -> dict[str, str]:
    if override is not None:
        return {str(k): str(v) for k, v in override.items()}
    out: dict[str, str] = {}
    for measure in _model(project).get("measures", []):
        if isinstance(measure, Mapping) and "name" in measure and "expression" in measure:
            out[str(measure["name"])] = str(measure["expression"])
    return out


def _closure_text(expression: str, measures: Mapping[str, str], filter_context: tuple[str, ...]) -> str:
    """The expression, the measures it uses (through other measures too) and the filter text, case-folded.

    Only these: a call for one measure must not read the decimal metadata of columns that other measures use.
    """
    folded = {key.casefold(): body for key, body in measures.items()}
    texts = [expression]
    seen: set[str] = set()
    pending = [expression]
    while pending:
        found: set[str] = set()
        try:
            _referenced_measure_names(parse_expression(pending.pop()), found)
        except Exception:
            continue  # the planner reports a syntax error in its own words
        for reference in found:
            if reference in folded and reference not in seen:
                seen.add(reference)
                texts.append(folded[reference])
                pending.append(folded[reference])
    return "\n".join([*texts, *filter_context]).casefold()


def _decimal_meta(
    store: Any, table_name: str, physical: str, column_types: Mapping[str, str], text: str
) -> dict[tuple[str, str], ColumnMeta]:
    """Decimal scale and digits of the decimal columns the formulas may read (a column whose name is absent is skipped)."""
    wanted = [
        column for column, ctype in column_types.items()
        if ctype == "decimal_number" and (column.casefold() in text or column.casefold().replace("]", "]]") in text)
    ]
    found = column_decimal_meta(store, physical, wanted) if wanted else {}
    return {(table_name, column): meta for column, meta in found.items()}


class _Budget:
    """Interrupts the store when the budget runs out. Re-fires until cancelled: an interrupt that lands between two
    queries of one execute would otherwise be lost."""

    def __init__(self, store: Any, budget_s: float) -> None:
        self._store = store
        self._budget_s = max(0.0, budget_s)
        self._done = threading.Event()
        self.fired = threading.Event()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._arm(self._budget_s)

    def _arm(self, delay: float) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._timer = threading.Timer(delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        # The lock is held while interrupting, so cancel() returns only when no interrupt can still arrive
        # (a late interrupt must never hit the next query). DuckStore.interrupt takes no store lock.
        with self._lock:
            if self._done.is_set():
                return
            self.fired.set()
            self._store.interrupt()
            self._timer = threading.Timer(_RE_REINTERRUPT_S, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        with self._lock:
            self._done.set()
            if self._timer is not None:
                self._timer.cancel()


def _is_interrupt(exc: BaseException) -> bool:
    return "interrupt" in str(exc).casefold()


def route_measure(
    project: Mapping[str, Any],
    measure_name_or_expression: str,
    *,
    project_store: Any,
    filter_context: tuple[str, ...] = (),
    group_by: tuple[str, str] | None = None,
    budget_s: float = DEFAULT_BUDGET_S,
    deadline: float | None = None,
    candidates: Mapping[str, Any] | None = None,
    measures: Mapping[str, str] | None = None,
) -> StoreAnswer | RouteRefusal:
    """Answer one measure on the store, or refuse with a plain sentence. Never raises for a bad measure.

    `measure_name_or_expression` is a measure name of the project, or a DAX expression (a draft). `measures`
    (optional) replaces the project's measures {name: expression}, used to check a measure before it is saved.
    `deadline` is an absolute time.monotonic() value shared by a refresh: a measure started after it is not run.
    `candidates` is the controller's loaded candidates (see `_store_info_by_source`).
    It raises only for programmer errors (wrong argument types).
    """
    if not isinstance(project, Mapping):
        raise TypeError("project must be a mapping")
    if not isinstance(measure_name_or_expression, str):
        raise TypeError("measure_name_or_expression must be text")
    if project_store is None or not hasattr(project_store, "job"):
        raise TypeError("project_store must be a ProjectStore")
    if not isinstance(filter_context, tuple):
        raise TypeError("filter_context must be a tuple of predicate texts")
    if group_by is not None and not (isinstance(group_by, tuple) and len(group_by) == 2):
        raise TypeError("group_by must be a (table, column) tuple or None")

    measure_map = _measure_map(project, measures)
    name = "This measure"
    expression = measure_name_or_expression
    for known, body in measure_map.items():
        if known.casefold() == measure_name_or_expression.strip().casefold():
            name, expression = known, body
            break

    shape = store_shape(project, candidates)
    if not shape.ok:
        return RouteRefusal(f"{name}: {shape.reason}" if name != "This measure" else shape.reason, shape.reason, CODE_SHAPE)

    started = time.monotonic()
    effective = float(budget_s)
    if deadline is not None:
        remaining = deadline - started
        if remaining <= 0:
            return RouteRefusal(DEADLINE_MESSAGE, "refresh deadline passed", CODE_TIMEOUT)
        effective = min(effective, remaining)

    info = _store_info_by_source(project, candidates)
    model_table = next(t for t in _model(project)["tables"] if isinstance(t, Mapping))
    table_name = str(model_table.get("name", ""))
    physical, kind = info[str(model_table.get("source_id") or model_table.get("id") or "")]
    column_types = {str(c): str(t) for c, t in dict(model_table.get("column_types", {})).items()}
    tables = {table_name: column_types}
    store_tables = {table_name: physical}
    text = _closure_text(expression, measure_map, filter_context)
    if kind == "parquet":
        # The planner does not take Parquet tables yet: say it first, in its own sentence, before any other reason.
        return _refusal(name, dax_sql.PARQUET_PLAN_REASON)

    try:
        with project_store.job():
            store = project_store.store
            # The budget covers everything that touches the store: the decimal metadata, the guards and the SELECT.
            budget = _Budget(store, effective)
            budget.start()
            try:
                try:
                    column_meta = _decimal_meta(store, table_name, physical, column_types, text)
                    kwargs: dict[str, Any] = dict(
                        home_table=table_name,
                        tables=tables,
                        store_tables=store_tables,
                        column_meta=column_meta,
                        measures=measure_map,
                        source_kind=kind,
                        filter_context=filter_context,
                    )
                    if group_by is None:
                        plan: Any = plan_measure(expression, **kwargs)
                    else:
                        plan = plan_group_by(expression, group_by=group_by, **kwargs)
                    result = plan if isinstance(plan, Refusal) else plan.execute(store)
                except StoreBusyError:
                    return RouteRefusal(BUSY_MESSAGE, "store busy", CODE_BUSY)
                except StoreError as exc:
                    if budget.fired.is_set() and _is_interrupt(exc):
                        return _timeout(name, effective)
                    if project_store.closed or "closed" in str(exc).casefold():
                        return RouteRefusal(
                            f"{name} cannot be computed: the large table is closed.", str(exc), CODE_CLOSED
                        )
                    return RouteRefusal(
                        f"{name} cannot be computed: the large table could not be read.", str(exc), CODE_PLAN
                    )
                except (MeasureError, LargeTableError) as exc:
                    return RouteRefusal(f"{name} cannot be computed on a large table: {exc}", str(exc), CODE_PLAN)
                except Exception as exc:  # nothing may escape into a card refresh, a save or a preview
                    return RouteRefusal(
                        f"{name} could not be computed ({type(exc).__name__}).", f"{type(exc).__name__}: {exc}", CODE_PLAN
                    )
                if isinstance(result, Refusal):
                    # An interrupt that lands inside a guard query is swallowed there and comes back as a stale or
                    # missing-metadata refusal: when the budget fired, the honest answer is the timeout.
                    if budget.fired.is_set():
                        return _timeout(name, effective)
                    return _refusal(name, result.reason)
            finally:
                budget.cancel()
            elapsed = time.monotonic() - started
            if isinstance(plan, dax_sql.GroupByPlan):
                return StoreAnswer("grouped", None, list(result), elapsed, table_name)
            return StoreAnswer("scalar", result, [], elapsed, table_name)
    except StoreBusyError:
        return RouteRefusal(BUSY_MESSAGE, "store busy", CODE_BUSY)
    except StoreError as exc:
        return RouteRefusal(f"{name} cannot be computed: the large table is closed.", str(exc), CODE_CLOSED)


def refresh_deadline(seconds: float = DEFAULT_REFRESH_BUDGET_S) -> float:
    """The shared absolute deadline (time.monotonic) of one card refresh."""
    return time.monotonic() + seconds


def _referenced_measure_names(node: Any, found: set[str]) -> None:
    if isinstance(node, tuple):
        if len(node) == 3 and node[0] == "reference" and node[1] == "":
            found.add(str(node[2]).casefold())
        for part in node:
            _referenced_measure_names(part, found)
    elif isinstance(node, (list, frozenset)):
        for part in node:
            _referenced_measure_names(part, found)


def measures_depending_on(measures: Mapping[str, str], names: set[str]) -> list[str]:
    """Names of the measures that use any of `names` (directly or through other measures), by their text.

    A measure whose text cannot be parsed is left out (the save path reports that error itself).
    """
    wanted = {n.casefold() for n in names}
    uses: dict[str, set[str]] = {}
    for name, expression in measures.items():
        found: set[str] = set()
        try:
            _referenced_measure_names(parse_expression(expression), found)
        except MeasureError:
            continue
        uses[name] = found
    out: list[str] = []
    changed = True
    while changed:
        changed = False
        for name, found in uses.items():
            if name not in out and name.casefold() not in wanted and found & wanted:
                out.append(name)
                wanted.add(name.casefold())
                changed = True
    return out


def _timeout(name: str, budget_s: float) -> RouteRefusal:
    return RouteRefusal(
        f"{name} took longer than {budget_s:g} seconds on this large table and was stopped.",
        f"interrupted after {budget_s:g} s",
        CODE_TIMEOUT,
    )
