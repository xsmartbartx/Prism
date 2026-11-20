"""Calculated fields: a small, typed expression language compiled to bound SQL.

Authors write spreadsheet-like formulas over a dataset's columns::

    [Revenue] - [Cost]
    ROUND([Profit] / [Revenue] * 100, 1)
    IF([Units] >= 10, 'Bulk', 'Single')
    YEAR([Order Date])

No user text ever reaches SQL. A formula is tokenized and parsed into a tree;
every column must exist (and becomes a quoted identifier), every function must
be on the whitelist below, every literal becomes a bound parameter, and the
tree is type-checked before it is compiled. Division by zero gives an empty
value, not an error.

Types are Prism's: integer, float, string, date, boolean.

A formula that uses an aggregate — SUM, AVG, MIN, MAX, MEDIAN, COUNT, COUNTD —
is an *aggregate field* (a measure): ``(SUM([Revenue]) - SUM([Cost])) /
SUM([Revenue])`` is the margin of whatever group a chart shows, which is not
the average of each row's margin. Every column in such a formula must sit
inside an aggregate, and aggregates do not nest. Aggregate fields may use
earlier aggregate fields; any formula that does becomes one too.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.errors import ValidationError

MAX_LENGTH = 1000
MAX_DEPTH = 40
MAX_CALCULATIONS = 25
NUMERIC = ("integer", "float")
TYPES = ("integer", "float", "string", "date", "boolean")


class CalcError(ValidationError):
    """The formula is not valid (syntax, unknown column or function, or wrong types)."""


# ----------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
  | (?P<str>'(?:[^']|'')*')
  | (?P<col>\[(?:[^\]]|\]\])*\])
  | (?P<op><>|!=|<=|>=|[-+*/%(),=<>&])
  | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int


def tokenize(text: str) -> list[Token]:
    if len(text) > MAX_LENGTH:
        raise CalcError(f"A formula can be at most {MAX_LENGTH} characters")
    out: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            snippet = text[pos : pos + 12]
            if text[pos] == "'":
                raise CalcError("A text value is missing its closing quote '")
            if text[pos] == "[":
                raise CalcError("A column name is missing its closing bracket ]")
            raise CalcError(f"Unexpected character at position {pos + 1}: {snippet!r}")
        kind = m.lastgroup or ""
        if kind != "ws":
            out.append(Token(kind, m.group(), pos))
        pos = m.end()
    out.append(Token("end", "", len(text)))
    return out


# ----------------------------------------------------------------------
# Tree
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    kind: str  # num | str | bool | null | col | neg | not | bin | call
    value: Any = None
    args: tuple[Node, ...] = field(default=())


class _Parser:
    """Precedence climbing: OR < AND < NOT < comparison < & < + - < * / % < unary."""

    def __init__(self, tokens: list[Token]) -> None:
        self.t = tokens
        self.i = 0
        self.depth = 0

    def peek(self) -> Token:
        return self.t[self.i]

    def take(self) -> Token:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def word(self, *words: str) -> bool:
        tok = self.peek()
        return tok.kind == "name" and tok.text.upper() in words

    def expect(self, text: str) -> None:
        tok = self.take()
        if tok.text != text:
            found = tok.text or "the end"
            raise CalcError(f"Expected {text!r} at position {tok.pos + 1}, found {found!r}")

    def deeper(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError("The formula is nested too deeply")

    def parse(self) -> Node:
        if self.peek().kind == "end":
            raise CalcError("Enter a formula")
        node = self.or_()
        tok = self.peek()
        if tok.kind != "end":
            raise CalcError(f"Unexpected {tok.text!r} at position {tok.pos + 1}")
        return node

    def or_(self) -> Node:
        node = self.and_()
        while self.word("OR"):
            self.take()
            node = Node("bin", "OR", (node, self.and_()))
        return node

    def and_(self) -> Node:
        node = self.not_()
        while self.word("AND"):
            self.take()
            node = Node("bin", "AND", (node, self.not_()))
        return node

    def not_(self) -> Node:
        if self.word("NOT"):
            self.take()
            self.deeper()
            node = Node("not", None, (self.not_(),))
            self.depth -= 1
            return node
        return self.compare()

    def compare(self) -> Node:
        node = self.concat()
        tok = self.peek()
        if tok.kind == "op" and tok.text in ("=", "<>", "!=", "<", "<=", ">", ">="):
            self.take()
            op = "<>" if tok.text == "!=" else tok.text
            node = Node("bin", op, (node, self.concat()))
        return node

    def concat(self) -> Node:
        node = self.additive()
        while self.peek().text == "&":
            self.take()
            node = Node("bin", "&", (node, self.additive()))
        return node

    def additive(self) -> Node:
        node = self.term()
        while self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.take().text
            node = Node("bin", op, (node, self.term()))
        return node

    def term(self) -> Node:
        node = self.unary()
        while self.peek().kind == "op" and self.peek().text in ("*", "/", "%"):
            op = self.take().text
            node = Node("bin", op, (node, self.unary()))
        return node

    def unary(self) -> Node:
        if self.peek().text in ("-", "+"):
            op = self.take().text
            self.deeper()
            inner = self.unary()
            self.depth -= 1
            return Node("neg", None, (inner,)) if op == "-" else inner
        return self.atom()

    def atom(self) -> Node:
        tok = self.take()
        if tok.kind == "num":
            num: float | int = float(tok.text) if re.search(r"[.eE]", tok.text) else int(tok.text)
            return Node("num", num)
        if tok.kind == "str":
            return Node("str", tok.text[1:-1].replace("''", "'"))
        if tok.kind == "col":
            name = tok.text[1:-1].replace("]]", "]")
            if not name.strip():
                raise CalcError("A column reference is empty: write [Column name]")
            return Node("col", name)
        if tok.text == "(":
            self.deeper()
            node = self.or_()
            self.expect(")")
            self.depth -= 1
            return node
        if tok.kind == "name":
            upper = tok.text.upper()
            if upper in ("TRUE", "FALSE"):
                return Node("bool", upper == "TRUE")
            if upper == "NULL":
                return Node("null")
            if self.peek().text == "(":
                return self.call(upper, tok)
            raise CalcError(
                f"Unknown name {tok.text!r}: put column names in brackets, like [{tok.text}]"
            )
        found = tok.text or "the end of the formula"
        raise CalcError(f"Expected a value at position {tok.pos + 1}, found {found!r}")

    def call(self, name: str, tok: Token) -> Node:
        if name not in FUNCTIONS and name not in AGGREGATES:
            raise CalcError(f"Unknown function {tok.text}()")
        self.take()  # (
        self.deeper()
        args: list[Node] = []
        if self.peek().text != ")":
            args.append(self.or_())
            while self.peek().text == ",":
                self.take()
                args.append(self.or_())
        self.expect(")")
        self.depth -= 1
        return Node("call", name, tuple(args))


def parse(text: str) -> Node:
    return _Parser(tokenize(text)).parse()


# ----------------------------------------------------------------------
# Types and SQL
# ----------------------------------------------------------------------


@dataclass
class _Ctx:
    columns: dict[str, str]
    params: list[Any]
    used: set[str] = field(default_factory=set)
    # Aggregate fields defined so far: name -> (sql, type, params, uses).
    aggregates: dict[str, tuple[str, str, tuple[Any, ...], frozenset[str]]] = field(
        default_factory=dict
    )
    depth: int = 0  # > 0 inside an aggregate's argument
    bare: set[str] = field(default_factory=set)  # columns read outside any aggregate
    state: dict[str, bool] = field(default_factory=dict)  # "aggregate": seen one

    def bind(self, value: Any) -> str:
        self.params.append(value)
        return "?"


def _q(name: str) -> str:
    if "\x00" in name:
        raise CalcError("Column names cannot contain NUL")
    return '"' + name.replace('"', '""') + '"'


Compiled = tuple[str, str]  # (sql, type) ; type "null" for NULL literals


_KIND_TEXT = {"number": "a number", "string": "text", "date": "a date", "boolean": "true/false"}
_ACCEPTS = {
    "number": (*NUMERIC, "null"),
    "string": ("string", "null"),
    "date": ("date", "null"),
    "boolean": ("boolean", "null"),
}


def _need(kind: str, got: str, what: str) -> None:
    if got not in _ACCEPTS[kind]:
        raise CalcError(f"{what} needs {_KIND_TEXT[kind]}, not {_describe(got)}")


def _describe(t: str) -> str:
    return {
        "integer": "a whole number",
        "float": "a decimal number",
        "string": "text",
        "date": "a date",
        "boolean": "true/false",
        "null": "an empty value",
    }.get(t, t)


def _num_type(*types: str) -> str:
    return "float" if "float" in types else "integer"


def _common(types: list[str], what: str) -> str:
    real = [t for t in types if t != "null"]
    if not real:
        return "null"
    if all(t in NUMERIC for t in real):
        return _num_type(*real)
    if len(set(real)) > 1:
        raise CalcError(
            f"{what}: all results must be the same kind of value, not "
            + " and ".join(sorted({_describe(t) for t in real}))
        )
    return real[0]


def _compile(node: Node, ctx: _Ctx) -> Compiled:
    k = node.kind
    if k == "num":
        return ctx.bind(node.value), "float" if isinstance(node.value, float) else "integer"
    if k == "str":
        return f"CAST({ctx.bind(node.value)} AS VARCHAR)", "string"
    if k == "bool":
        return ("TRUE" if node.value else "FALSE"), "boolean"
    if k == "null":
        return "NULL", "null"
    if k == "col":
        name = node.value
        if name in ctx.aggregates:
            if ctx.depth:
                raise CalcError(f"[{name}] is already aggregated, so it cannot go inside one")
            agg_sql, agg_type, agg_params, agg_uses = ctx.aggregates[name]
            ctx.params.extend(agg_params)
            ctx.used |= {name, *agg_uses}
            ctx.state["aggregate"] = True
            return f"({agg_sql})", agg_type
        if name not in ctx.columns:
            near = [c for c in ctx.columns if c.casefold() == str(name).casefold()]
            hint = f" Did you mean [{near[0]}]?" if near else ""
            raise CalcError(f"There is no column [{name}].{hint}")
        ctx.used.add(name)
        if not ctx.depth:
            ctx.bare.add(name)
        return _q(name), ctx.columns[name]
    if k == "neg":
        sql, t = _compile(node.args[0], ctx)
        _need("number", t, "A minus sign")
        return f"(-{sql})", t if t != "null" else "integer"
    if k == "not":
        sql, t = _compile(node.args[0], ctx)
        _need("boolean", t, "NOT")
        return f"(NOT {sql})", "boolean"
    if k == "bin":
        return _binary(node, ctx)
    return _call(node, ctx)


def _isolated(node: Node, ctx: _Ctx) -> tuple[str, str, list[Any]]:
    """Compile ``node`` with its own parameter list, so the caller decides their order."""
    sub = _Ctx(
        columns=ctx.columns,
        params=[],
        used=ctx.used,
        aggregates=ctx.aggregates,
        depth=ctx.depth,
        bare=ctx.bare,
        state=ctx.state,
    )
    sql, kind = _compile(node, sub)
    return sql, kind, sub.params


def _binary(node: Node, ctx: _Ctx) -> Compiled:
    op = node.value
    a, b = node.args
    ls, lt, lp = _isolated(a, ctx)
    rs, rt, rp = _isolated(b, ctx)
    if op in ("=", "<>", "<", "<=", ">", ">="):
        # A date compared with a quoted date ('2026-01-31') compares as dates.
        if lt == "date" and b.kind == "str":
            rp = []
            rs, rt = _date_literal(b, rp), "date"
        elif rt == "date" and a.kind == "str":
            lp = []
            ls, lt = _date_literal(a, lp), "date"
    ctx.params.extend([*lp, *rp])  # in the order they appear in the SQL text
    return _combine(op, ls, lt, rs, rt)


def _combine(op: str, ls: str, lt: str, rs: str, rt: str) -> Compiled:
    if op in ("AND", "OR"):
        _need("boolean", lt, op)
        _need("boolean", rt, op)
        return f"({ls} {op} {rs})", "boolean"
    if op == "&":
        left, right = f"COALESCE(CAST({ls} AS VARCHAR), '')", f"COALESCE(CAST({rs} AS VARCHAR), '')"
        return f"({left} || {right})", "string"
    if op in ("=", "<>", "<", "<=", ">", ">="):
        both = {lt, rt} - {"null"}
        if len(both) > 1 and not both <= set(NUMERIC):
            raise CalcError(f"Cannot compare {_describe(lt)} with {_describe(rt)}")
        return f"({ls} {op} {rs})", "boolean"
    # arithmetic
    if op in ("+", "-") and lt == "date" and rt in (*NUMERIC, "null"):
        return f"CAST({ls} {op} CAST({rs} AS INTEGER) AS DATE)", "date"  # date ± days
    if op == "-" and lt == "date" and rt == "date":
        return f"date_diff('day', {rs}, {ls})", "integer"
    _need("number", lt, f"'{op}'")
    _need("number", rt, f"'{op}'")
    if op == "/":
        return f"(CAST({ls} AS DOUBLE) / NULLIF({rs}, 0))", "float"
    if op == "%":
        return f"({ls} % NULLIF({rs}, 0))", _num_type(lt, rt)
    return f"({ls} {op} {rs})", _num_type(lt, rt)


def _date_literal(node: Node, params: list[Any]) -> str:
    text = str(node.value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise CalcError(f"'{text}' is not a date: write dates as 'YYYY-MM-DD'")
    import datetime as _dt

    try:
        day = _dt.date.fromisoformat(text)
    except ValueError as exc:
        raise CalcError(f"'{text}' is not a real date") from exc
    params.append(day.isoformat())
    return "CAST(? AS DATE)"


Fn = Callable[[list[Compiled], _Ctx], Compiled]


def _arity(name: str, args: list[Compiled], low: int, high: int | None = None) -> None:
    high = low if high is None else high
    if not low <= len(args) <= high:
        want = str(low) if low == high else f"{low} to {high}"
        raise CalcError(f"{name}() takes {want} value{'s' if high != 1 else ''}, not {len(args)}")


def _math(name: str, sql: str) -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 1)
        _need("number", args[0][1], f"{name}()")
        return sql.format(args[0][0]), args[0][1] if name == "ABS" else "integer"

    return fn


def _round(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("ROUND", args, 1, 2)
    _need("number", args[0][1], "ROUND()")
    if len(args) == 1:
        return f"ROUND({args[0][0]})", "integer" if args[0][1] == "integer" else "float"
    _need("number", args[1][1], "ROUND() digits")
    return f"ROUND({args[0][0]}, CAST({args[1][0]} AS INTEGER))", "float"


def _date_part(name: str, part: str) -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 1)
        _need("date", args[0][1], f"{name}()")
        return f"CAST(date_part('{part}', {args[0][0]}) AS BIGINT)", "integer"

    return fn


def _text(name: str, sql: str, result: str = "string") -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 1)
        _need("string", args[0][1], f"{name}()")
        return sql.format(args[0][0]), result

    return fn


def _left_right(name: str) -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 2)
        _need("string", args[0][1], f"{name}()")
        _need("number", args[1][1], f"{name}() length")
        n = f"GREATEST(CAST({args[1][0]} AS INTEGER), 0)"
        return f"{name.lower()}({args[0][0]}, {n})", "string"

    return fn


def _contains(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("CONTAINS", args, 2)
    _need("string", args[0][1], "CONTAINS()")
    _need("string", args[1][1], "CONTAINS()")
    return f"contains(lower({args[0][0]}), lower({args[1][0]}))", "boolean"


def _if(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("IF", args, 2, 3)
    _need("boolean", args[0][1], "IF() condition")
    other = args[2] if len(args) == 3 else ("NULL", "null")
    t = _common([args[1][1], other[1]], "IF()")
    return f"(CASE WHEN {args[0][0]} THEN {args[1][0]} ELSE {other[0]} END)", t


def _coalesce(args: list[Compiled], ctx: _Ctx) -> Compiled:
    if len(args) < 2:
        raise CalcError("COALESCE() takes at least 2 values")
    t = _common([a[1] for a in args], "COALESCE()")
    return f"COALESCE({', '.join(a[0] for a in args)})", t


def _concat(args: list[Compiled], ctx: _Ctx) -> Compiled:
    if not args:
        raise CalcError("CONCAT() takes at least 1 value")
    parts = ", ".join(f"COALESCE(CAST({a[0]} AS VARCHAR), '')" for a in args)
    return f"concat({parts})", "string"


def _days_between(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("DAYS_BETWEEN", args, 2)
    _need("date", args[0][1], "DAYS_BETWEEN()")
    _need("date", args[1][1], "DAYS_BETWEEN()")
    return f"date_diff('day', {args[0][0]}, {args[1][0]})", "integer"


def _is_empty(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("ISEMPTY", args, 1)
    return f"({args[0][0]} IS NULL)", "boolean"


FUNCTIONS: dict[str, Fn] = {
    "ROUND": _round,
    "ABS": _math("ABS", "ABS({})"),
    "FLOOR": _math("FLOOR", "CAST(FLOOR({}) AS BIGINT)"),
    "CEIL": _math("CEIL", "CAST(CEIL({}) AS BIGINT)"),
    "IF": _if,
    "COALESCE": _coalesce,
    "ISEMPTY": _is_empty,
    "YEAR": _date_part("YEAR", "year"),
    "QUARTER": _date_part("QUARTER", "quarter"),
    "MONTH": _date_part("MONTH", "month"),
    "DAY": _date_part("DAY", "day"),
    "WEEKDAY": _date_part("WEEKDAY", "isodow"),
    "DAYS_BETWEEN": _days_between,
    "UPPER": _text("UPPER", "upper({})"),
    "LOWER": _text("LOWER", "lower({})"),
    "TRIM": _text("TRIM", "trim({})"),
    "LEN": _text("LEN", "CAST(length({}) AS BIGINT)", "integer"),
    "LEFT": _left_right("LEFT"),
    "RIGHT": _left_right("RIGHT"),
    "CONTAINS": _contains,
    "CONCAT": _concat,
}


def _agg_number(name: str, sql: str, keep_type: bool) -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 1)
        _need("number", args[0][1], f"{name}()")
        kind = args[0][1] if keep_type and args[0][1] in NUMERIC else "float"
        return sql.format(args[0][0]), kind

    return fn


def _agg_order(name: str) -> Fn:
    def fn(args: list[Compiled], ctx: _Ctx) -> Compiled:
        _arity(name, args, 1)
        if args[0][1] == "boolean":
            raise CalcError(f"{name}() needs numbers, dates or text, not true/false")
        return f"{name}({args[0][0]})", args[0][1]

    return fn


def _count(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("COUNT", args, 0, 1)
    return (f"COUNT({args[0][0]})" if args else "COUNT(*)"), "integer"


def _countd(args: list[Compiled], ctx: _Ctx) -> Compiled:
    _arity("COUNTD", args, 1)
    return f"COUNT(DISTINCT {args[0][0]})", "integer"


AGGREGATES: dict[str, Fn] = {
    "SUM": _agg_number("SUM", "SUM({})", keep_type=True),
    "AVG": _agg_number("AVG", "AVG({})", keep_type=False),
    "MEDIAN": _agg_number("MEDIAN", "MEDIAN({})", keep_type=False),
    "MIN": _agg_order("MIN"),
    "MAX": _agg_order("MAX"),
    "COUNT": _count,
    "COUNTD": _countd,
}


def _call(node: Node, ctx: _Ctx) -> Compiled:
    if node.value in AGGREGATES:
        if ctx.depth:
            raise CalcError(f"{node.value}() cannot go inside another aggregate")
        ctx.depth += 1
        try:
            args = [_compile(a, ctx) for a in node.args]
        finally:
            ctx.depth -= 1
        ctx.state["aggregate"] = True
        return AGGREGATES[node.value](args, ctx)
    args = [_compile(a, ctx) for a in node.args]
    return FUNCTIONS[node.value](args, ctx)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Calculation:
    """A checked calculated field, ready to add to a query."""

    name: str
    expression: str
    type: str
    sql: str
    params: tuple[Any, ...]
    uses: frozenset[str] = frozenset()  # the columns and fields it reads
    aggregate: bool = False  # a measure: SQL is an aggregate over a group's rows


@dataclass(frozen=True)
class Formula:
    sql: str
    type: str
    params: list[Any]
    uses: set[str]
    aggregate: bool


def compile_formula(
    text: str,
    columns: dict[str, str],
    aggregates: dict[str, Calculation] | None = None,
) -> Formula:
    """Check and compile a formula over ``columns`` (name → type) and aggregate fields."""
    ctx = _Ctx(
        columns=dict(columns),
        params=[],
        aggregates={c.name: (c.sql, c.type, c.params, c.uses) for c in (aggregates or {}).values()},
    )
    sql, t = _compile(parse(text), ctx)
    if t == "null":
        raise CalcError("The formula is always empty")
    aggregate = bool(ctx.state.get("aggregate"))
    if aggregate and ctx.bare:
        cols = ", ".join(f"[{c}]" for c in sorted(ctx.bare))
        raise CalcError(
            f"In a formula with SUM() or another aggregate, every column must be inside one: {cols}"
        )
    return Formula(sql, t, ctx.params, ctx.used, aggregate)


def compile_expression(text: str, columns: dict[str, str]) -> tuple[str, str, list[Any], set[str]]:
    """``(sql, type, params, used columns)`` for a row-level formula (no aggregate fields)."""
    f = compile_formula(text, columns)
    return f.sql, f.type, f.params, f.uses


def check_name(name: str, taken: set[str]) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise CalcError("Give the calculated field a name")
    if len(name) > 120:
        raise CalcError("Names can be at most 120 characters")
    if name.startswith("__"):
        raise CalcError("Names cannot start with two underscores")
    if name.casefold() in {t.casefold() for t in taken}:
        raise CalcError(f"There is already a column or field called {name}")
    return name


def build(
    definitions: list[dict[str, Any]], columns: dict[str, str], *, strict: bool = True
) -> list[Calculation]:
    """Check a dataset's calculated fields in order; each may use the ones before it.

    ``strict=False`` (when querying) skips fields that no longer check — a column was
    renamed in a refresh, say — so charts that do not use them keep working.
    """
    if strict and len(definitions) > MAX_CALCULATIONS:
        raise CalcError(f"A dataset can have at most {MAX_CALCULATIONS} calculated fields")
    known = dict(columns)
    aggregates: dict[str, Calculation] = {}
    out: list[Calculation] = []
    for d in definitions[:MAX_CALCULATIONS]:
        try:
            name = check_name(str(d.get("name", "")), set(known) | set(aggregates))
            expression = str(d.get("expression", "")).strip()
            try:
                f = compile_formula(expression, known, aggregates)
            except CalcError as exc:
                raise CalcError(f"{name}: {exc}") from exc
        except CalcError:
            if strict:
                raise
            continue
        calc = Calculation(
            name, expression, f.type, f.sql, tuple(f.params), frozenset(f.uses), f.aggregate
        )
        out.append(calc)
        if f.aggregate:
            aggregates[name] = calc
        else:
            known[name] = f.type
    return out


def needed(calculations: list[Calculation], names: set[str]) -> list[Calculation]:
    """The calculations a query reads, with the ones they depend on, in definition order."""
    by_name = {c.name: c for c in calculations}
    want: set[str] = set()
    stack = [n for n in names if n in by_name]
    while stack:
        n = stack.pop()
        if n in want:
            continue
        want.add(n)
        stack.extend(u for u in by_name[n].uses if u in by_name)
    return [c for c in calculations if c.name in want]
