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


# ── Elenco dipendenti ─────────────────────────────────────────────────────────
# Fonte unica: `views.build_dipendenti_rows` (stesso filtro della pagina, niente
# duplicazione → niente drift). PRIVACY (dati personali HR): le colonne sono
# esattamente quelle già visibili nella lista a schermo (`dipendenti_list.html`:
# Dipendente + #id, Reparto, Mansione, Email notifica). Nessun campo aggiuntivo
# (matricola, username, stato account…) va aggiunto qui senza che sia mostrato
# anche in pagina.

def _dipendenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_dipendenti_rows  # import locale: evita cicli

    rows = build_dipendenti_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "id": int(r.get("id") or 0) or "",
            "cognome": str(r.get("cognome") or "").strip(),
            "nome": str(r.get("nome") or "").strip(),
            "reparto": str(r.get("reparto") or "").strip(),
            "mansione": str(r.get("mansione") or "").strip(),
            "email_notifica": str(r.get("email_notifica") or "").strip(),
        }
        for r in rows
    ]


def _dipendenti_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    for param, label in (
        ("reparto", "Reparto"),
        ("area", "Reparto (catalogo)"),
        ("tipologia_contratto", "Tipo contratto"),
    ):
        value = (request.GET.get(param) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return " · ".join(parts)


register(ExportSpec(
    key="dipendenti",
    title="Elenco dipendenti",
    sheet_title="Dipendenti",
    columns=[
        ("ID", "id"),
        ("Cognome", "cognome"),
        ("Nome", "nome"),
        ("Reparto", "reparto"),
        ("Mansione", "mansione"),
        ("Email notifica", "email_notifica"),
    ],
    dataset=_dipendenti_rows,
    filters_label=_dipendenti_filters,
    permission=acl_gate("/anagrafica/dipendenti/"),
))


# ── Anagrafiche di supporto ───────────────────────────────────────────────────
# Cataloghi senza filtri di lista (aree/reparti, ruoli aziendali, ruoli
# operativi): `scope=filtered` e `scope=full` coincidono per costruzione, e
# `filters_label` resta vuota. Le colonne sono quelle mostrate a schermo.


def _no_filters(request: HttpRequest) -> str:
    return ""


# ── Aree & Reparti (lista annidata → appiattita) ──────────────────────────────
# La pagina mostra la gerarchia reparto → aree aziendali (più le aree senza
# reparto). L'export appiattisce: **una riga per area**, con le colonne del
# reparto (nome + caporeparto) ripetute. I reparti ancora senza aree — che la
# pagina mostra comunque, come banda — producono una riga con le colonne area
# vuote, così l'export non perde nulla di ciò che è a schermo.

def _aree_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import AreaAziendale, Reparto
    from anagrafica.views import _dipendenti_picker_rows

    try:
        dip_map = {item["id"]: item["label"] for item in _dipendenti_picker_rows()}
    except Exception:  # fail-safe: l'anagrafica legacy non deve bloccare l'export
        dip_map = {}

    rows: list[dict] = []
    reparti = Reparto.objects.prefetch_related("aree_aziendali").order_by("nome")
    for rep in reparti:
        capo = dip_map.get(rep.caporeparto_legacy_id or 0, "")
        aree = list(rep.aree_aziendali.all())
        if not aree:
            rows.append({
                "reparto": rep.nome or "",
                "caporeparto": capo,
                "area": "",
                "descrizione": "",
                "responsabile": "",
                "stato": "",
            })
            continue
        for area in aree:
            rows.append({
                "reparto": rep.nome or "",
                "caporeparto": capo,
                "area": area.nome or "",
                "descrizione": area.descrizione or "",
                "responsabile": dip_map.get(area.responsabile_legacy_id or 0, ""),
                "stato": "Attivo" if area.is_active else "Inattivo",
            })

    for area in AreaAziendale.objects.filter(reparto__isnull=True).order_by("nome"):
        rows.append({
            "reparto": "",
            "caporeparto": "",
            "area": area.nome or "",
            "descrizione": area.descrizione or "",
            "responsabile": dip_map.get(area.responsabile_legacy_id or 0, ""),
            "stato": "Attivo" if area.is_active else "Inattivo",
        })
    return rows


register(ExportSpec(
    key="aree",
    title="Aree & Reparti",
    sheet_title="Aree e reparti",
    columns=[
        ("Reparto", "reparto"),
        ("Caporeparto", "caporeparto"),
        ("Area aziendale", "area"),
        ("Descrizione", "descrizione"),
        ("Responsabile", "responsabile"),
        ("Stato", "stato"),
    ],
    dataset=_aree_rows,
    filters_label=_no_filters,
    permission=acl_gate("/anagrafica/aree/"),
))


# ── Ruoli aziendali ───────────────────────────────────────────────────────────

def _ruoli_aziendali_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import RuoloAziendale

    return [
        {
            "nome": r.nome or "",
            "descrizione": r.descrizione or "",
            "stato": "Attivo" if r.is_active else "Inattivo",
        }
        for r in RuoloAziendale.objects.all().order_by("nome")
    ]


register(ExportSpec(
    key="ruoli_aziendali",
    title="Ruoli aziendali",
    sheet_title="Ruoli aziendali",
    columns=[
        ("Nome", "nome"),
        ("Descrizione", "descrizione"),
        ("Stato", "stato"),
    ],
    dataset=_ruoli_aziendali_rows,
    filters_label=_no_filters,
    permission=acl_gate("/anagrafica/ruoli-aziendali/"),
))


# ── Ruoli operativi ───────────────────────────────────────────────────────────
# La pagina è a schede (non tabella): per ogni ruolo mostra nome, descrizione,
# numero di dipendenti assegnati e lo stato (badge «Inattivo»).

def _ruoli_operativi_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import RuoloOperativo

    return [
        {
            "nome": r.nome or "",
            "descrizione": r.descrizione or "",
            "n_assegnati": r.n_assegnati,
            "stato": "Attivo" if r.is_active else "Inattivo",
        }
        for r in RuoloOperativo.objects.annotate(n_assegnati=Count("assegnazioni")).order_by("nome")
    ]


register(ExportSpec(
    key="ruoli_operativi",
    title="Ruoli operativi",
    sheet_title="Ruoli operativi",
    columns=[
        ("Ruolo", "nome"),
        ("Descrizione", "descrizione"),
        ("Dipendenti assegnati", "n_assegnati"),
        ("Stato", "stato"),
    ],
    dataset=_ruoli_operativi_rows,
    filters_label=_no_filters,
    permission=acl_gate("/anagrafica/ruoli-operativi/"),
))


# ── Catalogo qualifiche ───────────────────────────────────────────────────────
# La pagina raggruppa il catalogo per categoria (tab `?categoria=`) e mostra
# Nome qualifica / Durata validità / Assegnazioni / Stato: l'export ripete la
# categoria come colonna (equivalente piatto del raggruppamento a schermo).

def _qualifiche_cat_filter(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    valid = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    cat = (request.GET.get("categoria") or "").strip().upper()
    return cat if cat in valid else ""


def _qualifiche_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import TipoQualifica

    qs = TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni")).order_by(
        "categoria", "nome"
    )
    cat = _qualifiche_cat_filter(request) if scope == "filtered" else ""
    if cat:
        qs = qs.filter(categoria=cat)

    return [
        {
            "categoria": t.get_categoria_display() if t.categoria else "",
            "nome": t.nome or "",
            "durata": f"{t.durata_mesi} mesi" if t.durata_mesi else "Nessuna scadenza",
            "n_assegnazioni": t.n_assegnazioni,
            "stato": "Attiva" if t.is_active else "Inattiva",
        }
        for t in qs
    ]


def _qualifiche_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    cat = _qualifiche_cat_filter(request)
    if not cat:
        return ""
    labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    return f"Categoria: {labels.get(cat, cat)}"


register(ExportSpec(
    key="qualifiche",
    title="Catalogo qualifiche",
    sheet_title="Qualifiche",
    columns=[
        ("Categoria", "categoria"),
        ("Nome qualifica", "nome"),
        ("Durata validità", "durata"),
        ("Assegnazioni", "n_assegnazioni"),
        ("Stato", "stato"),
    ],
    dataset=_qualifiche_rows,
    filters_label=_qualifiche_filters,
    permission=acl_gate("/anagrafica/qualifiche/"),
))


# ── Sessioni di rinnovo qualifiche ────────────────────────────────────────────
# Fonte unica: `views.build_qualifica_sessioni_rows` (stesso filtro tipo/q della
# pagina, niente duplicazione → niente drift).

def _fmt_date(value) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _qualifica_sessioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_qualifica_sessioni_rows  # import locale: evita cicli

    sessioni = build_qualifica_sessioni_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "data": _fmt_date(s.data_conseguimento),
            "qualifica": s.tipo.nome if s.tipo_id else "",
            "ente": s.ente or "",
            "n_part": s.n_part,
            "scadenza": _fmt_date(s.scadenza_effettiva),
        }
        for s in sessioni
    ]


