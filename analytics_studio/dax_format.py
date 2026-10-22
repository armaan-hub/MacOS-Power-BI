"""DAX FORMAT for numbers, True/False and text (en-US), matching Power BI Desktop 2.157.879.0.

Power BI follows the Visual Basic ``Format`` rules: named formats ("Currency", "Percent", "Yes/No", ...), custom patterns
with ``0 # . , % E+ E-``, quoted and backslash literals and up to three ``;`` sections, rounding half away from zero.
Compared live through ``tools/dax_battery_format.json``.
"""

from __future__ import annotations

import re
from decimal import Context, Decimal, ROUND_HALF_UP

from analytics_studio import dax_dates, dax_typed

_NAMED = {
    "general number": "general",
    "currency": "$#,##0.00;($#,##0.00)",
    "fixed": "0.00",
    "standard": "#,##0.00",
    "percent": "0.00%",
    "scientific": "0.00E+00",
}
_BOOLEAN_NAMED = {
    "yes/no": ("Yes", "No"),
    "true/false": ("True", "False"),
    "on/off": ("On", "Off"),
}
_EXACT = Context(prec=60, rounding=ROUND_HALF_UP, traps=[])


def format_value(value: object, pattern: object) -> str:
    """FORMAT(value, pattern): the value as text; blank gives an empty string."""
    if value is None:
        return ""
    fmt = "" if pattern is None else dax_typed.to_text(pattern)
    key = fmt.strip().casefold()
    if isinstance(value, bool):
        if key not in _BOOLEAN_NAMED and key:
            as_number = Decimal(-1 if value else 0)
            if dax_dates.is_date_pattern(fmt, False):
                return dax_dates.format_date(dax_dates.DaxDateTime(as_number), fmt)
            if key in _NAMED or re.search(r"[0#]", fmt):
                return format_value(as_number, pattern)  # a number pattern reads TRUE as -1
        names = _BOOLEAN_NAMED.get(key, ("True", "False"))
        return names[0] if value else names[1]
    if isinstance(value, str):
        return fmt.replace("@", value) if "@" in fmt else value
    number: Decimal = value  # type: ignore[assignment]
    if not number.is_finite():
        return dax_typed.number_to_text(number)
    if not dax_dates.is_date(number) and re.search(r"[@&<>]", fmt) and not re.search(r"[0#]", fmt) and key not in _NAMED:
        return _text_placeholders(fmt, dax_typed.number_to_text(number))
    if dax_dates.is_date(number) and (key == "" or dax_dates.is_date_pattern(fmt, True)):
        return dax_dates.format_date(number, fmt)
    if not dax_dates.is_date(number) and key and dax_dates.is_date_pattern(fmt, False):
        return dax_dates.format_date(dax_dates.DaxDateTime(number), fmt)
    if key in _BOOLEAN_NAMED:
        names = _BOOLEAN_NAMED[key]
        return names[0] if number != 0 else names[1]
    if key == "":
        return dax_typed.number_to_text(number)
    if re.search(r"[@&<>]", fmt) and not re.search(r"[0#]", fmt):
        return _text_placeholders(fmt, dax_typed.number_to_text(number))
    named = _NAMED.get(key)
    if named == "general":
        return dax_typed.number_to_text(number)
    return _custom(number, named or fmt)


def _text_placeholders(pattern: str, text: str) -> str:
    """"@" and "&" take one character of the text from the right; the left-over start goes to the first placeholder."""
    slots = [i for i, c in enumerate(pattern) if c in "@&"]
    shown = text.upper() if ">" in pattern else text.lower() if "<" in pattern else text
    if not slots:
        return shown
    taken = shown[len(shown) - len(slots):] if len(shown) >= len(slots) else shown.rjust(len(slots))
    head = shown[: max(len(shown) - len(slots), 0)]
    output = []
    fill = iter(taken)
    for i, c in enumerate(pattern):
        if c in "@&":
            output.append(head + next(fill) if i == slots[0] else next(fill))
        elif c not in "<>":
            output.append(c)
    return "".join(output)


def _split_sections(pattern: str) -> list[str]:
    sections, current, index, quoted = [], [], 0, False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            current.append(pattern[index:index + 2])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
        if char == ";" and not quoted:
            sections.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    sections.append("".join(current))
    return sections[:3]


