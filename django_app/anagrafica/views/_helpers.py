"""Viste anagrafica — Funzioni e costanti condivise dai pilastri del modulo (un solo punto di lookup per i test).

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging
from datetime import timedelta as _timedelta
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.http import (
    HttpResponseRedirect,
)
from django.shortcuts import redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.

from django.contrib.auth.decorators import login_required
from core import naming
from core.legacy_anagrafica import (
    fetch_anagrafica_rows,
)
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user, is_legacy_admin

from ..models import (
    AnagraficaHRPermission,
    AnagraficaVisiteMedichePermission,
    AreaAziendale,
    Reparto,
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    DocumentoDipendente,
    AmbitoRuolo,
    StoricoContratto,
    VisitaMedica,
)
from ..models_formazione import (
    AnagraficaFormazionePermission,
    AttestatoFormazioneConfig,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingLessonAttendance,
)
from ..services.visite import (
    ultime_visite_correnti_ids,
)
from ..services import onboarding as onboarding_service
from ..acl_bootstrap import (
    PERM_DOCUMENTI_RISERVATI,
    PERM_FORMAZIONE_MANAGE,
    PERM_FORMAZIONE_VIEW,
    PERM_HR_VIEW,
    PERM_SCHEDA_MANAGE,
    PERM_VISITE_VIEW,
    PERM_VISITE_EDIT,
)


logger = logging.getLogger(__name__)


def _file_field_url(file_field) -> str:
    if not file_field:
        return ""
    try:
        return file_field.url
    except (OSError, ValueError):
        return ""


def _cessati_legacy_ids() -> set[int]:
    """Insieme dei ``legacy_anagrafica_id`` con rapporto cessato (ex dipendenti).

    Un dipendente è considerato ex dipendente quando l'anagrafica aziendale ha
    una ``data_cessazione`` valorizzata. Questi nominativi restano a sistema con
    il fascicolo completo ma sono esclusi dalla lista dipendenti in forza.
    """
    return {
        int(lid)
        for lid in DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
        if lid
    }


def _audit_safe(request, azione: str, modulo: str, dettaglio: dict | None = None) -> None:
    try:
        from core.audit import log_action

        log_action(request, azione, modulo, dettaglio or {})
    except Exception:
        logger.warning("Audit %s fallito", azione, exc_info=True)


# ---------------------------------------------------------------------------
# NOTE: tutte le view "Fornitori" sono state spostate nel modulo dedicato
# `fornitori` (URL prefix /fornitori/). I modelli Fornitore* restano in
# `anagrafica.models` perché referenziati da `assets.models` via FK storiche
# (tabelle DB invariate).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Definizione widget statistiche dipendente
# ---------------------------------------------------------------------------

STAT_WIDGETS = [
    {
        "id": "tickets_aperti",
        "title": "Ticket aperti",
        "icon": "🎫",
        "color": "#ef4444",
        "link_url": "/tickets/",
        "link_label": "Vai ai ticket",
    },
    {
        "id": "tickets_totali",
        "title": "Ticket totali",
        "icon": "📋",
        "color": "#3b82f6",
        "link_url": "/tickets/",
        "link_label": "Vai ai ticket",
    },
    {
        "id": "anomalie",
        "title": "Anomalie",
        "icon": "⚠️",
        "color": "#f59e0b",
        "link_url": "/gestione-anomalie/",
        "link_label": "Vai alle anomalie",
    },
    {
        "id": "diario_preposto",
        "title": "Diario preposto",
        "icon": "📔",
        "color": "#8b5cf6",
        "link_url": "/diario-preposto/",
        "link_label": "Vai al diario",
    },
    {
        "id": "rilevazioni",
        "title": "Rilevazioni sicurezza",
        "icon": "🦺",
        "color": "#10b981",
        "link_url": "/rilevazione-incidenti/",
        "link_label": "Vai alle rilevazioni",
    },
    {
        "id": "assenze",
        "title": "Assenze",
        "icon": "📅",
        "color": "#06b6d4",
        "link_url": "/assenze/",
        "link_label": "Vai alle assenze",
    },
    {
        "id": "timbri",
        "title": "Timbri",
        "icon": "🕐",
        "color": "#64748b",
        "link_url": "",
        "link_label": "Vai ai timbri",
    },
    {
        "id": "dpi",
        "title": "DPI richiesti",
        "icon": "🦺",
        "color": "#16a34a",
        "link_url": "/dpi/gestione/",
        "link_label": "Vai ai DPI",
    },
]


def _user_in_utente_allowlist(legacy_user, perm) -> bool:
    """True se l'utente legacy è nella allow-list per-utente del permesso.

    Concessione *additiva* (Feature per-utente interna al modulo): gli utenti
    nominati vedono sempre la sezione, in aggiunta ad admin/ruoli. Non toglie mai
    accesso a chi già lo ha.
    """
    if not legacy_user:
        return False
    uid = int(getattr(legacy_user, "id", 0) or 0)
    if not uid:
        return False
    return uid in [int(u) for u in (getattr(perm, "utente_ids", None) or [])]


def _ruoli_attivi() -> bool:
    from core.permessi import sistema_ruoli_attivo

    return sistema_ruoli_attivo()


def _puo_su_tutti(request, modulo: str, azione: str) -> bool:
    """Ruoli attivi: l'azione e' concessa con visibilita' «tutti».

    Le sezioni globali (dashboard visite, formazione, dati riservati, gestione)
    elencano tutti i dipendenti: chi ha solo «propri» o «team» non le apre, e
    vede quei dati sulla scheda dei dipendenti che gli competono.
    """
    from core.permessi import decisione

    esito = decisione(request, modulo, azione)
    return bool(esito.consentito and esito.ambito == "tutti")


def _check_hr_permission(request) -> bool:
    """Verifica se l'utente può vedere i dati HR riservati (IBAN, CF, disabilità)."""
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "anagrafica", "dati_riservati")
    perm = AnagraficaHRPermission.get_instance()
    if perm.accesso == AnagraficaHRPermission.ACCESSO_TUTTI:
        return True
    legacy_user = get_legacy_user(request.user)
    if _user_in_utente_allowlist(legacy_user, perm):
        return True
    if is_legacy_admin(legacy_user):
        if perm.accesso in (AnagraficaHRPermission.ACCESSO_ADMIN, AnagraficaHRPermission.ACCESSO_TUTTI):
            return True
        # ACCESSO_RUOLI: legacy admin controlla comunque la lista ruoli
    # ACL v2 canonico: governabile da /admin-portale/acl-canonico/ (additivo).
    if _has_canonical_grant(request, PERM_HR_VIEW, legacy_user=legacy_user):
        return True
    if perm.accesso == AnagraficaHRPermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _has_canonical_grant(request, code: str, legacy_user=None) -> bool:
    """True se l'utente ha il permesso canonico ACL v2 ``code``.

    `evaluate_permission_code_access` include già il bypass superuser e admin
    legacy, quindi questo helper è sempre ADDITIVO rispetto ai cancelli storici:
    concede, non toglie. Fail-closed se la valutazione esplode.
    """
    from core.acl_v2 import evaluate_permission_code_access
    try:
        if legacy_user is None:
            legacy_user = get_legacy_user(request.user)
    except Exception:
        legacy_user = None
    try:
        return bool(evaluate_permission_code_access(
            permission_code=code, legacy_user=legacy_user, django_user=request.user,
        ).get("allowed"))
    except Exception:
        logger.exception("Valutazione ACL canonico fallita per %s", code)
        return False


