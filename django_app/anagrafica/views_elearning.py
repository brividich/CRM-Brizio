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
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_formazione import (
    ElearningConfig, TrainingAssignment, TrainingCourse, TrainingElearningEnrollment, TrainingQuizAttempt,
    TrainingSlide,
)
from .services import elearning_fruizione as fruizione
from .services import elearning_quiz as quiz
from .services import elearning_tracciamento as tracciamento
from .services.elearning_regole import regola_corso

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
        # Ordinati per ciclo: nel dizionario vince l'ultimo ciclo (il rinnovo).
        assegnazioni = {
            a.corso_id: a for a in TrainingAssignment.objects.filter(
                legacy_anagrafica_id=legacy_id, stato__in=fruizione.STATI_ASSEGNAZIONE_ATTIVI,
                corso__is_elearning=True,
            ).order_by("ciclo")
        }
    corsi = (
        fruizione.corsi_pubblicati()
        .filter(Q(pk__in=list(assegnazioni)) | Q(elearning_self_service=True))
        .select_related("piano", "categoria")
        .annotate(
            n_slide=Count("slides", filter=Q(slides__is_active=True), distinct=True),
            n_domande=Count("quiz_domande", filter=Q(quiz_domande__is_active=True), distinct=True),
        )
        .order_by("titolo")
    )
    iscrizioni = {}
    if legacy_id:
        iscrizioni = {e.corso_id: e for e in TrainingElearningEnrollment.objects.filter(
            legacy_anagrafica_id=legacy_id).order_by("ciclo")}
        from .models_elearning import TrainingElearningSlideView
        completate = dict(TrainingElearningSlideView.objects.filter(
            enrollment__in=list(iscrizioni.values()), completata=True, slide__is_active=True)
            .values("enrollment_id").annotate(n=Count("pk")).order_by().values_list("enrollment_id", "n"))
    # Completamenti ancora senza questionario di gradimento.
    da_valutare = set()
    from .models_formazione import ElearningConfig
    if iscrizioni and ElearningConfig.get_instance().gradimento_attivo:
        from .models_elearning import TrainingElearningGradimento
        record_ids = {e.record_completamento_id for e in iscrizioni.values() if e.record_completamento_id}
        gia = set(TrainingElearningGradimento.objects.filter(record_id__in=record_ids).values_list("record_id", flat=True))
        da_valutare = record_ids - gia
    cards = []
    oggi = timezone.localdate()
    for c in corsi:
        e = iscrizioni.get(c.pk)
        a = assegnazioni.get(c.pk)
        if e is not None and a is not None and e.ciclo < a.ciclo:
            e = None  # rinnovo assegnato, nuovo ciclo non ancora iniziato
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
            "progress_pct": min(round(completate.get(e.pk, 0) / c.n_slide * 100), 100)
            if e and c.n_slide else 0,
            "da_valutare": bool(completato and e.record_completamento_id in da_valutare),
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
        # Una sola sessione attiva: aprire il player chiude le altre schede.
        tracciamento.avvia_sessione(enr, request)
        # Ripresa: la prima slide non ancora completata (o l'ultima).
        dopo = [o for o in ordini if o > (enr.ultima_slide_ordine or 0)]
        slide_iniziale = dopo[0] if dopo else ordini[-1]
    regola = regola_corso(corso)
    return render(request, "anagrafica/pages/formazione_online_player.html", {
        "corso": corso,
        "slides": slides,
        "n_slide": len(slides),
        "slide_iniziale": slide_iniziale,
        "enrollment": enr,
        "anteprima": accesso.anteprima,
        "no_anagrafica": legacy_id is None,
        "n_domande": corso.quiz_domande.filter(is_active=True).count(),
        "regola": regola,
        "beat_url": reverse("anagrafica:formazione_online_beat", args=[corso.pk]) if enr else "",
        "beat_intervallo": tracciamento.INTERVALLO_MIN_SECONDI,
        "minuti_fatti": (enr.secondi_accreditati or 0) // 60 if enr else 0,
    })


