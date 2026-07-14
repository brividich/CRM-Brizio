"""Export tabellari delle liste «Persone» di anagrafica.

Le spec sono registrate all'import del modulo (vedi `anagrafica/exports.py`).

Ogni spec replica fedelmente i filtri della querystring e le colonne già visibili
a schermo nella lista di origine: sono dati HR, quindi l'export non aggiunge mai
campi non mostrati in pagina (nessun dato retributivo, sanitario o identificativo
aggiuntivo). Le sorgenti gated a schermo (visite mediche, formazione, contratti)
restano gated anche qui, valutando gli stessi permessi della view.
"""
from __future__ import annotations

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register  # noqa: F401


# ── Helper comuni ────────────────────────────────────────────────────────────

def _d(value) -> str:
    """Data in formato italiano (stringa vuota se assente)."""
    return value.strftime("%d-%m-%Y") if value else ""


def _hr_gate(list_path: str):
    """Gate ACL della lista + permesso HR della view (fail-closed).

    Le liste `documenti`, `onboarding` e `conformita` sono viste trasversali su
    tutto il personale: la view stessa le nega a chi non ha il permesso HR
    (`_check_hr_permission`). L'export non può essere più permissivo della
    pagina, quindi somma i due controlli.
    """
    base = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        if not base(request):
            return False
        from anagrafica.views import _check_hr_permission

        return bool(_check_hr_permission(request))

    return _check


def _documenti_gate(list_path: str):
    """Gate dell'archivio documentale: ACL della lista + (admin legacy OR HR)."""
    base = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        if not base(request):
            return False
        from core.legacy_utils import get_legacy_user, is_legacy_admin

        from anagrafica.views import _check_hr_permission

        user = getattr(request, "user", None)
        if getattr(user, "is_superuser", False):
            return True
        if is_legacy_admin(get_legacy_user(user)):
            return True
        return bool(_check_hr_permission(request))

    return _check


# ── Dipendenti in forza ──────────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.dipendenti_list` (q / reparto / area /
# tipologia_contratto). Gli ex dipendenti (rapporto cessato) non compaiono mai:
# hanno la loro lista dedicata, non è un filtro della querystring.

def _dipendenti_base_rows() -> list[dict]:
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from anagrafica.models import DipendenteAnagraficaAziendale
    from anagrafica.views import _cessati_legacy_ids

    ensure_anagrafica_schema()
    cessati_ids = _cessati_legacy_ids()
    rows = [
        row
        for row in fetch_anagrafica_rows(deduplicate=True)
        if int(row.get("id") or 0) not in cessati_ids
    ]

    # Fallback reparto: se il campo legacy è vuoto usa l'anagrafica aziendale.
    ids_no_reparto = [
        int(r.get("id") or 0) for r in rows if not str(r.get("reparto") or "").strip()
    ]
    if ids_no_reparto:
        az_area_map = dict(
            DipendenteAnagraficaAziendale.objects
            .filter(legacy_anagrafica_id__in=ids_no_reparto)
            .exclude(area="")
            .values_list("legacy_anagrafica_id", "area")
        )
        for row in rows:
            if not str(row.get("reparto") or "").strip():
                lid = int(row.get("id") or 0)
                if lid in az_area_map:
                    row["reparto"] = az_area_map[lid]

    rows.sort(key=lambda row: (
        str(row.get("cognome") or "").strip().casefold(),
        str(row.get("nome") or "").strip().casefold(),
        str(row.get("aliasusername") or "").strip().casefold(),
        int(row.get("id") or 0),
    ))
    return rows


