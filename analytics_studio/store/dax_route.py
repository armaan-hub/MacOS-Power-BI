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

import base64
import copy
import json
import re
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

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
CODE_FILTER = "filter"
CODE_TOO_MANY = "too_many"
CODE_CANCELED = "canceled"

# Time caps. DEFAULT_BUDGET_S is what a caller that names no cap gets; every caller names its own:
#   GUI_LIST_BUDGET_S    slicer, page-filter and region lists, which QML reads synchronously (cannot be asynchronous
#                        without a QML change);
#   VALIDATE_BUDGET_S    create / edit / delete measure validation: user-initiated, needs the answer before saving,
#                        runs on the GUI thread through a reader, so it never blocks the data grid and is bounded;
#   BACKGROUND_BUDGET_S  every background request: long enough for 1,000,000 rows with many groups, short enough that
#                        a runaway query ends by itself (the user can cancel earlier).
# The shared page deadlines (DEFAULT_REFRESH_BUDGET_S, DEFAULT_VISUAL_REFRESH_BUDGET_S) are for the synchronous
# callers that still exist (lists); background requests pass deadline=None and each has its own cap.
DEFAULT_BUDGET_S = 0.5
GUI_LIST_BUDGET_S = 2.0
VALIDATE_BUDGET_S = 5.0
BACKGROUND_BUDGET_S = 30.0
DEFAULT_REFRESH_BUDGET_S = 1.5
DEFAULT_VISUAL_REFRESH_BUDGET_S = 2.0
# Source kinds a store table can come from; the planner takes the first, and refuses the second on its own.
S1_SOURCE_KINDS = frozenset({"csv", "parquet"})

GENERIC_SENTENCE = "This measure cannot be computed on a large table yet."
MIXED_MODEL_REASON = "Large tables can only be combined with other tables in a later release."
BUSY_MESSAGE = "The large table is busy with another operation; try again when it finishes."
DEADLINE_MESSAGE = (
    "Not computed: the refresh took too long. Large-table calculations run in the background in a later release."
)
CANCELED_MESSAGE = "Canceled."
CANCELED_REASON = "canceled by the user"
_RE_REINTERRUPT_S = 0.05
_CANCEL_POLL_S = 0.05  # how often a budget with a cancel event looks at it (an Event cannot be waited on together with another)
MAX_GROUPS = 2000
DISTINCT_LIMIT = 1000
GROUP_TYPE_MESSAGE = "Large tables can only group by text, date or yes/no columns for now."


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
    _S.REASON_DATE_BEFORE_1900: "a date column holds a date before the year 1900, which large tables do not show the way Power BI does yet",
    _S.REASON_PLAN_STALE: "the table changed while the value was prepared",
    _S.REASON_DECIMAL_LITERAL_FIT: "a number in a filter does not fit the column's precision",
    _S.REASON_GROUP_NON_ASCII_SPACE: "the grouping column holds a special space character",
    _S.REASON_GROUP_BY_SHAPE: "the grouping must be one column",
    _S.REASON_GROUP_OWN_FILTER: "it has a CALCULATE filter of its own on the column the results are grouped by, which large tables cannot combine with grouping yet",
    _S.REASON_GROUP_BY_TYPE: "results can only be grouped by a text, date or true/false column",
    CANCELED_REASON: "the calculation was canceled",
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
    _S.REASON_DATE_BEFORE_1900,
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


# ---------------------------------------------------------------------------------------------------------
# Plain data for a worker thread (Stage C3)
# ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SnapshotTable:
    """One model table as the route reads it: ids, name and column types, in the project's order."""

    id: str | None
    source_id: str | None
    name: str
    column_types: tuple[tuple[str, str], ...]
    has_calculated_columns: bool


@dataclass(frozen=True)
class SnapshotSource:
    """One store-backed source: the store table name and the source kind (what a StoreCandidate says)."""

    source_id: str
    store_table: str
    kind: str
    is_store_backed: bool = True