@login_required
def formazione_online_slide(request, corso_id: int, ordine: int):
    """Partial HTMX della slide <ordine>: servita solo in sequenza, poi registrata."""
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito:
        return _nega(request, accesso.motivo or "Corso non disponibile.")
    if not request.headers.get("HX-Request"):
        return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
    slides = list(corso.slides.filter(is_active=True).select_related("modulo").order_by("ordine", "pk"))
    if not slides:
        return HttpResponse('<div class="fmd-empty"><span class="fmd-et">Nessuna slide disponibile</span></div>')
    ordini = [s.ordine for s in slides]
    regola = regola_corso(corso)
    enr = None if accesso.anteprima else fruizione.iscrizione(corso, legacy_id, len(slides))
    if not fruizione.slide_consentita(enr, ordine, ordini):
        return _nega(request, "Prosegui in ordine: completa prima la slide precedente.", htmx_status=409)
    pos = ordini.index(ordine)
    slide = slides[pos]
    secondi_mancanti = 0
    completato = False
    if enr is not None:
        tracciamento.registra_vista(enr, slide, regola, ordini)
        secondi_mancanti = tracciamento.secondi_mancanti_slide(enr, slide, regola)
        completato = _completa_senza_quiz(enr, regola, request.user)

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
        "secondi_mancanti": secondi_mancanti,
        "completato": completato or (enr is not None and enr.stato == "COMPLETATO"),
        "indice_corso": _indice_se_serve(slides, enr, ordini, ordine),
        "gradimento": bool((completato or (enr is not None and enr.stato == "COMPLETATO")) and not accesso.anteprima
                           and _gradimento_da_dare(corso, enr)),
    })


def _indice_se_serve(slides, enr, ordini, ordine):
    """L'indice compare con i moduli o da 4 slide in su; ogni slide è una lezione."""
    if not any(s.modulo_id for s in slides) and len(slides) < 4:
        return []
    return fruizione.indice_corso(slides, enr, ordini, ordine)


def _gradimento_da_dare(corso, enr) -> bool:
    from .services.elearning_gradimento import record_da_valutare
    return enr is not None and record_da_valutare(corso, enr.legacy_anagrafica_id) is not None


def _completa_senza_quiz(enr, regola, user) -> bool:
    """Corso senza quiz obbligatorio: completamento appena i requisiti (slide, tempo) sono soddisfatti."""
    if regola.richiede_quiz or enr.stato == "COMPLETATO":
        return False
    from .services.elearning_completamento import RequisitiNonSoddisfatti, completa
    try:
        completa(enr, tentativo=None, user=user)
        return True
    except RequisitiNonSoddisfatti:
        return False


@login_required
@require_POST
def formazione_online_beat(request, corso_id: int):
    """Heartbeat del player (JSON). Il tempo lo misura il server: il client manda solo segnali."""
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito or accesso.anteprima:
        return JsonResponse({"ok": False, "motivo": "non_consentito"}, status=403)
    import json
    try:
        dati = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "motivo": "payload"}, status=400)
    ordini = fruizione.ordini_slide(corso)
    enr = fruizione.iscrizione(corso, legacy_id, len(ordini))
    try:
        slide_id = int(dati.get("slide_id")) if dati.get("slide_id") is not None else None
        inattivo_ms = max(int(dati.get("inattivo_ms") or 0), 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "motivo": "payload"}, status=400)
    regola = regola_corso(corso)
    esito = tracciamento.beat(enr, slide_id=slide_id, visibile=bool(dati.get("visibile", True)),
                              inattivo_ms=inattivo_ms, regola=regola, ordini=ordini)
    if esito.get("credito"):
        enr.refresh_from_db()
        esito["completato"] = _completa_senza_quiz(enr, regola, request.user)
    esito["minuti_fatti"] = (type(enr).objects.filter(pk=enr.pk).values_list("secondi_accreditati", flat=True).first() or 0) // 60
    return JsonResponse(esito, status=200 if esito.get("ok") or esito.get("motivo") == "troppo_presto" else 409)


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

