"""Power Query ``List.*`` functions and the list-related constants (Task 104, m-list-94).

Every answer is computed from the arguments with the evaluator's own equality, ordering and arithmetic. Nothing is
looked up.

Lists are lazy in Power BI: an error inside an item surfaces only when the item is read, and a list that holds such an
error answers UNREPRESENTABLE. That deferred form is produced only where the measured answers show it (predicates in
FirstN, Skip, RemoveFirstN, RemoveLastN, MaxN and MinN; a non-list item in Combine; an index outside the list in the
Insert, Remove and Replace range functions). Everywhere else an error is raised at once, which is an ERR answer.

Measured messages are copied from the spec. A case whose answer is not measured raises ``_unsupported``: an explicit
ERR, never a guessed value.

Sorting and the extreme functions order values with ``compare``: null lowest; numbers before logicals before texts
across kinds; texts by UTF-16 code unit (ordinal); other kinds only with their own kind; anything else is the ``<``
operator error.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import Callable

from . import values as V
from .canonical import number_text_of
from .text import _ALL, _FIRST, _occurrence, _text, _text_replace, _units
from .values import MError, MValue

_MAX_ITEMS = 100_000  # longer results are not computed: no measured answer that large

COUNT_MESSAGE = "The 'count' argument is out of range."
COUNT_OR_CONDITION_MESSAGE = "The 'countOrCondition' argument is out of range."
COUNT_OR_CONDITION_EXPECTED = "We expected a CountOrCondition value."
PAGE_SIZE_MESSAGE = "The 'pageSize' argument is out of range."
NOT_ENOUGH_MESSAGE = "There weren't enough elements in the enumeration to complete the operation."
TOO_MANY_MESSAGE = "There were too many elements in the enumeration to complete the operation."
PERCENTILE_MESSAGE = ("List.Percentile requires a list of dates, datetimes, datetimezones, durations, numbers "
                      "or times.")

_ORDER_RANK = {"number": 1, "logical": 2, "text": 3}
_ORDERED_KINDS = frozenset({"number", "text", "logical", "date", "time", "datetime", "datetimezone", "duration"})
_TIME_KINDS = frozenset({"date", "datetime", "datetimezone", "duration", "time"})


# ---- helpers ----------------------------------------------------------------

def _native(params: tuple, fn: Callable[..., MValue]) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _unsupported(what: str) -> MError:
    """Not a Power BI answer this engine has measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


def _raise(err: MError):
    raise err


def _deferred(err: MError) -> V.Thunk:
    """An item that raises when it is read: the list holding it answers UNREPRESENTABLE."""
    return V.Thunk(lambda: _raise(err))


def _apply(fn: MValue, *args) -> MValue:
    from .evaluator import apply_function  # local import: the evaluator imports the stdlib

    return apply_function(fn, list(args))


def _list(value: MValue) -> V.List:
    if not isinstance(value, V.List):
        raise V.convert_error(value, V.TypeValue("list"))
    return value


def _items(value: MValue) -> list:
    """The raw (possibly lazy) items of a list."""
    return list(_list(value).items)


def _values(value: MValue) -> list:
    return [V.force(item) for item in _list(value).items]


def _whole(value: MValue) -> int:
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    x = value.value
    if math.isnan(x) or math.isinf(x) or x != math.floor(x):
        raise _unsupported("List argument that is not a whole number")
    return int(x)


def _bounded(count: int) -> int:
    if count > _MAX_ITEMS:
        raise _unsupported("List result of this size")
    return count


def _logical(value: MValue) -> bool:
    if not isinstance(value, V.Logical):
        raise V.convert_error(value, V.TypeValue("logical"))
    return value.value


def _number(value: MValue) -> float:
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    return value.value


def _order(value: MValue) -> bool:
    """Order.Ascending (0) or Order.Descending (1); null means ascending."""
    if isinstance(value, V.Null):
        return False
    if isinstance(value, V.Number) and value.value in (0.0, 1.0):
        return value.value == 1.0
    raise _unsupported("sort order")


def _key(value: V.MValue):
    kind = V.kind_of(value)
    if kind == "text":
        return _units(value.value)
    if kind == "logical":
        return int(value.value)
    if kind in ("number", "date"):
        return value.value
    if kind == "datetimezone":
        return V.utc_ticks(value)
    return value.ticks  # time, datetime, duration


def compare(a: MValue, b: MValue) -> int:
    """Ordering of values for sorting and the extreme functions (see the module docstring)."""
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        if isinstance(a, V.Null) and isinstance(b, V.Null):
            return 0
        return -1 if isinstance(a, V.Null) else 1
    ka, kb = V.kind_of(a), V.kind_of(b)
    if ka == kb and ka in _ORDERED_KINDS:
        x, y = _key(a), _key(b)
        if ka == "number" and (math.isnan(x) or math.isnan(y)):  # NaN sorts below every number
            if math.isnan(x) and math.isnan(y):
                return 0
            return -1 if math.isnan(x) else 1
        return (x > y) - (x < y)
    if ka != kb and ka in _ORDER_RANK and kb in _ORDER_RANK:
        ra, rb = _ORDER_RANK[ka], _ORDER_RANK[kb]
        return (ra > rb) - (ra < rb)
    raise V.operator_error("<", a, b)


def _hash_key(value: MValue):
    """A hashable key for the kinds whose equality is value equality; None for the rest (lists, records...)."""
    if isinstance(value, V.Null):
        return ("null",)
    if isinstance(value, V.Logical):
        return ("logical", value.value)
    if isinstance(value, V.Number):
        return None if math.isnan(value.value) else ("number", value.value)
    if isinstance(value, V.Text):
        return ("text", value.value)
    if isinstance(value, V.Date):
        return ("date", value.value)
    if isinstance(value, (V.Time, V.DateTime, V.Duration)):
        return (V.kind_of(value), value.ticks)
    if isinstance(value, V.DateTimeZone):
        return ("datetimezone", V.utc_ticks(value))
    return None