def _is_anagrafica_admin(request) -> bool:
    """Sostituisce il vecchio `is_superuser or is_legacy_admin(...)` in-line.

    Cancello delle sezioni di gestione della scheda dipendente e dei cataloghi.
    `is_legacy_admin` è vero solo per i ruoli il cui nome è in
    PORTAL_ADMIN_ROLE_NAMES (default {"admin"}): senza il grant canonico
    ``anagrafica.scheda.manage`` nessun altro ruolo poteva essere abilitato.
    """
    legacy_user = get_legacy_user(request.user)
    if request.user.is_superuser or is_legacy_admin(legacy_user):
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "anagrafica", "gestire")
    return _has_canonical_grant(request, PERM_SCHEDA_MANAGE, legacy_user=legacy_user)


def _can_view_documenti_riservati(request) -> bool:
    """Chi vede i documenti delle cartelle riservate (``solo_admin``).

    Superuser e amministratori del portale sempre; gli altri ruoli (HR,
    amministrazione, ...) se abilitati al permesso canonico
    ``anagrafica.documenti_riservati.view`` da /admin-portale/acl-canonico/.
    Stessa regola in scheda dipendente, download, archivio documenti ed export.
    """
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = get_legacy_user(request.user)
    if is_legacy_admin(legacy_user):
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "anagrafica", "dati_riservati")
    return _has_canonical_grant(request, PERM_DOCUMENTI_RISERVATI, legacy_user=legacy_user)


def _can_view_visite_mediche(request) -> bool:
    """Verifica se l'utente può vedere/registrare le visite mediche.

    Le visite mediche contengono dati sanitari sensibili (idoneità, prescrizioni).
    Il default del singleton è ADMIN: solo superuser + amministratori legacy.
    """
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "visite_mediche", "vedere")
    perm = AnagraficaVisiteMedichePermission.get_instance()
    if perm.accesso == AnagraficaVisiteMedichePermission.ACCESSO_TUTTI:
        return True
    legacy_user = get_legacy_user(request.user)
    if _user_in_utente_allowlist(legacy_user, perm):
        return True
    if is_legacy_admin(legacy_user):
        if perm.accesso in (
            AnagraficaVisiteMedichePermission.ACCESSO_ADMIN,
            AnagraficaVisiteMedichePermission.ACCESSO_TUTTI,
        ):
            return True
        # ACCESSO_RUOLI: legacy admin controlla comunque la lista ruoli
    # ACL v2 canonico: governabile da /admin-portale/acl-canonico/ (additivo).
    if _has_canonical_grant(request, PERM_VISITE_VIEW, legacy_user=legacy_user):
        return True
    if perm.accesso == AnagraficaVisiteMedichePermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _can_view_referti(request) -> bool:
    """Aprire il referto clinico (file, contenuto, coda referti).

    Con il sistema dei ruoli attivo serve l'azione «referti» delle visite mediche
    su tutti: chi vede le visite del team (capi, preposti) vede idoneita',
    limitazioni e scadenze, non il referto. Spento il sistema vale la regola
    storica: chi vede le visite apre anche i referti.
    """
    if not _can_view_visite_mediche(request):
        return False
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "visite_mediche", "referti")
    return True


def _can_edit_visite_mediche(request) -> bool:
    """Registrare, modificare o superare visite (e giornate, referti in arrivo).

    Finché il singleton non chiede un permesso di modifica separato, vale il
    comportamento storico: chi vede le visite le può anche registrare. Con
    ``richiedi_permesso_modifica`` serve il grant canonico ``anagrafica.visite.edit``
    (superuser e admin legacy passano dal bypass di ``_has_canonical_grant``).
    """
    if not _can_view_visite_mediche(request):
        return False
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "visite_mediche", "modificare")
    perm = AnagraficaVisiteMedichePermission.get_instance()
    if not perm.richiedi_permesso_modifica:
        return True
    return _has_canonical_grant(request, PERM_VISITE_EDIT)


