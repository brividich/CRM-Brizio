"""Viste anagrafica — Formazione: corsi, edizioni, piani, attestati, ricerca.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import (
    HttpResponse, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.utils import timezone as django_timezone
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import safe_csv_writer
from core.legacy_utils import get_legacy_user, is_legacy_admin

from ..forms import (
    AttestatoFormazioneConfigForm,
    ElearningConfigForm,
    TrainingCompletamentoDirettoForm,
    TrainingCompletionRuleForm,
    TrainingCourseDependencyForm,
    TrainingCourseForm,
    TrainingCourseVersionForm,
    TrainingDividiGruppiForm,
    TrainingEnrollmentEditForm,
    TrainingInstructorForm,
    TrainingLessonAttendanceForm,
    TrainingLessonForm,
    TrainingLezioniGeneraForm,
    TrainingPlanForm,
    TrainingProviderDocumentForm,
    TrainingProviderForm,
    TrainingRequirementRuleForm,
    TrainingSessioneUnicaForm,
    TrainingSessionForm,
    TrainingSlideForm,
    TrainingQuizQuestionForm,
    TrainingQuizOptionForm,
)
from ..models import (
    DipendenteAnagraficaAziendale,
    DocumentoDipendente,
    TipoQualifica,
    TipoVisitaMedica,
)
from ..models_formazione import (
    AttestatoFormazioneConfig,
    ElearningConfig,
    TrainingAssignment,
    TrainingAttachment,
    TrainingCertificate,
    TrainingCompletionRule,
    TrainingCourse,
    TrainingCourseArgomento,
    TrainingCourseDependency,
    TrainingCourseModule,
    TrainingCourseVersion,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingInstructor,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingExportLog,
    TrainingPlan,
    TrainingProvider,
    TrainingProviderDocument,
    TrainingRequirementRule,
    TrainingSession,
    TrainingSessionArgomento,
    TrainingScanIntakeConfig,
    TrainingScanLog,
    TrainingSignatureSheet,
    TrainingSlide,
    TrainingQuizQuestion,
    TrainingQuizOption,
    TrainingElearningEnrollment,
)
from ..acl_bootstrap import (
    PERM_FORMAZIONE_APPROVE,
)
from core.upload_limits import DOCUMENT_MAX_BYTES, DOCUMENT_MAX_MB

from ..models_rischi import CategoriaCorso, EsposizioneRischio, FattoreRischio
from ..forms import (
    CategoriaCorsoForm,
    EsposizioneRischioForm,
    FattoreRischioForm,
)

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Attestato di formazione — foglio A4 autogenerato (layout email NOVICROM HUB)
# ---------------------------------------------------------------------------

@login_required
def attestato_formazione(request, record_id: int):
    """Attestato autogenerato per un singolo completamento corso.

    Foglio A4 stampabile nello stile delle email NOVICROM HUB (header navy con
    logo + banda arancio). Vale per corsi, qualifiche e formazione interna
    generica ("altro"): il tipo viene derivato dalla qualifica àncora del corso.
    Riporta i dati del corso e del dipendente e due blocchi firma —
    Responsabile del corso e Dipendente. Nulla viene scritto: l'attestato si
    autogenera dal record di completamento (campi snapshot per stabilità
    storica). La generazione è tracciata in `TrainingExportLog` (tipo ATTESTATO).
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la formazione.")
        return redirect("anagrafica:formazione_dashboard")

    record = get_object_or_404(
        TrainingEmployeeRecord.objects.select_related(
            "corso", "corso__piano", "corso__qualifica",
            "sessione", "sessione__docente",
        ),
        pk=record_id,
    )

    # Derivazione condivisa con il builder PDF (tipo, responsabile, nominativo,
    # sede, numero, dati anagrafici) — un'unica fonte di verità.
    from ..services.attestato_pdf import build_attestato_context, _documento_esistente
    ctx = build_attestato_context(record, request=request)
    legacy_id = ctx["legacy_id"]

    # Variante "stampa": layout sobrio a basso consumo d'inchiostro (B/N),
    # mantenendo la versione a colori come default.
    stile = (request.GET.get("stile") or "").strip().lower()
    is_stampa = stile == "stampa"
    template_name = (
        "anagrafica/pages/attestato_formazione_stampa.html" if is_stampa
        else "anagrafica/pages/attestato_formazione.html"
    )

    try:
        TrainingExportLog.objects.create(
            tipo="ATTESTATO",
            filtri_json={
                "record_id": record.pk,
                "legacy_anagrafica_id": legacy_id,
                "formato": "attestato_stampa_html" if is_stampa else "attestato_html",
            },
            righe_esportate=1,
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore registrazione TrainingExportLog per attestato record %s", record_id)

    return render(request, template_name, {
        **ctx,
        "stile": stile,
        "can_edit": _helpers._can_edit_formazione(request),
        "doc_archiviato": _documento_esistente(record),
    })


@login_required
def attestato_impostazioni(request):
    """Impostazioni del template attestato di formazione (singleton).

    Gestione dei testi fissi (intestazioni, formule, etichette firma, nota
    legale, logo) e del toggle privacy dei dati personali, da Impostazioni
    Anagrafica HR. Gated dallo stesso permesso di modifica della formazione.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare le impostazioni della formazione.")
        return redirect("anagrafica:formazione_dashboard")

    from ..services.attestato_pdf import RIFERIMENTO_TIPO, archivia_attestato

    cfg = AttestatoFormazioneConfig.get_instance()
    form = AttestatoFormazioneConfigForm(instance=cfg)

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()

        # ── Azioni di gestione archivio report ───────────────────────────
        if action == "backfill":
            # Genera e archivia gli attestati mancanti per i completamenti
            # esistenti (idempotente, bounded). Fail-safe per singolo record.
            mancanti = list(
                TrainingEmployeeRecord.objects.exclude(
                    pk__in=DocumentoDipendente.objects.filter(
                        oggetto_riferimento_tipo=RIFERIMENTO_TIPO
                    ).values_list("oggetto_riferimento_id", flat=True)
                ).order_by("-data_completamento", "-id")[:500]
            )
            ok = err = 0
            for rec in mancanti:
                try:
                    archivia_attestato(rec, cfg=cfg, user=request.user)
                    ok += 1
                except Exception:
                    err += 1
                    logger.exception("Backfill attestato fallito per record %s", rec.pk)
            messages.success(
                request,
                f"Archiviazione completata: {ok} attestati generati"
                + (f", {err} errori" if err else "")
                + (". Limite di 500 per esecuzione: rilancia se restano completamenti." if len(mancanti) >= 500 else "."),
            )
            return redirect("anagrafica:attestato_impostazioni")

        if action == "purge":
            qs = DocumentoDipendente.objects.filter(oggetto_riferimento_tipo=RIFERIMENTO_TIPO)
            n = qs.count()
            for doc in qs:
                try:
                    doc.file.delete(save=False)
                except Exception:
                    logger.warning("File attestato non eliminabile (doc %s)", doc.pk, exc_info=True)
            qs.delete()
            try:
                from core.audit import log_action
                log_action(request, "ATTESTATI_ARCHIVIO_PURGE", "anagrafica", {"eliminati": n})
            except Exception:
                logger.warning("Audit ATTESTATI_ARCHIVIO_PURGE fallito", exc_info=True)
            messages.success(request, f"Archivio attestati svuotato: {n} documenti eliminati.")
            return redirect("anagrafica:attestato_impostazioni")

        # ── Salvataggio impostazioni (default) ───────────────────────────
        form = AttestatoFormazioneConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Impostazioni attestato salvate.")
            return redirect("anagrafica:attestato_impostazioni")
        messages.error(request, "Controlla i campi evidenziati.")

    # Statistiche archivio (per la sezione "Gestione report salvati").
    from datetime import date as _date, timedelta as _timedelta
    arch_qs = DocumentoDipendente.objects.filter(oggetto_riferimento_tipo=RIFERIMENTO_TIPO)
    n_archiviati = arch_qs.count()
    ultimo = arch_qs.order_by("-created_at").values_list("created_at", flat=True).first()
    n_completamenti = TrainingEmployeeRecord.objects.count()

    # Stato conservazione GDPR (retention_until calcolata su DocumentoDipendente).
    # Il command `cleanup_expired_documents` elimina solo i doc scaduti di cessati.
    _oggi = _date.today()
    n_retention_scaduta = arch_qs.filter(retention_until__lt=_oggi).count()
    n_retention_vicina = arch_qs.filter(
        retention_until__gte=_oggi, retention_until__lte=_oggi + _timedelta(days=90)
    ).count()

    # Record di esempio per il pulsante "anteprima" (il più recente disponibile).
    sample = TrainingEmployeeRecord.objects.order_by("-data_completamento", "-id").first()
    return render(request, "anagrafica/pages/attestato_impostazioni.html", {
        "form": form,
        "cfg": cfg,
        "sample_record_id": sample.pk if sample else None,
        "n_archiviati": n_archiviati,
        "n_completamenti": n_completamenti,
        "n_mancanti": max(0, n_completamenti - n_archiviati),
        "ultimo_archiviato": ultimo,
        "n_retention_scaduta": n_retention_scaduta,
        "n_retention_vicina": n_retention_vicina,
    })


@login_required
@require_POST
def attestato_salva_box(request, record_id: int):
    """Genera e salva (manualmente) l'attestato nel box documenti del dipendente.

    Pulsante «💾 Salva nel box» dalla pagina attestato. Forza la rigenerazione
    così l'utente ottiene sempre la versione aggiornata. Gated dal permesso di
    modifica formazione (scrive nello spazio documenti del dipendente).
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per archiviare gli attestati.")
        return redirect("anagrafica:attestato_formazione", record_id=record_id)

    record = get_object_or_404(TrainingEmployeeRecord, pk=record_id)
    from ..services.attestato_pdf import archivia_attestato
    try:
        doc = archivia_attestato(record, user=request.user, force=True)
        messages.success(
            request,
            f"Attestato archiviato nel box del dipendente ({doc.nome_originale}).",
        )
    except Exception:
        logger.exception("Archiviazione manuale attestato fallita per record %s", record_id)
        messages.error(request, "Errore durante l'archiviazione dell'attestato.")
    return redirect("anagrafica:attestato_formazione", record_id=record_id)


@login_required
def attestato_report_export(request):
    """Esporta in CSV l'elenco degli attestati archiviati (riepilogo audit).

    Gated dal permesso di visualizzazione formazione. Nessun dato sanitario;
    contiene riferimento dipendente, corso e metadati del documento.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per esportare i report.")
        return redirect("anagrafica:attestato_impostazioni")

    from ..services.attestato_pdf import RIFERIMENTO_TIPO

    nomi_map = _helpers._build_nomi_map()
    docs = list(
        DocumentoDipendente.objects
        .filter(oggetto_riferimento_tipo=RIFERIMENTO_TIPO)
        .select_related("cartella")
        .order_by("-created_at")[:5000]
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="attestati_archiviati.csv"'
    response.write("﻿")  # BOM per Excel
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow([
        "Documento ID", "Dipendente", "ID anagrafica", "Record completamento",
        "Cartella", "Nome file", "Dimensione (KB)", "Archiviato il", "Conservare fino al",
    ])
    for d in docs:
        writer.writerow([
            d.pk,
            nomi_map.get(d.legacy_anagrafica_id, f"#{d.legacy_anagrafica_id}"),
            d.legacy_anagrafica_id,
            d.oggetto_riferimento_id or "",
            d.cartella.nome if d.cartella else "",
            d.nome_originale,
            round((d.dimensione_bytes or 0) / 1024, 1),
            d.created_at.strftime("%d-%m-%Y %H:%M") if d.created_at else "",
            d.retention_until.strftime("%d-%m-%Y") if d.retention_until else "",
        ])

    try:
        TrainingExportLog.objects.create(
            tipo="ATTESTATO",
            filtri_json={"formato": "archivio_csv", "righe": len(docs)},
            righe_esportate=len(docs),
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog export archivio attestati")
    return response


@login_required
@require_POST
def formazione_sessione_attestati(request, sessione_id: int):
    """Genera e archivia nel box gli attestati di tutti i completati della sessione.

    Comodo a fine edizione: un click produce gli attestati PDF di tutti i
    `TrainingEmployeeRecord` della sessione e li salva nel box documenti
    (idempotente). Gated dal permesso di modifica formazione.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per archiviare gli attestati.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)

    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    records = list(TrainingEmployeeRecord.objects.filter(sessione=sessione))
    from ..services.attestato_pdf import archivia_attestato

    ok = err = 0
    for rec in records:
        try:
            archivia_attestato(rec, user=request.user)
            ok += 1
        except Exception:
            err += 1
            logger.exception(
                "Archiviazione attestato sessione %s record %s fallita", sessione_id, rec.pk
            )

    if not records:
        messages.info(
            request,
            "Nessun completamento registrato per questa sessione: nessun attestato da archiviare.",
        )
    else:
        messages.success(
            request,
            f"Attestati archiviati nel box: {ok}" + (f", {err} errori" if err else "") + ".",
        )
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


# ---------------------------------------------------------------------------
# Allegati formazione: registro firme firmato (sessione / lezione) e materiale
# ---------------------------------------------------------------------------

@login_required
@require_POST
def formazione_allegato_upload(request, sessione_id: int):
    """Carica un allegato (registro firme firmato/materiale) di sessione o lezione.

    Storage privato fuori webroot. Se ``lezione_id`` è valorizzato l'allegato è
    legato alla singola lezione, altrimenti all'intera sessione. Gated dal
    permesso di modifica formazione. Foglio firme = dato personale: come gli
    altri documenti HR, scaricabile solo dalla view protetta.

    Il gemello ``formazione_corso_allegato_upload`` carica al livello di CORSO
    passando per lo stesso codice: una sola validazione di formato, dimensione e
    MIME, un solo audit.
    """
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per caricare allegati.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    lezione = None
    lezione_raw = (request.POST.get("lezione_id") or "").strip()
    if lezione_raw.isdigit():
        lezione = TrainingLesson.objects.filter(pk=int(lezione_raw), sessione=sessione).first()

    tipo = (request.POST.get("tipo") or TrainingAttachment.Tipo.REGISTRO_FIRMATO).strip()
    if tipo not in TrainingAttachment.Tipo.values:
        tipo = TrainingAttachment.Tipo.REGISTRO_FIRMATO

    def _back():
        if lezione is not None:
            return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione.pk)
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Seleziona un file da caricare.")
        return _back()

    # SEC: tipo verificato dal contenuto, senza ripiego sul Content-Type del browser.
    from ..services.upload_documenti import UploadMimeValidationError, valida_documento
    try:
        mime = valida_documento(uploaded, _helpers._ALLOWED_DOC_EXTENSIONS)
    except UploadMimeValidationError as exc:
        messages.error(request, f"File rifiutato: {exc} Ammessi: PDF, immagini (JPG, PNG, WEBP), DOC/DOCX, XLS/XLSX.")
        return _back()

    att = TrainingAttachment(
        sessione=sessione,
        lezione=lezione,
        tipo=tipo,
        nome_originale=uploaded.name[:255],
        tipo_mime=mime,
        dimensione_bytes=uploaded.size,
        descrizione=(request.POST.get("descrizione") or "").strip()[:300],
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    att.file = uploaded
    att.save()

    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_ALLEGATO_UPLOAD", "anagrafica", {
            "attachment_id": att.pk, "sessione_id": sessione_id,
            "lezione_id": lezione.pk if lezione else None, "tipo": tipo,
            "nome_originale": att.nome_originale,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_ALLEGATO_UPLOAD fallito", exc_info=True)

    messages.success(request, f"Allegato «{att.nome_originale}» caricato.")
    return _back()


@login_required
@require_POST
def formazione_allegato_delete(request, attachment_id: int):
    att = get_object_or_404(
        TrainingAttachment.objects.select_related("corso", "sessione", "lezione"),
        pk=attachment_id,
    )
    corso_id = att.corso_id
    sessione_id = att.sessione_id
    lezione_id = att.lezione_id

    def _back():
        if corso_id:
            return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
        if lezione_id:
            return redirect(
                "anagrafica:formazione_lezione_presenze",
                sessione_id=sessione_id, lezione_id=lezione_id,
            )
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare allegati.")
        return _back()
    if att.sessione_id and att.sessione.is_chiusa:
        # Il registro firmato di un'edizione chiusa è l'evidenza degli attestati.
        from ..services.formazione_integrita import motivo_blocco_edizione
        messages.error(request, motivo_blocco_edizione(att.sessione))
        return _back()
    nome = att.nome_originale
    att.delete()
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_ALLEGATO_ELIMINATO", "anagrafica", {
            "attachment_id": attachment_id, "corso_id": corso_id,
            "sessione_id": sessione_id,
            "lezione_id": lezione_id, "nome_originale": nome,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_ALLEGATO_ELIMINATO fallito", exc_info=True)
    messages.success(request, "Allegato eliminato.")
    return _back()


@login_required
def formazione_allegato_download(request, attachment_id: int):
    """Scarica un allegato formazione dallo storage privato (ACL + audit)."""
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)
    att = get_object_or_404(TrainingAttachment, pk=attachment_id)
    if not att.file:
        return HttpResponse("File non disponibile.", status=404)
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_ALLEGATO_DOWNLOAD", "anagrafica", {
            "attachment_id": att.pk, "tipo": att.tipo, "corso_id": att.corso_id,
            "sessione_id": att.sessione_id, "lezione_id": att.lezione_id,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_ALLEGATO_DOWNLOAD fallito", exc_info=True)
    from django.http import FileResponse
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    filename = att.nome_originale or f"allegato_{att.pk}.bin"
    resp = FileResponse(fh, as_attachment=True, filename=filename)
    from core.download_security import harden_file_response
    return harden_file_response(resp, filename, inline=False)


@login_required
@require_POST
def formazione_corso_allegato_upload(request, corso_id: int):
    """Carica il materiale **del corso**: dispense, programma, modulistica.

    E\' il materiale "madre": ogni nuova edizione se lo ritrova proposto in copia
    (spunta ``proponi_a_nuova_edizione``). Stesse regole degli allegati di
    edizione — storage privato fuori webroot, stesse estensioni/MIME ammessi,
    stesso audit.
    """
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per caricare allegati.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    tipo = (request.POST.get("tipo") or TrainingAttachment.Tipo.MATERIALE).strip()
    if tipo not in TrainingAttachment.Tipo.values:
        tipo = TrainingAttachment.Tipo.MATERIALE

    def _back():
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Seleziona un file da caricare.")
        return _back()
    # SEC: tipo verificato dal contenuto, senza ripiego sul Content-Type del browser.
    from ..services.upload_documenti import UploadMimeValidationError, valida_documento
    try:
        mime = valida_documento(uploaded, _helpers._ALLOWED_DOC_EXTENSIONS)
    except UploadMimeValidationError as exc:
        messages.error(request, f"File rifiutato: {exc} Ammessi: PDF, immagini (JPG, PNG, WEBP), DOC/DOCX, XLS/XLSX.")
        return _back()

    att = TrainingAttachment(
        corso=corso,
        tipo=tipo,
        proponi_a_nuova_edizione=(request.POST.get("proponi") or "1") not in ("0", "", "off"),
        nome_originale=uploaded.name[:255],
        tipo_mime=mime,
        dimensione_bytes=uploaded.size,
        descrizione=(request.POST.get("descrizione") or "").strip()[:300],
        created_by=request.user,
        created_by_display=request.user.get_full_name() or request.user.username,
    )
    att.file = uploaded
    att.save()
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_ALLEGATO_UPLOAD", "anagrafica", {
            "attachment_id": att.pk, "corso_id": corso_id, "tipo": tipo,
            "nome_originale": att.nome_originale,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_ALLEGATO_UPLOAD fallito", exc_info=True)
    messages.success(request, f"Allegato «{att.nome_originale}» caricato sul corso.")
    return _back()


# ---------------------------------------------------------------------------
# Report rapidi del corso (CSV iscritti, attestati ZIP, fogli firme PDF)
# ---------------------------------------------------------------------------