def _equal_fn(criteria: MValue):
    """(same, is_default) for an equationCriteria argument: null is value equality, a two-argument function is a
    comparer whose answer 0 means equal, or a one-argument function is a key selector."""
    from .evaluator import equals

    if isinstance(criteria, V.Null):
        return equals, True
    if not isinstance(criteria, V.Function):
        raise V.convert_error(criteria, V.TypeValue("function"))
    if len(criteria.params) == 1:
        def same(a: MValue, b: MValue) -> bool:
            return equals(_apply(criteria, a), _apply(criteria, b))

        return same, False
    if len(criteria.params) != 2:
        raise _unsupported("equation criteria that is not a comparer")

    def same(a: MValue, b: MValue) -> bool:
        result = _apply(criteria, a, b)
        if not isinstance(result, V.Number) or math.isnan(result.value):
            raise _unsupported("comparer result")
        return result.value == 0.0

    return same, False


class _Index:
    """Values seen so far, found by equality: a hash for the hashable kinds, a scan for the rest."""

    def __init__(self, criteria: MValue = V.Null()):
        self.same, self.default = _equal_fn(criteria)
        self.entries: list = []  # (value, payload)
        self._hashed: dict = {}

    def find(self, value: MValue) -> int:
        """Position of the first entry equal to ``value``, or -1."""
        key = _hash_key(value) if self.default else None
        if key is not None:
            return self._hashed.get(key, -1)
        for position, (other, _) in enumerate(self.entries):
            if self.same(value, other):
                return position
        return -1

    def add(self, value: MValue, payload=None) -> int:
        position = len(self.entries)
        self.entries.append((value, payload))
        key = _hash_key(value) if self.default else None
        if key is not None:
            self._hashed.setdefault(key, position)
        return position


def _index_of(values: list, criteria: MValue = V.Null()) -> _Index:
    index = _Index(criteria)
    for value in values:
        if index.find(value) < 0:
            index.add(value)
    return index


def _sort_specs(criteria: MValue) -> list:
    """[(key selector or None, descending)] for the key-style comparisonCriteria forms."""
    if isinstance(criteria, V.Null):
        return [(None, False)]
    if isinstance(criteria, V.Number):
        return [(None, _order(criteria))]
    if isinstance(criteria, V.Function):
        if len(criteria.params) != 1:
            raise _unsupported("sort comparer")
        return [(criteria, False)]
    if isinstance(criteria, V.List):
        specs = []
        for item in criteria.items:
            pair = V.force(item)
            if not isinstance(pair, V.List) or len(pair.items) != 2:
                raise _unsupported("sort criteria")
            key = V.force(pair.items[0])
            if not isinstance(key, V.Function) or len(key.params) != 1:
                raise _unsupported("sort criteria")
            specs.append((key, _order(V.force(pair.items[1]))))
        return specs
    raise V.convert_error(criteria, V.TypeValue("function"))


def _sort(items: list, criteria: MValue) -> list:
    """The items in order; a stable sort, descending runs keep equal items in their original order."""
    if isinstance(criteria, V.Function) and len(criteria.params) == 2:
        def by_comparer(a, b) -> int:
            result = _apply(criteria, a, b)
            if not isinstance(result, V.Number) or math.isnan(result.value):
                raise _unsupported("sort comparer result")
            return (result.value > 0) - (result.value < 0)

        return sorted(items, key=cmp_to_key(by_comparer))
    specs = _sort_specs(criteria)
    order = list(range(len(items)))
    for key_fn, descending in reversed(specs):
        if key_fn is None:
            keys = [V.force(item) for item in items]
        else:
            keys = [V.force(_apply(key_fn, item)) for item in items]
        order.sort(key=cmp_to_key(lambda i, j, keys=keys: compare(keys[i], keys[j])), reverse=descending)
    return [items[i] for i in order]


def _extremes(items: list, count_or_condition: MValue, descending: bool) -> MValue:
    """MaxN / MinN: the non-null items sorted, then a count or the items while a condition holds."""
    values = [(raw, V.force(raw)) for raw in items]
    values = [pair for pair in values if not isinstance(pair[1], V.Null)]
    ordered = [raw for raw, _ in sorted(values, key=cmp_to_key(lambda p, q: compare(p[1], q[1])),
                                         reverse=descending)]
    if isinstance(count_or_condition, V.Function):
        return V.List(tuple(_take_while(ordered, count_or_condition)))
    if isinstance(count_or_condition, V.Number):
        count = _whole(count_or_condition)
        if count < 0:
            raise MError("Expression.Error", COUNT_OR_CONDITION_MESSAGE)
        return V.List(tuple(ordered[:count]))
    raise V.convert_error(count_or_condition, V.TypeValue("function"))


def _take_while(items: list, predicate: MValue) -> list:
    """The items up to the first one the predicate rejects. A predicate error is deferred into the list."""
    out: list = []
    for raw in items:
        try:
            keep = _logical(_apply(predicate, raw))
        except MError as err:
            out.append(_deferred(err))
            break
        if not keep:
            break
        out.append(raw)
    return out


def _drop_while(items: list, predicate: MValue) -> list:
    position = 0
    while position < len(items):
        try:
            drop = _logical(_apply(predicate, items[position]))
        except MError as err:
            return [_deferred(err)]
        if not drop:
            break
        position += 1
    return items[position:]


