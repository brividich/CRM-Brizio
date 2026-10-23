"""Viste anagrafica — Persone: elenco, scheda, creazione, onboarding/offboarding, documenti.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import timedelta as _timedelta
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, connections, transaction
from django.db.models import Count, Q
from django.http import (
    Http404, HttpResponse, HttpResponseForbidden, HttpResponseNotFound,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from core.legacy_anagrafica import (
    count_anagrafica_statuses,
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
    generate_username,
    normalize_legacy_alias,
    upsert_anagrafica_dipendente,
)
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns

from ..forms import (
    AnagraficaAziendaleForm,
    AnagraficaCivileForm,
    FiglioACaricoFormSet,
    DipendenteLegacyForm,
    VisitaMedicaForm,
)
from ..models import (
    AnagraficaStatPermission,
    AreaAziendale,
    Reparto,
    CartellaDocumentoDipendente,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteAssegnazione,
    DipendenteCambiamentoOrganizzativo,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    DocumentoDipendente,
    ImportazioneRetributiva,
    LivelloContrattuale,
    Mansione,
    OffboardingPratica,
    OffboardingTask,
    OnboardingOffboardingCampo,
    OnboardingPratica,
    OnboardingTask,
    RuoloOperativo,
    SaldoCedolino,
    StoricoContratto,
    TipologiaContratto,
    TipoQualifica,
    TipoVisitaMedica,
    DipendenteVisitaFacoltativa,
    VisitaMedica,
    VoceRetributiva,
    _classify_pay_item,
)
from ..models_formazione import (
    TrainingCertificate,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingExportLog,
)
from ..services.dpi_ingresso import (
    RigaConsegnaIniziale,
    archivia_pdf_cumulativo,
    crea_consegne_iniziali,
)
from ..services.visite import (
    stato_visite,
    ultime_visite_correnti_ids,
    visite_storico,
)
from ..services import conformita as conformita_service
from ..services import onboarding as onboarding_service
from ..services import account_portale
from ..services import avviso_it_ingresso
from .. import views_account
from ..services import mansionario as mansionario_service
from ..acl_bootstrap import (
    PERM_STATISTICHE_VIEW,
    PERM_VISITE_DELETE,
)
from core.upload_limits import DOCUMENT_MAX_BYTES, DOCUMENT_MAX_MB

from automazioni.managed_flows import event_flow

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _foto_dipendente_url(civile, legacy_id, miniatura: bool = False) -> str:
    """URL della view protetta che serve la foto profilo (storage privato).

    La foto NON ha più un URL pubblico /media/: ``ImageField.url`` solleva
    ``NotImplementedError`` su ``PrivateAnagraficaStorage``. Restituisce l'URL
    della view solo se il dipendente ha effettivamente una foto, altrimenti ""
    (così i template applicano il fallback iniziali).

    ``miniatura=True`` (elenchi): chiede l'icona piccola con la versione della foto
    nell'URL, così il browser la tiene finché la foto non cambia.
    """
    if not civile or not getattr(civile, "foto", None):
        return ""
    url = reverse("anagrafica:foto_dipendente", args=[int(legacy_id)])
    if miniatura:
        url += f"?m={_foto_versione(civile.foto.name)}"
    return url


def _foto_versione(nome: str) -> str:
    """Impronta corta del nome file: cambia a ogni nuova foto (il nome ha data e ora)."""
    import hashlib

    return hashlib.sha1(str(nome or "").encode("utf-8")).hexdigest()[:10]


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique_legacy_user(qs):
    users = list(qs.order_by("id")[:2])
    if len(users) == 1:
        return users[0]
    return None


def _resolve_account_portale_dipendente(dip: dict, aziendale=None):
    stored_id = _int_or_none(getattr(aziendale, "utente_id_pre_offboarding", None)) or 0
    if stored_id:
        user = UtenteLegacy.objects.filter(id=stored_id).first()
        if user:
            return user, "utente_id_pre_offboarding"

    current_id = _int_or_none(dip.get("utente_id")) or 0
    if current_id:
        user = UtenteLegacy.objects.filter(id=current_id).first()
        if user:
            return user, "utente_id_corrente"

    email = str(dip.get("email") or "").strip()
    if email:
        user = _unique_legacy_user(UtenteLegacy.objects.filter(email__iexact=email))
        if user:
            return user, "email"

    alias = str(dip.get("aliasusername") or "").strip()
    if alias:
        if "@" in alias:
            user = _unique_legacy_user(UtenteLegacy.objects.filter(email__iexact=alias))
            if user:
                return user, "alias_email"
        else:
            user = _unique_legacy_user(UtenteLegacy.objects.filter(email__istartswith=f"{alias}@"))
            if user:
                return user, "alias_upn"

    nome = str(dip.get("nome") or "").strip()
    cognome = str(dip.get("cognome") or "").strip()
    candidate_names = [name for name in {f"{nome} {cognome}".strip(), f"{cognome} {nome}".strip()} if name]
    if candidate_names:
        name_filter = Q()
        for candidate_name in candidate_names:
            name_filter |= Q(nome__iexact=candidate_name)
        user = _unique_legacy_user(UtenteLegacy.objects.filter(name_filter))
        if user:
            return user, "nome_cognome"

    return None, ""


OFFBOARDING_RESTITUZIONI_LABELS = {
    "badge_chiavi": "Badge, chiavi, tessere",
    "device_it": "PC, telefono, SIM, token",
    "dpi_divise": "DPI, divise, attrezzature",
    "mezzi_carte": "Mezzi, carte, carburante",
    "documenti_archivi": "Documenti e archivi",
    "accessi_account": "Accessi e account da revocare",
}


OFFBOARDING_TASK_BASE = [
    {
        "codice": "hr_documenti_finali",
        "categoria": OffboardingTask.CATEGORIA_HR,
        "titolo": "Preparare documenti e chiusura HR",
        "descrizione": "Verificare comunicazioni, documenti finali e passaggi amministrativi HR.",
    },
    {
        "codice": "it_revoca_accessi",
        "categoria": OffboardingTask.CATEGORIA_IT,
        "titolo": "Revocare accessi e account",
        "descrizione": "Pianificare disattivazione account portale, AD/email, gruppi e credenziali collegate.",
    },
    {
        "codice": "responsabile_passaggio_consegne",
        "categoria": OffboardingTask.CATEGORIA_RESPONSABILE,
        "titolo": "Passaggio consegne con responsabile",
        "descrizione": "Verificare attivita aperte, documenti di reparto e consegne operative.",
    },
]

OFFBOARDING_TASK_BY_RESTITUZIONE = {
    "badge_chiavi": {
        "codice": "restituzione_badge_chiavi",
        "categoria": OffboardingTask.CATEGORIA_HR,
        "titolo": "Recuperare badge, chiavi e tessere",
        "descrizione": "Ritirare badge, chiavi, tessere e accessi fisici assegnati.",
    },
    "device_it": {
        "codice": "restituzione_device_it",
        "categoria": OffboardingTask.CATEGORIA_IT,
        "titolo": "Recuperare dotazioni IT",
        "descrizione": "Ritirare PC, telefono, SIM, token, accessori e verificare eventuali backup.",
    },
    "dpi_divise": {
        "codice": "restituzione_dpi_divise",
        "categoria": OffboardingTask.CATEGORIA_DPI,
        "titolo": "Recuperare DPI, divise e attrezzature",
        "descrizione": "Verificare DPI, divise, utensili e attrezzature assegnate.",
    },
    "mezzi_carte": {
        "codice": "restituzione_mezzi_carte",
        "categoria": OffboardingTask.CATEGORIA_AMMINISTRAZIONE,
        "titolo": "Recuperare mezzi, carte e carburante",
        "descrizione": "Ritirare veicoli, carte aziendali, carte carburante o altri strumenti amministrativi.",
    },
    "documenti_archivi": {
        "codice": "restituzione_documenti_archivi",
        "categoria": OffboardingTask.CATEGORIA_RESPONSABILE,
        "titolo": "Recuperare documenti e archivi",
        "descrizione": "Verificare documenti, archivi locali e materiali di reparto da rientrare.",
    },
    "accessi_account": {
        "codice": "restituzione_accessi_account",
        "categoria": OffboardingTask.CATEGORIA_IT,
        "titolo": "Verificare accessi applicativi da revocare",
        "descrizione": "Controllare applicativi, cartelle condivise, licenze e permessi specifici.",
    },
}


def _offboarding_task_definitions(restituzioni_codes: list[str]) -> list[dict]:
    tasks = list(OFFBOARDING_TASK_BASE)
    existing_codes = {task["codice"] for task in tasks}
    for code in restituzioni_codes:
        task = OFFBOARDING_TASK_BY_RESTITUZIONE.get(code)
        if task and task["codice"] not in existing_codes:
            tasks.append(task)
            existing_codes.add(task["codice"])
    for task in _offboarding_configured_field_tasks():
        if task["codice"] not in existing_codes:
            tasks.append(task)
            existing_codes.add(task["codice"])
    return tasks


def _offboarding_is_admin(request) -> bool:
    return _helpers._is_anagrafica_admin(request)


def _workflow_task_code(field_key: str) -> str:
    safe = "".join(
        ch if ch.isalnum() else "_"
        for ch in (field_key or "").strip().lower()
    ).strip("_")
    return f"campo_{safe or 'configurato'}"[:60]


def _offboarding_configured_field_tasks() -> list[dict]:
    configured = OnboardingOffboardingCampo.objects.filter(
        fase=OnboardingOffboardingCampo.FASE_OFFBOARDING,
        is_active=True,
    ).order_by("ordine", "campo_label")
    tasks: list[dict] = []
    for item in configured:
        description_parts = []
        if item.sezione:
            description_parts.append(f"Sezione + Nuovo dipendente: {item.sezione}.")
        if item.note:
            description_parts.append(item.note)
        if item.obbligatorio:
            description_parts.append("Campo marcato come obbligatorio nel workflow.")
        tasks.append({
            "codice": _workflow_task_code(item.campo_key),
            "categoria": item.categoria,
            "titolo": f"Verificare {item.campo_label}",
            "descrizione": " ".join(description_parts).strip(),
        })
    return tasks


def _offboarding_dipendente_nome(dip: dict) -> str:
    cognome = str(dip.get("cognome") or "").strip()
    nome = str(dip.get("nome") or "").strip()
    legacy_id = dip.get("id") or ""
    return naming.nome_completo(nome, cognome) or f"#{legacy_id}".strip()


# ---------------------------------------------------------------------------
# Dashboard anagrafica
# ---------------------------------------------------------------------------

# Righe del blocco «Cose da gestire»: una per sorgente dello scadenzario, nello
# stesso ordine in cui vanno affrontate. Il gating per sorgente è già dentro
# _build_scadenzario_voci — qui non si decide chi vede cosa.
_COSE_DA_GESTIRE_KINDS = [
    ("visita",     "🩺", "Visite mediche"),
    ("qualifica",  "🎓", "Qualifiche"),
    ("formazione", "📘", "Corsi obbligatori"),
    ("contratto",  "📄", "Contratti e periodi di prova"),
]
# Concordanza: «Corsi obbligatori scaduti», «Contratti … scaduti», «Visite … scadute».
_COSE_DA_GESTIRE_MASCHILI = {"formazione", "contratto"}


def _build_cose_da_gestire(request, dip_map: dict) -> list[dict]:
    """Righe azionabili della dashboard HR, contate sulle voci dello scadenzario.

    Ogni riga porta allo scadenzario già filtrato su ciò che ha appena contato:
    numero e lista vengono dalla stessa funzione, quindi non possono divergere.
    Le righe a zero non compaiono — una dashboard elenca le cose da fare, non le
    cose che non ci sono.
    """
    voci = _helpers._build_scadenzario_voci(request, dip_map=dip_map)
    base = reverse("anagrafica:scadenzario")

    scadute: list[dict] = []
    in_scadenza: list[dict] = []
    for kind, icona, label in _COSE_DA_GESTIRE_KINDS:
        voci_kind = [v for v in voci if v["kind"] == kind]
        n_scadute = sum(1 for v in voci_kind if v["scaduta"])
        # Le voci non scadute che _build_scadenzario_voci restituisce senza filtro
        # stato sono già solo quelle entro 60 giorni.
        n_prossime = len(voci_kind) - n_scadute
        if n_scadute:
            scadute.append({
                "icona": icona,
                "titolo": f"{label} {'scaduti' if kind in _COSE_DA_GESTIRE_MASCHILI else 'scadute'}",
                "count": n_scadute,
                "urgente": True,
                "url": f"{base}?tipo={kind}&stato=scaduta",
            })
        if n_prossime:
            in_scadenza.append({
                "icona": icona,
                "titolo": f"{label} in scadenza (60 giorni)",
                "count": n_prossime,
                "urgente": False,
                "url": f"{base}?tipo={kind}&stato=60",
            })
    return scadute + in_scadenza


@login_required
def index(request):
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(deduplicate=True)
    # Esclude gli ex dipendenti (rapporto cessato) dai KPI "in organico":
    # restano a sistema solo per storico ma non concorrono al conteggio attivi.
    cessati_ids = _helpers._cessati_legacy_ids()
    rows_attivi = [row for row in rows if int(row.get("id") or 0) not in cessati_ids]
    n_dipendenti = len(rows_attivi)
    n_reparti = len({str(row.get("reparto") or "").strip().casefold() for row in rows_attivi if str(row.get("reparto") or "").strip()})

    # Conteggi catalogo per dashboard HR
    n_mansioni = Mansione.objects.filter(is_active=True).count()
    n_aree = AreaAziendale.objects.filter(is_active=True).count()
    n_reparti_catalog = Reparto.objects.filter(is_active=True).count()
    n_qualifiche = TipoQualifica.objects.filter(is_active=True).count()

    # Qualifiche scadute e in scadenza (prossimi 60 giorni)
    from datetime import timedelta
    from django.utils import timezone as tz
    oggi = tz.localdate()
    soglia = oggi + timedelta(days=60)
    n_qualifiche_scadute = DipendenteQualifica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lt=oggi
    ).count()
    n_qualifiche_scadenza = DipendenteQualifica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__gte=oggi, data_scadenza__lte=soglia
    ).count()

    # Visite mediche scadute (dato sanitario sensibile: gating)
    can_view_visite = _helpers._can_view_visite_mediche(request)
    n_visite_scadute = 0
    if can_view_visite:
        n_visite_scadute = VisitaMedica.objects.filter(
            id__in=ultime_visite_correnti_ids(), data_scadenza__lt=oggi
        ).count()

    # Cose da gestire: righe azionabili contate sulle voci dello scadenzario.
    # `dip_map` riusa le righe legacy già lette a inizio view — nessun secondo fetch.
    dip_map = {int(row["id"]): row for row in rows if row.get("id")}
    cose_da_gestire = _build_cose_da_gestire(request, dip_map)

    # Cruscotto HR dal motore unico dei requisiti (stessi numeri di libretto,
    # reportistica e scadenzario). Un errore qui non deve togliere la dashboard.
    cruscotto = None
    try:
        from ..services.cruscotto_hr import calcola as calcola_cruscotto
        cruscotto = calcola_cruscotto(include_visite=can_view_visite)
        n_dipendenti = cruscotto.persone
        n_qualifiche_scadute = cruscotto.n_qualifiche_scadute
        n_qualifiche_scadenza = cruscotto.n_qualifiche_in_scadenza
    except Exception:
        logger.exception("Cruscotto HR non calcolabile")

    return render(request, "anagrafica/pages/index.html", {
        "n_dipendenti": n_dipendenti,
        "n_reparti": n_reparti,
        "n_mansioni": n_mansioni,
        # Il catalogo ha due livelli: Reparto (contenitore) e AreaAziendale (figlia,
        # FK `reparto`). Il KPI «Reparti (catalogo)» mostrava `n_aree`, cioè le aree:
        # un numero giusto sotto l'etichetta sbagliata.
        "n_reparti_catalog": n_reparti_catalog,
        "n_aree": n_aree,
        "n_qualifiche": n_qualifiche,
        "n_qualifiche_scadute": n_qualifiche_scadute,
        "n_qualifiche_scadenza": n_qualifiche_scadenza,
        "can_view_visite": can_view_visite,
        "n_visite_scadute": n_visite_scadute,
        "cose_da_gestire": cose_da_gestire,
        "cruscotto": cruscotto,
        "cruscotto_coperture": (
            [("Formazione obbligatoria", cruscotto.formazione)]
            + ([("Sorveglianza sanitaria", cruscotto.visite)] if cruscotto.visite else [])
        ) if cruscotto else [],
        "can_admin": _helpers._is_anagrafica_admin(request),
        # Fascia «Vai a»: i sottomoduli gated non compaiono a chi vedrebbe solo un
        # rifiuto. La nav non è un confine di sicurezza — le view restano gated.
        "can_view_formazione": _helpers._can_view_formazione(request),
        "can_view_hr": _helpers._check_hr_permission(request),
    })


# ---------------------------------------------------------------------------
# Dipendenti (sola lettura — dati da legacy SQL Server)
# ---------------------------------------------------------------------------

def _dipendenti_base_rows() -> list[dict]:
    """Righe dell'anagrafica in forza (legacy, deduplicate), pre-filtro.

    Esclude i rapporti cessati e risolve il reparto dalla **fonte unica
    canonica** (``dipendente → area_aziendale → reparto``): il reparto
    canonico ha **precedenza sul testo legacy**, così le tabelle non mostrano
    più il vecchio reparto quando l'assegnazione canonica è cambiata. Se non
    c'è canonico si tiene il testo legacy della riga; se anche quello è vuoto
    si ripiega su ``DipendenteAnagraficaAziendale.area``. Ogni riga riceve
    anche ``area_aziendale_nome`` (l'accoppiata reparto + area).
    """
    from anagrafica.services.reparto_canonico import enrich_rows_reparto_canonico

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(deduplicate=True)
    # Gli ex dipendenti (rapporto cessato) restano a sistema ma non compaiono
    # mai in questa lista: hanno una vista dedicata `ex_dipendenti_list`.
    cessati_ids = _helpers._cessati_legacy_ids()
    rows = [row for row in rows if int(row.get("id") or 0) not in cessati_ids]

    # Reparto/area CANONICI (precedenza sul testo legacy stantio).
    enrich_rows_reparto_canonico(rows)

    # Fallback finale: testo `.area` sull'aziendale, solo per chi non ha né
    # canonico (reparto non toccato dall'enricher) né testo legacy sulla riga.
    _ids_no_reparto = [int(r.get("id") or 0) for r in rows if not str(r.get("reparto") or "").strip()]
    if _ids_no_reparto:
        _az_area_text = dict(
            DipendenteAnagraficaAziendale.objects
            .filter(legacy_anagrafica_id__in=_ids_no_reparto)
            .exclude(area="")
            .values_list("legacy_anagrafica_id", "area")
        )
        for row in rows:
            if not str(row.get("reparto") or "").strip():
                lid = int(row.get("id") or 0)
                if lid in _az_area_text:
                    row["reparto"] = _az_area_text[lid]
    return rows


def _filter_dipendenti_rows(rows: list[dict], request) -> list[dict]:
    """Filtri della lista dipendenti (q / reparto / area / tipologia_contratto)."""
    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()

    if q:
        q_norm = q.casefold()
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
        rows = [row for row in rows if str(row.get("reparto") or "").strip().casefold() == reparto.casefold()]

    # Filtri su campi Django (area, tipologia_contratto)
    if area_filter or contratto_filter:
        az_qs = DipendenteAnagraficaAziendale.objects.all()
        if area_filter:
            az_qs = az_qs.filter(area__iexact=area_filter)
        if contratto_filter:
            az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
        allowed_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))
        rows = [row for row in rows if int(row.get("id") or 0) in allowed_ids]
    return rows


def _sort_dipendenti_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda row: (
        str(row.get("cognome") or "").strip().casefold(),
        str(row.get("nome") or "").strip().casefold(),
        str(row.get("aliasusername") or "").strip().casefold(),
        int(row.get("id") or 0),
    ))
    return rows


def build_dipendenti_rows(
    request,
    *,
    apply_filters: bool = True,
    base_rows: list[dict] | None = None,
) -> list[dict]:
    """Righe dell'elenco dipendenti (legacy + fallback reparto), filtrate e ordinate.

    Fonte unica condivisa tra la view ``dipendenti_list`` e l'export
    (``anagrafica.exports``): il filtro non va duplicato altrove, o le due
    superfici divergono (drift). La view passa ``base_rows`` (le righe
    pre-filtro già calcolate per ``n_totale``/``reparti``) per evitare un
    secondo fetch legacy; l'export, che non ha già una base, lascia che
    l'helper la calcoli da sé.
    """
    rows = base_rows if base_rows is not None else _dipendenti_base_rows()
    if _helpers._ruoli_attivi():
        # Ruoli: elenco ed export mostrano solo le schede visibili (propri / team / tutti).
        visibili = _schede_visibili(request)
        if visibili is not None:
            rows = [r for r in rows if int(r.get("id") or 0) in visibili]
    if apply_filters:
        rows = _filter_dipendenti_rows(rows, request)
    return _sort_dipendenti_rows(list(rows))


def ruoli_ricoperti_map(legacy_ids: list[int]) -> dict[int, list[dict]]:
    """Ruoli **in essere** per dipendente, principale in testa.

    Una persona ricopre spesso più ruoli insieme perché gli ambiti si
    sovrappongono (produttivo, SGSL 45001, SGSI 27001 — vedi ``AmbitoRuolo``):
    il solo «Ruolo aziendale» della scheda ne mostrerebbe uno soltanto, per
    questo le liste persone li mostrano tutti sotto il nome.

    Le assegnazioni concluse (``data_fine`` passata) sono storia, non ruoli
    ricoperti: restano nella scheda del dipendente e non compaiono qui. Idem
    per i ruoli disattivati in catalogo.
    """
    ids = [int(value) for value in legacy_ids if int(value or 0) > 0]
    if not ids:
        return {}

    oggi = django_timezone.localdate()
    mappa: dict[int, list[dict]] = {}
    for assegnazione in (
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id__in=ids, ruolo__is_active=True)
        .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
        .select_related("ruolo")
        .order_by("ruolo__nome")
    ):
        mappa.setdefault(int(assegnazione.legacy_anagrafica_id), []).append({
            "nome": assegnazione.ruolo.nome,
            "principale": assegnazione.tipologia == DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE,
        })
    # Il principale davanti: è quello che vale come «Ruolo aziendale».
    for voci in mappa.values():
        voci.sort(key=lambda voce: (0 if voce["principale"] else 1, voce["nome"]))
    return mappa


@login_required
def dipendenti_list(request):
    from ..services import colonne_elenco, viste_elenco

    # Vista configurabile (prompt 03): colonne dal registro, filtrate dai permessi dell'utente.
    vista = viste_elenco.vista_corrente(request)
    if (vista and vista.filtri and request.GET.get("vf") != "0"
            and not any(k in request.GET for k in ("q", "reparto", "area", "tipologia_contratto"))):
        filtri = request.GET.copy()
        for chiave, valore in vista.filtri.items():
            if chiave in ("reparto", "area", "tipologia_contratto") and valore:
                filtri[chiave] = valore
        request.GET = filtri
    colonne = viste_elenco.colonne_richieste(request, vista)
    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()

    rows_all = _dipendenti_base_rows()
    # NB: `reparti_list` e `n_totale` sono calcolati sulle righe PRE-filtro.
    reparti_list = sorted({str(row.get("reparto") or "").strip() for row in rows_all if str(row.get("reparto") or "").strip()})
    n_totale = len(rows_all)
    cessati_ids = _helpers._cessati_legacy_ids()

    # Stessa costruzione righe dell'export (`anagrafica.exports._dipendenti_rows`
    # → `build_dipendenti_rows`): passare `rows_all` come base evita un secondo
    # fetch legacy pur restando sull'unica fonte condivisa filtro/ordina.
    rows = build_dipendenti_rows(request, base_rows=rows_all)

    _helpers.aree_list = sorted(
        DipendenteAnagraficaAziendale.objects.exclude(area="")
        .values_list("area", flat=True)
        .distinct()
        .order_by("area")
    )

    user_map = {
        int(user.id): user
        for user in UtenteLegacy.objects.filter(
            id__in=[int(row.get("utente_id") or 0) for row in rows if int(row.get("utente_id") or 0) > 0]
        )
    }
    for row in rows:
        raw_attivo = row.get("attivo")
        row["anagrafica_attivo"] = True if raw_attivo is None else bool(raw_attivo)
        row["matricola_legacy"] = str(row.get("matricola") or "").strip()
        row["ruolo_legacy"] = str(row.get("ruolo") or row.get("mansione") or "").strip()
        linked_user = user_map.get(int(row.get("utente_id") or 0))
        row["account_attivo"] = bool(getattr(linked_user, "attivo", False))
        row["has_account"] = bool(linked_user)
        row["timbri_operator_id"] = None
        row["timbri_count"] = 0
        row["timbri_legacy_id"] = int(row.get("id") or 0) or None

    # Pagina unica: la tabella usa ricerca/ordina/filtra per colonna lato client
    # (fm-table-enhanced.js), che opera sulle righe nel DOM. Con il volume reale
    # dell'anagrafica (~150 dipendenti) carichiamo tutto in un blocco così filtro
    # e ordinamento coprono l'intero elenco e non solo la pagina corrente.
    # Ordinamento all'apertura scelto nella vista (solo su una colonna che l'utente può vedere).
    if vista and vista.ordinamento and not request.GET.get("sort"):
        da_ordinare = colonne_elenco.colonne_da_specifica(viste_elenco.specifica([vista.ordinamento]), request)
        if da_ordinare:
            chiave_ord = da_ordinare[0]["colonna"].chiave
            colonne_elenco.arricchisci(rows, [da_ordinare[0]["colonna"]])
            pieni = [r for r in rows if (r.get("valori") or {}).get(chiave_ord, ("", None))[1] not in (None, "")]
            vuoti = [r for r in rows if r not in pieni]
            try:
                pieni.sort(key=lambda r: r["valori"][chiave_ord][1])
            except TypeError:
                pieni.sort(key=lambda r: str(r["valori"][chiave_ord][1]))
            rows = pieni + vuoti

    paginator = Paginator(rows, 500)
    page = paginator.get_page(request.GET.get("page"))

    civile_map = {
        int(obj.legacy_anagrafica_id): obj
        for obj in DipendenteAnagraficaCivile.objects.filter(
            legacy_anagrafica_id__in=[int(dip.get("id") or 0) for dip in list(page.object_list)]
        ).only("legacy_anagrafica_id", "foto")
    }
    for dip in list(page.object_list):
        civile = civile_map.get(int(dip.get("id") or 0))
        dip["foto_url"] = _foto_dipendente_url(civile, dip.get("id") or 0, miniatura=True)

    try:
        from timbri.models import OperatoreTimbri, RegistroTimbro

        operator_map: dict[int, OperatoreTimbri] = {
            int(obj.legacy_anagrafica_id): obj
            for obj in OperatoreTimbri.objects.filter(
                legacy_anagrafica_id__in=[int(dip.get("id") or 0) for dip in list(page.object_list)]
            )
            if obj.legacy_anagrafica_id
        }

        counts = {
            int(row["operatore_id"]): int(row["n"])
            for row in RegistroTimbro.objects.filter(operatore_id__in=[op.id for op in operator_map.values()])
            .order_by()
            .values("operatore_id")
            .annotate(n=Count("id"))
        }
        for dip in list(page.object_list):
            legacy_id = int(dip.get("id") or 0)
            operatore = operator_map.get(legacy_id)
            dip["timbri_operator_id"] = getattr(operatore, "id", None)
            dip["timbri_count"] = counts.get(getattr(operatore, "id", 0), 0)
            dip["timbri_legacy_id"] = legacy_id if legacy_id > 0 else None
    except Exception:
        logger.exception("Impossibile arricchire l'elenco dipendenti con i dati timbri.")
        for dip in list(page.object_list):
            dip["timbri_operator_id"] = None
            dip["timbri_count"] = 0
            dip["timbri_legacy_id"] = None

    ruoli_map = ruoli_ricoperti_map([int(dip.get("id") or 0) for dip in list(page.object_list)])
    for dip in list(page.object_list):
        dip["ruoli"] = ruoli_map.get(int(dip.get("id") or 0), [])
    colonne_elenco.arricchisci(list(page.object_list), [c["colonna"] for c in colonne])

    status_stats = count_anagrafica_statuses()
    tipologie_contratto_list = list(
        TipologiaContratto.objects.filter(is_active=True).order_by("ordine", "codice")
    )

    # Stile C: una scheda per reparto con l'organico per tipo di contratto, sullo
    # stesso perimetro visibile dell'elenco (senza i filtri della barra).
    from ..services import sezioni_c
    visibili = build_dipendenti_rows(request, base_rows=rows_all, apply_filters=False)
    tipologia_per_id = dict(
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=[int(r.get("id") or 0) for r in visibili])
        .values_list("legacy_anagrafica_id", "tipologia_contratto")
    )
    nomi_tipologia = dict(TipologiaContratto.objects.values_list("codice", "nome"))
    schede_reparti, legenda_reparti = sezioni_c.schede_reparti(
        visibili, {k: (v or "") for k, v in tipologia_per_id.items()}, nomi_tipologia, reparto_attivo=reparto,
    )
    reparti_griglia = sezioni_c.griglia(
        id="fmd-reparti", titolo="Reparti", icona="i-building",
        aside="Organico per tipo di contratto · clic per filtrare l'elenco",
        schede=schede_reparti, legenda=legenda_reparti,
        ordini=[("n", "Per organico"), ("az", "A–Z")],
        vuoto_titolo="Nessun dipendente in elenco",
    )
    contratti_in_scadenza = [
        v for v in _helpers._build_scadenzario_voci(request, filtro_tipo="contratto") if v["giorni"] >= 0
    ] if _helpers._check_hr_permission(request) else None
    aree_sezione = sezioni_c.aree_visibili(request, [
        sezioni_c.Area("anagrafica:dipendente_create", "Nuovo dipendente", "Scheda vuota", icona="i-plus"),
        sezioni_c.Area("anagrafica:ex_dipendenti_list", "Ex dipendenti", "Rapporti cessati", icona="i-clock"),
        sezioni_c.Area("anagrafica:documenti_list", "Documenti", "Tutti i documenti HR", icona="i-doc"),
        sezioni_c.Area("anagrafica:organigramma", "Organigramma", "Albero e diagramma", icona="i-users"),
        sezioni_c.Area("anagrafica:aree_list", "Reparti", "Catalogo e capireparto", icona="i-building"),
        sezioni_c.Area("anagrafica:mansioni_list", "Mansioni", "Catalogo mansioni", icona="i-clipboard"),
        sezioni_c.Area("anagrafica:dipendenti_report", "Report dipendenti", "Elenco filtrabile con export", icona="i-download"),
    ])
    return render(request, "anagrafica/pages/dipendenti_list.html", {
        "reparti_griglia": reparti_griglia,
        "contratti_in_scadenza": contratti_in_scadenza,
        "aree_sezione": aree_sezione,
        "page_obj": page,
        "q": q,
        "reparto": reparto,
        "area": area_filter,
        "tipologia_contratto": contratto_filter,
        "reparti": reparti_list,
        "aree": _helpers.aree_list,
        "tipologie_contratto": tipologie_contratto_list,
        "n_totale": n_totale,
        "n_reparti": len(reparti_list),
        "n_attivi": status_stats["active"],
        "n_non_attivi": status_stats["inactive"],
        "n_ex": len(cessati_ids),
        "vista": vista,
        "viste": viste_elenco.viste_per_utente(request),
        "colonne": colonne,
        "puo_gestire_viste": _helpers._is_anagrafica_admin(request),
        "table_id": "anagrafica.dipendenti.list" + (f":{vista.codice}" if vista else ""),
    })


# ---------------------------------------------------------------------------
# Ex dipendenti — vista dedicata ai rapporti cessati
# ---------------------------------------------------------------------------

@login_required
def ex_dipendenti_list(request):
    """Elenco degli ex dipendenti (rapporto di lavoro cessato).

    Vista separata dalla lista dipendenti in forza: questi nominativi restano a
    sistema con il fascicolo completo (documenti, retribuzioni, storico) ma non
    compaiono tra i dipendenti attivi. Un dipendente è qui quando la sua
    anagrafica aziendale ha una ``data_cessazione`` valorizzata.
    """
    ensure_anagrafica_schema()
    q = request.GET.get("q", "").strip()

    cessati_ids = _helpers._cessati_legacy_ids()
    rows = [
        row
        for row in fetch_anagrafica_rows(deduplicate=True)
        if int(row.get("id") or 0) in cessati_ids
    ]
    if q:
        q_norm = q.casefold()
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
    civile_map = {
        int(obj.legacy_anagrafica_id): obj
        for obj in DipendenteAnagraficaCivile.objects.filter(
            legacy_anagrafica_id__in=cessati_ids
        ).only("legacy_anagrafica_id", "foto")
    }
    for row in rows:
        legacy_id = int(row.get("id") or 0)
        az = az_map.get(legacy_id)
        civile = civile_map.get(legacy_id)
        row["legacy_id"] = legacy_id
        row["matricola_legacy"] = str(row.get("matricola") or "").strip()
        row["foto_url"] = _foto_dipendente_url(civile, legacy_id, miniatura=True)
        row["data_cessazione"] = getattr(az, "data_cessazione", None)
        row["data_assunzione"] = (
            getattr(az, "data_assunzione_ultima", None)
            or getattr(az, "data_prima_assunzione", None)
        )
        row["tipologia_contratto_display"] = (
            az.get_tipologia_contratto_display() if az and az.tipologia_contratto else ""
        )

    rows.sort(key=lambda row: (
        row.get("data_cessazione") or date.min,
        str(row.get("cognome") or "").strip().casefold(),
        str(row.get("nome") or "").strip().casefold(),
    ), reverse=True)

    # Pagina unica per filtro/ordinamento client-side completo (vedi dipendenti_list).
    paginator = Paginator(rows, 500)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/ex_dipendenti_list.html", {
        "page_obj": page,
        "q": q,
        "n_ex": len(cessati_ids),
    })


# ---------------------------------------------------------------------------
# Dipendente — creazione completa (legacy + civile + aziendale)
# ---------------------------------------------------------------------------

@login_required
def dipendente_create(request):
    ensure_anagrafica_schema()
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Non hai i permessi per creare un dipendente.")
        return redirect("anagrafica:dipendenti_list")

    can_hr = _helpers._check_hr_permission(request)

    if request.method == "POST":
        legacy_form = DipendenteLegacyForm(request.POST)
        form_civile = AnagraficaCivileForm(request.POST, request.FILES)
        form_aziendale = AnagraficaAziendaleForm(request.POST)
        formset_figli = FiglioACaricoFormSet(request.POST, prefix="figli")

        # Le form civile/aziendale sono facoltative: ignora errori se tutti i campi sono vuoti
        civile_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and not k.startswith("az_") and not k.startswith("legacy_")
            and v and k in AnagraficaCivileForm().fields
        ) or bool(request.FILES)
        aziendale_has_data = any(
            v for k, v in request.POST.items()
            if k not in ("csrfmiddlewaretoken",) and v and k in AnagraficaAziendaleForm().fields
        )

        scelta_account = account_portale.scelta_da_post(request.POST)
        errori_account: list[str] = []
        if legacy_form.is_valid():
            errori_account = account_portale.valida_scelta(
                request, scelta_account,
                email=(legacy_form.cleaned_data.get("email_notifica") or legacy_form.cleaned_data.get("email") or "").strip(),
                codice_fiscale=(request.POST.get("codice_fiscale") or "").strip(),
                attivo=bool(legacy_form.cleaned_data.get("attivo")),
            )
            for _errore in errori_account:
                messages.error(request, _errore)
        creazione_token = views_account.token_creazione(request.POST.get("creazione_token"))

        if legacy_form.is_valid() and not errori_account:
            data = legacy_form.cleaned_data
            duplicato = views_account.prenota_creazione(request, creazione_token)
            if duplicato is not None:
                return duplicato
            try:
                _nome = (data.get("nome") or "").strip()
                _cognome = (data.get("cognome") or "").strip()
                _alias = (data.get("aliasusername") or "").strip()
                if not _alias:
                    _existing_u = set(
                        AnagraficaDipendente.objects
                        .exclude(aliasusername="")
                        .exclude(aliasusername__isnull=True)
                        .values_list("aliasusername", flat=True)
                    )
                    _alias = generate_username(_nome, _cognome, _existing_u)
                row = upsert_anagrafica_dipendente(
                    aliasusername=_alias,
                    nome=_nome,
                    cognome=_cognome,
                    matricola=(data.get("matricola") or "").strip(),
                    reparto=(data.get("reparto") or "").strip(),
                    mansione=(data.get("mansione") or "").strip(),
                    ruolo=(data.get("ruolo") or "").strip(),
                    email=(data.get("email") or "").strip(),
                    email_notifica=(data.get("email_notifica") or "").strip(),
                    attivo=bool(data.get("attivo")),
                    utente_id=None,
                )
                new_id = int(row.get("id") or 0)

                # Salva anagrafica aziendale se il form è valido
                if new_id and form_aziendale.is_valid():
                    az = form_aziendale.save(commit=False)
                    az.legacy_anagrafica_id = new_id
                    az.updated_by = request.user
                    az.save()

                # Salva anagrafica civile se il form è valido
                if new_id and form_civile.is_valid():
                    civ = form_civile.save(commit=False)
                    civ.legacy_anagrafica_id = new_id
                    civ.updated_by = request.user
                    civ.save()
                    # Figli a carico: salva il formset e allinea il flag ai record registrati
                    if formset_figli.is_valid():
                        formset_figli.instance = civ
                        formset_figli.save()
                        ha_figli = civ.figli.exists()
                        if civ.figli_a_carico != ha_figli:
                            civ.figli_a_carico = ha_figli
                            civ.save(update_fields=["figli_a_carico"])

                # Reparto effettivo: sincronizza area aziendale e caporeparto dal catalogo.
                # L'area aziendale scelta nel form (accanto al reparto) è validata dal
                # service (deve appartenere al reparto) o azzerata.
                if new_id:
                    _area_az_raw = (request.POST.get("area_aziendale") or "").strip()
                    _area_az_id = int(_area_az_raw) if _area_az_raw.isdigit() else None
                    _sync_aziendale_from_reparto(
                        new_id, (data.get("reparto") or "").strip(),
                        area_aziendale_id=_area_az_id, saved_by=request.user,
                    )

                # Account portale: scelta esplicita dello step «Account portale», rivalidata dal
                # service (UPN/email esatti, allowlist AD, account privilegiati solo con conferma di
                # un superuser, audit). Nessun collegamento per alias né password prevedibili.
                if new_id:
                    try:
                        _livello, _testo = account_portale.applica_scelta(
                            request, new_id, scelta_account,
                            nome_completo=naming.nome_completo(data.get("nome"), data.get("cognome")),
                        )
                        getattr(messages, _livello)(request, _testo)
                    except Exception:
                        logger.warning("Account portale non applicato per dipendente %s", new_id, exc_info=True)
                        messages.warning(request, "Account portale non collegato per un errore: collegalo dal riquadro «Account portale» della scheda del dipendente.")

                # Assegna ruoli operativi scelti nel form (multiselect "ruoli_operativi_ids")
                if new_id:
                    ruoli_raw = request.POST.getlist("ruoli_operativi_ids")
                    ruoli_ids: list[int] = []
                    for raw in ruoli_raw:
                        try:
                            ruoli_ids.append(int(raw))
                        except (TypeError, ValueError):
                            continue
                    if ruoli_ids:
                        ruoli_validi = list(
                            RuoloOperativo.objects.filter(pk__in=ruoli_ids, is_active=True)
                        )
                        for ruolo in ruoli_validi:
                            DipendenteRuoloOperativo.objects.get_or_create(
                                legacy_anagrafica_id=new_id,
                                ruolo=ruolo,
                                defaults={"assegnato_da": request.user},
                            )

                # DPI consegnati all'ingresso (proposti dalla mansione e confermati da HR)
                if new_id:
                    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=new_id).first()
                    aziendale_obj = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=new_id).first()
                    righe_iniziali = _parse_dpi_iniziali_post(request.POST)
                    if righe_iniziali:
                        consegne = crea_consegne_iniziali(
                            civile_obj, aziendale_obj, righe_iniziali, request.user
                        )
                        if consegne:
                            archivia_pdf_cumulativo(consegne, request.user)
                            try:
                                from core.audit import log_action
                                log_action(
                                    request, "DPI_CONSEGNA_INGRESSO", "anagrafica",
                                    f"Consegna iniziale DPI a #{new_id}: {len(consegne)} articoli",
                                )
                            except Exception:
                                logger.warning("Audit DPI_CONSEGNA_INGRESSO fallito", exc_info=True)

                # Crea primo StoricoContratto se la sezione contratto è stata compilata
                if new_id:
                    from datetime import date as _date
                    data_inizio_raw = (request.POST.get("contratto_data_inizio") or "").strip()
                    if data_inizio_raw:
                        try:
                            data_inizio = _date.fromisoformat(data_inizio_raw)
                        except ValueError:
                            data_inizio = None
                        if data_inizio:
                            data_fine_raw = (request.POST.get("contratto_data_fine") or "").strip()
                            data_fine = None
                            if data_fine_raw:
                                try:
                                    data_fine = _date.fromisoformat(data_fine_raw)
                                except ValueError:
                                    data_fine = None
                            tip_id = request.POST.get("contratto_tipologia_id") or ""
                            tipologia_codice = ""
                            if tip_id.isdigit():
                                tip = TipologiaContratto.objects.filter(pk=int(tip_id)).first()
                                if tip:
                                    tipologia_codice = tip.codice
                            cod_lvl = (request.POST.get("contratto_codice_livello") or "").strip().upper()[:10]
                            descr_lvl = ""
                            if cod_lvl:
                                lvl = LivelloContrattuale.objects.filter(codice=cod_lvl).first()
                                if lvl:
                                    descr_lvl = lvl.descrizione
                            tax_code = (request.POST.get("codice_fiscale") or "").upper().strip()[:16]
                            StoricoContratto.objects.create(
                                legacy_anagrafica_id=new_id,
                                tax_code=tax_code,
                                data_inizio=data_inizio,
                                data_fine=data_fine,
                                tipologia_contratto=tipologia_codice,
                                codice_livello=cod_lvl,
                                descrizione_livello=descr_lvl,
                                ccnl=(request.POST.get("contratto_ccnl") or "").strip()[:100],
                                qualifica_nome=(request.POST.get("contratto_qualifica_nome") or "").strip()[:150],
                                importato_da=request.user,
                            )

                # Onboarding strutturato: avvio opzionale della pratica + checklist
                if new_id and request.POST.get("avvia_onboarding"):
                    try:
                        nome_onb = naming.nome_completo(data.get("nome"), data.get("cognome"))
                        ruoli_onb = list(
                            DipendenteRuoloOperativo.objects
                            .filter(legacy_anagrafica_id=new_id)
                            .values_list("ruolo_id", flat=True)
                        )
                        data_ass = None
                        _ass_raw = (request.POST.get("contratto_data_inizio") or "").strip()
                        if _ass_raw:
                            try:
                                from datetime import date as _date2
                                data_ass = _date2.fromisoformat(_ass_raw)
                            except ValueError:
                                data_ass = None
                        onboarding_service.avvia_onboarding(
                            legacy_id=new_id,
                            dipendente_nome=nome_onb or f"#{new_id}",
                            reparto=(data.get("reparto") or "").strip(),
                            mansione=(data.get("mansione") or "").strip(),
                            data_assunzione=data_ass,
                            user=request.user,
                            ruolo_ids=ruoli_onb,
                        )
                    except Exception:
                        logger.warning("Avvio onboarding automatico fallito per dipendente %s", new_id, exc_info=True)

                # Formazione sicurezza pregressa dichiarata in preinserimento
                if new_id:
                    try:
                        fsic_items: list[dict] = []
                        for cid in request.POST.getlist("fsic_corso"):
                            if not str(cid).isdigit():
                                continue
                            raw = (request.POST.get(f"fsic_data_{cid}") or "").strip()
                            if not raw:
                                continue
                            try:
                                from datetime import date as _date3
                                fsic_items.append({"corso_id": int(cid), "data": _date3.fromisoformat(raw)})
                            except ValueError:
                                continue
                        if fsic_items:
                            n_fsic = onboarding_service.registra_formazione_pregressa(
                                new_id, fsic_items, user=request.user
                            )
                            if n_fsic:
                                messages.info(request, f"Registrati {n_fsic} corsi di formazione pregressa.")
                    except Exception:
                        logger.warning("Registrazione formazione pregressa fallita per %s", new_id, exc_info=True)

                # Avviso all'IT (email / notifica in-app / ticket, se configurati): parte dopo il
                # commit ed è fail-soft. Logica in services.avviso_it_ingresso.
                if new_id:
                    avviso_it_ingresso.programma_avviso(request, new_id, scelta_tipo=scelta_account.tipo)

                views_account.completa_creazione(request, creazione_token, new_id)
                nome_disp = naming.nome_completo(data.get("nome"), data.get("cognome")) or "Dipendente"
                messages.success(request, f'Dipendente "{nome_disp}" creato.')
                if new_id:
                    return redirect("anagrafica:dipendente_detail", legacy_id=new_id)
                return redirect("anagrafica:dipendenti_list")
            except Exception as exc:
                views_account.annulla_creazione(request, creazione_token)
                logger.exception("Errore creazione dipendente")
                messages.error(request, f"Impossibile creare il dipendente: {exc}")
        elif not errori_account:
            messages.error(request, "Controlla i campi obbligatori nella sezione Dati account.")
    else:
        legacy_form = DipendenteLegacyForm(initial={"attivo": True})
        form_civile = AnagraficaCivileForm()
        form_aziendale = AnagraficaAziendaleForm()
        formset_figli = FiglioACaricoFormSet(prefix="figli")
        creazione_token = views_account.token_creazione("")
        scelta_account = account_portale.SceltaAccount()

    reparti_catalogo = list(
        Reparto.objects.filter(is_active=True).order_by("nome")
    )
    # Corsi di sicurezza per la dichiarazione "formazione pregressa" in preinserimento.
    from ..models_formazione import TrainingCourse
    formazione_sicurezza_corsi = list(
        TrainingCourse.objects
        .filter(is_active=True, stato="ATTIVO", obbligatorio=True)
        .order_by("titolo")
    )
    return render(request, "anagrafica/pages/dipendente_create.html", {
        "legacy_form": legacy_form,
        "form_civile": form_civile,
        "form_aziendale": form_aziendale,
        "formset_figli": formset_figli,
        "can_hr": can_hr,
        "mansioni_catalogo": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "reparti_catalogo": reparti_catalogo,
        "contratto_choices": DipendenteAnagraficaAziendale.CONTRATTO_CHOICES,
        "tipologie_contratto": list(TipologiaContratto.objects.filter(is_active=True).order_by("ordine", "codice")),
        "livelli_contrattuali": list(LivelloContrattuale.objects.filter(is_active=True).order_by("ordine", "codice")),
        "ruoli_operativi_catalogo": list(RuoloOperativo.objects.filter(is_active=True).order_by("nome")),
        "formazione_sicurezza_corsi": formazione_sicurezza_corsi,
        "creazione_token": creazione_token,
        "step_iniziale": 3 if (request.method == "POST" and errori_account) else 1,
        "scelta_account": scelta_account,
        "account_scelte": account_portale.SCELTE,
        "puo_confermare_privilegiati": bool(getattr(request.user, "is_superuser", False)),
    })


def _parse_dpi_iniziali_post(post) -> list[RigaConsegnaIniziale]:
    """Estrae le righe DPI iniziali confermate (checkbox 'consegnato') dal POST.

    Convenzioni di name dei campi (per indice intero ``i``):
      - ``dpi_consegnato_<i>`` checkbox (presenza = riga selezionata)
      - ``dpi_categoria_id_<i>`` int obbligatorio
      - ``dpi_modello_id_<i>`` int opzionale
      - ``dpi_taglia_id_<i>`` int opzionale
      - ``dpi_quantita_<i>`` int (default 1)

    Gli indici disponibili sono enumerati dal campo nascosto ``dpi_indici``
    (CSV) inviato dal partial HTMX.
    """
    righe: list[RigaConsegnaIniziale] = []
    indici_raw = post.get("dpi_indici", "").strip()
    if not indici_raw:
        return righe
    for token in indici_raw.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        i = int(token)
        if not post.get(f"dpi_consegnato_{i}"):
            continue
        cat_raw = post.get(f"dpi_categoria_id_{i}", "").strip()
        if not cat_raw.isdigit():
            continue
        try:
            quantita = int(post.get(f"dpi_quantita_{i}", "1") or 1)
        except ValueError:
            quantita = 1
        def _int_or_none(value: str) -> int | None:
            value = (value or "").strip()
            return int(value) if value.isdigit() else None

        righe.append(RigaConsegnaIniziale(
            categoria_id=int(cat_raw),
            quantita=max(1, quantita),
            tipo_id=_int_or_none(post.get(f"dpi_tipo_id_{i}", "")),
            modello_id=_int_or_none(post.get(f"dpi_modello_id_{i}", "")),
            taglia_id=_int_or_none(post.get(f"dpi_taglia_id_{i}", "")),
        ))
    return righe


def _puo(request, modulo: str, azione: str, oggetto=None) -> bool:
    from core.permessi import puo_fare

    return puo_fare(request, modulo, azione, oggetto)


def _schede_visibili(request, modulo: str = "anagrafica", azione: str = "vedere") -> set[int] | None:
    """Ruoli attivi: id anagrafica delle schede visibili. None = tutte."""
    from core.permessi import utenti_visibili
    from core.permessi.identita import anagrafiche_di_utenti

    ammessi = utenti_visibili(request, modulo, azione)
    return None if ammessi is None else anagrafiche_di_utenti(ammessi)


def _can_view_stats(request) -> bool:
    """Verifica se l'utente corrente può visualizzare la sezione statistiche."""
    if request.user.is_superuser:
        return True
    if _helpers._ruoli_attivi():
        return _puo(request, "anagrafica", "vedere")
    perm = AnagraficaStatPermission.get_instance()
    if perm.accesso == AnagraficaStatPermission.ACCESSO_TUTTI:
        return True
    legacy_user = get_legacy_user(request.user)
    if _helpers._user_in_utente_allowlist(legacy_user, perm):
        return True
    if is_legacy_admin(legacy_user):
        return True
    # ACL v2 canonico: governabile da /admin-portale/acl-canonico/ (additivo).
    if _helpers._has_canonical_grant(request, PERM_STATISTICHE_VIEW, legacy_user=legacy_user):
        return True
    if perm.accesso == AnagraficaStatPermission.ACCESSO_ADMIN:
        return False
    # ACCESSO_RUOLI: controlla se il ruolo dell'utente è nella lista
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _compute_widget_counts(dip: dict) -> dict[str, int]:
    """Calcola i contatori per ogni widget statistiche del dipendente."""
    legacy_id = int(dip.get("id") or 0)
    nome = str(dip.get("nome") or "").strip()
    cognome = str(dip.get("cognome") or "").strip()
    nome_completo = f"{nome} {cognome}".strip()
    counts: dict[str, int] = {w["id"]: 0 for w in _helpers.STAT_WIDGETS}

    # Ticket aperti e totali
    try:
        from tickets.models import StatoTicket, Ticket
        qs = Ticket.objects.filter(richiedente_legacy_user_id=legacy_id) if legacy_id else Ticket.objects.none()
        counts["tickets_totali"] = qs.count()
        counts["tickets_aperti"] = qs.filter(stato=StatoTicket.APERTA).count()
    except Exception:
        logger.exception("Errore conteggio ticket per dipendente %s", legacy_id)

    # Anomalie (legacy SQL Server — solo se connesso)
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            # Cerca per nome in capo_commessa (campo testo con nome)
            cur.execute(
                "SELECT COUNT(*) FROM anomalie WHERE UPPER(COALESCE(capo_commessa,'')) LIKE UPPER(%s)",
                [f"%{nome_completo}%"],
            )
            row = cur.fetchone()
            counts["anomalie"] = int(row[0]) if row else 0
    except Exception:
        logger.debug("Impossibile contare anomalie per dipendente %s (tabella legacy assente in dev)", legacy_id)

    # Diario preposto
    try:
        from diario_preposto.models import SegnalazionePreposto
        counts["diario_preposto"] = SegnalazionePreposto.objects.filter(
            Q(chi_segnala__icontains=nome_completo) | Q(preposto__icontains=nome_completo)
        ).count()
    except Exception:
        logger.exception("Errore conteggio diario preposto per dipendente %s", legacy_id)

    # Rilevazioni sicurezza
    try:
        from rilevazione_incidenti.models import RilevazioneIncidente
        counts["rilevazioni"] = RilevazioneIncidente.objects.filter(
            nominativo__icontains=nome_completo
        ).count()
    except Exception:
        logger.exception("Errore conteggio rilevazioni per dipendente %s", legacy_id)

    # Assenze (legacy SQL Server)
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM assenze WHERE UPPER(COALESCE(copia_nome,'')) LIKE UPPER(%s)",
                [f"%{nome_completo}%"],
            )
            row = cur.fetchone()
            counts["assenze"] = int(row[0]) if row else 0
    except Exception:
        logger.debug("Impossibile contare assenze per dipendente %s (tabella legacy assente in dev)", legacy_id)

    # Timbri
    try:
        from timbri.models import OperatoreTimbri, RegistroTimbro
        operatore = OperatoreTimbri.objects.filter(legacy_anagrafica_id=legacy_id).first()
        if operatore:
            counts["timbri"] = RegistroTimbro.objects.filter(operatore=operatore).count()
    except Exception:
        logger.exception("Errore conteggio timbri per dipendente %s", legacy_id)

    # DPI richiesti
    try:
        from dpi.models import RichiestaDPI
        counts["dpi"] = RichiestaDPI.objects.filter(richiedente_legacy_id=legacy_id).count() if legacy_id else 0
    except Exception:
        logger.exception("Errore conteggio DPI per dipendente %s", legacy_id)

    return counts