def _dipendenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import DipendenteAnagraficaAziendale

    rows = _dipendenti_base_rows()

    if scope == "filtered":
        q_text = (request.GET.get("q") or "").strip()
        reparto = (request.GET.get("reparto") or "").strip()
        area_filter = (request.GET.get("area") or "").strip()
        contratto_filter = (request.GET.get("tipologia_contratto") or "").strip()

        if q_text:
            q_norm = q_text.casefold()
            rows = [
                row
                for row in rows
                if any(
                    q_norm in value.casefold()
                    for value in [
                        str(row.get("nome") or "").strip(),
                        str(row.get("cognome") or "").strip(),
                        str(row.get("aliasusername") or "").strip(),
                        str(row.get("matricola") or "").strip(),
                    ]
                    if value
                )
            ]
        if reparto:
            rows = [
                row for row in rows
                if str(row.get("reparto") or "").strip().casefold() == reparto.casefold()
            ]
        if area_filter or contratto_filter:
            az_qs = DipendenteAnagraficaAziendale.objects.all()
            if area_filter:
                az_qs = az_qs.filter(area__iexact=area_filter)
            if contratto_filter:
                az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
            allowed_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))
            rows = [row for row in rows if int(row.get("id") or 0) in allowed_ids]

    return [
        {
            "dipendente": f"{str(row.get('cognome') or '').strip()} {str(row.get('nome') or '').strip()}".strip(),
            "reparto": str(row.get("reparto") or "").strip(),
            "mansione": str(row.get("mansione") or "").strip(),
            "email_notifica": str(row.get("email_notifica") or "").strip(),
        }
        for row in rows
    ]


def _dipendenti_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    reparto = (request.GET.get("reparto") or "").strip()
    if reparto:
        parts.append(f"Reparto: {reparto}")
    area = (request.GET.get("area") or "").strip()
    if area:
        parts.append(f"Reparto (catalogo): {area}")
    contratto = (request.GET.get("tipologia_contratto") or "").strip()
    if contratto:
        from anagrafica.models import TipologiaContratto

        nome = (
            TipologiaContratto.objects.filter(codice=contratto)
            .values_list("nome", flat=True)
            .first()
        )
        parts.append(f"Tipo contratto: {nome or contratto}")
    return " · ".join(parts)


register(ExportSpec(
    key="dipendenti",
    title="Dipendenti in forza",
    sheet_title="Dipendenti",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Mansione", "mansione"),
        ("Email notifica", "email_notifica"),
    ],
    dataset=_dipendenti_rows,
    filters_label=_dipendenti_filters,
    permission=acl_gate("/anagrafica/dipendenti/"),
))


# ── Ex dipendenti ────────────────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.ex_dipendenti_list` (solo `q`).

def _ex_dipendenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from datetime import date

    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from anagrafica.models import DipendenteAnagraficaAziendale
    from anagrafica.views import _cessati_legacy_ids

    ensure_anagrafica_schema()
    cessati_ids = _cessati_legacy_ids()
    rows = [
        row
        for row in fetch_anagrafica_rows(deduplicate=True)
        if int(row.get("id") or 0) in cessati_ids
    ]

    if scope == "filtered":
        q_text = (request.GET.get("q") or "").strip()
        if q_text:
            q_norm = q_text.casefold()
            rows = [
                row
                for row in rows
                if any(
                    q_norm in str(row.get(field) or "").strip().casefold()
                    for field in ("nome", "cognome", "aliasusername", "matricola")
                    if str(row.get(field) or "").strip()
                )
            ]

    az_map = {
        obj.legacy_anagrafica_id: obj
        for obj in DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id__in=cessati_ids
        )
    }

    out: list[dict] = []
    for row in rows:
        legacy_id = int(row.get("id") or 0)
        az = az_map.get(legacy_id)
        data_cessazione = getattr(az, "data_cessazione", None)
        data_assunzione = (
            getattr(az, "data_assunzione_ultima", None)
            or getattr(az, "data_prima_assunzione", None)
        )
        out.append({
            "_sort_cessazione": data_cessazione or date.min,
            "_sort_nome": (
                str(row.get("cognome") or "").strip().casefold(),
                str(row.get("nome") or "").strip().casefold(),
            ),
            "dipendente": f"{str(row.get('cognome') or '').strip()} {str(row.get('nome') or '').strip()}".strip(),
            "username": str(row.get("aliasusername") or "").strip(),
            "matricola": str(row.get("matricola") or "").strip(),
            "contratto": az.get_tipologia_contratto_display() if az and az.tipologia_contratto else "",
            "data_assunzione": _d(data_assunzione),
            "data_cessazione": _d(data_cessazione),
        })

    out.sort(key=lambda r: (r["_sort_cessazione"], r["_sort_nome"]), reverse=True)
    for r in out:
        r.pop("_sort_cessazione", None)
        r.pop("_sort_nome", None)
    return out


