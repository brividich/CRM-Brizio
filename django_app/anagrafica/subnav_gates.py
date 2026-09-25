"""Cancelli di pagina delle voci della subnav Anagrafica, ricavati in automatico.

Il middleware ACL decide se una route è raggiungibile; molte pagine però hanno
un secondo cancello in-view che rimbalza l'utente anche con l'ACL concessa::

    if not _can_view_formazione(request):
        messages.error(...)
        return redirect(...)

    is_admin = _is_anagrafica_admin(request)
    if not is_admin:
        return redirect(...)

Invece di tenere a mano un elenco route → helper (che si dimentica alla prima
pagina nuova), qui si legge il sorgente della view e si estraggono i cancelli
di questa forma: ``if not <helper>(request, ...)`` al primo livello del corpo,
prima del primo ``return``, con un ``return`` nel ramo. La subnav poi chiama
gli STESSI helper con la request corrente: la regola resta una sola, quella
della view.

Sono riconosciuti solo helper chiamati con ``request`` come primo argomento e
con eventuali altri argomenti costanti o nomi del modulo: niente di ciò che
dipende dai parametri della pagina. Se il sorgente non si legge la voce resta
governata dalla sola ACL.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import textwrap
from functools import lru_cache
from importlib.util import resolve_name
from typing import Callable

from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)

_MISSING = object()


def _local_imports(body) -> dict[str, tuple[str, str]]:
    """``from X import y`` al primo livello della view: nome → (modulo, attributo)."""
    found: dict[str, tuple[str, str]] = {}
    for stmt in body:
        if isinstance(stmt, ast.ImportFrom):
            module = "." * stmt.level + (stmt.module or "")
            for alias in stmt.names:
                found[alias.asname or alias.name] = (module, alias.name)
    return found


def _lookup(name: str, func, local_imports) -> object:
    if name in local_imports:
        module, attr = local_imports[name]
        try:
            package = func.__module__.rpartition(".")[0] or None
            mod = importlib.import_module(resolve_name(module, package) if module.startswith(".") else module)
            return getattr(mod, attr, _MISSING)
        except Exception:
            return _MISSING
    return func.__globals__.get(name, _MISSING)


def _gate_from_call(call, func, local_imports) -> Callable | None:
    """Da ``helper(request, COSTANTE, ...)`` a ``lambda request: helper(request, ...)``."""
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or not call.args:
        return None
    first = call.args[0]
    if not (isinstance(first, ast.Name) and first.id == "request"):
        return None

    def _value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id != "request":
            return _lookup(node.id, func, local_imports)
        return _MISSING

    args = [_value(a) for a in call.args[1:]]
    kwargs = {kw.arg: _value(kw.value) for kw in call.keywords if kw.arg}
    if len(kwargs) != len(call.keywords) or _MISSING in args or _MISSING in kwargs.values():
        return None
    name = call.func.id
    if not callable(_lookup(name, func, local_imports)):
        return None

    def gate(request):
        # Risolto a ogni chiamata: vale l'helper del modulo della view in quel momento.
        return _lookup(name, func, local_imports)(request, *args, **kwargs)

    gate.__name__ = name
    return gate


@lru_cache(maxsize=None)
def page_gates(func) -> tuple[Callable, ...]:
    """I cancelli di pagina della view ``func`` (vuoto se non ne ha o non si legge)."""
    func = inspect.unwrap(func)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError, SyntaxError):
        return ()
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None:
        return ()

    local_imports = _local_imports(fn.body)
    assigned: dict[str, ast.AST] = {}
    gates: list[Callable] = []
    for stmt in fn.body:
        if isinstance(stmt, ast.Return):
            break  # oltre il primo return la pagina è già stata servita
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            assigned[stmt.targets[0].id] = stmt.value
            continue
        if not (
            isinstance(stmt, ast.If)
            and not stmt.orelse
            and isinstance(stmt.test, ast.UnaryOp)
            and isinstance(stmt.test.op, ast.Not)
            and any(isinstance(s, ast.Return) for s in stmt.body)
        ):
            continue
        operand = stmt.test.operand
        if isinstance(operand, ast.Name):
            operand = assigned.get(operand.id)
        gate = _gate_from_call(operand, func, local_imports)
        if gate is not None:
            gates.append(gate)
    return tuple(gates)


def section_gate_allows(request, path: str) -> bool:
    """True se i cancelli in-view della pagina ``path`` lasciano passare l'utente.

    Pagina senza cancelli riconosciuti → True (decide solo l'ACL). Fail-closed
    se un helper esplode: meglio una voce in meno che un link che rimbalza.
    """
    try:
        match = resolve(path)
    except Resolver404:
        return True
    try:
        gates = page_gates(match.func)
    except Exception:
        logger.exception("Subnav anagrafica: lettura cancelli fallita per %s", match.view_name)
        return True
    for gate in gates:
        try:
            if not gate(request):
                return False
        except Exception:
            logger.exception(
                "Subnav anagrafica: cancello %s fallito per %s", gate.__name__, match.view_name
            )
            return False
    return True
