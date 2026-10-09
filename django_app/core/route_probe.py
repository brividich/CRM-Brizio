"""Enumerazione delle route per i guardrail di sicurezza (audit 09/10, Fase 3).

Usato dai test ``core.test_security_audit_fase3``: genera un path d'esempio per
ogni pattern (convertitori riempiti con valori sintetici) per verificare che le
route esenti dal login non rispondano 200 a un anonimo e che le route con un id
non espongano oggetti a un utente senza permessi.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from django.urls import URLPattern, URLResolver, get_resolver

_SAMPLES = {
    "int": "1",
    "str": "x",
    "slug": "x",
    "uuid": str(uuid.UUID(int=1)),
    "path": "x/y",
}
_CONVERTER_RE = re.compile(r"<(?:(?P<conv>[a-z_]+):)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")


@dataclass(frozen=True)
class RouteSample:
    route: str  # pattern completo, es. "assets/<int:pk>/"
    path: str  # path d'esempio, es. "/assets/1/"
    name: str  # namespace:nome o "" se anonima
    view: str  # modulo.funzione della view
    has_int_param: bool


def _view_label(callback) -> str:
    view_class = getattr(callback, "view_class", None)
    target = view_class or callback
    module = getattr(target, "__module__", "") or ""
    name = getattr(target, "__qualname__", None) or getattr(target, "__name__", "") or repr(target)
    return f"{module}.{name}"


def _sample_route(route: str) -> tuple[str, bool] | None:
    has_int = False

    def repl(match):
        nonlocal has_int
        conv = match.group("conv") or "str"
        if conv == "int":
            has_int = True
        return _SAMPLES.get(conv, "x")

    if "(?P<" in route or route.startswith("^"):
        return None  # re_path: niente campione affidabile
    sample = _CONVERTER_RE.sub(repl, route)
    return "/" + sample.lstrip("/"), has_int


def iter_route_samples() -> list[RouteSample]:
    samples: list[RouteSample] = []

    def walk(patterns, prefix: str, namespace: str):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                ns = namespace
                if entry.namespace:
                    ns = f"{namespace}:{entry.namespace}" if namespace else entry.namespace
                walk(entry.url_patterns, prefix + str(entry.pattern), ns)
            elif isinstance(entry, URLPattern):
                route = prefix + str(entry.pattern)
                sampled = _sample_route(route)
                if sampled is None:
                    continue
                path, has_int = sampled
                name = entry.name or ""
                if name and namespace:
                    name = f"{namespace}:{name}"
                samples.append(RouteSample(route, path, name, _view_label(entry.callback), has_int))

    walk(get_resolver().url_patterns, "", "")
    return samples
