"""Safe evaluation of STE Slicer setting formulas such as ``machine_height if printing_mode
== 'classic' else 231.1``.

Formulas come from the slicer definitions. They are parsed with ``ast`` and only a small
expression language is evaluated: constants, lists, boolean logic, arithmetic, comparisons,
conditional expressions, setting names and the slicer's own lookup functions. Anything else
raises ``FormulaError``; nothing from a definition is ever executed.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

Lookup = Callable[[str], Any]


class FormulaError(ValueError):
    pass


_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_COMPARE: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.Gt: operator.gt,
    ast.LtE: operator.le,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
}
_BUILTINS: dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "int": int,
    "float": float,
    "sum": sum,
    "any": any,
    "all": all,
    # The extruder the slicer gives a setting by default, the only active one.
    "defaultExtruderPosition": lambda: "0",
}
_MATH: dict[str, Callable[..., Any]] = {
    "ceil": math.ceil,
    "floor": math.floor,
    "sqrt": math.sqrt,
    "log": math.log,
    "tan": math.tan,
    "radians": math.radians,
}
_LITERALS = {"True": True, "False": False, "None": None}
# The slicer's lookups name the setting in their last argument; the extruder index is ignored
# because the printer has one active extruder.
_LOOKUPS = {"resolveOrValue", "extruderValue", "extruderValues"}


def evaluate(expression: str, lookup: Lookup) -> Any:
    """Evaluate a definition formula; ``lookup`` returns the value of another setting."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as error:
        raise FormulaError(f"формула не разбирается: {expression!r}") from error
    return _Evaluator(lookup).visit(tree.body)


class _Evaluator:
    def __init__(self, lookup: Lookup):
        self.lookup = lookup
        self.handlers: dict[type[ast.expr], Callable[[Any], Any]] = {
            ast.Constant: lambda node: node.value,
            ast.List: self._sequence,
            ast.Tuple: self._sequence,
            ast.BoolOp: self._bool_op,
            ast.UnaryOp: self._unary,
            ast.BinOp: self._binary,
            ast.Compare: self._compare,
            ast.IfExp: self._conditional,
            ast.Name: self._name,
            ast.Call: self._call,
        }

    def visit(self, node: ast.expr) -> Any:
        handler = self.handlers.get(type(node))
        if handler is None:
            raise FormulaError(f"неподдерживаемое выражение: {type(node).__name__}")
        return handler(node)

    def _sequence(self, node: ast.List | ast.Tuple) -> list[Any]:
        return [self.visit(element) for element in node.elts]

    def _bool_op(self, node: ast.BoolOp) -> bool:
        values = [self.visit(value) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)

    def _unary(self, node: ast.UnaryOp) -> Any:
        return _pick(_UNARY, node.op, "унарная операция")(self.visit(node.operand))

    def _binary(self, node: ast.BinOp) -> Any:
        apply = _pick(_BINARY, node.op, "арифметическая операция")
        return apply(self.visit(node.left), self.visit(node.right))

    def _compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if not _pick(_COMPARE, op, "сравнение")(left, right):
                return False
            left = right
        return True

    def _conditional(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def _name(self, node: ast.Name) -> Any:
        if node.id in _LITERALS:
            return _LITERALS[node.id]
        return self.lookup(node.id)

    def _call(self, node: ast.Call) -> Any:
        arguments = [self.visit(argument) for argument in node.args]
        function = _function(node.func)
        if function in _LOOKUPS:
            value = self.lookup(arguments[-1])
            return [value] if function == "extruderValues" else value
        if function in _BUILTINS:
            return _BUILTINS[function](*arguments)
        return _MATH[function.removeprefix("math.")](*arguments)


def _pick(table: dict[type, Callable[..., Any]], op: object, kind: str) -> Callable[..., Any]:
    if type(op) not in table:
        raise FormulaError(f"неподдерживаемая {kind}: {type(op).__name__}")
    return table[type(op)]


def _function(func: ast.expr) -> str:
    """Name of a call the language allows: a lookup, a builtin or ``math.<name>``."""
    if isinstance(func, ast.Name) and (func.id in _LOOKUPS or func.id in _BUILTINS):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return _math(func.value.id, func.attr)
    raise FormulaError("неподдерживаемый вызов функции")


def _math(module: str, name: str) -> str:
    if module != "math" or name not in _MATH:
        raise FormulaError(f"неподдерживаемый вызов функции {module}.{name}")
    return f"math.{name}"
