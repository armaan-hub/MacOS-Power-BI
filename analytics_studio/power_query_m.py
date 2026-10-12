"""Safe, bounded Power Query M transformations for the local table engine.

This module accepts a linear ``let ... in`` query using a deliberately small
set of ``Table.*`` operations. It translates supported calls to the same
validated steps used by the visual Transform Data editor; user text is never
executed as Python or sent to an M runtime.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, DecimalException
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.file_import import MAX_DATA_ROWS, ImportCandidate
from analytics_studio.dialog_theme import apply_light_dialog_theme
from analytics_studio.import_preview_dialog import ImportPreviewTableModel
from analytics_studio.power_query_expression import (
    ExpressionError,
    compile_expression,
    expression_value_to_text,
)
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    canonical_column_type,
    column_types_after_steps,
    validate_steps,
)
from analytics_studio.query_engine import QueryError, append_candidates


MAX_M_SCRIPT_LENGTH = 32_000
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\((.*)\)\Z", re.DOTALL)
_M_LOCALE_TYPES = {"whole_number", "decimal_number", "date", "datetime", "time"}


class PowerQueryMScriptError(ValueError):
    """Invalid or unsupported local Power Query M subset script."""


def _m_column_types_after_steps(
    steps: list[dict[str, Any]],
    initial_column_types: dict[str, str] | None,
) -> dict[str, str]:
    initial_types = dict(initial_column_types or {})
    return column_types_after_steps(
        list(initial_types), steps, initial_types=initial_types
    )


def parse_m_script(
    script: str,
    query_name: str,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Translate a linear supported M query into replayable local steps."""
    return parse_m_query_script(
        script,
        query_name,
        parameter_names=parameter_names,
        query_functions=query_functions,
        initial_column_types=initial_column_types,
    )[1]