def _can_view_formazione(request) -> bool:
    """Verifica se l'utente può visualizzare la sezione formazione HR.
    Usa AnagraficaFormazionePermission.accesso_visualizzazione (singleton).
    """
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "formazione", "vedere")
    perm = AnagraficaFormazionePermission.get_instance()
    if perm.accesso_visualizzazione == AnagraficaFormazionePermission.ACCESSO_TUTTI:
        return True
    legacy_user = get_legacy_user(request.user)
    if is_legacy_admin(legacy_user):
        if perm.accesso_visualizzazione in (
            AnagraficaFormazionePermission.ACCESSO_ADMIN,
            AnagraficaFormazionePermission.ACCESSO_TUTTI,
        ):
            return True
        # ACCESSO_RUOLI: legacy admin controlla comunque la lista ruoli
    # ACL v2 canonico: governabile da /admin-portale/acl-canonico/ (additivo).
    if _has_canonical_grant(request, PERM_FORMAZIONE_VIEW, legacy_user=legacy_user):
        return True
    if perm.accesso_visualizzazione == AnagraficaFormazionePermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruoli_autorizzati_json or [])]
    return False


# ---------------------------------------------------------------------------
# Libretto formativo dipendente — pagina stampa per audit ISO / uscita
# ---------------------------------------------------------------------------