def _qualifica_sessioni_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    parts: list[str] = []
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    if filtro_tipo.isdigit():
        nome = (
            TipoQualifica.objects.filter(pk=int(filtro_tipo))
            .values_list("nome", flat=True)
            .first()
        )
        if nome:
            parts.append(f"Qualifica: {nome}")
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    return " · ".join(parts)


register(ExportSpec(
    key="qualifica_sessioni",
    title="Sessioni di rinnovo qualifiche",
    sheet_title="Sessioni qualifiche",
    columns=[
        ("Data", "data"),
        ("Qualifica", "qualifica"),
        ("Ente", "ente"),
        ("Partecipanti", "n_part"),
        ("Scadenza", "scadenza"),
    ],
    dataset=_qualifica_sessioni_rows,
    filters_label=_qualifica_sessioni_filters,
    permission=acl_gate("/anagrafica/qualifiche/sessioni/"),
))


# ── FORMAZIONE ────────────────────────────────────────────────────────────────
# Le liste di formazione hanno DUE gate: l'ACL di rotta (come ogni altra lista) e
# il permesso funzionale della sezione (`views._can_view_formazione`, singleton
# AnagraficaFormazionePermission). L'export deve rispettarli entrambi: chi non
# vede la sezione a schermo non può scaricarla.