# ---------------------------------------------------------------------------
# Scheda dettaglio dipendente — helper assenze
# ---------------------------------------------------------------------------

def _query_assenze_dipendente(dip: dict) -> tuple[list[dict], bool]:
    """Read-only: assenze del dipendente (anno corrente + precedente).

    Match robusto, allineato al widget conteggio (`_compute_widget_counts`) e al
    modulo assenze (`assenze.views._load_events`):
    - `copia_nome` LIKE nome (ordini "Nome Cognome" e "Cognome Nome");
    - `utente_id` diretto su `assenze`, se la colonna esiste;
    - JOIN `dipendenti` via `dipendente_id`, solo se la colonna esiste.

    La sola JOIN su `assenze.dipendente_id` era fragile: quella colonna può
    mancare in prod (referenziarla mandava in errore l'intera query → 42S22 →
    catch → lista vuota) o restare NULL (INNER JOIN senza match), per cui il tab
    mostrava sempre "nessuna assenza" mentre il widget conteggio — che filtra per
    `copia_nome` — ne riportava di presenti.

    Ritorna `(lista, no_link)` dove `no_link` indica che il dipendente non è
    identificabile (né nome né utente_id). Chiavi dict: data_inizio, data_fine,
    tipo_assenza, moderation_status.
    """
    import datetime as _dt
    from django.utils import timezone as _tz

    nome = str(dip.get("nome") or "").strip()
    cognome = str(dip.get("cognome") or "").strip()
    utente_id = int(dip.get("utente_id") or 0) or None
    nome_cognome = f"{nome} {cognome}".strip()
    cognome_nome = f"{cognome} {nome}".strip()

    if not nome_cognome and not utente_id:
        return [], True

    assenze_cols = legacy_table_columns("assenze")
    if not assenze_cols:
        # Tabella legacy non disponibile (es. dev senza SQL Server): non è un
        # problema di linking, semplicemente non ci sono dati da mostrare.
        return [], False

    or_clauses: list[str] = []
    params: list = []

    if "copia_nome" in assenze_cols and nome_cognome:
        or_clauses.append("UPPER(COALESCE(a.copia_nome,'')) LIKE UPPER(%s)")
        params.append(f"%{nome_cognome}%")
        if cognome_nome != nome_cognome:
            or_clauses.append("UPPER(COALESCE(a.copia_nome,'')) LIKE UPPER(%s)")
            params.append(f"%{cognome_nome}%")

    if utente_id and "utente_id" in assenze_cols:
        or_clauses.append("a.utente_id = %s")
        params.append(utente_id)

    join = ""
    if utente_id and "dipendente_id" in assenze_cols and legacy_table_columns("dipendenti"):
        join = " LEFT JOIN dipendenti d ON d.id = a.dipendente_id "
        or_clauses.append("d.utente_id = %s")
        params.append(utente_id)

    if not or_clauses:
        return [], False

    data_da = _dt.date(_tz.localdate().year - 1, 1, 1)
    where = "(" + " OR ".join(or_clauses) + ") AND a.data_inizio >= %s"
    params.append(data_da)
    sql = f"""
        SELECT a.data_inizio, a.data_fine, a.tipo_assenza, a.moderation_status
        FROM assenze a
        {join}
        WHERE {where}
        ORDER BY a.data_inizio DESC
    """
    try:
        with connections["default"].cursor() as cur:
            cur.execute(sql, params)
            cols = [str(c[0]) for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()], False
    except Exception:
        logger.warning("_query_assenze_dipendente: query assenze fallita (dip_id=%s)", dip.get("id"))
        return [], False