@login_required
def formazione_corso_report_iscritti_csv(request, corso_id: int):
    """CSV dei dipendenti del corso (aggregato su tutte le sessioni)."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per esportare i report.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)

    agg = defaultdict(lambda: {"n_sessioni": 0, "stati": set(), "data": None, "idoneo": None, "n_compl": 0, "perc": None})
    for e in TrainingEnrollment.objects.filter(sessione__corso=corso).values(
        "legacy_anagrafica_id", "stato", "percentuale_presenza"
    ):
        a = agg[e["legacy_anagrafica_id"]]
        a["n_sessioni"] += 1
        a["stati"].add(e["stato"])
        if e["percentuale_presenza"] is not None:
            a["perc"] = e["percentuale_presenza"]
    for r in TrainingEmployeeRecord.objects.filter(corso=corso).order_by("-data_completamento").values(
        "legacy_anagrafica_id", "data_completamento", "idoneo"
    ):
        a = agg[r["legacy_anagrafica_id"]]
        a["n_compl"] += 1
        if a["data"] is None:
            a["data"] = r["data_completamento"]
            a["idoneo"] = r["idoneo"]

    nomi = _helpers._build_nomi_map()
    ordine = _helpers._build_ordine_map()
    _prio = ["COMPLETATO", "IN_CORSO", "ISCRITTO", "NON_IDONEO", "ASSENTE", "RITIRATO"]

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="corso_{corso.codice}_iscritti.csv"'
    response.write("﻿")
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow(["Dipendente", "ID anagrafica", "Stato", "Sessioni", "Completamenti",
                     "% presenza", "Idoneo", "Ultimo completamento"])
    for lid, a in sorted(agg.items(), key=lambda kv: ordine.get(kv[0], f"#{kv[0]}").casefold()):
        stato = next((s for s in _prio if s in a["stati"]), next(iter(a["stati"]), ""))
        writer.writerow([
            nomi.get(lid, f"#{lid}"), lid, stato, a["n_sessioni"], a["n_compl"],
            a["perc"] if a["perc"] is not None else "",
            "" if a["idoneo"] is None else ("Sì" if a["idoneo"] else "No"),
            a["data"].strftime("%d-%m-%Y") if a["data"] else "",
        ])

    try:
        TrainingExportLog.objects.create(
            tipo="CORSI", filtri_json={"corso_id": corso.pk, "formato": "iscritti_csv"},
            righe_esportate=len(agg), generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog export iscritti corso")
    return response


@login_required
def formazione_corso_attestati_zip(request, corso_id: int):
    """ZIP con gli attestati PDF di tutti i completamenti idonei del corso."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per esportare gli attestati.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)

    import io
    import zipfile
    from ..services.attestato_pdf import build_attestato_pdf_bytes, build_attestato_context

    records = list(
        TrainingEmployeeRecord.objects
        .filter(corso=corso)
        .select_related("corso", "corso__piano", "corso__qualifica", "sessione", "sessione__docente")
        .order_by("-data_completamento", "-id")
    )
    if not records:
        messages.info(request, "Nessun completamento da esportare per questo corso.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    nomi = _helpers._build_nomi_map()
    buf = io.BytesIO()
    ok = err = 0
    used_names: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rec in records:
            try:
                pdf = build_attestato_pdf_bytes(rec)
                try:
                    numero = build_attestato_context(rec)["numero_display"]
                except Exception:
                    numero = f"FORM-{rec.pk:05d}"
                nome_dip = nomi.get(rec.legacy_anagrafica_id, f"dip{rec.legacy_anagrafica_id}")
                base = f"{numero}_{nome_dip}".replace("/", "-").replace(" ", "_")[:120]
                fname = f"{base}.pdf"
                i = 2
                while fname in used_names:
                    fname = f"{base}_{i}.pdf"
                    i += 1
                used_names.add(fname)
                zf.writestr(fname, pdf)
                ok += 1
            except Exception:
                err += 1
                logger.exception("Attestato ZIP corso %s record %s fallito", corso_id, rec.pk)

    if not ok:
        messages.error(request, "Generazione attestati fallita per tutti i record.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    try:
        TrainingExportLog.objects.create(
            tipo="ATTESTATO", filtri_json={"corso_id": corso.pk, "formato": "attestati_zip", "ok": ok, "err": err},
            righe_esportate=ok, generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog export attestati ZIP")

    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="attestati_{corso.codice}.zip"'
    return resp


@login_required
def formazione_corso_registri_pdf(request, corso_id: int):
    """PDF del foglio firme (vuoto) di tutte le lezioni del corso."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per generare i report.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    from ..services.attestato_pdf import build_registri_corso_pdf_bytes
    try:
        pdf = build_registri_corso_pdf_bytes(corso)
    except Exception:
        logger.exception("Errore generazione fogli firme corso %s", corso_id)
        messages.error(request, "Errore nella generazione dei fogli firme.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    try:
        TrainingExportLog.objects.create(
            tipo="REPORT_FIRMA", filtri_json={"corso_id": corso.pk, "formato": "fogli_firme_corso_pdf"},
            righe_esportate=0, generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog fogli firme corso")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="fogli_firme_{corso.codice}.pdf"'
    return resp


# ============================================================================
# FORMAZIONE HR — Dashboard (PATCH-02)
# ============================================================================

# Stato della scadenza → segmento della barra di copertura. VALIDO e UNA_TANTUM
# (completato una volta, senza rinnovo) sono entrambi «in regola».
_COPERTURA_SEGMENTI = {
    "VALIDO": "ok", "UNA_TANTUM": "ok", "IN_SCADENZA_90": "s90",
    "IN_SCADENZA_30": "s30", "SCADUTO": "ko", "MAI_FREQUENTATO": "mai",
}


def _copertura_corsi_obbligatori(oggi) -> list[dict]:
    """Una riga per corso con scadenze obbligatorie: quante persone sono in regola,
    in scadenza, scadute o mai formate (dalla cache TrainingDeadline, come i KPI)
    e la prossima sessione pianificata. Ordinata dal corso più scoperto."""
    conteggi: dict[int, dict[str, int]] = {}
    righe = (
        TrainingDeadline.objects.filter(is_required=True)
        .values("corso_id", "stato_scadenza").annotate(n=Count("id")).order_by()
    )
    for r in righe:
        segmento = _COPERTURA_SEGMENTI.get(r["stato_scadenza"])
        if segmento:
            c = conteggi.setdefault(r["corso_id"], dict.fromkeys(("ok", "s90", "s30", "ko", "mai"), 0))
            c[segmento] += r["n"]
    if not conteggi:
        return []

    prossime: dict[int, TrainingSession] = {}
    for s in (
        TrainingSession.objects.filter(corso_id__in=conteggi, stato="PIANIFICATA", data_inizio__gte=oggi)
        .annotate(n_iscritti=Count("iscrizioni")).order_by("data_inizio", "pk")
    ):
        prossime.setdefault(s.corso_id, s)

    out = []
    for corso in TrainingCourse.objects.filter(pk__in=conteggi, is_active=True).select_related("piano"):
        c = conteggi[corso.pk]
        totale = sum(c.values())
        if not totale:
            continue
        segmenti = [
            {"chiave": k, "n": c[k], "perc": round(c[k] * 100 / totale, 2)}
            for k in ("ok", "s90", "s30", "ko", "mai") if c[k]
        ]
        out.append({
            "corso": corso, "piano": corso.piano.nome if corso.piano_id else "",
            "totale": totale, "perc_ok": round(c["ok"] * 100 / totale), "segmenti": segmenti,
            "scoperti": c["ko"] + c["mai"] + c["s30"], **c,
            "prossima": prossime.get(corso.pk),
        })
    out.sort(key=lambda r: (-r["scoperti"], r["perc_ok"], r["corso"].titolo.casefold()))
    return out

@login_required
def formazione_dashboard(request):
    """Dashboard globale formazione HR.

    KPI letti da TrainingDeadline (cache ricalcolabile) e TrainingEmployeeRecord.
    Se TrainingDeadline è vuota (non ancora ricalcolata) i KPI scadenze sono 0
    e viene mostrato un banner informativo.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    # «Leggi un attestato»: stessa rotta (e stesso ACL) della dashboard.
    if request.GET.get("vista") == "leggi-attestato" or request.POST.get("azione") in ("leggi_attestato", "registra_attestato"):
        from ..views_lettura_attestati import gestisci

        return gestisci(request)

    from django.utils import timezone as _tz

    oggi = _tz.localdate()

    # KPI da TrainingEmployeeRecord (non dipende dalla cache)
    kpi_dipendenti_formazione = (
        TrainingEmployeeRecord.objects
        .values("legacy_anagrafica_id").distinct().count()
    )

    # KPI da TrainingDeadline (cache — può essere 0 se non ancora ricalcolata)
    kpi_scaduti         = TrainingDeadline.objects.filter(stato_scadenza="SCADUTO").count()
    kpi_in_scadenza_30  = TrainingDeadline.objects.filter(stato_scadenza="IN_SCADENZA_30").count()
    kpi_obbligatori_mancanti = TrainingDeadline.objects.filter(
        stato_scadenza__in=["MAI_FREQUENTATO", "SCADUTO"],
        is_required=True,
    ).count()

    # KPI catalogo
    kpi_piani_attivi = TrainingPlan.objects.filter(stato="ATTIVO", is_active=True).count()
    kpi_corsi_attivi = TrainingCourse.objects.filter(stato="ATTIVO", is_active=True).count()

    # Scadenzario urgente TOP 20 (ordinato per urgenza crescente)
    scadenze_raw = list(
        TrainingDeadline.objects
        .filter(stato_scadenza__in=["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90"])
        .select_related("corso", "corso__piano")
        .order_by("data_scadenza", "legacy_anagrafica_id")[:20]
    )
    nomi_map = _helpers._build_nomi_map()
    for d in scadenze_raw:
        d.dipendente_nome = nomi_map.get(d.legacy_anagrafica_id, f"#{d.legacy_anagrafica_id}")
        d.giorni = (d.data_scadenza - oggi).days if d.data_scadenza else None

    deadline_cache_empty = not TrainingDeadline.objects.exists()
    copertura_corsi = _copertura_corsi_obbligatori(oggi)

    return render(request, "anagrafica/pages/formazione_dashboard.html", {
        "copertura_corsi": copertura_corsi,
        "copertura_piani": sorted({c["piano"] for c in copertura_corsi if c["piano"]}),
        "oggi": oggi,
        "can_edit_formazione": _helpers._can_edit_formazione(request),
        "kpi_dipendenti_formazione": kpi_dipendenti_formazione,
        "kpi_scaduti": kpi_scaduti,
        "kpi_in_scadenza_30": kpi_in_scadenza_30,
        "kpi_obbligatori_mancanti": kpi_obbligatori_mancanti,
        "kpi_piani_attivi": kpi_piani_attivi,
        "kpi_corsi_attivi": kpi_corsi_attivi,
        "scadenze_urgenti": scadenze_raw,
        "deadline_cache_empty": deadline_cache_empty,
    })


@login_required
def formazione_ricerca(request):
    """Ricerca globale formazione: corsi, sessioni, piani, qualifiche, docenti,
    aziende formative, argomenti del programma, dipendenti (libretto) e
    attestati. Un'unica casella dalla dashboard.

    Best-effort, limitata in righe: serve a "saltare" velocemente all'entità,
    non è un motore full-text. Gated dal permesso di visualizzazione formazione.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    q = (request.GET.get("q") or "").strip()
    risultati: dict[str, list] = {
        "corsi": [], "sessioni": [], "piani": [], "qualifiche": [],
        "istruttori": [], "aziende": [], "argomenti": [],
        "dipendenti": [], "attestati": [],
    }
    totale = 0
    if q:
        ql = q.lower()

        from django.db.models import Count as _Count, Prefetch as _Prefetch
        # Edizioni + lezioni precaricate per il sottoelenco espandibile,
        # sia in pagina risultati sia nella tendina (no query N+1).
        risultati["corsi"] = list(
            TrainingCourse.objects.select_related("piano", "ente_formativo")
            .filter(
                Q(titolo__icontains=q) | Q(codice__icontains=q)
                | Q(ente_formativo__nome__icontains=q)
            )
            .annotate(n_sessioni=_Count("sessioni", distinct=True))
            .prefetch_related(
                _Prefetch(
                    "sessioni",
                    queryset=TrainingSession.objects.prefetch_related("lezioni").order_by("-data_inizio"),
                )
            )
            .order_by("titolo")[:25]
        )
        risultati["piani"] = list(
            TrainingPlan.objects.filter(Q(nome__icontains=q) | Q(codice__icontains=q))
            .annotate(n_corsi=_Count("corsi", distinct=True))
            .order_by("nome")[:25]
        )
        risultati["sessioni"] = list(
            TrainingSession.objects.select_related("corso", "corso__ente_formativo", "docente_ente")
            .filter(
                Q(codice_sessione__icontains=q) | Q(corso__titolo__icontains=q)
                | Q(sede__icontains=q)
                | Q(docente__nome__icontains=q) | Q(docente_nome__icontains=q)
                | Q(docente_ente__nome__icontains=q)
                | Q(corso__ente_formativo__nome__icontains=q)
            )
            .annotate(n_iscritti=_Count("iscrizioni", distinct=True))
            .order_by("-data_inizio")[:25]
        )
        risultati["qualifiche"] = list(
            TipoQualifica.objects.filter(Q(nome__icontains=q) | Q(descrizione__icontains=q))
            .annotate(n_assegnazioni=_Count("assegnazioni", distinct=True))
            .order_by("nome")[:25]
        )

        # Docenti: si cercano per nome, ente (a catalogo o testo libero) ed email.
        # Le sessioni sono precaricate perché il risultato mostra "cosa ha
        # svolto": senza quelle, trovare il docente non dice ancora niente.
        risultati["istruttori"] = list(
            TrainingInstructor.objects.select_related("azienda")
            .filter(
                Q(nome__icontains=q)
                | Q(ragione_sociale__icontains=q)
                | Q(azienda__nome__icontains=q)
                | Q(email__icontains=q)
            )
            .annotate(
                n_sessioni=_Count("sessioni", distinct=True),
                n_lezioni=_Count("lezioni", distinct=True),
            )
            .prefetch_related(
                _Prefetch(
                    "sessioni",
                    queryset=TrainingSession.objects.select_related("corso").order_by("-data_inizio"),
                )
            )
            .order_by("nome")[:25]
        )
        risultati["aziende"] = list(
            TrainingProvider.objects
            .filter(
                Q(nome__icontains=q)
                | Q(partita_iva__icontains=q)
                | Q(accreditamento__icontains=q)
            )
            .annotate(n_istruttori=_Count("istruttori", distinct=True))
            .order_by("nome")[:25]
        )

        # Programma didattico: il contenuto insegnato, non il titolo del corso.
        # «Spazi confinati» può essere un modulo dentro un corso che si chiama
        # altrimenti — cercarlo solo nei titoli non lo trova. Si guarda prima
        # l'**erogato** (programma dell'edizione, il fatto documentato) e poi il
        # **previsto** (programma del corso), tenendo le due cose distinte.
        argomenti: list[dict] = []
        for a in (
            TrainingSessionArgomento.objects
            .select_related("sessione", "sessione__corso")
            .filter(Q(argomento__icontains=q) | Q(riferimento__icontains=q))
            .order_by("-sessione__data_inizio", "ordine")[:20]
        ):
            argomenti.append({
                "argomento": a.argomento,
                "riferimento": a.riferimento,
                "ore": a.ore_previste,
                "erogato": True,
                "titolo": a.sessione.corso.titolo,
                "codice": a.sessione.codice_sessione,
                "data": a.sessione.data_inizio,
                "url": reverse("anagrafica:formazione_sessione_detail", args=[a.sessione_id]),
            })
        for a in (
            TrainingCourseArgomento.objects
            .select_related("corso")
            .filter(Q(argomento__icontains=q) | Q(riferimento__icontains=q))
            .order_by("corso__titolo", "ordine")[:20]
        ):
            argomenti.append({
                "argomento": a.argomento,
                "riferimento": a.riferimento,
                "ore": a.ore_previste,
                "erogato": False,
                "titolo": a.corso.titolo,
                "codice": a.corso.codice,
                "data": None,
                "url": reverse("anagrafica:formazione_corso_detail", args=[a.corso_id]),
            })
        risultati["argomenti"] = argomenti

        # Dipendenti per nome → link al libretto formativo.
        nomi = _helpers._build_nomi_map()
        dip_match = [
            {"legacy_id": lid, "nome": nome}
            for lid, nome in nomi.items() if ql in nome.lower()
        ]
        _ordine = _helpers._build_ordine_map()
        dip_match.sort(key=lambda d: _ordine.get(d["legacy_id"], d["nome"]).casefold())
        risultati["dipendenti"] = dip_match[:25]

        # Attestati: per nome dipendente o titolo corso (snapshot).
        matched_ids = [d["legacy_id"] for d in dip_match]
        rec_qs = TrainingEmployeeRecord.objects.filter(
            Q(course_title_snapshot__icontains=q)
            | Q(course_code_snapshot__icontains=q)
            | Q(legacy_anagrafica_id__in=matched_ids)
        ).order_by("-data_completamento")[:25]
        att = []
        for r in rec_qs:
            att.append({
                "record": r,
                "nome": nomi.get(r.legacy_anagrafica_id, f"#{r.legacy_anagrafica_id}"),
            })
        risultati["attestati"] = att

        totale = sum(len(v) for v in risultati.values())

    # Ricerca live: su richiesta HTMX rende solo il frammento dei risultati;
    # con ?suggest=1 (casella nella dashboard) rende la tendina compatta.
    if request.headers.get("HX-Request"):
        template = (
            "anagrafica/partials/_formazione_search_suggest.html"
            if request.GET.get("suggest")
            else "anagrafica/partials/_formazione_search_results.html"
        )
    else:
        template = "anagrafica/pages/formazione_ricerca.html"
    return render(request, template, {
        "q": q,
        "risultati": risultati,
        "totale": totale,
    })


def _audit_formazione(request, azione: str, dettaglio: dict | None = None) -> None:
    """Registra nel registro audit del portale un gesto irreversibile o sensibile.

    Si tracciano solo i gesti che in verifica ispettiva sollevano la domanda
    "chi l'ha fatto e quando": cancellazioni e ritocchi a una presenza già
    firmata. Le registrazioni ordinarie non finiscono qui, altrimenti il
    registro diventa illeggibile.

    Fire-and-forget: un errore di audit non deve mai far fallire l'operazione
    dell'utente (``core.audit.log_action`` già inghiotte le eccezioni).
    """
    try:
        from core.audit import log_action

        log_action(request, azione, "anagrafica.formazione", dettaglio or {})
    except Exception:  # pragma: no cover - difesa in profondità
        pass


# ============================================================================
# FORMAZIONE HR — Piani formativi (PATCH-03)
# ============================================================================

@login_required
def formazione_piani_list(request):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    filtro_stato = request.GET.get("stato", "")
    filtro_cat   = request.GET.get("categoria", "")
    qs = TrainingPlan.objects.all()
    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_cat:
        qs = qs.filter(categoria=filtro_cat)
    piani = list(qs.order_by("nome").annotate(n_corsi=Count("corsi")))

    form = TrainingPlanForm()
    return render(request, "anagrafica/pages/formazione_piani.html", {
        "piani": piani,
        "form": form,
        "is_editor": is_editor,
        "filtro_stato": filtro_stato,
        "filtro_cat": filtro_cat,
        "STATO_CHOICES": TrainingPlan.STATO_CHOICES,
        "CATEGORIA_CHOICES": TrainingPlan.CATEGORIA_CHOICES,
    })


@login_required
@require_POST
def formazione_piano_create(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare piani formativi.")
        return redirect("anagrafica:formazione_piani_list")
    form = TrainingPlanForm(request.POST)
    if form.is_valid():
        piano = form.save(commit=False)
        piano.created_by = request.user
        piano.save()
        messages.success(request, f'Piano "{piano.nome}" creato.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_piani_list")


@login_required
def formazione_piano_detail(request, piano_id: int):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    piano = get_object_or_404(TrainingPlan, pk=piano_id)
    corsi = list(
        TrainingCourse.objects.filter(piano=piano)
        .order_by("titolo")
        .annotate(n_sessioni=Count("sessioni", distinct=True))
    )
    regole = list(
        TrainingRequirementRule.objects.filter(piano=piano, is_active=True)
        .select_related("mansione", "area", "ruolo_operativo", "competenza")
        .order_by("-priority")
    )
    nomi_singoli: dict[int, str] = {}
    ids_singoli = [r.legacy_anagrafica_id for r in regole if r.legacy_anagrafica_id]
    if ids_singoli:
        nomi_singoli = _helpers._build_nomi_map()
    for r in regole:
        r.dipendente_nome = nomi_singoli.get(r.legacy_anagrafica_id, "") if r.legacy_anagrafica_id else ""

    edit_form = TrainingPlanForm(instance=piano)
    return render(request, "anagrafica/pages/formazione_piano_detail.html", {
        "piano": piano,
        "corsi": corsi,
        "regole": regole,
        "edit_form": edit_form,
        "is_editor": is_editor,
    })


@login_required
@require_POST
def formazione_piano_edit(request, piano_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare piani formativi.")
        return redirect("anagrafica:formazione_piani_list")
    piano = get_object_or_404(TrainingPlan, pk=piano_id)
    form = TrainingPlanForm(request.POST, instance=piano)
    if form.is_valid():
        form.save()
        messages.success(request, f'Piano "{piano.nome}" aggiornato.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_piano_detail", piano_id=piano_id)


@login_required
@require_POST
def formazione_piano_delete(request, piano_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare piani formativi.")
        return redirect("anagrafica:formazione_piani_list")
    piano = get_object_or_404(TrainingPlan, pk=piano_id)
    if piano.corsi.exists():
        messages.error(request, f'Il piano "{piano.nome}" ha corsi associati. Archivia o rimuovi prima i corsi.')
        return redirect("anagrafica:formazione_piano_detail", piano_id=piano_id)
    nome = piano.nome
    piano.delete()
    messages.success(request, f'Piano "{nome}" eliminato.')
    return redirect("anagrafica:formazione_piani_list")


# ============================================================================
# FORMAZIONE HR — Corsi (PATCH-03)
# ============================================================================

@login_required
def formazione_corsi_list(request):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    filtro_piano = request.GET.get("piano", "")
    filtro_stato = request.GET.get("stato", "")
    filtro_obbligatorio = request.GET.get("obbligatorio", "")
    q_search = (request.GET.get("q") or "").strip()

    qs = TrainingCourse.objects.select_related("piano", "ente_formativo").prefetch_related(
        Prefetch(
            "sessioni",
            queryset=TrainingSession.objects.select_related("docente__azienda").order_by("-data_inizio"),
        )
    )
    if filtro_piano:
        qs = qs.filter(piano_id=filtro_piano)
    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_obbligatorio == "1":
        qs = qs.filter(obbligatorio=True)
    elif filtro_obbligatorio == "0":
        qs = qs.filter(obbligatorio=False)
    if q_search:
        qs = qs.filter(
            Q(titolo__icontains=q_search) | Q(codice__icontains=q_search)
            | Q(ente_formativo__nome__icontains=q_search)
        )

    paginator = Paginator(qs.order_by("piano__nome", "titolo"), 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    piani = list(TrainingPlan.objects.filter(is_active=True).order_by("nome"))

    for corso in page_obj:
        nomi = []
        visti = set()
        # L'ente di riferimento del corso (esplicito) viene per primo; gli enti
        # visti solo tramite i docenti delle sessioni completano l'elenco quando
        # differiscono (es. corso storicamente erogato da più provider).
        if corso.ente_formativo_id:
            nomi.append(corso.ente_formativo.nome)
            visti.add(corso.ente_formativo.nome)
        for sessione in corso.sessioni.all():
            docente = sessione.docente
            if not docente:
                continue
            nome = docente.azienda.nome if docente.azienda_id else docente.ragione_sociale
            if nome and nome not in visti:
                visti.add(nome)
                nomi.append(nome)
        corso.enti_formatori = nomi

    return render(request, "anagrafica/pages/formazione_corsi.html", {
        "page_obj": page_obj,
        "is_editor": is_editor,
        "filtro_piano": filtro_piano,
        "filtro_stato": filtro_stato,
        "filtro_obbligatorio": filtro_obbligatorio,
        "q_search": q_search,
        "piani": piani,
        "STATO_CHOICES": TrainingCourse.STATO_CHOICES,
    })


@login_required
def formazione_corso_create(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare corsi formativi.")
        return redirect("anagrafica:formazione_corsi_list")
    if request.method == "POST":
        form = TrainingCourseForm(request.POST)
        sess_form = TrainingSessioneUnicaForm(request.POST, prefix="sess")
        # Il blocco «Programmazione» è opzionale: si valida sempre (per non perdere
        # gli errori quando è acceso) ma vincola il salvataggio solo se spuntato.
        sess_ok = sess_form.is_valid()
        if form.is_valid() and sess_ok:
            sessione = None
            n_gruppi = sess_form.cleaned_data.get("n_gruppi") or 1
            try:
                # Corso, sessione, giornate e gruppi nascono in un colpo solo: se
                # la programmazione fallisce non deve restare a terra un corso a
                # meta' che l'utente non ha chiesto.
                with transaction.atomic():
                    corso = form.save(commit=False)
                    corso.created_by = request.user
                    corso.save()
                    form.salva_processi(corso)
                    if sess_form.cleaned_data.get("pianifica"):
                        from ..services.formazione_pianificazione import crea_sessione_unica
                        cd = sess_form.cleaned_data
                        date_puntuali = cd.get("date_puntuali_lista") or []
                        giorni_settimana = (
                            None if date_puntuali else {int(g) for g in cd.get("giorni_settimana") or []}
                        )
                        sessione = crea_sessione_unica(
                            corso,
                            data_inizio=cd.get("data_inizio"),
                            data_fine=cd.get("data_fine"),
                            ora_inizio=cd.get("ora_inizio"),
                            ora_fine=cd.get("ora_fine"),
                            pausa_minuti=cd.get("pausa_minuti") or 0,
                            sede=cd.get("sede") or "",
                            docente=cd.get("docente"),
                            modalita=cd.get("modalita") or "IN_SEDE",
                            giorni_settimana=giorni_settimana,
                            date_puntuali=date_puntuali or None,
                            user=request.user,
                        )
                        if n_gruppi > 1:
                            from ..services.formazione_pianificazione import dividi_in_gruppi
                            dividi_in_gruppi(sessione, n_gruppi=n_gruppi, user=request.user)
            except ValueError as exc:
                # Il form copre gia' questi casi: ci si arriva solo con una POST
                # costruita a mano. Meglio un messaggio comprensibile di un 500.
                messages.error(request, str(exc))
            else:
                if sessione is not None:
                    n_lez = sessione.lezioni.count()
                    extra_gruppi = f' in {n_gruppi} gruppi paralleli' if n_gruppi > 1 else ""
                    messages.success(
                        request,
                        f'Corso "{corso.titolo}" creato con la sessione {sessione.codice_sessione}{extra_gruppi} '
                        f'({n_lez} giornat{"a" if n_lez == 1 else "e"} a gruppo, {sessione.ore_pianificate:g} ore formative).',
                    )
                    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)
                messages.success(request, f'Corso "{corso.titolo}" creato.')
                return redirect("anagrafica:formazione_corso_detail", corso_id=corso.pk)
    else:
        initial = {}
        if request.GET.get("piano"):
            initial["piano"] = request.GET.get("piano")
        # Preset "nuovo corso e-learning" dal hub di gestione e-learning: applica i
        # default configurati nelle Impostazioni e-learning.
        if request.GET.get("elearning") in ("1", "true", "on"):
            cfg = ElearningConfig.get_instance()
            initial["is_elearning"] = True
            initial["quiz_punteggio_minimo"] = cfg.quiz_punteggio_minimo_default
            if cfg.validita_mesi_default:
                initial["validita_mesi"] = cfg.validita_mesi_default
        form = TrainingCourseForm(initial=initial)
        sess_form = TrainingSessioneUnicaForm(prefix="sess")
    return render(request, "anagrafica/pages/formazione_corso_form.html", {
        "form": form,
        "sess_form": sess_form,
        "modo": "crea",
    })


# ── Quick-add inline (JSON) delle entità collegate dei form formazione ───────
# Creano l'entità minimale e ritornano {ok, id, label} così la UI la appende al
# <select> e la seleziona senza ricaricare. Gated dal permesso di modifica.

@login_required
@require_POST
def formazione_quickadd_piano(request):
    if not _helpers._can_edit_formazione(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:200]
    if not codice or not nome:
        return JsonResponse({"ok": False, "error": "Codice e nome sono obbligatori."}, status=400)
    if TrainingPlan.objects.filter(codice=codice).exists():
        return JsonResponse({"ok": False, "error": f"Esiste già un piano con codice {codice}."}, status=400)
    p = TrainingPlan.objects.create(codice=codice, nome=nome, created_by=request.user)
    return JsonResponse({"ok": True, "id": p.pk, "label": str(p)})


@login_required
@require_POST
def formazione_quickadd_categoria(request):
    if not _helpers._can_edit_formazione(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    from ..models_rischi import CategoriaCorso
    codice = (request.POST.get("codice") or "").strip().upper()[:20]
    nome = (request.POST.get("nome") or "").strip()[:200]
    if not codice or not nome:
        return JsonResponse({"ok": False, "error": "Codice e nome sono obbligatori."}, status=400)
    if CategoriaCorso.objects.filter(codice=codice).exists():
        return JsonResponse({"ok": False, "error": f"Esiste già una categoria con codice {codice}."}, status=400)
    c = CategoriaCorso.objects.create(codice=codice, nome=nome)
    return JsonResponse({"ok": True, "id": c.pk, "label": c.nome})


@login_required
@require_POST
def formazione_quickadd_qualifica(request):
    if not _helpers._can_edit_formazione(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    from ..models import TipoQualifica
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        return JsonResponse({"ok": False, "error": "Il nome è obbligatorio."}, status=400)
    try:
        durata = max(0, int(request.POST.get("durata_mesi") or 0))
    except (TypeError, ValueError):
        durata = 0
    obj, _created = TipoQualifica.objects.get_or_create(nome=nome, defaults={"durata_mesi": durata})
    return JsonResponse({"ok": True, "id": obj.pk, "label": obj.nome})


@login_required
@require_POST
def formazione_quickadd_docente(request):
    if not _helpers._can_edit_formazione(request):
        return JsonResponse({"ok": False, "error": "Permesso negato."}, status=403)
    nome = (request.POST.get("nome") or "").strip()[:200]
    if not nome:
        return JsonResponse({"ok": False, "error": "Il nome è obbligatorio."}, status=400)
    tipo = (request.POST.get("tipo") or "ESTERNO").strip().upper()
    if tipo not in ("INTERNO", "ESTERNO"):
        tipo = "ESTERNO"
    d = TrainingInstructor.objects.create(nome=nome, tipo=tipo)
    return JsonResponse({"ok": True, "id": d.pk, "label": d.nome})


@login_required
def formazione_corso_codice_suggest(request):
    """Anteprima del prossimo codice corso ``YYNNN`` (JSON).

    Il codice non si digita piu\': e\' allocato al salvataggio da
    ``services.formazione_numerazione.alloca_codice_corso``. Qui si mostra solo
    che numero uscirebbe adesso, per far vedere a video cosa nascera\'; il valore
    definitivo puo\' differire se qualcun altro salva prima.
    """
    if not _helpers._can_edit_formazione(request):
        return JsonResponse({"ok": False}, status=403)
    from ..services.formazione_numerazione import anteprima_codice_corso

    return JsonResponse({"ok": True, "codice": anteprima_codice_corso(), "anteprima": True})


@login_required
def formazione_qualifica_durata(request):
    """Durata (mesi) di una TipoQualifica (JSON): il form corso preimposta la
    validità del corso da quella della qualifica àncora selezionata."""
    if not _helpers._can_view_formazione(request):
        return JsonResponse({"ok": False}, status=403)
    from ..models import TipoQualifica
    try:
        q = TipoQualifica.objects.get(pk=int(request.GET.get("id") or 0))
    except (TipoQualifica.DoesNotExist, TypeError, ValueError):
        return JsonResponse({"ok": False}, status=404)
    return JsonResponse({"ok": True, "durata_mesi": q.durata_mesi or 0})


@login_required
def formazione_corso_detail(request, corso_id: int):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    corso = get_object_or_404(TrainingCourse.objects.select_related("piano", "ente_formativo"), pk=corso_id)

    prerequisiti = list(
        TrainingCourseDependency.objects.filter(corso_principale=corso)
        .select_related("prerequisito")
    )
    moduli = list(
        TrainingCourseModule.objects.filter(corso_padre=corso)
        .select_related("corso_modulo")
        .order_by("ordine")
    )
    versioni = list(
        TrainingCourseVersion.objects.filter(corso=corso).order_by("-created_at")
    )
    regole = list(
        TrainingRequirementRule.objects.filter(corso=corso, is_active=True)
        .select_related("mansione", "area", "ruolo_operativo", "competenza")
        .order_by("-priority")
    )
    nomi_singoli: dict[int, str] = {}
    ids_singoli = [r.legacy_anagrafica_id for r in regole if r.legacy_anagrafica_id]
    if ids_singoli:
        nomi_singoli = _helpers._build_nomi_map()
    for r in regole:
        r.dipendente_nome = nomi_singoli.get(r.legacy_anagrafica_id, "") if r.legacy_anagrafica_id else ""

    try:
        completion_rule = corso.regola_superamento
    except TrainingCompletionRule.DoesNotExist:
        completion_rule = None

    n_sessioni = corso.sessioni.count() if hasattr(corso, "sessioni") else 0
    n_completamenti = TrainingEmployeeRecord.objects.filter(corso=corso).count()

    # Lista sessioni del corso con conteggi lezioni/iscritti per la sezione
    # "Sessioni del corso" nel dettaglio. Limita a 100 per evitare pagine enormi
    # su corsi storici molto frequentati (ordine: piu recenti prima).
    sessioni_list = list(
        corso.sessioni
        .select_related("docente", "docente_ente")
        .annotate(n_lezioni=Count("lezioni", distinct=True),
                  n_iscritti=Count("iscrizioni", distinct=True))
        .order_by("-data_inizio")[:100]
    )
    for s in sessioni_list:
        s.corso = corso  # evita una query per sessione in erogatore_display (fallback ente_formativo)

    # Aggregazione dipendenti iscritti distinti (across all sessioni del corso).
    # Per ciascuno: n. sessioni, stato sintetico, ultimo completamento, idoneo.
    agg_dip = defaultdict(lambda: {
        "n_sessioni": 0,
        "stati": set(),
        "data_completamento": None,
        "idoneo": None,
        "n_completati": 0,
    })
    for e in (TrainingEnrollment.objects
              .filter(sessione__corso=corso)
              .values("legacy_anagrafica_id", "stato")):
        a = agg_dip[e["legacy_anagrafica_id"]]
        a["n_sessioni"] += 1
        a["stati"].add(e["stato"])
    for r in (TrainingEmployeeRecord.objects
              .filter(corso=corso)
              .order_by("-data_completamento")
              .values("legacy_anagrafica_id", "data_completamento", "idoneo")):
        a = agg_dip[r["legacy_anagrafica_id"]]
        a["n_completati"] += 1
        if a["data_completamento"] is None:
            a["data_completamento"] = r["data_completamento"]
            a["idoneo"] = r["idoneo"]

    nomi_dipendenti = _helpers._build_nomi_map() if agg_dip else {}
    # Ordine sintetico stati per scegliere il più rappresentativo
    _stato_priority = ["COMPLETATO", "IN_CORSO", "ISCRITTO", "NON_IDONEO", "ASSENTE", "RITIRATO"]
    dipendenti_iscritti = []
    for lid, a in agg_dip.items():
        stato_sint = next((s for s in _stato_priority if s in a["stati"]), next(iter(a["stati"]), ""))
        dipendenti_iscritti.append({
            "legacy_id": lid,
            "nome": nomi_dipendenti.get(lid, f"#{lid}"),
            "n_sessioni": a["n_sessioni"],
            "n_completati": a["n_completati"],
            "stato_sint": stato_sint,
            "data_completamento": a["data_completamento"],
            "idoneo": a["idoneo"],
        })
    _ordine_dip = _helpers._build_ordine_map() if agg_dip else {}
    dipendenti_iscritti.sort(key=lambda x: _ordine_dip.get(x["legacy_id"], x["nome"]).lower())
    n_dipendenti_iscritti = len(dipendenti_iscritti)

    edit_form = TrainingCourseForm(instance=corso)
    dep_form = TrainingCourseDependencyForm(corso_principale=corso)
    completion_form = TrainingCompletionRuleForm(instance=completion_rule)
    version_form = TrainingCourseVersionForm()
    req_rule_form = TrainingRequirementRuleForm(initial={"corso": corso})

    # Candidati all'assegnazione al corso (primo anello corso→sessione): idonei non
    # ancora assegnati. Solo per editor (evita il calcolo in sola lettura).
    candidati_assegnazione: list = []
    assegnazione_pool_filtrato = False
    if is_editor:
        from ..services.training_eligibility import candidati_corso
        _res = candidati_corso(corso)
        assegnazione_pool_filtrato = _res["pool_filtrato"]
        _gia_assegnati = set(
            TrainingAssignment.objects.filter(corso=corso)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        candidati_assegnazione = [
            c for c in _res["idonei"] if c["legacy_id"] not in _gia_assegnati
        ]

    # Registrazione diretta del completamento (corso senza sessione): pool completo
    # dei dipendenti attivi, come nel form di iscrizione manuale.
    from django.utils import timezone as _tz
    completamento_form = None
    dipendenti_pool: list = []
    if is_editor:
        completamento_form = TrainingCompletamentoDirettoForm(initial={
            "data_completamento": _tz.localdate(),
            "idoneo": True,
        })
        _ordine_pool = _helpers._build_ordine_map()
        dipendenti_pool = sorted(
            _helpers._build_nomi_map().items(),
            key=lambda x: _ordine_pool.get(x[0], x[1]).casefold(),
        )

    return render(request, "anagrafica/pages/formazione_corso_detail.html", {
        "corso": corso,
        # Materiale del corso: e' la base che ogni nuova edizione si ritrova
        # proposta in copia (vedi TrainingSessionForm.allegati_dal_corso).
        "allegati_corso": list(corso.allegati.order_by("tipo", "-created_at")),
        "tipi_allegato": TrainingAttachment.Tipo.choices,
        "prerequisiti": prerequisiti,
        "programma": list(corso.programma.all()),
        "moduli": moduli,
        "versioni": versioni,
        "regole": regole,
        "completion_rule": completion_rule,
        "n_sessioni": n_sessioni,
        "n_completamenti": n_completamenti,
        "sessioni_list": sessioni_list,
        "dipendenti_iscritti": dipendenti_iscritti,
        "n_dipendenti_iscritti": n_dipendenti_iscritti,
        "edit_form": edit_form,
        "dep_form": dep_form,
        "completion_form": completion_form,
        "version_form": version_form,
        "req_rule_form": req_rule_form,
        "is_editor": is_editor,
        "tutti_corsi": TrainingCourse.objects.exclude(pk=corso_id).filter(is_active=True).order_by("titolo"),
        "candidati_assegnazione": candidati_assegnazione,
        "assegnazione_pool_filtrato": assegnazione_pool_filtrato,
        "completamento_form": completamento_form,
        "dipendenti_pool": dipendenti_pool,
    })


@login_required
@require_POST
def formazione_corso_edit(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corsi_list")
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    form = TrainingCourseForm(request.POST, instance=corso)
    if form.is_valid():
        corso = form.save()
        form.salva_processi(corso)
        messages.success(request, f'Corso "{corso.titolo}" aggiornato.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_delete(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare corsi formativi.")
        return redirect("anagrafica:formazione_corsi_list")
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    if corso.sessioni.exists():
        messages.error(request, f'Il corso "{corso.titolo}" ha sessioni associate. Archivia o rimuovi prima le sessioni.')
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    piano_id = corso.piano_id
    nome = corso.titolo
    codice = corso.codice
    corso.delete()
    _audit_formazione(request, "corso_eliminato", {
        "corso_id": corso_id, "codice": codice, "titolo": nome, "piano_id": piano_id,
    })
    messages.success(request, f'Corso "{nome}" eliminato.')
    return redirect("anagrafica:formazione_piano_detail", piano_id=piano_id)


# ── Prerequisiti ────────────────────────────────────────────────────────────

@login_required
@require_POST
def formazione_corso_dep_add(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    form = TrainingCourseDependencyForm(request.POST, corso_principale=corso)
    if form.is_valid():
        prereq_id = form.cleaned_data["prerequisito_id"]
        prereq = get_object_or_404(TrainingCourse, pk=prereq_id)
        if prereq == corso:
            messages.error(request, "Un corso non può essere prerequisito di sé stesso.")
        else:
            _, created = TrainingCourseDependency.objects.get_or_create(
                corso_principale=corso,
                prerequisito=prereq,
                defaults={"obbligatorio": form.cleaned_data.get("obbligatorio", True)},
            )
            if created:
                messages.success(request, f'Prerequisito "{prereq.codice}" aggiunto.')
            else:
                messages.warning(request, "Prerequisito già presente.")
    else:
        messages.error(request, "Dati non validi per il prerequisito.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_dep_delete(request, corso_id: int, dep_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    dep = get_object_or_404(TrainingCourseDependency, pk=dep_id, corso_principale_id=corso_id)
    dep.delete()
    messages.success(request, "Prerequisito rimosso.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


# ── Programma didattico ─────────────────────────────────────────────────────
# Sul corso è il previsto; sull'edizione è ciò che è stato davvero erogato.
# Le due liste sono indipendenti per costruzione (vedi copia_programma_dal_corso).

def _ore_da_post(request, campo: str = "ore_previste"):
    """Ore previste dal POST: vuoto o non numerico valgono «non dichiarate»."""
    grezzo = (request.POST.get(campo) or "").strip().replace(",", ".")
    if not grezzo:
        return None
    try:
        return Decimal(grezzo)
    except (InvalidOperation, ValueError):
        return None


@login_required
@require_POST
def formazione_corso_argomento_add(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    argomento = (request.POST.get("argomento") or "").strip()
    if not argomento:
        messages.error(request, "L'argomento non può essere vuoto.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    ultimo = corso.programma.order_by("-ordine").values_list("ordine", flat=True).first() or 0
    TrainingCourseArgomento.objects.create(
        corso=corso,
        ordine=ultimo + 1,
        argomento=argomento[:300],
        ore_previste=_ore_da_post(request),
        riferimento=(request.POST.get("riferimento") or "").strip()[:200],
    )
    messages.success(request, "Argomento aggiunto al programma del corso.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_argomento_delete(request, corso_id: int, arg_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    voce = get_object_or_404(TrainingCourseArgomento, pk=arg_id, corso_id=corso_id)
    voce.delete()
    messages.success(request, "Argomento rimosso dal programma del corso. "
                              "Le edizioni già erogate non sono state toccate.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_sessione_argomento_add(request, sessione_id: int):
    """Argomento integrato dall'edizione: nasce con ``aggiunto=True`` e per questo
    sopravvive a una ricopiatura del programma dal corso."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    argomento = (request.POST.get("argomento") or "").strip()
    if not argomento:
        messages.error(request, "L'argomento non può essere vuoto.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    ultimo = sessione.programma.order_by("-ordine").values_list("ordine", flat=True).first() or 0
    TrainingSessionArgomento.objects.create(
        sessione=sessione,
        ordine=ultimo + 1,
        argomento=argomento[:300],
        ore_previste=_ore_da_post(request),
        riferimento=(request.POST.get("riferimento") or "").strip()[:200],
        aggiunto=True,
    )
    messages.success(request, "Argomento integrato nel programma dell'edizione.")
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_argomento_delete(request, sessione_id: int, arg_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    voce = get_object_or_404(TrainingSessionArgomento, pk=arg_id, sessione_id=sessione_id)
    voce.delete()
    messages.success(request, "Argomento rimosso dal programma dell'edizione.")
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_programma_riprendi(request, sessione_id: int):
    """Riporta nell'edizione il programma del corso. Le integrazioni restano."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    from ..services.formazione_pianificazione import copia_programma_dal_corso

    creati = copia_programma_dal_corso(sessione, forza=True)
    if creati:
        messages.success(request, f"{creati} argomenti ripresi dal programma del corso.")
    else:
        messages.info(request, "Il corso non ha un programma da riprendere.")
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_argomento_giornate(request, sessione_id: int, arg_id: int):
    """In quali giornate l'argomento è stato svolto: è il confronto previsto/erogato."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    voce = get_object_or_404(TrainingSessionArgomento, pk=arg_id, sessione_id=sessione_id)
    try:
        scelte = [int(x) for x in request.POST.getlist("lezioni")]
    except (TypeError, ValueError):
        scelte = []
    # Solo giornate di QUESTA edizione: un id arrivato da fuori non deve passare.
    valide = list(TrainingLesson.objects.filter(sessione_id=sessione_id, pk__in=scelte))
    voce.lezioni.set(valide)
    messages.success(request, f'Argomento "{voce.argomento[:40]}": {len(valide)} giornate segnate.')
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


# ── Versioni corso ───────────────────────────────────────────────────────────

@login_required
@require_POST
def formazione_corso_version_add(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    form = TrainingCourseVersionForm(request.POST)
    if form.is_valid():
        ver = form.save(commit=False)
        ver.corso = corso
        ver.revised_by = request.user
        ver.save()
        messages.success(request, f'Versione "{ver.version_label}" aggiunta.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_version_delete(request, corso_id: int, ver_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    ver = get_object_or_404(TrainingCourseVersion, pk=ver_id, corso_id=corso_id)
    ver.delete()
    messages.success(request, "Versione rimossa.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


# ── Regola superamento ───────────────────────────────────────────────────────

@login_required
@require_POST
def formazione_corso_completion_rule_save(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    try:
        instance = corso.regola_superamento
    except TrainingCompletionRule.DoesNotExist:
        instance = None
    form = TrainingCompletionRuleForm(request.POST, instance=instance)
    if form.is_valid():
        rule = form.save(commit=False)
        rule.corso = corso
        rule.save()
        messages.success(request, "Regola di superamento salvata.")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


# ── Regole obbligatorietà sul corso ─────────────────────────────────────────

@login_required
@require_POST
def formazione_corso_req_rule_add(request, corso_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    form = TrainingRequirementRuleForm(request.POST)
    if form.is_valid():
        rule = form.save(commit=False)
        rule.corso = corso
        rule.piano = None
        rule.created_by = request.user
        rule.save()
        messages.success(request, "Regola di obbligatorietà aggiunta.")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_req_rule_delete(request, corso_id: int, rule_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare corsi formativi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    rule = get_object_or_404(TrainingRequirementRule, pk=rule_id, corso_id=corso_id)
    rule.delete()
    messages.success(request, "Regola rimossa.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
@require_POST
def formazione_corso_assegna(request, corso_id: int):
    """Assegna in blocco dei dipendenti al corso (TrainingAssignment, stato ASSEGNATO).

    Primo anello del ciclo corso→sessione: chi è assegnato al corso viene poi proposto
    in cima ai candidati delle sue edizioni. Idempotente (unique_together corso×dip)."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per assegnare corsi.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse.objects.select_related("piano"), pk=corso_id)

    ids: list[int] = []
    seen: set[int] = set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    from ..services.elearning_fruizione import ciclo_per_nuova_assegnazione
    n_new = 0
    for lid in ids:
        _, created = TrainingAssignment.objects.get_or_create(
            corso=corso, legacy_anagrafica_id=lid, ciclo=ciclo_per_nuova_assegnazione(corso, lid),
            defaults={
                "stato": "ASSEGNATO",
                "piano": corso.piano,
                "assigned_by": request.user,
            },
        )
        if created:
            n_new += 1
    if n_new:
        messages.success(request, f"{n_new} dipendenti assegnati al corso.")
    else:
        messages.info(request, "I dipendenti selezionati erano già assegnati al corso.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


# ============================================================================
# FORMAZIONE HR — Istruttori (PATCH-03)
# ============================================================================

@login_required
def formazione_istruttori_list(request):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    filtro_tipo = request.GET.get("tipo", "")
    q_search = (request.GET.get("q") or "").strip()
    filtro_azienda = (request.GET.get("azienda") or "").strip()

    qs = TrainingInstructor.objects.select_related("azienda")
    if filtro_tipo:
        qs = qs.filter(tipo=filtro_tipo)
    if q_search:
        qs = qs.filter(
            Q(nome__icontains=q_search)
            | Q(ragione_sociale__icontains=q_search)
            | Q(azienda__nome__icontains=q_search)
        )
    if filtro_azienda == "NESSUNA":
        qs = qs.filter(azienda__isnull=True)
    elif filtro_azienda.isdigit():
        qs = qs.filter(azienda_id=int(filtro_azienda))

    istruttori = list(
        qs.annotate(
            n_sessioni=Count("sessioni", distinct=True),
            n_lezioni=Count("lezioni", distinct=True),
        ).order_by("nome")
    )

    # Le aziende formative aprono la pagina: sono l'ente da cui i docenti
    # arrivano, e il conteggio dice subito quali sono davvero in uso.
    # I docenti per ente sono prefetchati per poter espandere la riga senza
    # ricaricare la pagina; le ultime sessioni si recuperano con un'unica
    # query in blocco (per istruttore, non una per riga) per evitare N+1.
    aziende = list(
        TrainingProvider.objects
        .annotate(n_istruttori=Count("istruttori", distinct=True))
        .prefetch_related(Prefetch(
            "istruttori",
            queryset=TrainingInstructor.objects.annotate(
                n_sessioni=Count("sessioni", distinct=True)
            ).order_by("nome"),
        ))
        .order_by("nome")
    )
    tutti_istruttori_id = [i.pk for az in aziende for i in az.istruttori.all()]
    ultime_sessioni_per_istruttore = {}
    if tutti_istruttori_id:
        for sess in (
            TrainingSession.objects
            .filter(docente_id__in=tutti_istruttori_id)
            .select_related("corso")
            .order_by("docente_id", "-data_inizio")
        ):
            ultime_sessioni_per_istruttore.setdefault(sess.docente_id, []).append(sess)
    for az in aziende:
        for istr in az.istruttori.all():
            istr.ultime_sessioni = ultime_sessioni_per_istruttore.get(istr.pk, [])[:3]

    senza_azienda = TrainingInstructor.objects.filter(azienda__isnull=True).count()
    azienda_corrente = None
    if filtro_azienda.isdigit():
        azienda_corrente = next((a for a in aziende if a.pk == int(filtro_azienda)), None)

    return render(request, "anagrafica/pages/formazione_istruttori.html", {
        "istruttori": istruttori,
        "form": TrainingInstructorForm(),
        "provider_form": TrainingProviderForm(),
        "aziende": aziende,
        "senza_azienda": senza_azienda,
        "is_editor": is_editor,
        "filtro_tipo": filtro_tipo,
        "filtro_azienda": filtro_azienda,
        "azienda_corrente": azienda_corrente,
        "q_search": q_search,
        "TIPO_CHOICES": TrainingInstructor.TIPO_CHOICES,
    })


@login_required
def formazione_istruttore_detail(request, istruttore_id: int):
    """Scheda del docente: chi è, da quale ente arriva, e cosa ha erogato.

    I "corsi svolti" sono le sessioni in cui è docente titolare **oppure** ha
    tenuto almeno una lezione: nel portale le due cose possono divergere
    (titolare della sessione, docente della singola giornata) e per la
    tracciabilità contano entrambe.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    istr = get_object_or_404(TrainingInstructor.objects.select_related("azienda"), pk=istruttore_id)

    # Due passaggi: prima gli id distinti (senza ordinamento, che con DISTINCT
    # su SQL Server pretende la colonna nella select), poi la query annotata.
    sessioni_ids = list(
        TrainingSession.objects
        .filter(Q(docente_id=istr.pk) | Q(lezioni__docente_id=istr.pk))
        .order_by().values_list("id", flat=True).distinct()
    )
    sessioni = list(
        TrainingSession.objects.filter(pk__in=sessioni_ids)
        .select_related("corso")
        .annotate(n_iscritti=Count("iscrizioni", distinct=True))
        .prefetch_related("lezioni")
        .order_by("-data_inizio")
    )

    ore_erogate = 0.0
    for sess in sessioni:
        ore_erogate += sum(
            lz.durata_ore for lz in sess.lezioni.all()
            if lz.docente_id == istr.pk or (sess.docente_id == istr.pk and lz.docente_id is None)
        )
    corsi_distinti = len({s.corso_id for s in sessioni})
    discenti = sum(s.n_iscritti for s in sessioni)

    return render(request, "anagrafica/pages/formazione_istruttore_detail.html", {
        "istr": istr,
        "documenti": list(istr.documenti.all()),
        "doc_form": TrainingProviderDocumentForm(),
        "sessioni": sessioni,
        "ore_erogate": round(ore_erogate, 2),
        "corsi_distinti": corsi_distinti,
        "discenti": discenti,
        "is_editor": _helpers._can_edit_formazione(request),
    })


# -- Aziende formative (enti di formazione) -----------------------------------
# CRUD dalla stessa pagina dei docenti: l'ente non ha vita propria, esiste per
# raggruppare i docenti e per rispondere in verifica "chi ha erogato".

@login_required
@require_POST
def formazione_azienda_create(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare aziende formative.")
        return redirect("anagrafica:formazione_istruttori_list")
    form = TrainingProviderForm(request.POST)
    if form.is_valid():
        az = form.save()
        messages.success(request, f'Azienda formativa "{az.nome}" creata.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_istruttori_list")


@login_required
@require_POST
def formazione_azienda_edit(request, azienda_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare aziende formative.")
        return redirect("anagrafica:formazione_istruttori_list")
    az = get_object_or_404(TrainingProvider, pk=azienda_id)
    form = TrainingProviderForm(request.POST, instance=az)
    if form.is_valid():
        form.save()
        messages.success(request, f'Azienda formativa "{az.nome}" aggiornata.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_istruttori_list")


@login_required
def formazione_azienda_detail(request, azienda_id: int):
    """Scheda dell'ente: chi è, cosa ci ha erogato, con quali carte.

    È la pagina a cui porta la ricerca quando si cerca un ente formativo: la
    domanda dietro «cerco Formazione Sicura S.r.l.» non è «quali docenti ha»
    ma «cosa ci ha fatto». Il periodo (`?dal=`/`?al=`) ritaglia le erogazioni
    come sul libretto del dipendente.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    az = get_object_or_404(TrainingProvider, pk=azienda_id)
    dal, al = _helpers._periodo_da_request(request)

    from ..services.formazione_enti import erogazioni_di_ente

    erog = erogazioni_di_ente(az.pk, dal=dal, al=al)
    docenti = list(
        az.istruttori.annotate(n_sessioni=Count("sessioni", distinct=True)).order_by("nome")
    )
    return render(request, "anagrafica/pages/formazione_azienda_detail.html", {
        "az": az,
        "docenti": docenti,
        "documenti": list(az.documenti.all()),
        "doc_form": TrainingProviderDocumentForm(),
        "sessioni": erog["sessioni"],
        "per_corso": erog["per_corso"],
        "ore": erog["ore"],
        "discenti": erog["discenti"],
        "n_corsi": erog["n_corsi"],
        "dal": dal,
        "al": al,
        "periodo_attivo": bool(dal or al),
        "is_editor": _helpers._can_edit_formazione(request),
    })


@login_required
def formazione_enti_report(request):
    """«Chi ci ha formato»: una riga per ente, nel periodo scelto.

    Gli enti che nel periodo non hanno erogato niente restano in elenco a zero:
    un fornitore che non si usa più è un'informazione, non un'assenza.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    dal, al = _helpers._periodo_da_request(request)
    from ..services.formazione_enti import riepilogo_enti

    righe = riepilogo_enti(dal=dal, al=al)
    return render(request, "anagrafica/pages/formazione_enti_report.html", {
        "righe": righe,
        "dal": dal,
        "al": al,
        "periodo_attivo": bool(dal or al),
        "tot_sessioni": sum(r["n_sessioni"] for r in righe),
        "tot_ore": round(sum(r["ore"] for r in righe), 2),
        "tot_discenti": sum(r["discenti"] for r in righe),
        "enti_attivi": sum(1 for r in righe if r["n_sessioni"]),
    })


# ── Documenti di ente e docente ──────────────────────────────────────────────
# Accreditamento, contratto, CV, attestato del formatore: carte che in verifica
# vanno mostrate. Stesso trattamento degli altri documenti HR — archivio privato
# fuori webroot, download solo dalla view protetta, audit su ogni passaggio.

def _salva_documento_ente(request, *, azienda=None, docente=None):
    """Valida e salva l'upload. Ritorna il messaggio d'errore, o None."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return "Seleziona un file da caricare."

    # SEC: tipo verificato dal contenuto, senza ripiego sul Content-Type del browser.
    from ..services.upload_documenti import UploadMimeValidationError, valida_documento
    try:
        mime = valida_documento(uploaded, _helpers._ALLOWED_DOC_EXTENSIONS)
    except UploadMimeValidationError as exc:
        return f"File rifiutato: {exc} Ammessi: PDF, immagini (JPG, PNG, WEBP), DOC/DOCX, XLS/XLSX."

    form = TrainingProviderDocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return " ".join(str(e) for errs in form.errors.values() for e in errs)

    doc = form.save(commit=False)
    doc.azienda = azienda
    doc.docente = docente
    doc.nome_originale = (uploaded.name or "")[:255]
    doc.tipo_mime = mime
    doc.dimensione_bytes = uploaded.size
    doc.created_by = request.user
    doc.created_by_display = request.user.get_full_name() or request.user.username
    doc.save()

    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_DOC_ENTE_UPLOAD", "anagrafica", {
            "documento_id": doc.pk, "tipo": doc.tipo,
            "azienda_id": azienda.pk if azienda else None,
            "docente_id": docente.pk if docente else None,
            "nome_originale": doc.nome_originale,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_DOC_ENTE_UPLOAD fallito", exc_info=True)
    return None


@login_required
@require_POST
def formazione_azienda_documento_add(request, azienda_id: int):
    az = get_object_or_404(TrainingProvider, pk=azienda_id)
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per caricare documenti.")
        return redirect("anagrafica:formazione_azienda_detail", azienda_id=az.pk)
    errore = _salva_documento_ente(request, azienda=az)
    if errore:
        messages.error(request, errore)
    else:
        messages.success(request, "Documento caricato.")
    return redirect("anagrafica:formazione_azienda_detail", azienda_id=az.pk)


@login_required
@require_POST
def formazione_istruttore_documento_add(request, istruttore_id: int):
    istr = get_object_or_404(TrainingInstructor, pk=istruttore_id)
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per caricare documenti.")
        return redirect("anagrafica:formazione_istruttore_detail", istruttore_id=istr.pk)
    errore = _salva_documento_ente(request, docente=istr)
    if errore:
        messages.error(request, errore)
    else:
        messages.success(request, "Documento caricato.")
    return redirect("anagrafica:formazione_istruttore_detail", istruttore_id=istr.pk)


@login_required
@require_POST
def formazione_ente_documento_delete(request, documento_id: int):
    doc = get_object_or_404(TrainingProviderDocument, pk=documento_id)
    azienda_id, docente_id, nome = doc.azienda_id, doc.docente_id, doc.nome_originale
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare documenti.")
    else:
        doc.delete()
        try:
            from core.audit import log_action
            log_action(request, "FORMAZIONE_DOC_ENTE_ELIMINATO", "anagrafica", {
                "documento_id": documento_id, "azienda_id": azienda_id,
                "docente_id": docente_id, "nome_originale": nome,
            })
        except Exception:
            logger.warning("Audit FORMAZIONE_DOC_ENTE_ELIMINATO fallito", exc_info=True)
        messages.success(request, "Documento eliminato.")
    if azienda_id:
        return redirect("anagrafica:formazione_azienda_detail", azienda_id=azienda_id)
    return redirect("anagrafica:formazione_istruttore_detail", istruttore_id=docente_id)


@login_required
def formazione_ente_documento_download(request, documento_id: int):
    """Scarica il documento dall'archivio privato (ACL formazione + audit)."""
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)
    doc = get_object_or_404(TrainingProviderDocument, pk=documento_id)
    if not doc.file:
        return HttpResponse("File non disponibile.", status=404)
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_DOC_ENTE_DOWNLOAD", "anagrafica", {
            "documento_id": doc.pk, "tipo": doc.tipo,
            "azienda_id": doc.azienda_id, "docente_id": doc.docente_id,
        })
    except Exception:
        logger.warning("Audit FORMAZIONE_DOC_ENTE_DOWNLOAD fallito", exc_info=True)
    from django.http import FileResponse
    try:
        fh = doc.file.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    filename = doc.nome_originale or f"documento_{doc.pk}.bin"
    resp = FileResponse(fh, as_attachment=True, filename=filename)
    from core.download_security import harden_file_response
    return harden_file_response(resp, filename, inline=False)


# ── Espansione della tabella corsi: corso → edizioni → lezioni ───────────────
# Il catalogo corsi è l'elenco di ciò che *si può* fare; per sapere cosa è stato
# davvero erogato bisognava aprire il corso, poi l'edizione, poi le giornate.
# I due frammenti qui sotto aprono quei due livelli dentro la riga, caricati
# solo quando servono: 50 corsi × edizioni × lezioni renderizzati sempre
# sarebbero una pagina enorme per una cosa che si guarda una riga alla volta.

@login_required
def formazione_corso_espansione(request, corso_id: int):
    """Frammento HTMX: le edizioni di un corso, dentro la riga della tabella."""
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    sessioni = list(
        corso.sessioni
        .select_related("docente", "docente__azienda")
        .annotate(n_iscritti=Count("iscrizioni", distinct=True), n_lezioni=Count("lezioni", distinct=True))
        .order_by("-data_inizio")
    )
    return render(request, "anagrafica/partials/_formazione_corso_espansione.html", {
        "corso": corso,
        "sessioni": sessioni,
    })


@login_required
def formazione_sessione_espansione(request, sessione_id: int):
    """Frammento HTMX: le giornate di un'edizione, dentro la riga espansa."""
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    lezioni = list(
        sessione.lezioni.select_related("docente").order_by("data", "ora_inizio")
    )
    return render(request, "anagrafica/partials/_formazione_sessione_espansione.html", {
        "sessione": sessione,
        "lezioni": lezioni,
    })


@login_required
@require_POST
def formazione_azienda_delete(request, azienda_id: int):
    """Elimina l'ente solo se non ha docenti; altrimenti lo disattiva.

    Stessa prudenza già applicata ai docenti: quello che è citato da altro non
    sparisce, si spegne — così lo storico resta leggibile.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare aziende formative.")
        return redirect("anagrafica:formazione_istruttori_list")
    az = get_object_or_404(TrainingProvider, pk=azienda_id)
    if az.istruttori.exists():
        az.is_active = False
        az.save(update_fields=["is_active"])
        messages.warning(request, f'Azienda formativa "{az.nome}" disattivata (ha docenti associati).')
    else:
        nome = az.nome
        az.delete()
        messages.success(request, f'Azienda formativa "{nome}" eliminata.')
    return redirect("anagrafica:formazione_istruttori_list")


@login_required
@require_POST
def formazione_istruttore_create(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare istruttori.")
        return redirect("anagrafica:formazione_istruttori_list")
    form = TrainingInstructorForm(request.POST)
    if form.is_valid():
        istr = form.save()
        messages.success(request, f'Istruttore "{istr.nome}" creato.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_istruttori_list")


@login_required
@require_POST
def formazione_istruttore_edit(request, istruttore_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare istruttori.")
        return redirect("anagrafica:formazione_istruttori_list")
    istr = get_object_or_404(TrainingInstructor, pk=istruttore_id)
    form = TrainingInstructorForm(request.POST, instance=istr)
    if form.is_valid():
        form.save()
        messages.success(request, f'Istruttore "{istr.nome}" aggiornato.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_istruttori_list")


@login_required
@require_POST
def formazione_istruttore_delete(request, istruttore_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare istruttori.")
        return redirect("anagrafica:formazione_istruttori_list")
    istr = get_object_or_404(TrainingInstructor, pk=istruttore_id)
    if istr.sessioni.exists() or istr.lezioni.exists():
        istr.is_active = False
        istr.save()
        messages.warning(request, f'Istruttore "{istr.nome}" disattivato (ha sessioni/lezioni associate).')
    else:
        nome = istr.nome
        istr.delete()
        messages.success(request, f'Istruttore "{nome}" eliminato.')
    return redirect("anagrafica:formazione_istruttori_list")


# ============================================================================
# FORMAZIONE HR — Sessioni formative (PATCH-04)
# ============================================================================

@login_required
def formazione_sessioni_list(request):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    filtro_corso  = request.GET.get("corso", "")
    filtro_stato  = request.GET.get("stato", "")
    filtro_anno   = request.GET.get("anno", "")
    q_search      = (request.GET.get("q") or "").strip()

    qs = TrainingSession.objects.select_related("corso", "corso__piano", "docente").all()
    if filtro_corso:
        qs = qs.filter(corso_id=filtro_corso)
    if filtro_stato:
        qs = qs.filter(stato=filtro_stato)
    if filtro_anno:
        qs = qs.filter(data_inizio__year=filtro_anno)
    if q_search:
        qs = qs.filter(
            Q(codice_sessione__icontains=q_search) |
            Q(corso__titolo__icontains=q_search) |
            Q(sede__icontains=q_search)
        )

    paginator = Paginator(qs.order_by("-data_inizio"), 50)
    page_obj  = paginator.get_page(request.GET.get("page"))

    corsi_attivi = list(TrainingCourse.objects.filter(is_active=True).order_by("titolo"))
    anni = list(
        TrainingSession.objects
        .values_list("data_inizio__year", flat=True)
        .distinct()
        .order_by("-data_inizio__year")
    )

    return render(request, "anagrafica/pages/formazione_sessioni.html", {
        "page_obj": page_obj,
        "is_editor": is_editor,
        "filtro_corso": filtro_corso,
        "filtro_stato": filtro_stato,
        "filtro_anno": filtro_anno,
        "q_search": q_search,
        "corsi_attivi": corsi_attivi,
        "anni": anni,
        "STATO_CHOICES": TrainingSession.STATO_CHOICES,
    })


@login_required
@require_POST
def formazione_rinnovo_da_scadenzario(request):
    """Punto d'ingresso «seleziona dipendenti → sessione di rinnovo»: raccoglie i
    dipendenti selezionati per un corso e li porta nel FLUSSO STANDARD di creazione
    sessione (``formazione_sessione_create``). Gli id restano in ``request.session``
    e vengono iscritti in blocco al salvataggio della sessione."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare sessioni di rinnovo.")
        return redirect("anagrafica:formazione_scadenzario")
    try:
        corso = TrainingCourse.objects.get(pk=request.POST.get("corso_id"), is_active=True)
    except (TrainingCourse.DoesNotExist, ValueError, TypeError):
        messages.error(request, "Corso non valido.")
        return redirect("anagrafica:formazione_scadenzario")
    ids, seen = [], set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        from core.redirects import safe_next

        return redirect(safe_next(request, request.POST.get("back"), reverse("anagrafica:scadenzario")))
    request.session["rinnovo_preselect"] = {"corso": corso.pk, "ids": ids}
    messages.info(request, f"{len(ids)} dipendenti pronti per il rinnovo: compila la sessione.")
    return redirect(f"{reverse('anagrafica:formazione_sessione_create')}?corso={corso.pk}")


@login_required
def formazione_sessione_create(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per creare sessioni formative.")
        return redirect("anagrafica:formazione_sessioni_list")
    if request.method == "POST":
        form = TrainingSessionForm(request.POST)
        if form.is_valid():
            sessione = form.save(commit=False)
            sessione.created_by = request.user
            sessione.save()
            # L'edizione parte dal programma del corso, come copia modificabile:
            # documenterà ciò che ha davvero erogato anche se il corso cambierà.
            from ..services.formazione_pianificazione import copia_programma_dal_corso
            copia_programma_dal_corso(sessione)
            # Materiale del corso spuntato nel form: copiato sull\'edizione (copia,
            # non collegamento, come il programma qui sopra).
            n_allegati = form.copia_allegati(user=request.user)
            if n_allegati:
                messages.info(
                    request,
                    f"{n_allegati} allegat{'o' if n_allegati == 1 else 'i'} del corso "
                    f"riportat{'o' if n_allegati == 1 else 'i'} sull\'edizione.",
                )
            # Rinnovo dallo scadenzario: se ci sono dipendenti pre-selezionati per
            # QUESTO corso, iscrivili in blocco (idempotente) e vai agli iscritti.
            pre = request.session.get("rinnovo_preselect")
            if pre and pre.get("corso") == sessione.corso_id and pre.get("ids"):
                n_new = 0
                for lid in pre["ids"]:
                    _, created = TrainingEnrollment.objects.get_or_create(
                        sessione=sessione, legacy_anagrafica_id=lid,
                        defaults={"stato": "ISCRITTO", "iscritto_da": request.user},
                    )
                    if created:
                        n_new += 1
                request.session.pop("rinnovo_preselect", None)
                messages.success(request, f'Sessione "{sessione.codice_sessione}" creata; {n_new} dipendenti iscritti per il rinnovo.')
                return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione.pk)
            messages.success(request, f'Sessione "{sessione.codice_sessione}" creata.')
            return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione.pk)
    else:
        initial = {}
        if request.GET.get("corso"):
            initial["corso"] = request.GET.get("corso")
        form = TrainingSessionForm(initial=initial)
    return render(request, "anagrafica/pages/formazione_sessione_form.html", {
        "form": form,
        "modo": "crea",
    })


@login_required
def formazione_sessione_detail(request, sessione_id: int):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    sessione = get_object_or_404(
        TrainingSession.objects.select_related(
            "corso", "corso__piano", "corso__ente_formativo", "docente", "docente_ente",
        ),
        pk=sessione_id,
    )
    lezioni  = list(sessione.lezioni.select_related("docente").order_by("data", "ora_inizio"))
    # Il numero della giornata non si digita: si mostra quello che verra' assegnato
    # (massimo in uso + 1, non il conteggio: un numero gia' stampato sul registro
    # firme non deve rinascere).
    prossimo_numero_lezione = max((lz.numero for lz in lezioni), default=0) + 1
    n_iscritti = sessione.iscrizioni.count()

    # Presenze registrate per lezione (1 query aggregata).
    presenze_per_lezione = {
        row["lezione_id"]: row["n"]
        for row in (
            TrainingLessonAttendance.objects
            .filter(lezione__sessione=sessione)
            .values("lezione_id")
            .annotate(n=Count("id"))
        )
    }
    # Allegati (registro firmato / materiale): livello sessione + per-lezione.
    allegati = list(sessione.allegati.select_related("lezione").order_by("-created_at"))
    allegati_sessione = [a for a in allegati if a.lezione_id is None]
    allegati_per_lezione: dict[int, list] = {}
    for a in allegati:
        if a.lezione_id is not None:
            allegati_per_lezione.setdefault(a.lezione_id, []).append(a)
    for lz in lezioni:
        lz.n_presenze = presenze_per_lezione.get(lz.pk, 0)
        lz.allegati_list = allegati_per_lezione.get(lz.pk, [])

    # Programma dell'edizione con la copertura: per ogni argomento, in quali
    # giornate è stato svolto. È il confronto fra previsto ed erogato.
    programma = list(sessione.programma.prefetch_related("lezioni"))
    for voce in programma:
        svolte = {lz.pk for lz in voce.lezioni.all()}
        voce.giornate_svolte = sorted(
            lz.numero for lz in lezioni if lz.pk in svolte
        )
        voce.scelte_giornate = [
            {"lezione": lz, "segnata": lz.pk in svolte} for lz in lezioni
        ]
    programma_scoperti = sum(1 for v in programma if not v.giornate_svolte)

    edit_form   = TrainingSessionForm(instance=sessione)
    lezione_form = TrainingLessonForm(sessione=sessione)
    # Generatore giornate: propone l'orario-tipo dell'ultima lezione già inserita,
    # così allungare una sessione non fa ridigitare orari e pausa.
    _ultima = lezioni[-1] if lezioni else None
    genera_form = TrainingLezioniGeneraForm(initial={
        "ora_inizio":   _ultima.ora_inizio if _ultima else "08:00",
        "ora_fine":     _ultima.ora_fine if _ultima else "17:00",
        "pausa_minuti": _ultima.pausa_minuti if _ultima else 60,
    })

    # Monte ore pianificato vs durata teorica del corso: lo scostamento è il primo
    # segnale che il calendario non regge (pausa dimenticata, giornata mancante).
    ore_pianificate = round(sum(lz.durata_ore for lz in lezioni), 2)
    ore_teoriche = float(sessione.corso.durata_ore_teorica or 0)
    ore_scostamento = round(ore_pianificate - ore_teoriche, 2) if ore_teoriche else 0.0

    # Gruppi gemelli della stessa edizione (corso diviso per motivi logistici):
    # ogni gruppo È una sessione a sé, l'edizione li tiene solo collegati in UI.
    gruppi_gemelli = list(
        sessione.sessioni_gemelle()
        .select_related("docente")
        .annotate(n_iscritti_gruppo=Count("iscrizioni", distinct=True))
    )
    dividi_form = TrainingDividiGruppiForm(initial={"n_gruppi": 2})

    # Edizione chiusa: i comandi di modifica spariscono (il server li rifiuta
    # comunque) e resta il pannello di chiusura con riapertura motivata.
    from ..services.formazione_integrita import motivo_blocco_edizione, requisiti_approvazione
    can_approve = _can_approve_formazione(request)
    gestore = is_editor
    is_editor = is_editor and not sessione.is_chiusa
    dovuta = sessione.verifica_nc_dovuta_dal

    return render(request, "anagrafica/pages/formazione_sessione_detail.html", {
        "gestore":      gestore,
        "can_approve":  can_approve,
        "can_reopen":   gestore and (can_approve or not sessione.is_approvata),
        "motivo_blocco": motivo_blocco_edizione(sessione),
        "requisiti_approvazione": requisiti_approvazione(sessione),
        "verifica_nc_scaduta": bool(dovuta and dovuta <= django_timezone.localdate()),
        "sessione":     sessione,
        "lezioni":      lezioni,
        "prossimo_numero_lezione": prossimo_numero_lezione,
        "n_iscritti":   n_iscritti,
        "edit_form":    edit_form,
        "lezione_form": lezione_form,
        "genera_form":  genera_form,
        "ore_pianificate": ore_pianificate,
        "ore_teoriche":    ore_teoriche,
        "ore_scostamento": ore_scostamento,
        "programma":          programma,
        "programma_scoperti": programma_scoperti,
        "is_editor":    is_editor,
        "allegati_sessione": allegati_sessione,
        "ATTACH_TIPI":  TrainingAttachment.Tipo.choices,
        "gruppi_gemelli": gruppi_gemelli,
        "dividi_form":    dividi_form,
    })


@login_required
@require_POST
def formazione_sessione_edit(request, sessione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessioni_list")
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    form = TrainingSessionForm(request.POST, instance=sessione)
    if form.is_valid():
        form.save()
        messages.success(request, f'Sessione "{sessione.codice_sessione}" aggiornata.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_delete(request, sessione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per eliminare sessioni formative.")
        return redirect("anagrafica:formazione_sessioni_list")
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="approvata")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    if sessione.iscrizioni.exists():
        messages.error(
            request,
            f'La sessione "{sessione.codice_sessione}" ha iscrizioni. '
            "Rimuovi prima gli iscritti o annulla la sessione.",
        )
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    corso_id = sessione.corso_id
    codice   = sessione.codice_sessione
    n_lezioni = sessione.lezioni.count()
    sessione.delete()
    _audit_formazione(request, "sessione_eliminata", {
        "sessione_id": sessione_id, "codice_sessione": codice,
        "corso_id": corso_id, "lezioni_eliminate": n_lezioni,
    })
    messages.success(request, f'Sessione "{codice}" eliminata.')
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


# ── Lezioni ──────────────────────────────────────────────────────────────────

@login_required
@require_POST
def formazione_lezione_add(request, sessione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    form = TrainingLessonForm(request.POST, sessione=sessione)
    if form.is_valid():
        lezione = form.save(commit=False)
        lezione.sessione = sessione
        lezione.updated_by = request.user
        lezione.save()
        messages.success(request, f'Lezione {lezione.numero} aggiunta.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_lezione_edit(request, sessione_id: int, lezione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    lezione  = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)
    form = TrainingLessonForm(request.POST, instance=lezione, sessione=sessione)
    if form.is_valid():
        lz = form.save(commit=False)
        lz.updated_by = request.user
        lz.save()
        messages.success(request, f'Lezione {lezione.numero} aggiornata.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_lezione_delete(request, sessione_id: int, lezione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    lezione = get_object_or_404(TrainingLesson, pk=lezione_id, sessione_id=sessione_id)
    num = lezione.numero
    n_presenze = lezione.presenze.count()
    data = lezione.data.isoformat() if lezione.data else ""
    lezione.delete()
    _audit_formazione(request, "lezione_eliminata", {
        "sessione_id": sessione_id, "lezione_id": lezione_id,
        "numero": num, "data": data, "presenze_eliminate": n_presenze,
    })
    messages.success(request, f'Lezione {num} eliminata.')
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_lezioni_genera(request, sessione_id: int):
    """Genera in blocco le giornate della sessione con un orario-tipo comune.

    Una lezione per ogni giorno dell'intervallo che cade nei giorni della
    settimana selezionati (o per ogni data puntuale indicata), pausa scalata
    dalle ore formative. Salta i giorni che hanno già una lezione, così si può
    rilanciare dopo aver allungato la sessione."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    form = TrainingLezioniGeneraForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    from ..services.formazione_pianificazione import genera_lezioni, giorni_da_pianificare
    cd = form.cleaned_data
    date_puntuali = cd.get("date_puntuali_lista") or []
    giorni_settimana = None if date_puntuali else {int(g) for g in cd.get("giorni_settimana") or []}
    # Generazione e allargamento dell'intervallo sono un'unica mossa: un errore a
    # meta' non deve lasciare lezioni fuori dalle date dichiarate dalla sessione.
    with transaction.atomic():
        richiesti = giorni_da_pianificare(
            sessione, giorni_settimana=giorni_settimana, date_puntuali=date_puntuali or None,
        )
        creati = genera_lezioni(
            sessione,
            ora_inizio=cd["ora_inizio"],
            ora_fine=cd["ora_fine"],
            pausa_minuti=cd.get("pausa_minuti") or 0,
            argomento=cd.get("argomento") or "",
            docente=cd.get("docente"),
            giorni_settimana=giorni_settimana,
            date_puntuali=date_puntuali or None,
            user=request.user,
        )
        if date_puntuali:
            # Date puntuali possono cadere fuori dall'intervallo attuale: lo si allarga
            # per tenerlo coerente con le lezioni effettivamente a calendario.
            aggiorna = {}
            if min(date_puntuali) < sessione.data_inizio:
                aggiorna["data_inizio"] = min(date_puntuali)
            if max(date_puntuali) > sessione.data_fine:
                aggiorna["data_fine"] = max(date_puntuali)
            if aggiorna:
                for campo, valore in aggiorna.items():
                    setattr(sessione, campo, valore)
                sessione.save(update_fields=list(aggiorna.keys()))
    gia_presenti = len(richiesti) - len(creati)
    if creati:
        ore = round(sum(lz.durata_ore for lz in creati), 2)
        # Generazione parziale: dire quante erano gia' a calendario evita che
        # "3 giornate generate" su 5 richieste sembri una perdita di dati.
        extra = f' {gia_presenti} erano già a calendario.' if gia_presenti else ""
        messages.success(
            request,
            f'{len(creati)} giornat{"a" if len(creati) == 1 else "e"} generat'
            f'{"a" if len(creati) == 1 else "e"} ({ore:g} ore formative).{extra}',
        )
    else:
        messages.info(
            request,
            "Nessuna giornata da generare: i giorni scelti hanno già una lezione "
            "(o non cadono nei giorni della settimana selezionati).",
        )
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_sessione_dividi_gruppi(request, sessione_id: int):
    """Divide gli iscritti già presenti nella sessione in più gruppi logistici.

    Caso reale: 10 iscritti su un'unica sessione, ma l'aula (o il turno) non li
    contiene tutti insieme — servono 2 gruppi da 5, ciascuno con il proprio
    calendario. Ogni gruppo È una sessione a sé (stesso corso, programma clonato);
    l'``edizione`` è solo l'etichetta che li tiene collegati in UI. Vedi
    services.formazione_pianificazione.dividi_in_gruppi."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare sessioni formative.")
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "detail", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    form = TrainingDividiGruppiForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    from ..services.formazione_pianificazione import dividi_in_gruppi
    cd = form.cleaned_data
    try:
        gruppi = dividi_in_gruppi(
            sessione,
            n_gruppi=cd["n_gruppi"],
            edizione=cd.get("edizione") or "",
            giorni_tra_gruppi=cd.get("giorni_tra_gruppi") or 0,
            user=request.user,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)

    codici = ", ".join(g.codice_sessione for g in gruppi)
    messages.success(
        request,
        f'Divisa in {len(gruppi)} gruppi (edizione «{gruppi[0].edizione}»): {codici}.',
    )
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


# ============================================================================
# FORMAZIONE HR — Iscritti e Presenze (PATCH-05)
# ============================================================================

def _can_approve_formazione(request) -> bool:
    """Approvazione MOD.040 (MT CN 06 §9.3): MSM, o MSO quale delegato.

    Permesso canonico dedicato, non derivato dalla gestione: chi registra i
    corsi non approva per default. Superutenti e admin legacy passano."""
    if request.user.is_superuser:
        return True
    legacy_user = get_legacy_user(request.user)
    if is_legacy_admin(legacy_user):
        return True
    if _helpers._ruoli_attivi():
        return _helpers._puo_su_tutti(request, "formazione", "approvare")
    return _helpers._has_canonical_grant(request, PERM_FORMAZIONE_APPROVE, legacy_user=legacy_user)


def _redirect_se_edizione_chiusa(request, sessione_id: int, dest: str = "detail", *,
                                 livello: str = "chiusa", lezione_id: int | None = None):
    """Redirect con messaggio se l'edizione è chiusa, None se si può procedere.

    ``livello="chiusa"`` blocca le edizioni COMPLETATE o approvate (calendario,
    iscritti, presenze); ``livello="approvata"`` solo quelle approvate (esiti
    degli iscritti, che si chiudono dopo la fine dell'edizione)."""
    from ..services.formazione_integrita import motivo_blocco_edizione

    sessione = TrainingSession.objects.filter(pk=sessione_id).first()
    if sessione is None:
        return None
    if livello == "approvata" and not sessione.is_approvata:
        return None
    motivo = motivo_blocco_edizione(sessione)
    if not motivo:
        return None
    messages.error(request, motivo)
    if dest == "iscritti":
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if dest == "presenze" and lezione_id:
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)
    return redirect("anagrafica:formazione_sessione_detail", sessione_id=sessione_id)


def _ricalcola_presenza_enrollment(enrollment: TrainingEnrollment) -> None:
    """Ricalcola e salva ore_frequentate e percentuale_presenza dell'iscrizione dalle
    presenze registrate su tutte le lezioni della sessione."""
    perc = _helpers._calcola_percentuale_presenza(enrollment)
    ore = sum(
        float(pr.ore_effettive) if pr.ore_effettive else lz.durata_ore
        for lz, pr in [
            (lz, TrainingLessonAttendance.objects.filter(
                lezione=lz, legacy_anagrafica_id=enrollment.legacy_anagrafica_id
            ).first())
            for lz in enrollment.sessione.lezioni.all()
        ]
        if pr and pr.stato_presenza in ("PRESENTE", "PARZIALE")
    )
    enrollment.ore_frequentate = round(ore, 2)
    enrollment.percentuale_presenza = perc
    enrollment.save(update_fields=["ore_frequentate", "percentuale_presenza"])


def _motivi_blocco_completamento(iscrizione: TrainingEnrollment) -> list[str]:
    """Motivi che impediscono un completamento *conforme* (Accordo Stato-Regioni 2025),
    secondo la regola di superamento del corso: verifica finale non superata e/o
    frequenza sotto la soglia minima. Lista vuota = nessun blocco (o nessuna regola)."""
    corso = iscrizione.sessione.corso
    try:
        regola = corso.regola_superamento
    except TrainingCompletionRule.DoesNotExist:
        return []
    motivi: list[str] = []
    if regola.richiede_esame_finale and iscrizione.verifica_superata is not True:
        motivi.append("verifica finale di apprendimento non superata o non registrata")
    soglia = regola.presenza_minima_percentuale or 0
    if soglia:
        perc = iscrizione.percentuale_presenza
        if perc is None:
            perc = _helpers._calcola_percentuale_presenza(iscrizione)
        if perc is not None and float(perc) < float(soglia):
            motivi.append(f"frequenza {float(perc):.0f}% inferiore al minimo richiesto ({soglia}%)")
    return motivi


def _crea_employee_record(enrollment: TrainingEnrollment, created_by) -> TrainingEmployeeRecord | None:
    """Crea TrainingEmployeeRecord con tutti i campi snapshot al completamento.

    Ritorna None se il record esiste già (idempotente).
    Segna TrainingDeadline.needs_refresh=True per invalidare la cache scadenze.
    """
    if hasattr(enrollment, "record_completamento") and enrollment.record_completamento_id:
        return None

    corso    = enrollment.sessione.corso
    sessione = enrollment.sessione
    from django.utils import timezone as _tz
    oggi = _tz.localdate()

    data_completamento = enrollment.data_completamento or oggi
    if data_completamento > oggi:
        # Sessione con date future (pianificata, anno sbagliato): il corso si chiude
        # oggi. In prod c'erano completamenti al 31/12 e al 2029 che, presi per
        # «ultimi», nascondevano quelli veri nel motore dei requisiti.
        logger.warning("Completamento iscrizione %s datato %s nel futuro: registrato a oggi",
                       enrollment.pk, data_completamento)
        data_completamento = oggi
    data_scadenza = None
    if corso.validita_mesi:
        data_scadenza = _helpers._add_months(data_completamento, corso.validita_mesi)

    try:
        completion_rule = corso.regola_superamento
        rule_json = {
            "ore_minime": completion_rule.ore_minime_percentuale,
            "presenza_minima": completion_rule.presenza_minima_percentuale,
            "esame": completion_rule.richiede_esame_finale,
        }
    except TrainingCompletionRule.DoesNotExist:
        rule_json = {}

    record = TrainingEmployeeRecord.objects.create(
        corso=corso,
        sessione=sessione,
        enrollment=enrollment,
        legacy_anagrafica_id=enrollment.legacy_anagrafica_id,
        data_completamento=data_completamento,
        ore_frequentate=enrollment.ore_frequentate or 0,
        percentuale_presenza=enrollment.percentuale_presenza,
        idoneo=enrollment.idoneo if enrollment.idoneo is not None else True,
        data_scadenza=data_scadenza,
        # Snapshot storici
        course_code_snapshot=corso.codice,
        course_title_snapshot=corso.titolo,
        course_version_snapshot=corso.versione,
        plan_code_snapshot=corso.piano.codice if corso.piano_id else "",
        plan_name_snapshot=corso.piano.nome if corso.piano_id else "",
        duration_hours_snapshot=corso.durata_ore_teorica,
        validity_months_snapshot=corso.validita_mesi,
        completion_rule_snapshot_json=rule_json,
        session_code_snapshot=sessione.codice_sessione,
        teacher_name_snapshot=(sessione.erogatore_display or "")[:200],
        completion_calculation_snapshot_json={
            "ore_frequentate": str(enrollment.ore_frequentate or 0),
            "percentuale": str(enrollment.percentuale_presenza or ""),
        },
    )

    _post_completamento(record, created_by)
    return record


def _post_completamento(record: TrainingEmployeeRecord, created_by) -> None:
    """Effetti collaterali comuni a OGNI completamento, da qualunque strada arrivi
    (iscrizione a sessione, e-learning, registrazione diretta senza sessione):
    invalidazione/ricalcolo scadenze, allineamento qualifica, archiviazione
    attestato. Tutti fail-safe: un errore qui non deve annullare il completamento."""
    corso = record.corso

    # Invalida cache scadenze per questo dipendente × corso
    TrainingDeadline.objects.filter(
        corso=corso,
        legacy_anagrafica_id=record.legacy_anagrafica_id,
    ).update(needs_refresh=True)

    # Tenta ricalcolo immediato (stub — NON lancia eccezione se non ancora implementato)
    try:
        from ..services.training_deadline_service import refresh_deadlines
        refresh_deadlines(legacy_id=record.legacy_anagrafica_id, corso_id=corso.pk)
    except NotImplementedError:
        pass  # PATCH-06 implementerà il ricalcolo completo

    # Valutazione di efficacia: se il corso la prevede, il completamento apre la
    # pendenza datata. Qui perché è il punto unico attraversato da tutte le
    # strade del completamento (aula, e-learning, registrazione diretta).
    try:
        from ..services.formazione_efficacia import pianifica_valutazione_efficacia
        pianifica_valutazione_efficacia(record)
    except Exception:
        pass  # fail-safe: non deve mai annullare un completamento

    # Allineamento qualifica (competency management): se il corso rilascia/rinnova una
    # qualifica e il completamento è idoneo, crea/aggiorna la DipendenteQualifica corrente
    # collegandola al record (la prova formativa). Riusa la convenzione "una qualifica
    # corrente per (dip, tipo), niente duplicati". Fail-safe: non deve bloccare il
    # completamento.
    try:
        if corso.qualifica_id and record.idoneo:
            qual, _ = _helpers._upsert_dipendente_qualifica(
                record.legacy_anagrafica_id, corso.qualifica,
                record.data_completamento, record.data_scadenza,
                user=created_by,
            )
            if qual.record_formazione_id != record.pk:
                qual.record_formazione = record
                qual.save(update_fields=["record_formazione"])
    except Exception:
        logger.exception("Allineamento qualifica fallito per record %s", record.pk)

    # Archiviazione automatica dell'attestato nel box documenti del dipendente
    # (se abilitata da Impostazioni → Template attestato). Fail-safe: un errore
    # qui NON deve impedire la registrazione del completamento.
    try:
        from ..models_formazione import AttestatoFormazioneConfig
        cfg = AttestatoFormazioneConfig.get_instance()
        if cfg.auto_salva_attestato:
            from ..services.attestato_pdf import archivia_attestato
            archivia_attestato(record, cfg=cfg, user=created_by)
    except Exception:
        logger.exception("Archiviazione automatica attestato fallita per record %s", record.pk)


def _crea_record_diretto(
    corso, legacy_id: int, data_completamento, ore_frequentate,
    idoneo: bool, erogato_da: str, note: str, created_by,
) -> TrainingEmployeeRecord | None:
    """Completamento **senza sessione**: corso frequentato altrove o storico.

    ``TrainingEmployeeRecord.sessione`` è nullable proprio per questo caso: si va
    a libretto senza inventare una sessione e un registro presenze mai esistiti.
    Idempotente su (corso, dipendente, data): ritorna None se il record c'è già."""
    if TrainingEmployeeRecord.objects.filter(
        corso=corso, legacy_anagrafica_id=legacy_id, data_completamento=data_completamento,
    ).exists():
        return None

    data_scadenza = None
    if corso.validita_mesi:
        data_scadenza = _helpers._add_months(data_completamento, corso.validita_mesi)

    ore = ore_frequentate if ore_frequentate is not None else (corso.durata_ore_teorica or 0)
    record = TrainingEmployeeRecord.objects.create(
        corso=corso,
        sessione=None,
        enrollment=None,
        legacy_anagrafica_id=legacy_id,
        data_completamento=data_completamento,
        ore_frequentate=ore,
        percentuale_presenza=None,
        idoneo=idoneo,
        data_scadenza=data_scadenza,
        note=note or "",
        # Nessuna auto-validazione: la validazione formale (MT CN 06 §9.3) è un
        # atto di MSM/MSO, non di chi registra.
        # Snapshot storici (nessuna sessione: il codice edizione resta vuoto)
        course_code_snapshot=corso.codice,
        course_title_snapshot=corso.titolo,
        course_version_snapshot=corso.versione,
        plan_code_snapshot=corso.piano.codice if corso.piano_id else "",
        plan_name_snapshot=corso.piano.nome if corso.piano_id else "",
        duration_hours_snapshot=corso.durata_ore_teorica,
        validity_months_snapshot=corso.validita_mesi,
        session_code_snapshot="",
        teacher_name_snapshot=(erogato_da or "")[:200],
        completion_calculation_snapshot_json={
            "origine": "REGISTRAZIONE_DIRETTA",
            "ore_frequentate": str(ore),
        },
    )
    _post_completamento(record, created_by)
    return record


@login_required
@require_POST
def formazione_corso_completamento_diretto(request, corso_id: int):
    """Registra il completamento del corso per i dipendenti selezionati **senza
    creare una sessione**: corso già frequentato presso un ente esterno, o storico
    recuperato. Il record finisce a libretto e nello scadenzario come gli altri."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per registrare completamenti.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse.objects.select_related("piano"), pk=corso_id)

    form = TrainingCompletamentoDirettoForm(request.POST)
    ids: list[int] = []
    seen: set[int] = set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)

    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)

    cd = form.cleaned_data
    n_new = 0
    for lid in ids:
        try:
            # Il vincolo univoco (corso, persona, data) è l'ultima difesa contro
            # il doppio invio: il doppione si salta, non rompe gli altri.
            with transaction.atomic():
                rec = _crea_record_diretto(
                    corso, lid,
                    data_completamento=cd["data_completamento"],
                    ore_frequentate=cd.get("ore_frequentate"),
                    idoneo=bool(cd.get("idoneo")),
                    erogato_da=cd.get("erogato_da") or "",
                    note=cd.get("note") or "",
                    created_by=request.user,
                )
        except IntegrityError:
            rec = None
        if rec is not None:
            n_new += 1
    if n_new:
        messages.success(
            request,
            f"{n_new} completament{'o' if n_new == 1 else 'i'} registrat"
            f"{'o' if n_new == 1 else 'i'} senza sessione.",
        )
    else:
        messages.info(request, "Nessun nuovo completamento: erano già tutti a libretto per quella data.")
    return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)


@login_required
def formazione_sessione_iscritti(request, sessione_id: int):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    sessione = get_object_or_404(
        TrainingSession.objects.select_related("corso", "corso__piano"),
        pk=sessione_id,
    )
    iscrizioni = list(
        TrainingEnrollment.objects.filter(sessione=sessione)
        .order_by("legacy_anagrafica_id")
    )
    lezioni = list(sessione.lezioni.order_by("data", "ora_inizio"))

    # Mappa presenze: {(legacy_id, lezione_id): stato_presenza}
    ids = [i.legacy_anagrafica_id for i in iscrizioni]
    presenze_qs = TrainingLessonAttendance.objects.filter(
        lezione__in=lezioni,
        legacy_anagrafica_id__in=ids,
    ).values("lezione_id", "legacy_anagrafica_id", "stato_presenza")
    presenze_map: dict[tuple, str] = {
        (p["legacy_anagrafica_id"], p["lezione_id"]): p["stato_presenza"]
        for p in presenze_qs
    }

    # Turni: a quali lezioni è assegnato ciascun iscritto (vuoto = tutte le lezioni).
    from ..services.training_turni import mappa_turni_sessione
    turni_map = mappa_turni_sessione(sessione) if lezioni else {}

    nomi_map = _helpers._build_nomi_map()
    # Completamenti a libretto per iscrizione: chi li ha non si elimina, si annulla.
    record_per_iscrizione = {
        r.enrollment_id: r for r in TrainingEmployeeRecord.objects.filter(enrollment__in=iscrizioni)
    }
    for i in iscrizioni:
        i.nome_dip = nomi_map.get(i.legacy_anagrafica_id, f"#{i.legacy_anagrafica_id}")
        i.record_attivo = record_per_iscrizione.get(i.pk)
        # Griglia presenze per riga (lista parallela alle lezioni)
        presenze_griglia = [
            presenze_map.get((i.legacy_anagrafica_id, lz.pk), "")
            for lz in lezioni
        ]
        i.lezioni_presenze = list(zip(lezioni, presenze_griglia))
        # Turni assegnati: set di lezione_id (vuoto = tutte). Lista parallela per la UI.
        i.turni_ids = turni_map.get(i.pk, set())
        i.turni_espliciti = bool(i.turni_ids)
        i.turni_griglia = [(lz, lz.pk in i.turni_ids) for lz in lezioni]
        i.turni_label = (
            ", ".join(f"L{lz.numero}" for lz in lezioni if lz.pk in i.turni_ids)
            if i.turni_espliciti else "Tutte"
        )

    # Lista dipendenti attivi per il form di iscrizione manuale
    dipendenti_attivi = _helpers._build_nomi_map()

    # Candidati all'iscrizione: motore di idoneità (pertinenza + scadenze + prerequisiti).
    # Restituisce idonei (proponibili, pre-spuntati i rinnovi) e non idonei (prerequisiti
    # mancanti, in coda e disabilitati). Solo per editor.
    candidati = {"idonei": [], "non_idonei": [], "pool_filtrato": False, "n_preselect": 0}
    if is_editor:
        from ..services.training_eligibility import candidati_corso
        candidati = candidati_corso(sessione.corso, sessione=sessione)
    candidati_rinnovo = candidati["idonei"] + candidati["non_idonei"]

    from ..services.formazione_integrita import motivo_blocco_edizione
    annullati = list(TrainingEmployeeRecord.tutti.filter(sessione=sessione, annullato_il__isnull=False)
                     .order_by("-annullato_il"))
    for r in annullati:
        r.nome_dip = nomi_map.get(r.legacy_anagrafica_id, f"#{r.legacy_anagrafica_id}")

    return render(request, "anagrafica/pages/formazione_iscritti.html", {
        "sessione":          sessione,
        "iscrizioni":        iscrizioni,
        "lezioni":           lezioni,
        "is_editor":         is_editor,
        # Edizione chiusa: niente nuovi iscritti, turni o cancellazioni; con
        # l'approvazione anche gli esiti restano fermi.
        "puo_iscrivere":     is_editor and not sessione.is_chiusa,
        "puo_esiti":         is_editor and not sessione.is_approvata,
        "motivo_blocco":     motivo_blocco_edizione(sessione),
        "annullati":         annullati,
        "dipendenti_attivi": sorted(dipendenti_attivi.items(), key=lambda x: x[1]),
        "STATO_CHOICES":     TrainingEnrollment.STATO_CHOICES,
        "candidati":         candidati,
        "candidati_rinnovo": candidati_rinnovo,
        "n_rinnovo_pre":     candidati["n_preselect"],
    })


@login_required
@require_POST
def formazione_iscrizione_add(request, sessione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le iscrizioni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)

    try:
        legacy_id = int(request.POST.get("legacy_anagrafica_id") or 0)
    except (TypeError, ValueError):
        legacy_id = 0
    if not legacy_id:
        messages.error(request, "Selezionare un dipendente valido.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)

    # Enforcement *soft* dei prerequisiti: se mancano e non c'è forzatura esplicita,
    # blocca con avviso; con force=1 procede ma traccia la deroga in audit.
    from ..services.training_eligibility import prerequisiti_mancanti
    mancanti = prerequisiti_mancanti(sessione.corso, legacy_id)
    force = request.POST.get("force") == "1"
    if mancanti and not force:
        nome = _helpers._build_nomi_map().get(legacy_id, f"#{legacy_id}")
        messages.error(
            request,
            f'"{nome}" non soddisfa i prerequisiti del corso '
            f'(manca: {", ".join(mancanti)}). Per iscriverlo comunque, conferma la forzatura.',
        )
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if mancanti and force:
        _helpers._audit_safe(request, "formazione_iscrizione_forzata", "formazione", {
            "sessione_id": sessione.pk, "legacy_id": legacy_id, "prerequisiti_mancanti": mancanti,
        })

    # Collega l'eventuale assegnazione a livello corso (TrainingAssignment).
    assignment = TrainingAssignment.objects.filter(
        corso=sessione.corso, legacy_anagrafica_id=legacy_id
    ).first()

    _, created = TrainingEnrollment.objects.get_or_create(
        sessione=sessione,
        legacy_anagrafica_id=legacy_id,
        defaults={
            "stato": "ISCRITTO",
            "iscritto_da": request.user,
            "assignment": assignment,
            "note": (request.POST.get("note") or "").strip(),
        },
    )
    if created:
        nomi = _helpers._build_nomi_map()
        nome = nomi.get(legacy_id, f"#{legacy_id}")
        messages.success(request, f'Dipendente "{nome}" iscritto alla sessione.')
    else:
        messages.warning(request, "Dipendente già iscritto a questa sessione.")
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_iscrizione_edit(request, sessione_id: int, iscrizione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le iscrizioni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="approvata")) is not None:
        return blocco
    iscrizione = get_object_or_404(TrainingEnrollment, pk=iscrizione_id, sessione_id=sessione_id)
    stato_precedente = iscrizione.stato

    form = TrainingEnrollmentEditForm(request.POST, instance=iscrizione)
    if (form.is_valid() and stato_precedente == "COMPLETATO"
            and form.cleaned_data.get("stato") != "COMPLETATO"
            and TrainingEmployeeRecord.objects.filter(enrollment_id=iscrizione.pk).exists()):
        messages.error(
            request,
            "Il completamento è già a libretto: per cambiare l'esito annulla prima il "
            "completamento indicando il motivo.",
        )
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if form.is_valid():
        iscrizione = form.save()
        # Se diventa COMPLETATO per la prima volta: gating conformità (Accordo SR 2025).
        if iscrizione.stato == "COMPLETATO" and stato_precedente != "COMPLETATO":
            force = request.POST.get("force") == "1"
            motivi = _motivi_blocco_completamento(iscrizione)
            if motivi and not force:
                # Conserva i dati inseriti ma non avanza lo stato.
                iscrizione.stato = stato_precedente
                iscrizione.save(update_fields=["stato"])
                messages.error(
                    request,
                    "Completamento bloccato: " + "; ".join(motivi)
                    + ". Conferma la forzatura per registrarlo comunque.",
                )
                return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
            if motivi and force:
                _helpers._audit_safe(request, "formazione_completamento_forzato", "formazione", {
                    "sessione_id": sessione_id, "iscrizione_id": iscrizione.pk, "motivi": motivi,
                })
            _crea_employee_record(iscrizione, request.user)
        messages.success(request, "Iscrizione aggiornata.")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_iscrizione_attestato_upload(request, sessione_id: int, iscrizione_id: int):
    """Carica l'attestato dell'organizzatore esterno e **chiude il corso** per l'iscritto:
    porta l'iscrizione a COMPLETATO, crea il record storico, archivia il file nel box
    documenti (CERTIFICATO_FORMAZIONE) e registra il TrainingCertificate. Rispetta il
    gating conformità (verifica/frequenza), forzabile con force=1 (tracciato)."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le iscrizioni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="approvata")) is not None:
        return blocco
    iscrizione = get_object_or_404(
        TrainingEnrollment.objects.select_related("sessione", "sessione__corso"),
        pk=iscrizione_id, sessione_id=sessione_id,
    )

    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Seleziona l'attestato da caricare.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    # SEC: tipo verificato dal contenuto, senza ripiego sul Content-Type del browser.
    from ..services.upload_documenti import UploadMimeValidationError, valida_documento
    try:
        mime = valida_documento(uploaded, _helpers._ALLOWED_DOC_EXTENSIONS)
    except UploadMimeValidationError as exc:
        messages.error(request, f"File rifiutato: {exc} Ammessi: PDF, immagini (JPG, PNG, WEBP), DOC/DOCX, XLS/XLSX.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)

    force = request.POST.get("force") == "1"
    # Gating conformità (se non già completata)
    if iscrizione.stato != "COMPLETATO":
        motivi = _motivi_blocco_completamento(iscrizione)
        if motivi and not force:
            messages.error(
                request,
                "Chiusura bloccata: " + "; ".join(motivi)
                + ". Conferma la forzatura per chiudere comunque.",
            )
            return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
        if motivi and force:
            _helpers._audit_safe(request, "formazione_completamento_forzato", "formazione", {
                "sessione_id": sessione_id, "iscrizione_id": iscrizione.pk,
                "motivi": motivi, "via": "attestato_caricato",
            })
        from django.utils import timezone as _tz
        if not iscrizione.data_completamento:
            iscrizione.data_completamento = _tz.localdate()
        if iscrizione.idoneo is None:
            iscrizione.idoneo = True
        iscrizione.stato = "COMPLETATO"
        iscrizione.save(update_fields=["stato", "idoneo", "data_completamento"])

    record = _crea_employee_record(iscrizione, request.user)
    if record is None:
        record = getattr(iscrizione, "record_completamento", None)
    if record is None:
        messages.error(request, "Impossibile registrare il completamento.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)

    rilasciato_da = (request.POST.get("rilasciato_da") or "").strip()[:200]
    numero = (request.POST.get("numero_attestato") or "").strip()[:100]
    data_rilascio = None
    raw = (request.POST.get("data_rilascio") or "").strip()
    if raw:
        try:
            data_rilascio = date.fromisoformat(raw)
        except ValueError:
            data_rilascio = None
    if data_rilascio is None:
        data_rilascio = record.data_completamento

    try:
        from ..services.attestato_pdf import archivia_attestato, archivia_attestato_caricato
        # Copia interna NOVICROM: assicurane la presenza, così affianca l'esterno
        # (storico completo nel box). Fail-safe: non deve bloccare l'archiviazione esterna.
        try:
            archivia_attestato(record, user=request.user)
        except Exception:
            logger.exception("Copia interna attestato non generata (record %s)", record.pk)
        # Attestato esterno = principale (slot dedicato), collegato al certificato.
        descr = "Attestato organizzatore esterno (principale)" + (f" — {rilasciato_da}" if rilasciato_da else "")
        doc = archivia_attestato_caricato(
            record, uploaded, user=request.user, force=True, mime=mime, descrizione=descr,
        )
        TrainingCertificate.objects.update_or_create(
            record=record,
            defaults={
                "legacy_anagrafica_id": record.legacy_anagrafica_id,
                "numero_attestato": numero,
                "data_rilascio": data_rilascio,
                "rilasciato_da": rilasciato_da,
                "file_attestato": doc,
                "created_by": request.user,
            },
        )
        _helpers._audit_safe(request, "formazione_attestato_caricato", "formazione", {
            "sessione_id": sessione_id, "iscrizione_id": iscrizione.pk,
            "record_id": record.pk, "documento_id": doc.pk,
        })
        messages.success(request, "Attestato caricato e corso chiuso: completamento registrato e archiviato.")
    except Exception:
        logger.exception("Upload attestato organizzatore fallito (iscrizione %s)", iscrizione.pk)
        messages.error(request, "Errore durante l'archiviazione dell'attestato.")
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_iscrizione_delete(request, sessione_id: int, iscrizione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le iscrizioni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="chiusa")) is not None:
        return blocco
    iscrizione = get_object_or_404(TrainingEnrollment, pk=iscrizione_id, sessione_id=sessione_id)
    if TrainingEmployeeRecord.objects.filter(enrollment=iscrizione).exists():
        messages.error(
            request,
            "L'iscritto ha già il completamento a libretto: l'iscrizione non si elimina. "
            "Se il completamento è sbagliato annullalo indicando il motivo; se la persona non "
            "ha partecipato usa lo stato «Ritirato».",
        )
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    n_presenze = TrainingLessonAttendance.objects.filter(
        lezione__sessione_id=sessione_id, legacy_anagrafica_id=iscrizione.legacy_anagrafica_id,
    ).count()
    dettaglio = {
        "sessione_id": sessione_id, "iscrizione_id": iscrizione.pk,
        "legacy_anagrafica_id": iscrizione.legacy_anagrafica_id, "stato": iscrizione.stato,
        "presenze_registrate": n_presenze,
    }
    iscrizione.delete()
    _audit_formazione(request, "iscrizione_eliminata", dettaglio)
    messages.success(request, "Iscrizione rimossa.")
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_iscrizione_bulk(request, sessione_id: int):
    """Iscrive in blocco i dipendenti selezionati (candidati al rinnovo del
    corso) a questa edizione. Idempotente: chi è già iscritto viene saltato."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le iscrizioni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="chiusa")) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)

    ids: list[int] = []
    seen: set[int] = set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)

    # Collega alle assegnazioni a livello corso (TrainingAssignment), se presenti.
    assegnazioni = {
        a.legacy_anagrafica_id: a
        for a in TrainingAssignment.objects.filter(
            corso=sessione.corso, legacy_anagrafica_id__in=ids
        )
    }
    n_new = 0
    for lid in ids:
        _, created = TrainingEnrollment.objects.get_or_create(
            sessione=sessione, legacy_anagrafica_id=lid,
            defaults={
                "stato": "ISCRITTO",
                "iscritto_da": request.user,
                "assignment": assegnazioni.get(lid),
            },
        )
        if created:
            n_new += 1
    if n_new:
        messages.success(request, f"{n_new} dipendenti iscritti all'edizione di rinnovo.")
    else:
        messages.info(request, "I dipendenti selezionati erano già iscritti.")
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
@require_POST
def formazione_iscrizione_turni(request, sessione_id: int, iscrizione_id: int):
    """Imposta i turni (lezioni) di un'iscrizione = le lezioni selezionate.

    Nessuna selezione ⇒ l'iscritto torna "su tutte le lezioni" (default storico).
    Vedi :mod:`services.training_turni`."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire i turni.")
        return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "iscritti", livello="chiusa")) is not None:
        return blocco
    iscrizione = get_object_or_404(
        TrainingEnrollment, pk=iscrizione_id, sessione_id=sessione_id
    )
    lezione_ids: list[int] = []
    for raw in request.POST.getlist("lezioni_turno"):
        s = str(raw).strip()
        if s.isdigit():
            lezione_ids.append(int(s))

    from ..services.training_turni import set_turni
    set_turni(iscrizione, lezione_ids, user=request.user)
    if lezione_ids:
        messages.success(request, "Turni dell'iscritto aggiornati.")
    else:
        messages.success(request, "Turni rimossi: l'iscritto frequenta tutte le lezioni.")
    return redirect("anagrafica:formazione_sessione_iscritti", sessione_id=sessione_id)


@login_required
def formazione_lezione_presenze(request, sessione_id: int, lezione_id: int):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)

    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    lezione  = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)
    # Edizione chiusa: le presenze sono l'evidenza degli attestati, si leggono soltanto.
    from ..services.formazione_integrita import motivo_blocco_edizione
    motivo_blocco = motivo_blocco_edizione(sessione)
    is_editor = is_editor and not motivo_blocco
    from django.utils import timezone as _tz
    giornata_futura = bool(lezione.data and lezione.data > _tz.localdate())

    # Turni: mostra solo gli iscritti *attesi* a questa lezione (chi non ha turni
    # espliciti vale per tutte le lezioni — fallback storico).
    from ..services.training_turni import iscritti_attesi_lezione
    tutte_iscrizioni = list(
        TrainingEnrollment.objects.filter(sessione=sessione)
        .order_by("legacy_anagrafica_id")
    )
    iscrizioni = iscritti_attesi_lezione(sessione, lezione, tutte_iscrizioni)
    turno_filtrato = len(iscrizioni) != len(tutte_iscrizioni)
    ids = [i.legacy_anagrafica_id for i in iscrizioni]
    presenze_map = {
        p.legacy_anagrafica_id: p
        for p in TrainingLessonAttendance.objects.filter(
            lezione=lezione, legacy_anagrafica_id__in=ids
        )
    }
    nomi_map = _helpers._build_nomi_map()
    righe = []
    for i in iscrizioni:
        righe.append({
            "enrollment": i,
            "nome": nomi_map.get(i.legacy_anagrafica_id, f"#{i.legacy_anagrafica_id}"),
            "presenza": presenze_map.get(i.legacy_anagrafica_id),
        })

    n_presenti = sum(1 for r in righe if r["presenza"] is not None)

    allegati_lezione = list(lezione.allegati.order_by("-created_at"))

    return render(request, "anagrafica/pages/formazione_presenze.html", {
        "motivo_blocco": motivo_blocco,
        "giornata_futura": giornata_futura,
        "sessione":   sessione,
        "lezione":    lezione,
        "righe":      righe,
        "is_editor":  is_editor,
        "n_presenti": n_presenti,
        "turno_filtrato": turno_filtrato,
        "n_totale_iscritti": len(tutte_iscrizioni),
        "STATO_PRESENZA_CHOICES": TrainingLessonAttendance.STATO_PRESENZA_CHOICES,
        "allegati_lezione": allegati_lezione,
        "ATTACH_TIPI": TrainingAttachment.Tipo.choices,
    })


@login_required
def formazione_lezione_registro(request, sessione_id: int, lezione_id: int):
    """Foglio firme (registro presenze) di una lezione, in **PDF**.

    Veste UNIFICATA del portale (reportlab via `core/pdf`), identica ai fogli firme di
    corso e del fascicolo: intestazione corso/sessione/lezione, tabella nominativi +
    colonne firma ingresso/uscita, righe vuote di scorta e firma docente. Turno-aware
    (elenca gli iscritti attesi alla lezione). Tracciato in `TrainingExportLog`.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    sessione = get_object_or_404(TrainingSession.objects.select_related("corso", "corso__piano"), pk=sessione_id)
    lezione  = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)

    # Foglio firme PDF nella veste UNICA del portale (la stessa dei fogli firme di
    # corso e del fascicolo): riusa il builder reportlab condiviso, turno-aware
    # (elenca gli iscritti attesi a questa lezione, fallback tutti).
    from ..services.attestato_pdf import build_registro_lezione_pdf_bytes
    pdf = build_registro_lezione_pdf_bytes(lezione)
    try:
        TrainingExportLog.objects.create(
            tipo="REPORT_FIRMA",
            filtri_json={
                "sessione_id": sessione.pk,
                "lezione_id": lezione.pk,
                "formato": "foglio_firme_pdf",
            },
            righe_esportate=sessione.iscrizioni.count(),
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog per foglio firme lezione %s", lezione_id)

    fname = f"Foglio_firme_{sessione.codice_sessione}_L{lezione.numero}.pdf".replace("/", "-").replace(" ", "_")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{fname}"'
    return resp


@login_required
def formazione_lezione_registro_qr(request, sessione_id: int, lezione_id: int):
    """Emette il **foglio firme tracciato**: elenco congelato, QR con il token e
    marcatori d'angolo.

    Differenza dal foglio classico: qui la stampa è un fatto registrato. L'elenco
    resta quello del momento — se domani si aggiunge un iscritto, la riga 7 della
    scansione continua a essere la persona di allora — e la geometria delle celle
    viene salvata, così rileggere la scansione sarà una misura su rettangoli noti
    e non un tentativo di interpretare la scrittura.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per emettere fogli firme.")
        return redirect("anagrafica:formazione_lezione_presenze",
                        sessione_id=sessione_id, lezione_id=lezione_id)

    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    lezione  = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)

    from ..services.foglio_firme import emetti_foglio_firme
    foglio, pdf = emetti_foglio_firme(lezione, user=request.user)

    try:
        TrainingExportLog.objects.create(
            tipo="REPORT_FIRMA",
            filtri_json={
                "sessione_id": sessione.pk, "lezione_id": lezione.pk,
                "formato": "foglio_firme_qr", "token": foglio.token,
            },
            righe_esportate=foglio.n_righe,
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog per foglio firme QR %s", lezione_id)

    fname = f"Foglio_firme_{foglio.token}.pdf"
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{fname}"'
    return resp


@login_required
@require_POST
def formazione_presenza_set(request, sessione_id: int, lezione_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le presenze.")
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "presenze", livello="chiusa", lezione_id=lezione_id)) is not None:
        return blocco
    lezione = get_object_or_404(TrainingLesson, pk=lezione_id, sessione_id=sessione_id)

    try:
        legacy_id = int(request.POST.get("legacy_anagrafica_id") or 0)
    except (TypeError, ValueError):
        legacy_id = 0
    if not legacy_id:
        messages.error(request, "ID dipendente non valido.")
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)
    if not TrainingEnrollment.objects.filter(sessione_id=sessione_id, legacy_anagrafica_id=legacy_id).exists():
        messages.error(request, "La persona non è iscritta a questa edizione: iscrivila prima di registrare la presenza.")
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)
    from django.utils import timezone as _tz
    if lezione.data and lezione.data > _tz.localdate():
        messages.error(request, f"La giornata del {lezione.data:%d/%m/%Y} non si è ancora svolta: "
                                "la presenza si registra dopo.")
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)

    presenza, creata = TrainingLessonAttendance.objects.get_or_create(
        lezione=lezione,
        legacy_anagrafica_id=legacy_id,
        defaults={"registrato_da": request.user},
    )
    # Stato precedente: serve per capire se questa è una prima registrazione
    # oppure il ritocco di una presenza già firmata (che va tracciato).
    stato_prima = presenza.stato_presenza
    firma_prima = presenza.signature_status
    form = TrainingLessonAttendanceForm(request.POST, instance=presenza)
    if form.is_valid():
        p = form.save(commit=False)
        p.registrato_da = request.user
        p.save()

        if not creata and (p.stato_presenza != stato_prima or firma_prima == "FIRMATO"):
            _audit_formazione(request, "presenza_modificata", {
                "sessione_id": sessione_id, "lezione_id": lezione_id,
                "legacy_anagrafica_id": legacy_id,
                "stato_precedente": stato_prima, "stato_nuovo": p.stato_presenza,
                "firma_precedente": firma_prima, "firma_attuale": p.signature_status,
            })

        # Aggiorna ore_frequentate e percentuale nell'iscrizione
        try:
            enrollment = TrainingEnrollment.objects.get(
                sessione_id=sessione_id, legacy_anagrafica_id=legacy_id
            )
            _ricalcola_presenza_enrollment(enrollment)
        except TrainingEnrollment.DoesNotExist:
            pass

        messages.success(request, "Presenza registrata.")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)


@login_required
@require_POST
def formazione_registro_scansione(request, sessione_id: int, lezione_id: int):
    """Legge la scansione di un foglio con QR e **propone** le presenze.

    Non scrive nulla: mostra una pagina di conferma le cui spunte finiscono
    nell'autocompilazione già esistente. La presenza a un corso è un atto con
    valore legale: la decide una persona, non una misura di pixel.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le presenze.")
        return redirect("anagrafica:formazione_lezione_presenze",
                        sessione_id=sessione_id, lezione_id=lezione_id)

    sessione = get_object_or_404(TrainingSession.objects.select_related("corso"), pk=sessione_id)
    lezione = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)
    indietro = redirect("anagrafica:formazione_lezione_presenze",
                        sessione_id=sessione_id, lezione_id=lezione_id)

    caricato = request.FILES.get("scansione")
    if not caricato:
        messages.error(request, "Serve il file della scansione.")
        return indietro

    from ..services.archivio_scansioni import archivia_scansione, registra_lettura

    contenuto = caricato.read()

    # Si archivia PRIMA di provare a leggere. Se la lettura fallisce, il file
    # deve restare da qualche parte dove qualcuno possa andarlo a guardare:
    # senza, dell'errore resta solo la frase a schermo, che non è una diagnosi.
    percorso, dimensione = archivia_scansione(contenuto, caricato.name)
    comune = {
        "request": request, "lezione": lezione, "nome_file": caricato.name,
        "percorso": percorso, "dimensione": dimensione,
    }

    # Il token si decodifica dal QR stampato sul foglio; resta digitabile perché
    # un QR strappato, piegato o macchiato capita, e la strada a mano costa zero.
    token_digitato = (request.POST.get("token") or "").strip().upper()
    token_letto = ""
    if not token_digitato:
        from core.qr import leggi_codici

        for codice in leggi_codici(contenuto, caricato.name):
            candidato = codice.strip().upper()[:16]
            if TrainingSignatureSheet.objects.filter(token=candidato).exists():
                token_letto = candidato
                break

    token = token_digitato or token_letto
    if not token:
        motivo = (
            "Non ho trovato nessun QR leggibile nella scansione e non è stato indicato "
            "un codice. Digita il codice stampato sotto il QR e riprova."
        )
        registra_lettura(**comune, esito="RIFIUTATO", messaggio=motivo)
        messages.error(request, motivo + " Il file è comunque archiviato nel registro letture.")
        return indietro

    # Il foglio deve essere di QUESTA giornata: un token valido ma di un'altra
    # lezione porterebbe presenze sulla giornata sbagliata.
    foglio = TrainingSignatureSheet.objects.filter(token=token, lezione=lezione).first()
    if foglio is None:
        motivo = (
            f"Nessun foglio con codice «{token}» risulta emesso per questa giornata. "
            "Controlla il codice stampato sotto il QR."
        )
        registra_lettura(**comune, token_digitato=token_digitato, token_letto=token_letto,
                         esito="RIFIUTATO", messaggio=motivo)
        messages.error(request, motivo + " Il file è comunque archiviato nel registro letture.")
        return indietro

    comune["foglio"] = foglio
    from ..services.lettura_foglio_firme import ErroreLettura, analizza_scansione

    try:
        esito = analizza_scansione(foglio, contenuto, caricato.name)
    except ErroreLettura as exc:
        registra_lettura(**comune, token_digitato=token_digitato, token_letto=token_letto,
                         esito="ERRORE", messaggio=str(exc))
        messages.error(request, f"{exc} Il file è archiviato nel registro letture.")
        return indietro
    except Exception:
        logger.exception("Lettura scansione foglio firme fallita (foglio %s)", foglio.pk)
        motivo = "Non sono riuscito a leggere la scansione. Riprova con un file diverso."
        registra_lettura(**comune, token_digitato=token_digitato, token_letto=token_letto,
                         esito="ERRORE", messaggio=motivo)
        messages.error(request, motivo + " Il file è archiviato nel registro letture.")
        return indietro

    registra_lettura(**comune, token_digitato=token_digitato, token_letto=token_letto,
                     esito="OK", esito_lettura=esito)

    _audit_formazione(request, "scansione_registro_letta", {
        "sessione_id": sessione_id, "lezione_id": lezione_id,
        "token": foglio.token, "righe": len(esito["righe"]),
        "firmati": esito["n_firmati"], "dubbie": esito["n_dubbie"],
        "token_da_qr": bool(token_letto),
    })

    return render(request, "anagrafica/pages/formazione_scansione_esito.html", {
        "sessione": sessione,
        "lezione": lezione,
        "foglio": foglio,
        "esito": esito,
        "nome_file": caricato.name,
        "token_da_qr": token_letto,
    })


@login_required
def formazione_scansioni_log(request):
    """Registro delle scansioni caricate: cosa è arrivato e dov'è finito.

    Esiste per il caso in cui la lettura fallisce. Il messaggio d'errore a
    schermo dice *che* è andata male, non *perché*: qui c'è il file vero, con
    il percorso in cui è stato archiviato, da riaprire e guardare.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire la formazione.")
        return redirect("anagrafica:formazione_home")

    righe = (
        TrainingScanLog.objects
        .select_related("lezione", "lezione__sessione", "lezione__sessione__corso",
                        "foglio", "creato_da")
    )

    esito = (request.GET.get("esito") or "").strip().upper()
    if esito in {"OK", "ERRORE", "RIFIUTATO"}:
        righe = righe.filter(esito=esito)

    cerca = (request.GET.get("q") or "").strip()
    if cerca:
        righe = righe.filter(
            Q(nome_file__icontains=cerca)
            | Q(token_digitato__icontains=cerca)
            | Q(token_letto__icontains=cerca)
            | Q(lezione__sessione__corso__titolo__icontains=cerca)
        )

    conteggi = {
        "tutte": TrainingScanLog.objects.count(),
        "ok": TrainingScanLog.objects.filter(esito="OK").count(),
        "errore": TrainingScanLog.objects.filter(esito="ERRORE").count(),
        "rifiutato": TrainingScanLog.objects.filter(esito="RIFIUTATO").count(),
    }

    from core.qr import disponibile as qr_disponibile

    return render(request, "anagrafica/pages/formazione_scansioni_log.html", {
        "righe": righe[:300],
        "esito": esito,
        "cerca": cerca,
        "conteggi": conteggi,
        "lettore_qr_attivo": qr_disponibile(),
    })


@login_required
def formazione_scansioni_impostazioni(request):
    """Cartella di acquisizione e regole di conferma (singleton).

    Include il pulsante «Prova adesso», che vale più di ogni messaggio di
    aiuto: una share di rete o si raggiunge o non si raggiunge, e chi la
    configura deve poterlo sapere subito invece che dedurlo da una cartella
    che resta vuota.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare le impostazioni della formazione.")
        return redirect("anagrafica:formazione_dashboard")

    from ..forms import TrainingScanIntakeConfigForm

    config = TrainingScanIntakeConfig.load()
    form = TrainingScanIntakeConfigForm(instance=config)

    if request.method == "POST":
        azione = (request.POST.get("azione") or "salva").strip()

        if azione == "prova":
            from ..services.intake_scansioni import elabora_cartella

            esito = elabora_cartella(config)
            _audit_formazione(request, "intake_scansioni_prova", {
                "cartella": config.cartella, "riepilogo": esito.get("riepilogo", ""),
            })
            messages.info(request, f"Passaggio eseguito: {esito.get('riepilogo', '')}")
            return redirect("anagrafica:formazione_scansioni_impostazioni")

        form = TrainingScanIntakeConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            _audit_formazione(request, "intake_scansioni_config", {
                "attiva": config.attiva, "cartella": config.cartella,
                "conferma_automatica": config.conferma_automatica,
            })
            messages.success(request, "Impostazioni dell'acquisizione salvate.")
            return redirect("anagrafica:formazione_scansioni_impostazioni")
        messages.error(request, "Controlla i campi segnalati.")

    # Lo stato della cartella si guarda adesso, non si ricorda: una share può
    # essere sparita dall'ultimo salvataggio.
    import os

    stato_cartella = "non configurata"
    if (config.cartella or "").strip():
        try:
            stato_cartella = "raggiungibile" if os.path.isdir(config.cartella) else "non raggiungibile"
        except OSError:
            stato_cartella = "non raggiungibile"

    # Una lettera di unità *può* essere un disco locale del server, quindi non si
    # rifiuta; ma è più spesso una mappatura dell'utente collegato, che un
    # servizio non vede — e il sintomo sarebbe una cartella eternamente vuota.
    cartella = (config.cartella or "").strip()
    avviso_lettera_unita = len(cartella) > 2 and cartella[1] == ":"

    return render(request, "anagrafica/pages/formazione_scansioni_impostazioni.html", {
        "form": form,
        "config": config,
        "stato_cartella": stato_cartella,
        "avviso_lettera_unita": avviso_lettera_unita,
    })


@login_required
def formazione_scansione_scarica(request, log_id: int):
    """Riscarica il file archiviato di una lettura.

    L'archivio è privato e cifrato a riposo: non si apre da Esplora risorse, si
    passa di qui — dove ci sono permessi e traccia — perché il foglio contiene
    nomi e firme autografe.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire la formazione.")
        return redirect("anagrafica:formazione_home")

    riga = get_object_or_404(TrainingScanLog, pk=log_id)
    from ..services.archivio_scansioni import apri_archiviata

    f = apri_archiviata(riga.percorso)
    if f is None:
        messages.error(request, "Il file archiviato non è più disponibile.")
        return redirect("anagrafica:formazione_scansioni_log")

    _audit_formazione(request, "scansione_archiviata_scaricata", {
        "log_id": riga.pk, "percorso": riga.percorso, "nome_file": riga.nome_file,
    })

    from django.http import FileResponse

    return FileResponse(f, as_attachment=True, filename=riga.nome_file or "scansione")


@login_required
@require_POST
def formazione_registro_autocompila(request, sessione_id: int, lezione_id: int):
    """Autocompila le presenze di una lezione dal **registro firme** firmato.

    Per ogni iscritto *atteso* alla lezione (rispetta i turni) imposta firma
    ingresso/uscita in base ai campi spuntati nel modulo (= "a seconda dei campi
    firmati"), lo stato presenza (PRESENTE se entrambe, PARZIALE se una sola),
    ``signature_status=FIRMATO`` / ``signature_method=UPLOAD`` / ``signed_at``, e
    ricalcola ore/percentuale dell'iscrizione. Gli iscritti senza alcuna firma
    spuntata non vengono toccati.
    """
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per gestire le presenze.")
        return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)
    if (blocco := _redirect_se_edizione_chiusa(request, sessione_id, "presenze", livello="chiusa", lezione_id=lezione_id)) is not None:
        return blocco
    sessione = get_object_or_404(TrainingSession, pk=sessione_id)
    lezione = get_object_or_404(TrainingLesson, pk=lezione_id, sessione=sessione)

    from ..services.formazione_presenze import applica_firme_lezione
    from ..services.training_turni import iscritti_attesi_lezione

    # La scrittura vera sta nel servizio, condiviso con l'acquisizione da
    # cartella: due strade di scrittura sullo stesso fatto prima o poi
    # divergono, e in audit una delle due sarebbe sbagliata.
    firme = {
        e.legacy_anagrafica_id: (
            request.POST.get(f"ingresso_{e.legacy_anagrafica_id}") == "1",
            request.POST.get(f"uscita_{e.legacy_anagrafica_id}") == "1",
        )
        for e in iscritti_attesi_lezione(sessione, lezione)
    }
    n = len(applica_firme_lezione(lezione, firme, utente=request.user))

    if n:
        _helpers._audit_safe(request, "formazione_registro_autocompila", "formazione", {
            "sessione_id": sessione_id, "lezione_id": lezione_id, "iscritti": n,
        })
        messages.success(request, f"Presenze autocompilate dal registro per {n} iscritti.")
    else:
        messages.info(request, "Nessuna firma selezionata: nessuna presenza modificata.")
    return redirect("anagrafica:formazione_lezione_presenze", sessione_id=sessione_id, lezione_id=lezione_id)


@login_required
def formazione_sessione_fascicolo(request, sessione_id: int):
    """Fascicolo formativo dell'edizione in PDF (progettazione + programma + partecipanti
    ed esiti + relazione): documento unico per la tracciabilità Accordo SR 2025."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")
    sessione = get_object_or_404(
        TrainingSession.objects.select_related(
            "corso", "corso__piano", "corso__ente_formativo", "docente", "docente_ente",
        ),
        pk=sessione_id,
    )
    from ..services.attestato_pdf import build_fascicolo_sessione_pdf_bytes
    pdf = build_fascicolo_sessione_pdf_bytes(sessione)
    try:
        TrainingExportLog.objects.create(
            tipo="REPORT_FIRMA",
            filtri_json={"sessione_id": sessione.pk, "formato": "fascicolo_edizione"},
            righe_esportate=sessione.iscrizioni.count(),
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("Errore TrainingExportLog fascicolo sessione %s", sessione_id)
    fname = f"Fascicolo_{sessione.codice_sessione}.pdf".replace("/", "-").replace(" ", "_")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{fname}"'
    return resp


@login_required
def formazione_scadenzario(request):
    """Scadenzario formazione: corsi scaduti, in scadenza e mai frequentati."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    filtro_stato = request.GET.get("stato", "").strip()
    filtro_corso = request.GET.get("corso", "").strip()
    filtro_q     = request.GET.get("q", "").strip()

    qs = (
        TrainingDeadline.objects
        .select_related("corso", "corso__piano")
        .order_by("stato_scadenza", "data_scadenza", "legacy_anagrafica_id")
    )

    if filtro_stato:
        qs = qs.filter(stato_scadenza=filtro_stato)
    else:
        qs = qs.filter(
            stato_scadenza__in=["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO"]
        )

    if filtro_corso:
        try:
            qs = qs.filter(corso_id=int(filtro_corso))
        except (ValueError, TypeError):
            pass

    nomi_map = _helpers._build_nomi_map()

    if filtro_q:
        q_lower = filtro_q.lower()
        matched_ids = [lid for lid, nome in nomi_map.items() if q_lower in nome.lower()]
        qs = qs.filter(legacy_anagrafica_id__in=matched_ids)

    scadenze = list(qs)
    for s in scadenze:
        s.nome_dip = nomi_map.get(s.legacy_anagrafica_id, f"#{s.legacy_anagrafica_id}")

    # KPI globali (su tutti, non filtrati)
    all_qs = TrainingDeadline.objects
    n_scaduti  = all_qs.filter(stato_scadenza="SCADUTO").count()
    n_30gg     = all_qs.filter(stato_scadenza="IN_SCADENZA_30").count()
    n_90gg     = all_qs.filter(stato_scadenza="IN_SCADENZA_90").count()
    n_mai      = all_qs.filter(stato_scadenza="MAI_FREQUENTATO", is_required=True).count()

    is_cache_empty = not all_qs.exists()

    paginator = Paginator(scadenze, 50)
    page_obj  = paginator.get_page(request.GET.get("page"))

    corsi_list = TrainingCourse.objects.filter(is_active=True).order_by("codice")

    return render(request, "anagrafica/pages/formazione_scadenzario.html", {
        "page_obj":      page_obj,
        "filtro_stato":  filtro_stato,
        "filtro_corso":  filtro_corso,
        "filtro_q":      filtro_q,
        "corsi_list":    corsi_list,
        "n_scaduti":     n_scaduti,
        "n_30gg":        n_30gg,
        "n_90gg":        n_90gg,
        "n_mai":         n_mai,
        "is_cache_empty": is_cache_empty,
        "totale":        len(scadenze),
        "STATO_SCADENZA_CHOICES": TrainingDeadline.STATO_SCADENZA_CHOICES,
        "is_editor":     _helpers._can_edit_formazione(request),
    })


@login_required
def formazione_copertura(request):
    """Report «copertura / gap formativo»: per i corsi *obbligatori* (bersaglio di una
    regola di obbligo attiva) elenca i dipendenti **non in regola** (corso scaduto, in
    scadenza o mai frequentato), con reparto e mansione. Riusa il motore di idoneità
    (`candidati_corso`, che restituisce proprio i candidati = chi non è già a posto).
    Filtri GET: reparto, corso, stato."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    from ..services.training_eligibility import righe_gap_formativo

    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtro_corso   = (request.GET.get("corso") or "").strip()
    filtro_stato   = (request.GET.get("stato") or "").strip()

    corsi_all, reparti, righe = righe_gap_formativo(
        filtro_reparto=filtro_reparto, filtro_corso=filtro_corso, filtro_stato=filtro_stato,
    )

    paginator = Paginator(righe, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/formazione_copertura.html", {
        "page_obj": page_obj,
        "corsi": corsi_all,
        "reparti": reparti,
        "n_dip": len({r["legacy_id"] for r in righe}),
        "n_gap": len(righe),
        "n_scaduti": sum(1 for r in righe if r["stato"] == "SCADUTO"),
        "n_mai": sum(1 for r in righe if r["stato"] == "MAI_FREQUENTATO"),
        "filtro_reparto": filtro_reparto,
        "filtro_corso": filtro_corso,
        "filtro_stato": filtro_stato,
        "is_editor": _helpers._can_edit_formazione(request),
    })


# ─────────────────────────────────────────────────────────────────────────────
# CCNL — monte ore facoltativo del diritto soggettivo alla formazione
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def formazione_ccnl_dashboard(request):
    """Monte ore CCNL per dipendente: ore facoltative (verso le 24h/3 anni,
    «a riempire») e ore obbligatorie/sicurezza nello stesso periodo, informative
    («a diminuire» quando ci sono corsi obbligatori scaduti — vedi scadenzario
    per il dettaglio). Finestra scorrevole degli ultimi 3 anni da oggi, o da
    `?al=` per un istantanea passata."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    from ..services.formazione_ccnl import MONTE_ORE_TARGET, righe_dipendenti

    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtro_stato   = (request.GET.get("stato") or "").strip()
    filtro_q       = (request.GET.get("q") or "").strip()
    al_raw = (request.GET.get("al") or "").strip()
    try:
        al_param = date.fromisoformat(al_raw) if al_raw else None
    except ValueError:
        al_param = None

    dal, al, reparti_set, righe = righe_dipendenti(
        al=al_param, filtro_reparto=filtro_reparto, filtro_stato=filtro_stato, filtro_q=filtro_q,
    )

    paginator = Paginator(righe, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/formazione_ccnl_dashboard.html", {
        "page_obj": page_obj,
        "dal": dal,
        "al": al,
        "al_param": al_raw,
        "monte_ore_target": MONTE_ORE_TARGET,
        "reparti": sorted(reparti_set),
        "filtro_reparto": filtro_reparto,
        "filtro_stato": filtro_stato,
        "filtro_q": filtro_q,
        "totale": len(righe),
        "n_completi": sum(1 for r in righe if r["stato"] == "COMPLETO"),
        "n_da_iniziare": sum(1 for r in righe if r["stato"] == "DA_INIZIARE"),
        "media_ore_facoltative": round(sum(r["ore_facoltative"] for r in righe) / len(righe), 1) if righe else 0,
    })


@login_required
def formazione_ccnl_dipendente_espansione(request, legacy_id: int):
    """Frammento HTMX: i corsi del dipendente nel periodo, dentro la riga espansa."""
    if not _helpers._can_view_formazione(request):
        return HttpResponse(status=403)

    from ..services.formazione_ccnl import corsi_dipendente_nel_periodo

    al_raw = (request.GET.get("al") or "").strip()
    try:
        al_param = date.fromisoformat(al_raw) if al_raw else None
    except ValueError:
        al_param = None

    dati = corsi_dipendente_nel_periodo(legacy_id, al=al_param)
    return render(request, "anagrafica/partials/_formazione_ccnl_espansione.html", {
        "legacy_id": legacy_id,
        **dati,
    })


# ─────────────────────────────────────────────────────────────────────────────
# PLAN — calendario mese per mese di corsi, scadenze, DPI, assenze
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def formazione_plan(request, legacy_id: int | None = None):
    """Vista PLAN: eventi formazione/safety in 3 modalità.

    Senza `legacy_id` mostra il plan aggregato (tutto il personale).
    Con `legacy_id` filtra sui soli eventi del dipendente.

    Modalità (querystring `?view=`):
      - `mese`      (default) — card per mese con elenco eventi
      - `calendario` — griglia mensile classica (settimane × giorni)
      - `matrice`   — X giorni × Y dipendenti (planning resource view).
                      Disponibile solo nella vista globale (non per-dipendente).

    Eventi aggregati:
      - Sessioni formative (`TrainingSession`) per `data_inizio`, con elenco
        dipendenti iscritti (top 5 nomi + count totale).
      - Scadenze formazione (`TrainingDeadline`) per `data_scadenza`.
      - DPI scadenze — TODO PATCH successiva.
      - Assenze programmate — TODO PATCH successiva.

    Range default: mese corrente ± 3 mesi (7 mesi totali). Override via
    querystring `?from=YYYY-MM-DD&to=YYYY-MM-DD`. Per la vista `calendario` si
    può anche specificare `?anno=YYYY&mese=MM` per centrare su un singolo mese.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare la sezione formazione.")
        return redirect("anagrafica:index")

    from datetime import timedelta
    import calendar as _calendar
    from collections import OrderedDict

    today = django_timezone.localdate()
    view_mode = (request.GET.get("view") or "mese").lower()
    if view_mode not in {"mese", "calendario", "matrice"}:
        view_mode = "mese"

    def _parse_iso(s: str) -> date | None:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    # ── Calcolo range a seconda della modalità ──────────────────────────────
    if view_mode == "calendario":
        try:
            cal_anno = int(request.GET.get("anno") or today.year)
            cal_mese = int(request.GET.get("mese") or today.month)
        except (TypeError, ValueError):
            cal_anno, cal_mese = today.year, today.month
        if cal_mese < 1 or cal_mese > 12:
            cal_mese = today.month
        cal_first = date(cal_anno, cal_mese, 1)
        cal_last = (_helpers._add_months(cal_first, 1) - timedelta(days=1))
        range_from, range_to = cal_first, cal_last
    else:
        range_from = _parse_iso(request.GET.get("from") or "") or _helpers._add_months(today.replace(day=1), -3)
        range_to_input = _parse_iso(request.GET.get("to") or "")
        if range_to_input is None:
            plus3 = _helpers._add_months(today.replace(day=1), 4)
            range_to = plus3 - timedelta(days=1)
        else:
            range_to = range_to_input
        if range_to < range_from:
            range_from, range_to = range_to, range_from
        cal_anno, cal_mese = today.year, today.month

    # ── Mappa nomi dipendenti ──────────────────────────────────────────────
    nomi_map = _helpers._build_nomi_map()

    # ── Raccolta eventi ────────────────────────────────────────────────────
    eventi: list[dict] = []

    # 1) Sessioni formative
    qs_sessioni = (
        TrainingSession.objects
        .select_related("corso", "corso__piano", "docente")
        .filter(data_inizio__gte=range_from, data_inizio__lte=range_to)
    )
    if legacy_id is not None:
        sess_ids_dip = list(
            TrainingEnrollment.objects
            .filter(legacy_anagrafica_id=legacy_id,
                    sessione__data_inizio__gte=range_from,
                    sessione__data_inizio__lte=range_to)
            .values_list("sessione_id", flat=True)
        )
        qs_sessioni = qs_sessioni.filter(pk__in=sess_ids_dip)

    # Pre-fetch iscritti per sessione (per mostrare nomi)
    sess_ids = [s.pk for s in qs_sessioni]
    iscritti_per_sess: dict[int, list[int]] = defaultdict(list)
    if sess_ids:
        for sess_id, lid in (
            TrainingEnrollment.objects
            .filter(sessione_id__in=sess_ids)
            .values_list("sessione_id", "legacy_anagrafica_id")
        ):
            iscritti_per_sess[sess_id].append(lid)

    for s in qs_sessioni:
        legacy_ids = iscritti_per_sess.get(s.pk, [])
        nomi_top = [nomi_map.get(lid, f"#{lid}") for lid in legacy_ids[:5]]
        eventi.append({
            "data":   s.data_inizio,
            "data_fine": s.data_fine,
            "tipo":   "CORSO",
            "tipo_label": "Corso",
            "titolo": f"{s.corso.codice} — {s.corso.titolo[:60]}",
            "sub":    f"Sessione {s.codice_sessione} · {s.get_stato_display()}",
            "url":    f"/anagrafica/formazione/sessioni/{s.pk}/",
            "stato":  s.stato,
            "badge":  s.stato.lower(),
            "iscritti_count": len(legacy_ids),
            "iscritti_nomi":  nomi_top,
            "iscritti_extra": max(0, len(legacy_ids) - 5),
            "iscritti_legacy_ids": legacy_ids,
        })

    # 2) Scadenze formazione
    qs_scad = (
        TrainingDeadline.objects
        .select_related("corso", "corso__piano")
        .filter(data_scadenza__gte=range_from, data_scadenza__lte=range_to)
        .exclude(stato_scadenza="UNA_TANTUM")
    )
    if legacy_id is not None:
        qs_scad = qs_scad.filter(legacy_anagrafica_id=legacy_id)

    for d in qs_scad:
        nome_dip = nomi_map.get(d.legacy_anagrafica_id, "") if legacy_id is None else ""
        sub_parts = [d.get_stato_scadenza_display()]
        if nome_dip:
            sub_parts.insert(0, nome_dip)
        eventi.append({
            "data":   d.data_scadenza,
            "data_fine": d.data_scadenza,
            "tipo":   "SCADENZA",
            "tipo_label": "Scadenza",
            "titolo": f"{d.corso.codice} — {d.corso.titolo[:60]}",
            "sub":    " · ".join(sub_parts),
            "url":    f"/anagrafica/formazione/corsi/{d.corso_id}/",
            "stato":  d.stato_scadenza,
            "badge":  d.stato_scadenza.lower(),
            "iscritti_count": 1,
            "iscritti_nomi":  [nome_dip] if nome_dip else [],
            "iscritti_extra": 0,
            "iscritti_legacy_ids": [d.legacy_anagrafica_id],
        })

    # ── 3) Raggruppamento per mese (modalità "mese", per i KPI riepilogo) ──
    mesi: "OrderedDict[tuple[int,int], dict]" = OrderedDict()
    cursor = range_from.replace(day=1)
    end_month = range_to.replace(day=1)
    while cursor <= end_month:
        mesi[(cursor.year, cursor.month)] = {
            "anno": cursor.year, "mese": cursor.month,
            "label_mese": cursor.strftime("%B %Y").capitalize(),
            "is_corrente": (cursor.year, cursor.month) == (today.year, today.month),
            "is_passato":  cursor < today.replace(day=1),
            "is_futuro":   cursor > today.replace(day=1),
            "eventi": [],
        }
        cursor = _helpers._add_months(cursor, 1)
    for ev in eventi:
        key = (ev["data"].year, ev["data"].month)
        if key in mesi:
            mesi[key]["eventi"].append(ev)
    for m in mesi.values():
        m["eventi"].sort(key=lambda e: (e["data"], e["tipo"]))
        m["n_eventi"] = len(m["eventi"])
        m["n_corsi"]    = sum(1 for e in m["eventi"] if e["tipo"] == "CORSO")
        m["n_scadenze"] = sum(1 for e in m["eventi"] if e["tipo"] == "SCADENZA")

    # ── 4) Griglia calendario mensile (modalità "calendario") ──────────────
    calendar_weeks: list[list[dict]] = []
    if view_mode == "calendario":
        # Index eventi per giorno
        eventi_per_giorno: dict[date, list[dict]] = defaultdict(list)
        for ev in eventi:
            eventi_per_giorno[ev["data"]].append(ev)
        cal = _calendar.Calendar(firstweekday=0)  # 0 = lunedì
        for week in cal.monthdatescalendar(cal_anno, cal_mese):
            row = []
            for d in week:
                row.append({
                    "data": d,
                    "is_other_month": d.month != cal_mese,
                    "is_today": d == today,
                    "eventi": sorted(eventi_per_giorno.get(d, []), key=lambda e: e["tipo"]),
                })
            calendar_weeks.append(row)

    # ── 5) Matrice giorni × dipendenti (modalità "matrice") ────────────────
    matrice = None
    filtro_reparto  = (request.GET.get("reparto") or "").strip()
    filtro_mansione = (request.GET.get("mansione") or "").strip()
    filtro_area     = (request.GET.get("area") or "").strip()
    filtro_ruolo    = (request.GET.get("ruolo") or "").strip()
    if view_mode == "matrice" and legacy_id is None:
        # Cap dimensione: max 60 giorni.
        n_days = (range_to - range_from).days + 1
        if n_days > 60:
            range_to = range_from + timedelta(days=59)
            n_days = 60
        giorni = [range_from + timedelta(days=i) for i in range(n_days)]

        # Aggrega per (legacy_id, giorno) → list di eventi
        cell_index: dict[tuple[int, date], list[dict]] = defaultdict(list)
        legacy_ids_coinvolti: set[int] = set()
        for ev in eventi:
            for lid in (ev.get("iscritti_legacy_ids") or []):
                cell_index[(lid, ev["data"])].append(ev)
                legacy_ids_coinvolti.add(lid)

        # Carica attributi dipendente (mansione/reparto da legacy; area da DipendenteAnagraficaAziendale)
        from core.legacy_models import AnagraficaDipendente as _LegAna
        dip_attr: dict[int, dict] = {}
        if legacy_ids_coinvolti:
            for r in _LegAna.objects.filter(id__in=list(legacy_ids_coinvolti)).values("id", "mansione", "reparto"):
                dip_attr[int(r["id"])] = {
                    "mansione": (r.get("mansione") or "").strip(),
                    "reparto":  (r.get("reparto") or "").strip(),
                    "area":     "",
                }
            for r in DipendenteAnagraficaAziendale.objects.filter(
                legacy_anagrafica_id__in=list(legacy_ids_coinvolti)
            ).values("legacy_anagrafica_id", "area", "ruolo_aziendale"):
                lid = int(r["legacy_anagrafica_id"])
                attrs = dip_attr.setdefault(lid, {"mansione": "", "reparto": "", "area": "", "ruolo": ""})
                attrs["area"]  = (r.get("area") or "").strip()
                attrs["ruolo"] = (r.get("ruolo_aziendale") or "").strip()

        # Valori distinti per i menu filtro (calcolati PRIMA di filtrare, su tutti i coinvolti)
        opzioni_reparto  = sorted({a.get("reparto", "")  for a in dip_attr.values() if a.get("reparto")})
        opzioni_mansione = sorted({a.get("mansione", "") for a in dip_attr.values() if a.get("mansione")})
        opzioni_area     = sorted({a.get("area", "")     for a in dip_attr.values() if a.get("area")})
        opzioni_ruolo    = sorted({a.get("ruolo", "")    for a in dip_attr.values() if a.get("ruolo")})

        # Applica filtri sulle righe
        def _row_passes(lid: int) -> bool:
            a = dip_attr.get(lid) or {}
            if filtro_reparto  and a.get("reparto", "") != filtro_reparto:  return False
            if filtro_mansione and a.get("mansione", "") != filtro_mansione: return False
            if filtro_area     and a.get("area", "") != filtro_area:         return False
            if filtro_ruolo    and a.get("ruolo", "") != filtro_ruolo:       return False
            return True

        _ordine_coinvolti = _helpers._build_ordine_map()
        rows_legacy = sorted(
            (lid for lid in legacy_ids_coinvolti if _row_passes(lid)),
            key=lambda lid: _ordine_coinvolti.get(lid, f"#{lid}").lower(),
        )
        rows = []
        for lid in rows_legacy:
            a = dip_attr.get(lid) or {}
            cells = []
            for g in giorni:
                evs = cell_index.get((lid, g), [])
                cells.append({"data": g, "is_today": g == today, "eventi": evs})
            rows.append({
                "legacy_id": lid,
                "nome":      nomi_map.get(lid, f"#{lid}"),
                "reparto":   a.get("reparto", ""),
                "mansione":  a.get("mansione", ""),
                "area":      a.get("area", ""),
                "ruolo":     a.get("ruolo", ""),
                "cells":     cells,
                "n_eventi":  sum(len(c["eventi"]) for c in cells),
            })

        matrice = {
            "giorni":  giorni,
            "rows":    rows,
            "n_rows":  len(rows),
            "n_totale_dipendenti": len(legacy_ids_coinvolti),
            "n_days":  n_days,
            "opzioni_reparto":  opzioni_reparto,
            "opzioni_mansione": opzioni_mansione,
            "opzioni_area":     opzioni_area,
            "opzioni_ruolo":    opzioni_ruolo,
            "filtro_reparto":   filtro_reparto,
            "filtro_mansione":  filtro_mansione,
            "filtro_area":      filtro_area,
            "filtro_ruolo":     filtro_ruolo,
            "any_filter":       bool(filtro_reparto or filtro_mansione or filtro_area or filtro_ruolo),
        }

    # ── Contesto dipendente (per vista per-dipendente) ─────────────────────
    contesto_dipendente = None
    if legacy_id is not None:
        from core.legacy_models import AnagraficaDipendente
        dip = AnagraficaDipendente.objects.filter(id=legacy_id).first()
        if dip:
            contesto_dipendente = {
                "legacy_id": legacy_id,
                "nome":      naming.nome_completo(dip.nome, dip.cognome) or f"#{legacy_id}",
            }

    # Mese precedente/successivo per nav calendario
    cal_prev = _helpers._add_months(date(cal_anno, cal_mese, 1), -1)
    cal_next = _helpers._add_months(date(cal_anno, cal_mese, 1), 1)

    return render(request, "anagrafica/pages/formazione_plan.html", {
        "view_mode":       view_mode,
        "mesi":            list(mesi.values()),
        "calendar_weeks":  calendar_weeks,
        "cal_anno":        cal_anno,
        "cal_mese":        cal_mese,
        "cal_mese_label":  date(cal_anno, cal_mese, 1).strftime("%B %Y").capitalize(),
        "cal_prev_anno":   cal_prev.year, "cal_prev_mese": cal_prev.month,
        "cal_next_anno":   cal_next.year, "cal_next_mese": cal_next.month,
        "matrice":         matrice,
        "range_from":      range_from,
        "range_to":        range_to,
        "totale_eventi":   sum(m["n_eventi"] for m in mesi.values()),
        "totale_corsi":    sum(m["n_corsi"] for m in mesi.values()),
        "totale_scadenze": sum(m["n_scadenze"] for m in mesi.values()),
        "dip":             contesto_dipendente,
        "is_editor":       _helpers._can_edit_formazione(request),
        "today":           today,
    })


# ─────────────────────────────────────────────────────────────────────────────
# RISCHI / CATEGORIE / ESPOSIZIONI — CRUD (PATCH-RISK-02)
# ─────────────────────────────────────────────────────────────────────────────


# ── Fattori di Rischio ──────────────────────────────────────────────────────

@login_required
def fattori_rischio_list(request, form=None, open_create=False, status=200):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare i fattori di rischio.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    fattori = list(
        FattoreRischio.objects
        .annotate(n_categorie=Count("categorie_corso", distinct=True),
                  n_esposizioni=Count("esposizioni", distinct=True))
        .prefetch_related("tipi_visita", "categorie_dpi")
        .order_by("categoria", "nome")
    )
    # Id selezionati per il modale di modifica JS (requisiti generati dal fattore).
    for f in fattori:
        f.sel_visite_ids = [t.pk for t in f.tipi_visita.all()]
        f.sel_dpi_ids = [c.pk for c in f.categorie_dpi.all()]

    visite_opts = list(
        TipoVisitaMedica.objects.filter(is_active=True).order_by("nome").values("id", "nome")
    )
    dpi_opts: list[dict] = []
    try:
        from dpi.models import CategoriaDPI
        dpi_opts = list(
            CategoriaDPI.objects.filter(is_active=True)
            .order_by("order_index", "nome").values("id", "nome")
        )
    except Exception:
        dpi_opts = []

    if form is None:
        form = FattoreRischioForm()
    return render(request, "anagrafica/pages/rischi_fattori_list.html", {
        "fattori":   fattori,
        "form":      form,
        "is_editor": is_editor,
        "CATEGORIA_CHOICES": FattoreRischio.CATEGORIA_CHOICES,
        "visite_opts": visite_opts,
        "dpi_opts":    dpi_opts,
        "open_create": open_create,
    }, status=status)


@login_required
@require_POST
def fattore_rischio_create(request):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    form = FattoreRischioForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Fattore di rischio creato.")
        return redirect("anagrafica:fattori_rischio_list")
    messages.error(request, "Correggi gli errori evidenziati nel form.")
    return fattori_rischio_list(request, form=form, open_create=True, status=400)


@login_required
@require_POST
def fattore_rischio_edit(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(FattoreRischio, pk=pk)
    form = FattoreRischioForm(request.POST, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, f"Fattore «{obj.nome}» aggiornato.")
    else:
        messages.error(request, "Errore aggiornamento: " + "; ".join(f"{k}: {v}" for k, v in form.errors.items()))
    return redirect("anagrafica:fattori_rischio_list")


@login_required
@require_POST
def fattore_rischio_delete(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(FattoreRischio, pk=pk)
    if obj.categorie_corso.exists() or obj.esposizioni.exists():
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        messages.warning(request, f"Fattore «{obj.nome}» disattivato (è collegato a categorie/esposizioni).")
    else:
        obj.delete()
        messages.success(request, "Fattore di rischio eliminato.")
    return redirect("anagrafica:fattori_rischio_list")


# ── Categorie Corso ──────────────────────────────────────────────────────────

@login_required
def categorie_corso_list(request, form=None, open_create=False, status=200):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare le categorie corso.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    categorie = list(
        CategoriaCorso.objects
        .prefetch_related("fattori_rischio")
        .annotate(n_corsi=Count("corsi", distinct=True))
        .order_by("nome")
    )
    if form is None:
        form = CategoriaCorsoForm()
    return render(request, "anagrafica/pages/rischi_categorie_list.html", {
        "categorie": categorie,
        "form":      form,
        "is_editor": is_editor,
        "open_create": open_create,
    }, status=status)


@login_required
@require_POST
def categoria_corso_create(request):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    form = CategoriaCorsoForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Categoria corso creata.")
        return redirect("anagrafica:categorie_corso_list")
    messages.error(request, "Correggi gli errori evidenziati nel form.")
    return categorie_corso_list(request, form=form, open_create=True, status=400)


@login_required
@require_POST
def categoria_corso_edit(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(CategoriaCorso, pk=pk)
    form = CategoriaCorsoForm(request.POST, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, f"Categoria «{obj.nome}» aggiornata.")
    else:
        messages.error(request, "Errore aggiornamento: " + "; ".join(f"{k}: {v}" for k, v in form.errors.items()))
    return redirect("anagrafica:categorie_corso_list")


@login_required
@require_POST
def categoria_corso_delete(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(CategoriaCorso, pk=pk)
    if obj.corsi.exists():
        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        messages.warning(request, f"Categoria «{obj.nome}» disattivata (collegata a corsi).")
    else:
        obj.delete()
        messages.success(request, "Categoria eliminata.")
    return redirect("anagrafica:categorie_corso_list")


# ── Esposizioni Rischio ──────────────────────────────────────────────────────

@login_required
def esposizioni_rischio_list(request, form=None, open_create=False, status=200):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per visualizzare le esposizioni.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    esposizioni = list(
        EsposizioneRischio.objects
        .select_related("fattore", "mansione", "area")
        .order_by("fattore__categoria", "fattore__nome", "mansione__nome", "area__nome")
    )
    if form is None:
        form = EsposizioneRischioForm()
    return render(request, "anagrafica/pages/rischi_esposizioni_list.html", {
        "esposizioni": esposizioni,
        "form":        form,
        "is_editor":   is_editor,
        "open_create": open_create,
    }, status=status)


@login_required
@require_POST
def esposizione_rischio_create(request):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    form = EsposizioneRischioForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Esposizione creata.")
        return redirect("anagrafica:esposizioni_rischio_list")
    messages.error(request, "Correggi gli errori evidenziati nel form.")
    return esposizioni_rischio_list(request, form=form, open_create=True, status=400)


@login_required
@require_POST
def esposizione_rischio_edit(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(EsposizioneRischio, pk=pk)
    form = EsposizioneRischioForm(request.POST, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, "Esposizione aggiornata.")
    else:
        messages.error(request, "Errore aggiornamento: " + "; ".join(f"{k}: {v}" for k, v in form.errors.items()))
    return redirect("anagrafica:esposizioni_rischio_list")


@login_required
@require_POST
def esposizione_rischio_delete(request, pk: int):
    if not _helpers._can_edit_formazione(request):
        return _forbid_json_or_redirect(request, "Permessi insufficienti.")
    obj = get_object_or_404(EsposizioneRischio, pk=pk)
    obj.delete()
    messages.success(request, "Esposizione eliminata.")
    return redirect("anagrafica:esposizioni_rischio_list")


def _forbid_json_or_redirect(request, msg: str):
    """Helper: 403 JSON per AJAX, altrimenti messaggio flash + redirect."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": msg}, status=403)
    messages.error(request, msg)
    return redirect("anagrafica:index")