def _si_no(value) -> str:
    return "Sì" if value else "No"


def formazione_gate(list_path: str) -> Callable[[HttpRequest], bool]:
    base = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        if not base(request):
            return False
        from anagrafica.views import _can_view_formazione  # import locale: evita cicli

        try:
            return bool(_can_view_formazione(request))
        except Exception:
            return False  # fail-closed

    return _check


# ── Piani formativi ───────────────────────────────────────────────────────────
# Colonne = quelle di `formazione_piani.html` (Codice, Nome, Categoria, Stato,
# Corsi, Provider). Filtri della pagina: `stato`, `categoria`.

def _formazione_piani_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import TrainingPlan

    qs = TrainingPlan.objects.all()
    if scope == "filtered":
        filtro_stato = (request.GET.get("stato") or "").strip()
        filtro_cat = (request.GET.get("categoria") or "").strip()
        if filtro_stato:
            qs = qs.filter(stato=filtro_stato)
        if filtro_cat:
            qs = qs.filter(categoria=filtro_cat)

    return [
        {
            "codice": p.codice or "",
            "nome": p.nome or "",
            "categoria": p.get_categoria_display() if p.categoria else "",
            "stato": p.get_stato_display() if p.stato else "",
            "n_corsi": p.n_corsi,
            "provider": _si_no(p.provider_esterno),
        }
        for p in qs.order_by("nome").annotate(n_corsi=Count("corsi"))
    ]


def _formazione_piani_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingPlan

    parts: list[str] = []
    stati = dict(TrainingPlan.STATO_CHOICES)
    categorie = dict(TrainingPlan.CATEGORIA_CHOICES)
    filtro_stato = (request.GET.get("stato") or "").strip()
    if filtro_stato:
        parts.append(f"Stato: {stati.get(filtro_stato, filtro_stato)}")
    filtro_cat = (request.GET.get("categoria") or "").strip()
    if filtro_cat:
        parts.append(f"Categoria: {categorie.get(filtro_cat, filtro_cat)}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_piani",
    title="Piani formativi",
    sheet_title="Piani formativi",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Categoria", "categoria"),
        ("Stato", "stato"),
        ("Corsi", "n_corsi"),
        ("Provider esterno", "provider"),
    ],
    dataset=_formazione_piani_rows,
    filters_label=_formazione_piani_filters,
    permission=formazione_gate("/anagrafica/formazione/piani/"),
))


# ── Corsi formativi ───────────────────────────────────────────────────────────
# Fonte unica: `views.build_formazione_corsi_rows` (stessi filtri q/piano/stato/
# obbligatorio della pagina, niente duplicazione → niente drift). La pagina è
# impaginata (50/pagina): l'export scorre tutte le righe filtrate.

def _formazione_corsi_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_formazione_corsi_rows  # import locale: evita cicli

    corsi = build_formazione_corsi_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "codice": c.codice or "",
            "titolo": c.titolo or "",
            "piano": c.piano.nome if c.piano_id else "",
            "stato": c.get_stato_display() if c.stato else "",
            "durata": str(c.durata_ore_teorica) if c.durata_ore_teorica is not None else "",
            "validita": c.validita_mesi if c.validita_mesi else "una tantum",
            "obbligatorio": _si_no(c.obbligatorio),
        }
        for c in corsi
    ]


def _formazione_corsi_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingCourse, TrainingPlan

    parts: list[str] = []
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    filtro_piano = (request.GET.get("piano") or "").strip()
    if filtro_piano.isdigit():
        nome = (
            TrainingPlan.objects.filter(pk=int(filtro_piano))
            .values_list("nome", flat=True)
            .first()
        )
        if nome:
            parts.append(f"Piano: {nome}")
    filtro_stato = (request.GET.get("stato") or "").strip()
    if filtro_stato:
        stati = dict(TrainingCourse.STATO_CHOICES)
        parts.append(f"Stato: {stati.get(filtro_stato, filtro_stato)}")
    filtro_obbl = (request.GET.get("obbligatorio") or "").strip()
    if filtro_obbl == "1":
        parts.append("Solo obbligatori")
    elif filtro_obbl == "0":
        parts.append("Solo facoltativi")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_corsi",
    title="Corsi formativi",
    sheet_title="Corsi",
    columns=[
        ("Codice", "codice"),
        ("Titolo", "titolo"),
        ("Piano", "piano"),
        ("Stato", "stato"),
        ("Durata (h)", "durata"),
        ("Validità (mesi)", "validita"),
        ("Obbligatorio", "obbligatorio"),
    ],
    dataset=_formazione_corsi_rows,
    filters_label=_formazione_corsi_filters,
    permission=formazione_gate("/anagrafica/formazione/corsi/"),
))