def _assenza_tipo_meta(tipo) -> tuple[str, str]:
    """Ritorna ``(icona, accent)`` per un tipo di assenza, match per keyword.

    ``accent`` ∈ {ferie, malattia, permesso, congedo, altro} → mappa sulle
    classi CSS ``dp-abs-*`` usate dalla scheda dipendente (card riepilogo e
    chip della tabella storico). Tollerante a stringhe legacy eterogenee.
    """
    t = str(tipo or "").lower()
    if "feri" in t:
        return "🏖️", "ferie"
    if "malatt" in t or "infort" in t or "donaz" in t or "sangue" in t:
        return "🩺", "malattia"
    if "matern" in t or "patern" in t or "conged" in t or "allatt" in t or "104" in t:
        return "👶", "congedo"
    if "festiv" in t:
        return "🎉", "permesso"
    if "rol" in t or "permess" in t or "recuper" in t:
        return "⏱️", "permesso"
    if "sciop" in t:
        return "✊", "altro"
    return "🗓️", "altro"


# Nomi mese indicizzabili per numero (1-12). NB: più sotto nel modulo esiste un
# altro globale `_MESI_IT` (dict nome→numero, usato dall'import cedolini) che,
# essendo definito dopo, sovrascriverebbe questa tupla a livello di modulo: per
# questo qui il nome è distinto (`_MESI_IT_NOMI`) ed evitiamo la collisione.
_MESI_IT_NOMI = (
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
)


def _assenze_cronologia(assenze_list: list[dict]) -> list[dict]:
    """Raggruppa le assenze (già ordinate per data_inizio DESC) in Anno → Mese.

    Ritorna ``[{anno, totale, mesi: [{mese_label, items: [...]}]}]``. Si appoggia
    all'ordinamento decrescente della query (anni e mesi contigui) per costruire
    i bucket in un solo passaggio, senza riordinare. Nomi mese in italiano via
    ``_MESI_IT_NOMI`` per non dipendere dal locale dei template.
    """
    crono: list[dict] = []
    for _a in assenze_list:
        _d_i = _a.get("data_inizio")
        if not _d_i:
            continue
        _y, _m = _d_i.year, _d_i.month
        if not crono or crono[-1]["anno"] != _y:
            crono.append({"anno": _y, "totale": 0, "mesi": []})
        anno = crono[-1]
        anno["totale"] += 1
        if not anno["mesi"] or anno["mesi"][-1]["mese_num"] != _m:
            _label = _MESI_IT_NOMI[_m] if 1 <= _m <= 12 else ""
            anno["mesi"].append({"mese_num": _m, "mese_label": _label, "items": []})
        anno["mesi"][-1]["items"].append(_a)
    return crono


def _assenze_kpi_annuali(assenze_list: list[dict]) -> list[dict]:
    """1.11 — Conteggio richieste assenza per anno × tipologia.

    A differenza di ``assenze_summary_anno`` (che somma i *giorni* dell'anno
    corrente delle sole approvate), qui si conta il **numero di richieste** per
    tipologia su ciascun anno presente in ``assenze_list`` (anno corrente +
    precedente, tutte le moderazioni). Ritorna
    ``[{anno, totale, tipi: [{tipo, conteggio, icona, accent}]}]`` con anni in
    ordine decrescente e tipologie ordinate per conteggio desc.
    """
    per_anno: dict[int, dict[str, int]] = {}
    for _a in assenze_list:
        _d_i = _a.get("data_inizio")
        if not _d_i:
            continue
        try:
            _year = _d_i.year if hasattr(_d_i, "year") else int(str(_d_i)[:4])
        except (TypeError, ValueError):
            continue
        _tipo = str(_a.get("tipo_assenza") or "Altro").strip() or "Altro"
        per_anno.setdefault(_year, {})
        per_anno[_year][_tipo] = per_anno[_year].get(_tipo, 0) + 1

    kpi: list[dict] = []
    for _year in sorted(per_anno, reverse=True):
        tipi: list[dict] = []
        for _tipo, _n in sorted(per_anno[_year].items(), key=lambda kv: kv[1], reverse=True):
            _ic, _acc = _assenza_tipo_meta(_tipo)
            tipi.append({"tipo": _tipo, "conteggio": _n, "icona": _ic, "accent": _acc})
        kpi.append({"anno": _year, "totale": sum(per_anno[_year].values()), "tipi": tipi})
    return kpi


# ---------------------------------------------------------------------------
# Scheda dettaglio dipendente
# ---------------------------------------------------------------------------

def _mansioni_da_rivedere_ctx(request, legacy_id: int, is_admin: bool) -> dict:
    """Mansioni lavorative che non tornano più con reparto e ruoli di oggi (card Spostamenti)."""
    if not is_admin:
        return {"mansioni_da_rivedere": []}
    try:
        from ..services.mansionario_struttura import da_rivedere_dopo_spostamento
        from ..views_mansionario import _puo_valutare

        return {
            "mansioni_da_rivedere": da_rivedere_dopo_spostamento(legacy_id),
            "puo_togliere_mansioni": _puo_valutare(request),
        }
    except Exception:
        logger.warning("mansioni da rivedere non calcolate per %s", legacy_id, exc_info=True)
        return {"mansioni_da_rivedere": []}


def _posizione_struttura_ctx(request, legacy_id: int, is_admin: bool) -> dict:
    """Scheda «Ruolo e competenze»: ruoli, area, processi, mansioni e proposte da assegnare.

    La vede chi vede il Mansionario (amministrazione anagrafica o HR) e chi
    valuta (gestore skill matrix); gli accessi al portale solo l'amministrazione."""
    from ..views_mansionario import _puo_valutare, _puo_vedere

    puo_valutare = _puo_valutare(request)
    if not (is_admin or _puo_vedere(request) or puo_valutare):
        return {"posizione": None}
    try:
        from ..services.struttura_persona import posizione

        ctx = {"posizione": posizione(legacy_id), "puo_assegnare_mansioni": puo_valutare}
        if is_admin:
            from core.permessi.variazioni import ultime_variazioni

            ctx["variazioni_accessi"] = ultime_variazioni(legacy_id)
        return ctx
    except Exception:
        logger.warning("posizione nella struttura non calcolata per %s", legacy_id, exc_info=True)
        return {"posizione": None}


@login_required
def dipendente_detail(request, legacy_id: int):
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    if _helpers._ruoli_attivi() and not _puo(request, "anagrafica", "vedere", dip):
        from core.permessi.negato import risposta_negata

        return risposta_negata(
            request,
            "Questa scheda non rientra fra quelle che il tuo ruolo ti consente di vedere.",
            pagina="Anagrafica dipendenti",
        )

    can_stats = _can_view_stats(request)
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    can_hr = _helpers._check_hr_permission(request)
    from core.audit import log_consultazione

    log_consultazione(request, "DIPENDENTE_SCHEDA_VISUALIZZATA", "anagrafica",
                      {"dipendente_id": legacy_id, "dati_hr": bool(can_hr or is_admin)},
                      chiave=f"dipendente:{legacy_id}", oggetto_tipo="dipendente", oggetto_id=str(legacy_id))

    # Anagrafica civile e aziendale estese
    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    aziendale = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    civile_foto_url = _foto_dipendente_url(civile, legacy_id)
    form_civile = AnagraficaCivileForm(instance=civile) if is_admin else None
    form_aziendale = AnagraficaAziendaleForm(instance=aziendale) if is_admin else None
    formset_figli = FiglioACaricoFormSet(instance=civile, prefix="figli") if is_admin else None
    figli_list = list(civile.figli.all()) if civile else []

    # Widget layout viewer
    layout_obj = DipendenteStatLayout.objects.filter(viewer_user_id=request.user.id).first()
    hidden_ids: list[str] = list(layout_obj.hidden) if layout_obj else []
    order_ids: list[str] = list(layout_obj.order) if layout_obj else []

    # Costruisce lista widget ordinata
    all_widget_ids = [w["id"] for w in _helpers.STAT_WIDGETS]
    if order_ids:
        ordered = [wid for wid in order_ids if wid in all_widget_ids]
        ordered += [wid for wid in all_widget_ids if wid not in ordered]
    else:
        ordered = all_widget_ids[:]

    # Contatori
    widget_counts: dict[str, int] = {}
    if can_stats:
        widget_counts = _compute_widget_counts(dip)

    # Costruisce URL filtrati per dipendente
    from urllib.parse import urlencode
    from django.urls import reverse as _reverse

    _nome = str(dip.get("nome") or "").strip()
    _cognome = str(dip.get("cognome") or "").strip()
    _nome_completo = naming.nome_completo(_nome, _cognome)
    _alias = str(dip.get("aliasusername") or "").strip()

    def _qs(**params):
        return "?" + urlencode(params) if params else ""

    try:
        _ticket_base = _reverse("tickets:gestione_list")
    except Exception:
        _ticket_base = "/tickets/gestione/"
    try:
        _diario_base = _reverse("diario_preposto:lista")
    except Exception:
        _diario_base = "/diario-preposto/"
    try:
        _rilevazioni_base = _reverse("rilevazione_incidenti:lista")
    except Exception:
        _rilevazioni_base = "/rilevazione-incidenti/"
    try:
        _timbri_base = _reverse("timbri:operatore_detail_by_legacy", args=[legacy_id])
    except Exception:
        _timbri_base = ""

    _widget_links: dict[str, str] = {
        "tickets_aperti": _ticket_base + _qs(q=_nome_completo, stato="APERTA"),
        "tickets_totali": _ticket_base + _qs(q=_nome_completo),
        "anomalie": "/gestione-anomalie/",
        "diario_preposto": _diario_base + _qs(q=_nome_completo),
        "rilevazioni": _rilevazioni_base + _qs(q=_nome_completo),
        "assenze": "/assenze/",
        "timbri": _timbri_base,
        "dpi": "/dpi/gestione/" + _qs(q=_nome_completo),
    }

    # Costruisce lista widget con dati
    widget_map = {w["id"]: w for w in _helpers.STAT_WIDGETS}
    widgets_visible = []
    widgets_hidden = []
    for wid in ordered:
        w = dict(widget_map[wid])
        w["count"] = widget_counts.get(wid, 0)
        if wid in _widget_links:
            w["link_url"] = _widget_links[wid]
        if wid in hidden_ids:
            widgets_hidden.append(w)
        else:
            widgets_visible.append(w)

    # Ruoli operativi
    ruoli_assegnati = list(
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=legacy_id)
        .select_related("ruolo", "ruolo__ambito", "assegnato_da")
        .order_by("ruolo__nome")
    )
    ruoli_disponibili = (
        RuoloOperativo.objects.filter(is_active=True)
        .select_related("ambito")
        .exclude(id__in=[a.ruolo_id for a in ruoli_assegnati])
    )
    # Una persona può avere più ruoli: quello scritto nel campo «Ruolo aziendale»
    # è il principale, e va riconosciuto a colpo d'occhio tra i badge.
    _principale = (aziendale.ruolo_aziendale or "").strip().casefold() if aziendale else ""
    for _a in ruoli_assegnati:
        _a.is_principale = bool(_principale) and _a.ruolo.nome.strip().casefold() == _principale
    # I ruoli si leggono per ambito: produttivo, esecutivo, ISO 45001, ISO 27001…
    # Sono ruoli che convivono, e affiancarli senza distinguerli farebbe sembrare
    # un elenco di alternative quello che è un cumulo di incarichi.
    ruoli_per_ambito = _raggruppa_per_ambito(
        ruoli_assegnati, chiave=lambda a: a.ruolo.ambito
    )
    ruoli_disponibili_per_ambito = _raggruppa_per_ambito(
        list(ruoli_disponibili), chiave=lambda r: r.ambito
    )

    # Mansioni catalogo
    mansioni_catalogo = list(Mansione.objects.filter(is_active=True).order_by("nome"))

    # Qualifiche dipendente
    from django.utils import timezone as tz
    from datetime import timedelta
    oggi = tz.localdate()
    qualifiche_dip = list(
        DipendenteQualifica.objects.filter(legacy_anagrafica_id=legacy_id)
        .select_related("tipo", "record_formazione", "record_formazione__corso", "sessione")
        .prefetch_related("storico", "tipo__corsi")
        .order_by("data_scadenza", "tipo__nome")
    )
    tipi_qualifica = list(TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome"))

    # DPI dipendente
    dpi_consegnati = []
    dpi_richieste = []
    try:
        from dpi.models import RichiestaDPI
        dpi_richieste = list(
            RichiestaDPI.objects.filter(richiedente_legacy_id=legacy_id)
            .select_related("categoria", "consegna")
            .order_by("-created_at")[:20]
        )
        dpi_consegnati = [
            r for r in dpi_richieste
            if r.stato == "CONSEGNATA" and hasattr(r, "consegna") and r.consegna.is_attiva
        ]
    except Exception:
        logger.exception("Errore caricamento DPI per dipendente %s", legacy_id)

    # PDF consegne DPI archiviati: mappa consegna_id -> documento per linkare dal tab
    dpi_consegna_doc_map: dict[int, int] = {}
    try:
        dpi_docs = DocumentoDipendente.objects.filter(
            legacy_anagrafica_id=legacy_id,
            tipo=DocumentoDipendente.Tipo.DPI_CONSEGNA,
            oggetto_riferimento_tipo="dpi.consegna",
        ).values_list("oggetto_riferimento_id", "id")
        dpi_consegna_doc_map = {int(c): int(d) for c, d in dpi_docs if c is not None}
    except Exception:
        logger.exception("Errore caricamento documenti DPI per dipendente %s", legacy_id)

    # Visite mediche (dato sanitario sensibile: gating su _can_view_visite_mediche)
    can_view_visite = _helpers._can_view_visite_mediche(request)
    visite_stato_list: list = []
    visite_storico_list: list = []
    tipi_visita_attivi: list = []
    if can_view_visite:
        try:
            visite_stato_list = stato_visite(legacy_id)
            visite_storico_list = visite_storico(legacy_id)
            tipi_visita_attivi = list(
                TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")
            )
        except Exception:
            logger.exception("Errore caricamento visite mediche per dipendente %s", legacy_id)

    # Documenti dipendente (spazio privato): riga in tab "Documenti"
    documenti_dipendente = []
    cartelle_documenti = []
    try:
        qs_doc = DocumentoDipendente.objects.filter(legacy_anagrafica_id=legacy_id).select_related("cartella")
        # Nasconde i referti sanitari a chi non ha il permesso visite (e, con i ruoli
        # attivi, a chi vede l'idoneita' ma non i referti clinici)
        if not can_view_visite or not _helpers._can_view_referti(request):
            qs_doc = qs_doc.exclude(tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO)
        # Cartelle riservate (solo_admin): solo a chi ha il permesso documenti riservati.
        if not _helpers._can_view_documenti_riservati(request):
            qs_doc = qs_doc.exclude(cartella__solo_admin=True)
        documenti_dipendente = list(qs_doc.order_by("-created_at")[:100])
        # Scheletro cartelle: solo quelle applicabili al dipendente (targeting per
        # reparto/ruoli operativi; cartella senza targeting = universale).
        from ..models import DipendenteAnagraficaAziendale as _Az, DipendenteRuoloOperativo as _RO
        _area_nome = (_Az.objects.filter(legacy_anagrafica_id=legacy_id).values_list("area", flat=True).first() or "")
        _ruoli_ids = set(_RO.objects.filter(legacy_anagrafica_id=legacy_id).values_list("ruolo_id", flat=True))
        cartelle_documenti = [
            c for c in CartellaDocumentoDipendente.objects
            .filter(attiva=True).prefetch_related("reparti", "ruoli_operativi").order_by("ordine", "nome")
            if c.si_applica(_area_nome, _ruoli_ids)
        ]
    except Exception:
        logger.exception("Errore caricamento documenti per dipendente %s", legacy_id)

    software_licenses = []
    try:
        from assets.models import SoftwareLicense

        legacy_user_id = int(dip.get("utente_id") or 0)
        license_qs = SoftwareLicense.objects.filter(
            Q(assigned_anagrafica_id=legacy_id)
            | (Q(assigned_legacy_user_id=legacy_user_id) if legacy_user_id else Q())
        ).select_related("asset").order_by("category", "vendor", "product_name", "id")
        software_licenses = list(license_qs)
    except Exception:
        logger.exception("Errore caricamento licenze software per dipendente %s", legacy_id)

    # Asset assegnati al dipendente e asset del reparto (se caporeparto)
    assets_assegnati: list = []
    assets_reparto: list = []
    reparti_capo: list = []
    try:
        from assets.models import Asset
        from core.models import RepartoCapoMapping

        utente_id_asset = int(dip.get("utente_id") or 0)
        if utente_id_asset:
            assets_assegnati = list(
                Asset.objects.filter(assigned_legacy_user_id=utente_id_asset)
                .exclude(status=Asset.STATUS_RETIRED)
                .select_related("asset_category")
                .order_by("name")
            )

        # Verifica se è caporeparto: cerca RepartoCapoMapping dove caporeparto
        # corrisponde a email, id numerico o nome dell'utente legacy
        capo_user = UtenteLegacy.objects.filter(id=utente_id_asset).first() if utente_id_asset else None
        if capo_user:
            capo_email = str(getattr(capo_user, "email", "") or "").strip().lower()
            capo_nome = str(getattr(capo_user, "nome", "") or "").strip()
            capo_filters = Q(caporeparto=str(utente_id_asset))
            if capo_email:
                capo_filters |= Q(caporeparto__iexact=capo_email)
            if capo_nome:
                capo_filters |= Q(caporeparto__iexact=capo_nome)
            reparti_capo = list(
                RepartoCapoMapping.objects.filter(capo_filters, is_active=True)
                .values_list("reparto", flat=True)
                .distinct()
            )
            if reparti_capo:
                assets_reparto = list(
                    Asset.objects.filter(assignment_reparto__in=reparti_capo)
                    .exclude(status=Asset.STATUS_RETIRED)
                    .select_related("asset_category")
                    .order_by("assignment_reparto", "name")
                )
    except Exception:
        logger.exception("Errore caricamento asset per dipendente %s", legacy_id)

    # Voci retributive (solo se l'utente ha accesso HR)
    retribuzioni_latest: list = []
    retribuzioni_timeline: list = []
    retribuzioni_importazione = None
    retribuzioni_data_competenza = None
    retribuzioni_has_changes = False
    if can_hr:
        _voci_q = Q(legacy_anagrafica_id=legacy_id)
        if civile and civile.codice_fiscale:
            _voci_q |= Q(tax_code=civile.codice_fiscale.strip().upper())
        voci_qs = VoceRetributiva.objects.filter(
            _voci_q
        ).select_related("importazione").order_by(
            "-data_competenza", "-importazione__data_importazione", "categoria", "pay_item_key"
        )
        voci_all = list(voci_qs)
        if voci_all:
            # Raggruppa per mese, separando CSV (solo più recente per mese) e manuali (sempre incluse).
            # Le voci manuali fanno override delle CSV con stesso pay_item_key.
            _by_month: dict = {}
            for v in voci_all:
                key = v.data_competenza
                if key not in _by_month:
                    _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
                if v.manuale:
                    _by_month[key]["manuale_voci"].append(v)
                else:
                    if _by_month[key]["csv_imp"] is None:
                        _by_month[key]["csv_imp"] = v.importazione
                    if v.importazione_id == _by_month[key]["csv_imp"].id:
                        _by_month[key]["csv_voci"].append(v)

            def _merge(entry):
                manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
                return [v for v in entry["csv_voci"] if v.pay_item_key not in manuale_keys] + entry["manuale_voci"]

            _months_desc = sorted(_by_month.keys(), reverse=True)
            if _months_desc:
                _latest_month = _months_desc[0]
                _latest_entry = _by_month[_latest_month]
                retribuzioni_data_competenza = _latest_month
                retribuzioni_importazione = _latest_entry["csv_imp"]  # può essere None se mese ha solo manuali
                retribuzioni_latest = _merge(_latest_entry)
                retribuzioni_has_changes = any(v.is_changed for v in retribuzioni_latest)
                retribuzioni_timeline = [(d, _merge(_by_month[d])) for d in _months_desc]

    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    retribuzioni_fissi = [v for v in retribuzioni_latest if v.categoria == "fisso"]
    retribuzioni_variabili = [v for v in retribuzioni_latest if v.categoria == "variabile"]
    retribuzioni_totali = sorted(
        [v for v in retribuzioni_latest if v.categoria == "totale"],
        key=lambda v: _TOTALI_SORT.get(v.pay_item_key, 99),
    )
    retribuzioni_altri = [v for v in retribuzioni_latest if v.categoria == "altro"]

    # Ratei ferie/ROL/ex-festività da cedolini (solo se l'utente ha accesso HR)
    ratei_saldi: list = []
    if can_hr:
        _ratei_q = Q(legacy_anagrafica_id=legacy_id)
        if civile and civile.codice_fiscale:
            _ratei_q |= Q(tax_code=civile.codice_fiscale.strip().upper())
        ratei_saldi = list(
            SaldoCedolino.objects.filter(_ratei_q).order_by("-data_competenza")[:1]
        )

    # Assenze (read-only, ultimi 2 anni) — match per nome/utente_id, vedi helper
    assenze_list, assenze_no_link = _query_assenze_dipendente(dip)
    _summary_map: dict[str, int] = {}
    for _a in assenze_list:
        _d_i = _a.get("data_inizio")
        _d_f = _a.get("data_fine") or _d_i
        # Durata (giorni) + icona/accent per ogni riga, per la tabella storico
        _giorni_row = None
        if _d_i:
            try:
                _giorni_row = max(1, (_d_f - _d_i).days + 1) if _d_f and _d_f != _d_i else 1
            except Exception:
                _giorni_row = None
        _a["giorni"] = _giorni_row
        _ic, _acc = _assenza_tipo_meta(_a.get("tipo_assenza"))
        _a["icona"] = _ic
        _a["accent"] = _acc
        # Riepilogo: solo anno corrente e approvate
        if not _d_i:
            continue
        try:
            _year = _d_i.year if hasattr(_d_i, "year") else int(str(_d_i)[:4])
            if _year != oggi.year:
                continue
            if int(_a.get("moderation_status") or -1) != 0:
                continue
            _tipo = str(_a.get("tipo_assenza") or "Altro").strip() or "Altro"
            _summary_map[_tipo] = _summary_map.get(_tipo, 0) + (_giorni_row or 1)
        except Exception:
            pass

    # Riepilogo come lista ordinata (giorni desc) arricchita con icona/accent + totale
    assenze_summary_anno: list[dict] = []
    assenze_tot_anno = 0
    for _tipo, _giorni in sorted(_summary_map.items(), key=lambda kv: kv[1], reverse=True):
        _ic, _acc = _assenza_tipo_meta(_tipo)
        assenze_summary_anno.append({"tipo": _tipo, "giorni": _giorni, "icona": _ic, "accent": _acc})
        assenze_tot_anno += _giorni

    # Storico come cronologia raggruppata Anno → Mese
    assenze_cronologia = _assenze_cronologia(assenze_list)

    # 1.11 — KPI annuali: conteggio richieste per anno × tipologia (tutte le moderazioni)
    assenze_kpi_annuali = _assenze_kpi_annuali(assenze_list)

    # Storico cambiamenti organizzativi (mansione, reparto, area, ruolo aziendale) — solo admin
    storico_cambiamenti: list = []
    assegnazioni: list = []
    assegnazione_in_corso = None
    assetto_attuale: dict = {}
    if is_admin:
        # Assetto vivo della persona: è il default dello spostamento e il
        # fallback delle card. Serve anche a chi non ha mai registrato uno
        # spostamento, che altrimenti vedrebbe solo un vuoto.
        _dip_labels = _helpers._dipendenti_picker_rows()
        _dip_label_map = {item["id"]: item["label"] for item in _dip_labels}
        assetto_attuale = {
            "reparto": (dip.get("reparto") or "").strip(),
            "mansione": (dip.get("mansione") or "").strip(),
            "area": (aziendale.area_aziendale.nome if (aziendale and aziendale.area_aziendale_id) else ""),
            "ruolo_aziendale": ((aziendale.ruolo_aziendale or "").strip() if aziendale else ""),
            "responsabile_label": (
                _dip_label_map.get(aziendale.caporeparto_legacy_id or 0, "") if aziendale else ""
            ),
        }

        storico_cambiamenti = list(
            DipendenteCambiamentoOrganizzativo.objects
            .filter(legacy_anagrafica_id=legacy_id)
            .select_related("created_by")
            .order_by("-data_effetto", "-created_at")[:50]
        )
        # Spostamenti organizzativi: le programmate in cima, poi a ritroso. Il
        # caporeparto si risolve dal reparto/area della singola assegnazione, non
        # da quello attuale del dipendente, altrimenti una card storica mostrerebbe
        # il responsabile di oggi.
        assegnazioni = list(
            DipendenteAssegnazione.objects
            .filter(legacy_anagrafica_id=legacy_id)
            .select_related("area_aziendale", "area_aziendale__reparto", "created_by")
            .order_by("-data_inizio", "-created_at")[:30]
        )
        # Piano di adeguamento dei cambi mansione: prima si chiudono da soli gli
        # adempimenti già soddisfatti (visita registrata, corso fatto, DPI consegnato).
        try:
            from ..models import AdempimentoCambioMansione
            from ..services.cambio_mansione import aggiorna_piani

            aggiorna_piani([legacy_id])
            _piani: dict[int, list] = {}
            for _ad in AdempimentoCambioMansione.objects.filter(assegnazione__in=[a.pk for a in assegnazioni]):
                _piani.setdefault(_ad.assegnazione_id, []).append(_ad)
        except Exception:
            logger.warning("Piani di adeguamento non leggibili per %s", legacy_id, exc_info=True)
            _piani = {}
        for _ass in assegnazioni:
            _ass.piano = _piani.get(_ass.pk, [])
            _ass.piano_aperti = sum(1 for _ad in _ass.piano if _ad.aperto)
            _ass.responsabile_label = _dip_label_map.get(
                _responsabile_di(_ass.reparto, _ass.area_aziendale) or 0, ""
            )
            if _ass.is_in_corso:
                assegnazione_in_corso = _ass
                # Card in corso: i campi che lo spostamento non ha valorizzato
                # mostrano l'assetto vivo — è quello che la persona ha davvero —
                # marcato come invariato invece che con un trattino. Le card
                # storiche restano fedeli a quanto fu registrato allora.
                _ass.reparto_display = _ass.reparto or assetto_attuale["reparto"]
                _ass.area_display = (
                    _ass.area_aziendale.nome if _ass.area_aziendale_id else assetto_attuale["area"]
                )
                _ass.mansione_display = _ass.mansione or assetto_attuale["mansione"]
                _ass.mansione_ereditata = not _ass.mansione and bool(_ass.mansione_display)
                _ass.ruolo_display = _ass.ruolo_aziendale or assetto_attuale["ruolo_aziendale"]
                _ass.ruolo_ereditato = not _ass.ruolo_aziendale and bool(_ass.ruolo_display)
                if not _ass.responsabile_label:
                    _ass.responsabile_label = assetto_attuale["responsabile_label"]

    # Storico contrattuale
    storico_contratti: list = []
    tipologie_contratto: list = []
    livelli_catalogo: list = []
    livelli_json: str = "{}"
    tipi_qualifica_prof: list = []
    if can_hr:
        _contr_q = Q(legacy_anagrafica_id=legacy_id)
        tax_code_contr = civile.codice_fiscale.strip().upper() if civile and civile.codice_fiscale else None
        if tax_code_contr:
            _contr_q |= Q(tax_code=tax_code_contr)
        storico_contratti = list(
            StoricoContratto.objects.filter(_contr_q).order_by("-data_inizio", "-created_at")
        )
        tipologie_contratto = list(TipologiaContratto.objects.filter(is_active=True))
        _tipologie_map = {t.codice: t.nome for t in tipologie_contratto}
        for _c in storico_contratti:
            _c.tipologia_nome = _tipologie_map.get(_c.tipologia_contratto, _c.tipologia_contratto)
        livelli_catalogo = list(LivelloContrattuale.objects.filter(is_active=True))
        livelli_json = json.dumps({l.codice: l.descrizione for l in livelli_catalogo})
        tipi_qualifica_prof = [q for q in tipi_qualifica if q.categoria == TipoQualifica.CAT_PROFESSIONALE]

    # Formazione dipendente (gating su _can_view_formazione — accesso controllato)
    can_view_formazione_tab = _helpers._can_view_formazione(request)
    fm_storico: list = []
    fm_scadenze_urgenti: list = []
    fm_n_completati = 0
    fm_ore_totali = 0.0
    fm_n_attestati = 0
    # KPI formazione divisi per anno corrente / anni precedenti
    fm_anno_corrente = tz.localdate().year
    fm_kpi_anno_corrente = {"anno": fm_anno_corrente, "n": 0, "ore": 0.0}
    fm_kpi_precedenti_totale = {"n": 0, "ore": 0.0}
    fm_kpi_precedenti_per_anno: list = []
    if can_view_formazione_tab:
        try:
            # Carico TUTTI i completamenti (non più solo 30): lo storico mostra di
            # default i primi 30 (cap lato template) ma quando si filtra per anno
            # dai KPI il filtro deve poter agire su tutti i record senza limite.
            fm_storico = list(
                TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=legacy_id)
                .select_related("corso", "corso__piano")
                .order_by("-data_completamento")
            )
            # Aggregazione KPI sugli stessi record (nessuna seconda query)
            _per_anno: dict = {}
            for _rec in fm_storico:
                _data = _rec.data_completamento
                _anno = _data.year if _data else None
                _ore_f = float(_rec.ore_frequentate or 0)
                if _anno == fm_anno_corrente:
                    fm_kpi_anno_corrente["n"] += 1
                    fm_kpi_anno_corrente["ore"] += _ore_f
                else:
                    fm_kpi_precedenti_totale["n"] += 1
                    fm_kpi_precedenti_totale["ore"] += _ore_f
                    if _anno is not None:
                        _bucket = _per_anno.setdefault(_anno, {"anno": _anno, "n": 0, "ore": 0.0})
                        _bucket["n"] += 1
                        _bucket["ore"] += _ore_f
            fm_kpi_precedenti_per_anno = sorted(
                _per_anno.values(), key=lambda b: b["anno"], reverse=True
            )
            fm_n_completati = fm_kpi_anno_corrente["n"] + fm_kpi_precedenti_totale["n"]
            fm_ore_totali = fm_kpi_anno_corrente["ore"] + fm_kpi_precedenti_totale["ore"]
            fm_scadenze_urgenti = list(
                TrainingDeadline.objects.filter(
                    legacy_anagrafica_id=legacy_id,
                    stato_scadenza__in=["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO"],
                )
                .select_related("corso", "corso__piano")
                .order_by("data_scadenza")[:20]
            )
            fm_n_attestati = TrainingCertificate.objects.filter(
                legacy_anagrafica_id=legacy_id
            ).count()
        except Exception:
            logger.exception("Errore caricamento formazione per dipendente %s", legacy_id)

    offboarding_pratica_attiva = None
    offboarding_tasks = []
    offboarding_task_pending_count = 0
    offboarding_task_exception_count = 0
    offboarding_pratiche_recenti = []
    if is_admin:
        try:
            offboarding_pratica_attiva = (
                OffboardingPratica.objects
                .filter(
                    legacy_anagrafica_id=legacy_id,
                    stato__in=OffboardingPratica.STATI_APERTI,
                )
                .prefetch_related("tasks")
                .order_by("-created_at", "-id")
                .first()
            )
            if offboarding_pratica_attiva:
                offboarding_tasks = list(offboarding_pratica_attiva.tasks.all())
                offboarding_task_pending_count = sum(
                    1 for task in offboarding_tasks
                    if task.stato == OffboardingTask.STATO_DA_FARE
                )
                offboarding_task_exception_count = sum(
                    1 for task in offboarding_tasks
                    if task.stato == OffboardingTask.STATO_ECCEZIONE
                )
            offboarding_pratiche_recenti = list(
                OffboardingPratica.objects
                .filter(legacy_anagrafica_id=legacy_id)
                .exclude(stato__in=OffboardingPratica.STATI_APERTI)
                .order_by("-created_at", "-id")[:5]
            )
        except Exception:
            logger.exception("Errore caricamento pratiche offboarding per dipendente %s", legacy_id)

    # Onboarding strutturato (visibile a chi ha accesso HR)
    onboarding_pratica_attiva = None
    onboarding_pratiche_recenti = []
    if can_hr:
        try:
            onboarding_pratica_attiva = onboarding_service.pratica_aperta(legacy_id)
            onboarding_pratiche_recenti = list(
                OnboardingPratica.objects
                .filter(legacy_anagrafica_id=legacy_id)
                .exclude(stato__in=OnboardingPratica.STATI_APERTI)
                .order_by("-created_at", "-id")[:5]
            )
        except Exception:
            logger.exception("Errore caricamento pratiche onboarding per dipendente %s", legacy_id)

    # Catalogo reparti per dropdown + label caporeparto dall'aziendale
    reparti_catalog = list(Reparto.objects.filter(is_active=True).order_by("nome"))
    reparto_corrente = (dip.get("reparto") or "").strip()
    reparto_in_catalog = reparto_corrente and any(
        r.nome.strip().casefold() == reparto_corrente.casefold() for r in reparti_catalog
    )
    # Mansione/ruolo attuali fuori catalogo: il form dello spostamento deve
    # comunque poterli preselezionare, altrimenti "non tocco la mansione"
    # diventerebbe "azzero la mansione" al primo salvataggio.
    mansione_corrente = (dip.get("mansione") or "").strip()
    mansione_in_catalog = mansione_corrente and any(
        m.nome.strip().casefold() == mansione_corrente.casefold() for m in mansioni_catalogo
    )
    _dip_picker_map_detail = {item["id"]: item["label"] for item in _helpers._dipendenti_picker_rows()}
    caporeparto_label = _dip_picker_map_detail.get(aziendale.caporeparto_legacy_id, "") if aziendale and aziendale.caporeparto_legacy_id else ""
    reparto_autofill_json = json.dumps({
        r.nome: {
            "capo_label": _dip_picker_map_detail.get(r.caporeparto_legacy_id or 0, ""),
        }
        for r in reparti_catalog
    })

    _area_corrente_id = aziendale.area_aziendale_id if aziendale else None
    aree_by_reparto: dict[str, list[dict]] = {}
    for a in (
        AreaAziendale.objects.filter(Q(is_active=True) | Q(pk=_area_corrente_id))
        .select_related("reparto")
        .order_by("nome")
    ):
        if a.reparto_id is None:
            continue
        aree_by_reparto.setdefault(a.reparto.nome, []).append({"id": a.id, "nome": a.nome})
    aree_by_reparto_json = json.dumps(aree_by_reparto)

    # Catalogo unico dei ruoli: il dropdown «Ruolo aziendale» dello spostamento
    # legge `RuoloOperativo` come la pagina Ruoli. La vecchia tabella
    # `RuoloAziendale` era una fotografia ferma alla migration 0085 (copia una
    # tantum, a senso unico): i ruoli creati dopo nel catalogo non comparivano
    # qui. Il valore salvato resta il NOME (campo testuale ruolo_aziendale).
    ruoli_aziendali_catalogo = (
        list(
            RuoloOperativo.objects.filter(is_active=True)
            .select_related("ambito")
            .order_by("nome")
        )
        if is_admin else []
    )
    # Il dropdown mostra i ruoli raggruppati per ambito: da lì si capisce se il
    # ruolo scelto sostituirà il «Ruolo aziendale» (ambito della scheda) o si
    # sommerà agli altri (45001, 27001, …).
    ruoli_aziendali_per_ambito = _raggruppa_per_ambito(
        ruoli_aziendali_catalogo, chiave=lambda r: r.ambito
    )
    ruolo_aziendale_corrente = (aziendale.ruolo_aziendale or "").strip() if aziendale else ""
    ruolo_aziendale_in_catalog = ruolo_aziendale_corrente and any(
        r.nome.strip().casefold() == ruolo_aziendale_corrente.casefold()
        for r in ruoli_aziendali_catalogo
    )

    # Ogni card di spostamento può avere un valore fuori catalogo (es. reparto
    # rinominato dopo): il form di modifica deve comunque preselezionarlo,
    # altrimenti "non tocco il reparto" diventerebbe "lo azzero" al salvataggio.
    for _ass in assegnazioni:
        _ass.reparto_in_catalog = bool(_ass.reparto) and any(
            r.nome.strip().casefold() == _ass.reparto.strip().casefold() for r in reparti_catalog
        )
        _ass.mansione_in_catalog = bool(_ass.mansione) and any(
            m.nome.strip().casefold() == _ass.mansione.strip().casefold() for m in mansioni_catalogo
        )
        _ass.ruolo_aziendale_in_catalog = bool(_ass.ruolo_aziendale) and any(
            r.nome.strip().casefold() == _ass.ruolo_aziendale.strip().casefold()
            for r in ruoli_aziendali_catalogo
        )

    # Anzianità di servizio (KPI scheda sintetica del Riepilogo). Calcolata dalla
    # prima assunzione (fallback su assunzione corrente) fino a oggi o alla
    # cessazione se il rapporto è chiuso.
    anzianita_label = ""
    _data_assunzione_anz = (aziendale.data_prima_assunzione or aziendale.data_assunzione_ultima) if aziendale else None
    if _data_assunzione_anz:
        _fine_anz = aziendale.data_cessazione if (aziendale and aziendale.data_cessazione) else oggi
        if _fine_anz >= _data_assunzione_anz:
            _tot_mesi = (_fine_anz.year - _data_assunzione_anz.year) * 12 + (_fine_anz.month - _data_assunzione_anz.month)
            if _fine_anz.day < _data_assunzione_anz.day:
                _tot_mesi -= 1
            _tot_mesi = max(0, _tot_mesi)
            _anni, _mesi = divmod(_tot_mesi, 12)
            if _anni and _mesi:
                anzianita_label = f"{_anni} ann{'o' if _anni == 1 else 'i'} e {_mesi} mes{'e' if _mesi == 1 else 'i'}"
            elif _anni:
                anzianita_label = f"{_anni} ann{'o' if _anni == 1 else 'i'}"
            elif _mesi:
                anzianita_label = f"{_mesi} mes{'e' if _mesi == 1 else 'i'}"
            else:
                anzianita_label = "< 1 mese"

    return render(request, "anagrafica/pages/dipendente_detail.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "can_stats": can_stats,
        "is_admin": is_admin,
        "account_scheda": views_account.contesto_scheda(request, legacy_id) if is_admin else None,
        "can_hr": can_hr,
        "civile": civile,
        "civile_foto_url": civile_foto_url,
        "aziendale": aziendale,
        "form_civile": form_civile,
        "form_aziendale": form_aziendale,
        "formset_figli": formset_figli,
        "figli_list": figli_list,
        "reparti_catalog": reparti_catalog,
        "reparto_in_catalog": reparto_in_catalog,
        "mansione_in_catalog": mansione_in_catalog,
        "ruolo_aziendale_in_catalog": ruolo_aziendale_in_catalog,
        "caporeparto_label": caporeparto_label,
        "reparto_autofill_json": reparto_autofill_json,
        "aree_by_reparto_json": aree_by_reparto_json,
        "anzianita_label": anzianita_label,
        "widgets_visible": widgets_visible,
        "widgets_hidden": widgets_hidden,
        "all_widgets": _helpers.STAT_WIDGETS,
        "ruoli_assegnati": ruoli_assegnati,
        "ruoli_disponibili": ruoli_disponibili,
        "ruoli_per_ambito": ruoli_per_ambito,
        "ruoli_disponibili_per_ambito": ruoli_disponibili_per_ambito,
        "mansioni_catalogo": mansioni_catalogo,
        "assegnazioni": assegnazioni,
        **_mansioni_da_rivedere_ctx(request, legacy_id, is_admin),
        **_posizione_struttura_ctx(request, legacy_id, is_admin),
        "assegnazione_in_corso": assegnazione_in_corso,
        "assetto_attuale": assetto_attuale,
        "ruoli_aziendali_catalogo": ruoli_aziendali_catalogo,
        "ruoli_aziendali_per_ambito": ruoli_aziendali_per_ambito,
        "qualifiche_dip": qualifiche_dip,
        "tipi_qualifica": tipi_qualifica,
        "oggi": oggi,
        "oggi_plus60": oggi + timedelta(days=60),
        "dpi_richieste": dpi_richieste,
        "dpi_consegnati": dpi_consegnati,
        "dpi_consegna_doc_map": dpi_consegna_doc_map,
        "can_view_visite": can_view_visite,
        "can_edit_visite": can_view_visite and _helpers._can_edit_visite_mediche(request),
        "can_delete_visite": can_view_visite and _helpers._has_canonical_grant(request, PERM_VISITE_DELETE),
        "visite_stato_list": visite_stato_list,
        "visite_storico_list": visite_storico_list,
        "tipi_visita_attivi": tipi_visita_attivi,
        "documenti_dipendente": documenti_dipendente,
        "cartelle_documenti": cartelle_documenti,
        "visita_esiti": VisitaMedica.Esito.choices,
        "software_licenses": software_licenses,
        "assets_assegnati": assets_assegnati,
        "assets_reparto": assets_reparto,
        "reparti_capo": reparti_capo,
        "retribuzioni_latest": retribuzioni_latest,
        "retribuzioni_fissi": retribuzioni_fissi,
        "retribuzioni_variabili": retribuzioni_variabili,
        "retribuzioni_totali": retribuzioni_totali,
        "retribuzioni_altri": retribuzioni_altri,
        "retribuzioni_timeline": retribuzioni_timeline,
        "retribuzioni_importazione": retribuzioni_importazione,
        "retribuzioni_data_competenza": retribuzioni_data_competenza,
        "retribuzioni_has_changes": retribuzioni_has_changes,
        "storico_cambiamenti": storico_cambiamenti,
        "storico_contratti": storico_contratti,
        "tipologie_contratto": tipologie_contratto,
        "livelli_catalogo": livelli_catalogo,
        "livelli_json": livelli_json,
        "tipi_qualifica_prof": tipi_qualifica_prof,
        "ratei_saldi": ratei_saldi,
        "assenze_list": assenze_list,
        "assenze_summary_anno": assenze_summary_anno,
        "assenze_tot_anno": assenze_tot_anno,
        "assenze_kpi_annuali": assenze_kpi_annuali,
        "assenze_cronologia": assenze_cronologia,
        "assenze_no_link": assenze_no_link,
        # Formazione
        "can_view_formazione_tab": can_view_formazione_tab,
        "fm_storico": fm_storico,
        "fm_scadenze_urgenti": fm_scadenze_urgenti,
        "fm_n_completati": fm_n_completati,
        "fm_ore_totali": fm_ore_totali,
        "fm_n_attestati": fm_n_attestati,
        "fm_kpi_anno_corrente": fm_kpi_anno_corrente,
        "fm_kpi_precedenti_totale": fm_kpi_precedenti_totale,
        "fm_kpi_precedenti_per_anno": fm_kpi_precedenti_per_anno,
        "fm_storico_cap": 30,
        # Offboarding
        "offboarding_pratica_attiva": offboarding_pratica_attiva,
        "offboarding_tasks": offboarding_tasks,
        "offboarding_task_pending_count": offboarding_task_pending_count,
        "offboarding_task_exception_count": offboarding_task_exception_count,
        "offboarding_pratiche_recenti": offboarding_pratiche_recenti,
        "offboarding_motivo_choices": OffboardingPratica.MOTIVO_CHOICES,
        "offboarding_restituzioni_labels": OFFBOARDING_RESTITUZIONI_LABELS,
        # Onboarding
        "onboarding_pratica_attiva": onboarding_pratica_attiva,
        "onboarding_pratiche_recenti": onboarding_pratiche_recenti,
    })