@login_required
def formazione_online_quiz(request, corso_id: int):
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, is_editor = _ctx_utente(request)
    accesso = fruizione.accesso_discente(corso, legacy_id, is_editor=is_editor)
    if not accesso.consentito:
        return _nega(request, accesso.motivo or "Corso non disponibile.")
    if accesso.anteprima:
        if request.method == "POST":
            messages.info(request, "Anteprima editor: il quiz non viene corretto né registrato.")
            return redirect("anagrafica:formazione_online_quiz", corso_id=corso_id)
        domande = [quiz.DomandaServita(d.pk, d.testo, [(o.pk, o.testo) for o in d.opzioni.all()], d.tipo)
                   for d in quiz.domande_valide(corso)]
        if not domande:
            messages.info(request, "Il quiz non è ancora pronto: nessuna domanda ha una risposta corretta.")
            return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
        return render(request, "anagrafica/pages/formazione_online_quiz.html", {
            "corso": corso, "domande": domande, "esito": None, "anteprima": True, "token": "",
        })

    regola = regola_corso(corso)
    ordini = fruizione.ordini_slide(corso)
    enr = fruizione.iscrizione(corso, legacy_id, len(ordini))

    if request.method != "POST":
        try:
            tentativo = quiz.apri_tentativo(enr, regola, ordini, user=request.user)
        except quiz.QuizNonDisponibile as exc:
            messages.info(request, str(exc))
            return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
        return render(request, "anagrafica/pages/formazione_online_quiz.html", {
            "corso": corso, "domande": quiz.domande_servite(tentativo), "esito": None,
            "token": tentativo.token, "scade_il": tentativo.scade_il,
            "tentativi_rimasti": quiz.tentativi_rimasti(enr, regola),
        })

    risposte = {}
    for chiave in request.POST:
        if chiave.startswith("q_") and chiave[2:].isdigit():
            risposte[int(chiave[2:])] = {int(x) for x in request.POST.getlist(chiave) if str(x).isdigit()}
    try:
        tentativo = quiz.correggi(enr, (request.POST.get("token") or "")[:32], risposte, regola)
    except quiz.QuizNonDisponibile as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:formazione_online_player", corso_id=corso_id)
    completato, mancanti = False, []
    if tentativo.superato:
        from .services.elearning_completamento import RequisitiNonSoddisfatti, completa
        try:
            completa(enr, tentativo=tentativo, user=request.user)
            completato = True
        except RequisitiNonSoddisfatti as exc:
            mancanti = exc.mancanti
    enr.refresh_from_db()
    risposte_snapshot = tentativo.risposte_json.get("risposte", [])
    from .services.elearning_gradimento import record_da_valutare
    gradimento = bool(enr.stato == "COMPLETATO" and record_da_valutare(corso, enr.legacy_anagrafica_id))
    return render(request, "anagrafica/pages/formazione_online_quiz.html", {
        "corso": corso, "domande": [], "token": "",
        "tentativi_rimasti": quiz.tentativi_rimasti(enr, regola),
        "esito": {
            "superato": tentativo.superato, "completato": completato, "mancanti": mancanti,
            "punteggio": tentativo.punteggio_pct, "n_corrette": tentativo.n_corrette,
            "n_totali": tentativo.n_totali, "minimo": regola.soglia_pct,
            # Il dettaglio per domanda solo a quiz superato: con tentativi residui
            # direbbe quali risposte cambiare.
            "risposte": risposte_snapshot if tentativo.superato else [],
        },
        "gradimento": gradimento,
    })


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