def parse_m_query_script(
    script: str,
    query_name: str,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> tuple[list[str] | None, list[dict[str, Any]]]:
    """Parse a local query and return optional Append source names plus its steps.

    Ordinary table queries keep their project-managed source and return
    ``None`` for source names. An Append query may instead begin with the
    bounded ``Table.Combine({#"First", #"Second"})`` source form.
    """
    if not isinstance(script, str) or not script.strip():
        raise PowerQueryMScriptError("Enter a Power Query M script.")
    if len(script) > MAX_M_SCRIPT_LENGTH:
        raise PowerQueryMScriptError(
            f"A local M script may contain at most {MAX_M_SCRIPT_LENGTH:,} characters."
        )
    clean_script = _strip_line_comments(script).strip()
    if not clean_script[:3].casefold() == "let" or (
        len(clean_script) > 3 and clean_script[3].isalnum()
    ):
        raise PowerQueryMScriptError("A local M query must start with let and finish with in.")
    body = clean_script[3:].strip()
    in_position = _find_last_keyword(body, "in")
    if in_position < 0:
        raise PowerQueryMScriptError("Add an in clause that returns the final step.")
    binding_text = body[:in_position].strip().rstrip(",").strip()
    output_name = _parse_name(body[in_position + 2:].strip())
    bindings = _split_let_bindings(binding_text)
    if not bindings or any(not item.strip() for item in bindings):
        raise PowerQueryMScriptError("The let block contains an empty step.")

    parsed_steps: list[dict[str, Any]] = []
    known_parameters = set(parameter_names or set())
    from analytics_studio.query_functions import (
        QueryFunctionError,
        query_function_to_m,
        validate_query_functions,
    )
    try:
        known_functions = validate_query_functions(query_functions or [])
    except QueryFunctionError as exc:
        raise PowerQueryMScriptError(f"Power Query function registry: {exc}") from exc
    functions_by_name = {item["name"]: item for item in known_functions}
    function_names = set(functions_by_name)
    declared_functions: set[str] = set()
    table_step_seen = False
    seen_names: set[str] = set()
    previous_name = ""
    source_query_names: list[str] | None = None
    for index, binding in enumerate(bindings):
        equals_at = _find_top_level_character(binding, "=")
        if equals_at < 0:
            raise PowerQueryMScriptError(f"Step {index + 1} must use Name = expression.")
        name = _parse_name(binding[:equals_at].strip())
        rhs = binding[equals_at + 1:].strip()
        key = name.casefold()
        if key in seen_names:
            raise PowerQueryMScriptError(f"Step name {name!r} is defined more than once.")
        seen_names.add(key)
        if index == 0:
            if name.casefold() != "source":
                raise PowerQueryMScriptError("The first let binding must be named Source.")
            source_call = _CALL.fullmatch(rhs)
            if source_call is not None and source_call.group(1) == "Table.Combine":
                source_query_names = _parse_table_combine_source(rhs)
            else:
                source_name = _parse_query_reference(rhs)
                if source_name.casefold() != query_name.strip().casefold():
                    raise PowerQueryMScriptError(
                        f"Source must reference the current query {query_name!r}."
                    )
            previous_name = name
            continue
        if name in functions_by_name:
            if table_step_seen:
                raise PowerQueryMScriptError(
                    "Declare Power Query functions after Source and before table steps."
                )
            if rhs.strip() != query_function_to_m(functions_by_name[name]):
                raise PowerQueryMScriptError(
                    f"The M definition for function {name!r} does not match the staged project definition."
                )
            declared_functions.add(name)
            continue
        if "=>" in rhs:
            raise PowerQueryMScriptError(
                f"Function binding {name!r} is not present in the staged project registry."
            )
        table_step_seen = True
        input_types = _m_column_types_after_steps(
            parsed_steps, initial_column_types
        )
        parsed_steps.extend(
            _parse_table_call(
                rhs,
                previous_name,
                input_types,
                parameter_names=known_parameters,
                query_functions=known_functions,
            )
        )
        previous_name = name

    if output_name.casefold() != previous_name.casefold():
        raise PowerQueryMScriptError("The in clause must return the last step in this linear query.")
    try:
        validated_steps = validate_steps(parsed_steps)
        _validate_m_text_inputs(
            validated_steps,
            m_script_custom_types=True,
            parameter_names=known_parameters,
            query_functions=known_functions,
            initial_column_types=initial_column_types,
        )
        from analytics_studio.query_functions import function_references
        referenced = function_references(validated_steps, known_functions)
        missing_bindings = referenced - declared_functions
        if missing_bindings:
            raise PowerQueryMScriptError(
                "Declare each referenced Power Query function after Source: "
                + ", ".join(sorted(missing_bindings))
                + "."
            )
        unused_bindings = declared_functions - referenced
        if unused_bindings:
            raise PowerQueryMScriptError(
                "Remove unused Power Query function binding(s): "
                + ", ".join(sorted(unused_bindings))
                + "."
            )
        for step in validated_steps:
            if step["op"] == "add_custom_column":
                step["expression"] = _unwrap_text_from(step["expression"])
        return source_query_names, validated_steps
    except TransformationError as exc:
        raise PowerQueryMScriptError(str(exc)) from exc


def steps_to_m_script(
    steps: list[dict[str, Any]],
    query_name: str,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    source_query_names: list[str] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> str:
    """Render supported saved steps as editable linear M code.

    ``source_query_names`` emits a bounded two-query ``Table.Combine`` source
    for saved Append queries. Other query source connectors remain project
    managed and are represented by the current query name.
    """
    validated = validate_steps(steps)
    from analytics_studio.query_functions import (
        QueryFunctionError,
        function_references,
        query_function_to_m,
        validate_query_functions,
    )
    try:
        known_functions = validate_query_functions(query_functions or [])
    except QueryFunctionError as exc:
        raise PowerQueryMScriptError(f"Power Query function registry: {exc}") from exc
    _validate_m_text_inputs(
        validated,
        parameter_names=parameter_names,
        query_functions=known_functions,
        initial_column_types=initial_column_types,
    )
    used_functions = function_references(validated, known_functions)
    functions_by_name = {item["name"]: item for item in known_functions}
    missing_functions = used_functions - functions_by_name.keys()
    if missing_functions:
        raise PowerQueryMScriptError(
            "The query calls missing Power Query function(s): "
            + ", ".join(sorted(missing_functions))
            + "."
        )
    if source_query_names is None:
        source = _m_quoted_name(query_name)
    else:
        source_names = _validate_append_source_names(source_query_names)
        source = "Table.Combine({" + ", ".join(
            _m_quoted_name(name) for name in source_names
        ) + "})"
    bindings = [f"    Source = {source}"]
    for function in known_functions:
        if function["name"] in used_functions:
            bindings.append(f"    {function['name']} = {query_function_to_m(function)}")
    previous = "Source"
    for index, step in enumerate(validated, 1):
        step_name = f"Step {index}"
        binding = _m_quoted_name(step_name)
        input_types = _m_column_types_after_steps(
            validated[:index - 1], initial_column_types
        )
        call = _step_to_m_call(previous, step, input_types)
        bindings.append(f"    {binding} = {call}")
        previous = binding
    return "let\n" + ",\n".join(bindings) + f"\nin\n    {previous}"


def step_expression_to_m(
    steps: list[dict[str, Any]],
    query_name: str,
    index: int,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> str:
    """Return one generated table expression without assuming it fits on one line."""
    script = steps_to_m_script(
        steps[: index + 1], query_name,
        parameter_names=parameter_names,
        query_functions=query_functions,
        initial_column_types=initial_column_types,
    )
    bindings, _output_name = _generated_bindings(script)
    from analytics_studio.query_functions import function_references
    used_function_count = len(
        function_references(steps[:index + 1], query_functions or [])
    )
    binding_index = index + 1 + used_function_count
    if not 0 <= binding_index < len(bindings):
        raise PowerQueryMScriptError("The selected step has no generated M binding.")
    binding = bindings[binding_index]
    equals_at = _find_top_level_character(binding, "=")
    if equals_at < 0:
        raise PowerQueryMScriptError("The selected M binding has no expression.")
    return binding[equals_at + 1:].strip()


def replace_step_expression_in_m(
    steps: list[dict[str, Any]],
    query_name: str,
    index: int,
    expression: str,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> str:
    """Render a generated query with one selected step expression replaced."""
    script = steps_to_m_script(
        steps[: index + 1], query_name,
        parameter_names=parameter_names,
        query_functions=query_functions,
        initial_column_types=initial_column_types,
    )
    bindings, output_name = _generated_bindings(script)
    from analytics_studio.query_functions import function_references
    used_function_count = len(
        function_references(steps[:index + 1], query_functions or [])
    )
    binding_index = index + 1 + used_function_count
    if not 0 <= binding_index < len(bindings):
        raise PowerQueryMScriptError("The selected step has no generated M binding.")
    binding = bindings[binding_index]
    equals_at = _find_top_level_character(binding, "=")
    if equals_at < 0:
        raise PowerQueryMScriptError("The selected M binding has no expression.")
    name = binding[:equals_at].strip()
    bindings[binding_index] = f"{name} = {expression.strip()}"
    return (
        "let\n"
        + ",\n".join(f"    {item.strip()}" for item in bindings)
        + f"\nin\n    {output_name}"
    )


def _generated_bindings(script: str) -> tuple[list[str], str]:
    clean_script = script.strip()
    body = clean_script[3:].strip()
    in_position = _find_last_keyword(body, "in")
    if in_position < 0:
        raise PowerQueryMScriptError("The generated M query has no in clause.")
    binding_text = body[:in_position].strip().rstrip(",").strip()
    output_reference = body[in_position + 2:].strip()
    return _split_let_bindings(binding_text), output_reference


def m_compatibility_issues(
    steps: list[dict[str, Any]],
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Report every saved step that cannot round-trip through this local M subset.

    The emitter and parser are the compatibility contract. The per-step probes
    collect all blockers instead of stopping at the first unsupported operation;
    a final full-sequence round trip catches interactions between supported steps.
    """
    validated = validate_steps(steps)
    issues: list[dict[str, Any]] = []
    query_name = "__PowerQueryMCompatibilityProbe__"

    for index, step in enumerate(validated, 1):
        try:
            # Conditional comparisons need the type conversions that precede
            # them in order to retain the M value type in the generated script.
            if step["op"] == "conditional_column" and not issues:
                probe_steps = validated[:index]
                expected_steps = probe_steps
            elif step["op"] == "conditional_column":
                continue
            else:
                probe_steps = [step]
                expected_steps = [step]
            probe_initial_types = (
                initial_column_types
                if len(probe_steps) > 1
                else _m_column_types_after_steps(
                    validated[:index - 1], initial_column_types
                )
            )
            script = steps_to_m_script(
                probe_steps, query_name,
                parameter_names=parameter_names,
                query_functions=query_functions,
                initial_column_types=probe_initial_types,
            )
            parsed = parse_m_script(
                script, query_name,
                parameter_names=parameter_names,
                query_functions=query_functions,
                initial_column_types=probe_initial_types,
            )
            if _canonical_m_steps(parsed) != _canonical_m_steps(expected_steps):
                raise PowerQueryMScriptError(
                    "The editor would change this step while translating it to M."
                )
        except (PowerQueryMScriptError, TransformationError) as exc:
            issues.append({
                "step": index,
                "operation": step["op"],
                "message": str(exc),
            })

    if not issues and validated:
        try:
            script = steps_to_m_script(
                validated, query_name,
                parameter_names=parameter_names,
                query_functions=query_functions,
                initial_column_types=initial_column_types,
            )
            parsed = parse_m_script(
                script, query_name,
                parameter_names=parameter_names,
                query_functions=query_functions,
                initial_column_types=initial_column_types,
            )
            if _canonical_m_steps(parsed) != _canonical_m_steps(validated):
                raise PowerQueryMScriptError(
                    "The complete sequence would change while translating it to M."
                )
        except (PowerQueryMScriptError, TransformationError) as exc:
            issues.append({
                "step": len(validated),
                "operation": validated[-1]["op"],
                "message": str(exc),
            })
    return issues


def _canonical_m_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize known local aliases that have equivalent M representations."""
    canonical: list[dict[str, Any]] = []
    for source in validate_steps(steps):
        step = dict(source)
        if step["op"] == "sort_rows":
            direction = {"asc": "asc", "desc": "desc"}[step["direction"]]
            step = {
                "op": "sort_rows_by_columns",
                "sorts": [{"column": step["column"], "direction": direction}],
            }
        elif step["op"] == "convert_type":
            step["type"] = canonical_column_type(step["type"])
        elif step["op"] == "add_custom_column":
            step["expression"] = _unwrap_text_from(step["expression"])
        elif step["op"] == "filter_rows_advanced" and len(step["clauses"]) == 1:
            clause = step["clauses"][0]
            simple_filter = {
                "op": "filter_rows",
                "column": clause["column"],
                "operator": clause["operator"],
            }
            if "parameter" in clause:
                simple_filter["parameter"] = clause["parameter"]
            else:
                simple_filter["value"] = clause["value"]
            step = simple_filter
        canonical.append(step)
    return canonical


def m_script_matches_steps(
    script: str,
    query_name: str,
    steps: list[dict[str, Any]],
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    source_query_names: list[str] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> bool:
    """Return whether saved M text safely represents the current local steps."""
    try:
        parsed_sources, parsed = parse_m_query_script(
            script, query_name,
            parameter_names=parameter_names,
            query_functions=query_functions,
            initial_column_types=initial_column_types,
        )
        if source_query_names is None:
            sources_match = parsed_sources is None
        else:
            try:
                expected_sources = _validate_append_source_names(source_query_names)
            except PowerQueryMScriptError:
                return False
            sources_match = (
                parsed_sources is not None
                and [name.casefold() for name in parsed_sources]
                == [name.casefold() for name in expected_sources]
            )
        return sources_match and _canonical_m_steps(parsed) == _canonical_m_steps(steps)
    except (PowerQueryMScriptError, TransformationError, TypeError, ValueError):
        return False


def rewrite_m_append_source_names(
    script: str,
    query_name: str,
    steps: list[dict[str, Any]],
    old_source_names: list[str],
    new_source_names: list[str],
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> str | None:
    """Rebind a valid authored Append query while preserving its other M text."""
    try:
        old_names = _validate_append_source_names(old_source_names)
        new_names = _validate_append_source_names(new_source_names)
        parsed_names, parsed_steps = parse_m_query_script(
            script,
            query_name,
            parameter_names=parameter_names,
            query_functions=query_functions,
            initial_column_types=initial_column_types,
        )
        if (
            parsed_names is None
            or [name.casefold() for name in parsed_names]
            != [name.casefold() for name in old_names]
            or _canonical_m_steps(parsed_steps) != _canonical_m_steps(steps)
        ):
            return None
        if [name.casefold() for name in old_names] == [
            name.casefold() for name in new_names
        ]:
            return script

        masked = _mask_line_comments(script)
        let_position = _find_keyword(masked, "let")
        if let_position < 0:
            return None
        bindings_start = let_position + len("let")
        in_position = _find_last_keyword(masked[bindings_start:], "in")
        if in_position < 0:
            return None
        bindings_end = bindings_start + in_position
        bindings = masked[bindings_start:bindings_end].rstrip().rstrip(",")
        first_comma = _find_top_level_character(bindings, ",")
        first_binding = bindings[:first_comma] if first_comma >= 0 else bindings
        equals_position = _find_top_level_character(first_binding, "=")
        if equals_position < 0:
            return None
        rhs_position = bindings_start + equals_position + 1
        first_binding_end = bindings_start + len(first_binding)
        while rhs_position < first_binding_end and masked[rhs_position].isspace():
            rhs_position += 1
        while first_binding_end > rhs_position and masked[first_binding_end - 1].isspace():
            first_binding_end -= 1
        source_expression = script[rhs_position:first_binding_end]
        rewritten_source = _rewrite_table_combine_source_names(
            source_expression, old_names, new_names
        )
        if rewritten_source is None:
            return None
        return script[:rhs_position] + rewritten_source + script[first_binding_end:]
    except (PowerQueryMScriptError, TransformationError, TypeError, ValueError):
        return None


def _rewrite_table_combine_source_names(
    expression: str, old_names: list[str], new_names: list[str]
) -> str | None:
    """Replace only Append query tokens, keeping authored comments and spacing."""
    masked = _mask_line_comments(expression)
    try:
        parsed_names = _parse_table_combine_source(masked)
    except PowerQueryMScriptError:
        return None
    if [name.casefold() for name in parsed_names] != [
        name.casefold() for name in old_names
    ]:
        return None
    references = list(re.finditer(r'#"(?:[^"]|"")*"', masked))
    if len(references) != 2:
        return None
    try:
        reference_names = [
            _parse_query_reference(match.group(0)) for match in references
        ]
    except PowerQueryMScriptError:
        return None
    if [name.casefold() for name in reference_names] != [
        name.casefold() for name in old_names
    ]:
        return None

    rewritten = expression
    for match, new_name in reversed(list(zip(references, new_names))):
        rewritten = (
            rewritten[:match.start()]
            + _m_quoted_name(new_name)
            + rewritten[match.end():]
        )
    return rewritten


def _unwrap_text_from(expression: str) -> str:
    match = _CALL.fullmatch(expression.strip())
    if match is not None and match.group(1) == "Text.From":
        arguments = _split_top_level(match.group(2), ",")
        if len(arguments) == 1:
            return arguments[0].strip()
    return expression


def _keep_duplicates_m_expression(previous: str, columns: list[str]) -> str:
    """Build a canonical, order-preserving M expression for Keep Duplicates."""
    row_key_values = ", ".join(
        f"Record.Field(_, {_m_string(column)})" for column in columns
    )
    reference = previous
    return "\n".join([
        "let",
        f"    ExistingColumns = Table.ColumnNames({reference}),",
        "    OrderColumn = List.First(List.Select(",
        '        List.Transform({0..List.Count(ExistingColumns)}, each "__LocalKeepDuplicatesOrder" & Text.From(_)),',
        "        each not List.Contains(ExistingColumns, _))),",
        "    GroupKeyColumn = List.First(List.Select(",
        '        List.Transform({0..List.Count(ExistingColumns)}, each "__LocalKeepDuplicatesKey" & Text.From(_)),',
        "        each not List.Contains(ExistingColumns, _))),",
        "    GroupRowsColumn = List.First(List.Select(",
        '        List.Transform({0..List.Count(ExistingColumns)}, each "__LocalKeepDuplicatesRows" & Text.From(_)),',
        "        each not List.Contains(ExistingColumns, _))),",
        f"    Indexed = Table.AddIndexColumn({reference}, OrderColumn, 0, 1, Int64.Type),",
        "    Keyed = Table.AddColumn(Indexed, GroupKeyColumn, each Text.Combine(",
        f"        List.Transform({{{row_key_values}}}, each if _ = null then \"0:\" else Text.From(Text.Length(_), \"en-US\") & \":\" & _), \"\"), type text),",
        f"    Grouped = Table.Group(Keyed, {{GroupKeyColumn}}, {{{{GroupRowsColumn, each _, type table}}}}, GroupKind.Global, Comparer.Ordinal),",
        "    DuplicateGroups = Table.SelectRows(Grouped, each Table.RowCount(Record.Field(_, GroupRowsColumn)) > 1),",
        "    DuplicateRows = Table.Combine({Table.FirstN(Keyed, 0)} & Table.Column(DuplicateGroups, GroupRowsColumn)),",
        "    Ordered = Table.Sort(DuplicateRows, {{OrderColumn, Order.Ascending}}),",
        "    Result = Table.RemoveColumns(Ordered, {OrderColumn, GroupKeyColumn})",
        "in",
        "    Result",
    ])


def _parse_keep_duplicates_m_expression(
    expression: str, previous_name: str
) -> dict[str, Any]:
    """Accept only the exact generated M shape used by Keep Duplicates."""
    text = expression.strip()
    if not text[:3].casefold() == "let" or (
        len(text) > 3 and text[3].isalnum()
    ):
        raise PowerQueryMScriptError(
            "Only the canonical local Keep Duplicates M expression is supported."
        )
    body = text[3:].strip()
    in_position = _find_keyword(body, "in")
    if in_position < 0:
        raise PowerQueryMScriptError(
            "The Keep Duplicates M expression needs a final in clause."
        )
    binding_text = body[:in_position].strip().rstrip(",").strip()
    output_name = _parse_name(body[in_position + 2:].strip())
    bindings: dict[str, str] = {}
    for binding in _split_let_bindings(binding_text):
        equals_at = _find_top_level_character(binding, "=")
        if equals_at < 0:
            raise PowerQueryMScriptError(
                "Only the canonical local Keep Duplicates M expression is supported."
            )
        name = _parse_name(binding[:equals_at].strip())
        if name in bindings:
            raise PowerQueryMScriptError("The Keep Duplicates M expression repeats a step name.")
        bindings[name] = binding[equals_at + 1:].strip()
    expected_names = [
        "ExistingColumns", "OrderColumn", "GroupKeyColumn", "GroupRowsColumn",
        "Indexed", "Keyed", "Grouped", "DuplicateGroups", "DuplicateRows",
        "Ordered", "Result",
    ]
    if list(bindings) != expected_names or output_name != "Result":
        raise PowerQueryMScriptError(
            "Only the canonical local Keep Duplicates M expression is supported."
        )

    keyed_match = _CALL.fullmatch(bindings["Keyed"])
    if keyed_match is None or keyed_match.group(1) != "Table.AddColumn":
        raise PowerQueryMScriptError(
            "The Keep Duplicates M expression must use the generated composite key."
        )
    keyed_args = _split_top_level(keyed_match.group(2), ",")
    if len(keyed_args) != 4 or keyed_args[0].strip() != "Indexed":
        raise PowerQueryMScriptError(
            "The Keep Duplicates M expression must use the generated composite key."
        )
    try:
        if _parse_name(keyed_args[1]) != "GroupKeyColumn" or keyed_args[3].strip() != "type text":
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must use a text composite key."
            )
        key_expression = _parse_each_expression(keyed_args[2])
        combine_match = _CALL.fullmatch(key_expression)
        if combine_match is None or combine_match.group(1) != "Text.Combine":
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must encode its composite key."
            )
        combine_args = _split_top_level(combine_match.group(2), ",")
        if len(combine_args) != 2 or _parse_string(combine_args[1]) != "":
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must encode its composite key."
            )
        transform_match = _CALL.fullmatch(combine_args[0].strip())
        if transform_match is None or transform_match.group(1) != "List.Transform":
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must encode its composite key."
            )
        transform_args = _split_top_level(transform_match.group(2), ",")
        if len(transform_args) != 2:
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must encode its composite key."
            )
        columns = []
        for value in _parse_braced_items(transform_args[0]):
            field_match = _CALL.fullmatch(value)
            if field_match is None or field_match.group(1) != "Record.Field":
                raise PowerQueryMScriptError(
                    "The Keep Duplicates M expression must reference literal key columns."
                )
            field_args = _split_top_level(field_match.group(2), ",")
            if len(field_args) != 2 or field_args[0].strip() != "_":
                raise PowerQueryMScriptError(
                    "The Keep Duplicates M expression must reference literal key columns."
                )
            columns.append(_parse_string(field_args[1]))
        if not columns:
            raise PowerQueryMScriptError("Keep Duplicates needs at least one key column.")
        key_value_expression = (
            'each if _ = null then "0:" else '
            'Text.From(Text.Length(_), "en-US") & ":" & _'
        )
        if _compact_m_whitespace(transform_args[1]) != _compact_m_whitespace(
            key_value_expression
        ):
            raise PowerQueryMScriptError(
                "The Keep Duplicates M expression must normalize null text keys safely."
            )
    except PowerQueryMScriptError:
        raise
    except (IndexError, TypeError, ValueError) as exc:
        raise PowerQueryMScriptError(
            "The Keep Duplicates M expression must use literal text key columns."
        ) from exc

    expected = _keep_duplicates_m_expression(_m_reference(previous_name), columns)
    if _compact_m_whitespace(text) != _compact_m_whitespace(expected):
        raise PowerQueryMScriptError(
            "The Keep Duplicates M expression differs from the supported canonical form."
        )
    return {"op": "keep_duplicates", "columns": columns}


def _parse_pivot_aggregation(value: str) -> str | None:
    """Parse the named Pivot aggregates and the one supported nonblank lambda."""
    named = {
        "List.Sum": "sum",
        "List.Average": "average",
        "List.Median": "median",
        "List.Min": "min",
        "List.Max": "max",
        "List.Count": "count_all",
    }
    text = value.strip()
    if text in named:
        return named[text]
    # M identifiers are case-sensitive. The shared row-expression helper is
    # intentionally more permissive for other established local constructs.
    if re.match(r"each\s+", text, re.DOTALL) is None:
        return None

    try:
        expression = _parse_each_expression(text)
        count_call = _CALL.fullmatch(expression)
        if count_call is None or count_call.group(1) != "List.Count":
            return None
        count_args = _split_top_level(count_call.group(2), ",")
        if len(count_args) != 1:
            return None
        remove_call = _CALL.fullmatch(count_args[0].strip())
        if remove_call is None or remove_call.group(1) != "List.RemoveItems":
            return None
        remove_args = _split_top_level(remove_call.group(2), ",")
        if len(remove_args) != 2 or remove_args[0].strip() != "_":
            return None
        removed_values = _parse_braced_items(remove_args[1])
        if (
            len(removed_values) != 2
            or removed_values[0].strip() != "null"
            or _parse_string(removed_values[1]) != ""
        ):
            return None
        return "count_non_blank"
    except PowerQueryMScriptError:
        return None


def _parse_table_call(
    rhs: str,
    previous_name: str,
    input_column_types: dict[str, str] | None = None,
    *,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if rhs.strip().casefold().startswith("let"):
        return [_parse_keep_duplicates_m_expression(rhs, previous_name)]
    match = _CALL.fullmatch(rhs.strip())
    if match is None:
        raise PowerQueryMScriptError("Each applied step must call a supported Table.* function.")
    function = match.group(1)
    arguments = _split_top_level(match.group(2), ",")
    if function == "Table.ExpandListColumn":
        _expect_count(function, arguments, 2)
        column = _parse_string(arguments[1])
        return [_parse_split_to_rows(arguments[0], previous_name, column)]
    if not arguments or _parse_name(arguments[0].strip()).casefold() != previous_name.casefold():
        raise PowerQueryMScriptError("Each Table.* step must use the preceding step as its input.")
    args = [item.strip() for item in arguments[1:]]

    if function == "Table.Transpose":
        _expect_count(function, args, 0)
        return [{"op": "transpose_table"}]
    if function == "Table.RemoveColumns":
        _expect_count(function, args, 1)
        return [{"op": "remove_column", "column": column} for column in _parse_string_list(args[0])]
    if function == "Table.SelectColumns":
        _expect_count(function, args, 1)
        return [{"op": "keep_columns", "columns": _parse_string_list(args[0])}]
    if function == "Table.RenameColumns":
        _expect_count(function, args, 1)
        pairs = _parse_rename_pairs(args[0])
        return [{"op": "rename_column", "column": old, "new_name": new} for old, new in pairs]
    if function == "Table.SplitColumn":
        return [_parse_split_column(args, previous_name)]
    if function == "Table.CombineColumns":
        _expect_count(function, args, 3)
        combiner_match = _CALL.fullmatch(args[1])
        if combiner_match is None or combiner_match.group(1) != "Combiner.CombineTextByDelimiter":
            raise PowerQueryMScriptError(
                "Table.CombineColumns supports Combiner.CombineTextByDelimiter only."
            )
        combiner_args = _split_top_level(combiner_match.group(2), ",")
        if len(combiner_args) != 2 or combiner_args[1].strip() != "QuoteStyle.None":
            raise PowerQueryMScriptError(
                "Merged text must use QuoteStyle.None to match the local text engine."
            )
        return [{
            "op": "merge_columns",
            "columns": _parse_string_list(args[0]),
            "separator": _parse_string(combiner_args[0]),
            "new_name": _parse_string(args[2]),
        }]
    if function == "Table.SelectRows":
        _expect_count(function, args, 1)
        predicate = _parse_each_expression(args[0])
        if _compact_m_whitespace(predicate) == (
            'notList.IsEmpty(List.RemoveMatchingItems(Record.FieldValues(_),{null,""}))'
        ):
            return [{"op": "remove_blank_rows"}]
        return _parse_row_filter(predicate, parameter_names=parameter_names)
    if function == "Table.AddColumn":
        if len(args) not in {2, 3}:
            raise PowerQueryMScriptError("Table.AddColumn accepts a name, each expression, and optional type.")
        name = _parse_string(args[0])
        function_names = {item["name"] for item in (query_functions or [])}
        expression = _parse_each(
            args[1],
            parameter_names=parameter_names,
            function_names=function_names,
        )
        tree = compile_expression(
            expression,
            allowed_symbols=parameter_names,
            function_names=function_names,
        )
        output_type = "text"
        if len(args) == 3:
            declared_type = _parse_type(args[2])
            if declared_type == "time":
                raise PowerQueryMScriptError(
                    "Custom columns do not support Time output annotations in the local type model."
                )
            output_type = declared_type
        conditional = _parse_m_conditional_column(
            name, tree, input_column_types or {}
        )
        if conditional is not None:
            if output_type != "text":
                raise PowerQueryMScriptError(
                    "Conditional columns must use type text in the local model."
                )
            return [conditional]
        if _m_has_text_predicate(tree):
            raise PowerQueryMScriptError(
                "Text predicates in custom columns require a supported null guard "
                "and a literal search value."
            )
        step = {"op": "add_custom_column", "name": name, "expression": expression}
        if output_type != "text":
            step["output_type"] = output_type
        return [step]
    if function == "Table.TransformColumnTypes":
        if len(args) not in {1, 2}:
            raise PowerQueryMScriptError("Table.TransformColumnTypes accepts a type list and optional locale.")
        steps = []
        culture = _parse_string(args[1]) if len(args) == 2 else None
        for column, type_expr in _parse_typed_columns(args[0]):
            target_type = _parse_type(type_expr)
            if culture is None:
                steps.append({"op": "convert_type", "column": column, "type": target_type})
                continue
            if target_type not in _M_LOCALE_TYPES:
                raise PowerQueryMScriptError(
                    "The local M bridge only supports culture conversion for whole/decimal number, "
                    "date, datetime, and time types."
                )
            steps.append({
                "op": "convert_type_using_locale",
                "column": column,
                "type": target_type,
                "culture": culture,
            })
        return steps
    if function == "Table.Group":
        if len(args) not in {2, 3}:
            raise PowerQueryMScriptError(
                "Table.Group accepts key columns, aggregate columns, and optional group kind."
            )
        if len(args) == 3:
            if args[2] != "GroupKind.Global":
                raise PowerQueryMScriptError(
                    "The local grouping engine supports only the default global group kind."
                )
        columns = _parse_string_list(args[0])
        aggregations = _parse_group_aggregations(args[1])
        return [{"op": "group_by", "columns": columns, "aggregations": aggregations}]
    if function == "Table.Unpivot":
        _expect_count(function, args, 3)
        return [{
            "op": "unpivot_columns",
            "columns": _parse_string_list(args[0]),
            "attribute_name": _parse_string(args[1]),
            "value_name": _parse_string(args[2]),
        }]
    if function == "Table.UnpivotOtherColumns":
        _expect_count(function, args, 3)
        return [{
            "op": "unpivot_other_columns",
            "columns": _parse_string_list(args[0]),
            "attribute_name": _parse_string(args[1]),
            "value_name": _parse_string(args[2]),
        }]
    if function == "Table.Pivot":
        if len(args) not in {3, 4}:
            raise PowerQueryMScriptError(
                "Table.Pivot accepts pivot values, attribute and value columns, and an optional aggregation."
            )
        attribute_column = _parse_string(args[1])
        _validate_dynamic_pivot_values(args[0], previous_name, attribute_column)
        aggregation = "none"
        if len(args) == 4:
            aggregation = _parse_pivot_aggregation(args[3]) or ""
            if not aggregation:
                raise PowerQueryMScriptError(
                    "The local pivot supports List.Sum, List.Average, List.Median, "
                    "List.Min, List.Max, List.Count, or the canonical nonblank-count lambda aggregation."
                )
        return [{
            "op": "pivot_column",
            "attribute_column": attribute_column,
            "value_column": _parse_string(args[2]),
            "aggregation": aggregation,
        }]
    if function == "Table.Sort":
        _expect_count(function, args, 1)
        return [{"op": "sort_rows_by_columns", "sorts": _parse_sort_criteria(args[0])}]
    if function == "Table.Distinct":
        if len(args) > 1:
            raise PowerQueryMScriptError("Table.Distinct accepts an optional key-column list.")
        return [{"op": "remove_duplicates", **({"columns": _parse_string_list(args[0])} if args else {})}]
    if function == "Table.FirstN":
        _expect_count(function, args, 1)
        return [{"op": "keep_top_rows", "count": _parse_nonnegative_integer(args[0])}]
    if function == "Table.Skip":
        _expect_count(function, args, 1)
        return [{"op": "remove_top_rows", "count": _parse_nonnegative_integer(args[0])}]
    if function == "Table.RemoveLastN":
        if len(args) > 1:
            raise PowerQueryMScriptError(
                "The local row-removal step supports a numeric Table.RemoveLastN count only."
            )
        return [{
            "op": "remove_bottom_rows",
            "count": _parse_nonnegative_integer(args[0]) if args else 1,
        }]
    if function == "Table.LastN":
        _expect_count(function, args, 1)
        return [{"op": "keep_bottom_rows", "count": _parse_nonnegative_integer(args[0])}]
    if function == "Table.Range":
        if len(args) not in {1, 2}:
            raise PowerQueryMScriptError(
                "Table.Range accepts an offset and an optional row count."
            )
        offset = _parse_nonnegative_integer(args[0])
        count = (
            _parse_nonnegative_integer(args[1])
            if len(args) == 2 and args[1].casefold() != "null"
            else MAX_DATA_ROWS
        )
        if offset >= MAX_DATA_ROWS:
            raise PowerQueryMScriptError(
                f"Table.Range offset must be less than {MAX_DATA_ROWS:,} in the local row engine."
            )
        return [{"op": "keep_range_rows", "first_row": offset + 1, "count": count}]
    if function == "Table.AlternateRows":
        _expect_count(function, args, 3)
        offset = _parse_nonnegative_integer(args[0])
        remove_count = _parse_nonnegative_integer(args[1])
        keep_count = _parse_nonnegative_integer(args[2])
        if offset >= MAX_DATA_ROWS:
            raise PowerQueryMScriptError(
                f"Table.AlternateRows offset must be less than {MAX_DATA_ROWS:,} in the local row engine."
            )
        return [{
            "op": "remove_alternate_rows",
            "first_row_to_remove": offset + 1,
            "remove_count": remove_count,
            "keep_count": keep_count,
        }]
    if function == "Table.ReplaceValue":
        _expect_count(function, args, 4)
        old_value = _parse_string(args[0])
        replacement = _parse_string(args[1])
        if args[2] != "Replacer.ReplaceValue":
            raise PowerQueryMScriptError("Only Replacer.ReplaceValue is supported by Table.ReplaceValue.")
        return [{
            "op": "replace_value", "column": column,
            "value": old_value, "replacement": replacement,
        } for column in _parse_string_list(args[3])]
    if function == "Table.TransformColumns":
        _expect_count(function, args, 1)
        operation_map = {
            "Text.Trim": "trim_text", "Text.Clean": "clean_text",
            "Text.Lower": "lowercase_text", "Text.Upper": "uppercase_text",
            "Text.Proper": "proper_case_text", "Text.Reverse": "reverse_text",
        }
        steps = []
        for transform in _parse_transform_list(args[0]):
            column, operation_expression = transform[:2]
            if operation_expression in operation_map:
                if len(transform) == 3 and _parse_type(transform[2]) != "text":
                    raise PowerQueryMScriptError(
                        "The local text transforms return text; a non-text output type declaration "
                        "cannot be preserved."
                    )
                steps.append({"op": operation_map[operation_expression], "column": column})
                continue
            steps.append(_parse_delimiter_transform(column, operation_expression, transform[2:]))
        return steps
    if function == "Table.ReorderColumns":
        _expect_count(function, args, 1)
        return [{"op": "reorder_columns", "columns": _parse_string_list(args[0])}]
    if function == "Table.PromoteHeaders":
        _expect_count(function, args, 0)
        return [{"op": "promote_headers"}]
    if function == "Table.DemoteHeaders":
        _expect_count(function, args, 0)
        return [{"op": "demote_headers"}]
    if function == "Table.AddIndexColumn":
        if len(args) not in {1, 2, 3, 4}:
            raise PowerQueryMScriptError("Table.AddIndexColumn accepts a name, optional start, increment, and type.")
        name = _parse_string(args[0])
        start = _parse_nonnegative_or_signed_integer(args[1]) if len(args) > 1 else 0
        increment = _parse_nonnegative_or_signed_integer(args[2]) if len(args) > 2 else 1
        if len(args) == 4 and _parse_type(args[3]) != "whole_number":
            raise PowerQueryMScriptError("The local index column must use Int64.Type.")
        return [{"op": "add_index_column", "new_name": name, "start": start, "increment": increment}]
    if function == "Table.DuplicateColumn":
        _expect_count(function, args, 2)
        return [{"op": "duplicate_column", "column": _parse_string(args[0]), "new_name": _parse_string(args[1])}]
    if function == "Table.FillDown":
        _expect_count(function, args, 1)
        return [{"op": "fill_down", "columns": _parse_string_list(args[0])}]
    if function == "Table.FillUp":
        _expect_count(function, args, 1)
        return [{"op": "fill_up", "columns": _parse_string_list(args[0])}]

    raise PowerQueryMScriptError(f"{function} is not in the supported local M subset.")


_M_NUMERIC_TYPES = {"whole_number", "decimal_number", "number", "currency"}
_M_TEXT_PREDICATES = {
    "Text.Contains": "contains",
    "Text.StartsWith": "begins_with",
    "Text.EndsWith": "ends_with",
}


def _parse_m_conditional_column(
    name: str,
    tree: tuple[Any, ...],
    input_column_types: dict[str, str],
) -> dict[str, Any] | None:
    """Translate a simple M if-chain to the local ordered-rule step shape."""
    if tree[0] != "if":
        return None
    clauses: list[dict[str, str]] = []
    current = tree
    while current[0] == "if":
        predicate = _parse_m_conditional_predicate(
            current[1], input_column_types
        )
        output = _parse_m_conditional_output(current[2])
        if predicate is None and _m_has_text_predicate(current[1]):
            raise PowerQueryMScriptError(
                "Text conditional predicates require a supported null guard and a literal search value."
            )
        if predicate is None or output is None:
            return None
        clauses.append({**predicate, **output})
        current = current[3]
    else_output = _parse_m_conditional_output(current)
    if not clauses or else_output is None:
        return None
    return {
        "op": "conditional_column",
        "name": name,
        "clauses": clauses,
        "else_value": else_output["output"],
        "else_kind": else_output["output_kind"],
    }


def _m_has_text_predicate(node: tuple[Any, ...]) -> bool:
    """Return whether an expression contains one of the nullable text predicates."""
    if node[0] == "call" and node[1] in _M_TEXT_PREDICATES:
        return True
    return any(
        _m_has_text_predicate(child)
        for child in node[1:]
        if isinstance(child, tuple) and child and isinstance(child[0], str)
    )


def _parse_m_conditional_predicate(
    node: tuple[Any, ...], input_column_types: dict[str, str]
) -> dict[str, str] | None:
    if node[0] == "if":
        guard_column = _m_conditional_null_guard(node[1])
        when_null, when_nonnull = node[2], node[3]
        if guard_column is None or when_null[0] != "literal" or not isinstance(when_null[1], bool):
            return None
        negative = (
            when_nonnull[0] == "unary"
            and when_nonnull[1] == "not"
            and when_nonnull[2][0] == "call"
        )
        call = when_nonnull[2] if negative else when_nonnull
        if call[0] != "call" or call[1] not in _M_TEXT_PREDICATES:
            return None
        arguments = call[2]
        if len(arguments) != 2 or arguments[0][0] != "field":
            return None
        column = arguments[0][1]
        if column.casefold() != guard_column.casefold():
            raise PowerQueryMScriptError(
                "A conditional text predicate's null guard must check the same column it reads."
            )
        value = arguments[1]
        if value[0] == "field":
            raise PowerQueryMScriptError(
                "Text conditional predicates cannot use a column comparison value because "
                "the local table model does not preserve nulls in that column."
            )
        elif value[0] == "literal" and isinstance(value[1], str):
            test_value, test_kind = value[1], "value"
        else:
            return None
        if _m_conditional_column_type(input_column_types, column) != "text":
            raise PowerQueryMScriptError(
                "Text conditional rules require a text-typed input column."
            )
        empty_input_matches = test_value == ""
        expected_null_result = empty_input_matches != negative
        if when_null[1] != expected_null_result:
            raise PowerQueryMScriptError(
                "A conditional text predicate's null guard must preserve blank-row behavior."
            )
        operator = _M_TEXT_PREDICATES[call[1]]
        if negative:
            operator = {
                "contains": "does_not_contain",
                "begins_with": "does_not_begin_with",
                "ends_with": "does_not_end_with",
            }[operator]
        return {
            "column": column,
            "operator": operator,
            "test_value": test_value,
            "test_value_kind": test_kind,
        }

    if node[0] == "call" and node[1] in _M_TEXT_PREDICATES:
        # Text predicates return nullable logical for null input. A bare M if
        # would therefore have different behavior from the normalized local
        # text-cell model, so accept only the explicit guard above.
        return None
    if (
        node[0] == "unary"
        and node[1] == "not"
        and node[2][0] == "call"
        and node[2][1] in _M_TEXT_PREDICATES
    ):
        return None
    if node[0] != "binary" or node[1] not in {"=", "<>", ">", ">=", "<", "<="}:
        return None

    operator = {
        "=": "equals", "<>": "not_equals", ">": "greater_than",
        ">=": "greater_than_or_equal", "<": "less_than",
        "<=": "less_than_or_equal",
    }[node[1]]
    left, right = node[2], node[3]
    if left[0] == "literal" and right[0] == "field":
        left, right = right, left
        operator = {
            "greater_than": "less_than",
            "greater_than_or_equal": "less_than_or_equal",
            "less_than": "greater_than",
            "less_than_or_equal": "greater_than_or_equal",
        }.get(operator, operator)
    if left[0] != "field" or right[0] not in {"field", "literal"}:
        return None
    column = left[1]
    left_type = _m_conditional_column_type(input_column_types, column)
    if right[0] == "field":
        test_value, test_kind = right[1], "column"
        right_type = _m_conditional_column_type(input_column_types, test_value)
    else:
        literal = right[1]
        if literal is None:
            raise PowerQueryMScriptError(
                "Conditional comparisons to null are unsupported because the local table model "
                "stores null and empty text as the same cell value."
            )
        try:
            test_value = expression_value_to_text(literal)
        except ExpressionError as exc:
            raise PowerQueryMScriptError(str(exc)) from exc
        test_kind = "value"
        right_type = _m_conditional_literal_type(literal)

    if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
        if left_type not in _M_NUMERIC_TYPES or right_type not in _M_NUMERIC_TYPES:
            raise PowerQueryMScriptError(
                "Ordered conditional M comparisons are supported only for numeric columns "
                "after an explicit numeric type conversion."
            )
    elif left_type != right_type and not (
        left_type in _M_NUMERIC_TYPES and right_type in _M_NUMERIC_TYPES
    ):
        raise PowerQueryMScriptError(
            "A conditional comparison must use matching M input and comparison types."
        )
    if operator in {"equals", "not_equals"}:
        if left_type in _M_NUMERIC_TYPES or right_type in _M_NUMERIC_TYPES:
            raise PowerQueryMScriptError(
                "Numeric conditional equality is unsupported because the local step engine "
                "compares normalized text rather than numeric values."
            )
        if left_type == "text" and (
            test_kind == "column" or test_value == ""
        ):
            raise PowerQueryMScriptError(
                "Text conditional equality to another column or an empty string is unsupported "
                "because the local table model conflates null and empty text."
            )
    return {
        "column": column,
        "operator": operator,
        "test_value": test_value,
        "test_value_kind": test_kind,
    }


def _m_conditional_null_guard(node: tuple[Any, ...]) -> str | None:
    if (
        node[0] == "binary"
        and node[1] == "="
        and node[2][0] == "field"
        and node[3] == ("literal", None)
    ):
        return node[2][1]
    if (
        node[0] == "binary"
        and node[1] == "="
        and node[2] == ("literal", None)
        and node[3][0] == "field"
    ):
        return node[3][1]
    return None


def _parse_m_conditional_output(node: tuple[Any, ...]) -> dict[str, str] | None:
    if node[0] == "call" and node[1] == "Text.From" and len(node[2]) == 1:
        node = node[2][0]
    if node[0] == "field":
        return {"output": node[1], "output_kind": "column"}
    if node[0] == "literal":
        try:
            value = expression_value_to_text(node[1])
        except ExpressionError as exc:
            raise PowerQueryMScriptError(str(exc)) from exc
        return {"output": value, "output_kind": "value"}
    return None


def _m_conditional_column_type(
    column_types: dict[str, str], column: str
) -> str:
    actual = next(
        (name for name in column_types if name.casefold() == column.casefold()),
        None,
    )
    return canonical_column_type(column_types.get(actual, "text"))


def _m_conditional_literal_type(value: Any) -> str:
    if isinstance(value, str):
        return "text"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Decimal):
        return "decimal_number"
    return "unknown"


def _m_conditional_column_call(
    previous: str,
    step: dict[str, Any],
    input_column_types: dict[str, str],
) -> str:
    comparisons = {
        "equals": "=", "not_equals": "<>",
        "greater_than": ">", "greater_than_or_equal": ">=",
        "less_than": "<", "less_than_or_equal": "<=",
    }

    def comparison_value(value: str, kind: str, column_type: str) -> str:
        if kind == "column":
            return _m_field(value)
        if column_type in _M_NUMERIC_TYPES:
            try:
                number = Decimal(value)
            except Exception as exc:
                raise PowerQueryMScriptError(
                    "A numeric conditional rule needs a valid numeric comparison value."
                ) from exc
            if not number.is_finite():
                raise PowerQueryMScriptError(
                    "A numeric conditional rule needs a finite comparison value."
                )
            return str(number)
        if column_type == "boolean":
            normalized = value.casefold()
            if normalized not in {"true", "false"}:
                raise PowerQueryMScriptError(
                    "A Boolean conditional rule needs true or false as its comparison value."
                )
            return normalized
        if column_type == "text":
            return _m_string(value)
        raise PowerQueryMScriptError(
            "Conditional M rules support text, Boolean, and numeric comparison columns only."
        )

    def predicate(clause: dict[str, str]) -> str:
        column = clause["column"]
        column_type = _m_conditional_column_type(input_column_types, column)
        operator = clause["operator"]
        if operator in comparisons:
            right_type = (
                _m_conditional_column_type(input_column_types, clause["test_value"])
                if clause["test_value_kind"] == "column"
                else column_type
            )
            if operator in {
                "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
            } and (column_type not in _M_NUMERIC_TYPES or right_type not in _M_NUMERIC_TYPES):
                raise PowerQueryMScriptError(
                    "Ordered conditional rules require numeric type conversions before the rule."
                )
            if operator in {"equals", "not_equals"} and (
                column_type != right_type
                and not (column_type in _M_NUMERIC_TYPES and right_type in _M_NUMERIC_TYPES)
            ):
                raise PowerQueryMScriptError(
                    "A conditional comparison must use matching M input and comparison types."
                )
            if operator in {"equals", "not_equals"}:
                if column_type in _M_NUMERIC_TYPES or right_type in _M_NUMERIC_TYPES:
                    raise PowerQueryMScriptError(
                        "Numeric conditional equality is unsupported because the local step "
                        "engine compares normalized text rather than numeric values."
                    )
                if column_type == "text" and (
                    clause["test_value_kind"] == "column"
                    or clause["test_value"] == ""
                ):
                    raise PowerQueryMScriptError(
                        "Text conditional equality to another column or an empty string is "
                        "unsupported because the local table model conflates null and empty text."
                    )
            right = comparison_value(
                clause["test_value"], clause["test_value_kind"], column_type
            )
            return f"{_m_field(column)} {comparisons[operator]} {right}"
        if operator not in {
            "contains", "does_not_contain", "begins_with", "does_not_begin_with",
            "ends_with", "does_not_end_with",
        }:
            raise PowerQueryMScriptError(
                f"Conditional operator {operator!r} cannot be represented as M."
            )
        if column_type != "text":
            raise PowerQueryMScriptError(
                "Text conditional rules require a text-typed column."
            )
        function = {
            "contains": "Text.Contains", "does_not_contain": "Text.Contains",
            "begins_with": "Text.StartsWith", "does_not_begin_with": "Text.StartsWith",
            "ends_with": "Text.EndsWith", "does_not_end_with": "Text.EndsWith",
        }[operator]
        if clause["test_value_kind"] == "column":
            raise PowerQueryMScriptError(
                "Text conditional predicates cannot use a column comparison value because "
                "the local table model does not preserve nulls in that column."
            )
        value = _m_string(clause["test_value"])
        negative = operator.startswith("does_not_")
        empty_input_matches = clause["test_value"] == ""
        null_result = str(empty_input_matches != negative).lower()
        call = f"{function}({_m_field(column)}, {value})"
        result = f"not {call}" if negative else call
        return f"(if {_m_field(column)} = null then {null_result} else {result})"

    def output(value: str, kind: str) -> str:
        raw = _m_field(value) if kind == "column" else _m_string(value)
        return f"Text.From({raw})"

    expression = output(step["else_value"], step["else_kind"])
    for clause in reversed(step["clauses"]):
        expression = (
            f"if {predicate(clause)} then "
            f"{output(clause['output'], clause['output_kind'])} else {expression}"
        )
    return (
        f"Table.AddColumn({previous}, {_m_string(step['name'])}, "
        f"each {expression}, type text)"
    )


def _parse_row_predicate(
    expression: str, *, parameter_names: set[str] | None = None
) -> tuple[str, str, Any]:
    try:
        tree = compile_expression(
            _decode_m_expression_literals(expression),
            allowed_symbols=parameter_names,
        )
    except ExpressionError as exc:
        raise PowerQueryMScriptError(f"Unsupported row filter: {exc}") from exc
    return _parse_row_predicate_tree(tree)


def _parse_row_filter(
    expression: str, *, parameter_names: set[str] | None = None
) -> list[dict[str, Any]]:
    try:
        tree = compile_expression(
            _decode_m_expression_literals(expression),
            allowed_symbols=parameter_names,
        )
    except ExpressionError as exc:
        raise PowerQueryMScriptError(f"Unsupported row filter: {exc}") from exc
    if tree[0] != "binary" or tree[1] not in {"and", "or"}:
        column, operator, value = _parse_row_predicate_tree(tree)
        reference = (
            {"parameter": value[1]}
            if isinstance(value, tuple) and value[:1] == ("parameter",)
            else {"value": value}
        )
        return [{"op": "filter_rows", "column": column, "operator": operator, **reference}]

    groups = _flatten_boolean_tree(tree, "or")
    clauses: list[dict[str, str]] = []
    for group_index, group in enumerate(groups):
        if _contains_boolean_tree(group, "or"):
            raise PowerQueryMScriptError(
                "A row filter must use AND clauses grouped before OR clauses, as supported by the local advanced filter."
            )
        group_clauses = _flatten_boolean_tree(group, "and")
        for clause_index, predicate in enumerate(group_clauses):
            column, operator, value = _parse_row_predicate_tree(predicate)
            clause_value = (
                {"parameter": value[1]}
                if isinstance(value, tuple) and value[:1] == ("parameter",)
                else {"value": value}
            )
            clauses.append({
                "column": column,
                "operator": operator,
                **clause_value,
                "join": "or" if group_index and clause_index == 0 else "and",
            })
    if len(clauses) == 1:
        clause = clauses[0]
        return [{
            "op": "filter_rows", "column": clause["column"],
            "operator": clause["operator"],
            **({"parameter": clause["parameter"]} if "parameter" in clause else {"value": clause["value"]}),
        }]
    return [{"op": "filter_rows_advanced", "clauses": clauses}]


def _flatten_boolean_tree(tree: tuple[Any, ...], operator: str) -> list[tuple[Any, ...]]:
    if tree[0] == "binary" and tree[1] == operator:
        return _flatten_boolean_tree(tree[2], operator) + _flatten_boolean_tree(tree[3], operator)
    return [tree]


def _contains_boolean_tree(tree: tuple[Any, ...], operator: str) -> bool:
    if tree[0] == "binary" and tree[1] == operator:
        return True
    if tree[0] == "binary":
        return _contains_boolean_tree(tree[2], operator) or _contains_boolean_tree(tree[3], operator)
    if tree[0] == "unary":
        return _contains_boolean_tree(tree[2], operator)
    return False


def _parse_row_predicate_tree(tree: tuple[Any, ...]) -> tuple[str, str, Any]:
    operators = {
        "=": "equals", "<>": "not_equals", ">": "greater_than",
        ">=": "greater_than_or_equal", "<": "less_than",
        "<=": "less_than_or_equal",
    }
    blank_guard_field: str | None = None
    blank_guard_value: bool | None = None
    predicate_tree = tree
    if tree[0] == "if":
        condition, when_true, when_false = tree[1:]
        blank_guard_field = _parse_blank_row_guard(condition)
        if (
            blank_guard_field is not None
            and when_true[0] == "literal"
            and isinstance(when_true[1], bool)
        ):
            blank_guard_value = when_true[1]
            predicate_tree = when_false

    if predicate_tree[0] == "binary" and predicate_tree[1] in operators:
        left, right = predicate_tree[2], predicate_tree[3]
        operator = operators[predicate_tree[1]]
        left_field = left[1] if left[0] == "field" else _number_from_field(left)
        right_field = right[1] if right[0] == "field" else _number_from_field(right)
        if left[0] == "literal" and right_field is not None:
            left_field, right = right_field, left
            right_field = None
            operator = {
                "greater_than": "less_than",
                "greater_than_or_equal": "less_than_or_equal",
                "less_than": "greater_than",
                "less_than_or_equal": "greater_than_or_equal",
            }.get(operator, operator)
        elif left_field is not None:
            right_field = None
        if left_field is not None and right_field is None and right[0] in {"literal", "symbol"}:
            if right[0] == "symbol":
                if operator not in {"equals", "not_equals", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
                    raise PowerQueryMScriptError(
                        "Power Query parameters are supported only as direct row-filter comparison values."
                    )
                if _number_from_field(left) is not None and (
                    blank_guard_field != left_field or blank_guard_value is not False
                ):
                    raise PowerQueryMScriptError(
                        "Number.From row filters must exclude null and empty values before numeric conversion."
                    )
                return left_field, operator, ("parameter", right[1])
            value = right[1]
            if value is None:
                if operator not in {"equals", "not_equals"}:
                    raise PowerQueryMScriptError("Null can only be used with equality in a row filter.")
                return left_field, "is_blank" if operator == "equals" else "is_not_blank", ""
            if isinstance(value, bool):
                value = "true" if value else "false"
            else:
                value = expression_value_to_text(value)
            if blank_guard_field is not None and blank_guard_field != left_field:
                raise PowerQueryMScriptError("A numeric filter's blank guard must reference its filtered column.")
            if _number_from_field(left) is not None and (
                blank_guard_field != left_field or blank_guard_value is not False
            ):
                raise PowerQueryMScriptError(
                    "Number.From row filters must exclude null and empty values before numeric conversion."
                )
            return left_field, operator, value

    # Text.Contains/StartsWith/EndsWith return nullable logical values for null
    # input in M. The local table model stores blanks as empty text, so the
    # generated negative filters explicitly map null to true and the positive
    # filters map null to false. Accept only that guard when parsing a negative
    # predicate so the local replay has the same row set.
    null_guard_value = blank_guard_value
    text_predicate = predicate_tree

    negative = False
    if (
        text_predicate[0] == "unary"
        and text_predicate[1] == "not"
        and text_predicate[2][0] == "call"
    ):
        negative = True
        text_predicate = text_predicate[2]

    if text_predicate[0] == "call" and text_predicate[1] in {
        "Text.Contains", "Text.StartsWith", "Text.EndsWith",
    }:
        arguments = text_predicate[2]
        if len(arguments) == 2:
            left, right = arguments
            if (
                left[0] == "field"
                and right[0] == "literal"
                and isinstance(right[1], str)
                and (blank_guard_field is None or blank_guard_field == left[1])
            ):
                prefix = {
                    "Text.Contains": "contain",
                    "Text.StartsWith": "begin",
                    "Text.EndsWith": "end",
                }[text_predicate[1]]
                operator = f"does_not_{prefix}_with" if negative and prefix != "contain" else (
                    "does_not_contain" if negative else {
                        "contain": "contains",
                        "begin": "begins_with",
                        "end": "ends_with",
                    }[prefix]
                )
                if null_guard_value is not None and null_guard_value != negative:
                    raise PowerQueryMScriptError(
                        "A text filter's null guard does not match its positive/negative operator."
                    )
                if negative and null_guard_value is None:
                    raise PowerQueryMScriptError(
                        "A negative text filter must explicitly include null rows through an if-blank guard."
                    )
                return left[1], operator, right[1]
    raise PowerQueryMScriptError(
        "A row filter supports comparisons or Text.Contains/StartsWith/EndsWith predicates."
    )


def _number_from_field(tree: tuple[Any, ...]) -> str | None:
    if (
        tree[0] == "call"
        and tree[1] == "Number.From"
        and len(tree[2]) == 1
        and tree[2][0][0] == "field"
    ):
        return tree[2][0][1]
    return None


def _parse_blank_row_guard(tree: tuple[Any, ...]) -> str | None:
    checks = _flatten_boolean_tree(tree, "or")
    if not checks:
        return None
    field_name: str | None = None
    blank_values: set[Any] = set()
    for check in checks:
        if check[0] != "binary" or check[1] != "=":
            return None
        left, right = check[2], check[3]
        if left[0] == "literal" and right[0] == "field":
            left, right = right, left
        if left[0] != "field" or right[0] != "literal" or right[1] not in {None, ""}:
            return None
        if field_name is not None and field_name != left[1]:
            return None
        field_name = left[1]
        blank_values.add(right[1])
    return field_name if None in blank_values else None


def _filter_clause_to_m_predicate(clause: dict[str, str]) -> str:
    column = _m_field(clause["column"])
    comparison_value = (
        clause["parameter"]
        if "parameter" in clause
        else _m_string(clause["value"])
    )
    comparators = {
        "equals": "=", "not_equals": "<>",
    }
    operator = clause["operator"]
    if operator in comparators:
        return f"{column} {comparators[operator]} {comparison_value}"
    numeric_comparators = {
        "greater_than": ">", "greater_than_or_equal": ">=",
        "less_than": "<", "less_than_or_equal": "<=",
    }
    if operator in numeric_comparators:
        numeric_value = (
            clause["parameter"]
            if "parameter" in clause
            else _m_numeric_literal(clause["value"])
        )
        return (
            f'(if {column} = null or {column} = "" then false else '
            f"Number.From({column}) {numeric_comparators[operator]} "
            f"{numeric_value})"
        )
    if operator in {"is_blank", "is_not_blank"}:
        comparator = "=" if operator == "is_blank" else "<>"
        return f"{column} {comparator} null"
    function = {
        "contains": "Text.Contains",
        "does_not_contain": "Text.Contains",
        "begins_with": "Text.StartsWith",
        "does_not_begin_with": "Text.StartsWith",
        "ends_with": "Text.EndsWith",
        "does_not_end_with": "Text.EndsWith",
    }.get(operator)
    if function is None:
        raise PowerQueryMScriptError(f"Filter operator {operator!r} cannot be exported as M.")
    if "parameter" in clause:
        raise PowerQueryMScriptError(
            "Text-search filters do not support parameter references in this local M subset."
        )
    negative = operator.startswith("does_not_")
    null_result = "true" if negative else "false"
    text_call = f"{function}({column}, {_m_string(clause['value'])})"
    branch = f"not {text_call}" if negative else text_call
    return f'(if {column} = null or {column} = "" then {null_result} else {branch})'


def _m_numeric_literal(value: str) -> str:
    try:
        number = Decimal(value.strip())
    except DecimalException as exc:
        raise PowerQueryMScriptError(
            f"Numeric filter value {value!r} is not a finite number."
        ) from exc
    if not number.is_finite():
        raise PowerQueryMScriptError(
            f"Numeric filter value {value!r} is not a finite number."
        )
    return str(number)


def _step_to_m_call(
    previous: str,
    step: dict[str, Any],
    input_column_types: dict[str, str] | None = None,
) -> str:
    op = step["op"]
    if op == "remove_blank_rows":
        return (
            f'Table.SelectRows({previous}, each not List.IsEmpty('
            'List.RemoveMatchingItems(Record.FieldValues(_), {null, ""})))'
        )
    if op == "remove_column":
        return f"Table.RemoveColumns({previous}, {{{_m_string(step['column'])}}})"
    if op == "keep_columns":
        return f"Table.SelectColumns({previous}, {_m_string_list(step['columns'])})"
    if op == "rename_column":
        pair = "{" + _m_string(step["column"]) + ", " + _m_string(step["new_name"]) + "}"
        return f"Table.RenameColumns({previous}, {{{pair}}})"
    if op in {"filter_rows", "filter_rows_advanced"}:
        clauses = ([{
            "column": step["column"], "operator": step["operator"],
            **({"parameter": step["parameter"]} if "parameter" in step else {"value": step["value"]}),
            "join": "and",
        }] if op == "filter_rows" else step["clauses"])
        groups: list[list[str]] = []
        for clause in clauses:
            expression = _filter_clause_to_m_predicate(clause)
            if clause["join"] == "or":
                groups.append([expression])
            elif groups:
                groups[-1].append(expression)
            else:
                groups.append([expression])
        predicate = " or ".join(
            " and ".join(group) if len(group) == 1 else "(" + " and ".join(group) + ")"
            for group in groups
        )
        return f"Table.SelectRows({previous}, each {predicate})"
    if op == "add_custom_column":
        expression = step["expression"]
        output_type = step.get("output_type", "text")
        if output_type == "text" and _unwrap_text_from(expression) == expression:
            expression = f"Text.From({expression})"
        return (
            f"Table.AddColumn({previous}, {_m_string(step['name'])}, "
            f"each {expression}, {_m_type(output_type)})"
        )
    if op == "conditional_column":
        return _m_conditional_column_call(
            previous, step, input_column_types or {}
        )
    if op in {"convert_type", "convert_type_using_locale"}:
        type_list = f"{{{{{_m_string(step['column'])}, {_m_type(step['type'])}}}}}"
        culture = (
            f", {_m_string(step['culture'])}"
            if op == "convert_type_using_locale"
            else ""
        )
        return f"Table.TransformColumnTypes({previous}, {type_list}{culture})"
    if op == "sort_rows":
        direction = "Descending" if step["direction"] in {"desc", "descending"} else "Ascending"
        pair = "{" + _m_string(step["column"]) + f", Order.{direction}" + "}"
        return f"Table.Sort({previous}, {{{pair}}})"
    if op == "sort_rows_by_columns":
        pairs = []
        for sort in step["sorts"]:
            direction = "Descending" if sort["direction"] in {"desc", "descending"} else "Ascending"
            pairs.append("{" + _m_string(sort["column"]) + f", Order.{direction}" + "}")
        return f"Table.Sort({previous}, {{{', '.join(pairs)}}})"
    if op == "remove_duplicates":
        extra = f", {_m_string_list(step['columns'])}" if "columns" in step else ""
        return f"Table.Distinct({previous}{extra})"
    if op == "keep_duplicates":
        return _keep_duplicates_m_expression(previous, step["columns"])
    if op == "keep_top_rows":
        return f"Table.FirstN({previous}, {step['count']})"
    if op == "remove_top_rows":
        return f"Table.Skip({previous}, {step['count']})"
    if op == "remove_bottom_rows":
        return f"Table.RemoveLastN({previous}, {step['count']})"
    if op == "keep_bottom_rows":
        return f"Table.LastN({previous}, {step['count']})"
    if op == "keep_range_rows":
        return f"Table.Range({previous}, {step['first_row'] - 1}, {step['count']})"
    if op == "remove_alternate_rows":
        return (
            f"Table.AlternateRows({previous}, {step['first_row_to_remove'] - 1}, "
            f"{step['remove_count']}, {step['keep_count']})"
        )
    if op == "group_by":
        aggregations = ", ".join(
            "{" + _m_string(aggregate["new_name"]) + ", "
            + _m_group_aggregation(aggregate) + "}"
            for aggregate in step["aggregations"]
        )
        return (
            f"Table.Group({previous}, {_m_string_list(step['columns'])}, "
            f"{{{aggregations}}})"
        )
    if op in {"unpivot_columns", "unpivot_other_columns"}:
        function = (
            "Table.Unpivot" if op == "unpivot_columns"
            else "Table.UnpivotOtherColumns"
        )
        return (
            f"{function}({previous}, {_m_string_list(step['columns'])}, "
            f"{_m_string(step['attribute_name'])}, {_m_string(step['value_name'])})"
        )
    if op == "pivot_column":
        aggregation = {
            "sum": "List.Sum",
            "average": "List.Average",
            "median": "List.Median",
            "min": "List.Min",
            "max": "List.Max",
            "count_all": "List.Count",
            "count_non_blank": 'each List.Count(List.RemoveItems(_, {null, ""}))',
        }.get(step["aggregation"])
        if step["aggregation"] != "none" and aggregation is None:
            raise PowerQueryMScriptError(
                f"Pivot aggregation {step['aggregation']!r} cannot be represented as M."
            )
        arguments = (
            f"{previous}, List.Distinct(Table.Column({previous}, "
            f"{_m_string(step['attribute_column'])})), "
            f"{_m_string(step['attribute_column'])}, {_m_string(step['value_column'])}"
        )
        if aggregation is not None:
            arguments += f", {aggregation}"
        return f"Table.Pivot({arguments})"
    if op == "replace_value":
        return (
            f"Table.ReplaceValue({previous}, {_m_string(step['value'])}, "
            f"{_m_string(step['replacement'])}, Replacer.ReplaceValue, "
            f"{{{_m_string(step['column'])}}})"
        )
    if op in {"extract_text_by_delimiter", "extract_text_between_delimiters"}:
        column = step["column"]
        if op == "extract_text_by_delimiter":
            function = "Text.BeforeDelimiter" if step["side"] == "before" else "Text.AfterDelimiter"
            arguments = f"_, {_m_string(step['delimiter'])}, {step['occurrence']}"
        else:
            function = "Text.BetweenDelimiters"
            arguments = (
                f"_, {_m_string(step['start_delimiter'])}, {_m_string(step['end_delimiter'])}, "
                f"{step['start_occurrence']}, {step['end_occurrence']}"
            )
        transform = (
            "{" + _m_string(column)
            + f', each if _ = null or _ = "" then "" else {function}({arguments}), type text' + "}"
        )
        return f"Table.TransformColumns({previous}, {{{transform}}})"
    if op == "split_column":
        names = _m_string_list([f"{step['column']}.1", f"{step['column']}.2"])
        splitter = (
            "Splitter.SplitTextByEachDelimiter("
            f"{{{_m_string(step['delimiter'])}}}, QuoteStyle.None)"
        )
        return (
            f"Table.SplitColumn({previous}, {_m_string(step['column'])}, "
            f"{splitter}, {names}, {_m_string('')})"
        )
    if op == "split_column_by_positions":
        positions = "{" + ", ".join(map(str, step["positions"])) + "}"
        names = _m_string_list([
            f"{step['column']}.{index}"
            for index in range(1, len(step["positions"]) + 1)
        ])
        splitter = f"Splitter.SplitTextByPositions({positions})"
        return (
            f"Table.SplitColumn({previous}, {_m_string(step['column'])}, "
            f"{splitter}, {names}, {_m_string('')})"
        )
    if op == "split_column_by_each_delimiter":
        splitter = (
            f"Splitter.SplitTextByDelimiter({_m_string(step['delimiter'])}, QuoteStyle.None)"
        )
        split_count = _m_dynamic_split_count(previous, step["column"], step["delimiter"])
        return (
            f"Table.SplitColumn({previous}, {_m_string(step['column'])}, "
            f"{splitter}, {split_count}, {_m_string('')})"
        )
    if op == "split_column_to_rows":
        column = step["column"]
        splitter = (
            "each Text.Split(if _ = null then \"\" else _, "
            f"{_m_string(step['delimiter'])})"
        )
        transformed = (
            f"Table.TransformColumns({previous}, "
            f"{{{{{_m_string(column)}, {splitter}}}}})"
        )
        return f"Table.ExpandListColumn({transformed}, {_m_string(column)})"
    if op == "merge_columns":
        combiner = (
            "Combiner.CombineTextByDelimiter("
            f"{_m_string(step['separator'])}, QuoteStyle.None)"
        )
        return (
            f"Table.CombineColumns({previous}, {_m_string_list(step['columns'])}, "
            f"{combiner}, {_m_string(step['new_name'])})"
        )
    text_function = {
        "trim_text": "Text.Trim", "clean_text": "Text.Clean",
        "lowercase_text": "Text.Lower", "uppercase_text": "Text.Upper",
        "proper_case_text": "Text.Proper", "reverse_text": "Text.Reverse",
    }.get(op)
    if text_function:
        transform = "{" + _m_string(step["column"]) + f", {text_function}, type text" + "}"
        return f"Table.TransformColumns({previous}, {{{transform}}})"
    if op == "reorder_columns":
        return f"Table.ReorderColumns({previous}, {_m_string_list(step['columns'])})"
    if op == "promote_headers":
        return f"Table.PromoteHeaders({previous})"
    if op == "demote_headers":
        return f"Table.DemoteHeaders({previous})"
    if op == "transpose_table":
        return f"Table.Transpose({previous})"
    if op == "add_index_column":
        return f"Table.AddIndexColumn({previous}, {_m_string(step['new_name'])}, {step['start']}, {step['increment']}, Int64.Type)"
    if op == "duplicate_column":
        return f"Table.DuplicateColumn({previous}, {_m_string(step['column'])}, {_m_string(step['new_name'])})"
    if op in {"fill_down", "fill_up"}:
        function = "Table.FillDown" if op == "fill_down" else "Table.FillUp"
        return f"{function}({previous}, {_m_string_list(step['columns'])})"
    raise PowerQueryMScriptError(
        f"Applied step {op!r} cannot be represented in the current M subset."
    )


def _parse_group_aggregations(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    function_operations = {
        "List.Sum": "sum",
        "List.Average": "average",
        "List.Median": "median",
        "List.Min": "min",
        "List.Max": "max",
    }
    for item in _parse_braced_items(value):
        parts = _parse_braced_items(item)
        if len(parts) != 2:
            raise PowerQueryMScriptError(
                "Each local Table.Group aggregation needs an output name and an each expression."
            )
        new_name = _parse_string(parts[0])
        expression = parts[1].strip()
        if expression == "each Table.RowCount(_)":
            result.append({"operation": "count_rows", "new_name": new_name})
            continue
        if expression == "each Table.RowCount(Table.Distinct(_))":
            result.append({"operation": "count_distinct_rows", "new_name": new_name})
            continue
        expression = re.sub(r"^each\s+", "", expression, count=1)
        call = _CALL.fullmatch(expression)
        if call is None:
            raise PowerQueryMScriptError(
                f"Table.Group aggregation {new_name!r} is outside the supported local subset."
            )
        function = call.group(1)
        arguments = _split_top_level(call.group(2), ",")
        if function == "List.Count" and len(arguments) == 1:
            distinct = _CALL.fullmatch(arguments[0].strip())
            if distinct is not None and distinct.group(1) == "List.Distinct":
                distinct_arguments = _split_top_level(distinct.group(2), ",")
                if len(distinct_arguments) == 1:
                    column = _parse_m_field_reference(distinct_arguments[0])
                    result.append({
                        "operation": "count_distinct_values",
                        "column": column,
                        "new_name": new_name,
                    })
                    continue
        operation = function_operations.get(function)
        if operation is None or len(arguments) != 1:
            raise PowerQueryMScriptError(
                f"Table.Group aggregation {new_name!r} is outside the supported local subset."
            )
        result.append({
            "operation": operation,
            "column": _parse_m_field_reference(arguments[0]),
            "new_name": new_name,
        })
    if not result:
        raise PowerQueryMScriptError("Table.Group needs at least one aggregation.")
    return result


def _parse_m_field_reference(value: str) -> str:
    text = value.strip()
    quoted = re.fullmatch(r'\[\s*#"((?:[^"]|"")*)"\s*\]', text)
    if quoted is not None:
        return _parse_quoted('#"' + quoted.group(1) + '"', prefix="#")
    plain = re.fullmatch(r"\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*\]", text)
    if plain is not None:
        return plain.group(1)
    raise PowerQueryMScriptError(
        "A grouped column aggregation must reference one field, such as [Revenue]."
    )


def _validate_dynamic_pivot_values(
    value: str,
    previous_name: str,
    attribute_column: str,
) -> None:
    distinct_call = _CALL.fullmatch(value.strip())
    if distinct_call is None or distinct_call.group(1) != "List.Distinct":
        raise PowerQueryMScriptError(
            "Table.Pivot must derive its category list from the current table with "
            "List.Distinct(Table.Column(step, attribute))."
        )
    distinct_args = _split_top_level(distinct_call.group(2), ",")
    if len(distinct_args) != 1:
        raise PowerQueryMScriptError("The Table.Pivot category expression is not supported.")
    column_call = _CALL.fullmatch(distinct_args[0].strip())
    if column_call is None or column_call.group(1) != "Table.Column":
        raise PowerQueryMScriptError("The Table.Pivot category expression is not supported.")
    column_args = _split_top_level(column_call.group(2), ",")
    if len(column_args) != 2:
        raise PowerQueryMScriptError("Table.Column needs a step and one column name here.")
    table_name = _parse_name(column_args[0])
    column_name = _parse_string(column_args[1])
    if table_name.casefold() != previous_name.casefold() or column_name != attribute_column:
        raise PowerQueryMScriptError(
            "Table.Pivot category values must come from the current step's attribute column."
        )


def _m_group_aggregation(aggregate: dict[str, str]) -> str:
    operation = aggregate["operation"]
    if operation == "count_rows":
        return "each Table.RowCount(_)"
    if operation == "count_distinct_rows":
        return "each Table.RowCount(Table.Distinct(_))"
    column = _m_field(aggregate["column"])
    if operation == "count_distinct_values":
        return f"each List.Count(List.Distinct({column}))"
    functions = {
        "sum": "List.Sum",
        "average": "List.Average",
        "median": "List.Median",
        "min": "List.Min",
        "max": "List.Max",
    }
    function = functions.get(operation)
    if function is None:
        raise PowerQueryMScriptError(
            f"Group aggregation {operation!r} cannot be represented as M."
        )
    return f"each {function}({column})"


def _parse_string_list(value: str) -> list[str]:
    items = _parse_braced_items(value)
    if not items:
        raise PowerQueryMScriptError("A column list must contain at least one column name.")
    return [_parse_string(item) for item in items]


def _parse_rename_pairs(value: str) -> list[tuple[str, str]]:
    pairs = []
    for item in _parse_braced_items(value):
        parts = _parse_braced_items(item)
        if len(parts) != 2:
            raise PowerQueryMScriptError("Each rename entry must contain two text values.")
        pairs.append((_parse_string(parts[0]), _parse_string(parts[1])))
    if not pairs:
        raise PowerQueryMScriptError("This operation needs at least one rename pair.")
    return pairs


def _parse_sort_criteria(value: str) -> list[dict[str, str]]:
    sorts = []
    for item in _parse_braced_items(value):
        if item.strip().startswith("{"):
            parts = _parse_braced_items(item)
            if len(parts) not in {1, 2}:
                raise PowerQueryMScriptError(
                    "A sort criterion must contain a column and optional Order.Ascending or Order.Descending."
                )
            column = _parse_string(parts[0])
            if len(parts) == 1:
                direction = "asc"
            elif parts[1].strip() == "Order.Ascending":
                direction = "asc"
            elif parts[1].strip() == "Order.Descending":
                direction = "desc"
            else:
                raise PowerQueryMScriptError(
                    "Sort order must be Order.Ascending or Order.Descending."
                )
        else:
            column = _parse_string(item)
            direction = "asc"
        sorts.append({"column": column, "direction": direction})
    if not sorts:
        raise PowerQueryMScriptError("A sort needs at least one column criterion.")
    return sorts


def _parse_typed_columns(value: str) -> list[tuple[str, str]]:
    result = []
    for item in _parse_braced_items(value):
        parts = _parse_braced_items(item)
        if len(parts) != 2:
            raise PowerQueryMScriptError("Each type entry must contain a column name and type.")
        result.append((_parse_string(parts[0]), parts[1].strip()))
    if not result:
        raise PowerQueryMScriptError("Choose at least one column to change type.")
    return result


def _parse_transform_list(value: str) -> list[tuple[str, ...]]:
    result = []
    for item in _parse_braced_items(value):
        parts = _parse_braced_items(item)
        if len(parts) not in {2, 3}:
            raise PowerQueryMScriptError("Each transform entry needs a column and function.")
        expression = parts[1].strip()
        if not expression:
            raise PowerQueryMScriptError("A column transform needs a function expression.")
        result.append((_parse_string(parts[0]), expression, *(parts[2:])))
    if not result:
        raise PowerQueryMScriptError("Choose at least one column transform.")
    return result


def _parse_text_splitter(value: str) -> tuple[str, str]:
    """Parse only literal, quote-insensitive delimiter splitters."""
    match = _CALL.fullmatch(value.strip())
    if match is None:
        raise PowerQueryMScriptError("The split function is outside the supported local subset.")
    arguments = _split_top_level(match.group(2), ",")
    if match.group(1) == "Splitter.SplitTextByEachDelimiter":
        if len(arguments) != 2 or arguments[1].strip() != "QuoteStyle.None":
            raise PowerQueryMScriptError(
                "A first-delimiter split must use QuoteStyle.None and one literal delimiter."
            )
        delimiters = _parse_string_list(arguments[0])
        if len(delimiters) != 1:
            raise PowerQueryMScriptError(
                "A first-delimiter split must list exactly one delimiter."
            )
        return "first", delimiters[0]
    if match.group(1) == "Splitter.SplitTextByDelimiter":
        if len(arguments) != 2 or arguments[1].strip() != "QuoteStyle.None":
            raise PowerQueryMScriptError(
                "A delimiter split must use QuoteStyle.None to match the local text engine."
            )
        return "all", _parse_string(arguments[0])
    raise PowerQueryMScriptError(f"Unsupported split function {match.group(1)!r}.")


def _parse_split_column(arguments: list[str], previous_name: str) -> dict[str, Any]:
    if len(arguments) != 4:
        raise PowerQueryMScriptError(
            "Table.SplitColumn supports only literal split shapes with an explicit blank default."
        )
    column = _parse_string(arguments[0])
    splitter_match = _CALL.fullmatch(arguments[1].strip())
    if splitter_match is not None and splitter_match.group(1) == "Splitter.SplitTextByPositions":
        splitter_arguments = _split_top_level(splitter_match.group(2), ",")
        if len(splitter_arguments) != 1:
            raise PowerQueryMScriptError(
                "Positional splitting supports only the default start-from-beginning form."
            )
        positions = [
            _parse_nonnegative_integer(item)
            for item in _parse_braced_items(splitter_arguments[0])
        ]
        names = _parse_string_list(arguments[2])
        expected_names = [
            f"{column}.{index}" for index in range(1, len(positions) + 1)
        ]
        if names != expected_names:
            raise PowerQueryMScriptError(
                "A positional split must use the local numbered output column names."
            )
        if _parse_string(arguments[3]) != "":
            raise PowerQueryMScriptError(
                "A positional split must use an empty-text default to match the local table model."
            )
        step = {"op": "split_column_by_positions", "column": column, "positions": positions}
        try:
            return validate_steps([step])[0]
        except TransformationError as exc:
            raise PowerQueryMScriptError(str(exc)) from exc
    split_kind, delimiter = _parse_text_splitter(arguments[1])
    if _parse_string(arguments[3]) != "":
        raise PowerQueryMScriptError(
            "Table.SplitColumn must use an empty-text default to match the local table model."
        )
    if split_kind == "first":
        names = _parse_string_list(arguments[2])
        expected = [f"{column}.1", f"{column}.2"]
        if names != expected:
            raise PowerQueryMScriptError(
                "A first-delimiter split must name exactly the local .1 and .2 output columns."
            )
        return {"op": "split_column", "column": column, "delimiter": delimiter}
    expected_count = _m_dynamic_split_count(_m_name_reference(previous_name), column, delimiter)
    if _compact_m_whitespace(expected_count) != _compact_m_whitespace(arguments[2]):
        raise PowerQueryMScriptError(
            "Splitting every delimiter must derive its output width from the current table."
        )
    return {
        "op": "split_column_by_each_delimiter",
        "column": column,
        "delimiter": delimiter,
    }


def _m_dynamic_split_count(previous_name: str, column: str, delimiter: str) -> str:
    return (
        "List.Max({2} & List.Transform("
        f"Table.Column({previous_name}, {_m_string(column)}), "
        "each List.Count(Text.Split(if _ = null then \"\" else _, "
        f"{_m_string(delimiter)}))))"
    )


def _m_name_reference(name: str) -> str:
    return name if _IDENTIFIER.fullmatch(name) else _m_quoted_name(name)


def _parse_split_to_rows(
    table_expression: str, previous_name: str, column: str
) -> dict[str, Any]:
    transformed_call = _CALL.fullmatch(table_expression.strip())
    if transformed_call is None or transformed_call.group(1) != "Table.TransformColumns":
        raise PowerQueryMScriptError(
            "Table.ExpandListColumn is supported only over the local Text.Split pattern."
        )
    arguments = _split_top_level(transformed_call.group(2), ",")
    if len(arguments) != 2 or _parse_name(arguments[0]).casefold() != previous_name.casefold():
        raise PowerQueryMScriptError(
            "The list expansion must transform the preceding step before expanding it."
        )
    transforms = _parse_transform_list(arguments[1])
    if len(transforms) != 1 or len(transforms[0]) != 2:
        raise PowerQueryMScriptError(
            "The local row split accepts one column transformed by Text.Split."
        )
    transformed_column, expression = transforms[0]
    if transformed_column != column:
        raise PowerQueryMScriptError(
            "The expanded column must be the same column transformed by Text.Split."
        )
    expression_match = re.fullmatch(r"each\s+(.+)", expression, re.DOTALL)
    call = _CALL.fullmatch(expression_match.group(1).strip()) if expression_match else None
    if call is None or call.group(1) != "Text.Split":
        raise PowerQueryMScriptError(
            "Table.ExpandListColumn is supported only over each Text.Split(_, delimiter)."
        )
    split_arguments = _split_top_level(call.group(2), ",")
    if len(split_arguments) != 2 or _compact_m_whitespace(split_arguments[0]) != 'if_=nullthen""else_':
        raise PowerQueryMScriptError(
            'Text.Split must coalesce a null cell to "" before splitting.'
        )
    return {
        "op": "split_column_to_rows",
        "column": column,
        "delimiter": _parse_string(split_arguments[1]),
    }


def _parse_delimiter_transform(
    column: str, expression: str, type_arguments: tuple[str, ...]
) -> dict[str, Any]:
    if type_arguments and _parse_type(type_arguments[0]) != "text":
        raise PowerQueryMScriptError(
            "Delimiter extraction returns text; a non-text output type declaration cannot be preserved."
        )
    each_match = re.fullmatch(r"each\s+(.+)", expression, re.DOTALL)
    if each_match is None:
        raise PowerQueryMScriptError(
            f"Unsupported Table.TransformColumns function {expression!r}."
        )
    conditional = each_match.group(1).strip()
    if not conditional.startswith("if "):
        raise PowerQueryMScriptError(
            "Delimiter extraction must normalize null and empty cells to empty text."
        )
    then_at = _find_keyword(conditional, "then")
    else_at = _find_keyword(conditional, "else")
    if then_at < 0 or else_at < then_at:
        raise PowerQueryMScriptError("The empty-text guard must include then and else branches.")
    condition = conditional[3:then_at].strip()
    empty_branch = conditional[then_at + len("then"):else_at].strip()
    if condition != '_ = null or _ = ""' or _parse_string(empty_branch) != "":
        raise PowerQueryMScriptError(
            "Delimiter extraction must normalize null and empty cells to empty text."
        )
    call = _CALL.fullmatch(conditional[else_at + len("else"):].strip())
    if call is None:
        raise PowerQueryMScriptError("The guarded delimiter extraction call is invalid.")
    arguments = _split_top_level(call.group(2), ",")
    if not arguments or arguments[0].strip() != "_":
        raise PowerQueryMScriptError("A delimiter extraction must operate on the current cell.")
    if call.group(1) in {"Text.BeforeDelimiter", "Text.AfterDelimiter"}:
        if len(arguments) not in {2, 3}:
            raise PowerQueryMScriptError("Text delimiter extraction accepts a delimiter and optional occurrence.")
        occurrence = _parse_nonnegative_integer(arguments[2]) if len(arguments) == 3 else 0
        return {
            "op": "extract_text_by_delimiter",
            "column": column,
            "side": "before" if call.group(1) == "Text.BeforeDelimiter" else "after",
            "delimiter": _parse_string(arguments[1]),
            "occurrence": occurrence,
        }
    if call.group(1) == "Text.BetweenDelimiters":
        if len(arguments) not in {3, 4, 5}:
            raise PowerQueryMScriptError(
                "Text.BetweenDelimiters accepts start/end delimiters and optional numeric occurrences."
            )
        return {
            "op": "extract_text_between_delimiters",
            "column": column,
            "start_delimiter": _parse_string(arguments[1]),
            "end_delimiter": _parse_string(arguments[2]),
            "start_occurrence": _parse_nonnegative_integer(arguments[3]) if len(arguments) >= 4 else 0,
            "end_occurrence": _parse_nonnegative_integer(arguments[4]) if len(arguments) == 5 else 0,
        }
    raise PowerQueryMScriptError(f"Unsupported delimiter extraction function {call.group(1)!r}.")


def _validate_m_text_inputs(
    steps: list[dict[str, Any]],
    *,
    m_script_custom_types: bool = False,
    parameter_names: set[str] | None = None,
    query_functions: list[dict[str, Any]] | None = None,
    initial_column_types: dict[str, str] | None = None,
) -> None:
    text_operations = {
        "extract_text_by_delimiter", "extract_text_between_delimiters",
        "split_column", "split_column_by_each_delimiter", "split_column_to_rows",
        "split_column_by_positions", "merge_columns", "trim_text", "clean_text",
        "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text",
        "keep_duplicates",
    }
    nontext_unpivot_values: set[str] = set()
    pivot_seen = False
    transpose_seen = False
    schema_uncertain = False
    explicitly_text_columns: set[str] = set()
    function_map = {item["name"]: item for item in (query_functions or [])}
    function_names = set(function_map)
    safe_after_transpose = {
        "keep_columns", "remove_column", "rename_column", "reorder_columns",
        "keep_top_rows", "remove_top_rows", "keep_bottom_rows", "remove_bottom_rows",
        "keep_range_rows", "remove_alternate_rows", "add_index_column", "remove_blank_rows",
    }

    def types_before(index: int) -> dict[str, str]:
        return _m_column_types_after_steps(
            steps[:index], initial_column_types
        )

    for index, step in enumerate(steps):
        op = step["op"]
        if transpose_seen and op not in safe_after_transpose:
            raise PowerQueryMScriptError(
                f"M operation {op!r} after Table.Transpose is not supported because the "
                "local text model cannot preserve M cell types or distinguish null from "
                "empty text."
            )
        text_filter_operators = {
            "contains", "does_not_contain", "begins_with",
            "does_not_begin_with", "ends_with", "does_not_end_with",
        }
        filter_text_columns = (
            [step["column"]]
            if op == "filter_rows" and step["operator"] in text_filter_operators
            else [
                clause["column"] for clause in step["clauses"]
                if clause["operator"] in text_filter_operators
            ]
            if op == "filter_rows_advanced"
            else []
        )
        filter_uses_text = bool(filter_text_columns)
        if op in text_operations or filter_uses_text:
            if pivot_seen:
                raise PowerQueryMScriptError(
                    "M text operations after Pivot are not supported: Pivot creates nullable, "
                    "data-derived columns that this local text model cannot type safely."
                )
            types = types_before(index)
            columns = (
                step["columns"]
                if op in {"merge_columns", "keep_duplicates"}
                else filter_text_columns
                if filter_uses_text
                else [step["column"]]
            )
            for column in columns:
                explicitly_text = column in explicitly_text_columns or any(
                    prefix.endswith(".*") and column.startswith(prefix[:-1])
                    for prefix in explicitly_text_columns
                )
                if schema_uncertain and not explicitly_text:
                    raise PowerQueryMScriptError(
                        f"M text operation {op!r} after a schema reshaping step requires an "
                        f"explicit text conversion for {column!r}."
                    )
                if column in nontext_unpivot_values or types.get(column, "text") != "text":
                    raise PowerQueryMScriptError(
                        f"M text operation {op!r} requires {column!r} to remain text-typed."
                    )

        if op in {"promote_headers", "demote_headers", "transpose_table"}:
            if op == "transpose_table":
                transpose_seen = True
            schema_uncertain = True
            explicitly_text_columns.clear()
            nontext_unpivot_values.clear()
        elif op == "pivot_column":
            pivot_seen = True
            schema_uncertain = True
            explicitly_text_columns.clear()
            nontext_unpivot_values.clear()
        elif op == "unpivot_columns":
            types = types_before(index)
            unpivoted_nontext = any(
                column in nontext_unpivot_values
                or types.get(column, "text") != "text"
                or (schema_uncertain and column not in explicitly_text_columns)
                for column in step["columns"]
            )
            nontext_unpivot_values.difference_update(step["columns"])
            nontext_unpivot_values.discard(step["value_name"])
            if schema_uncertain:
                explicitly_text_columns.add(step["attribute_name"])
                explicitly_text_columns.discard(step["value_name"])
            if unpivoted_nontext:
                nontext_unpivot_values.add(step["value_name"])
            elif schema_uncertain:
                explicitly_text_columns.add(step["value_name"])
        elif op == "unpivot_other_columns":
            types = types_before(index)
            retained = set(step["columns"])
            unpivoted_nontext = any(
                column not in retained and column_type != "text"
                for column, column_type in types.items()
            ) or any(column not in retained for column in nontext_unpivot_values)
            nontext_unpivot_values.intersection_update(retained)
            nontext_unpivot_values.discard(step["value_name"])
            if schema_uncertain:
                explicitly_text_columns.add(step["attribute_name"])
                explicitly_text_columns.discard(step["value_name"])
            if unpivoted_nontext:
                nontext_unpivot_values.add(step["value_name"])
        elif op == "group_by":
            previous_nontext = nontext_unpivot_values
            previous_explicit_text = explicitly_text_columns

            def is_explicit_text(column: str) -> bool:
                return column in previous_explicit_text or any(
                    prefix.endswith(".*") and column.startswith(prefix[:-1])
                    for prefix in previous_explicit_text
                )

            grouped_nontext = {
                column for column in step["columns"] if column in previous_nontext
            }
            grouped_explicit_text = {
                column for column in step["columns"] if is_explicit_text(column)
            }
            for aggregate in step["aggregations"]:
                if aggregate["operation"] not in {"min", "max"}:
                    continue
                source_column = aggregate["column"]
                output_column = aggregate["new_name"]
                if source_column in previous_nontext:
                    grouped_nontext.add(output_column)
                if is_explicit_text(source_column):
                    grouped_explicit_text.add(output_column)

            nontext_unpivot_values.clear()
            nontext_unpivot_values.update(grouped_nontext)
            explicitly_text_columns.clear()
            explicitly_text_columns.update(grouped_explicit_text)
        elif op == "rename_column" and step["column"] in nontext_unpivot_values:
            nontext_unpivot_values.discard(step["column"])
            nontext_unpivot_values.add(step["new_name"])
        elif op == "rename_column":
            if step["column"] in explicitly_text_columns:
                explicitly_text_columns.discard(step["column"])
                explicitly_text_columns.add(step["new_name"])
        elif op == "remove_column":
            nontext_unpivot_values.discard(step["column"])
            explicitly_text_columns.discard(step["column"])
        elif op == "keep_columns":
            nontext_unpivot_values.intersection_update(step["columns"])
            explicitly_text_columns.intersection_update(step["columns"])
        elif op == "duplicate_column" and step["column"] in nontext_unpivot_values:
            nontext_unpivot_values.add(step["new_name"])
        elif op == "duplicate_column" and step["column"] in explicitly_text_columns:
            explicitly_text_columns.add(step["new_name"])
        elif op in {"convert_type", "convert_type_using_locale"}:
            if canonical_column_type(step["type"]) == "text":
                nontext_unpivot_values.discard(step["column"])
                if schema_uncertain:
                    explicitly_text_columns.add(step["column"])
            else:
                nontext_unpivot_values.add(step["column"])
                explicitly_text_columns.discard(step["column"])
        elif op in {"split_column", "split_column_by_each_delimiter", "split_column_by_positions"}:
            nontext_unpivot_values.discard(step["column"])
            if schema_uncertain:
                explicitly_text_columns.discard(step["column"])
                if op == "split_column":
                    explicitly_text_columns.update({f"{step['column']}.1", f"{step['column']}.2"})
                elif op == "split_column_by_each_delimiter":
                    # Store the known-text prefix for generated, data-dependent names.
                    explicitly_text_columns.add(f"{step['column']}.*")
                else:
                    explicitly_text_columns.update(
                        f"{step['column']}.{part}"
                        for part in range(1, len(step["positions"]) + 1)
                    )
        elif op == "split_column_to_rows":
            nontext_unpivot_values.discard(step["column"])
        elif op in {"extract_text_by_delimiter", "extract_text_between_delimiters"}:
            nontext_unpivot_values.discard(step["column"])
        elif op == "merge_columns":
            nontext_unpivot_values.difference_update(step["columns"])
            explicitly_text_columns.difference_update(step["columns"])
            if schema_uncertain:
                explicitly_text_columns.add(step["new_name"])
        elif op in {"trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
            nontext_unpivot_values.discard(step["column"])
        elif op in {"add_custom_column", "conditional_column"}:
            name = step["name"]
            formula_tree = None
            if op == "add_custom_column":
                try:
                    formula_tree = compile_expression(
                        step["expression"],
                        allowed_symbols=parameter_names,
                        function_names=function_names,
                    )
                except ExpressionError as exc:
                    raise PowerQueryMScriptError(
                        f"Unsupported custom-column expression: {exc}"
                    ) from exc
            if op == "add_custom_column" and m_script_custom_types:
                types = types_before(index)
                inferred_type = _m_expression_type(
                    formula_tree,
                    types,
                    nontext_unpivot_values,
                    schema_uncertain,
                    explicitly_text_columns,
                    function_map,
                )
                output_type = step.get("output_type", "text")
                if inferred_type != output_type:
                    if inferred_type is None:
                        inferred_label = "unknown"
                    elif inferred_type == "invalid":
                        inferred_label = "invalid or incompatible"
                    else:
                        inferred_label = inferred_type.replace("_", " ")
                    raise PowerQueryMScriptError(
                        "A custom-column expression must produce "
                        f"{output_type.replace('_', ' ')}; its inferred type is "
                        f"{inferred_label}."
                    )
            if step.get("output_type", "text") == "text":
                nontext_unpivot_values.discard(name)
            else:
                nontext_unpivot_values.add(name)
            if schema_uncertain:
                if step.get("output_type", "text") == "text":
                    explicitly_text_columns.add(name)

        if op in text_operations and schema_uncertain:
            if op == "merge_columns":
                explicitly_text_columns.add(step["new_name"])
            elif op in {"split_column_to_rows", "extract_text_by_delimiter", "extract_text_between_delimiters", "trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
                explicitly_text_columns.add(step["column"])


def _m_expression_type(
    expression: tuple[Any, ...],
    column_types: dict[str, str],
    nontext_columns: set[str],
    schema_uncertain: bool,
    explicitly_text_columns: set[str],
    function_map: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Infer the expression types needed to keep M custom columns text-safe."""
    numeric_types = {"whole_number", "decimal_number", "number", "currency"}
    type_error = object()
    null_type = object()

    def has_known_type_mismatch(
        arguments: list[Any], accepted_types: set[str], nullable_positions: set[int] | None = None
    ) -> bool:
        """Reject a known incompatible argument even when a sibling is unknown."""
        nullable_positions = nullable_positions or set()
        for index, argument in enumerate(arguments):
            if argument is None:
                continue  # An unknown field type must not hide a known bad sibling.
            if argument is null_type:
                if index not in nullable_positions:
                    return True
            elif argument not in accepted_types:
                return True
        return False

    def infer(node: tuple[Any, ...]) -> Any:
        kind = node[0]
        if kind == "literal":
            value = node[1]
            if isinstance(value, str):
                return "text"
            if isinstance(value, bool):
                return "boolean"
            if isinstance(value, Decimal):
                return "decimal_number"
            if value is None:
                return null_type
            return None
        if kind == "field":
            column = node[1]
            explicitly_text = column in explicitly_text_columns or any(
                prefix.endswith(".*") and column.startswith(prefix[:-1])
                for prefix in explicitly_text_columns
            )
            if schema_uncertain and not explicitly_text:
                return None
            column_type = column_types.get(column, "text")
            if column in nontext_columns and column_type == "text":
                return None
            return column_type
        if kind == "user_call":
            definition = (function_map or {}).get(node[1])
            if definition is None or len(node[2]) != 1:
                return None
            argument_type = infer(node[2][0])
            expected_type = definition["parameter_type"]
            if argument_type not in {expected_type, None, null_type}:
                return type_error
            return definition["return_type"]
        if kind == "call":
            name, arguments = node[1], [infer(argument) for argument in node[2]]
            if type_error in arguments:
                return type_error
            if name == "Text.From":
                return null_type if arguments and arguments[0] is null_type else "text"
            if name in {"Text.Upper", "Text.Lower", "Text.Trim", "Text.Replace"}:
                nullable_positions = {0}
                if has_known_type_mismatch(arguments, {"text"}, nullable_positions):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "text"
            if name == "Text.Length":
                if has_known_type_mismatch(arguments, {"text"}, {0}):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "whole_number"
            if name in {"Text.Contains", "Text.StartsWith", "Text.EndsWith"}:
                if has_known_type_mismatch(arguments, {"text"}, {0}):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "boolean"
            if name == "Number.From":
                return null_type if arguments and arguments[0] is null_type else "decimal_number"
            if name == "Number.Abs":
                if has_known_type_mismatch(arguments, numeric_types, {0}):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "decimal_number"
            if name == "Number.Round":
                # The local evaluator has no verified meaning for an explicit null
                # precision, though M's signature permits it; keep that shape blocked.
                if has_known_type_mismatch(arguments, numeric_types, {0}):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "decimal_number"
            if name == "Date.From":
                return null_type if arguments and arguments[0] is null_type else "date"
            if name in {"Date.Year", "Date.Month", "Date.Day"}:
                if has_known_type_mismatch(arguments, {"date"}, {0}):
                    return type_error
                return null_type if arguments and arguments[0] is null_type else "whole_number"
            return None
        if kind == "if":
            condition = infer(node[1])
            when_true, when_false = infer(node[2]), infer(node[3])
            if type_error in (condition, when_true, when_false):
                return type_error
            if condition is null_type or (condition is not None and condition != "boolean"):
                return type_error
            when_true = None if when_true is null_type else when_true
            when_false = None if when_false is null_type else when_false
            return when_true if when_true == when_false else None
        if kind == "coalesce":
            left, right = infer(node[1]), infer(node[2])
            if type_error in (left, right):
                return type_error
            left = None if left is null_type else left
            right = None if right is null_type else right
            return left if left == right else None
        if kind == "unary":
            operator, operand = node[1], infer(node[2])
            if operand is type_error:
                return type_error
            if operator == "not":
                if operand is None or operand is null_type:
                    return None
                return "boolean" if operand == "boolean" else type_error
            if operand is None or operand is null_type:
                return None
            return operand if operand in numeric_types else type_error
        if kind == "binary":
            operator, left, right = node[1], infer(node[2]), infer(node[3])
            if type_error in (left, right):
                return type_error
            left = None if left is null_type else left
            right = None if right is null_type else right
            if operator == "&":
                if left is None or right is None:
                    return None
                return "text" if left == right == "text" else type_error
            if operator in {"and", "or"}:
                if left is None or right is None:
                    return None
                return "boolean" if left == right == "boolean" else type_error
            if operator in {"=", "<>", "<", "<=", ">", ">="}:
                if left is None or right is None:
                    return None
                if left != right and not (left in numeric_types and right in numeric_types):
                    return type_error
                return "boolean"
            if operator in {"+", "-", "*", "/"}:
                if left is None or right is None:
                    return None
                return "decimal_number" if left in numeric_types and right in numeric_types else type_error
        return None

    result = infer(expression)
    # A definite null is an empty cell in the local normalized-text model.
    if result is null_type:
        return "text"
    if result is type_error:
        return "invalid"
    return result


def _parse_braced_items(value: str) -> list[str]:
    text = value.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise PowerQueryMScriptError("Expected an M list enclosed in braces.")
    inner = text[1:-1].strip()
    return [] if not inner else [part.strip() for part in _split_top_level(inner, ",")]


def _parse_each_expression(value: str) -> str:
    match = re.match(r"each\s+(.+)\Z", value.strip(), re.IGNORECASE | re.DOTALL)
    if match is None:
        raise PowerQueryMScriptError("A row expression must start with each.")
    return match.group(1).strip()


def _parse_each(
    value: str,
    *,
    parameter_names: set[str] | None = None,
    function_names: set[str] | None = None,
) -> str:
    expression = _decode_m_expression_literals(_parse_each_expression(value))
    try:
        compile_expression(
            expression,
            allowed_symbols=parameter_names,
            function_names=function_names,
        )
    except ExpressionError as exc:
        raise PowerQueryMScriptError(f"Unsupported each expression: {exc}") from exc
    return expression


def _decode_m_expression_literals(expression: str) -> str:
    """Decode M string and quoted-field escapes before using the local expression parser."""
    result: list[str] = []
    index = 0
    while index < len(expression):
        if expression.startswith('[#"', index):
            cursor = index + 3
            while cursor < len(expression):
                if expression[cursor] == '"':
                    if expression.startswith('""', cursor):
                        cursor += 2
                        continue
                    if expression.startswith('"]', cursor):
                        raw_name = expression[index + 1:cursor + 1]
                        name = _parse_quoted(raw_name, prefix="#")
                        result.append('[#"' + name.replace('"', '""') + '"]')
                        index = cursor + 2
                        break
                    raise PowerQueryMScriptError("Invalid quoted M column reference in an expression.")
                cursor += 1
            else:
                raise PowerQueryMScriptError("Unclosed quoted M column reference in an expression.")
            continue
        if expression[index] != '"':
            result.append(expression[index])
            index += 1
            continue

        cursor = index + 1
        while cursor < len(expression):
            if expression[cursor] == '"':
                if expression.startswith('""', cursor):
                    cursor += 2
                    continue
                decoded = _parse_string(expression[index:cursor + 1])
                result.append('"' + decoded.replace('"', '""') + '"')
                index = cursor + 1
                break
            cursor += 1
        else:
            raise PowerQueryMScriptError("Unclosed M text literal in an expression.")
    return "".join(result)


def _compact_m_whitespace(value: str) -> str:
    """Ignore formatting whitespace without changing quoted M string values."""
    compact: list[str] = []
    in_string = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == '"':
            compact.append(character)
            if in_string and index + 1 < len(value) and value[index + 1] == '"':
                compact.append('"')
                index += 2
                continue
            in_string = not in_string
        elif in_string or not character.isspace():
            compact.append(character)
        index += 1
    return "".join(compact)


def _parse_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized == "currency.type":
        raise PowerQueryMScriptError(
            "Currency.Type is not supported by the local M subset because its fixed-decimal "
            "rounding and range semantics differ from a regular number."
        )
    types = {
        "type text": "text", "type number": "decimal_number",
        "type logical": "boolean", "type date": "date",
        "type datetime": "datetime", "type time": "time",
        "int64.type": "whole_number",
        "type decimal": "decimal_number",
    }
    if normalized not in types:
        raise PowerQueryMScriptError(f"Unsupported M column type {value!r}.")
    return types[normalized]


def _m_type(value: str) -> str:
    return {
        "text": "type text", "whole_number": "Int64.Type",
        "decimal_number": "type number", "number": "type number",
        "boolean": "type logical", "date": "type date",
        "datetime": "type datetime", "time": "type time",
    }[value]


def _parse_nonnegative_integer(value: str) -> int:
    parsed = _parse_nonnegative_or_signed_integer(value)
    if parsed < 0:
        raise PowerQueryMScriptError("A row count must be zero or greater.")
    return parsed


def _parse_nonnegative_or_signed_integer(value: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise PowerQueryMScriptError("Expected a whole-number argument.") from exc
    if abs(parsed) > 2**63 - 1:
        raise PowerQueryMScriptError("Whole-number arguments must fit in a signed 64-bit integer.")
    return parsed


def _expect_count(function: str, arguments: list[str], count: int) -> None:
    if len(arguments) != count:
        raise PowerQueryMScriptError(f"{function} needs {count} argument(s) after the input table.")


def _parse_name(value: str) -> str:
    text = value.strip()
    if _IDENTIFIER.fullmatch(text):
        return text
    return _parse_quoted(text, prefix="#")


def _parse_query_reference(value: str) -> str:
    return _parse_quoted(value.strip(), prefix="#")


def _validate_append_source_names(names: list[str]) -> list[str]:
    if not isinstance(names, list) or len(names) != 2:
        raise PowerQueryMScriptError(
            "The local Table.Combine source needs exactly two query references."
        )
    result: list[str] = []
    for name in names:
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 120
            or any(ord(character) < 32 for character in name)
        ):
            raise PowerQueryMScriptError(
                "Append source references must be valid query names."
            )
        result.append(name.strip())
    if result[0].casefold() == result[1].casefold():
        raise PowerQueryMScriptError(
            "An Append query must reference two distinct queries."
        )
    return result


def _parse_table_combine_source(value: str) -> list[str]:
    match = _CALL.fullmatch(value.strip())
    if match is None or match.group(1) != "Table.Combine":
        raise PowerQueryMScriptError(
            "An Append query source must use Table.Combine with two query references."
        )
    arguments = _split_top_level(match.group(2), ",")
    _expect_count("Table.Combine", arguments, 1)
    sources = [
        _parse_query_reference(item)
        for item in _parse_braced_items(arguments[0])
    ]
    return _validate_append_source_names(sources)


def _parse_string(value: str) -> str:
    return _parse_quoted(value.strip(), prefix="")


def _parse_quoted(value: str, prefix: str) -> str:
    text = value.strip()
    start = len(prefix)
    if not text.startswith(prefix + '"') or not text.endswith('"'):
        raise PowerQueryMScriptError(f"Expected a quoted M name or text value, got {value!r}.")
    content = text[start + 1:-1]
    result: list[str] = []
    index = 0
    while index < len(content):
        if content.startswith("#(", index):
            close = content.find(")", index + 2)
            if close < 0:
                raise PowerQueryMScriptError("An M character escape is missing its closing parenthesis.")
            sequence = content[index + 2:close]
            for escaped in sequence.split(","):
                token = escaped.casefold()
                if token in {"cr", "lf", "tab"}:
                    result.append({"cr": "\r", "lf": "\n", "tab": "\t"}[token])
                elif token == "#":
                    result.append("#")
                elif re.fullmatch(r"(?:[0-9A-Fa-f]{4}|[0-9A-Fa-f]{8})", escaped):
                    codepoint = int(escaped, 16)
                    if 0xD800 <= codepoint <= 0xDFFF:
                        raise PowerQueryMScriptError("An M character escape cannot encode a surrogate.")
                    try:
                        result.append(chr(codepoint))
                    except ValueError as exc:
                        raise PowerQueryMScriptError("An M character escape is outside Unicode.") from exc
                else:
                    raise PowerQueryMScriptError(f"Unsupported M character escape {escaped!r}.")
            index = close + 1
            continue
        if content[index] == '"':
            if index + 1 < len(content) and content[index + 1] == '"':
                result.append('"')
                index += 2
                continue
            raise PowerQueryMScriptError("M text values escape quotes by doubling them.")
        if content[index] == "#" and index + 1 < len(content) and content[index + 1] == "(":
            raise PowerQueryMScriptError("M text escape could not be parsed.")
        if unicodedata.category(content[index]).startswith("C") or unicodedata.category(content[index]) in {"Zl", "Zp"}:
            raise PowerQueryMScriptError(
                "Non-graphic characters in M text must use character escape sequences."
            )
        result.append(content[index])
        index += 1
    return "".join(result)


def _strip_line_comments(value: str) -> str:
    result: list[str] = []
    quoted = False
    index = 0
    while index < len(value):
        char = value[index]
        if char == '"':
            result.append(char)
            if quoted and index + 1 < len(value) and value[index + 1] == '"':
                result.append('"')
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted and value.startswith("//", index):
            end = value.find("\n", index)
            if end < 0:
                break
            result.append("\n")
            index = end + 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _mask_line_comments(value: str) -> str:
    """Replace line-comment characters with spaces without changing offsets."""
    result = list(value)
    quoted = False
    in_comment = False
    index = 0
    while index < len(value):
        char = value[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            else:
                result[index] = " "
            index += 1
            continue
        if char == '"':
            if quoted and index + 1 < len(value) and value[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted and value.startswith("//", index):
            result[index] = result[index + 1] = " "
            in_comment = True
            index += 2
            continue
        index += 1
    return "".join(result)


def _find_keyword(value: str, keyword: str) -> int:
    for index in _top_level_positions(value, keyword=keyword):
        before = value[index - 1] if index else " "
        after_index = index + len(keyword)
        after = value[after_index] if after_index < len(value) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return index
    return -1


def _find_last_keyword(value: str, keyword: str) -> int:
    for index in reversed(_top_level_positions(value, keyword=keyword)):
        before = value[index - 1] if index else " "
        after_index = index + len(keyword)
        after = value[after_index] if after_index < len(value) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return index
    return -1


def _find_top_level_character(value: str, target: str) -> int:
    for index in _top_level_positions(value, character=target):
        return index
    return -1


def _split_top_level(value: str, separator: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for index in _top_level_positions(value, character=separator):
        pieces.append(value[start:index])
        start = index + 1
    pieces.append(value[start:])
    return pieces


def _split_let_bindings(value: str) -> list[str]:
    """Split let bindings while keeping commas inside nested let expressions."""
    pieces: list[str] = []
    start = 0
    quoted = False
    paren = brace = bracket = nested_let = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == '"':
            if quoted and index + 1 < len(value) and value[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if quoted:
            index += 1
            continue

        matched_keyword = None
        for keyword in ("let", "in"):
            if value[index:index + len(keyword)].casefold() != keyword:
                continue
            before = value[index - 1] if index else " "
            after_index = index + len(keyword)
            after = value[after_index] if after_index < len(value) else " "
            if (before.isalnum() or before == "_") or (after.isalnum() or after == "_"):
                continue
            matched_keyword = keyword
            break
        if matched_keyword == "let":
            nested_let += 1
            index += 3
            continue
        if matched_keyword == "in" and nested_let:
            nested_let -= 1
            index += 2
            continue

        if character == "(" and not quoted:
            paren += 1
        elif character == ")" and not quoted:
            paren -= 1
        elif character == "{" and not quoted:
            brace += 1
        elif character == "}" and not quoted:
            brace -= 1
        elif character == "[" and not quoted:
            bracket += 1
        elif character == "]" and not quoted:
            bracket -= 1
        elif (
            character == "," and paren == brace == bracket == nested_let == 0
        ):
            pieces.append(value[start:index])
            start = index + 1
        index += 1
    pieces.append(value[start:])
    return pieces


def _top_level_positions(
    value: str,
    *,
    character: str | None = None,
    keyword: str | None = None,
) -> list[int]:
    positions: list[int] = []
    quoted = False
    paren = brace = bracket = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == '"':
            if quoted and index + 1 < len(value) and value[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            if paren == brace == bracket == 0:
                if character is not None and char == character:
                    positions.append(index)
                elif keyword is not None and value[index:index + len(keyword)].casefold() == keyword:
                    positions.append(index)
            if char == "(":
                paren += 1
            elif char == ")":
                paren -= 1
            elif char == "{":
                brace += 1
            elif char == "}":
                brace -= 1
            elif char == "[":
                bracket += 1
            elif char == "]":
                bracket -= 1
        index += 1
    return positions


def _m_string(value: str) -> str:
    escaped: list[str] = []
    text = str(value)
    for index, character in enumerate(text):
        if character == '"':
            escaped.append('""')
        elif character == "#" and index + 1 < len(text) and text[index + 1] == "(":
            escaped.append("#(#)")
        elif character == "\r":
            escaped.append("#(cr)")
        elif character == "\n":
            escaped.append("#(lf)")
        elif character == "\t":
            escaped.append("#(tab)")
        elif unicodedata.category(character).startswith("C") or unicodedata.category(character) in {"Zl", "Zp"}:
            codepoint = ord(character)
            digits = f"{codepoint:04X}" if codepoint <= 0xFFFF else f"{codepoint:08X}"
            escaped.append(f"#({digits})")
        else:
            escaped.append(character)
    return '"' + "".join(escaped) + '"'


def _m_quoted_name(value: str) -> str:
    return "#" + _m_string(value)


def _m_reference(value: str) -> str:
    return value if _IDENTIFIER.fullmatch(value) else _m_quoted_name(value)


def _m_string_list(values: list[str]) -> str:
    return "{" + ", ".join(_m_string(value) for value in values) + "}"


def _m_field(value: str) -> str:
    return "[" + _m_quoted_name(value) + "]"


class PowerQueryMEditorDialog(QDialog):
    """Edit and preview a safe linear subset of Power Query M."""

    def __init__(
        self,
        source_candidate: ImportCandidate,
        steps: list[dict[str, Any]],
        query_name: str,
        parent: QWidget | None = None,
        initial_script: str | None = None,
        parameters: dict[str, Any] | None = None,
        query_functions: list[dict[str, Any]] | None = None,
        source_query_names: list[str] | None = None,
        query_sources: list[dict[str, Any]] | None = None,
        source_column_types: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._source_candidate = source_candidate
        self._query_name = query_name
        self._source_column_types = {
            str(name): canonical_column_type(str(column_type))
            for name, column_type in (source_column_types or {}).items()
        }
        self._source_query_names = (
            _validate_append_source_names(source_query_names)
            if source_query_names is not None
            else None
        )
        self._query_sources: dict[str, dict[str, Any]] = {}
        for item in query_sources or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id", "")).strip()
            source_name = str(item.get("name", "")).strip()
            candidate = item.get("candidate")
            if (
                source_id
                and source_name
                and isinstance(candidate, ImportCandidate)
                and source_name.casefold() not in self._query_sources
            ):
                self._query_sources[source_name.casefold()] = {
                    "id": source_id,
                    "name": source_name,
                    "candidate": candidate,
                }
        from analytics_studio.query_functions import (
            QueryEvaluationContext,
            validate_query_functions,
        )
        self._query_functions = validate_query_functions(query_functions or [])
        self._parameters = QueryEvaluationContext(
            dict(parameters or {}), self._query_functions
        )
        self._parameter_names = set(self._parameters)
        self._steps: list[dict[str, Any]] | None = None
        self._candidate: ImportCandidate | None = None
        self._preview_source_candidate: ImportCandidate | None = None
        self._previewed_script: str | None = None
        self.setWindowTitle("Advanced Editor · Power Query M subset")
        self.setMinimumSize(680, 500)
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        title = QLabel("Power Query M Advanced Editor")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        note = QLabel(
            "Edit a let … in query for the current table. The bounded local subset includes "
            "Table.SelectRows, column selection/rename/reorder, delimiter extract/split/merge, "
            "Table.Group, Pivot and Unpivot, Table.Range, RemoveLastN and AlternateRows, sorting, "
            "duplicate handling, type and text transforms, custom columns, row windows, headers, "
            "index columns, and fill operations. "
            "It is not the Microsoft Mashup runtime; source connections stay managed by the project."
        )
        if self._source_query_names is not None:
            note.setText(
                note.text()
                + " This Append query starts with Table.Combine over its two saved source queries; "
                "use Home → Append Queries to change those inputs."
            )
        note.setWordWrap(True)
        note.setStyleSheet("color: #526477;")
        layout.addWidget(note)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("powerQueryMEditor")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(28)
        self.editor.setStyleSheet("font-family: monospace; font-size: 12px;")
        try:
            generated_script = steps_to_m_script(
                steps, query_name,
                parameter_names=self._parameter_names,
                query_functions=self._query_functions,
                source_query_names=self._source_query_names,
                initial_column_types=self._source_column_types,
            )
        except (PowerQueryMScriptError, TransformationError) as exc:
            raise PowerQueryMScriptError(
                f"The current applied steps cannot be represented in this M subset yet: {exc}"
            ) from exc
        if not isinstance(initial_script, str) or not m_script_matches_steps(
            initial_script, query_name, steps,
            parameter_names=self._parameter_names,
            query_functions=self._query_functions,
            source_query_names=self._source_query_names,
            initial_column_types=self._source_column_types,
        ):
            initial_script = generated_script
        self.editor.setPlainText(initial_script)
        layout.addWidget(self.editor, 2)

        self.error_label = QLabel()
        self.error_label.setObjectName("powerQueryMError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setObjectName("powerQueryMPreview")
        self.preview.setMinimumHeight(140)
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview, 1)

        footer = QHBoxLayout()
        self.preview_button = QPushButton("Preview query")
        self.preview_button.setObjectName("previewPowerQueryMButton")
        footer.addWidget(self.preview_button)
        footer.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Apply query")
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        self.preview_button.clicked.connect(self._preview_query)
        self.apply_button.clicked.connect(self._accept_query)
        self.buttons.rejected.connect(self.reject)
        self.editor.textChanged.connect(self._invalidate_preview)
        self._preview_query()

    @property
    def steps(self) -> list[dict[str, Any]] | None:
        return [dict(step) for step in self._steps] if self._steps is not None and self.result() == QDialog.DialogCode.Accepted else None

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_candidate(self) -> ImportCandidate | None:
        return (
            self._preview_source_candidate
            if self.result() == QDialog.DialogCode.Accepted
            else None
        )

    @property
    def script(self) -> str | None:
        return (
            self._previewed_script
            if self._previewed_script is not None
            and self.result() == QDialog.DialogCode.Accepted
            else None
        )

    def _invalidate_preview(self) -> None:
        """Drop the cached result as soon as the script stops matching it."""
        self._steps = None
        self._candidate = None
        self._preview_source_candidate = None
        self._previewed_script = None
        model = self.preview.model()
        if isinstance(model, ImportPreviewTableModel):
            model.set_candidate(None)
        self.apply_button.setEnabled(False)
        self.error_label.setText("Preview the current query before applying it.")
        self.error_label.setVisible(True)

    def _preview_query(self) -> None:
        script = self.editor.toPlainText()
        self._steps = None
        self._candidate = None
        self._preview_source_candidate = None
        self._previewed_script = None
        self.apply_button.setEnabled(False)
        model = self.preview.model()
        if isinstance(model, ImportPreviewTableModel):
            model.set_candidate(None)
        try:
            source_names, steps = parse_m_query_script(
                script, self._query_name,
                parameter_names=self._parameter_names,
                query_functions=self._query_functions,
                initial_column_types=self._source_column_types,
            )
            if self._source_query_names is not None:
                if source_names is None:
                    raise PowerQueryMScriptError(
                        "An Append query must keep its Table.Combine source. "
                        "Use Append Queries in the Home ribbon to change its inputs."
                    )
                if [name.casefold() for name in source_names] != [
                    name.casefold() for name in self._source_query_names
                ]:
                    raise PowerQueryMScriptError(
                        "Append source references are managed by the query session. "
                        "Use Append Queries in the Home ribbon to choose different inputs."
                    )
                try:
                    source_candidate = append_candidates([
                        self._query_sources[name.casefold()]["candidate"]
                        for name in source_names
                    ])
                except KeyError as exc:
                    missing_name = source_names[
                        next(
                            index for index, name in enumerate(source_names)
                            if name.casefold() == str(exc.args[0])
                        )
                    ]
                    raise PowerQueryMScriptError(
                        f"Append source query {missing_name!r} is not available in this session."
                    ) from exc
                except QueryError as exc:
                    raise PowerQueryMScriptError(str(exc)) from exc
            else:
                if source_names is not None:
                    raise PowerQueryMScriptError(
                        "Table.Combine is available only for a saved Append query."
                    )
                source_candidate = self._source_candidate
            candidate = apply_transformations(
                source_candidate, steps, parameters=self._parameters
            )
        except (PowerQueryMScriptError, TransformationError) as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self._steps = steps
        self._candidate = candidate
        self._preview_source_candidate = source_candidate
        self._previewed_script = script
        if isinstance(model, ImportPreviewTableModel):
            model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.apply_button.setEnabled(True)

    def _accept_query(self) -> None:
        self._preview_query()
        if (
            self._steps is None
            or self._candidate is None
            or self._previewed_script != self.editor.toPlainText()
        ):
            if not self.error_label.text():
                self.error_label.setText("Preview the current query successfully before applying it.")
                self.error_label.setVisible(True)
            return
        super().accept()


__all__ = [
    "MAX_M_SCRIPT_LENGTH",
    "PowerQueryMEditorDialog",
    "PowerQueryMScriptError",
    "m_compatibility_issues",
    "m_script_matches_steps",
    "rewrite_m_append_source_names",
    "parse_m_script",
    "parse_m_query_script",
    "steps_to_m_script",
]