@dataclass(frozen=True)
class RouteSnapshot:
    """A deep copy of exactly what `route_*` read from the project and the candidates, and nothing else.

    A worker thread given a snapshot never reads the live project dict or a live StoreCandidate, so the GUI thread
    may change them while the worker runs. Nothing in it is shared with the live objects: `measures` is a read-only
    mapping of {name: expression}, the rest is tuples of frozen values.
    """

    tables: tuple[SnapshotTable, ...]
    measures: Mapping[str, str]
    relationships: tuple[Any, ...]
    sources: tuple[SnapshotSource, ...]

    def project_view(self) -> dict[str, Any]:
        """A fresh plain project mapping with the same answers as the live project (new dicts on every call)."""
        tables: list[dict[str, Any]] = []
        for table in self.tables:
            record: dict[str, Any] = {"name": table.name, "column_types": dict(table.column_types)}
            if table.id is not None:
                record["id"] = table.id
            if table.source_id is not None:
                record["source_id"] = table.source_id
            if table.has_calculated_columns:
                record["calculated_columns"] = [{"name": "calculated column"}]
            tables.append(record)
        return {
            "model": {
                "tables": tables,
                "measures": [{"name": name, "expression": body} for name, body in self.measures.items()],
                "relationships": copy.deepcopy(list(self.relationships)),
            },
        }

    def candidate_view(self) -> dict[str, SnapshotSource]:
        return {source.source_id: source for source in self.sources}


def snapshot_for_route(project: Mapping[str, Any], candidates: Mapping[str, Any] | None = None) -> RouteSnapshot:
    """Copy what `route_*` read from `project` (and `candidates`) into a `RouteSnapshot`. Call it on the GUI thread."""
    if not isinstance(project, Mapping):
        raise TypeError("project must be a mapping")
    model = _model(project)
    tables: list[SnapshotTable] = []
    for table in model.get("tables", []):
        if not isinstance(table, Mapping):
            continue
        ident, source_id = table.get("id"), table.get("source_id")
        tables.append(SnapshotTable(
            id=None if ident is None else str(ident),
            source_id=None if source_id is None else str(source_id),
            name=str(table.get("name", "")),
            column_types=tuple((str(c), str(t)) for c, t in dict(table.get("column_types", {}) or {}).items()),
            has_calculated_columns=bool(table.get("calculated_columns")),
        ))
    sources = tuple(
        SnapshotSource(source_id, physical, kind) for source_id, (physical, kind) in _store_info_by_source(project, candidates).items()
    )
    return RouteSnapshot(
        tables=tuple(tables),
        measures=MappingProxyType(_measure_map(project, None)),
        relationships=tuple(copy.deepcopy(list(model.get("relationships") or []))),
        sources=sources,
    )


def _resolve_inputs(
    project: Any, candidates: Mapping[str, Any] | None
) -> tuple[Any, Mapping[str, Any] | None]:
    """(project mapping, candidates) for the helpers: a RouteSnapshot becomes plain views, anything else is unchanged."""
    if isinstance(project, RouteSnapshot):
        if candidates is not None:
            raise TypeError("candidates must be None when the project is a RouteSnapshot")
        return project.project_view(), project.candidate_view()
    return project, candidates


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
    project, candidates = _resolve_inputs(project, candidates)
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
    project, candidates = _resolve_inputs(project, candidates)
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
    """Interrupts the reader when the budget runs out or when `cancel` is set. Re-fires until cancelled: an interrupt
    that lands between two queries of one execute would otherwise be lost.

    One watcher thread. Without a cancel event it sleeps on the internal done event until the budget ends, so it
    never polls; with one it waits on the cancel event in short steps (an Event cannot be waited on together with
    another one), so a cancel reaches the query within `_CANCEL_POLL_S`.
    """

    def __init__(self, interrupt: Any, budget_s: float, cancel: threading.Event | None = None) -> None:
        self._interrupt = interrupt
        self._budget_s = max(0.0, budget_s)
        self._cancel_event = cancel
        self._done = threading.Event()
        self.fired = threading.Event()  # the time budget ran out
        self.canceled = threading.Event()  # the cancel event was seen
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._watch, name="dax-route-budget", daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        end = time.monotonic() + self._budget_s
        cancel = self._cancel_event
        while not self._done.is_set():
            is_canceled = cancel is not None and cancel.is_set()
            expired = time.monotonic() >= end
            if is_canceled or expired:
                # The lock is held while interrupting, so cancel() returns only when no interrupt can still arrive
                # (a late interrupt must never hit the next query). StoreReader.interrupt takes no store lock.
                with self._lock:
                    if self._done.is_set():
                        return
                    (self.canceled if is_canceled else self.fired).set()
                    self._interrupt()
                self._done.wait(_RE_REINTERRUPT_S)
                continue
            remaining = end - time.monotonic()
            if cancel is None:
                self._done.wait(remaining)
            else:
                cancel.wait(min(remaining, _CANCEL_POLL_S))

    def cancel(self) -> None:
        """End the budget: after this returns no interrupt can arrive any more."""
        with self._lock:
            self._done.set()