def _average(values: list) -> MValue:
    """Average as Power BI computes it: the first item plus the mean of the differences from it. Each difference is
    an operator subtraction, so the first kind that cannot be subtracted gives the operator error."""
    first = values[0]
    total = 0.0
    for value in values:
        difference = _arithmetic("-", value, first)
        if not isinstance(difference, V.Number):
            raise _unsupported("List.Average of this kind")
        total += difference.value
    if not isinstance(first, V.Number):
        raise _unsupported("List.Average of this kind")
    return V.Number(first.value + total / len(values))


def _arithmetic(op: str, a: MValue, b: MValue) -> MValue:
    from .evaluator import arithmetic  # local import: the evaluator imports the stdlib

    return arithmetic(op, a, b)


def _replace_text(value: MValue, old: MValue, new: MValue) -> MValue:
    if not isinstance(value, V.Null):
        _text(value)  # measured: a value that is not text is reported before the search and replacement texts
    return _text_replace(value, old, new)


def _replace_value(value: MValue, old: MValue, new: MValue) -> MValue:
    from .evaluator import equals

    return new if equals(value, old) else value


# ---- counting and access ----------------------------------------------------------

def _count(lst: MValue) -> MValue:
    return V.Number(float(len(_list(lst).items)))


def _non_null_count(lst: MValue) -> MValue:
    return V.Number(float(sum(1 for value in _values(lst) if not isinstance(value, V.Null))))


def _is_empty(lst: MValue) -> MValue:
    return V.Logical(len(_list(lst).items) == 0)


def _first(lst: MValue, default: MValue) -> MValue:
    items = _items(lst)
    return V.force(items[0]) if items else default


def _last(lst: MValue, default: MValue) -> MValue:
    items = _items(lst)
    return V.force(items[-1]) if items else default


def _single(lst: MValue) -> MValue:
    items = _items(lst)
    if not items:
        raise MError("Expression.Error", NOT_ENOUGH_MESSAGE)
    if len(items) > 1:
        raise MError("Expression.Error", TOO_MANY_MESSAGE)
    return V.force(items[0])


def _single_or_default(lst: MValue, default: MValue) -> MValue:
    items = _items(lst)
    if not items:
        return default
    if len(items) > 1:
        raise MError("Expression.Error", TOO_MANY_MESSAGE)
    return V.force(items[0])


def _reverse(lst: MValue) -> MValue:
    return V.List(tuple(reversed(_items(lst))))


def _positions(lst: MValue) -> MValue:
    return V.List(tuple(V.Number(float(i)) for i in range(len(_items(lst)))))


def _buffer(lst: MValue) -> MValue:
    return _list(lst)


def _remove_nulls(lst: MValue) -> MValue:
    return V.List(tuple(raw for raw in _items(lst) if not isinstance(V.force(raw), V.Null)))


def _numbers(start: MValue, count: MValue, increment: MValue) -> MValue:
    first = _number(start)
    total = _whole(count)
    if total < 0:
        raise MError("Expression.Error", COUNT_MESSAGE)
    _bounded(total)
    step = 1.0 if isinstance(increment, V.Null) else _number(increment)
    return V.List(tuple(V.Number(first + i * step) for i in range(total)))


# ---- equality and membership ------------------------------------------------------

def _distinct(lst: MValue, criteria: MValue) -> MValue:
    index = _Index(criteria)
    kept = []
    for raw in _items(lst):
        value = V.force(raw)
        if index.find(value) < 0:
            index.add(value)
            kept.append(raw)
    return V.List(tuple(kept))


def _is_distinct(lst: MValue, criteria: MValue) -> MValue:
    index = _Index(criteria)
    for value in _values(lst):
        if index.find(value) >= 0:
            return V.Logical(False)
        index.add(value)
    return V.Logical(True)


def _contains(lst: MValue, value: MValue, criteria: MValue) -> MValue:
    same, _ = _equal_fn(criteria)
    return V.Logical(any(same(item, value) for item in _values(lst)))


def _contains_all(lst: MValue, values: MValue, criteria: MValue) -> MValue:
    index = _index_of(_values(lst), criteria)
    return V.Logical(all(index.find(value) >= 0 for value in _values(values)))


def _contains_any(lst: MValue, values: MValue, criteria: MValue) -> MValue:
    index = _index_of(_values(lst), criteria)
    return V.Logical(any(index.find(value) >= 0 for value in _values(values)))


def _hits_result(hits: list, occurrence: MValue) -> MValue:
    mode = _occurrence(occurrence)
    if mode == _ALL:
        return V.List(tuple(V.Number(float(i)) for i in hits))
    if not hits:
        return V.Number(-1.0)
    return V.Number(float(hits[0] if mode == _FIRST else hits[-1]))


def _position_of(lst: MValue, value: MValue, occurrence: MValue, criteria: MValue) -> MValue:
    same, _ = _equal_fn(criteria)
    hits = [i for i, item in enumerate(_values(lst)) if same(item, value)]
    return _hits_result(hits, occurrence)


def _position_of_any(lst: MValue, values: MValue, occurrence: MValue, criteria: MValue) -> MValue:
    index = _index_of(_values(values), criteria)
    hits = [i for i, item in enumerate(_values(lst)) if index.find(item) >= 0]
    return _hits_result(hits, occurrence)


def _find_text(lst: MValue, text: MValue) -> MValue:
    if not isinstance(text, V.Text):
        raise V.convert_error(text, V.TypeValue("text"))
    needle = _units(text.value)
    hits = []
    for raw in _items(lst):
        value = V.force(raw)
        if isinstance(value, V.Text):
            haystack = value.value
        elif isinstance(value, V.Number) and math.isfinite(value.value):
            haystack = number_text_of(value)
        else:
            raise _unsupported("List.FindText over this kind of item")
        if needle in _units(haystack):
            hits.append(raw)
    return V.List(tuple(hits))