# ── Docenti / formatori ───────────────────────────────────────────────────────
# Colonne = quelle di `formazione_istruttori.html`. Email/telefono sono già a
# schermo (recapiti professionali del docente): nessun campo aggiuntivo.

def _formazione_istruttori_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Q

    from anagrafica.models import TrainingInstructor

    qs = TrainingInstructor.objects.all()
    if scope == "filtered":
        filtro_tipo = (request.GET.get("tipo") or "").strip()
        q_search = (request.GET.get("q") or "").strip()
        if filtro_tipo:
            qs = qs.filter(tipo=filtro_tipo)
        if q_search:
            qs = qs.filter(
                Q(nome__icontains=q_search) | Q(ragione_sociale__icontains=q_search)
            )

    return [
        {
            "nome": i.nome or "",
            "tipo": i.get_tipo_display() if i.tipo else "",
            "ragione_sociale": i.ragione_sociale or "",
            "email": i.email or "",
            "telefono": i.telefono or "",
            "attivo": _si_no(i.is_active),
        }
        for i in qs.order_by("nome")
    ]


def _formazione_istruttori_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingInstructor

    parts: list[str] = []
    q_search = (request.GET.get("q") or "").strip()
    if q_search:
        parts.append(f'Ricerca: "{q_search}"')
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    if filtro_tipo:
        tipi = dict(TrainingInstructor.TIPO_CHOICES)
        parts.append(f"Tipo: {tipi.get(filtro_tipo, filtro_tipo)}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_istruttori",
    title="Docenti / Formatori",
    sheet_title="Docenti",
    columns=[
        ("Nome", "nome"),
        ("Tipo", "tipo"),
        ("Ragione sociale", "ragione_sociale"),
        ("Email", "email"),
        ("Telefono", "telefono"),
        ("Attivo", "attivo"),
    ],
    dataset=_formazione_istruttori_rows,
    filters_label=_formazione_istruttori_filters,
    permission=formazione_gate("/anagrafica/formazione/istruttori/"),
))


# ── Sessioni formative ────────────────────────────────────────────────────────
# Fonte unica: `views.build_formazione_sessioni_rows` (stessi filtri corso/stato/
# anno/q della pagina). Pagina impaginata (50/pagina): l'export scorre tutto.

def _formazione_sessioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_formazione_sessioni_rows  # import locale: evita cicli

    sessioni = build_formazione_sessioni_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "codice": s.codice_sessione or "",
            "corso": s.corso.titolo if s.corso_id else "",
            "piano": s.corso.piano.nome if s.corso_id and s.corso.piano_id else "",
            "inizio": _fmt_date(s.data_inizio),
            "fine": _fmt_date(s.data_fine),
            "stato": s.get_stato_display() if s.stato else "",
            "modalita": s.get_modalita_display() if s.modalita else "",
            "docente": (s.docente_nome or "").strip() or (s.docente.nome if s.docente_id else ""),
        }
        for s in sessioni
    ]


def _formazione_sessioni_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingCourse, TrainingSession

    parts: list[str] = []
    q_search = (request.GET.get("q") or "").strip()
    if q_search:
        parts.append(f'Ricerca: "{q_search}"')
    filtro_corso = (request.GET.get("corso") or "").strip()
    if filtro_corso.isdigit():
        titolo = (
            TrainingCourse.objects.filter(pk=int(filtro_corso))
            .values_list("titolo", flat=True)
            .first()
        )
        if titolo:
            parts.append(f"Corso: {titolo}")
    filtro_stato = (request.GET.get("stato") or "").strip()
    if filtro_stato:
        stati = dict(TrainingSession.STATO_CHOICES)
        parts.append(f"Stato: {stati.get(filtro_stato, filtro_stato)}")
    filtro_anno = (request.GET.get("anno") or "").strip()
    if filtro_anno:
        parts.append(f"Anno: {filtro_anno}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_sessioni",
    title="Sessioni formative",
    sheet_title="Sessioni",
    columns=[
        ("Codice", "codice"),
        ("Corso", "corso"),
        ("Piano", "piano"),
        ("Inizio", "inizio"),
        ("Fine", "fine"),
        ("Stato", "stato"),
        ("Modalità", "modalita"),
        ("Docente", "docente"),
    ],
    dataset=_formazione_sessioni_rows,
    filters_label=_formazione_sessioni_filters,
    permission=formazione_gate("/anagrafica/formazione/sessioni/"),
))


# ── Safety: fattori di rischio / categorie corso / esposizioni ────────────────
# Tre cataloghi senza filtri di lista (`scope=filtered` == `scope=full`).
# Colonne = intestazioni delle rispettive tabelle a schermo.