def _is_interrupt(exc: BaseException) -> bool:
    return "interrupt" in str(exc).casefold()


def _canceled_refusal() -> RouteRefusal:
    return RouteRefusal(CANCELED_MESSAGE, CANCELED_REASON, CODE_CANCELED)


def route_measure(
    project: Mapping[str, Any] | RouteSnapshot,
    measure_name_or_expression: str,
    *,
    project_store: Any,
    filter_context: tuple[str, ...] = (),
    group_by: tuple[str, str] | None = None,
    budget_s: float = DEFAULT_BUDGET_S,
    deadline: float | None = None,
    candidates: Mapping[str, Any] | None = None,
    measures: Mapping[str, str] | None = None,
    reader: Any = None,
    cancel: threading.Event | None = None,
) -> StoreAnswer | RouteRefusal:
    """Answer one measure on the store, or refuse with a plain sentence. Never raises for a bad measure.

    `measure_name_or_expression` is a measure name of the project, or a DAX expression (a draft). `measures`
    (optional) replaces the project's measures {name: expression}, used to check a measure before it is saved.
    `deadline` is an absolute time.monotonic() value shared by a refresh: a measure started after it is not run.
    `candidates` is the controller's loaded candidates (see `_store_info_by_source`). `project` is the live project
    mapping (with `candidates`) or a `RouteSnapshot` (then `candidates` must be None).

    Every query runs on a StoreReader, never on the main connection and never under the store's busy flag. With
    `reader` (a StoreReader the caller leased) the route uses it and takes no lease of its own; without, it opens
    `project_store.read_lease()` for the call. `cancel` (a threading.Event) set before or during the call gives a
    RouteRefusal with code "canceled" and never a value. Refusals win in this order: canceled, timeout, stale.
    It raises only for programmer errors (wrong argument types).
    """
    project, candidates = _resolve_inputs(project, candidates)
    if not isinstance(project, Mapping):
        raise TypeError("project must be a mapping")
    if not isinstance(measure_name_or_expression, str):
        raise TypeError("measure_name_or_expression must be text")
    if project_store is None or not hasattr(project_store, "read_lease"):
        raise TypeError("project_store must be a ProjectStore")
    if reader is not None and not (hasattr(reader, "execute") and hasattr(reader, "interrupt")):
        raise TypeError("reader must be a StoreReader")
    if cancel is not None and not isinstance(cancel, threading.Event):
        raise TypeError("cancel must be a threading.Event")
    if not isinstance(filter_context, tuple):
        raise TypeError("filter_context must be a tuple of predicate texts")
    if group_by is not None and not (isinstance(group_by, tuple) and len(group_by) == 2):
        raise TypeError("group_by must be a (table, column) tuple or None")

    if cancel is not None and cancel.is_set():
        return _canceled_refusal()

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

    def run(on: Any) -> StoreAnswer | RouteRefusal:
        return _run_on_reader(
            on, project_store, name, expression, effective, started, cancel,
            table_name, physical, kind, column_types, tables, store_tables, text, measure_map, filter_context, group_by,
        )

    if reader is not None:
        return run(reader)
    try:
        with project_store.read_lease() as leased:
            return run(leased)
    except StoreBusyError:
        return RouteRefusal(BUSY_MESSAGE, "store busy", CODE_BUSY)
    except StoreError as exc:
        return RouteRefusal(f"{name} cannot be computed: the large table is closed.", str(exc), CODE_CLOSED)