def _intersect(lists: MValue, criteria: MValue) -> MValue:
    if isinstance(criteria, V.List):  # checked first: the measured error names the first text item
        for item in criteria.items:
            value = V.force(item)
            if not isinstance(value, V.Number):
                raise V.convert_error(value, V.TypeValue("function"))
        raise _unsupported("List.Intersect with a list of criteria")
    if not isinstance(criteria, (V.Null, V.Function)):
        raise V.convert_error(criteria, V.TypeValue("function"))
    groups = [_items(group) for group in _values(lists)]
    if not groups:
        return V.List(())
    first, others = groups[0], groups[1:]
    counts = []  # per other list: how often each value occurs
    for group in others:
        index = _Index(criteria)
        for raw in group:
            value = V.force(raw)
            position = index.find(value)
            if position < 0:
                index.add(value, [1])
            else:
                index.entries[position][1][0] += 1
        counts.append(index)
    # Multiset intersection, measured: the first list's items stay in their order, and a value keeps its first k
    # occurrences where k is its smallest count over the other lists.
    seen = _Index(criteria)
    kept = []
    for raw in first:
        value = V.force(raw)
        position = seen.find(value)
        if position < 0:
            position = seen.add(value, [0])
        seen.entries[position][1][0] += 1
        number = seen.entries[position][1][0]
        keep = True
        for index in counts:
            other = index.find(value)
            if other < 0 or index.entries[other][1][0] < number:
                keep = False
                break
        if keep:
            kept.append(raw)
    return V.List(tuple(kept))


def _difference(first: MValue, second: MValue, criteria: MValue) -> MValue:
    """Each item of the second list removes the first equal item of the first list."""
    same, _ = _equal_fn(criteria)
    items = _items(first)
    for removal in _values(second):
        for position, raw in enumerate(items):
            if same(V.force(raw), removal):
                del items[position]
                break
    return V.List(tuple(items))


def _remove_items(first: MValue, second: MValue, criteria: MValue) -> MValue:
    index = _index_of(_values(second), criteria)
    return V.List(tuple(raw for raw in _items(first) if index.find(V.force(raw)) < 0))


def _replace_matching(lst: MValue, replacements: MValue, criteria: MValue) -> MValue:
    pairs = []
    for item in _values(replacements):
        if not isinstance(item, V.List) or len(item.items) != 2:
            raise _unsupported("List.ReplaceMatchingItems replacement")
        pairs.append((V.force(item.items[0]), item.items[1]))
    same, _ = _equal_fn(criteria)
    for position, (old, _) in enumerate(pairs):
        for other, _ in pairs[position + 1:]:
            if same(old, other):
                raise _unsupported("List.ReplaceMatchingItems with repeated replacements")
    out = []
    for raw in _items(lst):
        value = V.force(raw)
        replacement = raw
        for old, new in pairs:
            if same(value, old):
                replacement = new
                break
        out.append(replacement)
    return V.List(tuple(out))


def _replace_with_replacer(lst: MValue, old: MValue, new: MValue, replacer: MValue) -> MValue:
    if not isinstance(replacer, V.Function):
        raise V.convert_error(replacer, V.TypeValue("function"))
    out = []
    for raw in _items(lst):
        item = V.force(raw)
        try:
            out.append(_apply(replacer, item, old, new))
        except MError:
            out.append(item)  # measured: a replacer call that fails (wrong kind, wrong arity, error) keeps the item
    return V.List(tuple(out))


# ---- predicates and transforms -----------------------------------------------------

def _select(lst: MValue, predicate: MValue) -> MValue:
    return V.List(tuple(raw for raw in _items(lst) if _logical(_apply(predicate, raw))))


def _transform(lst: MValue, transform: MValue) -> MValue:
    return V.List(tuple(_apply(transform, raw) for raw in _items(lst)))


def _transform_many(lst: MValue, selector: MValue, combiner: MValue) -> MValue:
    if not isinstance(combiner, V.Function):
        raise _unsupported("List.TransformMany without a result selector")
    out = []
    for raw in _items(lst):
        for inner in _items(_apply(selector, raw)):
            out.append(_apply(combiner, raw, inner))
    return V.List(tuple(out))


def _accumulate(lst: MValue, seed: MValue, accumulator: MValue) -> MValue:
    state = seed
    for raw in _items(lst):
        state = _apply(accumulator, state, raw)
    return state


def _generate(initial: MValue, condition: MValue, step: MValue, selector: MValue) -> MValue:
    state = _apply(initial)
    out: list = []
    while _logical(_apply(condition, state)):
        out.append(state if isinstance(selector, V.Null) else _apply(selector, state))
        if len(out) > _MAX_ITEMS:
            raise _unsupported("List.Generate that does not stop")
        state = _apply(step, state)
    return V.List(tuple(out))


def _all_true(lst: MValue) -> MValue:
    result = True
    for value in _values(lst):  # every item is read, so a non-logical item is always the error
        if isinstance(value, V.Null):
            continue
        if not _logical(value):
            result = False
    return V.Logical(result)


def _any_true(lst: MValue) -> MValue:
    result = False
    for value in _values(lst):
        if isinstance(value, V.Null):
            continue
        if _logical(value):
            result = True
    return V.Logical(result)


def _matches_all(lst: MValue, predicate: MValue) -> MValue:
    result = True
    for raw in _items(lst):
        if not _logical(_apply(predicate, raw)):
            result = False
    return V.Logical(result)


