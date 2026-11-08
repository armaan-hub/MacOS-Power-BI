"""AST node kinds for Power Query M expressions and type expressions.

Every node is a frozen dataclass. Child collections are tuples so trees are
hashable and safe to share. Operators are stored as their source text
("or", "and", "=", "<>", "+", "&", "meta", ...). No evaluation happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


class Node:
    """Base class of every expression and type node."""


# ---- literals and names -------------------------------------------------

@dataclass(frozen=True)
class NumberLiteral(Node):
    text: str
    value: Union[int, float]


@dataclass(frozen=True)
class TextLiteral(Node):
    value: str


@dataclass(frozen=True)
class LogicalLiteral(Node):
    value: bool


@dataclass(frozen=True)
class NullLiteral(Node):
    pass


@dataclass(frozen=True)
class SpecialLiteral(Node):
    """``#infinity`` or ``#nan`` (name is "infinity" or "nan")."""
    name: str


@dataclass(frozen=True)
class Identifier(Node):
    """A name reference; ``inclusive`` is True for ``@name``. ``_`` is an ordinary name."""
    name: str
    inclusive: bool = False


@dataclass(frozen=True)
class FieldSelector(Node):
    """Implicit-target field selector ``[name]`` (means ``_[name]`` inside ``each``)."""
    name: str


# ---- constructors -------------------------------------------------------

@dataclass(frozen=True)
class RecordField:
    name: str
    value: Node


@dataclass(frozen=True)
class RecordExpr(Node):
    fields: tuple[RecordField, ...]


@dataclass(frozen=True)
class ListRange(Node):
    """A ``start..end`` item inside a list expression."""
    start: Node
    end: Node


@dataclass(frozen=True)
class ListExpr(Node):
    items: tuple[Node, ...]


# ---- operators ----------------------------------------------------------

@dataclass(frozen=True)
class UnaryOp(Node):
    op: str  # "+", "-", "not"
    operand: Node


@dataclass(frozen=True)
class BinaryOp(Node):
    op: str  # or and = <> < <= > >= + - & * / meta
    left: Node
    right: Node


@dataclass(frozen=True)
class TypeOp(Node):
    """``operand is T`` or ``operand as T``."""
    op: str  # "is" or "as"
    operand: Node
    type_: Node


@dataclass(frozen=True)
class TypeLiteral(Node):
    """``type T`` evaluates to a type value."""
    type_: Node


# ---- postfix ------------------------------------------------------------

@dataclass(frozen=True)
class FieldAccess(Node):
    target: Node
    name: str
    optional: bool = False


@dataclass(frozen=True)
class ItemAccess(Node):
    target: Node
    index: Node
    optional: bool = False


@dataclass(frozen=True)
class Projection(Node):
    """``target[[a],[b]]``."""
    target: Node
    names: tuple[str, ...]
    optional: bool = False


@dataclass(frozen=True)
class Invocation(Node):
    target: Node
    args: tuple[Node, ...]


# ---- functions and control flow ----------------------------------------

@dataclass(frozen=True)
class EachExpr(Node):
    body: Node


@dataclass(frozen=True)
class Param:
    name: str
    type_: Optional[Node] = None
    optional: bool = False


@dataclass(frozen=True)
class FunctionLiteral(Node):
    params: tuple[Param, ...]
    return_type: Optional[Node]
    body: Node


@dataclass(frozen=True)
class LetBinding:
    name: str
    value: Node


@dataclass(frozen=True)
class LetExpr(Node):
    bindings: tuple[LetBinding, ...]
    body: Node


@dataclass(frozen=True)
class IfExpr(Node):
    condition: Node
    then_branch: Node
    else_branch: Node


@dataclass(frozen=True)
class ErrorExpr(Node):
    operand: Node


@dataclass(frozen=True)
class TryExpr(Node):
    """``try e``, ``try e otherwise f`` or ``try e catch (x) => f``."""
    operand: Node
    otherwise: Optional[Node] = None
    catch: Optional[Node] = None


# ---- type expressions ---------------------------------------------------

@dataclass(frozen=True)
class PrimitiveType(Node):
    name: str  # any, number, text, null, table, ...


@dataclass(frozen=True)
class NullableType(Node):
    inner: Node


@dataclass(frozen=True)
class ListType(Node):
    item: Node


@dataclass(frozen=True)
class TypeField:
    name: str
    type_: Node
    optional: bool = False


@dataclass(frozen=True)
class RecordType(Node):
    fields: tuple[TypeField, ...]


@dataclass(frozen=True)
class TableType(Node):
    row: RecordType


@dataclass(frozen=True)
class FunctionType(Node):
    params: tuple[Param, ...]
    return_type: Optional[Node]