# -- GESTIONE E-LEARNING: hub autori/HR --------------------------------------

def _elearning_salute(n_slide: int, n_domande: int, n_invalid: int) -> tuple[str, str]:
    """Classifica lo stato di salute di un micro-corso e-learning (codice, etichetta)."""
    if n_slide == 0:
        return ("CRIT", "Senza slide")
    if n_domande == 0:
        return ("INFO", "Senza quiz")
    if n_invalid:
        return ("WARN", "Quiz incompleto")
    return ("OK", "Pronto")


def _elearning_iscritti_rows(corso):
    """Righe «iscritti & esiti» di un micro-corso: nome dipendente + avanzamento + esito."""
    from ..services.elearning_quiz import tentativi_rimasti
    from ..services.elearning_regole import regola_corso
    enrollments = list(TrainingElearningEnrollment.objects.filter(corso=corso))
    nomi = _helpers._build_nomi_map() if enrollments else {}
    regola = regola_corso(corso)
    rows = []
    for e in enrollments:
        rows.append({
            "pk": e.pk,
            "esauriti": e.stato != "COMPLETATO" and tentativi_rimasti(e, regola) == 0,
            "legacy_id": e.legacy_anagrafica_id,
            "nome": nomi.get(e.legacy_anagrafica_id, f"#{e.legacy_anagrafica_id}"),
            "stato": e.stato,
            "stato_disp": e.get_stato_display(),
            "avanzamento": f"{e.ultima_slide_ordine}/{e.n_slide_totali}" if e.n_slide_totali else "—",
            "best": e.best_punteggio_pct,
            "n_tentativi": e.n_tentativi,
            "data_completamento": e.data_completamento,
        })
    _ordine = _helpers._build_ordine_map() if rows else {}
    rows.sort(key=lambda x: _ordine.get(x["legacy_id"], x["nome"]).lower())
    return rows