# ---------------------------------------------------------------------------
# Stampa scheda dipendente — anagrafica civile + aziendale + dati bancari
# ---------------------------------------------------------------------------

@login_required
def dipendente_print(request, legacy_id: int):
    """Pagina stampa scheda dipendente completa.

    Aggrega in un'unica vista A4-friendly:
      - dati legacy base (nome, cognome, username, reparto, mansione, email);
      - anagrafica civile (residenza, domicilio, CF, titolo studio, contatti
        privati, patente);
      - anagrafica aziendale (badge, area, ruolo, contratto, livello, date
        assunzione/cessazione/prova, taglie DPI, consenso privacy);
      - dati bancari (nome banca, IBAN, intestatario) — gated da
        `_check_hr_permission`; per gli utenti senza permesso l'IBAN appare
        mascherato e il blocco è etichettato come riservato.

    La pagina ha un'action bar (non stampata) con bottone "Stampa" che invoca
    `window.print()`. CSS `@media print` rimuove sfondi e action bar.
    """
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    aziendale = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    civile_foto_url = _foto_dipendente_url(civile, legacy_id)

    can_hr = _helpers._check_hr_permission(request)

    return render(request, "anagrafica/pages/dipendente_print.html", {
        "dip": dip,
        "civile": civile,
        "aziendale": aziendale,
        "civile_foto_url": civile_foto_url,
        "can_hr": can_hr,
        "legacy_id": legacy_id,
    })