def _periodo_da_request(request) -> tuple[date | None, date | None]:
    """Legge i parametri `dal`/`al` (ISO, come li manda `<input type="date">`).

    Una data illeggibile vale come assente: il filtro è una comodità di lettura,
    non deve mai far fallire la pagina. Se l'intervallo è invertito le due date
    vengono scambiate, così `dal` e `al` restano quello che dicono di essere.
    """
    def _parse(nome: str) -> date | None:
        raw = (request.GET.get(nome) or "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    dal, al = _parse("dal"), _parse("al")
    if dal and al and dal > al:
        dal, al = al, dal
    return dal, al


def _ruoli_conteggio_da_scheda() -> dict[str, int]:
    """Quante schede dipendente riportano ciascun ruolo nel campo testuale.

    Il «Ruolo aziendale» della scheda è ancora testo libero: non passa dalle
    assegnazioni del catalogo, quindi va contato a parte per non mostrare
    «0 dipendenti» su un ruolo che invece qualcuno ricopre.
    """
    conteggi: dict[str, int] = {}
    for valore in (
        DipendenteAnagraficaAziendale.objects
        .exclude(ruolo_aziendale="")
        .values_list("ruolo_aziendale", flat=True)
    ):
        chiave = (valore or "").strip().casefold()
        if chiave:
            conteggi[chiave] = conteggi.get(chiave, 0) + 1
    return conteggi


def _ambiti_context(ruoli) -> dict:
    """Ambiti per i filtri del catalogo, con quanti ruoli ciascuno ne raccoglie.

    «Non classificato» non è un ambito: è la voce che raduna i ruoli nati prima
    della classificazione, che valgono come ruoli dell'ambito della scheda.
    """
    ambiti = list(AmbitoRuolo.objects.all())
    conteggi: dict[int | None, int] = {}
    for r in ruoli:
        conteggi[r.ambito_id] = conteggi.get(r.ambito_id, 0) + 1
    for a in ambiti:
        a.n_ruoli = conteggi.get(a.id, 0)
    return {
        "ambiti": ambiti,
        "n_senza_ambito": conteggi.get(None, 0),
    }


def _upsert_dipendente_qualifica(legacy_id, tipo, data_conseguimento, data_scadenza,
                                 *, note="", user=None, sessione=None,
                                 numero=None, livello=None, ente=None,
                                 documento=None, documento_nome=None, origine=None):
    """Crea o aggiorna la qualifica corrente di un dipendente per un tipo.

    Convenzione (come ``import_asr``): una sola ``DipendenteQualifica`` corrente
    per (dipendente, tipo), aggiornata al rinnovo — niente duplicati. Lo storico
    dei rinnovi vive nelle ``QualificaSessione`` collegate. Ritorna (obj, created).

    I campi Fase 2 (``numero``/``livello``/``ente``/``documento``) sono opzionali:
    vengono scritti solo se passati esplicitamente (None = non toccare), così gli
    altri chiamanti (import ASR, sessioni) restano invariati.
    """
    if data_scadenza is None and tipo.durata_mesi and data_conseguimento:
        from anagrafica.models import _add_months
        data_scadenza = _add_months(data_conseguimento, tipo.durata_mesi)
    obj = (
        DipendenteQualifica.objects
        .filter(legacy_anagrafica_id=legacy_id, tipo=tipo)
        .order_by("-data_conseguimento", "-id").first()
    )
    created = obj is None
    if obj is None:
        obj = DipendenteQualifica(legacy_anagrafica_id=legacy_id, tipo=tipo)
    obj.data_conseguimento = data_conseguimento
    obj.data_scadenza = data_scadenza
    if note:
        obj.note = note[:255]
    if numero is not None:
        obj.numero = numero[:100]
    if livello is not None:
        obj.livello = livello[:80]
    if ente is not None:
        obj.ente = ente[:200]
    if documento is not None:
        obj.documento = documento
        obj.documento_nome_originale = (documento_nome or getattr(documento, "name", "") or "")[:255]
        # Un nuovo documento richiede una nuova verifica HR.
        obj.verificata = False
        obj.verificata_da = None
        obj.verificata_il = None
    if sessione is not None:
        obj.sessione = sessione
    if user is not None:
        obj.assegnato_da = user
    obj.save()

    # Storico append-only (Fase 2c): una riga per rilascio/rinnovo. Dedup contro
    # l'ultima riga identica (evita doppioni su re-import idempotenti).
    from anagrafica.models import DipendenteQualificaStorico
    doc_name = getattr(obj.documento, "name", "") or ""
    snap = (obj.data_conseguimento, obj.data_scadenza, obj.numero, obj.ente, doc_name)
    last = None if created else obj.storico.order_by("-id").first()
    last_snap = None if last is None else (
        last.data_conseguimento, last.data_scadenza, last.numero, last.ente,
        getattr(last.documento, "name", "") or "",
    )
    if last_snap != snap:
        if sessione is not None:
            org = DipendenteQualificaStorico.Origine.SESSIONE
        else:
            org = origine or DipendenteQualificaStorico.Origine.MANUALE
        DipendenteQualificaStorico.objects.create(
            qualifica=obj,
            data_conseguimento=obj.data_conseguimento,
            data_scadenza=obj.data_scadenza,
            numero=obj.numero, livello=obj.livello, ente=obj.ente,
            documento=(obj.documento or None),
            documento_nome_originale=obj.documento_nome_originale,
            note=(note or "")[:255], origine=org, registrato_da=user,
        )
    return obj, created


# ---------------------------------------------------------------------------
# Aree aziendali + Reparti — gerarchia a due livelli
# ---------------------------------------------------------------------------

def _dipendenti_picker_rows() -> list[dict]:
    """Elenco compatto dipendenti in forza per la selezione del caporeparto."""
    rows = fetch_anagrafica_rows(deduplicate=True)
    cessati = _cessati_legacy_ids()
    items: list[dict] = []
    for row in rows:
        legacy_id = int(row.get("id") or 0)
        if legacy_id <= 0 or legacy_id in cessati:
            continue
        nome = str(row.get("nome") or "").strip()
        cognome = str(row.get("cognome") or "").strip()
        label = naming.nome_completo(nome, cognome) or str(row.get("aliasusername") or "").strip() or f"#{legacy_id}"
        items.append({
            "id": legacy_id,
            "label": label,
            # L'etichetta è "Nome Cognome", ma la tendina resta ordinata per cognome.
            "_ordine": naming.chiave_ordinamento(nome, cognome) or label,
        })
    items.sort(key=lambda r: r["_ordine"].casefold())
    return items


@login_required
def aree_list(request):
    legacy_user = get_legacy_user(request.user)
    is_admin = _is_anagrafica_admin(request)
    reparti = list(
        Reparto.objects.prefetch_related("aree_aziendali", "responsabili", "aree_aziendali__responsabili")
        .order_by("nome")
    )
    aree_senza_reparto = list(
        AreaAziendale.objects.filter(reparto__isnull=True).prefetch_related("responsabili").order_by("nome")
    )
    dipendenti = _dipendenti_picker_rows()
    dip_map = {item["id"]: item["label"] for item in dipendenti}

    def _responsabili_labels(obj):
        ids = [d.id for d in obj.responsabili.all()]
        return ids, ", ".join(dip_map.get(i, "") for i in ids if dip_map.get(i, ""))

    for rep in reparti:
        rep.caporeparto_label = dip_map.get(rep.caporeparto_legacy_id or 0, "")
        rep.responsabili_ids, rep.responsabili_label = _responsabili_labels(rep)
        for area in rep.aree_aziendali.all():
            area.responsabile_label = dip_map.get(area.responsabile_legacy_id or 0, "")
            area.responsabili_ids, area.responsabili_label = _responsabili_labels(area)
    for area in aree_senza_reparto:
        area.responsabile_label = dip_map.get(area.responsabile_legacy_id or 0, "")
        area.responsabili_ids, area.responsabili_label = _responsabili_labels(area)
    return render(request, "anagrafica/pages/aree_list.html", {
        "reparti": reparti,
        "aree_senza_reparto": aree_senza_reparto,
        "is_admin": is_admin,
        "dipendenti_picker": dipendenti,
    })


# ---------------------------------------------------------------------------
# Sessioni di rinnovo qualifica — rilascio/rinnovo collettivo "a sessioni"
# (speculare alle sessioni corsi; pattern batch come le visite mediche)
# ---------------------------------------------------------------------------

def _qualifiche_can_edit(request) -> bool:
    return _is_anagrafica_admin(request)


# ---------------------------------------------------------------------------
# Helper: redirect verso il pannello impostazioni con tab attivo
# ---------------------------------------------------------------------------

def _redirect_impostazioni(tab: str | None = None):
    url = reverse("anagrafica:impostazioni")
    if tab:
        url = f"{url}?tab={tab}#tab-{tab}"
    return HttpResponseRedirect(url)


def _back_to_caller(request, fallback_view_name: str):
    """
    Redirect intelligente per le view CRUD dei cataloghi: se il form proviene dal
    pannello impostazioni (campo nascosto `next_tab`) torna lì, altrimenti
    redirige alla pagina di lista standalone.
    """
    next_tab = (request.POST.get("next_tab") or "").strip()
    if next_tab:
        return _redirect_impostazioni(next_tab)
    return redirect(fallback_view_name)


def _impostazioni_admin_check(request, tab: str | None = None):
    """Restituisce (is_admin, redirect_response_or_None)."""
    legacy_user = get_legacy_user(request.user)
    is_admin = _is_anagrafica_admin(request)
    if not is_admin:
        messages.error(request, "Permessi insufficienti.")
        return False, _redirect_impostazioni(tab)
    return True, None


# ---------------------------------------------------------------------------
# Pannello impostazioni anagrafica — vista aggregata con tabs
# ---------------------------------------------------------------------------
# Scadenzario unificato qualifiche + visite mediche
# ---------------------------------------------------------------------------

def _build_scadenzario_voci(
    request,
    *,
    filtro_tipo: str = "",
    filtro_stato: str = "",
    filtro_reparto: str = "",
    dip_map: dict | None = None,
    periodo: tuple | None = None,
) -> list[dict]:
    """Voci dello scadenzario unificato, ordinate per urgenza.

    ``periodo`` = ``(dal, al)``: solo le scadenze in quell'intervallo (inclusi),
    al posto della finestra di stato (scadute / 30 / 60 giorni).

    Fonte unica per la pagina scadenzario e per il blocco «Cose da gestire» della
    dashboard: se i due contassero per conto proprio, il numero sulla dashboard e
    la lista che quel numero apre potrebbero contraddirsi.

    Ogni sorgente entra solo se il permesso lo consente (visite mediche = dato
    sanitario, formazione e contratti = dato HR), quindi il chiamante non deve
    rifare il gating. ``dip_map`` evita un secondo fetch legacy quando il
    chiamante ha già le righe anagrafica.
    """
    from django.utils import timezone as tz
    oggi = tz.localdate()
    soglia_30 = oggi + _timedelta(days=30)
    soglia_60 = oggi + _timedelta(days=60)

    # Gli ex dipendenti (rapporto cessato) non devono comparire nello scadenzario
    # in NESSUNA sorgente: il filtro va applicato a monte, non solo ai contratti.
    cessati = _cessati_legacy_ids()

    can_view_visite = _can_view_visite_mediche(request)
    can_view_formazione = _can_view_formazione(request)
    can_view_contratti = _check_hr_permission(request)

    if dip_map is None:
        dip_rows = fetch_anagrafica_rows(deduplicate=True)
        dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    voci: list[dict] = []

    # ── Qualifiche ──────────────────────────────────────────────────────────
    if filtro_tipo in ("", "qualifica"):
        qs_q = DipendenteQualifica.objects.select_related("tipo").filter(
            data_scadenza__isnull=False
        ).exclude(legacy_anagrafica_id__in=cessati)
        if periodo:
            qs_q = qs_q.filter(data_scadenza__range=periodo)
        elif filtro_stato == "scaduta":
            qs_q = qs_q.filter(data_scadenza__lt=oggi)
        elif filtro_stato == "30":
            qs_q = qs_q.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_30)
        elif filtro_stato == "60":
            qs_q = qs_q.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_60)
        else:
            qs_q = qs_q.filter(data_scadenza__lte=soglia_60)

        # Solo la qualifica corrente per persona e tipo: un rinnovo registrato come
        # nuova riga non deve lasciare la vecchia «scaduta» (filtro in Python: un
        # IN con migliaia di id supererebbe il limite parametri di SQL Server).
        from ..services.requisiti import id_qualifiche_correnti
        correnti_q = id_qualifiche_correnti()
        for q in qs_q:
            if q.pk not in correnti_q:
                continue
            dip = dip_map.get(q.legacy_anagrafica_id, {})
            reparto = str(dip.get("reparto") or "").strip()
            if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
                continue
            delta = (q.data_scadenza - oggi).days
            voci.append({
                "kind":         "qualifica",
                "kind_label":   "Qualifica",
                "legacy_id":    q.legacy_anagrafica_id,
                "cognome":      str(dip.get("cognome") or f"ID {q.legacy_anagrafica_id}").strip(),
                "nome":         str(dip.get("nome") or "").strip(),
                "reparto":      reparto,
                "tipo_nome":    q.tipo.nome,
                "tipo_id":      q.tipo_id,
                "categoria":    q.tipo.get_categoria_display(),
                "data_scadenza": q.data_scadenza,
                "giorni":       delta,
                "scaduta":      delta < 0,
            })

    # ── Visite mediche (gated) ───────────────────────────────────────────────
    if can_view_visite and filtro_tipo in ("", "visita"):
        qs_v = VisitaMedica.objects.select_related("tipo").filter(
            id__in=ultime_visite_correnti_ids(), data_scadenza__isnull=False
        ).exclude(legacy_anagrafica_id__in=cessati)
        if periodo:
            qs_v = qs_v.filter(data_scadenza__range=periodo)
        elif filtro_stato == "scaduta":
            qs_v = qs_v.filter(data_scadenza__lt=oggi)
        elif filtro_stato == "30":
            qs_v = qs_v.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_30)
        elif filtro_stato == "60":
            qs_v = qs_v.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_60)
        else:
            qs_v = qs_v.filter(data_scadenza__lte=soglia_60)

        for v in qs_v:
            dip = dip_map.get(v.legacy_anagrafica_id, {})
            reparto = str(dip.get("reparto") or "").strip()
            if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
                continue
            delta = (v.data_scadenza - oggi).days
            voci.append({
                "kind":         "visita",
                "kind_label":   "Visita medica",
                "legacy_id":    v.legacy_anagrafica_id,
                "cognome":      str(dip.get("cognome") or f"ID {v.legacy_anagrafica_id}").strip(),
                "nome":         str(dip.get("nome") or "").strip(),
                "reparto":      reparto,
                "tipo_nome":    v.tipo.nome,
                "tipo_id":      v.tipo_id,
                "categoria":    "Visita medica",
                "data_scadenza": v.data_scadenza,
                "giorni":       delta,
                "scaduta":      delta < 0,
            })

    # ── Formazione: corsi obbligatori da TrainingDeadline (gated) ───────────
    if can_view_formazione and filtro_tipo in ("", "formazione"):
        qs_f = (
            TrainingDeadline.objects.select_related("corso")
            .filter(is_required=True, data_scadenza__isnull=False)
            .exclude(legacy_anagrafica_id__in=cessati)
        )
        if periodo:
            qs_f = qs_f.filter(data_scadenza__range=periodo)
        elif filtro_stato == "scaduta":
            qs_f = qs_f.filter(data_scadenza__lt=oggi)
        elif filtro_stato == "30":
            qs_f = qs_f.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_30)
        elif filtro_stato == "60":
            qs_f = qs_f.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_60)
        else:
            qs_f = qs_f.filter(data_scadenza__lte=soglia_60)

        for d in qs_f:
            dip = dip_map.get(d.legacy_anagrafica_id, {})
            reparto = str(dip.get("reparto") or "").strip()
            if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
                continue
            delta = (d.data_scadenza - oggi).days
            voci.append({
                "kind":         "formazione",
                "kind_label":   "Formazione",
                "legacy_id":    d.legacy_anagrafica_id,
                "cognome":      str(dip.get("cognome") or f"ID {d.legacy_anagrafica_id}").strip(),
                "nome":         str(dip.get("nome") or "").strip(),
                "reparto":      reparto,
                "tipo_nome":    d.corso.titolo,
                "corso_id":     d.corso_id,
                "categoria":    "Corso obbligatorio",
                "data_scadenza": d.data_scadenza,
                "giorni":       delta,
                "scaduta":      delta < 0,
            })

    # ── Contratti a termine e periodi di prova (gated: dato HR) ─────────────
    if can_view_contratti and filtro_tipo in ("", "contratto"):
        # `cessati` è già calcolato a monte (usato da tutte le sorgenti).
        # Solo l'ultimo contratto per dipendente: i precedenti sono storia chiusa.
        ultimo_contratto: dict[int, StoricoContratto] = {}
        for c in (
            StoricoContratto.objects
            .filter(legacy_anagrafica_id__isnull=False)
            .order_by("legacy_anagrafica_id", "-data_inizio", "-created_at")
        ):
            ultimo_contratto.setdefault(c.legacy_anagrafica_id, c)

        scadenze_contratti: list[tuple[int, date, str]] = []
        for legacy_id, c in ultimo_contratto.items():
            if legacy_id in cessati or c.data_fine is None:
                continue
            tip = c.tipologia_contratto or "a termine"
            scadenze_contratti.append((legacy_id, c.data_fine, f"Contratto {tip}"))
        # Periodi di prova: solo futuri — una prova già conclusa non è un'azione da fare.
        prova_rows = DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=True,
            prova_data_fine__isnull=False,
            prova_data_fine__gte=oggi,
        ).values_list("legacy_anagrafica_id", "prova_data_fine")
        for legacy_id, fine_prova in prova_rows:
            scadenze_contratti.append((legacy_id, fine_prova, "Fine periodo di prova"))

        for legacy_id, data_fine, descrizione in scadenze_contratti:
            if periodo:
                if not (periodo[0] <= data_fine <= periodo[1]):
                    continue
            elif filtro_stato == "scaduta":
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
            dip = dip_map.get(legacy_id, {})
            reparto = str(dip.get("reparto") or "").strip()
            if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
                continue
            delta = (data_fine - oggi).days
            voci.append({
                "kind":         "contratto",
                "kind_label":   "Contratto",
                "legacy_id":    legacy_id,
                "cognome":      str(dip.get("cognome") or f"ID {legacy_id}").strip(),
                "nome":         str(dip.get("nome") or "").strip(),
                "reparto":      reparto,
                "tipo_nome":    descrizione,
                "categoria":    "Contratto",
                "data_scadenza": data_fine,
                "giorni":       delta,
                "scaduta":      delta < 0,
            })

    # Ordina per urgenza: prima le più scadute (giorni più negativi), poi le più vicine
    voci.sort(key=lambda x: x["giorni"])
    return voci