def _ex_dipendenti_filters(request: HttpRequest) -> str:
    q_text = (request.GET.get("q") or "").strip()
    return f'Ricerca: "{q_text}"' if q_text else ""


register(ExportSpec(
    key="ex_dipendenti",
    title="Ex dipendenti",
    sheet_title="Ex dipendenti",
    columns=[
        ("Dipendente", "dipendente"),
        ("Username", "username"),
        ("Matricola", "matricola"),
        ("Contratto", "contratto"),
        ("Data assunzione", "data_assunzione"),
        ("Data cessazione", "data_cessazione"),
    ],
    dataset=_ex_dipendenti_rows,
    filters_label=_ex_dipendenti_filters,
    permission=acl_gate("/anagrafica/ex-dipendenti/"),
))


# ── Archivio documentale ─────────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.documenti_list` (cartella / q / anno).
# Le cartelle riservate (`solo_admin`) restano escluse ai non-superuser: è una
# regola di visibilità, non un filtro → vale anche con scope=full.
# NB: la pagina taglia a 500 righe per performance; l'export non taglia, deve
# contenere tutte le righe che soddisfano i filtri.

def _documenti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import DocumentoDipendente
    from anagrafica.views import _build_nomi_map

    qs = (
        DocumentoDipendente.objects
        .filter(tipo=DocumentoDipendente.Tipo.MANUALE)
        .select_related("cartella")
        .order_by("-created_at")
    )
    if not getattr(request.user, "is_superuser", False):
        qs = qs.exclude(cartella__solo_admin=True)

    filtro_cerca = ""
    if scope == "filtered":
        filtro_cartella = (request.GET.get("cartella") or "").strip()
        filtro_cerca = (request.GET.get("q") or "").strip()
        filtro_anno = (request.GET.get("anno") or "").strip()

        if filtro_cartella:
            if filtro_cartella == "__nessuna__":
                qs = qs.filter(cartella__isnull=True)
            else:
                try:
                    qs = qs.filter(cartella_id=int(filtro_cartella))
                except (ValueError, TypeError):
                    pass
        if filtro_anno:
            try:
                qs = qs.filter(created_at__year=int(filtro_anno))
            except (ValueError, TypeError):
                pass

    nomi_map = _build_nomi_map()
    documenti = list(qs)
    if filtro_cerca:
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
            "cartella": d.cartella.nome if d.cartella else "Senza cartella",
            "file": d.nome_originale or "",
            "descrizione": d.descrizione or "",
            "caricato": _d(d.created_at),
            "caricato_da": d.created_by_display or "",
            "retention": _d(d.retention_until),
        }
        for d in documenti
    ]


def _documenti_filters(request: HttpRequest) -> str:
    from anagrafica.models import CartellaDocumentoDipendente

    parts: list[str] = []
    filtro_cartella = (request.GET.get("cartella") or "").strip()
    if filtro_cartella == "__nessuna__":
        parts.append("Cartella: senza cartella")
    elif filtro_cartella:
        nome = (
            CartellaDocumentoDipendente.objects
            .filter(pk=filtro_cartella if filtro_cartella.isdigit() else 0)
            .values_list("nome", flat=True)
            .first()
        )
        parts.append(f"Cartella: {nome or filtro_cartella}")
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
        ("Caricato il", "caricato"),
        ("Caricato da", "caricato_da"),
        ("Conservare fino al", "retention"),
    ],
    dataset=_documenti_rows,
    filters_label=_documenti_filters,
    permission=_documenti_gate("/anagrafica/documenti/"),
))


# ── Pratiche di onboarding ───────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.onboarding_list` (solo `stato`).

def _onboarding_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import OnboardingPratica, OnboardingTask

    qs = OnboardingPratica.objects.prefetch_related("tasks").all()
    if scope == "filtered":
        filtro_stato = (request.GET.get("stato") or "").strip()
        valid_stati = {choice[0] for choice in OnboardingPratica.STATO_CHOICES}
        if filtro_stato in valid_stati:
            qs = qs.filter(stato=filtro_stato)

    rows: list[dict] = []
    for p in qs:
        tasks = list(p.tasks.all())
        totale = len(tasks)
        completati = sum(1 for t in tasks if t.stato == OnboardingTask.STATO_COMPLETATO)
        eccezioni = sum(1 for t in tasks if t.stato == OnboardingTask.STATO_ECCEZIONE)
        avanzamento = f"{completati}/{totale} completati"
        if eccezioni:
            avanzamento += f" · {eccezioni} eccezioni"
        rows.append({
            "dipendente": p.dipendente_nome or str(p.legacy_anagrafica_id),
            "reparto": p.reparto or "",
            "data_assunzione": _d(p.data_assunzione),
            "stato": p.get_stato_display(),
            "avanzamento": avanzamento,
        })
    return rows