def _tokens(section: str) -> list[tuple[str, str]]:
    """('digit', '0'|'#'), ('lit', text), ('point', '.'), ('comma', ','), ('percent', '%'), ('exp', 'E+'|'E-')."""
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(section):
        char = section[index]
        if char == '"':
            end = section.find('"', index + 1)
            end = len(section) if end < 0 else end
            tokens.append(("lit", section[index + 1:end]))
            index = end + 1
            continue
        if char == "\\" and index + 1 < len(section):
            tokens.append(("lit", section[index + 1]))
            index += 2
            continue
        if char in "eE" and index + 1 < len(section) and section[index + 1] in "+-" and any(
            kind == "digit" for kind, _ in tokens
        ):
            tokens.append(("exp", char.upper() + section[index + 1]))
            index += 2
            continue
        if char in "0#":
            tokens.append(("digit", char))
        elif char == ".":
            tokens.append(("point", "."))
        elif char == ",":
            tokens.append(("comma", ","))
        elif char == "%":
            tokens.append(("percent", "%"))
        elif char in "_*":
            index += 2  # padding / fill characters have no visible effect here
            continue
        elif char == "[" and section.find("]", index) > 0:
            index = section.find("]", index) + 1  # [Red] and other colour tags have no visible effect
            continue
        else:
            tokens.append(("lit", char))
        index += 1
    return tokens


def _custom(number: Decimal, pattern: str) -> str:
    sections = _split_sections(pattern)
    negative = number < 0
    magnitude = abs(number)
    first = _tokens(sections[0])
    rounds_to_zero = _round(_scale(magnitude, first), _fraction_places(first), first) == 0
    if negative and rounds_to_zero:
        negative = False  # a negative value that shows as zero has no sign and uses the zero section
    index = 0
    if len(sections) >= 3 and rounds_to_zero:
        index = 2
    elif len(sections) >= 2 and negative:
        index = 1
    if index == 2 and not sections[2]:
        index = 0  # an empty zero section falls back to the first one
    if index == 1 and not sections[1]:
        index = 0  # an empty negative section falls back to the first one, with its minus sign
    tokens = _tokens(sections[index]) if index else first
    if not tokens:
        return ""
    shown = Decimal(0) if index == 2 else magnitude  # the zero section always shows zero
    text = _render(_scale(shown, tokens), tokens)
    # a single section shows the minus sign itself; with several sections the negative one carries its own
    return ("-" if negative and index == 0 else "") + text


def _exp_token(tokens: list[tuple[str, str]]) -> int | None:
    for index, (kind, _) in enumerate(tokens):
        if kind == "exp":
            return index
    return None


def _fraction_places(tokens: list[tuple[str, str]]) -> int:
    exp = _exp_token(tokens)
    seen_point = False
    places = 0
    for kind, value in tokens[: exp if exp is not None else len(tokens)]:
        if kind == "point":
            seen_point = True
        elif kind == "digit" and seen_point:
            places += 1
    return places


def _scale(magnitude: Decimal, tokens: list[tuple[str, str]]) -> Decimal:
    percents = sum(1 for kind, _ in tokens if kind == "percent")
    value = magnitude * (Decimal(100) ** percents)
    # a comma right after the last integer digit placeholder (before any decimal point) divides by 1000 each
    last_digit = None
    for index, (kind, _) in enumerate(tokens):
        if kind == "point":
            break
        if kind == "digit":
            last_digit = index
    if last_digit is not None:
        index = last_digit + 1
        while index < len(tokens) and tokens[index][0] == "comma":
            value = value / Decimal(1000)
            index += 1
    return value


def _round(value: Decimal, places: int, tokens: list[tuple[str, str]]) -> Decimal:
    if _exp_token(tokens) is not None:
        return value
    return _EXACT.quantize(value, Decimal(1).scaleb(-places))