# ===========================================================================
# Visite mediche / Documenti dipendente / HTMX DPI iniziali
# ===========================================================================

def _ensure_admin(request):
    """Ritorna (legacy_user, is_admin). Riusa la convenzione del modulo."""
    legacy_user = get_legacy_user(request.user)
    return legacy_user, _is_anagrafica_admin(request)


def _elimina_file_salvati(file_salvati: list) -> None:
    """Toglie dallo storage i file scritti da una transazione poi annullata."""
    for storage, nome in file_salvati:
        try:
            if storage.exists(nome):
                storage.delete(nome)
        except Exception:
            logger.warning("File referto orfano non rimosso: %s", nome, exc_info=True)


def _salva_referto_visita(request, visita: VisitaMedica, referto_file, file_salvati: list | None = None) -> DocumentoDipendente:
    """Crea il ``DocumentoDipendente`` VISITA_MEDICA_REFERTO (storage privato)
    e lo aggancia a ``visita.referto_documento``. Percorso unico per form
    singolo e sessione batch.

    ``file_salvati`` raccoglie ``(storage, nome)`` del file scritto: se la
    transazione del chiamante viene annullata, il chiamante lo rimuove con
    ``_elimina_file_salvati`` (lo storage non partecipa alla transazione)."""
    # SEC (audit A8): solo PDF/PNG/JPEG verificati dal contenuto; il tipo salvato
    # e' quello rilevato, mai il Content-Type dichiarato dal browser.
    from ..services.referti_file import valida_referto
    mime_reale = valida_referto(referto_file)
    doc = DocumentoDipendente(
        legacy_anagrafica_id=visita.legacy_anagrafica_id,
        tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        nome_originale=getattr(referto_file, "name", "") or "referto",
        tipo_mime=mime_reale,
        dimensione_bytes=getattr(referto_file, "size", 0) or 0,
        descrizione=f"Referto visita {visita.tipo.nome} del {visita.data_svolgimento}",
        oggetto_riferimento_tipo="anagrafica.visitamedica",
        oggetto_riferimento_id=visita.pk,
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    try:
        doc.file.save(referto_file.name, referto_file, save=True)
    except Exception:
        if doc.file and doc.file.name:
            _elimina_file_salvati([(doc.file.storage, doc.file.name)])
        raise
    if file_salvati is not None:
        file_salvati.append((doc.file.storage, doc.file.name))
    visita.referto_documento = doc
    visita.save(update_fields=["referto_documento", "updated_at"])
    return doc
_ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".webp"}


