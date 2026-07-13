"""Registry degli export tabellari di anagrafica (PDF + Excel).

Ogni vista elenco dichiara una ``ExportSpec``; l'endpoint unico
``anagrafica:export`` risolve la chiave, applica il gate ACL della vista,
costruisce le righe, scrive l'audit e restituisce il file.

Il gate ACL di default (``acl_gate``) riusa la decisione ACL della pagina
elenco corrispondente: chi non può aprire la lista non può esportarla, anche
se la rotta di export ha un binding canonico proprio (vedi ``acl_bootstrap``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.http import Http404, HttpRequest, HttpResponse
from django.utils import timezone

from core.audit import log_action
from core.excel_export import make_xlsx_response
from core.table_pdf import render_table_pdf


@dataclass(frozen=True)
class ExportSpec:
    key: str
    title: str
    columns: list[tuple[str, str]]                      # (etichetta, chiave nel dict riga)
    dataset: Callable[[HttpRequest, str], list[dict]]   # (request, scope) -> righe
    # Fail-closed: `permission` è OBBLIGATORIO. Una spec registrata senza gate
    # sarebbe scaricabile da chiunque abbia `anagrafica.export.use` (cioè tutti i
    # ruoli): il gate fine è sempre la lista di origine → usa `acl_gate("/…/")`.
    permission: Callable[[HttpRequest], bool]
    filters_label: Callable[[HttpRequest], str] = lambda request: ""
    sheet_title: str = "Dati"


EXPORT_SPECS: dict[str, ExportSpec] = {}


def register(spec: ExportSpec) -> ExportSpec:
    EXPORT_SPECS[spec.key] = spec
    return spec


def acl_gate(list_path: str) -> Callable[[HttpRequest], bool]:
    """Gate riusabile: l'utente può esportare se può accedere alla lista.

    Replica la decisione che l'``ACLMiddleware`` prenderebbe sul path della
    pagina elenco, **compreso lo strict-mode**: `resolve_acl_access` non applica
    il deny di ``ACL_STRICT_CANONICAL`` (vive solo nel middleware, vedi
    `core/middleware.py`), quindi una lista senza `RoutePermissionBinding`
    canonico verrebbe consentita dal fallback legacy anche dove il middleware la
    nega. Qui il deny strict è replicato: chi non può aprire la lista non può
    esportarla, e l'export (che ha un binding canonico proprio, concesso a tutti
    i ruoli) non diventa una porta di servizio verso dati non visibili a schermo.
    """

    def _check(request: HttpRequest) -> bool:
        from django.conf import settings

        from core.acl_v2 import resolve_acl_access
        from core.legacy_utils import get_legacy_user, legacy_auth_enabled
        from core.middleware import is_acl_shared_path, resolve_acl_gate_target_path

        user = getattr(request, "user", None)
        # Stesso ordine di bypass del middleware.
        if getattr(user, "is_superuser", False):
            return True
        if not legacy_auth_enabled():
            return True
        if is_acl_shared_path(list_path):
            return True

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
        decision = resolve_acl_access(
            path=resolve_acl_gate_target_path(list_path),
            legacy_user=legacy_user,
            django_user=user,
            request=None,  # la request è quella dell'export, non della lista
            include_legacy_diagnostic=False,
        )
        if not bool(decision.get("allowed", False)):
            return False
        # Strict-mode: il fallback legacy non basta (il middleware nega).
        if (
            decision.get("decision_source") == "legacy_fallback"
            and getattr(settings, "ACL_STRICT_CANONICAL", False)
        ):
            return False
        return True

    return _check


def _actor_name(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    return (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or "").strip()


def build_export_response(request: HttpRequest, key: str, fmt: str, scope: str) -> HttpResponse:
    spec = EXPORT_SPECS.get(key)
    if spec is None:
        raise Http404("Export non disponibile.")

    fmt = (fmt or "xlsx").strip().lower()
    if fmt not in ("xlsx", "pdf"):
        fmt = "xlsx"
    scope = (scope or "filtered").strip().lower()
    if scope not in ("filtered", "full"):
        scope = "filtered"

    rows_data = list(spec.dataset(request, scope))
    headers = [label for label, _accessor in spec.columns]
    rows = [[row.get(accessor, "") for _label, accessor in spec.columns] for row in rows_data]

    filters = spec.filters_label(request) if scope == "filtered" else "Tutti i record"
    today = timezone.localdate().strftime("%d-%m-%Y")
    stamp = timezone.localdate().strftime("%Y%m%d")
    subtitle = f"Generato il {today} da {_actor_name(request)}".strip()
    filters_label = f"{filters} · {len(rows)} righe" if filters else f"{len(rows)} righe"

    log_action(request, "export", "anagrafica", {
        "lista": spec.key,
        "formato": fmt,
        "scope": scope,
        "n_righe": len(rows),
        "filtri": filters,
    })

    if fmt == "pdf":
        pdf_bytes = render_table_pdf(
            title=spec.title,
            headers=headers,
            rows=rows,
            subtitle=f"{subtitle} · {filters_label}",
        )
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{spec.key}_{stamp}.pdf"'
        return response

    return make_xlsx_response(
        filename=f"{spec.key}_{stamp}.xlsx",
        columns=headers,
        rows=rows,
        sheet_title=spec.sheet_title or spec.title[:31],
        title=spec.title,
        subtitle=subtitle,
        filters_label=filters_label,
    )


# ── Spec pilota: catalogo mansioni ────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.mansioni_list` (q / rischio / solo_rischio;
# «solo mansioni di rischio» = livello_rischio OPPURE DPI OPPURE visite richieste).

def _mansioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import Mansione

    mansioni = list(
        Mansione.objects.all()
        .order_by("nome")
        .prefetch_related("visite_richieste", "dpi_richiesti")
    )

    rows: list[dict] = []
    q_text = (request.GET.get("q") or "").strip()
    filtro_rischio = (request.GET.get("rischio") or "").strip().upper()
    if filtro_rischio not in dict(Mansione.LIVELLO_RISCHIO_CHOICES):
        filtro_rischio = ""
    solo_rischio = request.GET.get("solo_rischio") == "1"
    filtered = scope == "filtered"

    for m in mansioni:
        n_visite = len(m.visite_richieste.all())
        try:
            n_dpi = len(m.dpi_richiesti.all())
        except Exception:
            n_dpi = 0
        is_rischio = bool(m.livello_rischio or n_dpi or n_visite)

        if filtered:
            if q_text and q_text.casefold() not in (m.nome or "").casefold():
                continue
            if filtro_rischio and m.livello_rischio != filtro_rischio:
                continue
            if solo_rischio and not is_rischio:
                continue

        rows.append({
            "nome": m.nome or "",
            "categoria": m.get_categoria_display() if m.categoria else "",
            "livello_rischio": m.get_livello_rischio_display() if m.livello_rischio else "",
            "descrizione": m.descrizione or "",
            "n_dpi": n_dpi,
            "n_visite": n_visite,
            "attiva": "Si" if m.is_active else "No",
        })
    return rows


def _mansioni_filters(request: HttpRequest) -> str:
    from anagrafica.models import Mansione

    parts: list[str] = []
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    filtro_rischio = (request.GET.get("rischio") or "").strip().upper()
    labels = dict(Mansione.LIVELLO_RISCHIO_CHOICES)
    if filtro_rischio in labels:
        parts.append(f"Rischio: {labels[filtro_rischio]}")
    if request.GET.get("solo_rischio") == "1":
        parts.append("Solo mansioni di rischio")
    return " · ".join(parts)


register(ExportSpec(
    key="mansioni",
    title="Catalogo mansioni",
    sheet_title="Mansioni",
    columns=[
        ("Mansione", "nome"),
        ("Categoria", "categoria"),
        ("Livello di rischio", "livello_rischio"),
        ("Descrizione", "descrizione"),
        ("DPI richiesti", "n_dpi"),
        ("Visite richieste", "n_visite"),
        ("Attiva", "attiva"),
    ],
    dataset=_mansioni_rows,
    filters_label=_mansioni_filters,
    permission=acl_gate("/anagrafica/mansioni/"),
))