def _matches_any(lst: MValue, predicate: MValue) -> MValue:
    result = False
    for raw in _items(lst):
        if _logical(_apply(predicate, raw)):
            result = True
    return V.Logical(result)


# ---- combining and splitting ------------------------------------------------------

def _zip(lists: MValue) -> MValue:
    sequences = [_items(group) for group in _values(lists)]
    length = max((len(sequence) for sequence in sequences), default=0)
    rows = []
    for position in range(length):
        rows.append(V.List(tuple(seq[position] if position < len(seq) else V.Null() for seq in sequences)))
    return V.List(tuple(rows))


def _combine(lists: MValue) -> MValue:
    out: list = []
    for raw in _items(lists):
        value = V.force(raw)
        if isinstance(value, V.List):
            out.extend(value.items)
        else:
            out.append(_deferred(V.convert_error(value, V.TypeValue("list"))))
    return V.List(tuple(out))


def _split(lst: MValue, page_size: MValue) -> MValue:
    size = _whole(page_size)
    if size <= 0:
        raise MError("Expression.Error", PAGE_SIZE_MESSAGE)
    items = _items(lst)
    return V.List(tuple(V.List(tuple(items[i:i + size])) for i in range(0, len(items), size)))


def _repeat(lst: MValue, count: MValue) -> MValue:
    times = _whole(count)
    if times < 0:
        raise _unsupported("List.Repeat with a negative count")
    items = _items(lst)
    _bounded(len(items) * times)
    return V.List(tuple(items * times))


def _range(lst: MValue, offset: MValue, count: MValue) -> MValue:
    items = _items(lst)
    start = _whole(offset)
    if start < 0:
        raise MError("Expression.Error", COUNT_OR_CONDITION_MESSAGE)
    if isinstance(count, V.Null):
        return V.List(tuple(items[start:]))
    length = _whole(count)
    if length < 0:
        raise MError("Expression.Error", COUNT_OR_CONDITION_MESSAGE)
    return V.List(tuple(items[start:start + length]))


def _alternate(lst: MValue, count: MValue, skip: MValue, offset: MValue) -> MValue:
    """The first ``offset`` items are kept; then ``count`` items are passed over and ``skip`` items are kept,
    repeatedly; a null ``skip`` keeps everything after the first passed-over run."""
    items = _items(lst)
    passed = _whole(count)
    kept_per_run = None if isinstance(skip, V.Null) else _whole(skip)
    start = 0 if isinstance(offset, V.Null) else _whole(offset)
    if passed < 0 or (kept_per_run is not None and kept_per_run < 0) or start < 0:
        raise _unsupported("List.Alternate with a negative argument")
    if passed == 0 and kept_per_run == 0:
        raise _unsupported("List.Alternate that keeps nothing")
    out = items[:start]
    position = start
    while position < len(items):
        position += passed
        if position >= len(items):
            break
        if kept_per_run is None:
            out.extend(items[position:])
            break
        out.extend(items[position:position + kept_per_run])
        position += kept_per_run
    return V.List(tuple(out))


def _drop_front(lst: MValue, count_or_condition: MValue) -> MValue:
    """Skip and RemoveFirstN: a null count is one item."""
    items = _items(lst)
    if isinstance(count_or_condition, V.Function):
        return V.List(tuple(_drop_while(items, count_or_condition)))
    count = 1 if isinstance(count_or_condition, V.Null) else _whole(count_or_condition)
    if count < 0:
        raise MError("Expression.Error", COUNT_OR_CONDITION_MESSAGE)
    return V.List(tuple(items[count:]))


def _first_n(lst: MValue, count_or_condition: MValue) -> MValue:
    items = _items(lst)
    if isinstance(count_or_condition, V.Function):
        return V.List(tuple(_take_while(items, count_or_condition)))
    if not isinstance(count_or_condition, V.Number):
        raise MError("Expression.Error", COUNT_OR_CONDITION_EXPECTED)
    count = _whole(count_or_condition)
    if count < 0:
        raise MError("Expression.Error", COUNT_MESSAGE)
    return V.List(tuple(items[:count]))


def _last_n(lst: MValue, count_or_condition: MValue) -> MValue:
    items = _items(lst)
    if isinstance(count_or_condition, V.Function):
        taken: list = []
        for raw in reversed(items):  # read from the end; a predicate error is raised at once
            if not _logical(_apply(count_or_condition, raw)):
                break
            taken.append(raw)
        return V.List(tuple(reversed(taken)))
    if not isinstance(count_or_condition, V.Number):
        raise MError("Expression.Error", COUNT_OR_CONDITION_EXPECTED)
    count = _whole(count_or_condition)
    if count < 0:
        raise MError("Expression.Error", COUNT_MESSAGE)
    return V.List(tuple(items[max(0, len(items) - count):]))


def _remove_last_n(lst: MValue, count_or_condition: MValue) -> MValue:
    items = _items(lst)
    if isinstance(count_or_condition, V.Function):
        end = len(items)
        while end > 0:
            try:
                drop = _logical(_apply(count_or_condition, items[end - 1]))
            except MError as err:
                return V.List(tuple(items[:end] + [_deferred(err)]))
            if not drop:
                break
            end -= 1
        return V.List(tuple(items[:end]))
    count = 1 if isinstance(count_or_condition, V.Null) else _whole(count_or_condition)
    if count < 0:
        raise MError("Expression.Error", COUNT_OR_CONDITION_MESSAGE)
    return V.List(tuple(items[:max(0, len(items) - count)]))


def _max_n(lst: MValue, count_or_condition: MValue) -> MValue:
    return _extremes(_items(lst), count_or_condition, descending=True)


def _min_n(lst: MValue, count_or_condition: MValue) -> MValue:
    return _extremes(_items(lst), count_or_condition, descending=False)