@login_required
def formazione_elearning_hub(request):
    """Hub di gestione dei micro-corsi e-learning (autori/HR): elenco corsi con stato di
    salute (slide/quiz), iscritti e completati, e azioni rapide."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per la sezione formazione.")
        return redirect("anagrafica:index")
    from django.db.models import Count, Q
    corsi = list(
        TrainingCourse.objects.filter(is_elearning=True)
        .select_related("piano")
        .prefetch_related("quiz_domande__opzioni")
        .annotate(
            n_slide=Count("slides", filter=Q(slides__is_active=True), distinct=True),
            n_domande=Count("quiz_domande", filter=Q(quiz_domande__is_active=True), distinct=True),
            n_iscritti=Count("iscrizioni_elearning", distinct=True),
            n_completati=Count("iscrizioni_elearning", filter=Q(iscrizioni_elearning__stato="COMPLETATO"), distinct=True),
        )
        .order_by("-is_active", "stato", "titolo")
    )
    tot = {"corsi": len(corsi), "pubblicati": 0, "iscritti": 0, "completati": 0, "problemi": 0}
    rows = []
    for c in corsi:
        n_invalid = sum(
            1 for d in c.quiz_domande.all()
            if d.is_active and _problema_domanda(d)
        )
        salute = _elearning_salute(c.n_slide, c.n_domande, n_invalid)
        if c.stato == "ATTIVO" and c.is_active:
            tot["pubblicati"] += 1
        tot["iscritti"] += c.n_iscritti
        tot["completati"] += c.n_completati
        if salute[0] in ("CRIT", "WARN"):
            tot["problemi"] += 1
        rows.append({"corso": c, "n_invalid": n_invalid, "salute": salute})
    return render(request, "anagrafica/pages/formazione_elearning_hub.html", {
        "rows": rows,
        "tot": tot,
        "is_editor": _helpers._can_edit_formazione(request),
    })


@login_required
def formazione_elearning_manage(request, corso_id: int):
    """Cabina di regia di un singolo micro-corso e-learning: contenuti, iscritti & esiti,
    stato di pubblicazione ed export — tutto in un'unica pagina."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per la sezione formazione.")
        return redirect("anagrafica:index")
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    slides = list(corso.slides.filter(is_active=True))
    domande = list(corso.quiz_domande.filter(is_active=True).prefetch_related("opzioni"))
    n_invalid = sum(1 for d in domande if _problema_domanda(d))
    salute = _elearning_salute(len(slides), len(domande), n_invalid)

    iscritti = _elearning_iscritti_rows(corso)
    counts = {"iscritti": len(iscritti), "in_corso": 0, "completati": 0, "non_superato": 0}
    for r in iscritti:
        if r["stato"] == "COMPLETATO":
            counts["completati"] += 1
        elif r["stato"] == "NON_SUPERATO":
            counts["non_superato"] += 1
        elif r["stato"] == "IN_CORSO":
            counts["in_corso"] += 1

    is_editor = _helpers._can_edit_formazione(request)

    # Assegnazioni (obbligo) del corso + pool dipendenti assegnabili per il picker.
    assegnazioni = list(TrainingAssignment.objects.filter(corso=corso))
    nomi = _helpers._build_nomi_map() if (assegnazioni or is_editor) else {}
    for a in assegnazioni:
        a.nome = nomi.get(a.legacy_anagrafica_id, f"#{a.legacy_anagrafica_id}")
    assegnazioni.sort(key=lambda a: (a.nome or "").lower())
    assegnabili = []
    if is_editor:
        assegnati_ids = {a.legacy_anagrafica_id for a in assegnazioni}
        attivi_ids = set(
            DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=True)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        for lid in sorted(attivi_ids):
            if lid not in assegnati_ids and lid in nomi:
                assegnabili.append({"legacy_id": lid, "nome": nomi[lid]})
        _ordine_ass = _helpers._build_ordine_map()
        assegnabili.sort(key=lambda x: _ordine_ass.get(x["legacy_id"], x["nome"]).lower())

    # Storico delle versioni con i completamenti registrati su ciascuna.
    from django.db.models import Count as _Count
    per_versione = dict(TrainingEmployeeRecord.objects.filter(corso=corso, completamento_elearning__isnull=False)
                        .values("course_version_snapshot").annotate(n=_Count("pk")).order_by()
                        .values_list("course_version_snapshot", "n"))
    versioni = list(corso.versioni.select_related("revised_by").order_by("-created_at"))
    for v in versioni:
        v.n_completamenti = per_versione.get(v.version_label, 0)

    return render(request, "anagrafica/pages/formazione_elearning_manage.html", {
        "corso": corso,
        "versioni": versioni,
        "is_editor": is_editor,
        "n_slide": len(slides),
        "n_domande": len(domande),
        "n_invalid": n_invalid,
        "salute": salute,
        "iscritti": iscritti,
        "counts": counts,
        "pubblicato": corso.stato == "ATTIVO" and corso.is_active,
        "assegnazioni": assegnazioni,
        "assegnabili": assegnabili,
    })