def _run_on_reader(
    reader: Any, project_store: Any, name: str, expression: str, effective: float, started: float,
    cancel: threading.Event | None, table_name: str, physical: str, kind: str, column_types: dict[str, str],
    tables: dict[str, dict[str, str]], store_tables: dict[str, str], text: str, measure_map: dict[str, str],
    filter_context: tuple[str, ...], group_by: tuple[str, str] | None,
) -> StoreAnswer | RouteRefusal:
    """Plan and run one measure on `reader` under the time budget and the cancel event. Nothing escapes as an exception."""

    def is_canceled() -> bool:
        return cancel is not None and cancel.is_set()

    # The budget covers everything that touches the store: the decimal metadata, the guards and the SELECT.
    budget = _Budget(reader.interrupt, effective, cancel)
    budget.start()
    try:
        try:
            column_meta = _decimal_meta(reader, table_name, physical, column_types, text)
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
            result = plan if isinstance(plan, Refusal) else plan.execute(reader)
        except StoreBusyError:
            if is_canceled():
                return _canceled_refusal()
            return RouteRefusal(BUSY_MESSAGE, "store busy", CODE_BUSY)
        except StoreError as exc:
            if is_canceled():
                return _canceled_refusal()
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
            if is_canceled():
                return _canceled_refusal()
            return RouteRefusal(f"{name} cannot be computed on a large table: {exc}", str(exc), CODE_PLAN)
        except Exception as exc:  # nothing may escape into a card refresh, a save or a preview
            if is_canceled():
                return _canceled_refusal()
            return RouteRefusal(
                f"{name} could not be computed ({type(exc).__name__}).", f"{type(exc).__name__}: {exc}", CODE_PLAN
            )
        if is_canceled():
            return _canceled_refusal()
        if isinstance(result, Refusal):
            # An interrupt that lands inside a guard query is swallowed there and comes back as a stale or
            # missing-metadata refusal: when the budget fired, the honest answer is the timeout.
            if budget.fired.is_set():
                return _timeout(name, effective)
            return _refusal(name, result.reason)
    finally:
        budget.cancel()
    if is_canceled():
        return _canceled_refusal()
    elapsed = time.monotonic() - started
    if isinstance(plan, dax_sql.GroupByPlan):
        return StoreAnswer("grouped", None, list(result), elapsed, table_name)
    return StoreAnswer("scalar", result, [], elapsed, table_name)


