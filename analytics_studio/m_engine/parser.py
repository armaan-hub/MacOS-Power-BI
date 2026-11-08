"""Recursive-descent parser for Power Query M (Power Query M language specification).

Precedence, lowest to highest (each level's operands are the next level):

  expression      each, let, if, error, try, function literal (not operands of binary operators)
  or              or
  and             and
  is              x is T
  as              x as T
  equality        =  <>
  relational      <  <=  >  >=
  additive        +  -  &
  multiplicative  *  /
  metadata        x meta y
  unary           +x  -x  not x  type T
  postfix         x[f]  x[f]?  x{i}  x{i}?  x[[a],[b]]  x(args)
  primary         literals, names, (e), [record], {list}

Because ``error`` and the other expression-level forms are not operands of a
binary operator, ``true or error "x"`` is a syntax error, as in Power BI.
"""

from __future__ import annotations

from typing import Optional

from . import ast as A
from .lexer import MSyntaxError, Token, tokenize

PRIMITIVE_TYPES = frozenset({
    "any", "anynonnull", "binary", "date", "datetime", "datetimezone", "duration",
    "function", "list", "logical", "none", "null", "number", "record", "table",
    "text", "time", "type",
})


def parse(source: str) -> A.Node:
    """Parse one complete M expression. Trailing tokens are a syntax error."""
    return _Parser(source).document()