def _range_position_error() -> MError:
    return _unsupported("list range function with an index outside the list")


def _remove_range(lst: MValue, index: MValue, count: MValue) -> MValue:
    items = _items(lst)
    start = _whole(index)
    length = 1 if isinstance(count, V.Null) else _whole(count)
    if start < 0 or length < 0:
        raise _unsupported("List.RemoveRange with a negative argument")
    if start > len(items) or start + length > len(items):
        return V.List((_deferred(_range_position_error()),))
    return V.List(tuple(items[:start] + items[start + length:]))


def _insert_range(lst: MValue, index: MValue, values: MValue) -> MValue:
    items = _items(lst)
    start = _whole(index)
    if start < 0:
        raise _unsupported("List.InsertRange with a negative index")
    if start > len(items):
        return V.List((_deferred(_range_position_error()),))
    return V.List(tuple(items[:start] + _items(values) + items[start:]))


def _replace_range(lst: MValue, index: MValue, count: MValue, replacement: MValue) -> MValue:
    items = _items(lst)
    start = _whole(index)
    length = _whole(count)
    if start < 0 or length < 0:
        raise _unsupported("List.ReplaceRange with a negative argument")
    if start > len(items) or start + length > len(items):
        return V.List((_deferred(_range_position_error()),))
    return V.List(tuple(items[:start] + _items(replacement) + items[start + length:]))


# ---- sorting and extremes ---------------------------------------------------------

def _sort_list(lst: MValue, criteria: MValue) -> MValue:
    return V.List(tuple(_sort(_items(lst), criteria)))


def _min_max(lst: MValue, default: MValue, smallest: bool) -> MValue:
    values = [value for value in _values(lst) if not isinstance(value, V.Null)]
    if not values:
        return default
    best = values[0]
    for value in values[1:]:
        order = compare(value, best)
        if (order < 0) if smallest else (order > 0):
            best = value
    return best


def _min_of(lst: MValue, default: MValue) -> MValue:
    return _min_max(lst, default, True)


def _max_of(lst: MValue, default: MValue) -> MValue:
    return _min_max(lst, default, False)


def _median(lst: MValue) -> MValue:
    values = [value for value in _values(lst) if not isinstance(value, V.Null)]
    if not values:
        return V.Null()
    ordered = sorted(values, key=cmp_to_key(compare))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return _average([ordered[middle - 1], ordered[middle]])


def _modes_with(lst: MValue, criteria: MValue) -> list:
    index = _Index(criteria)
    for value in _values(lst):
        position = index.find(value)
        if position < 0:
            index.add(value, [value, 1])
        else:
            index.entries[position][1][1] += 1
    groups = [payload for _, payload in index.entries]
    if not groups:
        return []
    best = max(group[1] for group in groups)
    return [group[0] for group in groups if group[1] == best]


def _modes_of(lst: MValue, criteria: MValue) -> MValue:
    return V.List(tuple(_modes_with(lst, criteria)))


def _mode(lst: MValue, criteria: MValue) -> MValue:
    found = _modes_with(lst, criteria)
    return found[-1] if found else V.Null()


def _product(lst: MValue) -> MValue:
    values = [value for value in _values(lst) if not isinstance(value, V.Null)]
    if not values:
        return V.Null()
    _arithmetic("*", values[0], values[0])  # the operator error for a kind that cannot be multiplied
    total = values[0]
    for value in values[1:]:
        total = _arithmetic("*", total, value)
    if not isinstance(total, V.Number):
        raise _unsupported("List.Product of this kind")
    return total


def _average_of(lst: MValue, precision: MValue) -> MValue:
    if not isinstance(precision, V.Null):
        raise _unsupported("List.Average with a precision")
    values = [value for value in _values(lst) if not isinstance(value, V.Null)]
    if not values:
        return V.Null()
    return _average(values)


def _standard_deviation(lst: MValue) -> MValue:
    values = [value for value in _values(lst) if not isinstance(value, V.Null)]
    if not values:
        return V.Null()
    _average(values)  # the operator error for a kind that cannot be subtracted
    if len(values) == 1:
        return V.Number(0.0)
    if any(not isinstance(value, V.Number) for value in values):
        raise _unsupported("List.StandardDeviation of this kind")
    # Welford's running mean and sum of squares, the order Power BI adds in (measured on 20 fresh lists)
    count = 0
    mean = 0.0
    squares = 0.0
    for value in values:
        count += 1
        step = value.value - mean
        mean += step / count
        squares += step * (value.value - mean)
    return V.Number(math.sqrt(squares / (count - 1)))


def _percentile_mode(options: MValue) -> str:
    if isinstance(options, V.Null):
        return "SqlCont"
    if not isinstance(options, V.Record) or any(name != "PercentileMode" for name in options.names()):
        raise _unsupported("List.Percentile options")
    mode = options.get("PercentileMode")
    if mode == PERCENTILE_MODES["PercentileMode.SqlCont"]:
        return "SqlCont"
    if mode == PERCENTILE_MODES["PercentileMode.ExcelExc"]:
        return "ExcelExc"
    raise _unsupported("List.Percentile mode")


