"""Signatures and one-line help for the DAX functions known to Power BI Desktop.

This is documentation only (it drives the editor's completion list and parameter hints).
Whether the local engine can *evaluate* a function is decided elsewhere, from the engine's own
function tables, so an entry here never makes a function work.

Each line is ``SIGNATURE ;; one-line help``.  Parameters in square brackets are optional and a
trailing ``…`` marks a parameter that may repeat.
"""

from __future__ import annotations

_CATALOG_TEXT = """
ABS(<number>) ;; Returns the absolute value of a number.
ACCRINT(<issue>, <first_interest>, <settlement>, <rate>, <par>, <frequency>, [<basis>], [<calc_method>]) ;; Accrued interest for a security that pays periodic interest.
ACCRINTM(<issue>, <maturity>, <rate>, <par>, [<basis>]) ;; Accrued interest for a security that pays interest at maturity.
ACOS(<number>) ;; Returns the arccosine of a number, in radians.
ACOSH(<number>) ;; Returns the inverse hyperbolic cosine of a number.
ACOT(<number>) ;; Returns the arccotangent of a number, in radians.
ACOTH(<number>) ;; Returns the inverse hyperbolic cotangent of a number.
ADDCOLUMNS(<table>, <name>, <expression>, [<name>, <expression>]…) ;; Adds calculated columns to a table.
ADDMISSINGITEMS([<showAll_columnName>]…, <table>, <groupBy_columnName>…, [<filterTable>]…) ;; Adds combinations of items that are missing from a table.
ALL([<table> | <column>], [<column>]…) ;; Returns all rows of a table or all values of a column, ignoring filters.
ALLCROSSFILTERED(<table>) ;; Clears all filters that are applied to a table, including cross filters.
ALLEXCEPT(<table>, <column>, [<column>]…) ;; Removes all filters on a table except the ones on the listed columns.
ALLNOBLANKROW(<table> | <column>, [<column>]…) ;; Returns all rows or values, ignoring filters and the blank row.
ALLSELECTED([<table> | <column>], [<column>]…) ;; Removes filters from rows and columns but keeps the filters from outside the query.
AMORDEGRC(<cost>, <date_purchased>, <first_period>, <salvage>, <period>, <rate>, [<basis>]) ;; Depreciation for each accounting period (French accounting system).
AMORLINC(<cost>, <date_purchased>, <first_period>, <salvage>, <period>, <rate>, [<basis>]) ;; Depreciation for each accounting period (French accounting system).
AND(<logical1>, <logical2>) ;; Returns TRUE when both arguments are TRUE.
APPROXIMATEDISTINCTCOUNT(<columnName>) ;; Returns an estimated count of unique values in a column.
ASIN(<number>) ;; Returns the arcsine of a number, in radians.
ASINH(<number>) ;; Returns the inverse hyperbolic sine of a number.
ATAN(<number>) ;; Returns the arctangent of a number, in radians.
ATANH(<number>) ;; Returns the inverse hyperbolic tangent of a number.
AVERAGE(<column>) ;; Returns the average of all numbers in a column.
AVERAGEA(<column>) ;; Returns the average of the values in a column, handling text and logicals.
AVERAGEX(<table>, <expression>) ;; Returns the average of an expression evaluated for each row of a table.
BETA.DIST(<x>, <alpha>, <beta>, <cumulative>, [<A>], [<B>]) ;; Returns the beta distribution.
BETA.INV(<probability>, <alpha>, <beta>, [<A>], [<B>]) ;; Returns the inverse of the beta cumulative distribution.
BITAND(<number>, <number>) ;; Returns a bitwise AND of two numbers.
BITLSHIFT(<number>, <shift_amount>) ;; Shifts a number left by the given number of bits.
BITOR(<number>, <number>) ;; Returns a bitwise OR of two numbers.
BITRSHIFT(<number>, <shift_amount>) ;; Shifts a number right by the given number of bits.
BITXOR(<number>, <number>) ;; Returns a bitwise XOR of two numbers.
BLANK() ;; Returns a blank.
CALCULATE(<expression>, [<filter1>], [<filter2>]…) ;; Evaluates an expression in a context modified by filters.
CALCULATETABLE(<table>, [<filter1>], [<filter2>]…) ;; Evaluates a table expression in a context modified by filters.
CALENDAR(<start_date>, <end_date>) ;; Returns a table with one column of consecutive dates.
CALENDARAUTO([<fiscal_year_end_month>]) ;; Returns a calendar table covering all dates in the model.
CEILING(<number>, <significance>) ;; Rounds a number up to the nearest multiple of significance.
CHISQ.DIST(<x>, <deg_freedom>, <cumulative>) ;; Returns the left-tailed chi-squared distribution.
CHISQ.DIST.RT(<x>, <deg_freedom>) ;; Returns the right-tailed chi-squared distribution.
CHISQ.INV(<probability>, <deg_freedom>) ;; Returns the inverse of the left-tailed chi-squared distribution.
CHISQ.INV.RT(<probability>, <deg_freedom>) ;; Returns the inverse of the right-tailed chi-squared distribution.
CLOSINGBALANCEMONTH(<expression>, <dates>, [<filter>]) ;; Value of the expression at the last date of the month.
CLOSINGBALANCEQUARTER(<expression>, <dates>, [<filter>]) ;; Value of the expression at the last date of the quarter.
CLOSINGBALANCEYEAR(<expression>, <dates>, [<filter>], [<year_end_date>]) ;; Value of the expression at the last date of the year.
COALESCE(<expression>, <expression>, [<expression>]…) ;; Returns the first expression that does not evaluate to blank.
COMBIN(<number>, <number_chosen>) ;; Returns the number of combinations for a number of items.
COMBINA(<number>, <number_chosen>) ;; Returns the number of combinations, with repetitions.
COMBINEVALUES(<delimiter>, <expression>, <expression>, [<expression>]…) ;; Joins two or more text strings into one with a delimiter.
CONCATENATE(<text1>, <text2>) ;; Joins two text strings into one.
CONCATENATEX(<table>, <expression>, [<delimiter>], [<orderBy_expression>], [<order>]…) ;; Concatenates the result of an expression evaluated for each row of a table.
CONFIDENCE.NORM(<alpha>, <standard_dev>, <size>) ;; Confidence interval for a population mean, normal distribution.
CONFIDENCE.T(<alpha>, <standard_dev>, <size>) ;; Confidence interval for a population mean, Student's T distribution.
CONTAINS(<table>, <columnName>, <value>, [<columnName>, <value>]…) ;; Returns TRUE if a row of the table matches all of the values.
CONTAINSROW(<table>, <value>, [<value>]…) ;; Returns TRUE if a row with the given values exists in the table.
CONTAINSSTRING(<within_text>, <find_text>) ;; Returns TRUE if one text string contains another (not case sensitive).
CONTAINSSTRINGEXACT(<within_text>, <find_text>) ;; Returns TRUE if one text string contains another (case sensitive).
CONVERT(<expression>, <datatype>) ;; Converts an expression to the given data type.
COS(<number>) ;; Returns the cosine of an angle in radians.
COSH(<number>) ;; Returns the hyperbolic cosine of a number.
COT(<number>) ;; Returns the cotangent of an angle in radians.
COTH(<number>) ;; Returns the hyperbolic cotangent of a number.
COUNT(<column>) ;; Counts the numbers in a column.
COUNTA(<column>) ;; Counts the non-blank values in a column.
COUNTAX(<table>, <expression>) ;; Counts the non-blank results of an expression over a table.
COUNTBLANK(<column>) ;; Counts the blank cells in a column.
COUNTROWS([<table>]) ;; Counts the rows in a table.
COUNTX(<table>, <expression>) ;; Counts the rows with a number result of an expression over a table.
COUPDAYBS(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Days from the beginning of the coupon period to the settlement date.
COUPDAYS(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Days in the coupon period that contains the settlement date.
COUPDAYSNC(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Days from the settlement date to the next coupon date.
COUPNCD(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Next coupon date after the settlement date.
COUPNUM(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Number of coupons payable between settlement and maturity.
COUPPCD(<settlement>, <maturity>, <frequency>, [<basis>]) ;; Previous coupon date before the settlement date.
CROSSFILTER(<columnName1>, <columnName2>, <direction>) ;; Specifies the cross-filtering direction of a relationship for a calculation.
CROSSJOIN(<table>, <table>, [<table>]…) ;; Returns the Cartesian product of the rows of two or more tables.
CUMIPMT(<rate>, <nper>, <pv>, <start_period>, <end_period>, <type>) ;; Cumulative interest paid between two periods.
CUMPRINC(<rate>, <nper>, <pv>, <start_period>, <end_period>, <type>) ;; Cumulative principal paid between two periods.
CURRENCY(<value>) ;; Evaluates the argument and returns it as a currency value.
CURRENTGROUP() ;; Returns the rows of the current group inside GROUPBY.
CUSTOMDATA() ;; Returns the CustomData property of the connection.
DATATABLE(<name>, <type>, [<name>, <type>]…, <data>) ;; Returns a table with the declared columns and data.
DATE(<year>, <month>, <day>) ;; Returns the date for the given year, month and day.
DATEADD(<dates>, <number_of_intervals>, <interval>) ;; Shifts a column of dates forward or back by a number of intervals.
DATEDIFF(<date1>, <date2>, <interval>) ;; Returns the number of intervals between two dates.
DATESBETWEEN(<dates>, <start_date>, <end_date>) ;; Returns the dates from the start date to the end date.
DATESINPERIOD(<dates>, <start_date>, <number_of_intervals>, <interval>) ;; Returns the dates in a period that starts at a date.
DATESMTD(<dates>) ;; Returns the dates of the month to date.
DATESQTD(<dates>) ;; Returns the dates of the quarter to date.
DATESWTD(<dates>, [<first_day_of_week>]) ;; Returns the dates of the week to date.
DATESYTD(<dates>, [<year_end_date>]) ;; Returns the dates of the year to date.
DATEVALUE(<date_text>) ;; Converts a date in text form to a date.
DAY(<date>) ;; Returns the day of the month, from 1 to 31.
DB(<cost>, <salvage>, <life>, <period>, [<month>]) ;; Depreciation using the fixed-declining balance method.
DDB(<cost>, <salvage>, <life>, <period>, [<factor>]) ;; Depreciation using the double-declining balance method.
DEGREES(<angle>) ;; Converts radians into degrees.
DETAILROWS(<measureName>) ;; Evaluates the detail rows expression of a measure.
DISC(<settlement>, <maturity>, <pr>, <redemption>, [<basis>]) ;; Discount rate for a security.
DISTINCT(<column> | <table>) ;; Returns the distinct values of a column or the distinct rows of a table.
DISTINCTCOUNT(<column>) ;; Counts the distinct values in a column.
DISTINCTCOUNTNOBLANK(<column>) ;; Counts the distinct values in a column, ignoring blank.
DIVIDE(<numerator>, <denominator>, [<alternateresult>]) ;; Safe division that returns the alternate result (blank) on divide by zero.
DOLLARDE(<fractional_dollar>, <fraction>) ;; Converts a fractional dollar price to a decimal.
DOLLARFR(<decimal_dollar>, <fraction>) ;; Converts a decimal dollar price to a fraction.
DURATION(<settlement>, <maturity>, <coupon>, <yld>, <frequency>, [<basis>]) ;; Macauley duration of a security with periodic interest.
EARLIER(<column>, [<number>]) ;; Returns the value of a column from an outer row context.
EARLIEST(<column>) ;; Returns the value of a column from the outermost row context.
EDATE(<start_date>, <months>) ;; Returns the date that is the given number of months before or after a date.
EFFECT(<nominal_rate>, <npery>) ;; Effective annual interest rate.
ENDOFMONTH(<dates>) ;; Returns the last date of the month in the current context.
ENDOFQUARTER(<dates>) ;; Returns the last date of the quarter in the current context.
ENDOFYEAR(<dates>, [<year_end_date>]) ;; Returns the last date of the year in the current context.
EOMONTH(<start_date>, <months>) ;; Returns the last day of the month that is the given number of months away.
ERROR(<text>) ;; Raises an error with the given message.
EVEN(<number>) ;; Rounds a number up to the nearest even integer.
EXACT(<text1>, <text2>) ;; Checks whether two text strings are exactly the same (case sensitive).
EXCEPT(<table1>, <table2>) ;; Returns the rows of the first table that do not appear in the second.
EXP(<number>) ;; Returns e raised to the power of a number.
EXPON.DIST(<x>, <lambda>, <cumulative>) ;; Returns the exponential distribution.
FACT(<number>) ;; Returns the factorial of a number.
FALSE() ;; Returns the logical value FALSE.
FILTER(<table>, <filter>) ;; Returns the rows of a table that satisfy a condition.
FILTERS(<columnName>) ;; Returns the values that are directly applied as filters to a column.
FIND(<find_text>, <within_text>, [<start_num>], [<NotFoundValue>]) ;; Position of one text string in another (case sensitive).
FIRSTDATE(<dates>) ;; Returns the first date in the current context.
FIRSTNONBLANK(<column>, <expression>) ;; Returns the first value of a column for which the expression is not blank.
FIRSTNONBLANKVALUE(<column>, <expression>) ;; Returns the expression value for the first column value that is not blank.
FIXED(<number>, [<decimals>], [<no_commas>]) ;; Rounds a number and returns it as text.
FLOOR(<number>, <significance>) ;; Rounds a number down to the nearest multiple of significance.
FORMAT(<value>, <format_string>, [<locale_name>]) ;; Converts a value to text according to a format string.
FV(<rate>, <nper>, <pmt>, [<pv>], [<type>]) ;; Future value of an investment.
GCD(<number1>, [<number2>]) ;; Returns the greatest common divisor of integers.
GENERATE(<table1>, <table2>) ;; Returns a table with the Cartesian product of each row of table1 with table2.
GENERATEALL(<table1>, <table2>) ;; Like GENERATE but keeps rows of table1 that have no match.
GENERATESERIES(<startValue>, <endValue>, [<incrementValue>]) ;; Returns a single-column table of numbers.
GEOMEAN(<column>) ;; Geometric mean of the numbers in a column.
GEOMEANX(<table>, <expression>) ;; Geometric mean of an expression evaluated for each row of a table.
GROUPBY(<table>, [<groupBy_columnName>]…, [<name>, <expression>]…) ;; Groups a table and aggregates each group with an iterator.
HASONEFILTER(<columnName>) ;; Returns TRUE when exactly one value is directly filtered on a column.
HASONEVALUE(<columnName>) ;; Returns TRUE when the context has been filtered down to one distinct value.
HOUR(<datetime>) ;; Returns the hour as a number from 0 to 23.
IF(<logical_test>, <value_if_true>, [<value_if_false>]) ;; Returns one value if a condition is TRUE and another otherwise.
IF.EAGER(<logical_test>, <value_if_true>, [<value_if_false>]) ;; Like IF but evaluates both branches eagerly.
IFERROR(<value>, <value_if_error>) ;; Returns a value if the expression is an error, otherwise the expression.
IGNORE(<expression>) ;; Omits a measure from a SUMMARIZECOLUMNS blank-row check.
INDEX(<position>, [<relation>], [<orderBy>], [<blanks>], [<partitionBy>], [<matchBy>], [<reset>]) ;; Returns a row at an absolute position within a partition.
INT(<number>) ;; Rounds a number down to the nearest integer.
INTERSECT(<table1>, <table2>) ;; Returns the rows that appear in both tables.
INTRATE(<settlement>, <maturity>, <investment>, <redemption>, [<basis>]) ;; Interest rate for a fully invested security.
IPMT(<rate>, <per>, <nper>, <pv>, [<fv>], [<type>]) ;; Interest payment for a period of an investment.
ISAFTER(<scalar_expression>, <scalar_expression>, [<sort_order>]…) ;; Compares sorted tuples; used in filters.
ISBLANK(<value>) ;; Returns TRUE if the value is blank.
ISBOOLEAN(<value>) ;; Returns TRUE if the value is a Boolean.
ISCROSSFILTERED(<columnName>) ;; Returns TRUE when the column or another column of the table is cross-filtered.
ISDATETIME(<value>) ;; Returns TRUE if the value is a date/time.
ISEMPTY(<table_expression>) ;; Returns TRUE if the table has no rows.
ISERROR(<value>) ;; Returns TRUE if the value is an error.
ISEVEN(<number>) ;; Returns TRUE if the number is even.
ISFILTERED(<columnName>) ;; Returns TRUE when the column is directly filtered.
ISINSCOPE(<columnName>) ;; Returns TRUE when the column is the level in a hierarchy of levels.
ISLOGICAL(<value>) ;; Returns TRUE if the value is a logical value.
ISNONTEXT(<value>) ;; Returns TRUE if the value is not text.
ISNUMBER(<value>) ;; Returns TRUE if the value is a number.
ISNUMERIC(<value>) ;; Returns TRUE if the value is numeric.
ISO.CEILING(<number>, [<significance>]) ;; Rounds a number up to the nearest multiple of significance.
ISODD(<number>) ;; Returns TRUE if the number is odd.
ISONORAFTER(<scalar_expression>, <scalar_expression>, [<sort_order>]…) ;; Compares sorted tuples with an inclusive boundary.
ISPMT(<rate>, <per>, <nper>, <pv>) ;; Interest paid during a period of an investment.
ISSELECTEDMEASURE(<measure>…) ;; Returns TRUE if the measure is one of those named (calculation groups).
ISSTRING(<value>) ;; Returns TRUE if the value is a string.
ISSUBTOTAL(<columnName>) ;; Returns TRUE when a row is a subtotal row.
ISTEXT(<value>) ;; Returns TRUE if the value is text.
KEEPFILTERS(<expression>) ;; Changes how filters are applied inside CALCULATE.
LASTDATE(<dates>) ;; Returns the last date in the current context.
LASTNONBLANK(<column>, <expression>) ;; Returns the last value of a column for which the expression is not blank.
LASTNONBLANKVALUE(<column>, <expression>) ;; Returns the expression value for the last column value that is not blank.
LCM(<number1>, [<number2>]) ;; Returns the least common multiple of integers.
LEFT(<text>, [<num_chars>]) ;; Returns the leftmost characters of a text string.
LEN(<text>) ;; Returns the number of characters in a text string.
LN(<number>) ;; Returns the natural logarithm of a number.
LOG(<number>, [<base>]) ;; Returns the logarithm of a number to the given base.
LOG10(<number>) ;; Returns the base-10 logarithm of a number.
LOOKUPVALUE(<result_columnName>, <search_columnName>, <search_value>, [<search_columnName>, <search_value>]…, [<alternateResult>]) ;; Returns the value in the result column for the row that matches the search values.
LOWER(<text>) ;; Converts text to lowercase.
MATCHBY(<matchBy_columnName>, [<matchBy_columnName>]…) ;; Defines the columns that identify the current row in window functions.
MAX(<column> | <scalar1>, [<scalar2>]) ;; Returns the largest value in a column or between two expressions.
MAXA(<column>) ;; Returns the largest value in a column, handling logicals and text.
MAXX(<table>, <expression>, [<variant>]) ;; Returns the largest value of an expression evaluated for each row of a table.
MDURATION(<settlement>, <maturity>, <coupon>, <yld>, <frequency>, [<basis>]) ;; Modified Macauley duration for a security.
MEDIAN(<column>) ;; Returns the median of a column.
MEDIANX(<table>, <expression>) ;; Returns the median of an expression evaluated for each row of a table.
MID(<text>, <start_num>, <num_chars>) ;; Returns characters from the middle of a text string.
MIN(<column> | <scalar1>, [<scalar2>]) ;; Returns the smallest value in a column or between two expressions.
MINA(<column>) ;; Returns the smallest value in a column, handling logicals and text.
MINUTE(<datetime>) ;; Returns the minute as a number from 0 to 59.
MINX(<table>, <expression>, [<variant>]) ;; Returns the smallest value of an expression evaluated for each row of a table.
MOD(<number>, <divisor>) ;; Returns the remainder after a number is divided by a divisor.
MONTH(<datetime>) ;; Returns the month as a number from 1 to 12.
MROUND(<number>, <multiple>) ;; Rounds a number to the desired multiple.
NATURALINNERJOIN(<leftTable>, <rightTable>) ;; Inner join of two tables using the columns they have in common.
NATURALLEFTOUTERJOIN(<leftTable>, <rightTable>) ;; Left outer join of two tables using the columns they have in common.
NETWORKDAYS(<start_date>, <end_date>, [<weekend>], [<holidays>]) ;; Number of whole working days between two dates.
NEXTDAY(<dates>) ;; Returns the dates of the day after the first date in the context.
NEXTMONTH(<dates>) ;; Returns the dates of the month after the first date in the context.
NEXTQUARTER(<dates>) ;; Returns the dates of the quarter after the first date in the context.
NEXTYEAR(<dates>, [<year_end_date>]) ;; Returns the dates of the year after the first date in the context.
NOMINAL(<effect_rate>, <npery>) ;; Nominal annual interest rate.
NONVISUAL(<expression>) ;; Marks a measure filter in SUMMARIZECOLUMNS as not affecting visual totals.
NORM.DIST(<x>, <mean>, <standard_dev>, <cumulative>) ;; Returns the normal distribution.
NORM.INV(<probability>, <mean>, <standard_dev>) ;; Returns the inverse of the normal cumulative distribution.
NORM.S.DIST(<z>, <cumulative>) ;; Returns the standard normal distribution.
NORM.S.INV(<probability>) ;; Returns the inverse of the standard normal cumulative distribution.
NOT(<logical>) ;; Changes TRUE to FALSE and FALSE to TRUE.
NOW() ;; Returns the current date and time.
NPER(<rate>, <pmt>, <pv>, [<fv>], [<type>]) ;; Number of periods for an investment.
ODD(<number>) ;; Rounds a number up to the nearest odd integer.
ODDFPRICE(<settlement>, <maturity>, <issue>, <first_coupon>, <rate>, <yld>, <redemption>, <frequency>, [<basis>]) ;; Price of a security with an odd first period.
ODDFYIELD(<settlement>, <maturity>, <issue>, <first_coupon>, <rate>, <pr>, <redemption>, <frequency>, [<basis>]) ;; Yield of a security with an odd first period.
ODDLPRICE(<settlement>, <maturity>, <last_interest>, <rate>, <yld>, <redemption>, <frequency>, [<basis>]) ;; Price of a security with an odd last period.
ODDLYIELD(<settlement>, <maturity>, <last_interest>, <rate>, <pr>, <redemption>, <frequency>, [<basis>]) ;; Yield of a security with an odd last period.
OFFSET(<delta>, [<relation>], [<orderBy>], [<blanks>], [<partitionBy>], [<matchBy>], [<reset>]) ;; Returns a row that is a number of rows before or after the current row.
OPENINGBALANCEMONTH(<expression>, <dates>, [<filter>]) ;; Value of the expression at the first date of the month.
OPENINGBALANCEQUARTER(<expression>, <dates>, [<filter>]) ;; Value of the expression at the first date of the quarter.
OPENINGBALANCEYEAR(<expression>, <dates>, [<filter>], [<year_end_date>]) ;; Value of the expression at the first date of the year.
OR(<logical1>, <logical2>) ;; Returns TRUE when either argument is TRUE.
ORDERBY(<orderBy_expression>, [<order>]…) ;; Defines the sort order inside window functions.
PARALLELPERIOD(<dates>, <number_of_intervals>, <interval>) ;; Returns a parallel period shifted by a number of intervals.
PARTITIONBY(<partitionBy_columnName>, [<partitionBy_columnName>]…) ;; Defines the partitions of window functions.
PATH(<ID_columnName>, <parent_columnName>) ;; Returns a delimited text string of the ancestors of an item.
PATHCONTAINS(<path>, <item>) ;; Returns TRUE if the item occurs in the path.
PATHITEM(<path>, <position>, [<type>]) ;; Returns the item at a position in a path.
PATHITEMREVERSE(<path>, <position>, [<type>]) ;; Returns the item at a position counted from the end of a path.
PATHLENGTH(<path>) ;; Returns the number of items in a path.
PDURATION(<rate>, <pv>, <fv>) ;; Periods required for an investment to reach a value.
PERCENTILE.EXC(<column>, <k>) ;; Returns the k-th percentile of a column, exclusive.
PERCENTILE.INC(<column>, <k>) ;; Returns the k-th percentile of a column, inclusive.
PERCENTILEX.EXC(<table>, <expression>, <k>) ;; Returns the k-th percentile of an expression over a table, exclusive.
PERCENTILEX.INC(<table>, <expression>, <k>) ;; Returns the k-th percentile of an expression over a table, inclusive.
PERMUT(<number>, <number_chosen>) ;; Returns the number of permutations.
PI() ;; Returns the value of pi.
PMT(<rate>, <nper>, <pv>, [<fv>], [<type>]) ;; Payment for a loan.
POISSON.DIST(<x>, <mean>, <cumulative>) ;; Returns the Poisson distribution.
POWER(<number>, <power>) ;; Returns a number raised to a power.
PPMT(<rate>, <per>, <nper>, <pv>, [<fv>], [<type>]) ;; Principal payment for a period of an investment.
PREVIOUSDAY(<dates>) ;; Returns the dates of the day before the first date in the context.
PREVIOUSMONTH(<dates>) ;; Returns the dates of the month before the first date in the context.
PREVIOUSQUARTER(<dates>) ;; Returns the dates of the quarter before the first date in the context.
PREVIOUSYEAR(<dates>, [<year_end_date>]) ;; Returns the dates of the year before the first date in the context.
PRICE(<settlement>, <maturity>, <rate>, <yld>, <redemption>, <frequency>, [<basis>]) ;; Price per $100 of a security with periodic interest.
PRICEDISC(<settlement>, <maturity>, <discount>, <redemption>, [<basis>]) ;; Price per $100 of a discounted security.
PRICEMAT(<settlement>, <maturity>, <issue>, <rate>, <yld>, [<basis>]) ;; Price per $100 of a security that pays interest at maturity.
PRODUCT(<column>) ;; Returns the product of the numbers in a column.
PRODUCTX(<table>, <expression>) ;; Returns the product of an expression evaluated for each row of a table.
PV(<rate>, <nper>, <pmt>, [<fv>], [<type>]) ;; Present value of an investment.
QUARTER(<date>) ;; Returns the quarter as a number from 1 to 4.
QUOTIENT(<numerator>, <denominator>) ;; Returns the integer portion of a division.
RADIANS(<angle>) ;; Converts degrees to radians.
RAND() ;; Returns a random number between 0 and 1.
RANDBETWEEN(<bottom>, <top>) ;; Returns a random integer between two numbers.
RANK(<ties>, [<relation>], [<orderBy>], [<blanks>], [<partitionBy>], [<matchBy>], [<reset>]) ;; Returns the rank of the current row within a partition.
RANK.EQ(<value>, <column>, [<order>]) ;; Returns the rank of a number in a column of numbers.
RANKX(<table>, <expression>, [<value>], [<order>], [<ties>]) ;; Returns the rank of a value in the result of an expression over a table.
RATE(<nper>, <pmt>, <pv>, [<fv>], [<type>], [<guess>]) ;; Interest rate per period of an annuity.
RECEIVED(<settlement>, <maturity>, <investment>, <discount>, [<basis>]) ;; Amount received at maturity for a fully invested security.
RELATED(<column>) ;; Returns a related value from another table.
RELATEDTABLE(<tableName>) ;; Returns the related rows of another table.
REMOVEFILTERS([<table> | <column>], [<column>]…) ;; Clears filters from the specified tables or columns.
REPLACE(<old_text>, <start_num>, <num_chars>, <new_text>) ;; Replaces part of a text string with a different string.
REPT(<text>, <num_times>) ;; Repeats text a given number of times.
RIGHT(<text>, [<num_chars>]) ;; Returns the rightmost characters of a text string.
ROLLUP(<groupBy_columnName>, [<groupBy_columnName>]…) ;; Defines subtotals in SUMMARIZE.
ROLLUPADDISSUBTOTAL(<grandtotalFilter>, <groupBy_columnName>, <name>, …) ;; Adds subtotal rows to SUMMARIZECOLUMNS.
ROLLUPGROUP(<groupBy_columnName>, [<groupBy_columnName>]…) ;; Groups columns for ROLLUP.
ROUND(<number>, <num_digits>) ;; Rounds a number to the specified number of digits.
ROUNDDOWN(<number>, <num_digits>) ;; Rounds a number down, toward zero.
ROUNDUP(<number>, <num_digits>) ;; Rounds a number up, away from zero.
ROW(<name>, <expression>, [<name>, <expression>]…) ;; Returns a single-row table with the given columns.
ROWNUMBER([<relation>], [<orderBy>], [<blanks>], [<partitionBy>], [<matchBy>], [<reset>]) ;; Returns the unique rank of the current row within a partition.
RRI(<nper>, <pv>, <fv>) ;; Equivalent interest rate for the growth of an investment.
SAMEPERIODLASTYEAR(<dates>) ;; Returns the dates one year before the dates in the context.
SAMPLE(<n_value>, <table>, <orderBy_expression>, [<order>]…) ;; Returns a sample of rows from a table.
SEARCH(<find_text>, <within_text>, [<start_num>], [<NotFoundValue>]) ;; Position of one text string in another (not case sensitive).
SECOND(<datetime>) ;; Returns the seconds as a number from 0 to 59.
SELECTCOLUMNS(<table>, [<name>], <expression>, [<name>], [<expression>]…) ;; Returns a table with the selected columns.
SELECTEDMEASURE() ;; Returns the measure that is currently being evaluated (calculation groups).
SELECTEDMEASURENAME() ;; Returns the name of the measure currently being evaluated.
SELECTEDVALUE(<columnName>, [<alternateResult>]) ;; Returns the value when the context for the column has one distinct value.
SIGN(<number>) ;; Returns the sign of a number: 1, 0 or -1.
SIN(<number>) ;; Returns the sine of an angle in radians.
SINH(<number>) ;; Returns the hyperbolic sine of a number.
SLN(<cost>, <salvage>, <life>) ;; Straight-line depreciation for one period.
SQRT(<number>) ;; Returns the square root of a number.
SQRTPI(<number>) ;; Returns the square root of (number * pi).
STARTOFMONTH(<dates>) ;; Returns the first date of the month in the current context.
STARTOFQUARTER(<dates>) ;; Returns the first date of the quarter in the current context.
STARTOFYEAR(<dates>, [<year_end_date>]) ;; Returns the first date of the year in the current context.
STDEV.P(<column>) ;; Standard deviation of a population in a column.
STDEV.S(<column>) ;; Standard deviation of a sample in a column.
STDEVX.P(<table>, <expression>) ;; Population standard deviation of an expression over a table.
STDEVX.S(<table>, <expression>) ;; Sample standard deviation of an expression over a table.
SUBSTITUTE(<text>, <old_text>, <new_text>, [<instance_num>]) ;; Replaces existing text with new text.
SUBSTITUTEWITHINDEX(<table>, <indexColumnName>, <indexColumnTable>, <orderBy_expression>, [<order>]…) ;; Replaces columns of a table by an index from another table.
SUM(<column>) ;; Adds all the numbers in a column.
SUMMARIZE(<table>, <groupBy_columnName>, [<groupBy_columnName>]…, [<name>, <expression>]…) ;; Returns a summary table grouped by the given columns.
SUMMARIZECOLUMNS(<groupBy_columnName>, [<groupBy_columnName>]…, [<filterTable>]…, [<name>, <expression>]…) ;; Returns a summary table over a set of groups.
SUMX(<table>, <expression>) ;; Returns the sum of an expression evaluated for each row of a table.
SWITCH(<expression>, <value>, <result>, [<value>, <result>]…, [<else>]) ;; Evaluates an expression against a list of values and returns the matching result.
SYD(<cost>, <salvage>, <life>, <per>) ;; Sum-of-years-digits depreciation for a period.
T.DIST(<x>, <deg_freedom>, <cumulative>) ;; Returns the left-tailed Student's t-distribution.
T.DIST.2T(<x>, <deg_freedom>) ;; Returns the two-tailed Student's t-distribution.
T.DIST.RT(<x>, <deg_freedom>) ;; Returns the right-tailed Student's t-distribution.
T.INV(<probability>, <deg_freedom>) ;; Returns the left-tailed inverse of the Student's t-distribution.
T.INV.2T(<probability>, <deg_freedom>) ;; Returns the two-tailed inverse of the Student's t-distribution.
TAN(<number>) ;; Returns the tangent of an angle in radians.
TANH(<number>) ;; Returns the hyperbolic tangent of a number.
TBILLEQ(<settlement>, <maturity>, <discount>) ;; Bond-equivalent yield for a Treasury bill.
TBILLPRICE(<settlement>, <maturity>, <discount>) ;; Price per $100 for a Treasury bill.
TBILLYIELD(<settlement>, <maturity>, <pr>) ;; Yield for a Treasury bill.
TIME(<hour>, <minute>, <second>) ;; Converts hours, minutes and seconds to a time.
TIMEVALUE(<time_text>) ;; Converts a time in text form to a time.
TOCSV(<table>, [<maxrows>], [<delimiter>], [<includeheaders>]) ;; Returns a table as CSV text.
TODAY() ;; Returns the current date.
TOJSON(<table>, [<maxrows>]) ;; Returns a table as JSON text.
TOPN(<n_value>, <table>, [<orderBy_expression>], [<order>]…) ;; Returns the top N rows of a table.
TOPNSKIP(<n_value>, <skip>, <table>, [<orderBy_expression>], [<order>]…) ;; Returns the top N rows of a table after skipping rows.
TOTALMTD(<expression>, <dates>, [<filter>]) ;; Month-to-date value of an expression.
TOTALQTD(<expression>, <dates>, [<filter>]) ;; Quarter-to-date value of an expression.
TOTALWTD(<expression>, <dates>, [<filter>], [<first_day_of_week>]) ;; Week-to-date value of an expression.
TOTALYTD(<expression>, <dates>, [<filter>], [<year_end_date>]) ;; Year-to-date value of an expression.
TREATAS(<table_expression>, <column>, [<column>]…) ;; Applies the result of a table as filters on columns.
TRIM(<text>) ;; Removes extra spaces from text.
TRUE() ;; Returns the logical value TRUE.
TRUNC(<number>, [<num_digits>]) ;; Truncates a number to an integer or to a number of digits.
UNICHAR(<number>) ;; Returns the Unicode character for a number.
UNICODE(<text>) ;; Returns the Unicode number of the first character of text.
UNION(<table1>, <table2>, [<table>]…) ;; Combines the rows of two or more tables.
UPPER(<text>) ;; Converts text to uppercase.
USERCULTURE() ;; Returns the locale of the current user.
USERELATIONSHIP(<columnName1>, <columnName2>) ;; Uses an inactive relationship for a calculation.
USERNAME() ;; Returns the domain and user name of the current connection.
USEROBJECTID() ;; Returns the object id of the current user.
USERPRINCIPALNAME() ;; Returns the user principal name.
VALUE(<text>) ;; Converts a text string to a number.
VALUES(<TableNameOrColumnName>) ;; Returns the distinct values of a column or the rows of a table, including blank.
VAR.P(<column>) ;; Variance of a population in a column.
VAR.S(<column>) ;; Variance of a sample in a column.
VARX.P(<table>, <expression>) ;; Population variance of an expression over a table.
VARX.S(<table>, <expression>) ;; Sample variance of an expression over a table.
VDB(<cost>, <salvage>, <life>, <start_period>, <end_period>, [<factor>], [<no_switch>]) ;; Depreciation for any period using variable declining balance.
WEEKDAY(<date>, [<return_type>]) ;; Returns the day of the week as a number.
WEEKNUM(<date>, [<return_type>]) ;; Returns the week number of the year.
WINDOW(<from>, <from_type>, <to>, <to_type>, [<relation>], [<orderBy>], [<blanks>], [<partitionBy>], [<matchBy>], [<reset>]) ;; Returns a range of rows within a partition.
XIRR(<table>, <values>, <dates>, [<guess>]) ;; Internal rate of return for irregular cash flows.
XNPV(<table>, <values>, <dates>, <rate>) ;; Net present value for irregular cash flows.
YEAR(<date>) ;; Returns the year of a date as a four-digit integer.
YEARFRAC(<start_date>, <end_date>, [<basis>]) ;; Fraction of the year between two dates.
YIELD(<settlement>, <maturity>, <rate>, <pr>, <redemption>, <frequency>, [<basis>]) ;; Yield of a security with periodic interest.
YIELDDISC(<settlement>, <maturity>, <pr>, <redemption>, [<basis>]) ;; Annual yield of a discounted security.
YIELDMAT(<settlement>, <maturity>, <issue>, <rate>, <pr>, [<basis>]) ;; Annual yield of a security that pays interest at maturity.
"""


def _parse() -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for line in _CATALOG_TEXT.strip().splitlines():
        signature, _, doc = line.partition(" ;; ")
        name = signature.split("(", 1)[0].strip()
        entries[name.upper()] = (signature.strip(), doc.strip())
    return entries


CATALOG: dict[str, tuple[str, str]] = _parse()


def signature_of(name: str) -> str:
    entry = CATALOG.get(name.upper())
    return entry[0] if entry else f"{name.upper()}(…)"


def doc_of(name: str) -> str:
    entry = CATALOG.get(name.upper())
    return entry[1] if entry else ""


def split_parameters(signature: str) -> list[str]:
    """Return the parameter labels of a catalog signature, top-level commas only."""
    open_at = signature.find("(")
    close_at = signature.rfind(")")
    if open_at < 0 or close_at <= open_at:
        return []
    body = signature[open_at + 1:close_at]
    parameters: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char in "[<(":
            depth += 1
        elif char in "]>)":
            depth -= 1
        if char == "," and depth == 0:
            parameters.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        parameters.append(tail)
    return parameters