def _onboarding_filters(request: HttpRequest) -> str:
    from anagrafica.models import OnboardingPratica

    filtro_stato = (request.GET.get("stato") or "").strip()
    labels = dict(OnboardingPratica.STATO_CHOICES)
    return f"Stato: {labels[filtro_stato]}" if filtro_stato in labels else ""


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
    permission=_hr_gate("/anagrafica/onboarding/"),
))


# ── Scadenzario HR ───────────────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.scadenzario` (tipo / stato / reparto).
# Le sorgenti gated a schermo restano gated: visite mediche (dati sanitari),
# formazione e contratti entrano solo se l'utente può vederle nella pagina.
# `scope=full` toglie i filtri della querystring ma NON allarga la finestra
# temporale della lista (scadute + prossimi 60 giorni), che è la definizione
# stessa dello scadenzario.

def _scadenzario_rows(request: HttpRequest, scope: str) -> list[dict]:
    from datetime import timedelta

    from django.db.models import Max
    from django.utils import timezone

    from core.legacy_anagrafica import fetch_anagrafica_rows

    from anagrafica.models import (
        DipendenteAnagraficaAziendale,
        DipendenteQualifica,
        StoricoContratto,
        VisitaMedica,
    )
    from anagrafica.models_formazione import TrainingDeadline
    from anagrafica.views import (
        _can_view_formazione,
        _can_view_visite_mediche,
        _check_hr_permission,
    )

    oggi = timezone.localdate()
    soglia_30 = oggi + timedelta(days=30)
    soglia_60 = oggi + timedelta(days=60)

    can_view_visite = _can_view_visite_mediche(request)
    can_view_formazione = _can_view_formazione(request)
    can_view_contratti = _check_hr_permission(request)

    filtered = scope == "filtered"
    filtro_tipo = (request.GET.get("tipo") or "") if filtered else ""
    filtro_stato = (request.GET.get("stato") or "") if filtered else ""
    filtro_reparto = (request.GET.get("reparto") or "").strip() if filtered else ""

    def _finestra(qs):
        if filtro_stato == "scaduta":
            return qs.filter(data_scadenza__lt=oggi)
        if filtro_stato == "30":
            return qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_30)
        if filtro_stato == "60":
            return qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_60)
        return qs.filter(data_scadenza__lte=soglia_60)

    dip_map = {
        int(r["id"]): r
        for r in fetch_anagrafica_rows(deduplicate=True)
        if r.get("id")
    }

    voci: list[dict] = []

    def _add(kind_label: str, legacy_id: int, tipo_nome: str, data_scadenza):
        dip = dip_map.get(legacy_id, {})
        reparto = str(dip.get("reparto") or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            return
        giorni = (data_scadenza - oggi).days
        voci.append({
            "_giorni": giorni,
            "dipendente": (
                f"{str(dip.get('cognome') or f'ID {legacy_id}').strip()} "
                f"{str(dip.get('nome') or '').strip()}"
            ).strip(),
            "reparto": reparto,
            "tipo": kind_label,
            "descrizione": tipo_nome,
            "scadenza": _d(data_scadenza),
            "stato": "Scaduta" if giorni < 0 else f"Scade in {giorni} giorni",
        })

    # Qualifiche
    if filtro_tipo in ("", "qualifica"):
        qs_q = _finestra(
            DipendenteQualifica.objects.select_related("tipo")
            .filter(data_scadenza__isnull=False)
        )
        for q in qs_q:
            _add("Qualifica", q.legacy_anagrafica_id, q.tipo.nome, q.data_scadenza)

    # Visite mediche (gated: dati sanitari)
    if can_view_visite and filtro_tipo in ("", "visita"):
        latest_ids = (
            VisitaMedica.objects
            .filter(data_scadenza__isnull=False)
            .values("legacy_anagrafica_id", "tipo_id")
            .annotate(max_id=Max("id"))
            .values_list("max_id", flat=True)
        )
        qs_v = _finestra(VisitaMedica.objects.select_related("tipo").filter(id__in=latest_ids))
        for v in qs_v:
            _add("Visita medica", v.legacy_anagrafica_id, v.tipo.nome, v.data_scadenza)

    # Formazione obbligatoria (gated)
    if can_view_formazione and filtro_tipo in ("", "formazione"):
        qs_f = _finestra(
            TrainingDeadline.objects.select_related("corso")
            .filter(is_required=True, data_scadenza__isnull=False)
        )
        for d in qs_f:
            _add("Formazione", d.legacy_anagrafica_id, d.corso.titolo, d.data_scadenza)

    # Contratti a termine e periodi di prova (gated: dato HR)
    if can_view_contratti and filtro_tipo in ("", "contratto"):
        cessati = set(
            DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        ultimo_contratto: dict[int, StoricoContratto] = {}
        for c in (
            StoricoContratto.objects
            .filter(legacy_anagrafica_id__isnull=False)
            .order_by("legacy_anagrafica_id", "-data_inizio", "-created_at")
        ):
            ultimo_contratto.setdefault(c.legacy_anagrafica_id, c)

        scadenze: list[tuple[int, object, str]] = []
        for legacy_id, c in ultimo_contratto.items():
            if legacy_id in cessati or c.data_fine is None:
                continue
            tip = c.tipologia_contratto or "a termine"
            scadenze.append((legacy_id, c.data_fine, f"Contratto {tip}"))
        prova_rows = DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=True,
            prova_data_fine__isnull=False,
            prova_data_fine__gte=oggi,
        ).values_list("legacy_anagrafica_id", "prova_data_fine")
        for legacy_id, fine_prova in prova_rows:
            scadenze.append((legacy_id, fine_prova, "Fine periodo di prova"))

        for legacy_id, data_fine, descrizione in scadenze:
            if filtro_stato == "scaduta":
                if data_fine >= oggi:
                    continue
            elif filtro_stato == "30":
                if not (oggi <= data_fine <= soglia_30):
                    continue
            elif filtro_stato == "60":
                if not (oggi <= data_fine <= soglia_60):
                    continue
            elif data_fine > soglia_60:
                continue
            _add("Contratto", legacy_id, descrizione, data_fine)

    voci.sort(key=lambda v: v["_giorni"])
    for v in voci:
        v.pop("_giorni", None)
    return voci


def _scadenzario_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    tipi = {
        "qualifica": "Solo qualifiche",
        "visita": "Solo visite mediche",
        "formazione": "Solo formazione obbligatoria",
        "contratto": "Solo contratti / prova",
    }
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    if filtro_tipo in tipi:
        parts.append(f"Tipo: {tipi[filtro_tipo]}")
    stati = {
        "scaduta": "Solo scadute",
        "30": "Entro 30 giorni",
        "60": "Entro 60 giorni",
    }
    filtro_stato = (request.GET.get("stato") or "").strip()
    if filtro_stato in stati:
        parts.append(f"Stato: {stati[filtro_stato]}")
    else:
        parts.append("Scadute + entro 60gg")
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    if filtro_reparto:
        parts.append(f"Reparto: {filtro_reparto}")
    return " · ".join(parts)


register(ExportSpec(
    key="scadenzario",
    title="Scadenzario HR generale",
    sheet_title="Scadenzario",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Tipo", "tipo"),
        ("Descrizione", "descrizione"),
        ("Scadenza", "scadenza"),
        ("Stato", "stato"),
    ],
    dataset=_scadenzario_rows,
    filters_label=_scadenzario_filters,
    permission=acl_gate("/anagrafica/scadenzario/"),
))