def _percentile(lst: MValue, percentile: MValue, options: MValue) -> MValue:
    mode = _percentile_mode(options)
    values = []
    for value in _values(lst):
        if isinstance(value, V.Number):
            values.append(value.value)
        elif isinstance(value, V.Null) or V.kind_of(value) in _TIME_KINDS:
            raise _unsupported("List.Percentile over this kind of item")
        else:
            raise MError("Expression.Error", PERCENTILE_MESSAGE)
    if not values:
        if isinstance(percentile, V.List):
            raise _unsupported("List.Percentile of an empty list with a list of percentiles")
        return V.Null()
    ordered = sorted(values)
    count = len(ordered)

    def at(p: float) -> float:
        if not 0.0 <= p <= 1.0:
            raise _unsupported("List.Percentile outside 0 to 1")
        if mode == "SqlCont":
            position = p * (count - 1)
        else:
            position = p * (count + 1) - 1
            if position < 0 or position > count - 1:
                raise _unsupported("List.Percentile outside the ExcelExc range")
        low = math.floor(position)
        high = min(low + 1, count - 1)
        fraction = position - low
        return ordered[low] + fraction * (ordered[high] - ordered[low])

    if isinstance(percentile, V.List):
        return V.List(tuple(V.Number(at(_number(V.force(item)))) for item in percentile.items))
    return V.Number(at(_number(percentile)))


def _covariance(first: MValue, second: MValue) -> MValue:
    """Population covariance as Power BI adds it: running means (mean += (v - mean) / i) of the products and of
    each list, then mean(x*y) - mean(x) * mean(y). Nulls are dropped; the two lists are walked in step."""
    xs = [item for item in _list(first).items if not isinstance(V.force(item), V.Null)]
    ys = [item for item in _list(second).items if not isinstance(V.force(item), V.Null)]
    if not xs and not ys:
        return V.Null()
    count = 0
    mean_x = mean_y = mean_xy = 0.0
    for position in range(max(len(xs), len(ys))):
        if position >= len(xs) or position >= len(ys):
            raise MError("Expression.Error", NOT_ENOUGH_MESSAGE)
        x = V.force(xs[position])
        y = V.force(ys[position])
        for value in (x, y):
            if not isinstance(value, V.Number):
                raise V.convert_error(value, V.TypeValue("number"))
        count += 1
        mean_x += (x.value - mean_x) / count
        mean_y += (y.value - mean_y) / count
        mean_xy += (x.value * y.value - mean_xy) / count
    return V.Number(mean_xy - mean_x * mean_y)


# ---- sequences of dates, times, durations ------------------------------------------

def _series(start: MValue, count: MValue, step: MValue, kind: str) -> MValue:
    total = _whole(count)
    if total < 0:
        raise MError("Expression.Error", COUNT_MESSAGE)
    _bounded(total)
    if V.kind_of(start) != kind:
        raise V.convert_error(start, V.TypeValue(kind))
    if V.kind_of(step) != "duration":
        raise V.convert_error(step, V.TypeValue("duration"))
    if kind == "date" and step.ticks % V.TICKS_PER_DAY:
        raise _unsupported("List.Dates with a step that is not whole days")
    out = []
    for i in range(total):
        if kind == "date":
            out.append(V.make_date_from_ticks(V.date_ticks(start.value) + i * step.ticks))
        elif kind == "time":
            out.append(V.Time((start.ticks + i * step.ticks) % V.TICKS_PER_DAY))
        elif kind == "duration":
            out.append(V.make_duration(start.ticks + i * step.ticks))
        else:
            out.append(V.make_datetime(start.ticks + i * step.ticks))
    return V.List(tuple(out))


def _dates(start: MValue, count: MValue, step: MValue) -> MValue:
    return _series(start, count, step, "date")


def _times(start: MValue, count: MValue, step: MValue) -> MValue:
    return _series(start, count, step, "time")


def _durations(start: MValue, count: MValue, step: MValue) -> MValue:
    return _series(start, count, step, "duration")


def _date_times(start: MValue, count: MValue, step: MValue) -> MValue:
    return _series(start, count, step, "datetime")


def _value_is(value: MValue, type_value: MValue) -> MValue:
    if not isinstance(type_value, V.TypeValue):
        raise V.convert_error(type_value, V.TypeValue("type"))
    return V.Logical(V.is_type(value, type_value))


PERCENTILE_MODES = {
    "PercentileMode.SqlCont": V.Number(0.0),
    "PercentileMode.SqlDisc": V.Number(1.0),
    "PercentileMode.ExcelInc": V.Number(2.0),
    "PercentileMode.ExcelExc": V.Number(3.0),
}


def _union(lists: MValue, criteria: MValue) -> MValue:
    """Multiset union: each value appears as often as its largest count in any one input list, in order of first
    appearance across the inputs."""
    same_index = _Index(criteria)  # global: value -> [first raw item, largest count]
    for group in _values(lists):
        local = _Index(criteria)
        for raw in _list(group).items:
            value = V.force(raw)
            position = local.find(value)
            if position < 0:
                local.add(value, [raw, 1])
            else:
                local.entries[position][1][1] += 1
        for _, (raw, count) in local.entries:
            value = V.force(raw)
            position = same_index.find(value)
            if position < 0:
                same_index.add(value, [raw, count])
            else:
                payload = same_index.entries[position][1]
                payload[1] = max(payload[1], count)
    out: list = []
    for _, (raw, count) in same_index.entries:
        out.extend([raw] * count)
    return V.List(tuple(out))


# ---- registration -----------------------------------------------------------------