def _render(scaled: Decimal, tokens: list[tuple[str, str]]) -> str:
    exp_index = _exp_token(tokens)
    exponent_text = ""
    body = tokens
    if exp_index is not None:
        body, exponent_spec = tokens[:exp_index], tokens[exp_index:]
        scaled, exponent_text = _scientific(scaled, body, exponent_spec)
    point_index = next((i for i, (kind, _) in enumerate(body) if kind == "point"), None)
    integer_tokens = body if point_index is None else body[:point_index]
    fraction_tokens = [] if point_index is None else body[point_index + 1:]
    places = sum(1 for kind, _ in fraction_tokens if kind == "digit")
    rounded = _EXACT.quantize(scaled, Decimal(1).scaleb(-places))
    digits = f"{rounded:f}"
    whole, _, fraction = digits.partition(".")
    whole = whole.lstrip("0") or ("0" if exp_index is not None else "")
    fraction = fraction.ljust(places, "0")[:places]
    thousands = _has_thousands(integer_tokens)
    output = _render_integer(whole, integer_tokens, thousands, point_index is not None)
    if point_index is not None:
        output += "." + _render_fraction(fraction, fraction_tokens)
        # trailing "." stays, as in Visual Basic ("0.##" shows "1.")
    return output + exponent_text


def _has_thousands(tokens: list[tuple[str, str]]) -> bool:
    digit_positions = [i for i, (kind, _) in enumerate(tokens) if kind == "digit"]
    if not digit_positions:
        return False
    return any(
        kind == "comma" and digit_positions[0] < i < digit_positions[-1] for i, (kind, _) in enumerate(tokens)
    )


def _render_integer(whole: str, tokens: list[tuple[str, str]], thousands: bool, has_point: bool = False) -> str:
    placeholders = sum(1 for kind, _ in tokens if kind == "digit")
    remaining = list(whole)
    output: list[str] = []
    emitted = 0

    def emit_digit(char: str) -> None:
        nonlocal emitted
        if thousands and emitted and emitted % 3 == 0:
            output.append(",")
        output.append(char)
        emitted += 1

    first_placeholder = next((i for i, (kind, _) in enumerate(tokens) if kind == "digit"), None)
    for index in range(len(tokens) - 1, -1, -1):
        kind, value = tokens[index]
        if kind == "digit":
            if remaining:
                emit_digit(remaining.pop())
            elif value == "0":
                emit_digit("0")
            if index == first_placeholder:
                while remaining:
                    emit_digit(remaining.pop())
        elif kind == "lit":
            output.append(value)
        elif kind == "percent":
            output.append("%")
    if placeholders == 0 and has_point:
        while remaining:
            emit_digit(remaining.pop())  # ".00" still shows the whole part
    return "".join(reversed(output))


def _render_fraction(fraction: str, tokens: list[tuple[str, str]]) -> str:
    placeholder_values = [value for kind, value in tokens if kind == "digit"]
    keep = len(fraction)
    for position in range(len(placeholder_values) - 1, -1, -1):
        if placeholder_values[position] == "#" and fraction[position] == "0" and position == keep - 1:
            keep -= 1
        else:
            break
    digits = iter(fraction[:keep])
    output: list[str] = []
    placeholder_index = 0
    for kind, value in tokens:
        if kind == "digit":
            if placeholder_index < keep:
                output.append(next(digits))
            placeholder_index += 1
        elif kind == "lit":
            output.append(value)
        elif kind == "percent":
            output.append("%")
    return "".join(output)


def _scientific(
    scaled: Decimal, body: list[tuple[str, str]], spec: list[tuple[str, str]]
) -> tuple[Decimal, str]:
    point_index = next((i for i, (kind, _) in enumerate(body) if kind == "point"), None)
    integer_places = max(1, sum(1 for kind, _ in (body if point_index is None else body[:point_index]) if kind == "digit"))
    places = sum(1 for kind, _ in ([] if point_index is None else body[point_index + 1:]) if kind == "digit")
    sign_style = spec[0][1][1]
    min_digits = sum(1 for kind, value in spec[1:] if kind == "digit" and value == "0") or 1
    if scaled == 0:
        exponent, mantissa = 0, Decimal(0)
    else:
        exponent = scaled.adjusted() - (integer_places - 1)
        mantissa = scaled.scaleb(-exponent)
        rounded = _EXACT.quantize(mantissa, Decimal(1).scaleb(-places))
        if rounded >= Decimal(10) ** integer_places:
            exponent += 1
            mantissa = scaled.scaleb(-exponent)
    sign = "-" if exponent < 0 else ("+" if sign_style == "+" else "")
    return mantissa, f"E{sign}{abs(exponent):0{min_digits}d}"
