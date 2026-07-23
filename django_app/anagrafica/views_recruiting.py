"""Recruiting MOD. 05-01 — viste (lista, scheda, step 2, KPI, criteri).

Gating a due strati, come il resto delle sezioni HR sensibili:

1. il **permesso canonico ACL v2** (``anagrafica.recruiting.view`` / ``.manage``),
   governabile da ``/admin-portale/acl-canonico/`` e applicato dal middleware in
   ``ACL_STRICT_CANONICAL``;
2. il **singleton di sezione** ``RecruitingPermission``, default ADMIN, sul
   modello di quello delle visite mediche.

Servono entrambi: le schede contengono età, cittadinanza e note libere che
possono riportare situazioni familiari o di salute.

Importato da ``urls.py`` come modulo dedicato (``from . import views_recruiting``).
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from .forms_recruiting import CandidatoForm, CandidatoStep2Form, RecruitingCriterioForm
from .models_recruiting import (
    Candidato,
    CandidatoLog,
    CandidatoPunteggio,
    RecruitingCriterio,
    RecruitingPermission,
)
from .services import recruiting as recruiting_service

logger = logging.getLogger(__name__)

PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Permessi
# ---------------------------------------------------------------------------

def _singleton_consente(request) -> bool:
    """Strato 2: il singleton di sezione (default: solo amministratori)."""
    from core.legacy_utils import get_legacy_user, is_legacy_admin

    if request.user.is_superuser:
        return True
    perm = RecruitingPermission.get_instance()
    if perm.accesso == RecruitingPermission.ACCESSO_TUTTI:
        return True

    try:
        legacy_user = get_legacy_user(request.user)
    except Exception:
        legacy_user = None

    if perm.accesso == RecruitingPermission.ACCESSO_ADMIN:
        return bool(is_legacy_admin(legacy_user))

    # ACCESSO_RUOLI: anche l'admin legacy passa dalla lista ruoli.
    if legacy_user is not None and getattr(legacy_user, "ruolo_id", None) is not None:
        return int(legacy_user.ruolo_id) in [int(r) for r in (perm.ruolo_ids or [])]
    return False


def _acl_consente(request, code: str) -> bool:
    """Strato 1: permesso canonico ACL v2 (bypass superuser/admin legacy incluso)."""
    from core.acl_v2 import evaluate_permission_code_access
    from core.legacy_utils import get_legacy_user

    try:
        legacy_user = get_legacy_user(request.user)
    except Exception:
        legacy_user = None
    return bool(evaluate_permission_code_access(
        permission_code=code, legacy_user=legacy_user, django_user=request.user,
    ).get("allowed"))


def _can_view_recruiting(request) -> bool:
    from .acl_bootstrap import PERM_RECR_VIEW

    return _singleton_consente(request) and _acl_consente(request, PERM_RECR_VIEW)


def _can_manage_recruiting(request) -> bool:
    from .acl_bootstrap import PERM_RECR_MANAGE

    return _singleton_consente(request) and _acl_consente(request, PERM_RECR_MANAGE)


def _denied(request, azione: str = "consultare le schede candidato"):
    messages.error(request, f"Non hai i permessi per {azione}.")
    return redirect("anagrafica:index")


def _audit(request, azione: str, dettaglio: dict) -> None:
    try:
        log_action(request, azione, "anagrafica", dettaglio)
    except Exception:
        logger.debug("Audit recruiting fallito (%s)", azione, exc_info=True)


# ---------------------------------------------------------------------------
# Lista + ricerca
# ---------------------------------------------------------------------------

def _filtra_candidati(request):
    """Queryset filtrato dai parametri GET. Usato da lista e cruscotto KPI."""
    qs = Candidato.objects.all()

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(cognome__icontains=q) | Q(nome__icontains=q)
            | Q(mansione_cercata__icontains=q) | Q(azienda_attuale__icontains=q)
            | Q(localita__icontains=q) | Q(note__icontains=q)
        )

    stato = (request.GET.get("stato") or "").strip()
    if stato in {c[0] for c in Candidato.STATO_CHOICES}:
        qs = qs.filter(stato=stato)
    elif not q:
        # In navigazione le schede annullate/archiviate sono fuori dal lavoro
        # corrente: compaiono solo selezionandole dal filtro stato. Una ricerca
        # testuale (q) invece le trova comunque — chi cerca un nome deve trovarlo.
        qs = qs.exclude(stato__in=Candidato.STATI_ARCHIVIATI)

    canale = (request.GET.get("canale") or "").strip()
    if canale in {c[0] for c in Candidato.CANALE_CHOICES}:
        qs = qs.filter(canale_provenienza=canale)

    giudizio = (request.GET.get("giudizio") or "").strip()
    if giudizio in {c[0] for c in Candidato.GIUDIZIO_CHOICES}:
        qs = qs.filter(giudizio_finale=giudizio)

    mansione = (request.GET.get("mansione") or "").strip()
    if mansione:
        qs = qs.filter(mansione_cercata__icontains=mansione)

    if (request.GET.get("da_completare") or "").strip() == "1":
        qs = qs.filter(cognome="", nome="")

    punteggio_min = (request.GET.get("punteggio_min") or "").strip()
    if punteggio_min:
        try:
            qs = qs.filter(punteggio_ponderato__gte=float(punteggio_min.replace(",", ".")))
        except ValueError:
            pass

    for chiave, lookup in (("dal", "gte"), ("al", "lte")):
        grezzo = (request.GET.get(chiave) or "").strip()
        if grezzo:
            try:
                qs = qs.filter(**{f"data_primo_colloquio__{lookup}": date.fromisoformat(grezzo)})
            except ValueError:
                pass

    return qs


def _filtri_correnti(request) -> dict:
    return {
        "q": (request.GET.get("q") or "").strip(),
        "stato": (request.GET.get("stato") or "").strip(),
        "canale": (request.GET.get("canale") or "").strip(),
        "giudizio": (request.GET.get("giudizio") or "").strip(),
        "mansione": (request.GET.get("mansione") or "").strip(),
        "punteggio_min": (request.GET.get("punteggio_min") or "").strip(),
        "dal": (request.GET.get("dal") or "").strip(),
        "al": (request.GET.get("al") or "").strip(),
    }


@login_required
def recruiting_list(request):
    """Elenco candidati con ricerca e filtri (mansione, canale, punteggio, esito, data)."""
    if not _can_view_recruiting(request):
        return _denied(request)

    qs = _filtra_candidati(request).select_related("onboarding_pratica")
    totale = qs.count()
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/recruiting_list.html", {
        "page_obj": page_obj,
        "totale": totale,
        "filtri": _filtri_correnti(request),
        "stato_choices": Candidato.STATO_CHOICES,
        "canale_choices": Candidato.CANALE_CHOICES,
        "giudizio_choices": Candidato.GIUDIZIO_CHOICES,
        "can_manage": _can_manage_recruiting(request),
        "n_in_corso": Candidato.objects.exclude(stato__in=Candidato.STATI_CHIUSI).count(),
        "n_in_database": Candidato.objects.filter(stato=Candidato.STATO_IN_DATABASE).count(),
        "n_assunti": Candidato.objects.filter(stato=Candidato.STATO_ASSUNTO).count(),
        # Schede importate anonime, ancora senza nominativo (badge «Da completare»).
        "n_da_completare": Candidato.objects
            .filter(cognome="", nome="")
            .exclude(stato__in=Candidato.STATI_ARCHIVIATI)
            .count(),
    })


# ---------------------------------------------------------------------------
# Scheda candidato (step 1) — creazione e modifica
# ---------------------------------------------------------------------------

def _righe_criteri(criteri, candidato: Candidato | None) -> list[dict]:
    """Criteri con il voto già espresso, pronti per il template.

    L'accoppiata criterio+voto si prepara qui: nei template Django non esiste un
    accesso per chiave a un dizionario senza filtro custom.
    """
    voti: dict[int, int] = {}
    if candidato is not None:
        voti = {
            riga.criterio_id: riga.valore
            for riga in CandidatoPunteggio.objects.filter(candidato=candidato)
        }
    return [{"criterio": c, "valore": voti.get(c.id)} for c in criteri]


def _valori_punteggio_da_post(request, criteri) -> dict[int, int | None]:
    valori: dict[int, int | None] = {}
    for criterio in criteri:
        grezzo = (request.POST.get(f"criterio_{criterio.id}") or "").strip()
        valori[criterio.id] = grezzo or None
    return valori


@login_required
def recruiting_create(request):
    """Nuova scheda candidato con la valutazione pesata del primo colloquio."""
    if not _can_manage_recruiting(request):
        return _denied(request, "creare schede candidato")

    criteri = recruiting_service.criteri_attivi()

    if request.method == "POST":
        form = CandidatoForm(request.POST)
        if form.is_valid():
            candidato = form.save(commit=False)
            candidato.created_by = request.user
            candidato.updated_by = request.user
            candidato.save()

            recruiting_service.salva_punteggi(
                candidato, _valori_punteggio_da_post(request, criteri), user=request.user,
            )
            if candidato.giudizio_finale:
                recruiting_service.registra_cambio_giudizio(
                    candidato, "", candidato.giudizio_finale, user=request.user,
                )

            _audit(request, "RECRUITING_CANDIDATO_CREATO", {
                "candidato_id": candidato.pk, "stato": candidato.stato,
            })
            messages.success(request, "Scheda candidato creata.")
            return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)
        messages.error(request, "Controlla i campi evidenziati.")
    else:
        form = CandidatoForm()

    return render(request, "anagrafica/pages/recruiting_form.html", {
        "form": form,
        "candidato": None,
        "righe_criteri": _righe_criteri(criteri, None),
        "scala": range(1, 6),
    })


@login_required
def recruiting_detail(request, candidato_id: int):
    """Scheda candidato: valutazione, secondo colloquio, esito, storico modifiche."""
    if not _can_view_recruiting(request):
        return _denied(request)

    candidato = get_object_or_404(
        Candidato.objects.select_related("onboarding_pratica"), pk=candidato_id,
    )
    criteri = recruiting_service.criteri_attivi()

    return render(request, "anagrafica/pages/recruiting_detail.html", {
        "candidato": candidato,
        "righe_criteri": _righe_criteri(criteri, candidato),
        "step2_form": CandidatoStep2Form(instance=candidato),
        "log": list(candidato.log_modifiche.all()[:50]),
        "can_manage": _can_manage_recruiting(request),
        "peso_totale": sum((c.peso_percentuale for c in criteri), start=0),
        # A iter chiuso la scheda è in sola lettura finché non si riapre l'iter.
        "sola_lettura": candidato.iter_chiuso,
    })


@login_required
def recruiting_edit(request, candidato_id: int):
    """Modifica della scheda e della valutazione pesata (step 1)."""
    if not _can_manage_recruiting(request):
        return _denied(request, "modificare le schede candidato")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    # Una scheda a iter chiuso è in sola lettura: modificarla significa rimettere
    # mano a una decisione presa, e deve passare per «Riapri iter» (tracciato).
    if candidato.iter_chiuso:
        messages.warning(
            request,
            "La scheda è a iter chiuso. Riapri l'iter prima di modificarla.",
        )
        return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)

    criteri = recruiting_service.criteri_attivi()

    if request.method == "POST":
        giudizio_prima = candidato.giudizio_finale
        stato_prima = candidato.stato
        form = CandidatoForm(request.POST, instance=candidato)
        if form.is_valid():
            candidato = form.save(commit=False)
            candidato.updated_by = request.user
            candidato.save()

            recruiting_service.salva_punteggi(
                candidato, _valori_punteggio_da_post(request, criteri), user=request.user,
            )
            recruiting_service.registra_cambio_giudizio(
                candidato, giudizio_prima, candidato.giudizio_finale, user=request.user,
            )
            recruiting_service.registra_cambio_stato(
                candidato, stato_prima, candidato.stato, user=request.user,
            )

            _audit(request, "RECRUITING_CANDIDATO_MODIFICATO", {
                "candidato_id": candidato.pk,
                "giudizio_prima": giudizio_prima,
                "giudizio_dopo": candidato.giudizio_finale,
            })
            messages.success(request, "Scheda candidato aggiornata.")
            return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)
        messages.error(request, "Controlla i campi evidenziati.")
    else:
        form = CandidatoForm(instance=candidato)

    return render(request, "anagrafica/pages/recruiting_form.html", {
        "form": form,
        "candidato": candidato,
        "righe_criteri": _righe_criteri(criteri, candidato),
        "scala": range(1, 6),
    })


# ---------------------------------------------------------------------------
# Step 2 — secondo colloquio
# ---------------------------------------------------------------------------

@login_required
@require_POST
def recruiting_step2(request, candidato_id: int):
    """Salva i dati del secondo colloquio sulla stessa scheda."""
    if not _can_manage_recruiting(request):
        return _denied(request, "registrare il secondo colloquio")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    form = CandidatoStep2Form(request.POST, instance=candidato)
    if not form.is_valid():
        for errori in form.errors.values():
            for errore in errori:
                messages.error(request, errore)
        return redirect("anagrafica:recruiting_detail", candidato_id=candidato_id)

    stato_prima = candidato.stato
    candidato = form.save(commit=False)
    candidato.updated_by = request.user
    if candidato.data_secondo_colloquio and candidato.stato in (
        Candidato.STATO_NUOVO, Candidato.STATO_CV_VALUTATO, Candidato.STATO_COLLOQUIO_1,
    ):
        candidato.stato = Candidato.STATO_COLLOQUIO_2
    candidato.save()

    recruiting_service.registra_cambio_stato(
        candidato, stato_prima, candidato.stato, user=request.user,
        note="Registrato il secondo colloquio.",
    )
    _audit(request, "RECRUITING_STEP2_SALVATO", {"candidato_id": candidato.pk})
    messages.success(request, "Secondo colloquio registrato.")
    return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)


# ---------------------------------------------------------------------------
# Transizione di fine iter
# ---------------------------------------------------------------------------

@login_required
@require_POST
def recruiting_assumi(request, candidato_id: int):
    """Assunto → crea il dipendente e avvia la pratica di onboarding."""
    if not _can_manage_recruiting(request):
        return _denied(request, "avviare l'onboarding")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    try:
        pratica = recruiting_service.assumi_e_avvia_onboarding(
            candidato, user=request.user, reparto=(request.POST.get("reparto") or "").strip(),
        )
    except recruiting_service.TransizioneError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:recruiting_detail", candidato_id=candidato_id)
    except Exception:
        logger.exception("Transizione a onboarding fallita per candidato %s", candidato_id)
        messages.error(request, "Errore durante l'avvio dell'onboarding.")
        return redirect("anagrafica:recruiting_detail", candidato_id=candidato_id)

    _audit(request, "RECRUITING_CANDIDATO_ASSUNTO", {
        "candidato_id": candidato.pk,
        "legacy_anagrafica_id": candidato.legacy_anagrafica_id,
        "pratica_id": pratica.pk,
    })
    messages.success(
        request,
        "Candidato assunto: dipendente creato in anagrafica e pratica di onboarding avviata.",
    )
    return redirect("anagrafica:onboarding_detail", pratica_id=pratica.pk)


@login_required
@require_POST
def recruiting_archivia(request, candidato_id: int):
    """Mantiene il profilo nel database Recruiting per future opportunità."""
    if not _can_manage_recruiting(request):
        return _denied(request, "archiviare le schede candidato")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    recruiting_service.archivia_in_database(candidato, user=request.user)
    _audit(request, "RECRUITING_CANDIDATO_ARCHIVIATO", {"candidato_id": candidato.pk})
    messages.success(request, "Profilo mantenuto nel database Recruiting.")
    return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)


@login_required
@require_POST
def recruiting_annulla(request, candidato_id: int):
    """Annulla/archivia la scheda: la toglie dalle liste operative senza cancellarla."""
    if not _can_manage_recruiting(request):
        return _denied(request, "annullare le schede candidato")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    recruiting_service.annulla_scheda(
        candidato, user=request.user, motivo=(request.POST.get("motivo") or ""),
    )
    _audit(request, "RECRUITING_CANDIDATO_ANNULLATO", {"candidato_id": candidato.pk})
    messages.success(
        request,
        "Scheda annullata. Resta consultabile filtrando per stato «Annullato».",
    )
    return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)


@login_required
@require_POST
def recruiting_riapri(request, candidato_id: int):
    """Riapre un iter chiuso, riportando la scheda a uno stato modificabile."""
    if not _can_manage_recruiting(request):
        return _denied(request, "riaprire le schede candidato")

    candidato = get_object_or_404(Candidato, pk=candidato_id)
    if not candidato.iter_chiuso:
        messages.info(request, "L'iter è già aperto.")
        return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)

    nuovo = recruiting_service.riapri_iter(candidato, user=request.user)
    _audit(request, "RECRUITING_CANDIDATO_RIAPERTO", {
        "candidato_id": candidato.pk, "stato": nuovo,
    })
    avviso = "Iter riaperto: la scheda è di nuovo modificabile."
    if candidato.onboarding_pratica_id:
        avviso += " La pratica di onboarding collegata resta invariata."
    messages.success(request, avviso)
    return redirect("anagrafica:recruiting_detail", candidato_id=candidato.pk)


# ---------------------------------------------------------------------------
# Cruscotto KPI
# ---------------------------------------------------------------------------

@login_required
def recruiting_dashboard(request):
    """KPI di processo: volumi, punteggio medio, esiti, tempi, tasso di assunzione."""
    if not _can_view_recruiting(request):
        return _denied(request)

    qs = _filtra_candidati(request)
    canali = dict(Candidato.CANALE_CHOICES)
    stati = dict(Candidato.STATO_CHOICES)

    kpi = recruiting_service.calcola_kpi(qs)
    for riga in kpi["per_canale"]:
        riga["label"] = canali.get(riga["canale_provenienza"], riga["canale_provenienza"])
    for riga in kpi["per_stato"]:
        riga["label"] = stati.get(riga["stato"], riga["stato"])

    return render(request, "anagrafica/pages/recruiting_dashboard.html", {
        "kpi": kpi,
        "filtri": _filtri_correnti(request),
        "stato_choices": Candidato.STATO_CHOICES,
        "canale_choices": Candidato.CANALE_CHOICES,
        "criteri": recruiting_service.criteri_attivi(),
    })


# ---------------------------------------------------------------------------
# Impostazioni criteri
# ---------------------------------------------------------------------------

@login_required
def recruiting_criteri(request):
    """Configurazione dei criteri: pesi, rubriche, attivazione.

    Qui vivono le scelte che il prompt chiede di *segnalare* a HR senza deciderle
    al posto loro: ripesare, disattivare un criterio discutibile, scrivere la
    rubrica dei livelli 1-5.
    """
    if not _can_manage_recruiting(request):
        return _denied(request, "configurare i criteri di valutazione")

    if request.method == "POST":
        criterio_id = (request.POST.get("criterio_id") or "").strip()
        istanza = (
            get_object_or_404(RecruitingCriterio, pk=int(criterio_id)) if criterio_id else None
        )
        form = RecruitingCriterioForm(request.POST, instance=istanza)
        if form.is_valid():
            criterio = form.save()
            _audit(request, "RECRUITING_CRITERIO_SALVATO", {
                "criterio_id": criterio.pk, "codice": criterio.codice,
                "peso": str(criterio.peso_percentuale), "attivo": criterio.is_active,
            })
            # Il peso o l'attivazione sono cambiati: i ponderati salvati non sono
            # più coerenti con la configurazione corrente.
            _ricalcola_tutti()
            messages.success(request, f"Criterio «{criterio.label}» salvato. Punteggi ricalcolati.")
            return redirect("anagrafica:recruiting_criteri")
        messages.error(request, "Controlla i campi evidenziati.")
    else:
        form = RecruitingCriterioForm()

    criteri = list(RecruitingCriterio.objects.all())
    return render(request, "anagrafica/pages/recruiting_criteri.html", {
        "criteri": _righe_configurazione(criteri),
        "form": form,
        "peso_totale_attivi": sum(
            (c.peso_percentuale for c in criteri if c.is_active), start=0,
        ),
        "permessi": RecruitingPermission.get_instance(),
    })


def _righe_configurazione(criteri: list[RecruitingCriterio]) -> list[dict]:
    """Criteri con peso effettivo, usi e posizione, pronti per la tabella.

    Il **peso effettivo** è quello che conta davvero: il punteggio è normalizzato
    sulla somma dei pesi attivi, quindi un criterio al 25% su un totale di 80 pesa
    il 31%. Mostrare solo il peso nominale nasconde questo effetto — ed è la prima
    cosa che confonde quando si disattiva un criterio.
    """
    attivi = [c for c in criteri if c.is_active]
    totale = sum((c.peso_percentuale for c in attivi), start=Decimal("0"))
    usi = {
        riga["criterio"]: riga["n"]
        for riga in CandidatoPunteggio.objects.values("criterio").annotate(n=Count("id"))
    }

    righe = []
    for indice, criterio in enumerate(criteri):
        effettivo = None
        if criterio.is_active and totale > 0:
            effettivo = (criterio.peso_percentuale * 100 / totale).quantize(Decimal("0.1"))
        righe.append({
            "criterio": criterio,
            "peso_effettivo": effettivo,
            "usi": usi.get(criterio.pk, 0),
            "is_first": indice == 0,
            "is_last": indice == len(criteri) - 1,
        })
    return righe


def _ricalcola_tutti() -> int:
    """Ricalcola il ponderato di tutte le schede aperte dopo un cambio di pesi."""
    aggiornati = 0
    for candidato in Candidato.objects.exclude(stato__in=Candidato.STATI_CHIUSI):
        recruiting_service.ricalcola_punteggio(candidato)
        aggiornati += 1
    return aggiornati


@login_required
@require_POST
def recruiting_criterio_toggle(request, criterio_id: int):
    """Attiva/disattiva un criterio senza passare dal form.

    È la leva prevista dalle note UNI/PdR 125: togliere «Vicinanza» dal punteggio
    non cancella nulla, i voti già espressi restano e tornano a contare se il
    criterio viene riattivato.
    """
    if not _can_manage_recruiting(request):
        return _denied(request, "configurare i criteri di valutazione")

    criterio = get_object_or_404(RecruitingCriterio, pk=criterio_id)
    criterio.is_active = not criterio.is_active
    criterio.save(update_fields=["is_active", "updated_at"])
    _ricalcola_tutti()

    _audit(request, "RECRUITING_CRITERIO_TOGGLE", {
        "criterio_id": criterio.pk, "codice": criterio.codice, "attivo": criterio.is_active,
    })
    stato = "attivato" if criterio.is_active else "disattivato"
    messages.success(request, f"Criterio «{criterio.label}» {stato}. Punteggi ricalcolati.")
    return redirect("anagrafica:recruiting_criteri")


@login_required
@require_POST
def recruiting_criterio_delete(request, criterio_id: int):
    """Elimina un criterio mai usato.

    Se esistono già valutazioni la FK è PROTECT e la cancellazione va rifiutata:
    cancellare un criterio votato falsificherebbe lo storico delle decisioni.
    In quel caso la strada è disattivarlo.
    """
    if not _can_manage_recruiting(request):
        return _denied(request, "configurare i criteri di valutazione")

    criterio = get_object_or_404(RecruitingCriterio, pk=criterio_id)
    label = criterio.label

    if CandidatoPunteggio.objects.filter(criterio=criterio).exists():
        messages.error(
            request,
            f"«{label}» è già stato usato in almeno una valutazione: non si può "
            "eliminare senza falsare lo storico. Disattivalo per toglierlo dal punteggio.",
        )
        return redirect("anagrafica:recruiting_criteri")

    try:
        criterio.delete()
    except ProtectedError:
        messages.error(request, f"«{label}» è referenziato da valutazioni esistenti: disattivalo.")
        return redirect("anagrafica:recruiting_criteri")

    _ricalcola_tutti()
    _audit(request, "RECRUITING_CRITERIO_ELIMINATO", {"criterio_id": criterio_id, "label": label})
    messages.success(request, f"Criterio «{label}» eliminato.")
    return redirect("anagrafica:recruiting_criteri")


@login_required
@require_POST
def recruiting_criterio_move(request, criterio_id: int):
    """Sposta un criterio su/giù nell'ordine di comparsa in scheda.

    Scambia il campo ``ordine`` col vicino invece di riscriverlo a mano: l'ordine
    non incide sul punteggio, solo su come si presenta la valutazione.
    """
    if not _can_manage_recruiting(request):
        return _denied(request, "configurare i criteri di valutazione")

    direzione = (request.POST.get("direzione") or "").strip()
    if direzione not in ("su", "giu"):
        messages.error(request, "Direzione di spostamento non valida.")
        return redirect("anagrafica:recruiting_criteri")

    criterio = get_object_or_404(RecruitingCriterio, pk=criterio_id)
    ordinati = list(RecruitingCriterio.objects.all())
    posizione = next((i for i, c in enumerate(ordinati) if c.pk == criterio.pk), None)
    if posizione is None:
        return redirect("anagrafica:recruiting_criteri")

    vicino_pos = posizione - 1 if direzione == "su" else posizione + 1
    if not (0 <= vicino_pos < len(ordinati)):
        return redirect("anagrafica:recruiting_criteri")

    vicino = ordinati[vicino_pos]
    # Se i due condividono lo stesso `ordine` lo scambio non muoverebbe nulla:
    # in quel caso si separano di un punto nella direzione richiesta.
    if criterio.ordine == vicino.ordine:
        criterio.ordine = vicino.ordine + (-1 if direzione == "su" else 1)
    else:
        criterio.ordine, vicino.ordine = vicino.ordine, criterio.ordine
        vicino.save(update_fields=["ordine", "updated_at"])
    criterio.save(update_fields=["ordine", "updated_at"])

    _audit(request, "RECRUITING_CRITERIO_RIORDINATO", {
        "criterio_id": criterio.pk, "direzione": direzione,
    })
    return redirect("anagrafica:recruiting_criteri")