def _fattori_rischio_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import FattoreRischio

    qs = (
        FattoreRischio.objects
        .annotate(
            n_categorie=Count("categorie_corso", distinct=True),
            n_esposizioni=Count("esposizioni", distinct=True),
        )
        .order_by("categoria", "nome")
    )
    return [
        {
            "codice": f.codice or "",
            "nome": f.nome or "",
            "categoria": f.get_categoria_display() if f.categoria else "",
            "period_form": f.periodicita_formazione_mesi or "",
            "period_sorv": f.periodicita_sorveglianza_mesi or "",
            "req_form": _si_no(f.richiede_formazione),
            "req_med": _si_no(f.richiede_visita_medica),
            "req_dpi": _si_no(f.richiede_dpi),
            "n_categorie": f.n_categorie,
            "n_esposizioni": f.n_esposizioni,
            "attivo": _si_no(f.is_active),
        }
        for f in qs
    ]


register(ExportSpec(
    key="fattori_rischio",
    title="Fattori di rischio",
    sheet_title="Fattori di rischio",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Categoria", "categoria"),
        ("Formazione (mesi)", "period_form"),
        ("Sorveglianza (mesi)", "period_sorv"),
        ("Richiede formazione", "req_form"),
        ("Richiede visita medica", "req_med"),
        ("Richiede DPI", "req_dpi"),
        ("Categorie collegate", "n_categorie"),
        ("Esposizioni", "n_esposizioni"),
        ("Attivo", "attivo"),
    ],
    dataset=_fattori_rischio_rows,
    filters_label=_no_filters,
    permission=formazione_gate("/anagrafica/formazione/rischi/fattori/"),
))


def _categorie_corso_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import CategoriaCorso

    qs = (
        CategoriaCorso.objects
        .prefetch_related("fattori_rischio")
        .annotate(n_corsi=Count("corsi", distinct=True))
        .order_by("nome")
    )
    return [
        {
            "codice": c.codice or "",
            "nome": c.nome or "",
            "descrizione": c.descrizione or "",
            "fattori": ", ".join(fr.codice for fr in c.fattori_rischio.all()),
            "n_corsi": c.n_corsi,
            "attivo": _si_no(c.is_active),
        }
        for c in qs
    ]


register(ExportSpec(
    key="categorie_corso",
    title="Categorie corso",
    sheet_title="Categorie corso",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Descrizione", "descrizione"),
        ("Fattori collegati", "fattori"),
        ("Corsi", "n_corsi"),
        ("Attivo", "attivo"),
    ],
    dataset=_categorie_corso_rows,
    filters_label=_no_filters,
    permission=formazione_gate("/anagrafica/formazione/rischi/categorie/"),
))


def _esposizioni_rischio_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import EsposizioneRischio

    qs = (
        EsposizioneRischio.objects
        .select_related("fattore", "mansione", "area")
        .order_by("fattore__categoria", "fattore__nome", "mansione__nome", "area__nome")
    )
    return [
        {
            "fattore": f"[{e.fattore.codice}] {e.fattore.nome}" if e.fattore_id else "",
            "categoria": e.fattore.get_categoria_display() if e.fattore_id else "",
            "mansione": e.mansione.nome if e.mansione_id else "",
            "area": e.area.nome if e.area_id else "",
            "note": e.note or "",
            "attivo": _si_no(e.is_active),
        }
        for e in qs
    ]


register(ExportSpec(
    key="esposizioni_rischio",
    title="Esposizioni a rischio",
    sheet_title="Esposizioni",
    columns=[
        ("Fattore", "fattore"),
        ("Categoria fattore", "categoria"),
        ("Mansione", "mansione"),
        ("Area", "area"),
        ("Note", "note"),
        ("Attivo", "attivo"),
    ],
    dataset=_esposizioni_rischio_rows,
    filters_label=_no_filters,
    permission=formazione_gate("/anagrafica/formazione/rischi/esposizioni/"),
))


# ── HR & DOCUMENTI (dati personali) ───────────────────────────────────────────
# Liste con dati personali dei dipendenti: oltre all'ACL di rotta hanno un gate
# applicativo HR in-view (`views._check_hr_permission`, singleton
# AnagraficaHRPermission). L'export lo replica: chi non vede la pagina non può
# scaricarla. Per `documenti` il gate NON basta: la lista applica anche uno
# **scoping per riga** (cartelle `solo_admin` invisibili ai non-superuser) che il
# dataset deve replicare in OGNI scope, `full` compreso.

def hr_gate(list_path: str) -> Callable[[HttpRequest], bool]:
    """ACL di rotta AND permesso HR applicativo (`_check_hr_permission`)."""
    base = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        if not base(request):
            return False
        from anagrafica.views import _check_hr_permission  # import locale: evita cicli

        try:
            return bool(_check_hr_permission(request))
        except Exception:
            return False  # fail-closed

    return _check


def documenti_gate(list_path: str) -> Callable[[HttpRequest], bool]:
    """Gate dell'archivio documentale: `is_admin OR _check_hr_permission`.

    Ricalca esattamente ``views.documenti_list`` (che ammette anche l'admin
    legacy a prescindere dalla configurazione del permesso HR). NB: passare il
    gate NON dà accesso ai documenti riservati — quelli sono esclusi riga per
    riga dal dataset (vedi ``_documenti_rows``).
    """
    base = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        if not base(request):
            return False
        from anagrafica.views import _check_hr_permission  # import locale: evita cicli
        from core.legacy_utils import get_legacy_user, is_legacy_admin

        user = getattr(request, "user", None)
        try:
            if getattr(user, "is_superuser", False):
                return True
            if is_legacy_admin(get_legacy_user(user)):
                return True
            return bool(_check_hr_permission(request))
        except Exception:
            return False  # fail-closed

    return _check


