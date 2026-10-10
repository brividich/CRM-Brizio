"""Area del discente e-learning: catalogo, player (slide HTMX), quiz, immagini slide.

Spostate da ``views.py`` (rilascio 1 del prompt 05) per chiudere le falle di
accesso: ogni view verifica server-side che il corso sia pubblicato e che il
discente ne abbia diritto (assegnato, o corso facoltativo), che le slide siano
viste in sequenza e che il quiz sia disponibile. Il completamento è registrato
una sola volta, sotto lock dell'iscrizione. Le regole stanno in
:mod:`anagrafica.services.elearning_fruizione`.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_formazione import (
    ElearningConfig, TrainingAssignment, TrainingCourse, TrainingElearningEnrollment, TrainingQuizAttempt,
    TrainingSlide,
)
from .services import elearning_fruizione as fruizione

logger = logging.getLogger(__name__)
MODULE = "anagrafica"


def _ctx_utente(request):
    from .views import _can_edit_formazione, _current_legacy_anagrafica_id
    return _current_legacy_anagrafica_id(request), _can_edit_formazione(request)


def _nega(request, testo: str, *, htmx_status: int = 403):
    if request.headers.get("HX-Request"):
        return HttpResponse(f'<div class="fmd-empty"><span class="fmd-et">{testo}</span></div>', status=htmx_status)
    messages.error(request, testo)
    return redirect("anagrafica:formazione_online_catalog")


# ═══════════════════════════════════════════════════════════════════════════
# Catalogo
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def formazione_online_catalog(request):
    """I corsi e-learning del discente: assegnati (in evidenza) e facoltativi."""
    legacy_id, is_editor = _ctx_utente(request)
    assegnazioni = {}
    if legacy_id:
        assegnazioni = {
            a.corso_id: a for a in TrainingAssignment.objects.filter(
                legacy_anagrafica_id=legacy_id, stato__in=fruizione.STATI_ASSEGNAZIONE_ATTIVI,
                corso__is_elearning=True,
            )
        }
    corsi = (
        TrainingCourse.objects.filter(is_elearning=True, is_active=True, stato="ATTIVO")
        .filter(Q(pk__in=list(assegnazioni)) | Q(obbligatorio=False))
        .select_related("piano", "categoria")
        .annotate(
            n_slide=Count("slides", filter=Q(slides__is_active=True), distinct=True),
            n_domande=Count("quiz_domande", filter=Q(quiz_domande__is_active=True), distinct=True),
        )
        .order_by("titolo")
    )
    iscrizioni = {}
    if legacy_id:
        iscrizioni = {e.corso_id: e for e in TrainingElearningEnrollment.objects.filter(legacy_anagrafica_id=legacy_id)}
    cards = []
    oggi = timezone.localdate()
    for c in corsi:
        e = iscrizioni.get(c.pk)
        a = assegnazioni.get(c.pk)
        completato = bool(e and e.stato == "COMPLETATO")
        da_fare = bool(a) and a.stato not in ("COMPLETATO", "ESONERATO") and not completato
        cards.append({
            "corso": c,
            "stato": e.stato if e else None,
            "best_pct": e.best_punteggio_pct if e else None,
            "n_slide": c.n_slide,
            "n_domande": c.n_domande,
            "assegnato": bool(a),
            "assegnato_da_fare": da_fare,
            "due_date": a.due_date if a else None,
            "in_ritardo": bool(da_fare and a.due_date and a.due_date < oggi),
            "progress_pct": round((e.ultima_slide_ordine or 0) / e.n_slide_totali * 100)
            if e and e.n_slide_totali else 0,
        })
    cards.sort(key=lambda x: (not x["assegnato_da_fare"], x["due_date"] or oggi.max, x["corso"].titolo.lower()))
    return render(request, "anagrafica/pages/formazione_online_catalog.html", {
        "cards": cards,
        "no_anagrafica": legacy_id is None,
        "is_editor": is_editor,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Player e slide
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def formazione_online_player(request, corso_id: int):
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito:
        return _nega(request, accesso.motivo or "Corso non disponibile.")
    slides = list(corso.slides.filter(is_active=True).order_by("ordine", "pk"))
    ordini = [s.ordine for s in slides]
    enr = None
    slide_iniziale = ordini[0] if ordini else 1
    if not accesso.anteprima and legacy_id and slides:
        enr = fruizione.iscrizione(corso, legacy_id, len(slides))
        # Ripresa: l'ultima slide raggiunta (o la prima).
        raggiunte = [o for o in ordini if o <= (enr.ultima_slide_ordine or 0)]
        slide_iniziale = raggiunte[-1] if raggiunte else ordini[0]
    return render(request, "anagrafica/pages/formazione_online_player.html", {
        "corso": corso,
        "slides": slides,
        "n_slide": len(slides),
        "slide_iniziale": slide_iniziale,
        "enrollment": enr,
        "anteprima": accesso.anteprima,
        "no_anagrafica": legacy_id is None,
        "n_domande": corso.quiz_domande.filter(is_active=True).count(),
    })


@login_required
def formazione_online_slide(request, corso_id: int, ordine: int):
    """Partial HTMX della slide <ordine>: servita solo in sequenza, poi segnata come vista."""
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito:
        return _nega(request, accesso.motivo or "Corso non disponibile.")
    if not request.headers.get("HX-Request"):
        return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
    slides = list(corso.slides.filter(is_active=True).order_by("ordine", "pk"))
    if not slides:
        return HttpResponse('<div class="fmd-empty"><span class="fmd-et">Nessuna slide disponibile</span></div>')
    ordini = [s.ordine for s in slides]
    enr = None if accesso.anteprima else fruizione.iscrizione(corso, legacy_id, len(slides))
    if not fruizione.slide_consentita(enr, ordine, ordini):
        return _nega(request, "Prosegui in ordine: questa slide non è ancora disponibile.", htmx_status=409)
    pos = ordini.index(ordine)
    slide = slides[pos]
    if enr is not None:
        enr = fruizione.segna_slide_vista(corso, legacy_id, slide.ordine, len(slides))

    from .services.elearning_markdown import render_markdown
    return render(request, "anagrafica/partials/_formazione_online_slide.html", {
        "corso": corso,
        "slide": slide,
        "contenuto_html": render_markdown(slide.contenuto),
        "indice": pos + 1,
        "n_slide": len(slides),
        "ordine_prec": ordini[pos - 1] if pos > 0 else None,
        "ordine_succ": ordini[pos + 1] if pos < len(slides) - 1 else None,
        "is_ultima": pos == len(slides) - 1,
        "n_domande": corso.quiz_domande.filter(is_active=True).count(),
        "progress_pct": round((pos + 1) / len(slides) * 100),
        "anteprima": accesso.anteprima,
    })


@login_required
def formazione_slide_image(request, slide_id: int):
    """Immagine di una slide dallo storage privato, solo a chi può fruire del corso."""
    slide = get_object_or_404(TrainingSlide.objects.select_related("corso"), pk=slide_id)
    legacy_id, is_editor = _ctx_utente(request)
    if not fruizione.accesso_discente(slide.corso, legacy_id, is_editor=is_editor).consentito:
        return HttpResponse(status=403)
    if not slide.immagine:
        return HttpResponse("Immagine non disponibile.", status=404)
    from django.http import FileResponse
    try:
        fh = slide.immagine.open("rb")
    except FileNotFoundError:
        return HttpResponse("Immagine non trovata sul server.", status=404)
    resp = FileResponse(fh, content_type="image/png")
    resp["Content-Disposition"] = f'inline; filename="slide_{slide.pk}.png"'
    resp["Cache-Control"] = "private, max-age=300"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# Quiz
# ═══════════════════════════════════════════════════════════════════════════

def _domande_valide(corso) -> list:
    domande = list(corso.quiz_domande.filter(is_active=True).prefetch_related("opzioni"))
    # Una domanda senza risposta corretta non è indovinabile: esclusa finché l'autore non la completa.
    return [d for d in domande if any(o.corretta for o in d.opzioni.all())]


@login_required
def formazione_online_quiz(request, corso_id: int):
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito:
        return _nega(request, accesso.motivo or "Corso non disponibile.")
    domande = _domande_valide(corso)
    if not domande:
        messages.info(request, "Il quiz non è ancora pronto.")
        return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
    if accesso.anteprima:
        if request.method == "POST":
            messages.info(request, "Anteprima editor: il quiz non viene corretto né registrato.")
            return redirect("anagrafica:formazione_online_quiz", corso_id=corso_id)
        return render(request, "anagrafica/pages/formazione_online_quiz.html", {
            "corso": corso, "domande": domande, "no_anagrafica": False, "esito": None, "anteprima": True,
        })

    ordini = fruizione.ordini_slide(corso)
    cfg = ElearningConfig.get_instance()
    enr = fruizione.iscrizione(corso, legacy_id, len(ordini))
    blocco = _blocco_quiz(enr, ordini, cfg)
    if blocco:
        messages.info(request, blocco)
        return redirect("anagrafica:formazione_online_player", corso_id=corso_id)

    if request.method != "POST":
        return render(request, "anagrafica/pages/formazione_online_quiz.html", {
            "corso": corso, "domande": domande, "no_anagrafica": False, "esito": None,
            "tentativi_rimasti": _tentativi_rimasti(enr, cfg),
        })

    n_totali = len(domande)
    n_corrette = 0
    risposte = []
    for d in domande:
        scelte = {int(x) for x in request.POST.getlist(f"q_{d.pk}") if str(x).isdigit()}
        corrette = {o.pk for o in d.opzioni.all() if o.corretta}
        giusta = bool(corrette) and scelte == corrette
        n_corrette += giusta
        risposte.append({"domanda_id": d.pk, "domanda": d.testo, "scelte": sorted(scelte),
                         "corrette": sorted(corrette), "giusta": giusta})
    punteggio = Decimal(str(round(n_corrette / n_totali * 100, 2))) if n_totali else Decimal("0")
    superato = punteggio >= corso.quiz_punteggio_minimo

    with transaction.atomic():
        # Lock dell'iscrizione: conteggio tentativi e completamento senza corse.
        enr = TrainingElearningEnrollment.objects.select_for_update().get(pk=enr.pk)
        blocco = _blocco_quiz(enr, ordini, cfg)
        if blocco:
            transaction.set_rollback(True)
            messages.info(request, blocco)
            return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
        attempt = TrainingQuizAttempt.objects.create(
            corso=corso, enrollment=enr, legacy_anagrafica_id=legacy_id, punteggio_pct=punteggio,
            n_corrette=n_corrette, n_totali=n_totali, superato=superato,
            risposte_json={"risposte": risposte}, utente=request.user,
        )
        enr.n_tentativi = (enr.n_tentativi or 0) + 1
        if enr.best_punteggio_pct is None or punteggio > enr.best_punteggio_pct:
            enr.best_punteggio_pct = punteggio
        campi = ["n_tentativi", "best_punteggio_pct", "updated_at"]
        if superato:
            from .views import _crea_record_completamento_elearning
            enr.stato = "COMPLETATO"
            enr.data_completamento = timezone.localdate()
            campi += ["stato", "data_completamento"]
            if not enr.record_completamento_id:
                record = _crea_record_completamento_elearning(corso, legacy_id, attempt, request.user)
                enr.record_completamento = record
                attempt.record = record
                attempt.save(update_fields=["record"])
                campi.append("record_completamento")
            TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).exclude(
                stato__in=("COMPLETATO", "ESONERATO")).update(stato="COMPLETATO")
        else:
            enr.stato = "NON_SUPERATO"
            campi.append("stato")
        enr.save(update_fields=list(dict.fromkeys(campi)))

    return render(request, "anagrafica/pages/formazione_online_quiz.html", {
        "corso": corso, "domande": domande, "no_anagrafica": False,
        "tentativi_rimasti": _tentativi_rimasti(enr, cfg),
        "esito": {
            "superato": superato, "punteggio": punteggio, "n_corrette": n_corrette, "n_totali": n_totali,
            "minimo": corso.quiz_punteggio_minimo,
            # Il dettaglio per domanda solo a quiz superato: con tentativi residui
            # direbbe quali risposte cambiare.
            "risposte": risposte if superato else [],
        },
    })


def _blocco_quiz(enr, ordini, cfg) -> str:
    if enr.stato == "COMPLETATO":
        return "Hai già completato questo corso."
    if not fruizione.tutte_viste(enr, ordini):
        return "Il quiz si apre dopo aver visto tutte le slide."
    if fruizione.tentativi_esauriti(enr, cfg):
        return "Hai esaurito i tentativi disponibili: chiedi a HR lo sblocco."
    return ""


def _tentativi_rimasti(enr, cfg):
    massimo = fruizione.tentativi_massimi(enr, cfg)
    return max(massimo - (enr.n_tentativi or 0), 0) if massimo else None


# ═══════════════════════════════════════════════════════════════════════════
# HR: sblocco tentativi
# ═══════════════════════════════════════════════════════════════════════════

@login_required
@require_POST
def formazione_elearning_sblocca(request, corso_id: int, enrollment_id: int):
    from .views import _can_edit_formazione
    if not _can_edit_formazione(request):
        if request.headers.get("Accept", "").startswith("application/json"):
            return JsonResponse({"error": "forbidden"}, status=403)
        messages.error(request, "Non hai i permessi per sbloccare i tentativi.")
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
    enr = get_object_or_404(TrainingElearningEnrollment, pk=enrollment_id, corso_id=corso_id)
    try:
        enr, aggiunti = fruizione.sblocca_tentativi(enr, user=request.user, motivo=request.POST.get("motivo"))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
    log_action(request, "elearning_tentativi_sbloccati", MODULE, {
        "corso": corso_id, "enrollment": enr.pk, "legacy_anagrafica_id": enr.legacy_anagrafica_id,
        "aggiunti": aggiunti, "motivo": (request.POST.get("motivo") or "").strip()[:300],
    }, oggetto=enr)
    messages.success(request, f"Sbloccati {aggiunti} tentativi.")
    return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
