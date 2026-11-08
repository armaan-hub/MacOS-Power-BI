r"""Power Query (M) oracle: Power BI Desktop's answers (Parallels guest, Analysis Services) for M expressions.

Run from the repo root:  PYTHONPATH=. python3 tools/m_oracle_diff.py in.json out.json
in.json is a list of M expressions; out.json receives the list of Power BI answers, in the same order.
Each batch creates a scratch import table `MOracle__` in the unsaved in-memory model through TMSL, refreshes it,
reads it with EVALUATE and deletes it (also on failure). Never saves the Power BI project.

Answer text per expression:  "V:<canonical>" for a value, "ERR:<reason>: <message>" for an error,
"UNREPRESENTABLE" when the serializer itself fails on the value,
"ERR:PARTITION: <message>" when the expression's own partition fails to build or refresh.

Canonical value text (written by the M function M_SERIALIZER, applied to every answer; type-tagged, lossless):
  null -> null          logical -> true | false
  number -> number:<Number.ToText(v,"R","en-US")>, or number:NaN | number:+Infinity | number:-Infinity
  text -> text:"<escaped>"   escaping: \ for backslash, \" for double quote, \n \r \t for LF CR TAB,
          \uXXXX (4 upper-case hex digits) for every other control character U+0000-U+001F and U+007F;
          everything else (including non-ASCII) stays as is
  date -> date:yyyy-MM-dd   time -> time:HH:mm:ss.fffffff   datetime -> datetime:yyyy-MM-ddTHH:mm:ss.fffffff
  datetimezone -> datetimezone:yyyy-MM-ddTHH:mm:ss.fffffff+HH:mm   duration -> duration:<Duration.ToText(v)>
  list -> list:[item,item]   record -> record:["name"=value,"name"=value] (field order; names escaped like text)
  table -> table:cols=["name":Kind,...];rows=[list:[...],...]   (Kind from Table.Schema, rows from Table.ToRows)
  binary -> binary:<base64>   function -> function   type -> type
The scratch table is deleted after every batch and the model is asked whether it is really gone; the
"could not delete" warning is printed only when the table is still present afterwards.
"""
from __future__ import annotations

import base64
import json
import sys

from tools.dax_oracle_diff import PS_HEAD, guest, port

SCRATCH = "MOracle__"
TRIES = 3  # the guest sometimes returns nothing for a batch; never let that shift the answers

# The recursive type-tagged serializer, one M binding `S`; placed once in every partition. Reusable by later tasks.
M_SERIALIZER = r'''S = (v as any) as text =>
        let
            Esc = (t as text) as text =>
                Text.Combine(List.Transform(Text.ToList(t), (c as text) as text =>
                    let n = Character.ToNumber(c) in
                    if c = "\" then "\\"
                    else if c = """" then "\"""
                    else if n = 10 then "\n"
                    else if n = 13 then "\r"
                    else if n = 9 then "\t"
                    else if n < 32 or n = 127 then "\u" & Number.ToText(n, "X4", "en-US")
                    else c)),
            Q = (t as text) as text => """" & Esc(t) & """"
        in
            if v = null then "null"
            else if v is logical then (if v then "true" else "false")
            else if v is number then
                (if Number.IsNaN(v) then "number:NaN"
                 else if v = Number.PositiveInfinity then "number:+Infinity"
                 else if v = Number.NegativeInfinity then "number:-Infinity"
                 else "number:" & Number.ToText(v, "R", "en-US"))
            else if v is text then "text:" & Q(v)
            else if v is date then "date:" & Date.ToText(v, [Format = "yyyy-MM-dd", Culture = "en-US"])
            else if v is time then "time:" & Time.ToText(v, [Format = "HH:mm:ss.fffffff", Culture = "en-US"])
            else if v is datetimezone then "datetimezone:" & DateTimeZone.ToText(v, [Format = "yyyy-MM-dd'T'HH:mm:ss.fffffffzzz", Culture = "en-US"])
            else if v is datetime then "datetime:" & DateTime.ToText(v, [Format = "yyyy-MM-dd'T'HH:mm:ss.fffffff", Culture = "en-US"])
            else if v is duration then "duration:" & Duration.ToText(v)
            else if v is list then "list:[" & Text.Combine(List.Transform(v, (x) => @S(x)), ",") & "]"
            else if v is record then "record:[" & Text.Combine(List.Transform(Record.FieldNames(v), (f) => Q(f) & "=" & @S(Record.Field(v, f))), ",") & "]"
            else if v is table then "table:cols=[" & Text.Combine(List.Transform(Table.ToRows(Table.SelectColumns(Table.Schema(v), {"Name", "Kind"})), (r) => Q(r{0}) & ":" & Q(r{1})), ",") & "];rows=[" & Text.Combine(List.Transform(Table.ToRows(v), (r) => @S(r)), ",") & "]"
            else if v is binary then "binary:" & Binary.ToText(v, BinaryEncoding.Base64)
            else if v is function then "function"
            else if v is type then "type"
            else error "unknown value kind"
'''.rstrip()