# ═══════════════════════════════════════════════════════════════════════════
# Video delle slide: caricamento (editor) e riproduzione con Range (discente)
# ═══════════════════════════════════════════════════════════════════════════

@login_required
@require_POST
def formazione_slide_video_upload(request, corso_id: int):
    """Crea una slide video: MP4 verificato dal contenuto, storage privato."""
    from .views import _can_edit_formazione
    if not _can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    f = request.FILES.get("video")
    titolo = (request.POST.get("titolo") or "").strip()[:300] or "Video"
    if not f:
        messages.error(request, "Seleziona un file video MP4.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
    cfg = ElearningConfig.get_instance()
    try:
        validate_extension_and_mime(f, allowed_extensions={".mp4"}, allowed_mimes={"video/mp4"},
                                    max_bytes=int(cfg.video_max_mb or 500) * 1024 * 1024, label="Video",
                                    allow_empty=False)
    except UploadMimeValidationError as exc:
        messages.error(request, f"Video rifiutato: {exc}")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    from django.db.models import Max
    ordine = (corso.slides.aggregate(m=Max("ordine"))["m"] or 0) + 1
    try:
        durata = max(int(request.POST.get("durata_minima_secondi") or 0), 0)
    except ValueError:
        durata = 0
    slide = TrainingSlide(corso=corso, ordine=ordine, titolo=titolo, tipo=TrainingSlide.TIPO_VIDEO,
                          durata_minima_secondi=min(durata, 32767), created_by=request.user)
    slide.video.save(f.name, f, save=False)
    slide.save()
    log_action(request, "elearning_video_caricato", MODULE, {"corso": corso.pk, "slide": slide.pk}, oggetto=slide)
    messages.success(request, f"Video «{titolo}» aggiunto come slide {ordine}.")
    from .views import _versiona
    _versiona(request, corso, f"Video «{titolo}» aggiunto")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
def formazione_slide_video(request, slide_id: int):
    """Serve il video di una slide (Range per lo scorrimento), solo a chi può fruire del corso."""
    slide = get_object_or_404(TrainingSlide.objects.select_related("corso"), pk=slide_id, tipo=TrainingSlide.TIPO_VIDEO)
    legacy_id, is_editor = _ctx_utente(request)
    if not fruizione.accesso_discente(slide.corso, legacy_id, is_editor=is_editor).consentito:
        return HttpResponse(status=403)
    if not slide.video:
        return HttpResponse("Video non disponibile.", status=404)
    return _risposta_range(request, slide.video, "video/mp4")


def _risposta_range(request, campo_file, content_type: str):
    import re
    from django.http import FileResponse, StreamingHttpResponse

    try:
        dimensione = campo_file.size
        fh = campo_file.open("rb")
    except (FileNotFoundError, OSError):
        return HttpResponse("File non trovato sul server.", status=404)
    intervallo = re.match(r"^bytes=(\d*)-(\d*)$", request.headers.get("Range", "").strip())
    if not intervallo or (not intervallo.group(1) and not intervallo.group(2)):
        resp = FileResponse(fh, content_type=content_type)
        resp["Accept-Ranges"] = "bytes"
    else:
        inizio = int(intervallo.group(1)) if intervallo.group(1) else max(dimensione - int(intervallo.group(2)), 0)
        fine = int(intervallo.group(2)) if intervallo.group(1) and intervallo.group(2) else dimensione - 1
        fine = min(fine, dimensione - 1)
        if inizio > fine:
            fh.close()
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{dimensione}"
            return resp
        fh.seek(inizio)
        lunghezza = fine - inizio + 1

        def _blocchi(restanti=lunghezza, blocco=64 * 1024):
            try:
                while restanti > 0:
                    dati = fh.read(min(blocco, restanti))
                    if not dati:
                        break
                    restanti -= len(dati)
                    yield dati
            finally:
                fh.close()

        resp = StreamingHttpResponse(_blocchi(), status=206, content_type=content_type)
        resp._resource_closers.append(fh.close)  # anche se il client si disconnette prima
        resp["Content-Range"] = f"bytes {inizio}-{fine}/{dimensione}"
        resp["Content-Length"] = str(lunghezza)
        resp["Accept-Ranges"] = "bytes"
    resp["Content-Disposition"] = "inline"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, max-age=300"
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# Impostazioni: quali corsi sono online e con quali regole (FAD, conferma RSPP)
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def elearning_impostazioni_corsi(request):
    """Elenco dei corsi con l'interruttore «erogabile online» e lo stato della regola FAD."""
    from .views import _can_edit_formazione
    if not _can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per le impostazioni e-learning.")
        return redirect("anagrafica:formazione_dashboard")
    from .models_formazione import TrainingCompletionRule
    if request.method == "POST":
        corso = get_object_or_404(TrainingCourse, pk=request.POST.get("corso_id") or 0)
        azione = request.POST.get("azione")
        if azione == "online":
            corso.is_elearning = not corso.is_elearning
            if not corso.is_elearning and corso.stato == "ATTIVO":
                messages.info(request, "Il corso resta pubblicato per l'aula; non è più erogabile online.")
            corso.save(update_fields=["is_elearning", "updated_at"])
        elif azione == "self_service":
            corso.elearning_self_service = not corso.elearning_self_service
            corso.save(update_fields=["elearning_self_service", "updated_at"])
        log_action(request, "elearning_impostazione_corso", MODULE,
                   {"corso": corso.pk, "azione": azione, "is_elearning": corso.is_elearning,
                    "self_service": corso.elearning_self_service}, oggetto=corso)
        return redirect(f"{reverse('anagrafica:elearning_impostazioni_corsi')}?q={request.POST.get('q', '')}")
    q = (request.GET.get("q") or "").strip()
    qs = TrainingCourse.objects.filter(is_active=True).order_by("-is_elearning", "titolo")
    if q:
        qs = qs.filter(Q(titolo__icontains=q) | Q(codice__icontains=q))
    corsi = list(qs[:300])
    regole = {r.corso_id: r for r in TrainingCompletionRule.objects.filter(corso__in=corsi)}
    for c in corsi:
        c.regola_fad = regole.get(c.pk)
    return render(request, "anagrafica/pages/elearning_impostazioni_corsi.html", {
        "page_title": "Impostazioni e-learning", "corsi": corsi, "q": q,
    })


@login_required
def elearning_regola_corso(request, corso_id: int):
    """Regola FAD del corso: modificabile da HR; la conferma la dà l'RSPP (permesso dedicato)."""
    from .forms_elearning import ElearningRegolaForm
    from .models_formazione import TrainingCompletionRule
    from .services.elearning_regole import CAMPI_FAD, puo_confermare_fad
    from .views import _can_edit_formazione

    if not _can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per le impostazioni e-learning.")
        return redirect("anagrafica:formazione_dashboard")
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    regola, _ = TrainingCompletionRule.objects.get_or_create(corso=corso)
    puo_confermare = puo_confermare_fad(request.user)
    form = ElearningRegolaForm(instance=regola)
    if request.method == "POST":
        if request.POST.get("azione") == "conferma":
            if not puo_confermare:
                messages.error(request, "Solo l'RSPP (o chi ha il permesso dedicato) può confermare le regole.")
            else:
                regola.confermata_rspp_da = request.user
                regola.confermata_rspp_il = timezone.now()
                regola.save(update_fields=["confermata_rspp_da", "confermata_rspp_il"])
                log_action(request, "elearning_regola_confermata", MODULE,
                           {"corso": corso.pk, "regola": {k: getattr(regola, k) for k in CAMPI_FAD}}, oggetto=regola)
                messages.success(request, "Regole FAD confermate.")
            return redirect("anagrafica:elearning_regola_corso", corso_id=corso.pk)
        prima = {k: getattr(regola, k) for k in CAMPI_FAD}
        form = ElearningRegolaForm(request.POST, instance=regola)
        if form.is_valid():
            regola = form.save(commit=False)
            dopo = {k: getattr(regola, k) for k in CAMPI_FAD}
            cambiate = prima != dopo
            if cambiate and regola.confermata_rspp_il:
                # Ogni modifica annulla la conferma: l'RSPP deve rivederle.
                regola.confermata_rspp_da = None
                regola.confermata_rspp_il = None
            regola.save()
            log_action(request, "elearning_regola_modificata", MODULE,
                       {"corso": corso.pk, "prima": prima, "dopo": dopo}, oggetto=regola)
            messages.success(request, "Regole salvate." + (" La conferma RSPP va ripetuta." if cambiate else ""))
            return redirect("anagrafica:elearning_regola_corso", corso_id=corso.pk)
    return render(request, "anagrafica/pages/elearning_regola_corso.html", {
        "page_title": f"Regole FAD · {corso.titolo}", "corso": corso, "regola": regola, "form": form,
        "puo_confermare": puo_confermare,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Cruscotto Direzione e registro di audit
# ═══════════════════════════════════════════════════════════════════════════

def _puo_report(request) -> bool:
    from .views import _can_view_formazione
    return _can_view_formazione(request)


@login_required
def elearning_cruscotto(request):
    if not _puo_report(request):
        messages.error(request, "Non hai i permessi per la reportistica della formazione.")
        return redirect("anagrafica:formazione_dashboard")
    from .services import elearning_report as report
    reparto = (request.GET.get("reparto") or "").strip()
    corso_id = int(request.GET["corso"]) if (request.GET.get("corso") or "").isdigit() else None
    cop = report.copertura(reparto=reparto, corso_id=corso_id)
    ctx = {
        "page_title": "Cruscotto e-learning", "copertura": cop, "andamento": report.andamento(),
        "domande": report.domande_piu_sbagliate(), "reparto": reparto, "corso_id": corso_id,
        "corsi_opts": fruizione.corsi_pubblicati().order_by("titolo"),
        "persone": cop["persone"][:200] if reparto or corso_id else [],
        "qualita": _qualita_corsi(corso_id),
    }
    if request.headers.get("HX-Request") and request.GET.get("parte") == "persone":
        return render(request, "anagrafica/partials/_elearning_persone.html", ctx)
    return render(request, "anagrafica/pages/elearning_cruscotto.html", ctx)


def _qualita_corsi(corso_id=None) -> dict:
    """Gradimento (reazione a fine corso) ed efficacia (verifica sul campo) per corso."""
    from .services import elearning_gradimento as grad

    corsi = {c.pk: c.titolo for c in TrainingCourse.objects.filter(is_elearning=True)
             .filter(**({"pk": corso_id} if corso_id else {})).only("titolo")}
    gradimento = grad.per_corso(corsi)
    efficacia = grad.efficacia_per_corso(corsi)
    righe = [{"titolo": titolo, "gradimento": gradimento.get(pk), "efficacia": efficacia.get(pk)}
             for pk, titolo in corsi.items() if pk in gradimento or pk in efficacia]
    righe.sort(key=lambda r: r["titolo"].lower())
    return {"righe": righe, "commenti": grad.commenti_recenti(corso_id=corso_id)}


@login_required
def elearning_registro(request):
    if not _puo_report(request):
        messages.error(request, "Non hai i permessi per la reportistica della formazione.")
        return redirect("anagrafica:formazione_dashboard")
    from datetime import date
    from .services import elearning_report as report

    def _data(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None

    corso_id = int(request.GET["corso"]) if (request.GET.get("corso") or "").isdigit() else None
    righe = report.registro(corso_id=corso_id, dal=_data(request.GET.get("dal")), al=_data(request.GET.get("al")))
    return render(request, "anagrafica/pages/elearning_registro.html", {
        "page_title": "Registro e-learning", "righe": righe[:500], "n_righe": len(righe), "corso_id": corso_id,
        "corsi_opts": TrainingCourse.objects.filter(is_elearning=True).order_by("titolo"),
        "dal": request.GET.get("dal", ""), "al": request.GET.get("al", ""),
    })


# -- Verifica di autenticità dell'attestato (prompt 05, fase 2) ----------------

VERIFICHE_MAX = 30          # tentativi per utente …
VERIFICHE_FINESTRA = 600    # … ogni 10 minuti


@login_required
def formazione_verifica_attestato(request, codice: str = ""):
    """Pagina di verifica: solo il minimo (nome, corso, date, protocollo, esito).

    Aperta a ogni utente autenticato del portale (prefisso shared). Il codice ha
    ~59 bit casuali; un limite per utente rende comunque inutile tirare a indovinare."""
    from django.core.cache import cache
    from .services import attestato_verifica as av

    if request.method == "POST":
        digitato = av.normalizza(request.POST.get("codice", ""))
        if digitato:
            return redirect("anagrafica:formazione_verifica_attestato_codice", codice=av.formatta(digitato))
        return redirect("anagrafica:formazione_verifica_attestato")

    esito = None
    limitato = False
    if codice:
        chiave = f"elearning:verifica:{request.user.pk}"
        n = cache.get(chiave, 0)
        if n >= VERIFICHE_MAX:
            limitato = True
        else:
            cache.set(chiave, n + 1, VERIFICHE_FINESTRA)
            esito = av.verifica(codice)
            logger.info("Verifica attestato: utente %s esito %s", request.user.pk, esito.stato)
    resp = render(request, "anagrafica/pages/formazione_verifica_attestato.html", {
        "esito": esito, "codice": av.formatta(av.normalizza(codice)) if codice else "", "limitato": limitato,
        "STATI": {"VALIDO": av.VALIDO, "SCADUTO": av.SCADUTO, "NON_VALIDO": av.NON_VALIDO,
                  "SCONOSCIUTO": av.SCONOSCIUTO, "ALTERATO": av.ALTERATO},
    }, status=429 if limitato else 200)
    resp["Referrer-Policy"] = "no-referrer"
    return resp


# -- Questionario di gradimento (prompt 05, fase 2) ----------------------------

@login_required
def formazione_online_gradimento(request, corso_id: int):
    """Giudizio del discente sul corso appena completato (facoltativo, una volta)."""
    from .services import elearning_gradimento as grad

    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    legacy_id, _is_editor = _ctx_utente(request)
    record = grad.record_da_valutare(corso, legacy_id)
    if record is None:
        messages.info(request, "Non c'è un corso completato da valutare, o hai già lasciato il tuo giudizio.")
        return redirect("anagrafica:formazione_online_catalog")
    domande = grad.domande()
    errore = ""
    voti = {}
    if request.method == "POST":
        voti = {i: request.POST.get(f"v_{i}", "") for i in range(len(domande))}
        try:
            grad.salva(record, [voti[i] for i in range(len(domande))], request.POST.get("commento", ""))
        except grad.GradimentoNonValido as exc:
            errore = str(exc)
        else:
            messages.success(request, "Grazie: il tuo giudizio aiuta a migliorare il corso.")
            return redirect("anagrafica:formazione_online_catalog")
    return render(request, "anagrafica/pages/formazione_online_gradimento.html", {
        "corso": corso, "domande": list(enumerate(domande)), "voti": voti, "errore": errore,
        "scala": [(1, "Per niente"), (2, "Poco"), (3, "Abbastanza"), (4, "Molto"), (5, "Del tutto")],
        "commento": request.POST.get("commento", "") if request.method == "POST" else "",
    }, status=400 if errore else 200)