# ---------------------------------------------------------------------------
# Helpers: registrazione sessione batch visite mediche
# ---------------------------------------------------------------------------

def _build_nomi_map() -> dict[int, str]:
    """Ritorna dict {legacy_anagrafica_id: 'Nome Cognome'} per tutti i dipendenti."""
    nomi: dict[int, str] = {}
    try:
        for r in AnagraficaDipendente.objects.values("id", "cognome", "nome"):
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            nomi[lid] = naming.nome_completo(r.get("nome"), r.get("cognome")) or f"#{lid}"
    except Exception:
        logger.exception("Errore lookup nomi dipendenti per sessione visita")
    return nomi


def _build_ordine_map() -> dict[int, str]:
    """Chiave di ordinamento {legacy_anagrafica_id: 'Cognome Nome'}.

    Il nominativo si *mostra* "Nome Cognome" (`_build_nomi_map`), ma gli elenchi
    di persone restano ordinati per cognome come in ogni lista HR.
    """
    ordine: dict[int, str] = {}
    try:
        for r in AnagraficaDipendente.objects.values("id", "cognome", "nome"):
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            ordine[lid] = naming.chiave_ordinamento(r.get("nome"), r.get("cognome")) or f"#{lid}"
    except Exception:
        logger.exception("Errore lookup ordinamento nomi dipendenti")
    return ordine


