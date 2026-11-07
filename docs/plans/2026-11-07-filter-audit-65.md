# Task 75: filter audit (filter-audit-65)

A broad grid of 1,500 CALCULATE expressions with mixed modifiers (filters, KEEPFILTERS, ALL/REMOVEFILTERS, ALLEXCEPT, ALLNOBLANKROW, VALUES, FILTER, TREATAS, ALLSELECTED, nested CALCULATE) was probed on Power BI (scratchpad t75a). Main got 19 of them wrong. They are in the spec `tools/parity/task75_filter_audit_spec.json`:

- A: ALLNOBLANKROW(col) as a CALCULATE filter argument (13 rows). Power BI treats it as a table filter: ISFILTERED(col) is True and ISCROSSFILTERED(other columns of the table) is True. We treat it like ALL, a filter removal.
- B: FILTERS(Facts[Region]) under a FILTER(Facts, …) table filter or TREATAS (6 rows). Power BI counts the Region values that the table filter leaves, for example 1 when the filter keeps only East rows; we return all 3.

Check the rules against all 1,500 rows in pb.json, since most already match. Compute; never key on expressions. No row that matches on main may change. New test file: tests/test_iteration165_filter_audit_65.py.
