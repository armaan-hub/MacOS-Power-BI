"""Registry of scalar DAX function modules compared with Power BI Desktop 2.157.879.0.

Each module in ``MODULE_NAMES`` exposes:

* ``ARITY``: ``{"FUNCTION": (min_arguments, max_arguments)}``
* ``CATEGORY`` (optional): ``{"FUNCTION": "text" | "boolean" | "date/time"}``; anything else is numeric
* ``call(function, args)``: ``args`` are already evaluated (``None`` is BLANK, ``bool``, ``Decimal``, ``str`` or
  ``DaxDateTime``); return the DAX value, or raise ``dax_typed._error(message)`` where Power BI raises an error.
"""

from __future__ import annotations

import importlib

MODULE_NAMES = ("dax_stats", "dax_finance", "dax_bonds", "dax_misc", "dax_order")

_MODULES = [importlib.import_module(f"analytics_studio.{name}") for name in MODULE_NAMES]
ARITY: dict[str, tuple[int, int]] = {}
CATEGORY: dict[str, str] = {}
_OWNER: dict[str, object] = {}
for _module in _MODULES:
    for _function, _arity in _module.ARITY.items():
        ARITY[_function] = _arity
        _OWNER[_function] = _module
    CATEGORY.update(getattr(_module, "CATEGORY", {}))


def call(function: str, args: list[object]) -> object:
    return _OWNER[function].call(function, args)  # type: ignore[attr-defined]