class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    # ---- token helpers ---------------------------------------------------

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def at_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok.kind == "op" and tok.text in ops

    def at_kw(self, *words: str) -> bool:
        tok = self.peek()
        return tok.kind == "keyword" and tok.text in words

    def at_ident(self, word: str) -> bool:
        tok = self.peek()
        return tok.kind == "ident" and tok.text == word

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            self.fail(f"Expected '{op}'")
        return self.advance()

    def expect_kw(self, word: str) -> Token:
        if not self.at_kw(word):
            self.fail(f"Expected '{word}'")
        return self.advance()

    def fail(self, message: str) -> None:
        tok = self.peek()
        found = "end of input" if tok.kind == "eof" else f"'{tok.text}'"
        raise MSyntaxError(f"{message}, found {found}", tok.position, self.source)

    def identifier_name(self) -> str:
        tok = self.peek()
        if tok.kind != "ident":
            self.fail("Expected an identifier")
        self.advance()
        return str(tok.value)

    def _take_optional(self) -> bool:
        if self.at_op("?"):
            self.advance()
            return True
        return False

    # ---- document and expressions ----------------------------------------

    def document(self) -> A.Node:
        node = self.expression()
        if self.peek().kind != "eof":
            self.fail("Unexpected token after the end of the expression")
        return node

    def expression(self) -> A.Node:
        tok = self.peek()
        if tok.kind == "keyword":
            if tok.text == "each":
                self.advance()
                return A.EachExpr(self.expression())
            if tok.text == "let":
                return self.let_expression()
            if tok.text == "if":
                return self.if_expression()
            if tok.text == "error":
                self.advance()
                return A.ErrorExpr(self.expression())
            if tok.text == "try":
                return self.try_expression()
        if tok.kind == "op" and tok.text == "(":
            literal = self._try_function_literal()
            if literal is not None:
                return literal
        return self.logical_or()

    def _matching_paren(self, index: int) -> Optional[int]:
        depth = 0
        for k in range(index, len(self.tokens)):
            tok = self.tokens[k]
            if tok.kind == "eof":
                return None
            if tok.kind == "op" and tok.text == "(":
                depth += 1
            elif tok.kind == "op" and tok.text == ")":
                depth -= 1
                if depth == 0:
                    return k
        return None

    def _try_function_literal(self) -> Optional[A.Node]:
        close = self._matching_paren(self.i)
        if close is None or close + 1 >= len(self.tokens):
            return None
        after = self.tokens[close + 1]
        if after.kind == "op" and after.text == "=>":
            params, return_type = self._function_header()
            self.expect_op("=>")
            return A.FunctionLiteral(params, return_type, self.expression())
        if after.kind == "keyword" and after.text == "as":
            # "(x) as number" may also be a parenthesised expression; backtrack if no "=>".
            save = self.i
            try:
                params, return_type = self._function_header()
                matched = self.at_op("=>")
            except MSyntaxError:
                matched = False
            if matched:
                self.advance()
                return A.FunctionLiteral(params, return_type, self.expression())
            self.i = save
        return None

    def _function_header(self) -> tuple[tuple[A.Param, ...], Optional[A.Node]]:
        self.expect_op("(")
        params: list[A.Param] = []
        if not self.at_op(")"):
            while True:
                params.append(self.parameter())
                if not self.at_op(","):
                    break
                self.advance()
        self.expect_op(")")
        return_type = None
        if self.at_kw("as"):
            self.advance()
            return_type = self.nullable_primitive_type()
        return tuple(params), return_type

    def parameter(self) -> A.Param:
        optional = False
        if self.at_kw("optional"):
            self.advance()
            optional = True
        name = self.identifier_name()
        type_ = None
        if self.at_kw("as"):
            self.advance()
            type_ = self.nullable_primitive_type()
        return A.Param(name, type_, optional)

    def let_expression(self) -> A.Node:
        self.advance()  # let
        bindings: list[A.LetBinding] = []
        while True:
            name = self.identifier_name()
            self.expect_op("=")
            bindings.append(A.LetBinding(name, self.expression()))
            if not self.at_op(","):
                break
            self.advance()
        self.expect_kw("in")
        return A.LetExpr(tuple(bindings), self.expression())

    def if_expression(self) -> A.Node:
        self.advance()  # if
        condition = self.expression()
        self.expect_kw("then")
        then_branch = self.expression()
        self.expect_kw("else")
        return A.IfExpr(condition, then_branch, self.expression())

    def try_expression(self) -> A.Node:
        self.advance()  # try
        operand = self.expression()
        otherwise = None
        catch = None
        if self.at_kw("otherwise"):
            self.advance()
            otherwise = self.expression()
        elif self.at_ident("catch"):
            self.advance()
            catch = self.expression()
        return A.TryExpr(operand, otherwise, catch)

    # ---- operator levels --------------------------------------------------

    def logical_or(self) -> A.Node:
        left = self.logical_and()
        while self.at_kw("or"):
            self.advance()
            left = A.BinaryOp("or", left, self.logical_and())
        return left

    def logical_and(self) -> A.Node:
        left = self.is_expression()
        while self.at_kw("and"):
            self.advance()
            left = A.BinaryOp("and", left, self.is_expression())
        return left

    def is_expression(self) -> A.Node:
        left = self.as_expression()
        while self.at_kw("is"):
            self.advance()
            left = A.TypeOp("is", left, self.nullable_primitive_type())
        return left

    def as_expression(self) -> A.Node:
        left = self.equality()
        while self.at_kw("as"):
            self.advance()
            left = A.TypeOp("as", left, self.nullable_primitive_type())
        return left

    def equality(self) -> A.Node:
        left = self.relational()
        while self.at_op("=", "<>"):
            op = self.advance().text
            left = A.BinaryOp(op, left, self.relational())
        return left

    def relational(self) -> A.Node:
        left = self.additive()
        while self.at_op("<", "<=", ">", ">="):
            op = self.advance().text
            left = A.BinaryOp(op, left, self.additive())
        return left

    def additive(self) -> A.Node:
        left = self.multiplicative()
        while self.at_op("+", "-", "&"):
            op = self.advance().text
            left = A.BinaryOp(op, left, self.multiplicative())
        return left

    def multiplicative(self) -> A.Node:
        left = self.metadata()
        while self.at_op("*", "/"):
            op = self.advance().text
            left = A.BinaryOp(op, left, self.metadata())
        return left

    def metadata(self) -> A.Node:
        left = self.unary()
        while self.at_kw("meta"):
            self.advance()
            left = A.BinaryOp("meta", left, self.unary())
        return left

    def unary(self) -> A.Node:
        if self.at_op("+", "-"):
            op = self.advance().text
            return A.UnaryOp(op, self.unary())
        if self.at_kw("not"):
            self.advance()
            return A.UnaryOp("not", self.unary())
        if self.at_kw("type"):
            self.advance()
            return A.TypeLiteral(self.type_expression())
        return self.postfix(self.primary())

    # ---- postfix and primary ----------------------------------------------

    def postfix(self, node: A.Node) -> A.Node:
        while True:
            tok = self.peek()
            if tok.kind == "field":
                self.advance()
                node = A.FieldAccess(node, str(tok.value), self._take_optional())
            elif self.at_op("{"):
                self.advance()
                index = self.expression()
                self.expect_op("}")
                node = A.ItemAccess(node, index, self._take_optional())
            elif self.at_op("("):
                self.advance()
                args: list[A.Node] = []
                if not self.at_op(")"):
                    while True:
                        args.append(self.expression())
                        if not self.at_op(","):
                            break
                        self.advance()
                self.expect_op(")")
                node = A.Invocation(node, tuple(args))
            elif self.at_op("["):
                self.advance()
                names: list[str] = []
                while True:
                    field = self.peek()
                    if field.kind != "field":
                        self.fail("Expected a [field] selector in projection")
                    self.advance()
                    names.append(str(field.value))
                    if not self.at_op(","):
                        break
                    self.advance()
                self.expect_op("]")
                node = A.Projection(node, tuple(names), self._take_optional())
            else:
                return node

    def primary(self) -> A.Node:
        tok = self.peek()
        if tok.kind == "number":
            self.advance()
            return A.NumberLiteral(tok.text, tok.value)  # type: ignore[arg-type]
        if tok.kind == "text":
            self.advance()
            return A.TextLiteral(str(tok.value))
        if tok.kind == "keyword" and tok.text in ("true", "false"):
            self.advance()
            return A.LogicalLiteral(tok.text == "true")
        if tok.kind == "keyword" and tok.text == "null":
            self.advance()
            return A.NullLiteral()
        if tok.kind == "ident":
            self.advance()
            if tok.text in ("#infinity", "#nan"):
                return A.SpecialLiteral(tok.text[1:])
            return A.Identifier(str(tok.value))
        if tok.kind == "field":
            self.advance()
            return A.FieldSelector(str(tok.value))
        if self.at_op("@"):
            self.advance()
            if self.peek().kind != "ident":
                self.fail("Expected an identifier after '@'")
            return A.Identifier(str(self.advance().value), inclusive=True)
        if self.at_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        if self.at_op("["):
            return self.record_expression()
        if self.at_op("{"):
            return self.list_expression()
        self.fail("Expected an expression")
        raise AssertionError("unreachable")

    def record_expression(self) -> A.Node:
        self.advance()  # [
        if self.at_op("]"):
            self.advance()
            return A.RecordExpr(())
        fields: list[A.RecordField] = []
        while True:
            name = self.identifier_name()
            self.expect_op("=")
            fields.append(A.RecordField(name, self.expression()))
            if not self.at_op(","):
                break
            self.advance()
        self.expect_op("]")
        return A.RecordExpr(tuple(fields))

    def list_expression(self) -> A.Node:
        self.advance()  # {
        items: list[A.Node] = []
        if not self.at_op("}"):
            while True:
                first = self.expression()
                if self.at_op(".."):
                    self.advance()
                    items.append(A.ListRange(first, self.expression()))
                else:
                    items.append(first)
                if not self.at_op(","):
                    break
                self.advance()
        self.expect_op("}")
        return A.ListExpr(tuple(items))

    # ---- type expressions -------------------------------------------------

    def nullable_primitive_type(self) -> A.Node:
        """The type after ``as`` / ``is`` and in parameter or return positions."""
        nullable = False
        if self.at_ident("nullable"):
            self.advance()
            nullable = True
        tok = self.peek()
        if tok.kind not in ("ident", "keyword") or tok.text not in PRIMITIVE_TYPES:
            self.fail("Expected a primitive type")
        self.advance()
        node: A.Node = A.PrimitiveType(tok.text)
        return A.NullableType(node) if nullable else node

    def type_expression(self) -> A.Node:
        if self.at_ident("nullable"):
            self.advance()
            return A.NullableType(self.type_expression())
        if self.at_op("{"):
            self.advance()
            item = self.type_expression()
            self.expect_op("}")
            return A.ListType(item)
        if self.at_op("["):
            return self.record_type()
        tok = self.peek()
        if tok.kind in ("ident", "keyword") and tok.text in PRIMITIVE_TYPES:
            self.advance()
            if tok.text == "table" and self.at_op("["):
                return A.TableType(self.record_type())
            if tok.text == "function" and self.at_op("("):
                params, return_type = self._function_header()
                return A.FunctionType(params, return_type)
            return A.PrimitiveType(tok.text)
        self.fail("Expected a type")
        raise AssertionError("unreachable")

    def record_type(self) -> A.RecordType:
        self.expect_op("[")
        fields: list[A.TypeField] = []
        if self.at_op("]"):
            self.advance()
            return A.RecordType(())
        while True:
            optional = False
            if self.at_kw("optional"):
                self.advance()
                optional = True
            name = self.identifier_name()
            self.expect_op("=")
            fields.append(A.TypeField(name, self.type_expression(), optional))
            if not self.at_op(","):
                break
            self.advance()
        self.expect_op("]")
        return A.RecordType(tuple(fields))