# ── Ex dipendenti ─────────────────────────────────────────────────────────────
# Fonte unica: `views.build_ex_dipendenti_rows` (stesso perimetro «cessati» e
# stesso filtro `q` della pagina). PRIVACY: colonne = quelle di
# `ex_dipendenti_list.html` (Dipendente, Username, Matricola, Contratto, Data
# assunzione, Data cessazione). Nessun campo aggiuntivo.

def _ex_dipendenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import build_ex_dipendenti_rows  # import locale: evita cicli

    rows = build_ex_dipendenti_rows(request, apply_filters=(scope == "filtered"))
    return [
        {
            "cognome": str(r.get("cognome") or "").strip(),
            "nome": str(r.get("nome") or "").strip(),
            "username": str(r.get("aliasusername") or "").strip(),
            "matricola": str(r.get("matricola_legacy") or "").strip(),
            "contratto": str(r.get("tipologia_contratto_display") or "").strip(),
            "data_assunzione": _fmt_date(r.get("data_assunzione")),
            "data_cessazione": _fmt_date(r.get("data_cessazione")),
        }
        for r in rows
    ]


def _q_filter(request: HttpRequest) -> str:
    q_text = (request.GET.get("q") or "").strip()
    return f'Ricerca: "{q_text}"' if q_text else ""


register(ExportSpec(
    key="ex_dipendenti",
    title="Ex dipendenti",
    sheet_title="Ex dipendenti",
    columns=[
        ("Cognome", "cognome"),
        ("Nome", "nome"),
        ("Username", "username"),
        ("Matricola", "matricola"),
        ("Contratto", "contratto"),
        ("Data assunzione", "data_assunzione"),
        ("Data cessazione", "data_cessazione"),
    ],
    dataset=_ex_dipendenti_rows,
    filters_label=_q_filter,
    permission=acl_gate("/anagrafica/ex-dipendenti/"),
))


# ── Archivio documenti ────────────────────────────────────────────────────────
# SICUREZZA (punto critico): la lista esclude sempre le cartelle riservate
# (`solo_admin`) ai non-superuser. Lo stesso scoping è applicato QUI, riga per
# riga, e NON dipende dallo scope: `scope=full` fa cadere i filtri di pagina
# (cartella/anno/ricerca), mai il perimetro di sicurezza. Colonne = intestazioni
# di `documenti_list.html` (senza la colonna Azioni).

def _documenti_base_qs(request: HttpRequest):
    from anagrafica.models import DocumentoDipendente

    qs = (
        DocumentoDipendente.objects
        .filter(tipo=DocumentoDipendente.Tipo.MANUALE)
        .select_related("cartella")
        .order_by("-created_at")
    )
    # Perimetro di sicurezza: identico a `views.documenti_list`.
    if not getattr(getattr(request, "user", None), "is_superuser", False):
        qs = qs.exclude(cartella__solo_admin=True)
    return qs


def _documenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.views import _build_nomi_map  # import locale: evita cicli

    qs = _documenti_base_qs(request)

    filtro_cartella = (request.GET.get("cartella") or "").strip()
    filtro_cerca = (request.GET.get("q") or "").strip()
    filtro_anno = (request.GET.get("anno") or "").strip()
    filtered = scope == "filtered"

    if filtered and filtro_cartella:
        if filtro_cartella == "__nessuna__":
            qs = qs.filter(cartella__isnull=True)
        else:
            try:
                qs = qs.filter(cartella_id=int(filtro_cartella))
            except (ValueError, TypeError):
                pass
    if filtered and filtro_anno:
        try:
            qs = qs.filter(created_at__year=int(filtro_anno))
        except (ValueError, TypeError):
            pass

    nomi_map = _build_nomi_map()
    # A differenza della pagina (che tronca a 500 righe per la resa a schermo)
    # l'export scorre tutte le righe consentite: il cap è di presentazione, non
    # di sicurezza.
    documenti = list(qs)
    if filtered and filtro_cerca:
        q_low = filtro_cerca.lower()
        documenti = [
            d for d in documenti
            if q_low in nomi_map.get(d.legacy_anagrafica_id, "").lower()
            or q_low in (d.nome_originale or "").lower()
            or q_low in (d.descrizione or "").lower()
        ]

    return [
        {
            "dipendente": nomi_map.get(d.legacy_anagrafica_id, f"#{d.legacy_anagrafica_id}"),
            "cartella": d.cartella.nome if d.cartella_id else "Senza cartella",
            "file": d.nome_originale or "",
            "descrizione": d.descrizione or "",
            "caricato": _fmt_date(timezone.localtime(d.created_at).date() if d.created_at else None),
            "retention": _fmt_date(d.retention_until),
        }
        for d in documenti
    ]