def _can_edit_formazione(request) -> bool:
    """Verifica permesso di modifica sezione formazione (modifica catalogo piani/corsi/istruttori)."""
    if request.user.is_superuser:
        return True
    if _ruoli_attivi():
        return _puo_su_tutti(request, "formazione", "modificare")
    perm = AnagraficaFormazionePermission.get_instance()
    if perm.accesso_modifica == AnagraficaFormazionePermission.ACCESSO_TUTTI:
        return True
    legacy_user = get_legacy_user(request.user)
    if is_legacy_admin(legacy_user):
        return perm.accesso_modifica in (
            AnagraficaFormazionePermission.ACCESSO_ADMIN,
            AnagraficaFormazionePermission.ACCESSO_TUTTI,
        )
    # ACL v2 canonico: governabile da /admin-portale/acl-canonico/ (additivo).
    if _has_canonical_grant(request, PERM_FORMAZIONE_MANAGE, legacy_user=legacy_user):
        return True
    if perm.accesso_modifica == AnagraficaFormazionePermission.ACCESSO_ADMIN:
        return False
    if legacy_user and legacy_user.ruolo_id is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruoli_autorizzati_json or [])]
    return False


def _add_months(dt, months: int):
    """Aggiunge N mesi a una data, gestendo correttamente fine mese."""
    import calendar
    month = dt.month - 1 + months
    year  = dt.year + month // 12
    month = month % 12 + 1
    day   = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _calcola_percentuale_presenza(enrollment: TrainingEnrollment) -> float | None:
    """Calcola la percentuale di presenza sull'intero monte ore della sessione."""
    lezioni = list(enrollment.sessione.lezioni.all())
    if not lezioni:
        return None
    ore_totali = sum(lz.durata_ore for lz in lezioni)
    if ore_totali <= 0:
        return None
    presenze = {
        p.lezione_id: p
        for p in TrainingLessonAttendance.objects.filter(
            lezione__in=lezioni,
            legacy_anagrafica_id=enrollment.legacy_anagrafica_id,
        )
    }
    ore_effettive = 0.0
    for lz in lezioni:
        durata = lz.durata_ore
        if durata <= 0:
            # Giornata senza durata (import storici 09:00-09:00): non entra nel
            # denominatore, quindi non può entrare nemmeno nel numeratore,
            # altrimenti la percentuale supera il 100%.
            continue
        p = presenze.get(lz.pk)
        if p and p.stato_presenza == "PRESENTE":
            ore = float(p.ore_effettive) if p.ore_effettive else durata
        elif p and p.stato_presenza == "PARZIALE":
            ore = float(p.ore_effettive) if p.ore_effettive else (durata * 0.5)
        else:
            continue
        # Mai più ore della giornata (dato storico fuori misura).
        ore_effettive += min(ore, durata)
    return round(min(100.0, ore_effettive / ore_totali * 100), 2)