# ---------------------------------------------------------------------------------------------------------
# Visuals, slicers and filters (Stage C2b)
# ---------------------------------------------------------------------------------------------------------
_DATE_KEY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def label_for_key(key: str, column_type: str) -> str:
    """The text the in-memory path shows for a group key of the store: a date key `m/d/yyyy` reads `yyyy-mm-dd`.

    Every other key is shown as it is (the blank key is the empty text, as for the in-memory path).
    """
    if column_type == "date":
        match = _DATE_KEY.match(key)
        if match is not None:
            month, day, year = (int(part) for part in match.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"
    return key


def _filter_columns(node: Any, found: set[tuple[str, str]]) -> None:
    """The (table, column) pairs a parsed predicate refers to, case-folded."""
    if isinstance(node, tuple):
        if len(node) == 3 and node[0] == "reference" and node[1] != "":
            found.add((str(node[1]).casefold(), str(node[2]).casefold()))
        for part in node:
            _filter_columns(part, found)
    elif isinstance(node, (list, frozenset)):
        for part in node:
            _filter_columns(part, found)


def _predicates_use_column(predicates: Sequence[str], table: str, column: str) -> bool:
    wanted = (table.casefold(), column.casefold())
    for text in predicates:
        found: set[tuple[str, str]] = set()
        try:
            _filter_columns(parse_expression(text), found)
        except Exception:
            continue
        if wanted in found:
            return True
    return False


def route_grouped(
    project: Mapping[str, Any] | RouteSnapshot,
    measure_name_or_expression: str,
    group_by: tuple[str, str],
    *,
    project_store: Any,
    filter_context: tuple[str, ...] = (),
    budget_s: float = DEFAULT_BUDGET_S,
    deadline: float | None = None,
    candidates: Mapping[str, Any] | None = None,
    measures: Mapping[str, str] | None = None,
    max_groups: int | None | str = "default",
    reader: Any = None,
    cancel: threading.Event | None = None,
) -> StoreAnswer | RouteRefusal:
    """One measure grouped by one text, date or yes/no column of the store table (kind "grouped").

    Built on `route_measure` (same shape check, fresh inputs, timer interrupt, busy policy). The rows come back in
    SQL order with the planner's keys; the app applies its own order and drops blank values afterwards. More than
    `max_groups` rows is refused, because a chart that silently shows the first groups is a wrong chart.
    `reader` and `cancel` are those of `route_measure`; `project` may be a `RouteSnapshot`.
    """
    project, candidates = _resolve_inputs(project, candidates)
    if not (isinstance(group_by, tuple) and len(group_by) == 2 and all(isinstance(x, str) for x in group_by)):
        raise TypeError("group_by must be a (table, column) tuple")
    answer = route_measure(
        project, measure_name_or_expression, project_store=project_store, filter_context=filter_context,
        group_by=group_by, budget_s=budget_s, deadline=deadline, candidates=candidates, measures=measures,
        reader=reader, cancel=cancel,
    )
    if isinstance(answer, RouteRefusal):
        return _grouped_refusal(answer, group_by, filter_context)
    cap = MAX_GROUPS if max_groups == "default" else max_groups
    if cap is not None and len(answer.rows) > cap:
        return RouteRefusal(
            f"{group_by[1]} has more than {cap:,} groups; choose a column with fewer groups or filter first.",
            f"{len(answer.rows)} groups", CODE_TOO_MANY,
        )
    return answer


def _grouped_refusal(
    refusal: RouteRefusal, group_by: tuple[str, str], filter_context: tuple[str, ...]
) -> RouteRefusal:
    """The two refusals of a grouped answer that have their own sentence (grouping type, slicer on the grouping column)."""
    reasons = _split_reasons(refusal.reason)
    if _S.REASON_GROUP_BY_TYPE in reasons:
        return RouteRefusal(GROUP_TYPE_MESSAGE, refusal.reason, CODE_PLAN)
    if _W.REASON_SLICER_SAME_COLUMN in reasons and _predicates_use_column(filter_context, group_by[0], group_by[1]):
        return RouteRefusal(
            f"A slicer on {group_by[1]} cannot be used with a visual grouped by the same column on a large table yet.",
            refusal.reason, CODE_PLAN,
        )
    return refusal


_OPERATOR_LABELS = {
    "equals": "is", "not_equals": "is not", "is_any_of": "is any of", "is_none_of": "is none of",
    "relative_date": "relative date", "relative_time": "relative time", "top_n": "Top N", "contains": "contains",
    "does_not_contain": "does not contain", "begins_with": "begins with", "does_not_begin_with": "does not begin with",
    "ends_with": "ends with", "does_not_end_with": "does not end with", "report_month": "month is",
    "greater_than": "is greater than", "greater_than_or_equal": "is greater than or equal to",
    "less_than": "is less than", "less_than_or_equal": "is less than or equal to", "is_blank": "is blank",
    "is_not_blank": "is not blank",
}
_NUMBER_OPERATORS = {
    "equals": "=", "greater_than": ">", "greater_than_or_equal": ">=", "less_than": "<", "less_than_or_equal": "<=",
}
_TOKEN_PREFIX = "__npa_pqv1__:"


def _operator_label(operator: str) -> str:
    return _OPERATOR_LABELS.get(operator, operator.replace("_", " "))


def _filter_refusal(column: str, label: str, sentence: str) -> RouteRefusal:
    return RouteRefusal(
        f"The filter on {column} ({label}) cannot be used on a large table yet: {sentence}.", sentence, CODE_FILTER
    )


def _decode_value(value: Any) -> tuple[str, str]:
    """A filter value as the app stores it: (kind, text). kind is plain, number, blank, other or bad."""
    if not isinstance(value, str):
        return "bad", ""
    if not value.startswith(_TOKEN_PREFIX):
        return "plain", value
    payload = value[len(_TOKEN_PREFIX):]
    if payload in ("null", "empty"):
        return "blank", ""
    try:
        if payload.startswith("text:"):
            encoded = payload[5:]
            text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
            return "plain", text
        if payload.startswith("value:"):
            encoded = payload[6:]
            decoded = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if isinstance(decoded, list) and len(decoded) in (2, 3) and all(isinstance(p, str) for p in decoded):
                kind = decoded[0]
                if kind == "text":
                    return "plain", decoded[1]
                if kind == "number":
                    return "number", decoded[1]
                return "other", kind
    except (ValueError, UnicodeDecodeError):
        pass
    return "bad", ""


def _dax_name(table: str) -> str:
    return "'" + table.replace("'", "''") + "'"


def _dax_column(table: str, column: str) -> str:
    return f"{_dax_name(table)}[{column.replace(']', ']]')}]"


def _dax_text(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _selects_blank_cells(symbol: str, numbers: Sequence[Decimal]) -> bool:
    """True when a blank cell (0 on a large table) passes `cell <symbol> number` for any of the numbers."""
    compare = {"=": lambda a, b: a == b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
               "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}[symbol]
    return any(compare(Decimal(0), number) for number in numbers)


def _clause_predicates(
    table: str, column: str, column_type: str, clause: Mapping[str, Any]
) -> list[str] | RouteRefusal:
    operator = str(clause.get("operator", ""))
    label = _operator_label(operator)
    col = _dax_column(table, column)
    if column_type == "text":
        if operator == "equals":
            kinds_values = [_decode_value(clause.get("value"))]
        elif operator == "is_any_of":
            raw = clause.get("values")
            if not isinstance(raw, list) or not raw:
                return _filter_refusal(column, label, "no value is chosen")
            kinds_values = [_decode_value(item) for item in raw]
        else:
            return _filter_refusal(column, label, "only 'is' and 'is any of' work on a text column")
        texts: list[str] = []
        for kind, text in kinds_values:
            if kind == "blank" or (kind == "plain" and text == ""):
                return _filter_refusal(column, label, "a blank value cannot be chosen")
            if kind != "plain":
                return _filter_refusal(column, label, "a chosen value is not plain text")
            if text not in texts:
                texts.append(text)
        if len(texts) == 1:
            return [f"{col} = {_dax_text(texts[0])}"]
        return [f"{col} IN {{{', '.join(_dax_text(t) for t in texts)}}}"]
    if column_type == "whole_number":
        if operator in _NUMBER_OPERATORS:
            raw_values = [clause.get("value")]
        elif operator == "is_any_of":
            raw_values = clause.get("values") if isinstance(clause.get("values"), list) else []
            if not raw_values:
                return _filter_refusal(column, label, "no value is chosen")
        else:
            return _filter_refusal(column, label, "this kind of filter does not work on a number column")
        numbers: list[Decimal] = []
        for item in raw_values:
            kind, text = _decode_value(item)
            if kind not in ("plain", "number"):
                return _filter_refusal(column, label, "a chosen value is not a number")
            try:
                number = Decimal(text.strip())
            except Exception:
                return _filter_refusal(column, label, "a chosen value is not a number")
            if not number.is_finite():
                return _filter_refusal(column, label, "a chosen value is not a number")
            numbers.append(number)
        symbol = _NUMBER_OPERATORS.get(operator, "=")
        if _selects_blank_cells(symbol, numbers):
            # The app never selects a blank cell with a number filter; a large table counts a blank cell as 0.
            return _filter_refusal(
                column, label, "it would also select blank cells, which a large table counts as 0"
            )
        literals = [format(n, "f") if n != n.to_integral_value() else str(int(n)) for n in numbers]
        return [" || ".join(f"{col} = {text}" for text in literals) if symbol == "=" else f"{col} {symbol} {literals[0]}"]
    return _filter_refusal(column, label, f"a {_plain(column_type)} column cannot be filtered yet")


def route_filter_context(
    project: Mapping[str, Any] | RouteSnapshot,
    filters: Sequence[Mapping[str, Any]],
    *,
    candidates: Mapping[str, Any] | None = None,
) -> tuple[str, ...] | RouteRefusal:
    """The predicate strings `plan_*` takes for the app's slicer, page, visual and report filters, or a refusal.

    Each filter is `{"table_id", "column", "clauses": [{"operator", "value" | "values"}], "logic"}` (the saved
    shape). Allowed: a text column "is" / "is any of"; a whole-number column "is", "is any of" and the four
    comparisons, only when no blank cell would be selected; one or two conditions joined by AND. Everything else
    (is not, is none of, contains, begins/ends with, blank checks, relative date or time, Top N, month, OR,
    decimal, date and yes/no columns, another table) is refused with a sentence that names the field and the
    filter type. Every predicate then passes `classify_filter_context`. `project` may be a `RouteSnapshot`.
    """
    project, candidates = _resolve_inputs(project, candidates)
    if not isinstance(project, Mapping):
        raise TypeError("project must be a mapping")
    shape = store_shape(project, candidates)
    if not shape.ok:
        return RouteRefusal(shape.reason, shape.reason, CODE_SHAPE)
    info = _store_info_by_source(project, candidates)
    model_table = next(t for t in _model(project)["tables"] if isinstance(t, Mapping))
    table_name = str(model_table.get("name", ""))
    own_ids = {str(model_table.get(key)) for key in ("id", "source_id") if model_table.get(key)}
    column_types = {str(c): str(t) for c, t in dict(model_table.get("column_types", {})).items()}
    kind = info[str(model_table.get("source_id") or model_table.get("id") or "")][1]
    out: list[str] = []
    for item in filters:
        column = str(item.get("column", ""))
        if str(item.get("table_id", "")) not in own_ids:
            return _filter_refusal(column, "another table", "it belongs to another table, which large tables cannot combine yet")
        actual = next((c for c in column_types if c.casefold() == column.casefold()), None)
        if actual is None:
            return RouteRefusal(
                f"Column '{column}' was not found in table {table_name}.", f"unknown column '{column}'", CODE_FILTER
            )
        clauses = item.get("clauses")
        if not isinstance(clauses, list) or not clauses or not all(isinstance(c, Mapping) for c in clauses):
            return _filter_refusal(column, "filter", "the filter has no condition")
        label = " and ".join(_operator_label(str(c.get("operator", ""))) for c in clauses)
        if len(clauses) > 1 and str(item.get("logic", "and")) != "and":
            return _filter_refusal(column, label, "two conditions joined by OR are not available")
        predicates: list[str] = []
        for clause in clauses:
            built = _clause_predicates(table_name, actual, column_types[actual], clause)
            if isinstance(built, RouteRefusal):
                return built
            predicates.extend(built)
        decision = dax_whitelist.classify_filter_context(
            predicates, home_table=table_name, tables={table_name: column_types}, source_kind=kind,
        )
        if not decision.allowed:
            reason = "; ".join(decision.reasons)
            return RouteRefusal(
                message_for_reason(f"The filter on {column} ({label})", reason), reason, CODE_WHITELIST
            )
        out.extend(predicates)
    return tuple(out)


def route_distinct_values(
    project: Mapping[str, Any] | RouteSnapshot,
    table: str,
    column: str,
    *,
    project_store: Any,
    search: str = "",
    limit: int = DISTINCT_LIMIT,
    filter_context: tuple[str, ...] = (),
    budget_s: float = DEFAULT_BUDGET_S,
    deadline: float | None = None,
    candidates: Mapping[str, Any] | None = None,
    reader: Any = None,
    cancel: threading.Event | None = None,
) -> list[str] | RouteRefusal:
    """The different values of a text, date or yes/no column, each once with its first spelling, in first-seen order.

    This is the group list of `COUNTROWS(table)` grouped by the column, so the text fold, the blank key (the empty
    text, listed where it first appears) and the date text are exactly those of a visual axis, and a filter
    context keeps only the values that still have rows. `search` is matched in Python (case-insensitive, part of the
    text); it never reaches the SQL. More than `limit` matching values is refused.
    `reader` and `cancel` are those of `route_measure`; `project` may be a `RouteSnapshot`.
    """
    project, candidates = _resolve_inputs(project, candidates)
    if not isinstance(search, str) or not isinstance(table, str) or not isinstance(column, str):
        raise TypeError("table, column and search must be text")
    answer = route_grouped(
        project, f"COUNTROWS({_dax_name(table)})", (table, column), project_store=project_store,
        filter_context=filter_context, budget_s=budget_s, deadline=deadline, candidates=candidates, max_groups=None,
        reader=reader, cancel=cancel,
    )
    if isinstance(answer, RouteRefusal):
        if answer.message == GROUP_TYPE_MESSAGE:
            return RouteRefusal(
                "Large tables can only list the values of text, date or yes/no columns for now.", answer.reason, CODE_PLAN
            )
        return answer
    model_table = next(t for t in _model(project)["tables"] if isinstance(t, Mapping))
    column_types = {str(c).casefold(): str(t) for c, t in dict(model_table.get("column_types", {})).items()}
    column_type = column_types.get(column.casefold(), "text")
    labels = [label_for_key(key, column_type) for key, _ in answer.rows]
    needle = search.strip().casefold()
    if needle:
        labels = [label for label in labels if needle in label.casefold()]
    if len(labels) > limit:
        return RouteRefusal(
            f"{column} has more than {limit:,} different values; choose a column with fewer values.",
            f"{len(labels)} values", CODE_TOO_MANY,
        )
    return labels


def refresh_deadline(seconds: float = DEFAULT_REFRESH_BUDGET_S) -> float:
    """The shared absolute deadline (time.monotonic) of one card refresh, or of the visuals of one page (2 s)."""
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