def _documenti_filters(request: HttpRequest) -> str:
    from anagrafica.models import CartellaDocumentoDipendente

    parts: list[str] = []
    filtro_cartella = (request.GET.get("cartella") or "").strip()
    if filtro_cartella == "__nessuna__":
        parts.append("Cartella: senza cartella")
    elif filtro_cartella.isdigit():
        nome = (
            CartellaDocumentoDipendente.objects.filter(pk=int(filtro_cartella))
            .values_list("nome", flat=True)
            .first()
        )
        if nome:
            parts.append(f"Cartella: {nome}")
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    anno = (request.GET.get("anno") or "").strip()
    if anno:
        parts.append(f"Anno: {anno}")
    return " · ".join(parts)


register(ExportSpec(
    key="documenti",
    title="Archivio documenti dipendenti",
    sheet_title="Documenti",
    columns=[
        ("Dipendente", "dipendente"),
        ("Cartella", "cartella"),
        ("File", "file"),
        ("Descrizione", "descrizione"),
        ("Caricato", "caricato"),
        ("Conservare fino al", "retention"),
    ],
    dataset=_documenti_rows,
    filters_label=_documenti_filters,
    permission=documenti_gate("/anagrafica/documenti/"),
))


# ── Pratiche di onboarding ────────────────────────────────────────────────────
# Colonne = quelle di `onboarding_list.html` (Dipendente, Reparto, Assunzione,
# Stato, Avanzamento). Filtro della pagina: `stato`.

def _onboarding_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import OnboardingPratica
    from anagrafica.views import _onboarding_counts  # import locale: evita cicli

    qs = OnboardingPratica.objects.prefetch_related("tasks").all()
    valid_stati = {choice[0] for choice in OnboardingPratica.STATO_CHOICES}
    filtro_stato = (request.GET.get("stato") or "").strip()
    if scope == "filtered" and filtro_stato in valid_stati:
        qs = qs.filter(stato=filtro_stato)

    rows: list[dict] = []
    for pratica in qs:
        counts = _onboarding_counts(pratica)
        avanzamento = f"{counts['completati']}/{counts['totale']} completati"
        if counts["eccezioni"]:
            avanzamento += f" · {counts['eccezioni']} eccezioni"
        rows.append({
            "dipendente": (pratica.dipendente_nome or "").strip() or f"#{pratica.legacy_anagrafica_id}",
            "reparto": pratica.reparto or "",
            "data_assunzione": _fmt_date(pratica.data_assunzione),
            "stato": pratica.get_stato_display() if pratica.stato else "",
            "avanzamento": avanzamento,
        })
    return rows


def _onboarding_filters(request: HttpRequest) -> str:
    from anagrafica.models import OnboardingPratica

    filtro_stato = (request.GET.get("stato") or "").strip()
    stati = dict(OnboardingPratica.STATO_CHOICES)
    if filtro_stato in stati:
        return f"Stato: {stati[filtro_stato]}"
    return ""


register(ExportSpec(
    key="onboarding",
    title="Pratiche di onboarding",
    sheet_title="Onboarding",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Assunzione", "data_assunzione"),
        ("Stato", "stato"),
        ("Avanzamento", "avanzamento"),
    ],
    dataset=_onboarding_rows,
    filters_label=_onboarding_filters,
    permission=hr_gate("/anagrafica/onboarding/"),
))


# ── Ratei ferie / ROL / ex-festività ──────────────────────────────────────────
# NB: la pagina ha già un export XLSX dedicato (`views.ratei_export`, bottone
# «⬇ Excel» nella barra filtri): resta invariato. Questa spec è AGGIUNTIVA e
# passa dall'endpoint unico (PDF + Excel, filtrato o tutto). Colonne = quelle
# della tabella a schermo (Dipendente, Periodo, e le 4 misure × 3 gruppi).

