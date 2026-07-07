"""Aggancio dei documenti procedura alla Bacheca «Documenti & Collegamenti».

Costruisce **al volo** un gruppo virtuale (stessa forma di ``core.hub_bacheca``)
dai ``ProcedureDocument`` con revisione corrente, così i documenti SGI diventano
consultabili dalla home/bacheca **senza** duplicarli come righe ``HubLink``.

Visibilità (decisione utente): tutti i dipendenti autenticati, **esclusi i
sensibili** — stesso perimetro del RAG: flag ``escludi_dal_rag`` o deny-list
keyword (``OLLAMA_RAG_SGI_EXCLUDE``, es. roster operatori/skill matrix).

Il builder vive qui (in ``procedure_refresh``) ed è chiamato dalle view di
``dashboard``: ``core/hub_bacheca.py`` resta indipendente da questo modulo.
"""
from __future__ import annotations

from django.conf import settings
from django.urls import reverse


def _deny_patterns() -> list[str]:
    """Deny-list keyword condivisa col RAG (OLLAMA_RAG_SGI_EXCLUDE), lower-case."""
    raw = getattr(settings, "OLLAMA_RAG_SGI_EXCLUDE", []) or []
    if isinstance(raw, str):
        raw = raw.split(";")
    return [str(p).strip().lower() for p in raw if str(p).strip()]


def documento_e_sensibile(doc) -> bool:
    """True se il documento NON va mostrato in bacheca (né al RAG): flag
    ``escludi_dal_rag`` oppure codice/titolo in deny-list roster operatori."""
    if getattr(doc, "escludi_dal_rag", False):
        return True
    patterns = _deny_patterns()
    if not patterns:
        return False
    hay = f"{getattr(doc, 'code', '') or ''} {getattr(doc, 'title', '') or ''}".lower()
    return any(p in hay for p in patterns)


class _VirtualCategory:
    """Categoria bacheca virtuale (niente riga DB): stessa interfaccia di
    ``HubLinkCategory`` per quanto usa il template (``name``/``slug``/``icon``)."""

    is_virtual = True

    def __init__(self, name: str, slug: str, icon: str):
        self.name = name
        self.slug = slug
        self.icon = icon

    def __str__(self) -> str:  # pragma: no cover
        return self.name


def build_procedure_group(legacy_role_id=None, is_admin: bool = False, preview_limit=None):
    """Gruppo bacheca virtuale «Procedure SGI» o ``None`` se non c'è nulla da mostrare.

    Ritorna la stessa forma-dict di ``core.hub_bacheca.visible_bacheca`` così le view
    dashboard lo trattano come una categoria qualsiasi:
    ``{"category", "items": [item-dict], "total", "more"}``.

    Visibilità: tutti gli autenticati vedono i documenti **non sensibili**; i
    parametri ruolo restano nella firma per simmetria ma non filtrano ulteriormente.
    """
    from procedure_refresh.models import ProcedureDocument

    docs = (
        ProcedureDocument.objects.filter(is_active=True)
        .prefetch_related("revisions")
        .order_by("document_type", "code")
    )
    items: list[dict] = []
    for doc in docs:
        if documento_e_sensibile(doc):
            continue
        rev = next((r for r in doc.revisions.all() if r.is_current), None)
        if rev is None:
            continue
        rev_code = (rev.revision_code or "").strip()
        title = f"{doc.code} Rev.{rev_code} — {doc.title}" if rev_code else f"{doc.code} — {doc.title}"
        items.append({
            "title": title,
            "description": doc.category or "",
            "kind": "url",
            "kind_label": "Documento",
            "href": reverse("procedure_refresh:document_open", args=[rev.pk]),
            "open_in_new_tab": True,
        })

    if not items:
        return None
    total = len(items)
    shown = items[:preview_limit] if preview_limit else items
    return {
        "category": _VirtualCategory("Procedure SGI", "procedure-sgi", "📘"),
        "items": shown,
        "total": total,
        "more": max(0, total - len(shown)),
    }