@login_required
def dipendente_libretto_formativo(request, legacy_id: int):
    """Curriculum formativo completo del dipendente, A4-friendly.

    Aggrega lo storico completamenti (`TrainingEmployeeRecord`, usando i campi
    snapshot per integrità storica), gli attestati (`TrainingCertificate`) e
    lo stato corrente degli obblighi (`TrainingDeadline` con is_required).
    Stesso pattern di `dipendente_print`: action bar non stampata +
    `window.print()`. La generazione è tracciata in `TrainingExportLog`
    (tipo STORICO_DIP).

    Con `?dal=` / `?al=` (ISO) lo **storico** viene ristretto al periodo di
    completamento: è la domanda tipica di un'ispezione o di un bilancio annuale
    ("cosa ha fatto nel 2025"). Gli obblighi correnti restano fuori dal filtro,
    perché sono una fotografia di oggi e non un fatto datato.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la formazione.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    # Variante PDF server-side (stessa fonte dati): ?formato=pdf
    formato = (request.GET.get("formato") or "").strip().lower()
    dal, al = _helpers._periodo_da_request(request)
    if formato == "pdf":
        from ..services.attestato_pdf import build_libretto_pdf_bytes
        try:
            pdf = build_libretto_pdf_bytes(legacy_id, dal=dal, al=al)
        except Exception:
            logger.exception("Errore generazione PDF libretto %s", legacy_id)
            messages.error(request, "Errore nella generazione del PDF del libretto.")
            return redirect("anagrafica:dipendente_libretto_formativo", legacy_id=legacy_id)
        try:
            TrainingExportLog.objects.create(
                tipo="STORICO_DIP",
                filtri_json={
                    "legacy_anagrafica_id": legacy_id, "formato": "libretto_pdf",
                    "dal": dal.isoformat() if dal else None,
                    "al": al.isoformat() if al else None,
                },
                righe_esportate=0,
                generato_da=request.user,
                ip_address=request.META.get("REMOTE_ADDR") or None,
            )
        except Exception:
            logger.exception("Errore TrainingExportLog per libretto PDF")
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="libretto_formativo_{legacy_id}.pdf"'
        return resp

    record_qs = (
        TrainingEmployeeRecord.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .select_related("attestato", "corso")
    )
    if dal:
        record_qs = record_qs.filter(data_completamento__gte=dal)
    if al:
        record_qs = record_qs.filter(data_completamento__lte=al)
    record_storici = list(record_qs.order_by("-data_completamento", "-created_at"))
    ore_totali = sum((r.ore_frequentate or 0) for r in record_storici)
    totale_record = TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=legacy_id).count()

    from django.utils import timezone as tz
    oggi = tz.localdate()
    obblighi = list(
        TrainingDeadline.objects
        .filter(legacy_anagrafica_id=legacy_id, is_required=True)
        .select_related("corso")
        .order_by("data_scadenza")
    )

    try:
        TrainingExportLog.objects.create(
            tipo="STORICO_DIP",
            filtri_json={
                "legacy_anagrafica_id": legacy_id, "formato": "libretto_html",
                "dal": dal.isoformat() if dal else None,
                "al": al.isoformat() if al else None,
            },
            righe_esportate=len(record_storici),
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore registrazione TrainingExportLog per libretto formativo")

    from ..services.attestato_pdf import RIFERIMENTO_LIBRETTO
    doc_libretto = (
        DocumentoDipendente.objects
        .filter(oggetto_riferimento_tipo=RIFERIMENTO_LIBRETTO, oggetto_riferimento_id=legacy_id)
        .order_by("-id").first()
    )
    return render(request, "anagrafica/pages/dipendente_libretto.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "record_storici": record_storici,
        "ore_totali": ore_totali,
        "obblighi": obblighi,
        "oggi": oggi,
        "dal": dal,
        "al": al,
        "periodo_attivo": bool(dal or al),
        "totale_record": totale_record,
        "can_edit": _helpers._can_edit_formazione(request),
        "doc_libretto": doc_libretto,
    })


@login_required
def dipendente_libretto_sanitario(request, legacy_id: int):
    """Libretto sanitario aziendale: i requisiti della mansione e il loro stato.

    È la lettura per esteso della catena "fattori di rischio → mansione di
    rischio → mansione di lavoro → requisiti → conforme/non conforme": il
    semaforo nella scheda dice *se* la persona è a posto, questa pagina dice
    *su cosa*, *perché è dovuto* e *entro quando* — una riga per obbligo, con
    data dell'ultima evidenza, scadenza e origine. Stampabile (A4) perché è il
    documento che si mostra a un'ispezione.

    Privacy: i nomi delle tipologie di visita e il giudizio di idoneità
    compaiono solo con il gate sorveglianza sanitaria
    (``_can_view_visite_mediche``); le prescrizioni mai.
    """
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    from ..services import libretto_sanitario as libretto_service

    can_view_visite = _helpers._can_view_visite_mediche(request)
    mansione_nome = str(dip.get("mansione") or "").strip()
    dati = libretto_service.libretto(
        legacy_id,
        mansione_nome=mansione_nome,
        include_visite_dettaglio=can_view_visite,
    )
    mansione_obj = mansionario_service.mansione_per_nome(mansione_nome)
    return render(request, "anagrafica/pages/dipendente_libretto_sanitario.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "libretto": dati,
        "mansione_obj": mansione_obj,
        "can_view_visite": can_view_visite,
    })


@login_required
@require_POST
def libretto_salva_box(request, legacy_id: int):
    """Genera e salva (manualmente) il libretto formativo PDF nel box del dipendente.

    Un solo libretto per dipendente: la copia viene sostituita ad ogni salvataggio
    (è una fotografia aggiornata del curriculum). Gated dal permesso di modifica.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per archiviare il libretto.")
        return redirect("anagrafica:dipendente_libretto_formativo", legacy_id=legacy_id)
    from ..services.attestato_pdf import archivia_libretto
    try:
        doc = archivia_libretto(legacy_id, user=request.user)
        messages.success(request, f"Libretto formativo archiviato nel box ({doc.nome_originale}).")
    except Exception:
        logger.exception("Archiviazione libretto fallita per %s", legacy_id)
        messages.error(request, "Errore durante l'archiviazione del libretto.")
    return redirect("anagrafica:dipendente_libretto_formativo", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Ruoli operativi — assegna/rimuovi a dipendente
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_ruolo_assegna(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per assegnare ruoli operativi.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ruolo_id = int(request.POST.get("ruolo_id") or 0)
    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id, is_active=True)
    _, created = DipendenteRuoloOperativo.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        ruolo=ruolo,
        defaults={"assegnato_da": request.user},
    )
    if created:
        # Il ruolo aziendale della scheda è il ruolo *principale*: lo si scrive
        # solo a chi non ne ha ancora uno, per non ribaltare il principale a
        # ogni ruolo aggiuntivo (una persona può averne più d'uno).
        from anagrafica.services.ruoli_sync import dopo_assegnazione
        promosso = dopo_assegnazione(legacy_id, ruolo, user=request.user)
        if promosso:
            messages.success(
                request,
                f'Ruolo "{ruolo.nome}" assegnato ed impostato come ruolo aziendale principale.',
            )
        else:
            messages.success(request, f'Ruolo "{ruolo.nome}" assegnato.')
    else:
        messages.info(request, f'Ruolo "{ruolo.nome}" già assegnato.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_ruolo_rimuovi(request, legacy_id: int, assegnazione_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per rimuovere ruoli operativi.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    assegnazione = get_object_or_404(DipendenteRuoloOperativo, pk=assegnazione_id, legacy_anagrafica_id=legacy_id)
    nome = assegnazione.ruolo.nome
    assegnazione.delete()
    # Tolto il ruolo principale, subentra il primo rimasto: la scheda non deve
    # restare a indicare un ruolo che la persona non ricopre più.
    from anagrafica.services.ruoli_sync import dopo_rimozione
    nuovo_principale = dopo_rimozione(legacy_id, nome, user=request.user)
    if nuovo_principale:
        messages.success(
            request,
            f'Ruolo "{nome}" rimosso. Ruolo aziendale principale: "{nuovo_principale}".',
        )
    else:
        messages.success(request, f'Ruolo "{nome}" rimosso.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


def _raggruppa_per_ambito(elementi, chiave):
    """Raggruppa per ambito conservando l'ordine degli ambiti (senza in fondo).

    Ritorna ``[{"ambito": AmbitoRuolo|None, "elementi": [...]}, …]``.
    """
    gruppi: dict[int | None, dict] = {}
    for el in elementi:
        ambito = chiave(el)
        key = ambito.id if ambito else None
        gruppi.setdefault(key, {"ambito": ambito, "elementi": []})["elementi"].append(el)
    return sorted(
        gruppi.values(),
        key=lambda g: (
            g["ambito"].ordine if g["ambito"] else 9999,
            (g["ambito"].nome if g["ambito"] else "").casefold(),
        ),
    )


# ---------------------------------------------------------------------------
# Mansione dipendente — set dal catalogo (scrive su legacy DB)
# ---------------------------------------------------------------------------

def _data_decorrenza(request, campo: str = "data_decorrenza"):
    """Legge dal POST la data di inizio validità del cambiamento organizzativo.

    Vuota o malformata => nessuna decorrenza esplicita: il chiamante ricade su oggi.
    """
    raw = (request.POST.get(campo) or "").strip()
    if not raw:
        return None
    parsed = parse_date(raw)
    return parsed


def _registra_cambiamento(
    legacy_id: int,
    tipo: str,
    vecchio: str,
    nuovo: str,
    user,
    data_effetto=None,
    note: str = "",
) -> DipendenteCambiamentoOrganizzativo | None:
    """Apre un nuovo periodo di assegnazione, solo se il valore è cambiato davvero.

    Confronto case-insensitive con strip, così micro-edit di whitespace o maiuscole
    non generano voci storiche spurie.

    Il periodo ancora aperto dello stesso tipo viene chiuso al giorno prima della
    nuova decorrenza, così lo storico resta una sequenza continua di intervalli
    inizio/fine e una sola riga per tipo risulta "in corso".
    """
    from django.utils import timezone as _tz
    v = (vecchio or "").strip()
    n = (nuovo or "").strip()
    if v.casefold() == n.casefold():
        return None
    inizio = data_effetto or _tz.localdate()
    DipendenteCambiamentoOrganizzativo.chiudi_periodo_aperto(legacy_id, tipo, inizio)
    return DipendenteCambiamentoOrganizzativo.objects.create(
        legacy_anagrafica_id=legacy_id,
        tipo=tipo,
        valore_precedente=v[:300],
        valore_nuovo=n[:300],
        data_effetto=inizio,
        note=note,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


@event_flow("idoneita_gap_mansione", skipped_result=None)
def _notifica_gap_idoneita(legacy_id: int, dip: dict, mansione_nome: str, user=None) -> None:
    """All'assegnazione di una nuova mansione, ricalcola l'idoneità e notifica
    (email, fail-open) i requisiti mancanti/scaduti a caporeparto + RSPP/HR.
    Nessun dato clinico: le visite restano in forma generica."""
    try:
        stato = conformita_service.stato_conformita(legacy_id, mansione=mansione_nome)
        idn = stato.get("idoneita", {})
        gap = list(idn.get("scaduti", [])) + list(idn.get("mancanti", []))
        if idn.get("esito") not in ("warn", "ko") or not gap:
            return
        from core.email_utils import send_hub_mail
        from ..services.onboarding import _caporeparto_emails
        from ..services.reminders import get_reminder_recipients
        reparto = (dip.get("reparto") or "").strip()
        nome = naming.nome_completo(dip.get("nome"), dip.get("cognome")) or f"#{legacy_id}"
        dest = sorted(set(
            get_reminder_recipients("idoneita_reminder_emails") + _caporeparto_emails(reparto)
        ))
        if not dest:
            return
        send_hub_mail(
            subject=f"[Idoneità] {nome} → mansione «{mansione_nome}»: requisiti da verificare",
            body_text=(
                f"{nome}{(' — reparto ' + reparto) if reparto else ''} è stato assegnato alla "
                f"mansione «{mansione_nome}».\n\nRequisiti della mansione ancora da soddisfare:\n- "
                + "\n- ".join(gap)
            ),
            recipients=dest, title="Idoneità alla mansione",
            email_type="Anagrafica HR", section_label="Idoneità", fail_silently=True,
        )
    except Exception:
        logger.warning("Notifica gap idoneità (cambio mansione) fallita per %s", legacy_id, exc_info=True)


@login_required
@require_POST
def dipendente_assegnazione_create(request, legacy_id: int):
    """Registra uno spostamento organizzativo (reparto + area + mansione + ruolo).

    Sostituisce i vecchi mini-form separati "cambia reparto" / "cambia mansione":
    uno spostamento reale è un atto solo e va registrato come tale, con una sola
    decorrenza e una sola verifica di idoneità.

    Se la decorrenza è futura l'assegnazione resta **programmata** e i campi vivi
    del dipendente non vengono toccati: li allineerà il task alla data giusta.
    """
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per registrare uno spostamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    area_aziendale_raw = (request.POST.get("area_aziendale") or "").strip()
    data_inizio = _data_decorrenza(request, "data_inizio") or django_timezone.localdate()
    mansione_nome = (request.POST.get("mansione") or "").strip()[:200]

    try:
        from ..services.assegnazioni import crea_assegnazione
        assegnazione = crea_assegnazione(
            legacy_id,
            data_inizio=data_inizio,
            reparto=(request.POST.get("reparto") or "").strip()[:200],
            area_aziendale_id=int(area_aziendale_raw) if area_aziendale_raw.isdigit() else None,
            mansione=mansione_nome,
            ruolo_aziendale=(request.POST.get("ruolo_aziendale") or "").strip()[:200],
            ruolo_parallelo=bool(request.POST.get("ruolo_parallelo")),
            note=(request.POST.get("note") or "").strip(),
            user=request.user,
            include_visite_dettaglio=_helpers._can_view_visite_mediche(request),
        )
    except Exception:
        logger.exception("Errore registrazione spostamento dipendente %s", legacy_id)
        messages.error(request, "Errore durante la registrazione dello spostamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    quando = (
        f"programmato dal {data_inizio:%d-%m-%Y}"
        if assegnazione.is_programmata else "attivo da oggi"
    )
    esito_idoneita = assegnazione.idoneita_label.lower()
    if assegnazione.idoneita_gap:
        messages.warning(
            request,
            f"Spostamento registrato ({quando}) — {esito_idoneita}: "
            + ", ".join(assegnazione.idoneita_gap[:5])
            + ("…" if len(assegnazione.idoneita_gap) > 5 else ""),
        )
    else:
        messages.success(request, f"Spostamento registrato ({quando}) — {esito_idoneita}.")

    # Il gap di idoneità va anche a caporeparto/RSPP/HR, come già avveniva al
    # cambio mansione dal vecchio mini-form.
    if mansione_nome and assegnazione.idoneita_gap:
        _notifica_gap_idoneita(legacy_id, dip, mansione_nome, request.user)

    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_assegnazione_annulla(request, legacy_id: int, assegnazione_id: int):
    """Annulla uno spostamento **programmato e non ancora attivato**.

    Serve perché una decorrenza futura è una promessa revocabile: senza questo,
    una data sbagliata resterebbe in calendario senza rimedio. Un'assegnazione
    già attivata non si cancella — è storia, e si corregge con un nuovo
    spostamento.
    """
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per annullare uno spostamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    assegnazione = DipendenteAssegnazione.objects.filter(
        pk=assegnazione_id, legacy_anagrafica_id=legacy_id,
    ).first()
    if assegnazione is None:
        messages.error(request, "Spostamento non trovato.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    if assegnazione.attivata_il is not None:
        messages.error(
            request,
            "Lo spostamento è già attivo: usa \"Modifica\" per correggerlo.",
        )
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    # Gli adempimenti generati restano nella storia come ANNULLATI con motivo
    # (SET_NULL sull'assegnazione), e l'annullamento lascia traccia in timeline.
    # Tutto in una transazione: riapertura della card precedente compresa.
    from django.db import transaction as _tx
    from ..services import eventi_sicurezza
    from ..services.assegnazioni import rigenera_successiva
    from ..services.cambio_mansione import annulla_piano
    motivo = (request.POST.get("motivo") or "").strip()[:250]
    with _tx.atomic():
        # Riapre l'assegnazione che questa aveva chiuso, così non resta un buco.
        precedente = (
            DipendenteAssegnazione.objects
            .filter(legacy_anagrafica_id=legacy_id, data_fine__isnull=False)
            .exclude(pk=assegnazione.pk)
            .order_by("-data_fine", "-created_at")
            .first()
        )
        if precedente is not None and precedente.data_fine == assegnazione.data_inizio - _timedelta(days=1):
            precedente.data_fine = None
            precedente.save(update_fields=["data_fine"])
        descr = f"Spostamento a «{assegnazione.mansione or assegnazione.reparto}» dal {assegnazione.data_inizio:%d/%m/%Y} annullato"
        annullati = annulla_piano(assegnazione, motivo=f"{descr}{': ' + motivo if motivo else ''}", user=request.user)
        eventi_sicurezza.registra(
            legacy_id, "ASSEGNAZIONE_ANNULLATA", descr, request=request,
            data_effetto=assegnazione.data_inizio,
            payload={"assegnazione_id": assegnazione.pk, "mansione": assegnazione.mansione,
                     "reparto": assegnazione.reparto, "adempimenti_annullati": annullati,
                     "motivo": motivo},
        )
        data_annullata = assegnazione.data_inizio
        assegnazione.delete()
        rigenera_successiva(legacy_id, data_annullata, user=request.user)
    messages.success(request, "Spostamento programmato annullato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_assegnazione_modifica(request, legacy_id: int, assegnazione_id: int):
    """Corregge una card di spostamento già registrata — attiva, programmata o
    conclusa — senza registrarne una nuova.

    A differenza della creazione, qui i campi lasciati vuoti ereditano i
    valori già sulla card (non l'assetto vivo di oggi): si sta correggendo
    QUESTA registrazione. Vedi ``services.assegnazioni.modifica_assegnazione``
    per cosa succede quando la card è quella che descrive l'assetto attuale.
    """
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare uno spostamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    assegnazione = DipendenteAssegnazione.objects.filter(
        pk=assegnazione_id, legacy_anagrafica_id=legacy_id,
    ).first()
    if assegnazione is None:
        messages.error(request, "Spostamento non trovato.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    area_aziendale_raw = (request.POST.get("area_aziendale") or "").strip()
    data_inizio = _data_decorrenza(request, "data_inizio") or assegnazione.data_inizio

    try:
        from ..services.assegnazioni import modifica_assegnazione
        modifica_assegnazione(
            assegnazione,
            data_inizio=data_inizio,
            reparto=(request.POST.get("reparto") or "").strip()[:200],
            area_aziendale_id=int(area_aziendale_raw) if area_aziendale_raw.isdigit() else None,
            mansione=(request.POST.get("mansione") or "").strip()[:200],
            ruolo_aziendale=(request.POST.get("ruolo_aziendale") or "").strip()[:200],
            ruolo_parallelo=bool(request.POST.get("ruolo_parallelo")),
            note=(request.POST.get("note") or "").strip(),
            user=request.user,
            include_visite_dettaglio=_helpers._can_view_visite_mediche(request),
        )
    except Exception:
        logger.exception("Errore modifica spostamento %s (dipendente %s)", assegnazione_id, legacy_id)
        messages.error(request, "Errore durante la modifica dello spostamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    messages.success(request, "Spostamento aggiornato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_matricola_set(request, legacy_id: int):
    """Modifica la matricola di un dipendente già presente in anagrafica.

    Serve per i preinserimenti (dipendente creato prima dell'assegnazione
    della matricola aziendale) e per i candidati importati dal modulo
    recruiting, che possono già esistere come dipendente senza matricola.
    """
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare la matricola.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    matricola_nuova = (request.POST.get("matricola") or "").strip()[:100]

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    matricola_vecchia = (dip.get("matricola") or "").strip()

    try:
        upsert_anagrafica_dipendente(
            row_id=legacy_id,
            aliasusername=dip.get("aliasusername") or "",
            nome=dip.get("nome") or "",
            cognome=dip.get("cognome") or "",
            reparto=dip.get("reparto") or "",
            mansione=dip.get("mansione") or "",
            ruolo=dip.get("ruolo") or "",
            matricola=matricola_nuova,
            email=dip.get("email") or "",
            email_notifica=dip.get("email_notifica") or "",
            attivo=bool(dip.get("attivo", True)),
        )
        _registra_cambiamento(
            legacy_id,
            DipendenteCambiamentoOrganizzativo.TIPO_MATRICOLA,
            matricola_vecchia, matricola_nuova,
            request.user,
        )
        messages.success(request, f'Matricola aggiornata a "{matricola_nuova}".' if matricola_nuova else "Matricola rimossa.")
    except Exception:
        logger.exception("Errore aggiornamento matricola dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento della matricola.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_username_set(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare lo username.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    new_alias = (request.POST.get("aliasusername") or "").strip()[:150]

    if not new_alias:
        messages.error(request, "Lo username non può essere vuoto.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    if " " in new_alias:
        messages.error(request, "Lo username non può contenere spazi.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    # Normalizza con la stessa regola di upsert_anagrafica_dipendente, così
    # anagrafica e account portale restano allineati sullo stesso valore.
    new_alias = normalize_legacy_alias(new_alias)
    if not new_alias:
        messages.error(request, "Lo username non è valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    # Unicità: nessun altro dipendente deve avere lo stesso alias
    conflict = AnagraficaDipendente.objects.filter(
        aliasusername__iexact=new_alias
    ).exclude(id=legacy_id).first()
    if conflict:
        messages.error(request, f"Lo username '{new_alias}' è già in uso da un altro dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    old_alias = (dip.get("aliasusername") or "").strip()

    # Account portale Django collegato: anagrafica.utente_id -> Profile.legacy_user_id -> User.
    # aliasusername è la fonte di verità: lo username Django viene tenuto allineato.
    from django.db import transaction
    from django.contrib.auth import get_user_model
    from core.models import Profile

    linked_utente_id = int(dip.get("utente_id") or 0)
    django_profile = None
    if linked_utente_id > 0:
        django_profile = (
            Profile.objects.select_related("user")
            .filter(legacy_user_id=linked_utente_id)
            .first()
        )

    # Fail-closed: blocca prima di scrivere se lo username è già preso da un altro account.
    if django_profile and django_profile.user_id:
        User = get_user_model()
        username_conflict = (
            User.objects.filter(username__iexact=new_alias)
            .exclude(id=django_profile.user_id)
            .first()
        )
        if username_conflict:
            messages.error(request, f"Lo username '{new_alias}' è già in uso da un altro account portale.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    try:
        with transaction.atomic():
            upsert_anagrafica_dipendente(
                row_id=legacy_id,
                aliasusername=new_alias,
                nome=dip.get("nome") or "",
                cognome=dip.get("cognome") or "",
                reparto=dip.get("reparto") or "",
                mansione=dip.get("mansione") or "",
                ruolo=dip.get("ruolo") or "",
                matricola=dip.get("matricola") or "",
                email=dip.get("email") or "",
                email_notifica=dip.get("email_notifica") or "",
                attivo=bool(dip.get("attivo", True)),
            )
            if (
                django_profile
                and django_profile.user_id
                and django_profile.user.username != new_alias
            ):
                django_profile.user.username = new_alias
                django_profile.user.save(update_fields=["username"])
        _registra_cambiamento(legacy_id, "USERNAME", old_alias, new_alias, request.user)
        if django_profile and django_profile.user_id:
            messages.success(request, f"Username aggiornato a '{new_alias}' (anagrafica + account portale).")
        else:
            messages.success(request, f"Username aggiornato a '{new_alias}'.")
    except Exception:
        logger.exception("Errore aggiornamento username dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento dello username.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_toggle_active(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare lo stato del dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    currently_active = dip.get("attivo") not in {None, 0, False, "0"}
    new_active = not currently_active

    try:
        upsert_anagrafica_dipendente(
            row_id=legacy_id,
            aliasusername=dip.get("aliasusername") or "",
            nome=dip.get("nome") or "",
            cognome=dip.get("cognome") or "",
            reparto=dip.get("reparto") or "",
            mansione=dip.get("mansione") or "",
            ruolo=dip.get("ruolo") or "",
            matricola=dip.get("matricola") or "",
            email=dip.get("email") or "",
            email_notifica=dip.get("email_notifica") or "",
            attivo=new_active,
            detach_account=not new_active,
        )
        if new_active:
            messages.success(request, "Dipendente riattivato.")
        else:
            messages.success(request, "Dipendente disattivato. L'account portale è stato scollegato.")
    except Exception:
        logger.exception("Errore toggle attivo dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'aggiornamento dello stato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Qualifiche dipendente — assegna/rimuovi
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_offboarding_licenziamento(request, legacy_id: int):
    if not _offboarding_is_admin(request):
        messages.error(request, "Non hai i permessi per avviare l'offboarding del dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    from django.db import transaction
    from django.utils import timezone

    oggi = timezone.localdate()
    raw_date = (request.POST.get("data_cessazione") or "").strip()
    data_cessazione = oggi
    if raw_date:
        try:
            data_cessazione = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Data cessazione non valida.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    raw_ultimo_giorno = (request.POST.get("ultimo_giorno_operativo") or "").strip()
    ultimo_giorno_operativo = data_cessazione
    if raw_ultimo_giorno:
        try:
            ultimo_giorno_operativo = date.fromisoformat(raw_ultimo_giorno)
        except ValueError:
            messages.error(request, "Ultimo giorno operativo non valido.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    motivo = (request.POST.get("motivo") or OffboardingPratica.MOTIVO_LICENZIAMENTO).strip()
    valid_motivi = {choice[0] for choice in OffboardingPratica.MOTIVO_CHOICES}
    if motivo not in valid_motivi:
        motivo = OffboardingPratica.MOTIVO_ALTRO
    old_utente_id = _int_or_none(dip.get("utente_id")) or None
    restituzioni_codes = [
        code
        for code in request.POST.getlist("restituzioni")
        if code in OFFBOARDING_RESTITUZIONI_LABELS
    ]
    restituzioni_note = (request.POST.get("restituzioni_note") or "").strip()[:1000]
    dipendente_nome = _offboarding_dipendente_nome(dip)

    aziendale = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    if aziendale and aziendale.data_cessazione:
        messages.warning(request, "Dipendente gia cessato: usa 'Rimetti in forza' se devi riaprire il rapporto.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    pratica_aperta = OffboardingPratica.objects.filter(
        legacy_anagrafica_id=legacy_id,
        stato__in=OffboardingPratica.STATI_APERTI,
    ).first()
    if pratica_aperta:
        messages.warning(request, "Esiste gia una pratica offboarding aperta per questo dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    try:
        with transaction.atomic():
            pratica = OffboardingPratica.objects.create(
                legacy_anagrafica_id=legacy_id,
                dipendente_nome=dipendente_nome,
                reparto=str(dip.get("reparto") or "").strip(),
                mansione=str(dip.get("mansione") or "").strip(),
                motivo=motivo,
                data_cessazione_prevista=data_cessazione,
                ultimo_giorno_operativo=ultimo_giorno_operativo,
                note_hr=restituzioni_note,
                utente_id_pre_offboarding=old_utente_id,
                created_by=request.user,
                updated_by=request.user,
            )
            OffboardingTask.objects.bulk_create([
                OffboardingTask(
                    pratica=pratica,
                    codice=task["codice"],
                    categoria=task["categoria"],
                    titolo=task["titolo"],
                    descrizione=task["descrizione"],
                )
                for task in _offboarding_task_definitions(restituzioni_codes)
            ])

        try:
            from core.audit import log_action
            log_action(
                request,
                "DIPENDENTE_OFFBOARDING_PRATICA_APERTA",
                "anagrafica",
                {
                    "pratica_id": pratica.id,
                    "legacy_anagrafica_id": legacy_id,
                    "dipendente_nome": dipendente_nome,
                    "motivo": motivo,
                    "data_cessazione_prevista": data_cessazione.isoformat(),
                    "ultimo_giorno_operativo": ultimo_giorno_operativo.isoformat() if ultimo_giorno_operativo else "",
                    "legacy_attivo": bool(dip.get("attivo", True)),
                    "account_scollegato": False,
                    "utente_id_pre_offboarding": old_utente_id,
                    "restituzioni_richieste": restituzioni_codes,
                    "restituzioni_richieste_label": [
                        OFFBOARDING_RESTITUZIONI_LABELS[code]
                        for code in restituzioni_codes
                    ],
                    "restituzioni_note": restituzioni_note,
                },
            )
        except Exception:
            logger.warning("Audit DIPENDENTE_OFFBOARDING_PRATICA_APERTA fallito", exc_info=True)

        messages.success(
            request,
            f"Pratica offboarding avviata per il {data_cessazione:%d-%m-%Y}. "
            "Completa le restituzioni e poi conferma la chiusura del rapporto.",
        )
    except Exception:
        logger.exception("Errore avvio pratica offboarding dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'avvio della pratica offboarding.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_offboarding_task_update(request, legacy_id: int, pratica_id: int, task_id: int):
    if not _offboarding_is_admin(request):
        messages.error(request, "Non hai i permessi per aggiornare la pratica offboarding.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    task = get_object_or_404(
        OffboardingTask.objects.select_related("pratica"),
        pk=task_id,
        pratica_id=pratica_id,
        pratica__legacy_anagrafica_id=legacy_id,
        pratica__stato__in=OffboardingPratica.STATI_APERTI,
    )
    stato = (request.POST.get("stato") or "").strip()
    valid_stati = {choice[0] for choice in OffboardingTask.STATO_CHOICES}
    if stato not in valid_stati:
        messages.error(request, "Stato task offboarding non valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    from django.utils import timezone

    before = task.stato
    task.stato = stato
    task.note = (request.POST.get("note") or "").strip()[:1000]
    if stato in (OffboardingTask.STATO_COMPLETATO, OffboardingTask.STATO_ECCEZIONE):
        task.completed_at = timezone.now()
        task.completed_by = request.user
    else:
        task.completed_at = None
        task.completed_by = None
    task.save(update_fields=["stato", "note", "completed_at", "completed_by", "updated_at"])

    task.pratica.updated_by = request.user
    task.pratica.save(update_fields=["updated_by", "updated_at"])
    _helpers._audit_safe(request, "DIPENDENTE_OFFBOARDING_TASK_UPDATE", "anagrafica", {
        "pratica_id": pratica_id,
        "task_id": task_id,
        "legacy_anagrafica_id": legacy_id,
        "task_codice": task.codice,
        "stato_precedente": before,
        "stato_nuovo": task.stato,
        "note": task.note,
    })
    messages.success(request, f"Task offboarding aggiornato: {task.titolo}.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_offboarding_chiudi(request, legacy_id: int, pratica_id: int):
    if not _offboarding_is_admin(request):
        messages.error(request, "Non hai i permessi per chiudere la pratica offboarding.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    pratica = get_object_or_404(
        OffboardingPratica.objects.prefetch_related("tasks"),
        pk=pratica_id,
        legacy_anagrafica_id=legacy_id,
        stato__in=OffboardingPratica.STATI_APERTI,
    )
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    tasks = list(pratica.tasks.all())
    pending = [task for task in tasks if task.stato == OffboardingTask.STATO_DA_FARE]
    if pending:
        messages.warning(request, "Completa o marca come eccezione tutti i task prima di chiudere il rapporto.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    from django.db import transaction
    from django.utils import timezone

    oggi = timezone.localdate()
    data_cessazione = pratica.data_cessazione_prevista
    if data_cessazione > oggi:
        messages.warning(
            request,
            "La data cessazione prevista e futura: puoi completare i task, ma la chiusura effettiva va fatta alla data corretta.",
        )
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    old_utente_id = pratica.utente_id_pre_offboarding or (_int_or_none(dip.get("utente_id")) or None)
    try:
        with transaction.atomic():
            aziendale, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
                legacy_anagrafica_id=legacy_id
            )
            old_data_cessazione = aziendale.data_cessazione
            aziendale.data_cessazione = data_cessazione
            update_fields = ["data_cessazione", "updated_by", "updated_at"]
            if old_utente_id and aziendale.utente_id_pre_offboarding != old_utente_id:
                aziendale.utente_id_pre_offboarding = old_utente_id
                update_fields.append("utente_id_pre_offboarding")
            aziendale.updated_by = request.user
            aziendale.save(update_fields=update_fields)

            upsert_anagrafica_dipendente(
                row_id=legacy_id,
                aliasusername=dip.get("aliasusername") or "",
                nome=dip.get("nome") or "",
                cognome=dip.get("cognome") or "",
                reparto=dip.get("reparto") or "",
                mansione=dip.get("mansione") or "",
                ruolo=dip.get("ruolo") or "",
                matricola=dip.get("matricola") or "",
                email=dip.get("email") or "",
                email_notifica=dip.get("email_notifica") or "",
                attivo=False,
                detach_account=True,
            )

            has_exceptions = any(task.stato == OffboardingTask.STATO_ECCEZIONE for task in tasks)
            pratica.stato = (
                OffboardingPratica.STATO_CHIUSA_CON_ECCEZIONI
                if has_exceptions else OffboardingPratica.STATO_CHIUSA
            )
            pratica.closed_at = timezone.now()
            pratica.closed_by = request.user
            pratica.updated_by = request.user
            pratica.save(update_fields=["stato", "closed_at", "closed_by", "updated_by", "updated_at"])

        _helpers._audit_safe(request, "DIPENDENTE_OFFBOARDING_CHIUSO", "anagrafica", {
            "pratica_id": pratica.id,
            "legacy_anagrafica_id": legacy_id,
            "data_cessazione": data_cessazione.isoformat(),
            "data_cessazione_precedente": old_data_cessazione.isoformat() if old_data_cessazione else "",
            "legacy_attivo": False,
            "account_scollegato": True,
            "utente_id_pre_offboarding": old_utente_id,
            "stato_pratica": pratica.stato,
            "task_totali": len(tasks),
            "task_eccezioni": sum(1 for task in tasks if task.stato == OffboardingTask.STATO_ECCEZIONE),
        })
        messages.success(
            request,
            f"Pratica offboarding chiusa: dipendente cessato dal {data_cessazione:%d-%m-%Y}, "
            "non piu in forza e account scollegato.",
        )
    except Exception:
        logger.exception("Errore chiusura pratica offboarding dipendente %s", legacy_id)
        messages.error(request, "Errore durante la chiusura della pratica offboarding.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_rimetti_in_forza(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per rimettere in forza il dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    try:
        with transaction.atomic():
            aziendale = DipendenteAnagraficaAziendale.objects.filter(
                legacy_anagrafica_id=legacy_id
            ).first()
            old_data_cessazione = aziendale.data_cessazione if aziendale else None
            account_user, account_match = _resolve_account_portale_dipendente(dip, aziendale)
            account_id = int(account_user.id) if account_user else None
            if aziendale and old_data_cessazione:
                aziendale.data_cessazione = None
                aziendale.updated_by = request.user
                update_fields = ["data_cessazione", "updated_by", "updated_at"]
                if account_id and aziendale.utente_id_pre_offboarding:
                    aziendale.utente_id_pre_offboarding = None
                    update_fields.append("utente_id_pre_offboarding")
                aziendale.save(update_fields=update_fields)

            upsert_anagrafica_dipendente(
                row_id=legacy_id,
                aliasusername=dip.get("aliasusername") or "",
                nome=dip.get("nome") or "",
                cognome=dip.get("cognome") or "",
                reparto=dip.get("reparto") or "",
                mansione=dip.get("mansione") or "",
                ruolo=dip.get("ruolo") or "",
                matricola=dip.get("matricola") or "",
                email=dip.get("email") or "",
                email_notifica=dip.get("email_notifica") or "",
                attivo=True,
                utente_id=account_id,
                detach_account=False,
            )

        _helpers._audit_safe(
            request,
            "DIPENDENTE_RIMESSO_IN_FORZA",
            "anagrafica",
            {
                "legacy_anagrafica_id": legacy_id,
                "data_cessazione_precedente": old_data_cessazione.isoformat() if old_data_cessazione else "",
                "legacy_attivo": True,
                "account_ricollegato": bool(account_id),
                "account_legacy_user_id": account_id,
                "account_match": account_match,
            },
        )

        if old_data_cessazione:
            if account_id:
                messages.success(
                    request,
                    "Dipendente rimesso in forza: data cessazione rimossa, stato legacy riattivato "
                    "e account portale ricollegato automaticamente.",
                )
            else:
                messages.warning(
                    request,
                    "Dipendente rimesso in forza: data cessazione rimossa e stato legacy riattivato. "
                    "Non ho trovato un account portale univoco da ricollegare automaticamente.",
                )
        else:
            messages.success(request, "Dipendente gia in forza: stato legacy confermato attivo.")
    except Exception:
        logger.exception("Errore rimessa in forza dipendente %s", legacy_id)
        messages.error(request, "Errore durante la rimessa in forza del dipendente.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_qualifica_add(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per aggiungere qualifiche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    tipo_id = int(request.POST.get("tipo_id") or 0)
    tipo = get_object_or_404(TipoQualifica, pk=tipo_id, is_active=True)

    data_cons_raw = (request.POST.get("data_conseguimento") or "").strip()
    data_scad_raw = (request.POST.get("data_scadenza") or "").strip()

    from datetime import date, timedelta
    data_conseguimento = None
    data_scadenza = None

    if data_cons_raw:
        try:
            data_conseguimento = date.fromisoformat(data_cons_raw)
        except ValueError:
            pass

    if data_scad_raw:
        try:
            data_scadenza = date.fromisoformat(data_scad_raw)
        except ValueError:
            pass
    elif tipo.durata_mesi > 0 and data_conseguimento:
        # Auto-calcola scadenza
        from dateutil.relativedelta import relativedelta
        try:
            data_scadenza = data_conseguimento + relativedelta(months=tipo.durata_mesi)
        except Exception:
            data_scadenza = data_conseguimento + timedelta(days=tipo.durata_mesi * 30)

    note = (request.POST.get("note") or "").strip()[:255]
    numero = (request.POST.get("numero") or "").strip()[:100]
    livello = (request.POST.get("livello") or "").strip()[:80]
    ente = (request.POST.get("ente") or "").strip()[:200]

    # Evidenza documentale opzionale (storage privato). Validazione estensione/dimensione.
    documento = request.FILES.get("documento")
    documento_nome = None
    if documento:
        from pathlib import Path as _Path
        allowed = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
        suffix = _Path(documento.name or "").suffix.lower()
        if suffix not in allowed:
            messages.error(request, "Formato evidenza non ammesso (usa PDF o immagine).")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        if documento.size > DOCUMENT_MAX_BYTES:
            messages.error(request, f"Evidenza troppo grande (max {DOCUMENT_MAX_MB} MB).")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        documento_nome = documento.name

    _, created = _helpers._upsert_dipendente_qualifica(
        legacy_id, tipo, data_conseguimento, data_scadenza,
        note=note, user=request.user,
        numero=numero, livello=livello, ente=ente,
        documento=documento or None, documento_nome=documento_nome,
    )
    messages.success(
        request,
        f'Qualifica "{tipo.nome}" {"aggiunta" if created else "aggiornata (rinnovo)"}.',
    )
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_qualifica_delete(request, legacy_id: int, q_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per rimuovere qualifiche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    qualifica = get_object_or_404(DipendenteQualifica, pk=q_id, legacy_anagrafica_id=legacy_id)
    nome = qualifica.tipo.nome
    qualifica.delete()
    messages.success(request, f'Qualifica "{nome}" rimossa.')
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
def dipendente_qualifica_evidenza(request, legacy_id: int, q_id: int):
    """Serve l'evidenza documentale di una qualifica da storage privato (fuori
    webroot). ACL: admin legacy / superuser / HR (può contenere dati personali)."""
    legacy_user = get_legacy_user(request.user)
    if not (_helpers._is_anagrafica_admin(request) or _helpers._check_hr_permission(request)):
        return HttpResponse(status=403)
    q = get_object_or_404(DipendenteQualifica, pk=q_id, legacy_anagrafica_id=legacy_id)
    if not q.documento:
        return HttpResponse("Evidenza non disponibile.", status=404)
    try:
        from core.audit import log_action
        log_action(
            request, "QUALIFICA_EVIDENZA_DOWNLOAD", "anagrafica",
            {"qualifica_id": q.pk, "tipo": q.tipo.nome, "legacy_id": legacy_id},
        )
    except Exception:
        logger.warning("Audit QUALIFICA_EVIDENZA_DOWNLOAD fallito", exc_info=True)
    from django.http import FileResponse
    try:
        fh = q.documento.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    return FileResponse(
        fh, as_attachment=True,
        filename=q.documento_nome_originale or f"qualifica_{q.pk}.bin",
    )


@login_required
def dipendente_qualifica_storico_evidenza(request, legacy_id: int, q_id: int, storico_id: int):
    """Serve l'evidenza documentale storicizzata di un rinnovo (storage privato).
    ACL: admin legacy / superuser / HR (come l'evidenza corrente)."""
    legacy_user = get_legacy_user(request.user)
    if not (_helpers._is_anagrafica_admin(request) or _helpers._check_hr_permission(request)):
        return HttpResponse(status=403)
    from anagrafica.models import DipendenteQualificaStorico
    s = get_object_or_404(
        DipendenteQualificaStorico, pk=storico_id,
        qualifica_id=q_id, qualifica__legacy_anagrafica_id=legacy_id,
    )
    if not s.documento:
        return HttpResponse("Evidenza non disponibile.", status=404)
    try:
        from core.audit import log_action
        log_action(
            request, "QUALIFICA_STORICO_EVIDENZA_DOWNLOAD", "anagrafica",
            {"storico_id": s.pk, "qualifica_id": q_id, "legacy_id": legacy_id},
        )
    except Exception:
        logger.warning("Audit QUALIFICA_STORICO_EVIDENZA_DOWNLOAD fallito", exc_info=True)
    from django.http import FileResponse
    try:
        fh = s.documento.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    return FileResponse(
        fh, as_attachment=True,
        filename=s.documento_nome_originale or f"qualifica_storico_{s.pk}.bin",
    )


@login_required
@require_POST
def dipendente_qualifica_verifica(request, legacy_id: int, q_id: int):
    """Toggle del flag «verificata» (controllo HR dell'evidenza). ACL: admin/HR."""
    legacy_user = get_legacy_user(request.user)
    if not (_helpers._is_anagrafica_admin(request) or _helpers._check_hr_permission(request)):
        messages.error(request, "Permessi insufficienti per verificare la qualifica.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    q = get_object_or_404(DipendenteQualifica, pk=q_id, legacy_anagrafica_id=legacy_id)
    if q.verificata:
        q.verificata = False
        q.verificata_da = None
        q.verificata_il = None
        msg = f'Verifica rimossa da "{q.tipo.nome}".'
    else:
        from django.utils import timezone as _tz
        q.verificata = True
        q.verificata_da = request.user
        q.verificata_il = _tz.now()
        msg = f'Qualifica "{q.tipo.nome}" contrassegnata come verificata.'
    q.save(update_fields=["verificata", "verificata_da", "verificata_il"])
    messages.success(request, msg)
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Anagrafica civile e aziendale — salvataggio
# ---------------------------------------------------------------------------

@login_required
@require_POST
def dipendente_anagrafica_civile_save(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare l'anagrafica civile.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    instance, _ = DipendenteAnagraficaCivile.objects.get_or_create(
        legacy_anagrafica_id=legacy_id
    )
    form = AnagraficaCivileForm(request.POST, request.FILES, instance=instance)
    formset = FiglioACaricoFormSet(request.POST, instance=instance, prefix="figli")
    if form.is_valid() and formset.is_valid():
        obj = form.save(commit=False)
        obj.legacy_anagrafica_id = legacy_id
        obj.updated_by = request.user
        obj.save()
        formset.instance = obj
        formset.save()
        # Allinea il flag al numero effettivo di figli registrati.
        ha_figli = obj.figli.exists()
        if obj.figli_a_carico != ha_figli:
            obj.figli_a_carico = ha_figli
            obj.save(update_fields=["figli_a_carico"])
        messages.success(request, "Anagrafica civile salvata.")
    else:
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(request, f"{field}: {err}")
        for sub in formset:
            for field, errs in sub.errors.items():
                for err in errs:
                    messages.error(request, f"Figli — {field}: {err}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_anagrafica_aziendale_save(request, legacy_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare l'anagrafica aziendale.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    instance, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id
    )

    # Reparto, area aziendale e ruolo aziendale non passano più da qui: li governa
    # lo spostamento organizzativo (DipendenteAssegnazione), che li assegna insieme
    # con una sola decorrenza. Questo form copre il resto dei dati aziendali.
    form = AnagraficaAziendaleForm(request.POST, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.legacy_anagrafica_id = legacy_id
        obj.updated_by = request.user
        obj.save()
        messages.success(request, "Anagrafica aziendale salvata.")
    else:
        for field, errs in form.errors.items():
            for err in errs:
                messages.error(request, f"{field}: {err}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
def dipendente_retribuzioni(request, legacy_id: int):
    """Storico completo voci retributive per un dipendente (accesso HR)."""
    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    civile_retr = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    _retr_q = Q(legacy_anagrafica_id=legacy_id)
    if civile_retr and civile_retr.codice_fiscale:
        _retr_q |= Q(tax_code=civile_retr.codice_fiscale.strip().upper())
    voci_all = list(
        VoceRetributiva.objects.filter(_retr_q)
        .select_related("importazione")
        .order_by("-data_competenza", "-importazione__data_importazione", "categoria", "pay_item_key")
    )

    # Merge: una sola importazione CSV per mese (la più recente) + voci manuali del mese
    # (le voci manuali fanno override delle voci CSV con lo stesso pay_item_key).
    _by_month: dict = {}
    for v in voci_all:
        key = v.data_competenza
        if key not in _by_month:
            _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
        if v.manuale:
            _by_month[key]["manuale_voci"].append(v)
        else:
            if _by_month[key]["csv_imp"] is None:
                _by_month[key]["csv_imp"] = v.importazione
            if v.importazione_id == _by_month[key]["csv_imp"].id:
                _by_month[key]["csv_voci"].append(v)

    # Costruisco mese -> {pay_item_key: voce effettiva (manuale prevale su CSV)}
    _mesi_dict: dict = {}
    for _date, entry in _by_month.items():
        _manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
        _voci = [v for v in entry["csv_voci"] if v.pay_item_key not in _manuale_keys] + entry["manuale_voci"]
        _mesi_dict[_date] = {v.pay_item_key: v for v in _voci}

    # Ordinamento colonne pivot: per categoria (fisso, variabile, altro, totale)
    # e all'interno per ordine di prima apparizione cronologica (rispecchia l'ordine CSV originale).
    _CAT_ORDER = {"fisso": 0, "variabile": 1, "altro": 2, "totale": 3}
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    _key_meta: dict = {}
    # Iterazione cronologica ascendente per registrare prima apparizione
    _voci_for_meta = sorted(voci_all, key=lambda v: (v.data_competenza, v.categoria, v.pay_item_key))
    _seq = 0
    for v in _voci_for_meta:
        if v.pay_item_key not in _key_meta:
            _key_meta[v.pay_item_key] = {
                "key": v.pay_item_key,
                "label": v.pay_item,
                "categoria": v.categoria,
                "_seq": _seq,
            }
            _seq += 1

    def _col_sort(m):
        cat = _CAT_ORDER.get(m["categoria"], 99)
        sub = _TOTALI_SORT.get(m["key"], 50) if m["categoria"] == "totale" else m["_seq"]
        return (cat, sub)

    colonne = sorted(_key_meta.values(), key=_col_sort)

    # Costruzione righe pivot: per ogni mese cronologico ASC calcolo le celle e il flag changed
    # (confronto con il mese precedente per cui esiste un valore nella stessa colonna).
    _mesi_asc = sorted(_mesi_dict.keys())
    _prev_value_by_key: dict = {}  # pay_item_key -> ultimo importo visto
    _rows_by_date: dict = {}
    for _date in _mesi_asc:
        voci_map = _mesi_dict[_date]
        celle = []
        for col in colonne:
            v = voci_map.get(col["key"])
            importo = v.importo if v else None
            prev = _prev_value_by_key.get(col["key"])
            # Cella variata se il valore differisce dal mese precedente
            # (None vs valore = variazione; entrambi None = invariato).
            changed = (importo != prev) and not (importo is None and prev is None)
            # Aggiorno il "valore precedente" solo se in questo mese c'è un valore
            if importo is not None:
                _prev_value_by_key[col["key"]] = importo
            celle.append({
                "voce": v,
                "importo": importo,
                "changed": changed,
                "manuale": bool(v and v.manuale),
                "categoria": col["categoria"],
                "is_totale": col["categoria"] == "totale",
                "is_ral": col["key"] == "ral",
            })
        _rows_by_date[_date] = {
            "data": _date,
            "celle": celle,
            "importazione": _by_month[_date]["csv_imp"],
            "n_manuale": len(_by_month[_date]["manuale_voci"]),
            "n_changed": sum(1 for c in celle if c["changed"] and c["importo"] is not None),
        }

    # Raggruppo per anno (anno decrescente, mesi decrescenti dentro l'anno)
    _today = django_timezone.localdate()
    _anni_default_aperti = {_today.year, _today.year - 1}
    _by_year: dict = {}
    for _date in _mesi_asc:
        _by_year.setdefault(_date.year, []).append(_rows_by_date[_date])

    anni = []
    for anno in sorted(_by_year.keys(), reverse=True):
        mesi_desc = list(reversed(_by_year[anno]))
        anni.append({
            "anno": anno,
            "mesi": mesi_desc,
            "n_mesi": len(mesi_desc),
            "n_changed": sum(m["n_changed"] for m in mesi_desc),
            "open": anno in _anni_default_aperti,
        })

    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)

    return render(request, "anagrafica/pages/dipendente_retribuzioni.html", {
        "dip": dip,
        "legacy_id": legacy_id,
        "colonne": colonne,
        "anni": anni,
        "n_mesi": len(_mesi_asc),
        "n_colonne": len(colonne),
        "can_hr": can_hr,
        "is_admin": is_admin,
        "tax_code_dipendente": civile_retr.codice_fiscale.strip().upper() if civile_retr and civile_retr.codice_fiscale else "",
        "categorie_voce": VoceRetributiva.CATEGORIA_CHOICES,
    })


@login_required
def dipendente_retribuzioni_export_xlsx(request, legacy_id: int):
    """Esporta in Excel lo storico retributivo del dipendente come tabella pivot
    (righe = mesi cronologici desc, colonne = pay_item per categoria, celle = importi
    con highlight delle variazioni vs mese precedente)."""
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    from core.excel_export import write_cell

    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    _q = Q(legacy_anagrafica_id=legacy_id)
    if civile and civile.codice_fiscale:
        _q |= Q(tax_code=civile.codice_fiscale.strip().upper())
    voci_all = list(
        VoceRetributiva.objects.filter(_q)
        .order_by("-data_competenza", "categoria", "pay_item_key")
    )

    # Merge manuali/CSV identico alla view principale
    _by_month: dict = {}
    for v in voci_all:
        key = v.data_competenza
        if key not in _by_month:
            _by_month[key] = {"csv_imp": None, "csv_voci": [], "manuale_voci": []}
        if v.manuale:
            _by_month[key]["manuale_voci"].append(v)
        else:
            if _by_month[key]["csv_imp"] is None:
                _by_month[key]["csv_imp"] = v.importazione
            if v.importazione_id == _by_month[key]["csv_imp"].id:
                _by_month[key]["csv_voci"].append(v)

    _mesi_dict: dict = {}
    for _date, entry in _by_month.items():
        _manuale_keys = {v.pay_item_key for v in entry["manuale_voci"]}
        _voci = [v for v in entry["csv_voci"] if v.pay_item_key not in _manuale_keys] + entry["manuale_voci"]
        _mesi_dict[_date] = {v.pay_item_key: v for v in _voci}

    _CAT_ORDER = {"fisso": 0, "variabile": 1, "altro": 2, "totale": 3}
    _TOTALI_SORT = {"retribuzione di fatto": 0, "totale elementi variabili": 1, "rml": 2, "ral": 3}
    _key_meta: dict = {}
    _seq = 0
    for v in sorted(voci_all, key=lambda v: (v.data_competenza, v.categoria, v.pay_item_key)):
        if v.pay_item_key not in _key_meta:
            _key_meta[v.pay_item_key] = {
                "key": v.pay_item_key, "label": v.pay_item,
                "categoria": v.categoria, "_seq": _seq,
            }
            _seq += 1

    def _col_sort(m):
        cat = _CAT_ORDER.get(m["categoria"], 99)
        sub = _TOTALI_SORT.get(m["key"], 50) if m["categoria"] == "totale" else m["_seq"]
        return (cat, sub)

    colonne = sorted(_key_meta.values(), key=_col_sort)
    _mesi_asc = sorted(_mesi_dict.keys())

    # Workbook + foglio
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Storico retributivo"

    # Stili
    thin = Side(border_style="thin", color="E2E8F0")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill_by_cat = {
        "fisso":     PatternFill(fill_type="solid", fgColor="F1F5F9"),
        "variabile": PatternFill(fill_type="solid", fgColor="FFF7ED"),
        "altro":     PatternFill(fill_type="solid", fgColor="F5F3FF"),
        "totale":    PatternFill(fill_type="solid", fgColor="ECFDF5"),
    }
    font_header = Font(bold=True, name="Calibri", size=10, color="1E293B")
    font_date = Font(bold=True, name="Calibri", size=10)
    font_normal = Font(name="Calibri", size=10)
    font_totale = Font(bold=True, name="Calibri", size=10, color="065F46")
    fill_changed = PatternFill(fill_type="solid", fgColor="DBEAFE")
    fill_changed_totale = PatternFill(fill_type="solid", fgColor="BBF7D0")
    fill_manuale_marker = PatternFill(fill_type="solid", fgColor="EDE9FE")

    # Intestazione (riga 1)
    write_cell(ws, 1, 1, "Data retribuzione").font = font_header
    ws.cell(row=1, column=1).fill = PatternFill(fill_type="solid", fgColor="F8FAFC")
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")
    ws.cell(row=1, column=1).border = border_all
    for ci, col in enumerate(colonne, start=2):
        c = write_cell(ws, 1, ci, col["label"])
        c.font = font_header
        c.fill = fill_by_cat.get(col["categoria"], PatternFill(fill_type="solid", fgColor="F8FAFC"))
        c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        c.border = border_all

    # Righe: mesi in ordine cronologico discendente
    _prev_value_by_key: dict = {}
    # Per il calcolo "changed" itero ASC ma scrivo le righe DESC: costruisco prima la matrice
    _cell_data_by_date: dict = {}  # date -> list of (importo, changed, manuale)
    for _date in _mesi_asc:
        voci_map = _mesi_dict[_date]
        row_cells = []
        for col in colonne:
            v = voci_map.get(col["key"])
            importo = v.importo if v else None
            prev = _prev_value_by_key.get(col["key"])
            changed = (importo != prev) and not (importo is None and prev is None)
            if importo is not None:
                _prev_value_by_key[col["key"]] = importo
            row_cells.append((importo, changed, bool(v and v.manuale)))
        _cell_data_by_date[_date] = row_cells

    for ri, _date in enumerate(reversed(_mesi_asc), start=2):
        c_date = write_cell(ws, ri, 1, _date)  # date: resta tipizzata (non stringa)
        c_date.number_format = "DD/MM/YYYY"
        c_date.font = font_date
        c_date.alignment = Alignment(horizontal="left", vertical="center")
        c_date.border = border_all
        for ci, (col, (importo, changed, manuale)) in enumerate(zip(colonne, _cell_data_by_date[_date]), start=2):
            cell = ws.cell(row=ri, column=ci)
            if importo is not None:
                cell.value = float(importo)
                cell.number_format = '#,##0.00 "€"'
            cell.font = font_totale if col["categoria"] == "totale" else font_normal
            cell.alignment = Alignment(horizontal="right", vertical="center")
            cell.border = border_all
            if changed and importo is not None:
                cell.fill = fill_changed_totale if col["categoria"] == "totale" else fill_changed
            elif manuale:
                cell.fill = fill_manuale_marker

    # Freeze pane: prima riga + prima colonna
    ws.freeze_panes = "B2"

    # Auto-width approssimativo (label + padding)
    ws.column_dimensions["A"].width = 18
    for ci, col in enumerate(colonne, start=2):
        ws.column_dimensions[get_column_letter(ci)].width = max(14, min(28, len(col["label"]) + 4))

    _cognome = str(dip.get("cognome") or "").strip()
    _nome = str(dip.get("nome") or "").strip()

    # Riga riepilogo finale
    summary_row = len(_mesi_asc) + 3
    write_cell(
        ws, summary_row, 1,
        f"Dipendente: {naming.nome_completo(_nome, _cognome)} — {len(_mesi_asc)} mesi · {len(colonne)} voci",
    ).font = Font(italic=True, size=9, color="64748B")

    # Output
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    today = django_timezone.localdate().strftime("%Y%m%d")
    safe_name = "".join(ch for ch in f"{_nome}_{_cognome}" if ch.isalnum() or ch in ("_", "-")).strip("_") or str(legacy_id)
    filename = f"storico_retributivo_{safe_name}_{today}.xlsx"

    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------------------------------------------------------------------------
# Voci retributive — data-entry manuale (HR/admin)
# ---------------------------------------------------------------------------

def _get_or_create_import_manuale(data_competenza, user) -> ImportazioneRetributiva:
    """Recupera o crea l'unica `ImportazioneRetributiva` manuale per quel mese di competenza."""
    imp, created = ImportazioneRetributiva.objects.get_or_create(
        origine=ImportazioneRetributiva.ORIGINE_MANUALE,
        data_competenza=data_competenza,
        defaults={
            "importato_da": user,
            "file_nome": "(inserimento manuale)",
            "note": "Container voci retributive inserite manualmente",
        },
    )
    return imp


def _parse_data_competenza(raw: str):
    """Accetta 'YYYY-MM' o 'YYYY-MM-DD' e restituisce date(primo giorno mese)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 7:  # YYYY-MM
            return datetime.strptime(raw + "-01", "%Y-%m-%d").date()
        d = datetime.strptime(raw, "%Y-%m-%d").date()
        return d.replace(day=1)
    except ValueError:
        return None


def _parse_importo(raw: str):
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@login_required
@require_POST
def dipendente_retribuzione_voce_add(request, legacy_id: int):
    """Aggiunge una voce retributiva manuale (HR + admin)."""
    can_hr = _helpers._check_hr_permission(request)
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    data_comp = _parse_data_competenza(request.POST.get("data_competenza"))
    if not data_comp:
        messages.error(request, "Mese di competenza non valido.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    pay_item = (request.POST.get("pay_item") or "").strip()[:150]
    importo = _parse_importo(request.POST.get("importo"))
    if not pay_item or importo is None:
        messages.error(request, "Voce e importo sono obbligatori.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    categoria_raw = (request.POST.get("categoria") or "").strip().lower()
    valid_cats = {c for c, _ in VoceRetributiva.CATEGORIA_CHOICES}
    categoria = categoria_raw if categoria_raw in valid_cats else _classify_pay_item(pay_item.lower())

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tax_code = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""

    imp = _get_or_create_import_manuale(data_comp, request.user)
    VoceRetributiva.objects.create(
        importazione=imp,
        tax_code=tax_code,
        legacy_anagrafica_id=legacy_id,
        data_competenza=data_comp,
        pay_item=pay_item,
        pay_item_key=pay_item.lower(),
        categoria=categoria,
        importo=importo,
        manuale=True,
        note=(request.POST.get("note") or "").strip()[:300],
        updated_by=request.user,
    )
    imp.righe_ok = imp.voci.count()
    imp.save(update_fields=["righe_ok"])

    messages.success(request, f'Voce "{pay_item}" aggiunta per {data_comp.strftime("%B %Y")}.')
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_retribuzione_voce_edit(request, legacy_id: int, voce_id: int):
    """Modifica una voce retributiva (solo voci con flag manuale=True)."""
    can_hr = _helpers._check_hr_permission(request)
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    voce = get_object_or_404(VoceRetributiva, pk=voce_id)
    if not voce.manuale:
        messages.error(request, "Solo le voci inserite manualmente sono modificabili. Le voci da CSV vanno reimportate.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""
    if voce.legacy_anagrafica_id != legacy_id and (not tc or voce.tax_code != tc):
        messages.error(request, "Voce non appartenente a questo dipendente.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    pay_item = (request.POST.get("pay_item") or "").strip()[:150]
    importo = _parse_importo(request.POST.get("importo"))
    if not pay_item or importo is None:
        messages.error(request, "Voce e importo sono obbligatori.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    categoria_raw = (request.POST.get("categoria") or "").strip().lower()
    valid_cats = {c for c, _ in VoceRetributiva.CATEGORIA_CHOICES}
    categoria = categoria_raw if categoria_raw in valid_cats else _classify_pay_item(pay_item.lower())

    voce.pay_item = pay_item
    voce.pay_item_key = pay_item.lower()
    voce.importo = importo
    voce.categoria = categoria
    voce.note = (request.POST.get("note") or "").strip()[:300]
    voce.updated_by = request.user
    voce.save(update_fields=["pay_item", "pay_item_key", "importo", "categoria", "note", "updated_by", "updated_at"])

    messages.success(request, "Voce aggiornata.")
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_retribuzione_voce_delete(request, legacy_id: int, voce_id: int):
    """Elimina una voce retributiva (solo voci con flag manuale=True)."""
    can_hr = _helpers._check_hr_permission(request)
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not (can_hr or is_admin):
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    voce = get_object_or_404(VoceRetributiva, pk=voce_id)
    if not voce.manuale:
        messages.error(request, "Solo le voci inserite manualmente sono eliminabili.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""
    if voce.legacy_anagrafica_id != legacy_id and (not tc or voce.tax_code != tc):
        messages.error(request, "Voce non appartenente a questo dipendente.")
        return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)

    imp = voce.importazione
    voce.delete()
    # Se l'importazione manuale è rimasta senza voci, eliminala
    if imp.origine == ImportazioneRetributiva.ORIGINE_MANUALE and not imp.voci.exists():
        imp.delete()
    else:
        imp.righe_ok = imp.voci.count()
        imp.save(update_fields=["righe_ok"])

    messages.success(request, "Voce eliminata.")
    return redirect("anagrafica:dipendente_retribuzioni", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_contratto_add(request, legacy_id: int):
    """Aggiunge manualmente un record storico contrattuale."""
    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    di_raw = request.POST.get("data_inizio", "").strip()
    df_raw = request.POST.get("data_fine", "").strip()
    try:
        data_inizio = datetime.strptime(di_raw, "%Y-%m-%d").date()
        data_fine = datetime.strptime(df_raw, "%Y-%m-%d").date() if df_raw else None
    except ValueError:
        messages.error(request, "Formato data non valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    tax_code = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else ""

    # Auto-chiudi il record "in corso" se il nuovo inizia dopo
    _q_inc = Q(legacy_anagrafica_id=legacy_id)
    if tax_code:
        _q_inc |= Q(tax_code=tax_code)
    in_corso = (
        StoricoContratto.objects.filter(_q_inc, data_fine__isnull=True)
        .order_by("-data_inizio")
        .first()
    )
    if in_corso and in_corso.data_inizio < data_inizio:
        in_corso.data_fine = data_inizio
        in_corso.save(update_fields=["data_fine"])

    codice_liv = request.POST.get("codice_livello", "").strip().upper()
    # Auto-popola descrizione dal catalogo se non specificata manualmente
    desc_liv = request.POST.get("descrizione_livello", "").strip()
    if codice_liv and not desc_liv:
        _lc = LivelloContrattuale.objects.filter(codice=codice_liv).first()
        if _lc:
            desc_liv = _lc.descrizione

    StoricoContratto.objects.create(
        legacy_anagrafica_id=legacy_id,
        tax_code=tax_code,
        data_inizio=data_inizio,
        data_fine=data_fine,
        tipologia_contratto=request.POST.get("tipologia_contratto", "").strip(),
        codice_livello=codice_liv,
        descrizione_livello=desc_liv,
        qualifica_nome=request.POST.get("qualifica_nome", "").strip(),
        importato_da=request.user,
    )
    messages.success(request, "Record contrattuale aggiunto.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_contratto_delete(request, legacy_id: int, contratto_id: int):
    """Elimina un record storico contrattuale."""
    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto = get_object_or_404(StoricoContratto, pk=contratto_id)
    if contratto.legacy_anagrafica_id != legacy_id:
        civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
        tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else None
        if contratto.tax_code != tc:
            messages.error(request, "Record non appartenente a questo dipendente.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto.delete()
    messages.success(request, "Record contrattuale eliminato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_contratto_edit(request, legacy_id: int, contratto_id: int):
    """Aggiorna un record storico contrattuale esistente."""
    can_hr = _helpers._check_hr_permission(request)
    if not can_hr:
        messages.error(request, "Accesso riservato agli utenti HR.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    contratto = get_object_or_404(StoricoContratto, pk=contratto_id)
    if contratto.legacy_anagrafica_id != legacy_id:
        civile_obj = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
        tc = civile_obj.codice_fiscale.strip().upper() if civile_obj and civile_obj.codice_fiscale else None
        if contratto.tax_code != tc:
            messages.error(request, "Record non appartenente a questo dipendente.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    di_raw = request.POST.get("data_inizio", "").strip()
    df_raw = request.POST.get("data_fine", "").strip()
    try:
        data_inizio = datetime.strptime(di_raw, "%Y-%m-%d").date()
        data_fine = datetime.strptime(df_raw, "%Y-%m-%d").date() if df_raw else None
    except ValueError:
        messages.error(request, "Formato data non valido.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    codice_liv = request.POST.get("codice_livello", "").strip().upper()
    desc_liv = request.POST.get("descrizione_livello", "").strip()
    if codice_liv and not desc_liv:
        _lc = LivelloContrattuale.objects.filter(codice=codice_liv).first()
        if _lc:
            desc_liv = _lc.descrizione

    contratto.data_inizio = data_inizio
    contratto.data_fine = data_fine
    contratto.tipologia_contratto = request.POST.get("tipologia_contratto", "").strip()
    contratto.codice_livello = codice_liv
    contratto.descrizione_livello = desc_liv
    contratto.qualifica_nome = request.POST.get("qualifica_nome", "").strip()
    contratto.save()
    messages.success(request, "Record contrattuale aggiornato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Report dipendenti — filtri avanzati + export CSV
# ---------------------------------------------------------------------------

@login_required
def dipendenti_report(request):
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:dipendenti_list")

    q = request.GET.get("q", "").strip()
    reparto_filter = request.GET.get("reparto", "").strip()
    area_filter = request.GET.get("area", "").strip()
    contratto_filter = request.GET.get("tipologia_contratto", "").strip()
    consenso_filter = request.GET.get("consenso_privacy", "").strip()
    cat_protetta_filter = request.GET.get("categoria_protetta", "").strip()

    # Parte da tutti i dipendenti legacy
    all_rows = fetch_anagrafica_rows(deduplicate=True)

    # Filtro per testo su nome/cognome
    if q:
        q_norm = q.casefold()
        all_rows = [
            row for row in all_rows
            if any(
                q_norm in str(row.get(k) or "").casefold()
                for k in ("nome", "cognome", "aliasusername", "matricola")
            )
        ]

    # Reparto/area canonici: sovrascrive row["reparto"] col Reparto canonico
    # (fallback al testo legacy per i non ancora mappati) e valorizza
    # row["area_aziendale_nome"]. Da qui il filtro reparto è sul canonico.
    from anagrafica.services.reparto_canonico import enrich_rows_reparto_canonico
    enrich_rows_reparto_canonico(all_rows)

    # Filtro per reparto (canonico)
    if reparto_filter:
        all_rows = [
            row for row in all_rows
            if str(row.get("reparto") or "").strip().casefold() == reparto_filter.casefold()
        ]

    # Filtri su campi Django: area aziendale canonica e tipologia_contratto
    django_filter_ids: set[int] | None = None
    az_qs = DipendenteAnagraficaAziendale.objects.all()
    if area_filter:
        az_qs = az_qs.filter(area_aziendale__nome__iexact=area_filter)
    if contratto_filter:
        az_qs = az_qs.filter(tipologia_contratto=contratto_filter)
    if consenso_filter == "si":
        az_qs = az_qs.filter(consenso_privacy=True)
    elif consenso_filter == "no":
        az_qs = az_qs.filter(consenso_privacy=False)
    if area_filter or contratto_filter or consenso_filter:
        django_filter_ids = set(az_qs.values_list("legacy_anagrafica_id", flat=True))

    # Filtro categoria protetta (da DipendenteAnagraficaCivile)
    civ_filter_ids: set[int] | None = None
    if cat_protetta_filter == "si":
        civ_filter_ids = set(
            DipendenteAnagraficaCivile.objects.filter(categoria_protetta=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    elif cat_protetta_filter == "no":
        civ_filter_ids = set(
            DipendenteAnagraficaCivile.objects.filter(categoria_protetta=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )

    if django_filter_ids is not None:
        all_rows = [row for row in all_rows if int(row.get("id") or 0) in django_filter_ids]
    if civ_filter_ids is not None:
        all_rows = [row for row in all_rows if int(row.get("id") or 0) in civ_filter_ids]

    # Arricchisce ogni riga con dati Django
    legacy_ids = [int(row.get("id") or 0) for row in all_rows if int(row.get("id") or 0)]
    az_map = {
        obj.legacy_anagrafica_id: obj
        for obj in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=legacy_ids)
    }
    civ_map = {
        obj.legacy_anagrafica_id: obj
        for obj in DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id__in=legacy_ids)
    }
    for row in all_rows:
        lid = int(row.get("id") or 0)
        az = az_map.get(lid)
        row["az"] = az
        row["civ"] = civ_map.get(lid)

    # Export CSV (no campi sensibili)
    fmt = request.GET.get("format", "").strip()
    if fmt == "csv":
        from django.http import HttpResponse
        response = HttpResponse(content_type=CSV_CONTENT_TYPE)
        response["Content-Disposition"] = 'attachment; filename="dipendenti_report.csv"'
        response.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(response, delimiter=";")
        writer.writerow([
            "ID", "Cognome", "Nome", "Matricola", "Reparto",
            "Area aziendale", "Ruolo aziendale", "Tipologia contratto",
            "Livello inquadramento", "Data prima assunzione",
            "Consenso privacy", "Email aziendale", "Telefono aziendale",
        ])
        for row in all_rows:
            az = row.get("az")
            writer.writerow([
                row.get("id", ""),
                row.get("cognome", ""),
                row.get("nome", ""),
                row.get("matricola", ""),
                row.get("reparto", ""),
                row.get("area_aziendale_nome", "") or "",
                getattr(az, "ruolo_aziendale", "") or "",
                getattr(az, "get_tipologia_contratto_display", lambda: "")() if az else "",
                getattr(az, "livello_inquadramento", "") or "",
                getattr(az, "data_prima_assunzione", "") or "",
                "Sì" if getattr(az, "consenso_privacy", False) else "No",
                getattr(az, "email_aziendale", "") or "",
                getattr(az, "telefono_aziendale", "") or "",
            ])
        return response

    # Filtri dai cataloghi canonici (non più dal testo legacy).
    reparti_list = list(
        Reparto.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True)
    )
    _helpers.aree_list = list(
        AreaAziendale.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True)
    )

    paginator = Paginator(all_rows, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/dipendenti_report.html", {
        "page_obj": page,
        "q": q,
        "reparto": reparto_filter,
        "area": area_filter,
        "tipologia_contratto": contratto_filter,
        "consenso_privacy": consenso_filter,
        "categoria_protetta": cat_protetta_filter,
        "reparti": reparti_list,
        "aree": _helpers.aree_list,
        "contratto_choices": DipendenteAnagraficaAziendale.CONTRATTO_CHOICES,
        "n_totale": len(all_rows),
    })


# ---------------------------------------------------------------------------
# Export tabellari (PDF/Excel) — endpoint unico parametrico
# ---------------------------------------------------------------------------

@login_required
def export_view(request, key: str):
    """Endpoint unico di export delle liste di anagrafica (PDF/Excel).

    La chiave identifica la ``ExportSpec`` (vedi `anagrafica/exports.py`); il gate
    ACL della lista di origine è applicato dalla spec, l'audit dall'helper.
    """
    from anagrafica.exports import EXPORT_SPECS, build_export_response

    spec = EXPORT_SPECS.get(key)
    if spec is None:
        raise Http404("Export non disponibile.")
    if not spec.permission(request):
        return HttpResponseForbidden("Permessi insufficienti.")
    return build_export_response(
        request,
        key,
        request.GET.get("format", "xlsx"),
        request.GET.get("scope", "filtered"),
    )


def _responsabile_di(reparto_nome: str, area=None) -> int | None:
    """Legacy id del responsabile per una coppia (reparto, area aziendale).

    Stessa gerarchia del sync — il responsabile dell'area vince sul caporeparto —
    ma calcolata su valori arbitrari invece che sul dipendente: serve alle card
    storiche, dove il responsabile è quello del reparto di allora.
    """
    if area is not None and area.reparto_id:
        from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo
        return resolve_responsabile_effettivo(area=area, reparto=area.reparto)
    if not reparto_nome:
        return None
    rep = Reparto.objects.filter(nome__iexact=reparto_nome).first()
    return rep.caporeparto_legacy_id if rep else None


# Sentinella per `_sync_aziendale_from_reparto`: `None` significa "togli l'area",
# l'assenza del parametro significa "non mi esprimo". Senza questa distinzione i
# due casi collassano e ogni salvataggio di reparto scollega il dipendente.
AREA_NON_SPECIFICATA = object()


def _sync_aziendale_from_reparto(
    legacy_id: int, reparto_nome: str, *, area_aziendale_id=AREA_NON_SPECIFICATA, saved_by,
    data_decorrenza=None, area_precedente: str | None = None,
    area_aziendale_precedente: str | None = None,
) -> None:
    """Aggiorna caporeparto_legacy_id e area_aziendale su DipendenteAnagraficaAziendale
    in base al Reparto assegnato. Chiamato ogni volta che il reparto (o l'area) cambia.

    L'Area aziendale deve appartenere al Reparto risolto, altrimenti viene azzerata
    silenziosamente (reparto cambiato altrove, reparto non trovato/disattivato, o area
    di un altro reparto) invece di bloccare il salvataggio. Non si richiede che l'area
    sia attiva: un'assegnazione a un'area nel frattempo disattivata resta valida, come
    già avviene per area/ruolo_aziendale (forms.py preserva il valore corrente anche
    se non più nel catalogo "attive").

    **Omettere `area_aziendale_id` non significa azzerare l'area.** Chi non passa il
    parametro (es. `report_reparti_orfani`, che rimappa solo il nome del reparto) sta
    dicendo "non mi esprimo": l'area attuale viene conservata se appartiene ancora al
    reparto risolto. Per toglierla davvero si passa `area_aziendale_id=None`, che è
    quello che fanno i form dove l'area è un campo scelto dall'utente. Prima della
    distinzione qualunque salvataggio che toccasse il reparto senza nominare l'area
    scollegava il dipendente, e i report che ragionano per reparto smettevano di
    vederlo (vedi `schede_sicurezza.reports.matrice_presa_visione`).

    Essendo l'unico punto che scrive `area` e `area_aziendale`, è anche il punto in cui
    si storicizzano i due periodi corrispondenti: chi chiama non deve registrarli.
    I valori precedenti si leggono dalla riga a DB, salvo che il chiamante li passi
    esplicitamente — necessario quando ha già salvato la nuova versione della riga
    (è il caso del form completo di anagrafica aziendale).
    """
    capo_id = None
    rep = None
    if reparto_nome:
        rep = Reparto.objects.filter(nome__iexact=reparto_nome, is_active=True).first()
        if rep:
            capo_id = rep.caporeparto_legacy_id

    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        defaults={"updated_by": saved_by},
    )

    # Chi non passa il parametro non sta chiedendo di togliere l'area: si riparte
    # da quella attuale, che sopravvive solo se appartiene ancora al reparto
    # risolto (il filtro qui sotto e' lo stesso per entrambi i casi).
    area_candidata_id = (
        az.area_aziendale_id if area_aziendale_id is AREA_NON_SPECIFICATA else area_aziendale_id
    )

    area_id_valido = None
    if area_candidata_id and rep is not None:
        area = AreaAziendale.objects.filter(pk=area_candidata_id, reparto_id=rep.id).first()
        if area is not None:
            area_id_valido = area.id
            # Responsabile effettivo: il responsabile dell'AREA aziendale vince
            # sul caporeparto del REPARTO quando differisce (fallback al capo
            # reparto se l'area non ha responsabile). Fonte unica nel service.
            from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo
            capo_id = resolve_responsabile_effettivo(area=area, reparto=rep)
    area_vecchia = area_precedente if area_precedente is not None else (az.area or "")
    area_az_vecchia = (
        area_aziendale_precedente if area_aziendale_precedente is not None
        else (az.area_aziendale.nome if az.area_aziendale_id else "")
    )
    # Nessuno è responsabile di sé stesso: un caporeparto che appartiene al
    # proprio reparto si ritroverebbe indicato come proprio responsabile nella
    # scheda e nelle card dell'assetto. Il suo riferimento superiore è semmai
    # nella gerarchia dei ruoli, non qui.
    if capo_id and int(capo_id) == int(legacy_id):
        capo_id = None

    az.area = reparto_nome
    az.caporeparto_legacy_id = capo_id
    az.area_aziendale_id = area_id_valido
    az.updated_by = saved_by
    az.save(update_fields=["area", "caporeparto_legacy_id", "area_aziendale", "updated_by", "updated_at"])

    _registra_cambiamento(
        legacy_id,
        DipendenteCambiamentoOrganizzativo.TIPO_AREA,
        area_vecchia, reparto_nome,
        saved_by,
        data_effetto=data_decorrenza,
    )
    _registra_cambiamento(
        legacy_id,
        DipendenteCambiamentoOrganizzativo.TIPO_AREA_AZIENDALE,
        area_az_vecchia,
        AreaAziendale.objects.filter(pk=area_id_valido).values_list("nome", flat=True).first() or "",
        saved_by,
        data_effetto=data_decorrenza,
    )


def _sostituisci_referto_visita(request, visita: VisitaMedica, referto_file, file_salvati: list):
    """Carica il nuovo referto principale SENZA distruggere il precedente.

    Il referto sostituito è un documento sanitario con la sua conservazione
    (``retention_until``): resta nel fascicolo, agganciato alla visita come
    referto aggiuntivo e marcato «sostituito». Ritorna ``(nuovo, vecchio)``."""
    vecchio = visita.referto_documento if visita.referto_documento_id else None
    nuovo = _helpers._salva_referto_visita(request, visita, referto_file, file_salvati)
    if vecchio is not None:
        marca = f"[Sostituito il {django_timezone.localdate():%d-%m-%Y}] "
        descrizione = vecchio.descrizione or ""
        if not descrizione.startswith("[Sostituito"):
            descrizione = marca + descrizione
        limite = DocumentoDipendente._meta.get_field("descrizione").max_length
        # update(): niente save(), che ricalcolerebbe la conservazione del documento.
        DocumentoDipendente.objects.filter(pk=vecchio.pk).update(
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=visita.pk,
            descrizione=descrizione[:limite] if limite else descrizione,
        )
    return nuovo, vecchio


# Campi della visita tracciati nell'audit di modifica. I testi liberi (dato
# sanitario) si registrano solo come «modificato», senza copiarne il contenuto.
_CAMPI_AUDIT_VISITA = ("tipo_id", "data_svolgimento", "esito")
_CAMPI_AUDIT_VISITA_TESTO = ("prescrizioni", "medico_competente", "note")


def _istantanea_visita(visita: VisitaMedica) -> dict:
    out = {}
    for campo in _CAMPI_AUDIT_VISITA + _CAMPI_AUDIT_VISITA_TESTO:
        valore = getattr(visita, campo)
        out[campo] = valore.isoformat() if isinstance(valore, date) else valore
    return out


def _differenze_visita(prima: dict, dopo: dict) -> dict:
    diff = {}
    for campo in _CAMPI_AUDIT_VISITA:
        if prima.get(campo) != dopo.get(campo):
            diff[campo] = {"prima": prima.get(campo), "dopo": dopo.get(campo)}
    for campo in _CAMPI_AUDIT_VISITA_TESTO:
        if (prima.get(campo) or "") != (dopo.get(campo) or ""):
            diff[campo] = "modificato"
    return diff


def _messaggio_doppione(doppia: VisitaMedica) -> str:
    return (
        f"Esiste già una visita «{doppia.tipo.nome}» del "
        f"{doppia.data_svolgimento:%d-%m-%Y} per questo dipendente (stessa famiglia di "
        f"visite, stesso giorno): apri quella e correggila invece di registrarne un'altra."
    )


@login_required
@require_POST
def dipendente_visita_add(request, legacy_id: int):
    from ..services.visite import dipendenti_esistenti, errore_data_visita, visita_doppia

    if not _helpers._can_edit_visite_mediche(request):
        messages.error(request, "Non hai i permessi per registrare visite mediche.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    if not dipendenti_esistenti([legacy_id]):
        messages.error(request, "Dipendente non trovato: visita non registrata.")
        return redirect("anagrafica:dipendenti_list")

    form = VisitaMedicaForm(request.POST, request.FILES)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, "; ".join(err))
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita = form.save(commit=False)
    errore = errore_data_visita(legacy_id, visita.data_svolgimento)
    if errore:
        messages.error(request, errore)
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    doppia = visita_doppia(legacy_id, visita.tipo, visita.data_svolgimento)
    if doppia:
        messages.error(request, _messaggio_doppione(doppia))
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    visita.legacy_anagrafica_id = legacy_id
    visita.created_by = request.user
    visita.updated_by = request.user
    referto_file = form.cleaned_data.get("referto_file")
    file_salvati: list = []
    try:
        # Visita e referto insieme: o entrambi, o nessuno (niente visite orfane).
        with transaction.atomic():
            visita.save()
            if referto_file:
                _helpers._salva_referto_visita(request, visita, referto_file, file_salvati)
    except IntegrityError:
        _helpers._elimina_file_salvati(file_salvati)
        messages.error(request, "Visita già registrata per questo dipendente, tipo e data: non duplicata.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    except Exception:
        _helpers._elimina_file_salvati(file_salvati)
        logger.exception("Registrazione visita per #%s fallita", legacy_id)
        messages.error(request, "Registrazione non riuscita: nessun dato è stato salvato.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    try:
        from core.audit import log_action
        log_action(
            request, "VISITA_MEDICA_CREATA", "anagrafica",
            {
                "visita_id": visita.pk, "dipendente_id": legacy_id,
                "tipo_visita": visita.tipo.nome,
                "data_svolgimento": visita.data_svolgimento.isoformat(),
                "esito": visita.esito,
                "referto_id": visita.referto_documento_id,
            },
            oggetto=visita,
        )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_CREATA fallito", exc_info=True)

    messages.success(request, f"Visita medica registrata. Scadenza: {visita.data_scadenza or '—'}")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
@require_POST
def dipendente_visita_edit(request, legacy_id: int, v_id: int):
    from ..services.visite import errore_data_visita, visita_doppia

    if not _helpers._can_edit_visite_mediche(request):
        messages.error(request, "Non hai i permessi per modificare le visite mediche.")
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)

    visita = get_object_or_404(VisitaMedica, pk=v_id, legacy_anagrafica_id=legacy_id)
    # Prima del form: is_valid() scrive i nuovi valori sull'istanza.
    prima = _istantanea_visita(visita)
    form = VisitaMedicaForm(request.POST, request.FILES, instance=visita)
    if not form.is_valid():
        for err in form.errors.values():
            messages.error(request, "; ".join(err))
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)

    visita = form.save(commit=False)
    errore = errore_data_visita(legacy_id, visita.data_svolgimento)
    if errore:
        messages.error(request, errore)
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)
    doppia = visita_doppia(legacy_id, visita.tipo, visita.data_svolgimento, escludi_pk=visita.pk)
    if doppia:
        messages.error(request, _messaggio_doppione(doppia))
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)

    visita.updated_by = request.user
    referto_file = form.cleaned_data.get("referto_file")
    file_salvati: list = []
    referto_nuovo = referto_vecchio = None
    try:
        with transaction.atomic():
            visita.save()
            if referto_file:
                referto_nuovo, referto_vecchio = _sostituisci_referto_visita(
                    request, visita, referto_file, file_salvati,
                )
    except IntegrityError:
        _helpers._elimina_file_salvati(file_salvati)
        messages.error(request, "Esiste già una visita per questo dipendente, tipo e data: modifica non salvata.")
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)
    except Exception:
        _helpers._elimina_file_salvati(file_salvati)
        logger.exception("Modifica visita %s fallita", v_id)
        messages.error(request, "Modifica non riuscita: la visita è rimasta com'era.")
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)

    try:
        from core.audit import log_action
        dettaglio = {
            "visita_id": visita.pk, "dipendente_id": legacy_id,
            "tipo_visita": visita.tipo.nome,
            "modifiche": _differenze_visita(prima, _istantanea_visita(visita)),
        }
        if referto_nuovo is not None:
            dettaglio["referto_nuovo_id"] = referto_nuovo.pk
            dettaglio["referto_sostituito_id"] = getattr(referto_vecchio, "pk", None)
        log_action(request, "VISITA_MEDICA_MODIFICATA", "anagrafica", dettaglio, oggetto=visita)
        if referto_vecchio is not None:
            log_action(
                request, "REFERTO_SOSTITUITO", "anagrafica",
                {"visita_id": visita.pk, "referto_nuovo_id": referto_nuovo.pk,
                 "referto_sostituito_id": referto_vecchio.pk},
                oggetto=referto_vecchio,
            )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_MODIFICATA fallito", exc_info=True)

    if referto_vecchio is not None:
        messages.success(request, "Visita medica aggiornata. Il referto precedente resta nel fascicolo, segnato come sostituito.")
    else:
        messages.success(request, "Visita medica aggiornata.")
    return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)


@login_required
@require_POST
def dipendente_visita_delete(request, legacy_id: int, v_id: int):
    # Compatibilita' con vecchi form: nessuna cancellazione senza motivazione.
    if not _helpers._can_view_visite_mediche(request) or not _helpers._has_canonical_grant(request, PERM_VISITE_DELETE):
        return HttpResponseForbidden("Non hai i permessi per eliminare visite mediche.")
    get_object_or_404(VisitaMedica, pk=v_id, legacy_anagrafica_id=legacy_id)
    return redirect("anagrafica:visita_medica_elimina", v_id=v_id)


@login_required
def documento_dipendente_download(request, doc_id: int):
    doc = get_object_or_404(DocumentoDipendente, pk=doc_id)

    # ACL: referti visite mediche → permesso visite. Altri → admin/HR.
    if doc.tipo == DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO:
        if not _helpers._can_view_referti(request):
            return HttpResponse(status=403)
    else:
        legacy_user = get_legacy_user(request.user)
        if not (_helpers._is_anagrafica_admin(request) or _helpers._check_hr_permission(request)):
            return HttpResponse(status=403)

    # Cartelle riservate (solo_admin): solo col permesso documenti riservati, anche col link diretto.
    if doc.cartella_id and doc.cartella.solo_admin and not _helpers._can_view_documenti_riservati(request):
        return HttpResponse(status=403)

    if not doc.file:
        return HttpResponse("File non disponibile.", status=404)

    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_DOWNLOAD", "anagrafica",
            f"Download documento #{doc.pk} ({doc.tipo}) di dipendente #{doc.legacy_anagrafica_id}",
            oggetto=doc,
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_DOWNLOAD fallito", exc_info=True)

    from django.http import FileResponse
    try:
        fh = doc.file.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    filename = doc.nome_originale or f"documento_{doc.pk}.bin"
    # SEC (audit A8): tipo dai primi byte del file (sniff lato server), mai da
    # doc.tipo_mime; inline solo PDF/PNG/JPEG coerenti col nome, il resto come
    # allegato con CSP sandbox.
    from core.download_security import harden_sniffed_response, read_head
    head = read_head(fh)
    response = FileResponse(fh, as_attachment=False, filename=filename)
    return harden_sniffed_response(response, filename, head)


@login_required
def foto_dipendente(request, legacy_id: int):
    """Serve la foto profilo del dipendente da storage privato (fuori webroot).

    La foto è un dato personale e NON è esposta su URL pubblico /media/: passa
    da questa view, che richiede autenticazione. Compare nelle liste/rubriche
    interne, quindi è visibile a ogni utente loggato (no ACL HR specifica).
    Lo storage decifra in automatico i file cifrati at-rest.
    """
    civile = DipendenteAnagraficaCivile.objects.filter(
        legacy_anagrafica_id=legacy_id
    ).only("legacy_anagrafica_id", "foto").first()
    if not civile or not civile.foto:
        return HttpResponse(status=404)

    from django.http import FileResponse
    richiesta = str(request.GET.get("m") or "")
    if richiesta:
        # Elenchi e organigramma: icona piccola invece della foto intera (anche 6 MB).
        dati = _miniatura_foto(civile.foto)
        if dati is not None:
            response = HttpResponse(dati, content_type="image/jpeg")
            versionata = richiesta == _foto_versione(civile.foto.name)
            # Con la versione giusta nell'URL la si tiene a lungo: una foto nuova cambia l'URL.
            response["Cache-Control"] = "private, max-age=2592000" if versionata else "private, max-age=3600"
            return response
    try:
        fh = civile.foto.open("rb")
    except FileNotFoundError:
        return HttpResponse(status=404)

    import mimetypes
    content_type = mimetypes.guess_type(civile.foto.name)[0] or "application/octet-stream"
    response = FileResponse(fh, content_type=content_type)
    # Cache breve lato browser: la foto cambia di rado, ma resta dietro auth.
    response["Cache-Control"] = "private, max-age=3600"
    return response


MINIATURA_LATO = 160  # px: avatar mostrati a 40-48 px, nitidi anche su schermi 4K


def _miniatura_foto(foto):
    """JPEG piccolo della foto, creato una volta e salvato cifrato accanto all'originale.

    Sta in ``<cartella foto>/miniature/`` dello stesso storage privato (cifrato at rest);
    quando la foto cambia si crea quella nuova e si cancellano le vecchie.
    Se qualcosa va storto restituisce None e la view serve la foto intera.
    """
    import posixpath

    from django.core.files.base import ContentFile

    storage = foto.storage
    cartella = posixpath.join(posixpath.dirname(foto.name), "miniature")
    base = posixpath.splitext(posixpath.basename(foto.name))[0]
    nome = posixpath.join(cartella, f"{base}_{MINIATURA_LATO}.jpg")
    try:
        if storage.exists(nome):
            with storage.open(nome, "rb") as fh:
                return fh.read()
        from PIL import Image, ImageOps

        with foto.open("rb") as fh:
            img = ImageOps.exif_transpose(Image.open(fh))
            img.thumbnail((MINIATURA_LATO, MINIATURA_LATO))
            if img.mode != "RGB":
                sfondo = Image.new("RGB", img.size, (255, 255, 255))
                sfondo.paste(img, mask=img.convert("RGBA").getchannel("A"))
                img = sfondo
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=82, optimize=True)
        dati = out.getvalue()
        try:
            _, vecchie = storage.listdir(cartella)
        except (FileNotFoundError, NotADirectoryError):
            vecchie = []
        for vecchia in vecchie:
            storage.delete(posixpath.join(cartella, vecchia))
        storage.save(nome, ContentFile(dati))
        return dati
    except Exception:  # noqa: BLE001 - la miniatura è un'ottimizzazione, mai un errore per l'utente
        logger.exception("Miniatura foto non creata: %s", foto.name)
        return None


@login_required
@require_POST
def documento_dipendente_delete(request, doc_id: int):
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono eliminare un documento.")
        return redirect("anagrafica:dipendenti_list")
    doc = get_object_or_404(DocumentoDipendente, pk=doc_id)
    legacy_id = doc.legacy_anagrafica_id
    tipo = doc.tipo
    doc.delete()
    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_ELIMINATO", "anagrafica",
            f"Eliminato documento #{doc_id} ({tipo}) di dipendente #{legacy_id}",
            oggetto_tipo=DocumentoDipendente._meta.label_lower,
            oggetto_id=str(doc_id),
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_ELIMINATO fallito", exc_info=True)
    messages.success(request, "Documento eliminato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
# Niente .html: una pagina caricata verrebbe aperta nel dominio del portale;
# le email si caricano come .msg.
_ALLOWED_MANUAL_DOC_EXTENSIONS = _helpers._ALLOWED_DOC_EXTENSIONS | {".msg"}


@login_required
@require_POST
def documento_dipendente_upload(request, legacy_id: int):
    """Carica un documento manuale nella cartella virtuale del dipendente."""
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono caricare documenti.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    cartella_id = request.POST.get("cartella_id") or None
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    uploaded = request.FILES.get("file")

    if not uploaded:
        messages.error(request, "Seleziona un file da caricare.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    # SEC: tipo verificato dal contenuto, senza ripiego sul Content-Type del
    # browser. Niente HTML: le mail si caricano come .msg.
    from ..services.upload_documenti import UploadMimeValidationError, valida_documento
    try:
        mime = valida_documento(uploaded, _ALLOWED_MANUAL_DOC_EXTENSIONS)
    except UploadMimeValidationError as exc:
        messages.error(
            request,
            f"File rifiutato: {exc} Formati ammessi: PDF, DOC, DOCX, XLS, XLSX, JPG, PNG, WEBP, "
            "MSG (le email si caricano come .msg).",
        )
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    cartella = None
    if cartella_id:
        cartella = CartellaDocumentoDipendente.objects.filter(pk=cartella_id, attiva=True).first()

    doc = DocumentoDipendente(
        legacy_anagrafica_id=legacy_id,
        tipo=DocumentoDipendente.Tipo.MANUALE,
        cartella=cartella,
        nome_originale=uploaded.name[:255],
        tipo_mime=mime,
        dimensione_bytes=uploaded.size,
        descrizione=descrizione,
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    doc.file = uploaded
    doc.save()

    try:
        from core.audit import log_action
        log_action(
            request, "DOCUMENTO_DIPENDENTE_UPLOAD", "anagrafica",
            {
                "documento_id": doc.pk,
                "nome_originale": doc.nome_originale,
                "cartella_id": cartella.pk if cartella else None,
                "cartella_nome": cartella.nome if cartella else "",
                "legacy_anagrafica_id": legacy_id,
            },
        )
    except Exception:
        logger.warning("Audit DOCUMENTO_DIPENDENTE_UPLOAD fallito", exc_info=True)

    messages.success(request, f"Documento '{doc.nome_originale}' caricato correttamente.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


# ---------------------------------------------------------------------------
# Lista globale documenti manuali (tab generale)
# ---------------------------------------------------------------------------

@login_required
def documenti_list(request):
    """Lista di tutti i documenti caricati manualmente, filtrabile per dipendente/cartella."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    hr_ok = _helpers._check_hr_permission(request)

    if not (is_admin or hr_ok):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("anagrafica:index")

    cartelle = list(CartellaDocumentoDipendente.objects.all())
    qs = DocumentoDipendente.objects.filter(tipo=DocumentoDipendente.Tipo.MANUALE).select_related("cartella", "created_by").order_by("-created_at")

    # Cartelle riservate (solo_admin): visibili solo col permesso documenti riservati.
    if not _helpers._can_view_documenti_riservati(request):
        cartelle = [c for c in cartelle if not c.solo_admin]
        qs = qs.exclude(cartella__solo_admin=True)

    filtro_cartella = request.GET.get("cartella", "").strip()
    filtro_cerca = request.GET.get("q", "").strip()
    filtro_anno = request.GET.get("anno", "").strip()

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

    nomi_map = _helpers._build_nomi_map()
    documenti = list(qs[:500])
    if filtro_cerca:
        q_low = filtro_cerca.lower()
        documenti = [
            d for d in documenti
            if q_low in nomi_map.get(d.legacy_anagrafica_id, "").lower()
            or q_low in (d.nome_originale or "").lower()
            or q_low in (d.descrizione or "").lower()
        ]

    for d in documenti:
        d.nome_dipendente = nomi_map.get(d.legacy_anagrafica_id, f"#{d.legacy_anagrafica_id}")

    _oggi = django_timezone.localdate()
    return render(request, "anagrafica/pages/documenti_list.html", {
        "is_admin": is_admin,
        "documenti": documenti,
        "cartelle": cartelle,
        "filtro_cartella": filtro_cartella,
        "filtro_cerca": filtro_cerca,
        "filtro_anno": filtro_anno,
        "anni_disponibili": list(range(2020, _oggi.year + 1)),
        "today": _oggi,
        "today_plus_1y": _oggi.replace(year=_oggi.year + 1),
    })


@login_required
@require_POST
def documento_sposta_cartella(request, doc_id: int):
    """Sposta un documento manuale in un'altra cartella (o «senza cartella»).

    Gestione del container: stessa autorizzazione dell'archivio (HR/admin)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    if not (is_admin or _helpers._check_hr_permission(request)):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("anagrafica:documenti_list")
    doc = get_object_or_404(
        DocumentoDipendente, pk=doc_id, tipo=DocumentoDipendente.Tipo.MANUALE
    )
    target = (request.POST.get("cartella") or "").strip()
    if target in ("", "__nessuna__"):
        doc.cartella = None
    else:
        try:
            doc.cartella = CartellaDocumentoDipendente.objects.get(pk=int(target))
        except (CartellaDocumentoDipendente.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Cartella di destinazione non valida.")
            return redirect("anagrafica:documenti_list")
    doc.save(update_fields=["cartella"])
    messages.success(request, "Documento spostato.")
    nxt = request.POST.get("next") or ""
    from core.redirects import safe_next

    if nxt and safe_next(request, nxt, "") == nxt:
        return redirect(nxt)
    return redirect("anagrafica:documenti_list")


# ---------------------------------------------------------------------------
# CRUD cartelle documenti (da impostazioni)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def cartella_documento_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    nome = (request.POST.get("nome") or "").strip()[:100]
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    if not nome:
        messages.error(request, "Il nome della cartella è obbligatorio.")
        return _helpers._redirect_impostazioni("documenti")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = 0
    # Cartella superiore (sottocartella) opzionale
    parent = None
    parent_raw = (request.POST.get("parent") or "").strip()
    if parent_raw and parent_raw not in ("0", "__root__"):
        try:
            parent = CartellaDocumentoDipendente.objects.get(pk=int(parent_raw))
        except (CartellaDocumentoDipendente.DoesNotExist, ValueError, TypeError):
            parent = None
    if CartellaDocumentoDipendente.objects.filter(nome__iexact=nome, parent=parent).exists():
        dove = f" in «{parent.nome}»" if parent else " di primo livello"
        messages.error(request, f"Esiste già una cartella «{nome}»{dove}.")
        return _helpers._redirect_impostazioni("documenti")
    try:
        retention = max(1, min(99, int((request.POST.get("retention_anni") or "10").strip())))
    except (ValueError, TypeError):
        retention = 10
    solo_admin = request.POST.get("solo_admin") == "1"
    CartellaDocumentoDipendente.objects.create(
        nome=nome, parent=parent, descrizione=descrizione, ordine=ordine,
        retention_anni=retention, solo_admin=solo_admin,
    )
    dove = f" in «{parent.nome}»" if parent else ""
    messages.success(request, f"Cartella «{nome}»{dove} creata.")
    return _helpers._redirect_impostazioni("documenti")


@login_required
@require_POST
def cartella_documento_edit(request, cartella_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    cartella = get_object_or_404(CartellaDocumentoDipendente, pk=cartella_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    descrizione = (request.POST.get("descrizione") or "").strip()[:300]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    attiva = request.POST.get("attiva") == "1"
    if not nome:
        messages.error(request, "Il nome della cartella è obbligatorio.")
        return _helpers._redirect_impostazioni("documenti")
    if CartellaDocumentoDipendente.objects.filter(nome__iexact=nome, parent=cartella.parent).exclude(pk=cartella_id).exists():
        messages.error(request, f"Esiste già un'altra cartella «{nome}» nello stesso livello.")
        return _helpers._redirect_impostazioni("documenti")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = cartella.ordine
    cartella.nome = nome
    cartella.descrizione = descrizione
    cartella.ordine = ordine
    cartella.attiva = attiva
    cartella.solo_admin = request.POST.get("solo_admin") == "1"
    try:
        cartella.retention_anni = max(1, min(99, int((request.POST.get("retention_anni") or "10").strip())))
    except (ValueError, TypeError):
        pass
    cartella.save()
    # Targeting (visibilità mirata): reparti + ruoli operativi. Vuoto = universale.
    def _ids(name):
        out = []
        for raw in request.POST.getlist(name):
            if str(raw).strip().isdigit():
                out.append(int(raw))
        return out
    cartella.reparti.set(_ids("reparti_ids"))
    cartella.ruoli_operativi.set(_ids("ruoli_ids"))
    messages.success(request, f"Cartella «{nome}» aggiornata.")
    return _helpers._redirect_impostazioni("documenti")


@login_required
@require_POST
def cartella_documento_delete(request, cartella_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "documenti")
    if not ok:
        return resp
    cartella = get_object_or_404(CartellaDocumentoDipendente, pk=cartella_id)
    n_figlie = cartella.figlie.count()
    if n_figlie > 0:
        messages.error(request, f"La cartella «{cartella.nome}» contiene {n_figlie} sottocartella/e: eliminale o spostale prima.")
        return _helpers._redirect_impostazioni("documenti")
    n_docs = cartella.documenti.count()
    if n_docs > 0:
        if cartella.attiva:
            cartella.attiva = False
            cartella.save(update_fields=["attiva"])
            messages.warning(request, f"La cartella «{cartella.nome}» contiene {n_docs} documento/i: disattivata (non eliminata) per preservare lo storico. Riattivala dalla modifica.")
        else:
            messages.error(request, f"La cartella «{cartella.nome}» contiene {n_docs} documento/i: non eliminabile (già disattiva).")
        return _helpers._redirect_impostazioni("documenti")
    nome = cartella.nome
    cartella.delete()
    messages.success(request, f"Cartella «{nome}» eliminata.")
    return _helpers._redirect_impostazioni("documenti")


@login_required
def organigramma_persona_popup(request, legacy_id: int):
    """Scheda sintetica di una persona, per il popup dell'organigramma.

    Frammento HTML (niente ``base.html``): lo carica il diagramma quando si
    clicca una tessera. Sta sotto ``/anagrafica/dipendenti/`` di proposito, cosi'
    l'ACL lo governa **come la scheda dipendente**: chi non puo' aprire la scheda
    non ottiene questi dati da una scorciatoia. Solo dati di lavoro (ruolo,
    reparto, recapiti aziendali): l'organigramma non e' il fascicolo.
    """
    ensure_anagrafica_schema()
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        return HttpResponseNotFound("<p class=\"ogp-vuoto\">Dipendente non trovato.</p>")
    dip = rows[0]

    civile = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
    aziendale = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()

    ruoli = [
        {
            "nome": a.ruolo.nome,
            "ambito": a.ruolo.ambito.nome if a.ruolo.ambito_id else "",
            "ambito_colore": a.ruolo.ambito.colore if a.ruolo.ambito_id else "",
        }
        for a in (
            DipendenteRuoloOperativo.objects
            .filter(legacy_anagrafica_id=legacy_id, ruolo__is_active=True)
            .select_related("ruolo", "ruolo__ambito")
            .order_by("ruolo__nome")
        )
    ]

    nome = naming.nome_completo(dip.get("nome"), dip.get("cognome"))
    return render(request, "anagrafica/partials/_org_persona_popup.html", {
        "legacy_id": legacy_id,
        "nome": nome,
        "ha_foto": bool(civile and civile.foto),
        "matricola": dip.get("matricola") or "",
        "badge": aziendale.badge if aziendale else "",
        "mansione": dip.get("mansione") or "",
        "reparto": (aziendale.area if aziendale and aziendale.area else dip.get("reparto")) or "",
        "area_aziendale": str(aziendale.area_aziendale) if aziendale and aziendale.area_aziendale_id else "",
        "ruolo_principale": (aziendale.ruolo_aziendale if aziendale else "") or dip.get("ruolo") or "",
        "data_assunzione": (
            (aziendale.data_assunzione_ultima or aziendale.data_prima_assunzione) if aziendale else None
        ),
        "email": (aziendale.email_aziendale if aziendale else "") or dip.get("email_notifica") or "",
        "telefono": aziendale.telefono_aziendale if aziendale else "",
        "ruoli": ruoli,
    })


# ---------------------------------------------------------------------------
# Fascicolo conformità — "il dipendente è in regola con la sua mansione?"
# (H2: semaforo aggregato formazione + visite + qualifiche + DPI)
# ---------------------------------------------------------------------------

@login_required
def dipendente_conformita_panel(request, legacy_id: int):
    """Pannello semaforo conformità per la scheda dipendente (HTMX lazy-load).

    Accesso: login. Il semaforo visite mostra solo l'esito valido/scaduto; il
    dettaglio (nomi tipologia) è incluso solo se ``_can_view_visite_mediche``.
    Mai esiti/prescrizioni. La logica privacy è applicata dal service via
    ``include_visite_dettaglio``.
    """
    if request.GET.get("vista") == "badge":
        # Solo il semaforo complessivo, per l'intestazione della scheda.
        can_view_visite = _helpers._can_view_visite_mediche(request)
        mansione_nome = (
            AnagraficaDipendente.objects.filter(id=legacy_id).values_list("mansione", flat=True).first()
        ) or ""
        stato = conformita_service.stato_conformita(
            legacy_id, include_visite_dettaglio=can_view_visite, mansione=mansione_nome,
        )
        return render(request, "anagrafica/partials/conformita_badge.html",
                      {"esito": stato.get("complessivo") or "na"})
    return render(
        request, "anagrafica/partials/conformita_panel.html",
        _build_conformita_panel_ctx(request, legacy_id),
    )


def _build_conformita_panel_ctx(request, legacy_id: int) -> dict:
    """Context del pannello conformità + profilo di rischio derivato (A2)."""
    can_view_visite = _helpers._can_view_visite_mediche(request)
    mansione_nome = (
        AnagraficaDipendente.objects
        .filter(id=legacy_id).values_list("mansione", flat=True).first()
    ) or ""
    stato = conformita_service.stato_conformita(
        legacy_id,
        include_visite_dettaglio=can_view_visite,
        mansione=mansione_nome,
    )
    mansione_obj = mansionario_service.mansione_per_nome(mansione_nome)
    # Profilo di rischio DERIVATO ("mansione di rischio" a vista): unione dei requisiti
    # della mansione lavorativa + esposizioni di area + esposizioni dirette al dipendente.
    requisiti_rischio = mansionario_service.requisiti_dipendente(
        legacy_id, mansione_nome=mansione_nome
    )
    from ..models_rischi import EsposizioneRischio, FattoreRischio
    esposizioni_dirette = list(
        EsposizioneRischio.objects
        .filter(legacy_anagrafica_id=legacy_id, is_active=True)
        .select_related("fattore")
    )
    _, is_admin = _helpers._ensure_admin(request)
    visite_facoltative = list(
        DipendenteVisitaFacoltativa.objects
        .filter(legacy_anagrafica_id=legacy_id, is_active=True)
        .select_related("tipo_visita")
    ) if can_view_visite else []
    return {
        "legacy_id": legacy_id,
        "stato": stato,
        "mansione_nome": mansione_nome,
        "mansione_id": mansione_obj.id if mansione_obj else None,
        "can_view_visite": can_view_visite,
        "requisiti_rischio": requisiti_rischio,
        "esposizioni_dirette": esposizioni_dirette,
        "is_admin": is_admin,
        "fattori_disponibili": (
            list(FattoreRischio.objects.filter(is_active=True).order_by("nome"))
            if is_admin else []
        ),
        "visite_facoltative": visite_facoltative,
        "tipi_visita_disponibili": (
            list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))
            if is_admin and can_view_visite else []
        ),
        "mostra_pannello_visite_facoltative": can_view_visite and (visite_facoltative or is_admin),
    }


@login_required
@require_POST
def dipendente_esposizione_rischio_add(request, legacy_id: int):
    """(1.9) Assegna un'esposizione a rischio DIRETTAMENTE a un dipendente (admin).
    Ri-renderizza il pannello conformità (HTMX)."""
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        return HttpResponse(status=403)
    from ..models_rischi import EsposizioneRischio, FattoreRischio
    try:
        fattore = FattoreRischio.objects.get(pk=request.POST.get("fattore_id"), is_active=True)
    except (FattoreRischio.DoesNotExist, ValueError, TypeError):
        return render(
            request, "anagrafica/partials/conformita_panel.html",
            _build_conformita_panel_ctx(request, legacy_id),
        )
    EsposizioneRischio.objects.get_or_create(
        fattore=fattore, legacy_anagrafica_id=legacy_id,
        defaults={"note": (request.POST.get("note") or "").strip(), "is_active": True},
    )
    return render(
        request, "anagrafica/partials/conformita_panel.html",
        _build_conformita_panel_ctx(request, legacy_id),
    )


@login_required
@require_POST
def dipendente_esposizione_rischio_remove(request, legacy_id: int, esp_id: int):
    """(1.9) Rimuove un'esposizione diretta di un dipendente (admin). Ri-renderizza il pannello."""
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        return HttpResponse(status=403)
    from ..models_rischi import EsposizioneRischio
    EsposizioneRischio.objects.filter(
        pk=esp_id, legacy_anagrafica_id=legacy_id
    ).delete()
    return render(
        request, "anagrafica/partials/conformita_panel.html",
        _build_conformita_panel_ctx(request, legacy_id),
    )


@login_required
@require_POST
def dipendente_visita_facoltativa_add(request, legacy_id: int):
    """Assegna una visita medica facoltativa (non derivata da mansione/rischio)
    direttamente a un dipendente (admin). Ri-renderizza il pannello conformità."""
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        return HttpResponse(status=403)
    try:
        tipo_visita = TipoVisitaMedica.objects.get(
            pk=request.POST.get("tipo_visita_id"), is_active=True
        )
    except (TipoVisitaMedica.DoesNotExist, ValueError, TypeError):
        return render(
            request, "anagrafica/partials/conformita_panel.html",
            _build_conformita_panel_ctx(request, legacy_id),
        )
    DipendenteVisitaFacoltativa.objects.get_or_create(
        tipo_visita=tipo_visita, legacy_anagrafica_id=legacy_id,
        defaults={
            "note": (request.POST.get("note") or "").strip(),
            "is_active": True,
            "created_by": request.user,
        },
    )
    return render(
        request, "anagrafica/partials/conformita_panel.html",
        _build_conformita_panel_ctx(request, legacy_id),
    )


@login_required
@require_POST
def dipendente_visita_facoltativa_remove(request, legacy_id: int, vf_id: int):
    """Rimuove una visita facoltativa di un dipendente (admin). Ri-renderizza il pannello."""
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        return HttpResponse(status=403)
    DipendenteVisitaFacoltativa.objects.filter(
        pk=vf_id, legacy_anagrafica_id=legacy_id
    ).delete()
    return render(
        request, "anagrafica/partials/conformita_panel.html",
        _build_conformita_panel_ctx(request, legacy_id),
    )


@login_required
def dipendente_verbale_dpi(request, legacy_id: int):
    """Verbale di consegna DPI (MOD.155) precompilato con i DPI richiesti dalla
    mansione del dipendente. Pagina stampabile (``window.print()``) da firmare;
    riusa i requisiti del resolver mansionario, niente record di consegna creati."""
    from django.utils import timezone
    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]
    mansione_nome = str(dip.get("mansione") or "").strip()
    requisiti = (
        mansionario_service.requisiti_per_nome_mansione(mansione_nome)
        if mansione_nome else mansionario_service.requisiti_vuoti()
    )
    nome = naming.nome_completo(dip.get("nome"), dip.get("cognome"))
    return render(request, "anagrafica/pages/verbale_dpi.html", {
        "dip": dip,
        "nome": nome,
        "mansione": mansione_nome,
        "reparto": str(dip.get("reparto") or "").strip(),
        "dpi": requisiti["dpi"],
        "oggi": timezone.localdate(),
    })


def _onboarding_aggiorna_safe(**kwargs) -> None:
    """Chiusura automatica delle voci verificabili; un errore non blocca la pagina."""
    try:
        onboarding_service.aggiorna_pratiche(**kwargs)
    except Exception:
        logger.exception("Verifica automatica voci onboarding fallita")


@login_required
def onboarding_list(request):
    """Cruscotto onboarding: KPI, pratiche con avanzamento e coda per responsabile. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per le pratiche di onboarding.")
        return redirect("anagrafica:index")

    _onboarding_aggiorna_safe()
    oggi = django_timezone.localdate()
    filtro_stato = (request.GET.get("stato") or "").strip()
    filtro_resp = (request.GET.get("responsabile") or "").strip()
    solo_ritardo = (request.GET.get("ritardo") or "").strip() == "1"
    categorie = dict(OnboardingTask.CATEGORIA_CHOICES)

    qs = OnboardingPratica.objects.prefetch_related("tasks").all()
    valid_stati = {choice[0] for choice in OnboardingPratica.STATO_CHOICES}
    if filtro_stato in valid_stati:
        qs = qs.filter(stato=filtro_stato)
    elif filtro_stato != "tutte":
        qs = qs.filter(stato__in=OnboardingPratica.STATI_APERTI)

    pratiche = []
    for pratica in qs.order_by("data_assunzione", "-created_at"):
        tasks = list(pratica.tasks.all())
        pratica.counts = onboarding_service.riepilogo(pratica, tasks)
        if solo_ritardo and not pratica.counts["in_ritardo"]:
            continue
        if filtro_resp in categorie and not any(
            t.categoria == filtro_resp and t.stato == OnboardingTask.STATO_DA_FARE for t in tasks
        ):
            continue
        pratiche.append(pratica)

    # Coda delle attività aperte del responsabile scelto (o di tutti, se in ritardo).
    coda = []
    if filtro_resp in categorie or solo_ritardo:
        coda_qs = OnboardingTask.objects.filter(
            stato=OnboardingTask.STATO_DA_FARE,
            pratica__stato__in=OnboardingPratica.STATI_APERTI,
        ).select_related("pratica").order_by("scadenza", "ordine")
        if filtro_resp in categorie:
            coda_qs = coda_qs.filter(categoria=filtro_resp)
        if solo_ritardo:
            coda_qs = coda_qs.filter(scadenza__lt=oggi)
        coda = list(coda_qs[:200])

    aperte = OnboardingPratica.objects.filter(stato__in=OnboardingPratica.STATI_APERTI)
    task_ritardo = OnboardingTask.objects.filter(
        stato=OnboardingTask.STATO_DA_FARE, pratica__stato__in=OnboardingPratica.STATI_APERTI,
        scadenza__lt=oggi,
    )
    entro_30 = oggi + _timedelta(days=30)
    kpi = {
        "in_corso": aperte.count(),
        "pre_ingresso": aperte.filter(legacy_anagrafica_id__isnull=True).count(),
        "in_ritardo": task_ritardo.values("pratica_id").distinct().count(),
        "voci_in_ritardo": task_ritardo.count(),
        "ingressi_30": aperte.filter(data_assunzione__gte=oggi, data_assunzione__lte=entro_30).count(),
        "fine_prova_30": aperte.filter(fine_prova__gte=oggi, fine_prova__lte=entro_30).count(),
        "chiuse": OnboardingPratica.objects.filter(stato=OnboardingPratica.STATO_CHIUSA).count(),
        "eccezioni": OnboardingPratica.objects.filter(stato=OnboardingPratica.STATO_CHIUSA_CON_ECCEZIONI).count(),
    }
    per_responsabile = {
        riga["categoria"]: riga["n"]
        for riga in OnboardingTask.objects.filter(
            stato=OnboardingTask.STATO_DA_FARE, pratica__stato__in=OnboardingPratica.STATI_APERTI,
        ).values("categoria").annotate(n=Count("id")).order_by()
    }

    page_obj = Paginator(pratiche, 30).get_page(request.GET.get("page"))
    return render(request, "anagrafica/pages/onboarding_list.html", {
        "page_obj": page_obj,
        "totale": len(pratiche),
        "filtro_stato": filtro_stato,
        "filtro_resp": filtro_resp,
        "solo_ritardo": solo_ritardo,
        "stato_choices": OnboardingPratica.STATO_CHOICES,
        "responsabili": [
            {"codice": codice, "label": label, "aperte": per_responsabile.get(codice, 0)}
            for codice, label in OnboardingTask.CATEGORIA_CHOICES
        ],
        "coda": coda,
        "kpi": kpi,
        "oggi": oggi,
        # Compatibilità con il template precedente / export.
        "n_in_corso": kpi["in_corso"],
        "n_chiuse": kpi["chiuse"],
        "n_eccezioni": kpi["eccezioni"],
    })


def _onboarding_contesto_pratica(pratica) -> dict:
    tasks = list(pratica.tasks.all())
    return {
        "pratica": pratica,
        "tasks": tasks,
        "fasi": onboarding_service.fasi_con_voci(pratica, tasks),
        "counts": onboarding_service.riepilogo(pratica, tasks),
        "oggi": django_timezone.localdate(),
    }


@login_required
def onboarding_detail(request, pratica_id: int):
    """Pratica onboarding a timeline per fase. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per le pratiche di onboarding.")
        return redirect("anagrafica:index")

    pratica = get_object_or_404(OnboardingPratica, pk=pratica_id)
    if pratica.is_aperta and pratica.legacy_anagrafica_id:
        _onboarding_aggiorna_safe(pratiche=[pratica])
    candidato = pratica.candidati_recruiting.order_by("-pk").first()
    posizione_ctx = (_posizione_struttura_ctx(request, pratica.legacy_anagrafica_id, True)
                     if pratica.legacy_anagrafica_id else {"posizione": None})
    return render(request, "anagrafica/pages/onboarding_detail.html", {
        **_onboarding_contesto_pratica(pratica),
        **posizione_ctx,
        "candidato": candidato,
        "task_stato_choices": OnboardingTask.STATO_CHOICES,
        "is_admin": _offboarding_is_admin(request),
    })


@login_required
@require_POST
def onboarding_date(request, pratica_id: int):
    """Aggiorna data di ingresso e fine prova; le scadenze aperte si ricalcolano. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per aggiornare la pratica onboarding.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    pratica = get_object_or_404(OnboardingPratica, pk=pratica_id, stato__in=OnboardingPratica.STATI_APERTI)
    valori = {}
    for campo in ("data_assunzione", "fine_prova"):
        grezzo = (request.POST.get(campo) or "").strip()
        try:
            valori[campo] = date.fromisoformat(grezzo) if grezzo else None
        except ValueError:
            messages.error(request, "Data non valida.")
            return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)
    if valori["data_assunzione"] and valori["fine_prova"] and valori["fine_prova"] < valori["data_assunzione"]:
        messages.error(request, "La fine della prova non può precedere l'ingresso.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    prima = {"data_assunzione": str(pratica.data_assunzione or ""), "fine_prova": str(pratica.fine_prova or "")}
    pratica.data_assunzione = valori["data_assunzione"]
    pratica.fine_prova = valori["fine_prova"]
    pratica.updated_by = request.user
    pratica.save(update_fields=["data_assunzione", "fine_prova", "updated_by", "updated_at"])
    n = onboarding_service.ricalcola_scadenze(pratica)
    _helpers._audit_safe(request, "DIPENDENTE_ONBOARDING_DATE", "anagrafica", {
        "pratica_id": pratica.pk, "prima": prima,
        "dopo": {k: str(v or "") for k, v in valori.items()}, "scadenze_ricalcolate": n,
    })
    messages.success(request, f"Date aggiornate: {n} scadenze ricalcolate.")
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)


@login_required
@require_POST
def onboarding_avvia(request, legacy_id: int):
    """Avvia una pratica onboarding per il dipendente. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per avviare l'onboarding.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    rows = fetch_anagrafica_rows(ids=[legacy_id])
    if not rows:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    dip = rows[0]

    if onboarding_service.pratica_aperta(legacy_id):
        messages.warning(request, "Esiste gia una pratica onboarding aperta per questo dipendente.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    data_assunzione = None
    raw_date = (request.POST.get("data_assunzione") or "").strip()
    if raw_date:
        try:
            data_assunzione = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Data assunzione non valida.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    ruolo_ids = list(
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("ruolo_id", flat=True)
    )
    nome = naming.nome_completo(dip.get("nome"), dip.get("cognome"))
    try:
        pratica = onboarding_service.avvia_onboarding(
            legacy_id=legacy_id,
            dipendente_nome=nome or f"#{legacy_id}",
            reparto=str(dip.get("reparto") or "").strip(),
            mansione=str(dip.get("mansione") or "").strip(),
            data_assunzione=data_assunzione,
            note_hr=(request.POST.get("note_hr") or "").strip()[:1000],
            user=request.user,
            ruolo_ids=ruolo_ids,
        )
    except Exception:
        logger.exception("Errore avvio pratica onboarding dipendente %s", legacy_id)
        messages.error(request, "Errore durante l'avvio della pratica onboarding.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    _helpers._audit_safe(request, "DIPENDENTE_ONBOARDING_PRATICA_APERTA", "anagrafica", {
        "pratica_id": pratica.id,
        "legacy_anagrafica_id": legacy_id,
        "dipendente_nome": nome,
    })
    messages.success(request, "Pratica onboarding avviata. Completa la checklist di inserimento.")
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica.id)


@login_required
@require_POST
def onboarding_task_update(request, pratica_id: int, task_id: int):
    """Aggiorna lo stato/nota di un task onboarding. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per aggiornare la pratica onboarding.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    task = get_object_or_404(
        OnboardingTask.objects.select_related("pratica"),
        pk=task_id,
        pratica_id=pratica_id,
        pratica__stato__in=OnboardingPratica.STATI_APERTI,
    )
    stato = (request.POST.get("stato") or "").strip()
    valid_stati = {choice[0] for choice in OnboardingTask.STATO_CHOICES}
    if stato not in valid_stati:
        messages.error(request, "Stato task onboarding non valido.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    from django.utils import timezone

    before = task.stato
    task.stato = stato
    task.note = (request.POST.get("note") or "").strip()[:1000]
    if stato in (OnboardingTask.STATO_COMPLETATO, OnboardingTask.STATO_ECCEZIONE):
        task.completed_at = timezone.now()
        task.completed_by = request.user
    else:
        task.completed_at = None
        task.completed_by = None
    task.save(update_fields=["stato", "note", "completed_at", "completed_by", "updated_at"])

    task.pratica.updated_by = request.user
    task.pratica.save(update_fields=["updated_by", "updated_at"])
    _helpers._audit_safe(request, "DIPENDENTE_ONBOARDING_TASK_UPDATE", "anagrafica", {
        "pratica_id": pratica_id,
        "task_id": task_id,
        "task_codice": task.codice,
        "stato_precedente": before,
        "stato_nuovo": task.stato,
    })
    if getattr(request, "htmx", False):
        # Aggiornamento in pagina: la voce si ridisegna e avanzamento/fase
        # arrivano out-of-band, senza ricaricare la pratica.
        contesto = _onboarding_contesto_pratica(task.pratica)
        return render(request, "anagrafica/partials/_onboarding_voce_htmx.html", {
            **contesto,
            "task": task,
            "fase": next((f for f in contesto["fasi"] if f["codice"] == task.fase), None),
        })
    messages.success(request, f"Task onboarding aggiornato: {task.titolo}.")
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)


@login_required
@require_POST
def onboarding_chiudi(request, pratica_id: int):
    """Chiude la pratica onboarding (CHIUSA o CHIUSA_CON_ECCEZIONI). Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per chiudere la pratica onboarding.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    pratica = get_object_or_404(
        OnboardingPratica.objects.prefetch_related("tasks"),
        pk=pratica_id,
        stato__in=OnboardingPratica.STATI_APERTI,
    )
    stato_finale = onboarding_service.chiudi_pratica(pratica, user=request.user)
    _helpers._audit_safe(request, "DIPENDENTE_ONBOARDING_PRATICA_CHIUSA", "anagrafica", {
        "pratica_id": pratica_id,
        "legacy_anagrafica_id": pratica.legacy_anagrafica_id,
        "stato_finale": stato_finale,
    })
    if stato_finale == OnboardingPratica.STATO_CHIUSA_CON_ECCEZIONI:
        messages.warning(request, "Pratica onboarding chiusa con eccezioni (task non completati).")
    else:
        messages.success(request, "Pratica onboarding chiusa: checklist completata.")
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)


@login_required
@require_POST
def onboarding_annulla(request, pratica_id: int):
    """Annulla una pratica onboarding aperta. Gated HR."""
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per annullare la pratica onboarding.")
        return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)

    pratica = get_object_or_404(
        OnboardingPratica,
        pk=pratica_id,
        stato__in=OnboardingPratica.STATI_APERTI,
    )
    onboarding_service.annulla_pratica(pratica, user=request.user)
    _helpers._audit_safe(request, "DIPENDENTE_ONBOARDING_PRATICA_ANNULLATA", "anagrafica", {
        "pratica_id": pratica_id,
        "legacy_anagrafica_id": pratica.legacy_anagrafica_id,
    })
    messages.success(request, "Pratica onboarding annullata.")
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica_id)