def _ratei_maps() -> tuple[dict, dict]:
    """(tax_code → «Cognome Nome», legacy_id → reparto): stessa risoluzione della view."""
    from anagrafica.models import (
        DipendenteAnagraficaAziendale,
        DipendenteAnagraficaCivile,
        SaldoCedolino,
    )
    from core.legacy_models import AnagraficaDipendente

    cf_civile: dict[str, int] = {}
    for c in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="").values(
        "codice_fiscale", "legacy_anagrafica_id"
    ):
        cf_u = (c["codice_fiscale"] or "").strip().upper()
        if cf_u:
            cf_civile[cf_u] = c["legacy_anagrafica_id"]

    cf_to_legacy: dict[str, int | None] = {}
    for row in SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id").distinct():
        cf = (row["tax_code"] or "").strip()
        if not cf or cf in cf_to_legacy:
            continue
        cf_to_legacy[cf] = row["legacy_anagrafica_id"] or cf_civile.get(cf.upper())

    legacy_ids = sorted({lid for lid in cf_to_legacy.values() if lid})
    dip_qs = list(
        AnagraficaDipendente.objects.filter(id__in=legacy_ids).values(
            "id", "cognome", "nome", "reparto"
        )
    )
    id_to_nome = {
        d["id"]: f'{(d["cognome"] or "").strip()} {(d["nome"] or "").strip()}'.strip()
        for d in dip_qs
    }
    id_to_az_reparto = dict(
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .exclude(area="")
        .values_list("legacy_anagrafica_id", "area")
    )
    id_to_reparto = {
        d["id"]: (d["reparto"] or id_to_az_reparto.get(d["id"], "")).strip() for d in dip_qs
    }

    cf_to_nome: dict[str, str] = {}
    for cf, lid in cf_to_legacy.items():
        cf_to_nome[cf] = (id_to_nome.get(lid) if lid else None) or cf
    return cf_to_nome, id_to_reparto


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratei_rows(request: HttpRequest, scope: str) -> list[dict]:
    from datetime import date as _date

    from django.utils.formats import date_format

    from anagrafica.models import SaldoCedolino
    from anagrafica.ratei_alert import filtro_allerta_q, soglie_ratei

    cf_to_nome, id_to_reparto = _ratei_maps()
    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")

    if scope == "filtered":
        filtro_periodo = (request.GET.get("periodo") or "").strip()
        if filtro_periodo:
            try:
                anno, mese, giorno = filtro_periodo.split("-")
                qs = qs.filter(data_competenza=_date(int(anno), int(mese), int(giorno)))
            except (ValueError, AttributeError):
                pass

        filtro_reparti = request.GET.getlist("reparto")
        if filtro_reparti:
            ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in filtro_reparti]
            qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)

        filtro_dipendenti = request.GET.getlist("dipendente")
        if not filtro_dipendenti:
            cf_compat = (request.GET.get("cf") or "").strip().upper()
            if cf_compat:
                filtro_dipendenti = [cf_compat]
        if filtro_dipendenti:
            qs = qs.filter(tax_code__in=filtro_dipendenti)

        if request.GET.get("allerta", "") == "1":
            qs = qs.filter(filtro_allerta_q(soglie_ratei()))

    return [
        {
            "dipendente": cf_to_nome.get((s.tax_code or "").upper(), s.tax_code or ""),
            "periodo": date_format(s.data_competenza, "M Y") if s.data_competenza else "",
            "ferie_anni_prec": _num(s.ferie_anni_prec),
            "ferie_maturati": _num(s.ferie_maturati),
            "ferie_goduti": _num(s.ferie_goduti),
            "ferie_residui": _num(s.ferie_residui),
            "rol_anni_prec": _num(s.rol_anni_prec),
            "rol_maturati": _num(s.rol_maturati),
            "rol_goduti": _num(s.rol_goduti),
            "rol_residui": _num(s.rol_residui),
            "ex_fest_anni_prec": _num(s.ex_fest_anni_prec),
            "ex_fest_maturati": _num(s.ex_fest_maturati),
            "ex_fest_goduti": _num(s.ex_fest_goduti),
            "ex_fest_residui": _num(s.ex_fest_residui),
        }
        for s in qs
    ]


def _ratei_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    filtro_periodo = (request.GET.get("periodo") or "").strip()
    if filtro_periodo:
        parts.append(f"Periodo: {filtro_periodo}")
    filtro_reparti = [r for r in request.GET.getlist("reparto") if r.strip()]
    if filtro_reparti:
        parts.append("Reparto: " + ", ".join(filtro_reparti))
    filtro_dipendenti = [d for d in request.GET.getlist("dipendente") if d.strip()]
    if not filtro_dipendenti:
        cf_compat = (request.GET.get("cf") or "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    if filtro_dipendenti:
        cf_to_nome, _reparti = _ratei_maps()
        parts.append(
            "Dipendente: " + ", ".join(cf_to_nome.get(cf.upper(), cf) for cf in filtro_dipendenti)
        )
    if request.GET.get("allerta", "") == "1":
        parts.append("Solo in allerta")
    return " · ".join(parts)


register(ExportSpec(
    key="ratei",
    title="Ratei ferie / permessi",
    sheet_title="Ratei",
    columns=[
        ("Dipendente", "dipendente"),
        ("Periodo", "periodo"),
        ("Ferie anni prec.", "ferie_anni_prec"),
        ("Ferie maturate", "ferie_maturati"),
        ("Ferie godute", "ferie_goduti"),
        ("Ferie residue", "ferie_residui"),
        ("ROL anni prec.", "rol_anni_prec"),
        ("ROL maturati", "rol_maturati"),
        ("ROL goduti", "rol_goduti"),
        ("ROL residui", "rol_residui"),
        ("Ex-festività anni prec.", "ex_fest_anni_prec"),
        ("Ex-festività maturate", "ex_fest_maturati"),
        ("Ex-festività godute", "ex_fest_goduti"),
        ("Ex-festività residue", "ex_fest_residui"),
    ],
    dataset=_ratei_rows,
    filters_label=_ratei_filters,
    permission=hr_gate("/anagrafica/ratei/"),
))