# ── Conformità alla mansione ─────────────────────────────────────────────────
# Filtri e colonne rispecchiano `views.conformita_report`
# (reparto / esito / idoneita / mansione) e il suo export CSV storico.

_CONF_LABEL = {
    "ok": "In regola",
    "warn": "In scadenza",
    "ko": "Non conforme",
    "na": "Nessun requisito",
}
_CONF_LABEL_IDN = {
    "ok": "Idoneo",
    "warn": "Idoneo con riserve",
    "ko": "Non idoneo",
    "na": "Non valutabile",
}


def _conformita_rows(request: HttpRequest, scope: str) -> list[dict]:
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from anagrafica.services import conformita as conformita_service
    from anagrafica.views import _can_view_visite_mediche

    ensure_anagrafica_schema()
    can_view_visite = _can_view_visite_mediche(request)

    filtered = scope == "filtered"
    filtro_reparto = (request.GET.get("reparto") or "").strip() if filtered else ""
    filtro_esito = (request.GET.get("esito") or "").strip() if filtered else ""
    filtro_idoneita = (request.GET.get("idoneita") or "").strip() if filtered else ""
    filtro_mansione = (request.GET.get("mansione") or "").strip() if filtered else ""

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    mansioni_per_legacy = {
        lid: str(dip.get("mansione") or "").strip()
        for lid, dip in dip_map.items()
        if str(dip.get("mansione") or "").strip()
    }
    stati = conformita_service.stato_conformita_batch(
        list(dip_map.keys()),
        include_visite_dettaglio=can_view_visite,
        mansioni_per_legacy=mansioni_per_legacy,
    )

    ordine = {
        conformita_service.ESITO_KO: 0,
        conformita_service.ESITO_WARN: 1,
        conformita_service.ESITO_OK: 2,
        conformita_service.ESITO_NA: 3,
    }
    na = {"esito": conformita_service.ESITO_NA, "dettagli": []}

    righe: list[dict] = []
    for legacy_id, dip in dip_map.items():
        reparto = str(dip.get("reparto") or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        mansione_nome = str(dip.get("mansione") or "").strip()
        if filtro_mansione and mansione_nome.casefold() != filtro_mansione.casefold():
            continue
        stato = stati.get(legacy_id, {"complessivo": conformita_service.ESITO_NA})
        complessivo = stato.get("complessivo", conformita_service.ESITO_NA)
        if filtro_esito and complessivo != filtro_esito:
            continue
        idoneita = stato.get("idoneita", {"esito": conformita_service.ESITO_NA})
        if filtro_idoneita and idoneita.get("esito") != filtro_idoneita:
            continue

        cognome = str(dip.get("cognome") or f"ID {legacy_id}").strip()
        nome = str(dip.get("nome") or "").strip()
        da_soddisfare = "; ".join(
            list(idoneita.get("scaduti", [])) + list(idoneita.get("mancanti", []))
        )
        righe.append({
            "_ordine": (ordine.get(complessivo, 9), cognome.casefold(), nome.casefold()),
            "dipendente": f"{cognome} {nome}".strip(),
            "reparto": reparto,
            "mansione": mansione_nome,
            "conformita": _CONF_LABEL.get(complessivo, complessivo),
            "idoneita": _CONF_LABEL_IDN.get(idoneita.get("esito"), idoneita.get("esito") or ""),
            "da_soddisfare": da_soddisfare,
            "formazione": _CONF_LABEL.get(stato.get("formazione", na)["esito"], ""),
            "visite": _CONF_LABEL.get(stato.get("visite", na)["esito"], ""),
            "qualifiche": _CONF_LABEL.get(stato.get("qualifiche", na)["esito"], ""),
            "dpi": _CONF_LABEL.get(stato.get("dpi", na)["esito"], ""),
        })

    righe.sort(key=lambda r: r["_ordine"])
    for r in righe:
        r.pop("_ordine", None)
    return righe


def _conformita_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    filtro_esito = (request.GET.get("esito") or "").strip()
    if filtro_esito in _CONF_LABEL:
        parts.append(f"Conformità: {_CONF_LABEL[filtro_esito]}")
    filtro_idoneita = (request.GET.get("idoneita") or "").strip()
    if filtro_idoneita in _CONF_LABEL_IDN:
        parts.append(f"Idoneità: {_CONF_LABEL_IDN[filtro_idoneita]}")
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    if filtro_reparto:
        parts.append(f"Reparto: {filtro_reparto}")
    filtro_mansione = (request.GET.get("mansione") or "").strip()
    if filtro_mansione:
        parts.append(f"Mansione: {filtro_mansione}")
    return " · ".join(parts)


register(ExportSpec(
    key="conformita",
    title="Conformità alla mansione",
    sheet_title="Conformità",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Mansione", "mansione"),
        ("Conformità", "conformita"),
        ("Idoneità mansione", "idoneita"),
        ("Requisiti da soddisfare", "da_soddisfare"),
        ("Formazione", "formazione"),
        ("Visite mediche", "visite"),
        ("Qualifiche", "qualifiche"),
        ("DPI", "dpi"),
    ],
    dataset=_conformita_rows,
    filters_label=_conformita_filters,
    permission=_hr_gate("/anagrafica/conformita/"),
))