@login_required
@require_POST
def formazione_elearning_publish_toggle(request, corso_id: int):
    """Pubblica/ritira un micro-corso. La pubblicazione è bloccata se mancano le slide o
    il quiz ha domande senza risposta corretta (controllo qualità centralizzato)."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_elearning_hub")
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    if corso.stato == "ATTIVO":
        corso.stato = "BOZZA"
        corso.save(update_fields=["stato", "updated_at"])
        messages.info(request, "Corso ritirato (bozza): non più visibile ai discenti.")
    else:
        n_slide = corso.slides.filter(is_active=True).count()
        domande = list(corso.quiz_domande.filter(is_active=True).prefetch_related("opzioni"))
        n_invalid = sum(1 for d in domande if _problema_domanda(d))
        from ..services.elearning_regole import regola_corso
        if n_slide == 0:
            messages.error(request, "Impossibile pubblicare: aggiungi almeno una slide.")
        elif not regola_corso(corso).confermata_rspp:
            messages.error(request, "Impossibile pubblicare: le regole di fruizione (FAD) del corso non sono "
                                    "state confermate dall'RSPP. Impostazioni e-learning → Regole del corso.")
        elif domande and n_invalid:
            messages.error(request, "Impossibile pubblicare: il quiz ha domande incomplete (risposte corrette mancanti o non coerenti con il tipo). Completa le domande o disattivale.")
        else:
            corso.stato = "ATTIVO"
            corso.is_active = True
            corso.save(update_fields=["stato", "is_active", "updated_at"])
            messages.success(request, "Corso pubblicato: ora visibile in «Corsi online».")
            try:
                from ..services.elearning_versioni import registra
                registra(corso, user=request.user, motivo="Pubblicazione", alla_pubblicazione=True)
            except Exception:
                logger.exception("Versione e-learning non fissata alla pubblicazione del corso %s", corso.pk)
    # Ritorna alla pagina di provenienza interna, altrimenti alla cabina di regia
    nxt = request.POST.get("next") or ""
    from core.redirects import safe_next

    if nxt and safe_next(request, nxt, "") == nxt:
        return redirect(nxt)
    return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)


@login_required
def formazione_elearning_iscritti_csv(request, corso_id: int):
    """Export CSV di iscritti ed esiti del micro-corso (audit). Tracciato in TrainingExportLog."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per esportare i report.")
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id, is_elearning=True)
    rows = _elearning_iscritti_rows(corso)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="elearning_{corso.codice}_iscritti.csv"'
    resp.write("﻿")  # BOM per apertura corretta in Excel
    writer = safe_csv_writer(resp, delimiter=";")
    writer.writerow(["Dipendente", "ID", "Stato", "Avanzamento slide", "Miglior punteggio %", "Tentativi", "Data completamento"])
    for r in rows:
        writer.writerow([
            r["nome"], r["legacy_id"], r["stato_disp"], r["avanzamento"],
            r["best"] if r["best"] is not None else "", r["n_tentativi"],
            r["data_completamento"] or "",
        ])
    try:
        TrainingExportLog.objects.create(
            tipo="ISCRITTI",
            filtri_json={"modalita": "ELEARNING", "corso": corso.codice},
            righe_esportate=len(rows),
            generato_da=request.user,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except Exception:
        logger.warning("Audit export e-learning iscritti fallito", exc_info=True)
    return resp


@login_required
@require_POST
def formazione_elearning_assign(request, corso_id: int):
    """Assegna (obbligo) il micro-corso a uno o più dipendenti: crea TrainingAssignment
    e richiama l'hook notifica (predisposto, invio non attivo). Idempotente."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per assegnare corsi.")
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse.objects.select_related("piano"), pk=corso_id, is_elearning=True)

    ids, seen = [], set()
    for raw in request.POST.getlist("dipendenti_selezionati"):
        s = str(raw).strip()
        if s.isdigit():
            lid = int(s)
            if lid > 0 and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    if not ids:
        messages.warning(request, "Nessun dipendente selezionato.")
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)

    due = None
    raw_due = (request.POST.get("due_date") or "").strip()
    if raw_due:
        from datetime import datetime as _dt
        try:
            due = _dt.strptime(raw_due, "%Y-%m-%d").date()
        except ValueError:
            due = None

    from ..services.elearning_notifications import notify_corso_assegnato
    n_new = 0
    for lid in ids:
        from ..services.elearning_fruizione import ciclo_per_nuova_assegnazione
        obj, created = TrainingAssignment.objects.get_or_create(
            corso=corso, legacy_anagrafica_id=lid, ciclo=ciclo_per_nuova_assegnazione(corso, lid),
            defaults={"stato": "ASSEGNATO", "piano": corso.piano, "due_date": due, "assigned_by": request.user},
        )
        if created:
            n_new += 1
            try:
                notify_corso_assegnato(corso.pk, lid)
            except Exception:
                logger.debug("Hook notifica assegnazione e-learning fallito", exc_info=True)
    if n_new:
        messages.success(request, f"{n_new} dipendente/i assegnato/i al corso.")
    else:
        messages.info(request, "I dipendenti selezionati erano già assegnati.")
    return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)


@login_required
@require_POST
def formazione_elearning_unassign(request, corso_id: int, assignment_id: int):
    """Rimuove un'assegnazione non ancora completata."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)
    a = get_object_or_404(TrainingAssignment, pk=assignment_id, corso_id=corso_id)
    if a.stato == "COMPLETATO":
        messages.error(request, "Non puoi rimuovere un'assegnazione già completata.")
    else:
        a.delete()
        messages.success(request, "Assegnazione rimossa.")
    return redirect("anagrafica:formazione_elearning_manage", corso_id=corso_id)


@login_required
def formazione_elearning_settings(request):
    """Impostazioni e-learning (singleton): default dei nuovi micro-corsi e percorso
    LibreOffice per l'import PowerPoint. Gated dal permesso di modifica formazione."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare le impostazioni e-learning.")
        return redirect("anagrafica:formazione_elearning_hub")
    cfg = ElearningConfig.get_instance()
    if request.method == "POST":
        prima_rspp = list(cfg.conferma_fad_utente_ids or [])
        form = ElearningConfigForm(request.POST, instance=cfg, puo_rspp=request.user.is_superuser)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            from core.audit import log_action
            log_action(request, "elearning_impostazioni", "anagrafica", {
                "max_tentativi": obj.max_tentativi_quiz, "soglia_default": obj.quiz_punteggio_minimo_default,
                "rinnovo_giorni": obj.finestra_rinnovo_giorni, "entro_giorni": obj.giorni_entro_default,
                "conferma_fad_prima": prima_rspp, "conferma_fad_dopo": obj.conferma_fad_utente_ids,
            }, oggetto=obj)
            messages.success(request, "Impostazioni e-learning salvate.")
            return redirect("anagrafica:formazione_elearning_settings")
        messages.error(request, "Controlla i campi: " + form.errors.as_text())
    else:
        form = ElearningConfigForm(instance=cfg, puo_rspp=request.user.is_superuser)
    # Diagnostica LibreOffice (per l'import PowerPoint)
    from ..services.elearning_import import find_libreoffice
    return render(request, "anagrafica/pages/formazione_elearning_settings.html", {
        "form": form,
        "cfg": cfg,
        "libreoffice_trovato": find_libreoffice(),
    })


# -- AUTORE: gestione contenuti (slide + quiz) -------------------------------

def _problema_domanda(d) -> str:
    from ..services.elearning_quiz import problema_domanda
    return problema_domanda(d)


def _versiona(request, corso, motivo: str) -> None:
    """Dopo una modifica ai contenuti: allinea la versione del corso (solo se pubblicato)."""
    try:
        from ..services.elearning_versioni import registra
        esito = registra(corso, user=request.user, motivo=motivo)
    except Exception:
        logger.exception("Versione e-learning non aggiornata per corso %s", corso.pk)
        return
    if esito.nuova:
        messages.info(request, f"Il corso era già stato completato: creata la versione {esito.etichetta}. "
                               "Il registro di chi ha completato resta legato alla versione precedente."
                      + (" Se le regole del corso lo prevedono, chi ha completato la versione precedente "
                         "verrà riassegnato stanotte." ))


@login_required
def formazione_corso_elearning(request, corso_id: int):
    """Pagina autore: gestione slide e quiz di un micro-corso e-learning."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare i contenuti e-learning.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    slides = list(corso.slides.all())
    domande = list(corso.quiz_domande.prefetch_related("opzioni").all())
    # Segnala le domande attive senza alcuna opzione corretta: sarebbero impossibili da
    # superare e vengono escluse dal quiz del discente finché non si completa l'autoring.
    n_domande_incomplete = 0
    for d in domande:
        d.problema = _problema_domanda(d) if d.is_active else ""
        d.vf_vera = any(o.corretta and o.testo == "Vero" for o in d.opzioni.all())
        if d.problema:
            n_domande_incomplete += 1
    return render(request, "anagrafica/pages/formazione_corso_elearning.html", {
        "corso": corso,
        "slides": slides,
        "domande": domande,
        "n_domande_incomplete": n_domande_incomplete,
        "tipi_domanda": TrainingQuizQuestion.TIPO_CHOICES,
        "slide_form": TrainingSlideForm(initial={"ordine": (slides[-1].ordine + 1) if slides else 1}, corso=corso),
        "moduli": list(corso.moduli_elearning.all()),
        **_import_stato_ctx(corso),
        "question_form": TrainingQuizQuestionForm(initial={"ordine": (domande[-1].ordine + 1) if domande else 1}),
    })


@login_required
@require_POST
def formazione_slide_save(request, corso_id: int):
    """Crea o aggiorna una slide. slide_id vuoto = creazione."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    slide_id = request.POST.get("slide_id")
    instance = get_object_or_404(TrainingSlide, pk=slide_id, corso=corso) if slide_id else None
    form = TrainingSlideForm(request.POST, instance=instance, corso=corso)
    if form.is_valid():
        slide = form.save(commit=False)
        slide.corso = corso
        if not slide.pk:
            slide.created_by = request.user
        slide.save()
        messages.success(request, f'Slide "{slide.titolo}" salvata.')
        _versiona(request, corso, f"Slide «{slide.titolo}» modificata")
    else:
        messages.error(request, "Errore nel salvataggio della slide: " + form.errors.as_text())
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_slide_delete(request, corso_id: int, slide_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    slide = get_object_or_404(TrainingSlide, pk=slide_id, corso_id=corso_id)
    titolo = slide.titolo
    slide.delete()
    messages.success(request, "Slide eliminata.")
    _versiona(request, slide.corso, f"Slide «{titolo}» eliminata")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_slide_import(request, corso_id: int):
    """Importa slide da un file PowerPoint/PDF: una slide-immagine per pagina."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    f = request.FILES.get("file")
    if not f:
        messages.error(request, "Nessun file selezionato.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    # Limite dimensione (UPLOAD_MAX_FILE_MB) per evitare upload abnormi
    if f.size and f.size > DOCUMENT_MAX_BYTES:
        messages.error(request, f"File troppo grande (massimo {DOCUMENT_MAX_MB} MB).")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    from core.upload_mime import UploadMimeValidationError
    from ..services.elearning_import import ALLOWED_EXTS, ImportError_, accoda_import
    from ..services.upload_documenti import valida_documento
    try:
        valida_documento(f, set(ALLOWED_EXTS), label="Presentazione")
    except UploadMimeValidationError as exc:
        messages.error(request, f"File rifiutato: {exc}")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    try:
        accoda_import(corso, f, user=request.user)
        messages.success(request, f"«{f.name}» caricato: la conversione in slide prosegue in background. "
                                  "Lo stato è qui sotto, nella sezione Slide.")
    except ImportError_ as e:
        messages.error(request, str(e))
    except Exception:
        logger.exception("Import slide e-learning non accodato per corso %s", corso_id)
        messages.error(request, "Import non avviato: errore imprevisto.")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
def formazione_slide_import_stato(request, corso_id: int):
    """Partial HTMX: stato degli ultimi import di slide (si ricarica finché sono in corso)."""
    if not _helpers._can_edit_formazione(request):
        return HttpResponse(status=286)  # 286 = HTMX smette di interrogare
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    return render(request, "anagrafica/partials/_elearning_import_stato.html", _import_stato_ctx(corso))


def _import_stato_ctx(corso) -> dict:
    from ..models_elearning import TrainingElearningImport
    from ..services.elearning_import import scadi_import_bloccati
    scadi_import_bloccati()
    lavori = list(TrainingElearningImport.objects.filter(corso=corso).order_by("-creato_il")[:3])
    return {"corso": corso, "import_lavori": lavori, "import_in_corso": any(j.in_lavorazione for j in lavori)}


@login_required
@require_POST
def formazione_question_save(request, corso_id: int):
    """Crea o aggiorna una domanda del quiz."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    q_id = request.POST.get("question_id")
    instance = get_object_or_404(TrainingQuizQuestion, pk=q_id, corso=corso) if q_id else None
    tipo_prima = instance.tipo if instance else ""
    form = TrainingQuizQuestionForm(request.POST, instance=instance)
    if (form.is_valid() and form.cleaned_data.get("tipo") == TrainingQuizQuestion.TIPO_VERO_FALSO
            and request.POST.get("vf_vera") not in ("0", "1")):
        messages.error(request, "Per una domanda vero/falso indica se l'affermazione è vera o falsa.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    if form.is_valid():
        q = form.save(commit=False)
        q.corso = corso
        with transaction.atomic():
            q.save()
            if q.tipo == TrainingQuizQuestion.TIPO_VERO_FALSO:
                from ..services.elearning_quiz import imposta_vero_falso
                imposta_vero_falso(q, bool(form.cleaned_data.get("vf_vera")))
        messages.success(request, "Domanda salvata." + (
            " Le opzioni precedenti sono state sostituite da «Vero» e «Falso»."
            if tipo_prima and tipo_prima != q.tipo and q.tipo == TrainingQuizQuestion.TIPO_VERO_FALSO else ""))
        _versiona(request, corso, "Domanda del quiz modificata")
    else:
        messages.error(request, "Errore nella domanda: " + form.errors.as_text())
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_question_delete(request, corso_id: int, question_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    q = get_object_or_404(TrainingQuizQuestion, pk=question_id, corso_id=corso_id)
    corso = q.corso
    q.delete()
    messages.success(request, "Domanda eliminata.")
    _versiona(request, corso, "Domanda del quiz eliminata")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_option_save(request, corso_id: int, question_id: int):
    """Aggiunge/aggiorna un'opzione di risposta a una domanda."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    domanda = get_object_or_404(TrainingQuizQuestion, pk=question_id, corso_id=corso_id)
    if domanda.tipo == TrainingQuizQuestion.TIPO_VERO_FALSO:
        messages.error(request, "Le opzioni di una domanda vero/falso si impostano dalla domanda stessa.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    opt_id = request.POST.get("option_id")
    instance = get_object_or_404(TrainingQuizOption, pk=opt_id, domanda=domanda) if opt_id else None
    form = TrainingQuizOptionForm(request.POST, instance=instance)
    if form.is_valid():
        opt = form.save(commit=False)
        opt.domanda = domanda
        opt.save()
        messages.success(request, "Opzione salvata.")
        _versiona(request, domanda.corso, "Risposta del quiz modificata")
    else:
        messages.error(request, "Errore nell'opzione: " + form.errors.as_text())
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_option_delete(request, corso_id: int, option_id: int):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    opt = get_object_or_404(TrainingQuizOption, pk=option_id, domanda__corso_id=corso_id)
    if opt.domanda.tipo == TrainingQuizQuestion.TIPO_VERO_FALSO:
        messages.error(request, "Le opzioni di una domanda vero/falso si impostano dalla domanda stessa.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    corso = opt.domanda.corso
    opt.delete()
    messages.success(request, "Opzione eliminata.")
    _versiona(request, corso, "Risposta del quiz eliminata")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
def formazione_question_import(request, corso_id: int):
    """GET: scarica il foglio modello. POST: importa le domande da Excel (tutto o niente)."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    from ..services import elearning_quiz_import as qimp
    if request.method != "POST":
        resp = HttpResponse(qimp.modello_xlsx(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="modello_domande_quiz.xlsx"'
        return resp
    f = request.FILES.get("file")
    if not f:
        messages.error(request, "Nessun file selezionato.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    from core.upload_mime import UploadMimeValidationError
    from ..services.upload_documenti import valida_documento
    try:
        valida_documento(f, {".xlsx"}, label="Foglio domande")
    except UploadMimeValidationError as exc:
        messages.error(request, f"File rifiutato: {exc}")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    try:
        n = qimp.importa(corso, f)
    except qimp.ImportQuizError as exc:
        elenco = exc.errori[:8]
        altri = len(exc.errori) - len(elenco)
        messages.error(request, "Import non eseguito, nessuna domanda salvata. " + " · ".join(elenco)
                       + (f" · e altri {altri} errori." if altri > 0 else ""))
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    _audit_formazione(request, "elearning_quiz_import", {"corso_id": corso.pk, "domande": n})
    messages.success(request, f"Importate {n} domande da «{f.name}».")
    _versiona(request, corso, f"Importate {n} domande")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_modulo_save(request, corso_id: int):
    """Crea o rinomina un modulo del corso online (modulo_id vuoto = nuovo)."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    from ..models_elearning import TrainingElearningModulo
    corso = get_object_or_404(TrainingCourse, pk=corso_id)
    titolo = (request.POST.get("titolo") or "").strip()[:200]
    ordine = request.POST.get("ordine") or ""
    if not titolo:
        messages.error(request, "Il modulo ha bisogno di un titolo.")
        return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)
    modulo_id = request.POST.get("modulo_id")
    modulo = (get_object_or_404(TrainingElearningModulo, pk=modulo_id, corso=corso) if modulo_id
              else TrainingElearningModulo(corso=corso))
    modulo.titolo = titolo
    if ordine.isdigit():
        modulo.ordine = int(ordine)
    elif not modulo.pk:
        modulo.ordine = (corso.moduli_elearning.order_by("-ordine").values_list("ordine", flat=True).first() or 0) + 1
    modulo.save()
    messages.success(request, f"Modulo «{titolo}» salvato.")
    _versiona(request, corso, f"Modulo «{titolo}» salvato")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


@login_required
@require_POST
def formazione_modulo_delete(request, corso_id: int, modulo_id: int):
    """Elimina il modulo; le sue slide restano, senza modulo."""
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Permesso negato.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=corso_id)
    from ..models_elearning import TrainingElearningModulo
    modulo = get_object_or_404(TrainingElearningModulo, pk=modulo_id, corso_id=corso_id)
    corso, titolo = modulo.corso, modulo.titolo
    modulo.delete()
    messages.success(request, f"Modulo «{titolo}» eliminato: le sue slide restano nel corso.")
    _versiona(request, corso, f"Modulo «{titolo}» eliminato")
    return redirect("anagrafica:formazione_corso_elearning", corso_id=corso_id)


# -- DISCENTE: catalogo, player, slide, quiz e immagini delle slide vivono in
# views_elearning.py (prompt 05, rilascio 1: accesso verificato lato server).