LIST_GLOBALS: dict = {
    "Order.Ascending": V.Number(0.0),
    "Order.Descending": V.Number(1.0),
    **PERCENTILE_MODES,
    "Replacer.ReplaceValue": _native((("value", False), ("old", False), ("new", False)), _replace_value),
    "Replacer.ReplaceText": _native((("value", False), ("old", False), ("new", False)), _replace_text),
    "List.Type": V.TypeValue("list"),
    "Value.Is": _native((("value", False), ("type", False)), _value_is),
    "List.Count": _native((("list", False),), _count),
    "List.NonNullCount": _native((("list", False),), _non_null_count),
    "List.IsEmpty": _native((("list", False),), _is_empty),
    "List.First": _native((("list", False), ("default", True)), _first),
    "List.Last": _native((("list", False), ("default", True)), _last),
    "List.Single": _native((("list", False),), _single),
    "List.SingleOrDefault": _native((("list", False), ("default", True)), _single_or_default),
    "List.Reverse": _native((("list", False),), _reverse),
    "List.Positions": _native((("list", False),), _positions),
    "List.Buffer": _native((("list", False),), _buffer),
    "List.RemoveNulls": _native((("list", False),), _remove_nulls),
    "List.Numbers": _native((("start", False), ("count", False), ("increment", True)), _numbers),
    "List.Union": _native((("lists", False), ("equationCriteria", True)), _union),
    "List.Distinct": _native((("list", False), ("equationCriteria", True)), _distinct),
    "List.IsDistinct": _native((("list", False), ("equationCriteria", True)), _is_distinct),
    "List.Contains": _native((("list", False), ("value", False), ("equationCriteria", True)), _contains),
    "List.ContainsAll": _native((("list", False), ("values", False), ("equationCriteria", True)), _contains_all),
    "List.ContainsAny": _native((("list", False), ("values", False), ("equationCriteria", True)), _contains_any),
    "List.PositionOf": _native((("list", False), ("value", False), ("occurrence", True),
                                ("equationCriteria", True)), _position_of),
    "List.PositionOfAny": _native((("list", False), ("values", False), ("occurrence", True),
                                   ("equationCriteria", True)), _position_of_any),
    "List.FindText": _native((("list", False), ("text", False)), _find_text),
    "List.Intersect": _native((("lists", False), ("equationCriteria", True)), _intersect),
    "List.Difference": _native((("list1", False), ("list2", False), ("equationCriteria", True)), _difference),
    "List.RemoveItems": _native((("list1", False), ("list2", False), ("equationCriteria", True)), _remove_items),
    "List.RemoveMatchingItems": _native((("list1", False), ("list2", False), ("equationCriteria", True)),
                                        _remove_items),
    "List.ReplaceMatchingItems": _native((("list", False), ("replacements", False),
                                          ("equationCriteria", True)), _replace_matching),
    "List.ReplaceValue": _native((("list", False), ("oldValue", False), ("newValue", False),
                                  ("replacer", False)), _replace_with_replacer),
    "List.Select": _native((("list", False), ("selection", False)), _select),
    "List.Transform": _native((("list", False), ("transform", False)), _transform),
    "List.TransformMany": _native((("list", False), ("collectionTransform", False),
                                   ("resultSelector", True)), _transform_many),
    "List.Accumulate": _native((("list", False), ("seed", False), ("accumulator", False)), _accumulate),
    "List.Generate": _native((("initial", False), ("condition", False), ("next", False),
                              ("selector", True)), _generate),
    "List.AllTrue": _native((("list", False),), _all_true),
    "List.AnyTrue": _native((("list", False),), _any_true),
    "List.MatchesAll": _native((("list", False), ("condition", False)), _matches_all),
    "List.MatchesAny": _native((("list", False), ("condition", False)), _matches_any),
    "List.Zip": _native((("lists", False),), _zip),
    "List.Combine": _native((("lists", False),), _combine),
    "List.Split": _native((("list", False), ("pageSize", False)), _split),
    "List.Repeat": _native((("list", False), ("count", False)), _repeat),
    "List.Range": _native((("list", False), ("offset", False), ("count", True)), _range),
    "List.Alternate": _native((("list", False), ("count", False), ("skip", True), ("offset", True)), _alternate),
    "List.Skip": _native((("list", False), ("countOrCondition", False)), _drop_front),
    "List.RemoveFirstN": _native((("list", False), ("countOrCondition", False)), _drop_front),
    "List.FirstN": _native((("list", False), ("countOrCondition", False)), _first_n),
    "List.LastN": _native((("list", False), ("countOrCondition", False)), _last_n),
    "List.RemoveLastN": _native((("list", False), ("countOrCondition", False)), _remove_last_n),
    "List.MaxN": _native((("list", False), ("countOrCondition", False)), _max_n),
    "List.MinN": _native((("list", False), ("countOrCondition", False)), _min_n),
    "List.RemoveRange": _native((("list", False), ("index", False), ("count", True)), _remove_range),
    "List.InsertRange": _native((("list", False), ("index", False), ("values", False)), _insert_range),
    "List.ReplaceRange": _native((("list", False), ("index", False), ("count", False),
                                  ("replaceWith", False)), _replace_range),
    "List.Sort": _native((("list", False), ("comparisonCriteria", True)), _sort_list),
    "List.Min": _native((("list", False), ("default", True)), _min_of),
    "List.Max": _native((("list", False), ("default", True)), _max_of),
    "List.Median": _native((("list", False),), _median),
    "List.Mode": _native((("list", False), ("equationCriteria", True)), _mode),
    "List.Modes": _native((("list", False), ("equationCriteria", True)), _modes_of),
    "List.Average": _native((("list", False), ("precision", True)), _average_of),
    "List.Product": _native((("list", False),), _product),
    "List.StandardDeviation": _native((("list", False),), _standard_deviation),
    "List.Percentile": _native((("list", False), ("percentile", False), ("options", True)), _percentile),
    "List.Covariance": _native((("list1", False), ("list2", False)), _covariance),
    "List.Dates": _native((("start", False), ("count", False), ("step", False)), _dates),
    "List.Times": _native((("start", False), ("count", False), ("step", False)), _times),
    "List.Durations": _native((("start", False), ("count", False), ("step", False)), _durations),
    "List.DateTimes": _native((("start", False), ("count", False), ("step", False)), _date_times),
}
