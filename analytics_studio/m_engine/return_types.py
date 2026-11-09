"""Declared return types of the library functions, as Power BI reports them.

Type.FunctionReturn(Value.Type(f)) measured live for every function this engine implements (Task 107).
Table functions that build a column from a function (Table.TransformColumns, Table.AddColumn, Table.Group,
Table.ReplaceValue) give the column the function's declared return type. A function missing here has no measured
return type: the table function refuses (ERR) rather than guess."""

from __future__ import annotations

# (type name as Table.Schema prints it, is nullable) -> the functions that return it
_GROUPS = {
    ('Any.Type', True): (
        'Date.AddDays', 'Date.AddMonths', 'Date.AddQuarters', 'Date.AddWeeks', 'Date.AddYears', 'Date.EndOfDay',
        'Date.EndOfMonth', 'Date.EndOfQuarter', 'Date.EndOfWeek', 'Date.EndOfYear', 'Date.StartOfDay',
        'Date.StartOfMonth', 'Date.StartOfQuarter', 'Date.StartOfWeek', 'Date.StartOfYear', 'List.Accumulate',
        'List.Average', 'List.First', 'List.FirstN', 'List.Last', 'List.LastN', 'List.Max', 'List.Median',
        'List.Min', 'List.Mode', 'List.Percentile', 'List.PositionOf', 'List.PositionOfAny', 'List.Single',
        'List.SingleOrDefault', 'List.Sum', 'Number.BitwiseNot', 'Record.Field', 'Record.FieldOrDefault',
        'Replacer.ReplaceValue', 'Table.First', 'Table.Last', 'Table.Max', 'Table.Min', 'Table.PositionOf',
        'Text.AfterDelimiter', 'Text.BeforeDelimiter', 'Text.BetweenDelimiters', 'Text.PositionOf',
        'Text.PositionOfAny', 'Time.EndOfHour', 'Time.StartOfHour', 'Value.Metadata',
    ),
    ('Binary.Type', True): (
        'Text.ToBinary',
    ),
    ('Byte.Type', True): (
        'Byte.From',
    ),
    ('Character.Type', True): (
        'Text.At',
    ),
    ('Currency.Type', True): (
        'Currency.From',
    ),
    ('Date.Type', True): (
        'Date.From', 'Date.FromText', 'DateTime.Date',
    ),
    ('DateTime.Type', False): (
        'DateTime.FixedLocalNow', 'DateTime.LocalNow',
    ),
    ('DateTime.Type', True): (
        'DateTime.From', 'DateTime.FromFileTime', 'DateTime.FromText', 'DateTimeZone.RemoveZone',
    ),
    ('DateTimeZone.Type', False): (
        'DateTimeZone.FixedLocalNow', 'DateTimeZone.FixedUtcNow', 'DateTimeZone.LocalNow', 'DateTimeZone.UtcNow',
    ),
    ('DateTimeZone.Type', True): (
        'DateTime.AddZone', 'DateTimeZone.From', 'DateTimeZone.FromText', 'DateTimeZone.SwitchZone',
        'DateTimeZone.ToLocal', 'DateTimeZone.ToUtc',
    ),
    ('Decimal.Type', True): (
        'Decimal.From',
    ),
    ('Double.Type', True): (
        'Double.From',
    ),
    ('Duration.Type', True): (
        'Duration.From', 'Duration.FromText',
    ),
    ('Function.Type', False): (
        'Combiner.CombineTextByDelimiter', 'Splitter.SplitTextByDelimiter',
    ),
    ('Int16.Type', True): (
        'Int16.From',
    ),
    ('Int32.Type', False): (
        'Record.FieldCount',
    ),
    ('Int32.Type', True): (
        'Date.Day', 'Date.DayOfYear', 'Date.DaysInMonth', 'Date.Month', 'Date.QuarterOfYear', 'Date.WeekOfMonth',
        'Date.WeekOfYear', 'Date.Year', 'DateTimeZone.ZoneHours', 'DateTimeZone.ZoneMinutes', 'Duration.Days',
        'Duration.Hours', 'Duration.Minutes', 'Int32.From', 'Number.Sign', 'Text.Length', 'Time.Hour',
        'Time.Minute',
    ),
    ('Int64.Type', True): (
        'Int64.From',
    ),
    ('Int8.Type', True): (
        'Int8.From',
    ),
    ('List.Type', False): (
        'List.Alternate', 'List.Buffer', 'List.Combine', 'List.DateTimes', 'List.Dates', 'List.Difference',
        'List.Distinct', 'List.Durations', 'List.FindText', 'List.Generate', 'List.InsertRange', 'List.Intersect',
        'List.MaxN', 'List.MinN', 'List.Modes', 'List.Numbers', 'List.Positions', 'List.Range', 'List.RemoveFirstN',
        'List.RemoveItems', 'List.RemoveLastN', 'List.RemoveMatchingItems', 'List.RemoveNulls', 'List.RemoveRange',
        'List.Repeat', 'List.ReplaceMatchingItems', 'List.ReplaceRange', 'List.ReplaceValue', 'List.Reverse',
        'List.Select', 'List.Skip', 'List.Sort', 'List.Split', 'List.Times', 'List.Transform', 'List.TransformMany',
        'List.Union', 'List.Zip', 'Record.FieldNames', 'Record.FieldValues', 'Record.ToList', 'Table.Column',
        'Table.ColumnNames', 'Table.ColumnsOfType', 'Table.Keys', 'Table.ToColumns', 'Table.ToRecords',
        'Table.ToRows', 'Text.Split', 'Text.SplitAny', 'Text.ToList',
    ),
    ('Logical.Type', False): (
        'List.AllTrue', 'List.AnyTrue', 'List.Contains', 'List.ContainsAll', 'List.ContainsAny', 'List.IsDistinct',
        'List.IsEmpty', 'List.MatchesAll', 'List.MatchesAny', 'Number.IsEven', 'Number.IsNaN', 'Number.IsOdd',
        'Record.HasFields', 'Table.Contains', 'Table.ContainsAny', 'Table.HasColumns', 'Table.IsDistinct',
        'Table.IsEmpty', 'Table.MatchesAllRows', 'Table.MatchesAnyRows', 'Value.Is',
    ),
    ('Logical.Type', True): (
        'Date.IsInCurrentDay', 'Date.IsInCurrentMonth', 'Date.IsInCurrentQuarter', 'Date.IsInCurrentWeek',
        'Date.IsInCurrentYear', 'Date.IsInNextDay', 'Date.IsInNextMonth', 'Date.IsInNextQuarter',
        'Date.IsInNextWeek', 'Date.IsInNextYear', 'Date.IsInPreviousDay', 'Date.IsInPreviousMonth',
        'Date.IsInPreviousQuarter', 'Date.IsInPreviousWeek', 'Date.IsInPreviousYear', 'Date.IsInYearToDate',
        'Date.IsLeapYear', 'DateTime.IsInCurrentHour', 'DateTime.IsInCurrentMinute', 'DateTime.IsInCurrentSecond',
        'DateTime.IsInNextHour', 'DateTime.IsInNextMinute', 'DateTime.IsInNextSecond', 'DateTime.IsInPreviousHour',
        'DateTime.IsInPreviousMinute', 'DateTime.IsInPreviousSecond', 'Logical.From', 'Logical.FromText',
        'Text.Contains', 'Text.EndsWith', 'Text.StartsWith',
    ),
    ('Number.Type', False): (
        'Comparer.Ordinal', 'Comparer.OrdinalIgnoreCase', 'List.Count', 'List.NonNullCount', 'Number.Random',
        'Number.RandomBetween', 'Table.ColumnCount', 'Table.RowCount',
    ),
    ('Number.Type', True): (
        'Character.ToNumber', 'Date.DayOfWeek', 'Duration.Seconds', 'Duration.TotalDays', 'Duration.TotalHours',
        'Duration.TotalMinutes', 'Duration.TotalSeconds', 'List.Covariance', 'List.Product',
        'List.StandardDeviation', 'Number.Abs', 'Number.Acos', 'Number.Asin', 'Number.Atan', 'Number.Atan2',
        'Number.BitwiseAnd', 'Number.BitwiseOr', 'Number.BitwiseShiftLeft', 'Number.BitwiseShiftRight',
        'Number.BitwiseXor', 'Number.Combinations', 'Number.Cos', 'Number.Cosh', 'Number.Exp', 'Number.Factorial',
        'Number.From', 'Number.FromText', 'Number.IntegerDivide', 'Number.Ln', 'Number.Log', 'Number.Log10',
        'Number.Mod', 'Number.Permutations', 'Number.Power', 'Number.Round', 'Number.RoundAwayFromZero',
        'Number.RoundDown', 'Number.RoundTowardZero', 'Number.RoundUp', 'Number.Sin', 'Number.Sinh', 'Number.Sqrt',
        'Number.Tan', 'Number.Tanh', 'Time.Second',
    ),
    ('Percentage.Type', True): (
        'Percentage.From',
    ),
    ('Record.Type', False): (
        'Date.ToRecord', 'DateTime.ToRecord', 'DateTimeZone.ToRecord', 'Duration.ToRecord', 'Record.AddField',
        'Record.Combine', 'Record.FromList', 'Record.FromTable', 'Record.RemoveFields', 'Record.RenameFields',
        'Record.ReorderFields', 'Record.SelectFields', 'Record.TransformFields', 'Time.ToRecord',
        'Type.RecordFields',
    ),
    ('Single.Type', True): (
        'Single.From',
    ),
    ('Table.Type', False): (
        'Record.ToTable', 'Table.AddColumn', 'Table.AddIndexColumn', 'Table.Buffer', 'Table.Combine',
        'Table.CombineColumns', 'Table.DemoteHeaders', 'Table.Distinct', 'Table.DuplicateColumn',
        'Table.ExpandRecordColumn', 'Table.ExpandTableColumn', 'Table.FillDown', 'Table.FillUp', 'Table.FindText',
        'Table.FirstN', 'Table.FromColumns', 'Table.FromList', 'Table.FromRecords', 'Table.FromRows',
        'Table.FromValue', 'Table.Group', 'Table.InsertRows', 'Table.Join', 'Table.LastN', 'Table.MaxN',
        'Table.MinN', 'Table.NestedJoin', 'Table.Pivot', 'Table.Profile', 'Table.PromoteHeaders', 'Table.Range',
        'Table.RemoveColumns', 'Table.RemoveFirstN', 'Table.RemoveLastN', 'Table.RemoveMatchingRows',
        'Table.RemoveRows', 'Table.RemoveRowsWithErrors', 'Table.RenameColumns', 'Table.ReorderColumns',
        'Table.Repeat', 'Table.ReplaceValue', 'Table.ReverseRows', 'Table.Schema', 'Table.SelectColumns',
        'Table.SelectRows', 'Table.SelectRowsWithErrors', 'Table.Skip', 'Table.Sort', 'Table.SplitColumn',
        'Table.TransformColumnTypes', 'Table.TransformColumns', 'Table.Transpose', 'Table.Unpivot',
        'Table.UnpivotOtherColumns', 'Type.TableSchema',
    ),
    ('Text.Type', False): (
        'Text.Combine', 'Text.Format', 'Text.NewGuid',
    ),
    ('Text.Type', True): (
        'Date.DayOfWeekName', 'Date.MonthName', 'Date.ToText', 'DateTime.ToText', 'DateTimeZone.ToText',
        'Duration.ToText', 'Logical.ToText', 'Number.ToText', 'Replacer.ReplaceText', 'Text.Clean', 'Text.End',
        'Text.From', 'Text.FromBinary', 'Text.Insert', 'Text.Lower', 'Text.Middle', 'Text.PadEnd', 'Text.PadStart',
        'Text.Proper', 'Text.Range', 'Text.Remove', 'Text.RemoveRange', 'Text.Repeat', 'Text.Replace',
        'Text.ReplaceRange', 'Text.Reverse', 'Text.Select', 'Text.Start', 'Text.Trim', 'Text.TrimEnd',
        'Text.TrimStart', 'Text.Upper', 'Time.ToText',
    ),
    ('Time.Type', True): (
        'DateTime.Time', 'Time.From', 'Time.FromText',
    ),
    ('Type.Type', False): (
        'Text.InferNumberType', 'Value.Type',
    ),
}

RETURN_TYPES: dict = {name: spec for spec, names in _GROUPS.items() for name in names}