# ── Organigramma (lista piatta) ──────────────────────────────────────────────
# Filtro `reparto` come `views.organigramma`. L'albero a schermo diventa qui una
# riga per persona: reparto, aree aziendali del reparto, ruolo (capo/collaboratore)
# e responsabile. I dipendenti con reparto legacy non a catalogo ("Non mappati")
# entrano solo quando non c'è filtro reparto, come nella pagina.

def _organigramma_rows(request: HttpRequest, scope: str) -> list[dict]:
    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from anagrafica.models import Reparto

    ensure_anagrafica_schema()
    filtro_reparto = (
        (request.GET.get("reparto") or "").strip() if scope == "filtered" else ""
    )

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    reparti = list(
        Reparto.objects.filter(is_active=True)
        .prefetch_related("aree_aziendali")
        .order_by("nome")
    )
    reparto_by_name = {r.nome.strip().casefold(): r for r in reparti}

    membri_per_reparto: dict[int, list[dict]] = {}
    non_mappati: list[dict] = []
    for row in dip_rows:
        nome_rep = str(row.get("reparto") or "").strip()
        rep = reparto_by_name.get(nome_rep.casefold()) if nome_rep else None
        if rep is None:
            non_mappati.append(row)
        else:
            membri_per_reparto.setdefault(rep.id, []).append(row)

    def _sort_key(row: dict):
        return (
            str(row.get("cognome") or "").casefold(),
            str(row.get("nome") or "").casefold(),
        )

    def _nome(row: dict) -> str:
        return (
            f"{str(row.get('cognome') or '').strip()} {str(row.get('nome') or '').strip()}"
        ).strip()

    righe: list[dict] = []
    for rep in reparti:
        if filtro_reparto and rep.nome.casefold() != filtro_reparto.casefold():
            continue
        capo = dip_map.get(rep.caporeparto_legacy_id or 0)
        aree = ", ".join(
            a.nome for a in rep.aree_aziendali.filter(is_active=True).order_by("nome")
        )
        responsabile = _nome(capo) if capo else ""
        membri = sorted(membri_per_reparto.get(rep.id, []), key=_sort_key)
        if capo:
            membri = [m for m in membri if int(m.get("id") or 0) != int(capo.get("id") or 0)]
            righe.append({
                "dipendente": _nome(capo),
                "reparto": rep.nome,
                "aree": aree,
                "mansione": str(capo.get("mansione") or "").strip(),
                "ruolo": "Caporeparto",
                "responsabile": responsabile,
            })
        for m in membri:
            righe.append({
                "dipendente": _nome(m),
                "reparto": rep.nome,
                "aree": aree,
                "mansione": str(m.get("mansione") or "").strip(),
                "ruolo": "Collaboratore",
                "responsabile": responsabile,
            })

    if not filtro_reparto:
        for m in sorted(non_mappati, key=_sort_key):
            righe.append({
                "dipendente": _nome(m),
                "reparto": str(m.get("reparto") or "").strip(),
                "aree": "",
                "mansione": str(m.get("mansione") or "").strip(),
                "ruolo": "Reparto non a catalogo",
                "responsabile": "",
            })

    return righe


def _organigramma_filters(request: HttpRequest) -> str:
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    return f"Reparto: {filtro_reparto}" if filtro_reparto else ""


register(ExportSpec(
    key="organigramma",
    title="Organigramma",
    sheet_title="Organigramma",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Aree aziendali", "aree"),
        ("Mansione", "mansione"),
        ("Ruolo", "ruolo"),
        ("Responsabile", "responsabile"),
    ],
    dataset=_organigramma_rows,
    filters_label=_organigramma_filters,
    permission=acl_gate("/anagrafica/organigramma/"),
))