def chunks(expressions: list[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("chunk size must be at least 1")
    return [expressions[start:start + size] for start in range(0, len(expressions), size)]


def _answer_item(index: int, expression: str) -> str:
    # the expression goes verbatim inside its own parentheses, on its own line, so a trailing // comment cannot eat the rest
    return (
        f"    [I = {index}, A = (\n"
        "let\n"
        "    r = try (\n"
        f"{expression}\n"
        "    )\n"
        "in\n"
        '    if r[HasError] then "ERR:" & r[Error][Reason] & ": " & (r[Error][Message] ?? "")\n'
        '    else try ("V:" & S(r[Value])) otherwise "UNREPRESENTABLE"\n'
        ")]"
    )


def m_partition(expressions: list[str]) -> str:
    """The partition's M: one table row per expression, [I = index, A = answer text]."""
    items = ",\n".join(_answer_item(index, expression) for index, expression in enumerate(expressions))
    return (
        "let\n"
        "    " + M_SERIALIZER + ",\n"
        "    Rows = {\n" + items + "\n    },\n"
        "    T = Table.FromRecords(Rows, type table [I = Int64.Type, A = text])\n"
        "in\n"
        "    T"
    )


def tmsl(expressions: list[str]) -> str:
    """The TMSL createOrReplace command; the database placeholder is filled in on the guest."""
    return json.dumps({"createOrReplace": {"object": {"database": "__DB__", "table": SCRATCH}, "table": {
        "name": SCRATCH,
        "columns": [{"name": "I", "dataType": "int64", "sourceColumn": "I"},
                    {"name": "A", "dataType": "string", "sourceColumn": "A"}],
        "partitions": [{"name": "p", "mode": "import",
                        "source": {"type": "m", "expression": m_partition(expressions)}}]}}})


# PowerShell after the shared head (connection open). Create, refresh and read inside try; delete always in finally.
# Output: R|<index>|<base64 answer> per row, or FAIL|<base64 message> when create/refresh/read threw, then DROPPED or DROP_ERR.
_BODY = r"""
$t=$t.Replace('"__DB__"', '"'+$c.Database+'"')
$rows=New-Object System.Collections.ArrayList
$failed=$false
$fail=''
try{
  $cmd=$c.CreateCommand(); $cmd.CommandText=$t; $null=$cmd.ExecuteNonQuery()
  $cmd2=$c.CreateCommand(); $cmd2.CommandText='{"refresh":{"type":"full","objects":[{"database":"'+$c.Database+'","table":"MOracle__"}]}}'; $null=$cmd2.ExecuteNonQuery()
  $cmd3=$c.CreateCommand(); $cmd3.CommandText='EVALUATE MOracle__'; $r=$cmd3.ExecuteReader()
  while($r.Read()){ [void]$rows.Add([pscustomobject]@{I=[int64]$r.GetValue(0); A=[string]$r.GetValue(1)}) }
  $r.Close()
}catch{ $failed=$true; $fail=($_.Exception.Message -replace '\s+',' ') }
finally{
  $dropMsg=''
  try{ $cmd4=$c.CreateCommand(); $cmd4.CommandText='{"delete":{"object":{"database":"'+$c.Database+'","table":"MOracle__"}}}'; $null=$cmd4.ExecuteNonQuery() }catch{ $dropMsg=($_.Exception.Message -replace '\s+',' ') }
  # a failed delete only matters when the table is still there (a failed create leaves no table to delete)
  try{
    $cmd5=$c.CreateCommand(); $cmd5.CommandText='EVALUATE FILTER(INFO.TABLES(), [Name]="MOracle__")'; $r5=$cmd5.ExecuteReader(); $left=0; while($r5.Read()){ $left++ }; $r5.Close()
    if($left -gt 0){ 'DROP_ERR table still present: '+$dropMsg }else{ 'DROPPED' }
  }catch{ 'DROP_ERR could not check: '+($_.Exception.Message -replace '\s+',' ')+' '+$dropMsg }
}
if($failed){ 'FAIL|'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($fail)) }
else{ foreach($row in ($rows | Sort-Object I)){ 'R|'+$row.I+'|'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($row.A)) } }
$c.Close()"""


def _script(expressions: list[str], port_: str) -> str:
    return PS_HEAD.replace("__PORT__", port_) + "\n$t=@'\n" + tmsl(expressions) + "\n'@\n" + _BODY


def parse_output(output: str, count: int) -> tuple[list[str] | None, str | None]:
    """(answers, None) when every expression answered; (None, message) when the partition itself failed;
    (None, None) when the output is incomplete and the batch must be asked again."""
    lines = output.splitlines()
    for line in lines:
        if line.startswith("FAIL|"):
            return None, base64.b64decode(line[5:].strip()).decode("utf-8")
    answers: dict[int, str] = {}
    for line in lines:
        if line.startswith("R|"):
            index, _, payload = line[2:].partition("|")
            answers[int(index)] = base64.b64decode(payload.strip()).decode("utf-8")
    if sorted(answers) == list(range(count)):
        return [answers[index] for index in range(count)], None
    return None, None


def _run_batch(expressions: list[str], port_: str) -> tuple[list[str] | None, str | None]:
    script = _script(expressions, port_)
    for _attempt in range(TRIES):
        output = guest(script)
        if "DROP_ERR" in output:
            print(f"WARNING: could not delete scratch table {SCRATCH} from the Power BI model; remove it manually.")
        answers, failure = parse_output(output, len(expressions))
        if answers is not None or failure is not None:
            return answers, failure
    raise RuntimeError(f"Power BI returned no complete answer for {len(expressions)} expressions after {TRIES} tries")


def power_query(expressions: list[str], port_: str, chunk: int = 100) -> list[str]:
    """Power BI's answer for every M expression, asked in batches of `chunk`."""
    answers: list[str] = []
    for batch in chunks(expressions, chunk):
        got, _failure = _run_batch(batch, port_)
        if got is not None:
            answers += got
            continue
        # the batch's partition failed (usually one bad expression): ask each expression in its own partition
        for expression in batch:
            one, failure = _run_batch([expression], port_)
            answers.append(one[0] if one is not None else f"ERR:PARTITION: {failure}")
    return answers


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: PYTHONPATH=. python3 tools/m_oracle_diff.py in.json out.json")
    with open(sys.argv[1], encoding="utf-8") as source:
        expressions = json.load(source)
    answers = power_query(expressions, port())
    with open(sys.argv[2], "w", encoding="utf-8") as target:
        json.dump(answers, target, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