def _candidati_rinnovo_corso(corso, sessione=None) -> list[dict]:
    """Dipendenti da (ri)formare per un corso, dalla cache scadenze
    (`TrainingDeadline`): scaduti / in scadenza / mai frequentati, esclusi i
    cessati e chi è già iscritto alla sessione. Pre-seleziona scaduti e in
    scadenza (il "mai frequentato" è incluso ma non pre-spuntato: è un primo
    rilascio, non un rinnovo). Specchio di `_build_candidati_qualifica`."""
    rilevanti = ["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO"]
    deadlines = list(
        TrainingDeadline.objects.filter(corso=corso, stato_scadenza__in=rilevanti)
        .order_by("data_scadenza", "legacy_anagrafica_id")
    )
    iscritti_ids: set[int] = set()
    if sessione is not None:
        iscritti_ids = set(
            TrainingEnrollment.objects.filter(sessione=sessione)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    nomi = _build_nomi_map()
    cessati = _cessati_legacy_ids()
    out: list[dict] = []
    for d in deadlines:
        lid = d.legacy_anagrafica_id
        if lid in cessati or lid in iscritti_ids:
            continue
        out.append({
            "legacy_id": lid,
            "nome": nomi.get(lid, f"#{lid}"),
            "stato": d.stato_scadenza,
            "stato_label": d.get_stato_scadenza_display(),
            "data_scadenza": d.data_scadenza,
            "preselect": d.stato_scadenza in ("SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90"),
        })
    order = {"SCADUTO": 0, "IN_SCADENZA_30": 1, "IN_SCADENZA_90": 2, "MAI_FREQUENTATO": 3}
    _ordine = _build_ordine_map()
    out.sort(key=lambda c: (
        order.get(c["stato"], 9),
        _ordine.get(c["legacy_id"], c["nome"]).casefold(),
    ))
    return out


# ---------------------------------------------------------------------------
# Onboarding strutturato — pratica + checklist (H1, speculare a offboarding)
# ---------------------------------------------------------------------------

def _onboarding_counts(pratica) -> dict[str, int]:
    return onboarding_service.riepilogo(pratica)


# ============================================================================
# FORMAZIONE HR — E-LEARNING: MICRO-CORSI INTERNI (slide + quiz)
# ============================================================================
# Layer self-service sopra TrainingCourse (is_elearning=True). Distinzione ruoli
# via ACL formazione esistente:
#   - DISCENTE  -> @login_required (fruisce i corsi pubblicati, traccia solo i propri dati)
#   - AUTORE    -> _can_edit_formazione (crea/modifica slide e quiz)
#   - HR/ADMIN  -> _can_view_formazione (report completamenti gia esistenti)
# Identita discente = legacy_anagrafica_id (convenzione del modulo).


def _current_legacy_anagrafica_id(request) -> int | None:
    """Risolve il legacy_anagrafica_id del dipendente collegato all'utente loggato.

    Catena: utente Django -> Profile.legacy_user_id (UtenteLegacy) -> AnagraficaDipendente
    (utente_id). Ritorna None se l'utente non e collegato a un'anagrafica."""
    legacy_user = get_legacy_user(request.user)
    if not legacy_user:
        return None
    try:
        ana = AnagraficaDipendente.objects.filter(utente_id=legacy_user.id).only("id").first()
    except Exception:
        logger.debug("Impossibile risolvere anagrafica per utente legacy %s", getattr(legacy_user, "id", None))
        return None
    return int(ana.id) if ana else None


def _regola_elearning_snapshot(corso) -> dict:
    """Regola FAD applicata al completamento (fotografia storica, immutabile)."""
    try:
        from ..services.elearning_regole import regola_corso
        return {"modalita": "ELEARNING", **regola_corso(corso).come_dict()}
    except Exception:
        return {"modalita": "ELEARNING", "quiz_minimo_pct": corso.quiz_punteggio_minimo}


def _crea_record_completamento_elearning(corso, legacy_id, attempt, created_by):
    """Crea un TrainingEmployeeRecord storicizzato per il superamento di un micro-corso
    e-learning, riusando la tabella audit esistente (niente duplicazione).

    Allinea la qualifica e invalida/ricalcola la cache scadenze, come il flusso d'aula
    (`_crea_employee_record`)."""
    from django.utils import timezone as _tz
    oggi = _tz.localdate()
    data_scadenza = _add_months(oggi, corso.validita_mesi) if corso.validita_mesi else None

    record = TrainingEmployeeRecord.objects.create(
        corso=corso,
        sessione=None,
        enrollment=None,
        legacy_anagrafica_id=legacy_id,
        data_completamento=oggi,
        ore_frequentate=corso.durata_ore_teorica or 0,
        percentuale_presenza=None,
        idoneo=True,
        data_scadenza=data_scadenza,
        # Snapshot storici (immutabili)
        course_code_snapshot=corso.codice,
        course_title_snapshot=corso.titolo,
        course_version_snapshot=corso.versione,
        plan_code_snapshot=corso.piano.codice if corso.piano_id else "",
        plan_name_snapshot=corso.piano.nome if corso.piano_id else "",
        duration_hours_snapshot=corso.durata_ore_teorica,
        validity_months_snapshot=corso.validita_mesi,
        completion_rule_snapshot_json=_regola_elearning_snapshot(corso),
        session_code_snapshot="",
        teacher_name_snapshot="",
        completion_calculation_snapshot_json={
            "modalita": "ELEARNING",
            "quiz_punteggio_pct": str(attempt.punteggio_pct) if attempt else None,
            "quiz_corrette": attempt.n_corrette if attempt else None,
            "quiz_totali": attempt.n_totali if attempt else None,
            "quiz_minimo_pct": _regola_elearning_snapshot(corso).get("soglia_pct", corso.quiz_punteggio_minimo),
        },
    )

    # Invalida cache scadenze e tenta ricalcolo immediato (fail-safe come il flusso d'aula)
    TrainingDeadline.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).update(needs_refresh=True)
    try:
        from ..services.training_deadline_service import refresh_deadlines
        refresh_deadlines(legacy_id=legacy_id, corso_id=corso.pk)
    except NotImplementedError:
        pass
    except Exception:
        logger.exception("Refresh scadenze e-learning fallito per dip=%s corso=%s", legacy_id, corso.pk)

    # Allineamento qualifica (competency management), fail-safe
    try:
        if corso.qualifica_id and record.idoneo:
            qual, _ = _upsert_dipendente_qualifica(
                legacy_id, corso.qualifica, record.data_completamento, record.data_scadenza, user=created_by,
            )
            if qual.record_formazione_id != record.pk:
                qual.record_formazione = record
                qual.save(update_fields=["record_formazione"])
    except Exception:
        logger.exception("Allineamento qualifica e-learning fallito per record %s", record.pk)

    # Valutazione di efficacia sul campo, se il corso la prevede: come il flusso
    # d'aula (prima l'e-learning non la apriva mai). Fail-safe.
    try:
        from ..services.formazione_efficacia import pianifica_valutazione_efficacia
        with transaction.atomic():  # savepoint: un errore qui non rovina il completamento
            pianifica_valutazione_efficacia(record)
    except Exception:
        logger.exception("Valutazione di efficacia non pianificata per record e-learning %s", record.pk)

    # Archiviazione automatica dell'attestato nella cartella documenti del dipendente
    # (stesso flusso dei corsi d'aula: cartella «Attestati formazione» o quella scelta
    # in Impostazioni → Template attestato). Fail-safe: non deve bloccare il completamento.
    # Dopo il commit: la generazione del PDF non tiene lock né lascia file orfani
    # se il completamento viene annullato.
    def _archivia():
        try:
            cfg = AttestatoFormazioneConfig.get_instance()
            if cfg.auto_salva_attestato:
                from ..services.attestato_pdf import archivia_attestato
                archivia_attestato(record, cfg=cfg, user=created_by)
        except Exception:
            logger.exception("Archiviazione automatica attestato e-learning fallita per record %s", record.pk)

    transaction.on_commit(_archivia)
    return record
