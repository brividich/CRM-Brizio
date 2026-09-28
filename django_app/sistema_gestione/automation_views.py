from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.upload_mime import safe_filename
from .acl_bootstrap import PERM_AUDIT_VIEW, PERM_AUDIT_EDIT, PERM_AUDIT_APPROVA
from .audit_forms import AuditEsitoForm
from .automation_forms import ChecklistProcessoForm, AllegatoEvidenzaForm, VerificaEfficaciaForm
from .audit_views import _assigned_executor, _rapporto_modificabile, _audit_url
from .models import (Audit, AuditEsito, AuditAllegato, AuditRapportoVersione, Processo,
                     ChecklistProcesso, ProgrammaAudit, RigaProgramma, CellaProgramma)
from .services import audit as audit_service
from .services import audit_automation as service
from .views import _has_perm, _nega, MODULE


@login_required
def esito_editor(request, pk, esito_pk):
    audit = get_object_or_404(Audit, pk=pk)
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare questa verifica.")
    esito = get_object_or_404(AuditEsito, pk=esito_pk, audit=audit)
    prossima = next((e for e in audit.esiti.all() if e.pk != esito.pk and service.problemi_esito(e)), None)
    return render(request, "sistema_gestione/pages/audit_esito_editor.html", {
        "audit": audit, "esito": esito, "form": AuditEsitoForm(instance=esito),
        "form_allegato": AllegatoEvidenzaForm(), "prossima": prossima,
        "puo_compilare": _assigned_executor(request, audit) and _rapporto_modificabile(audit),
        "mancanti": service.problemi_esito(esito), "evidenza_completa": service.testo_evidenza(esito),
    })


@login_required
@transaction.atomic
def checklist_processo(request, processo_pk, pk=None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non puoi modificare le checklist.")
    processo = get_object_or_404(Processo.objects.select_for_update(), pk=processo_pk)
    domanda = get_object_or_404(ChecklistProcesso, pk=pk, processo=processo) if pk else ChecklistProcesso(processo=processo)
    form = ChecklistProcessoForm(request.POST or None, instance=domanda)
    if request.method == "POST" and form.is_valid():
        domanda = form.save(commit=False)
        if pk:
            domanda.revisione += 1
        domanda.save()
        service.registra_revisione(processo, request.user, form.cleaned_data["motivo"])
        log_action(request, "audit_checklist_revisionata", MODULE, {"domanda": domanda.pk, "revisione": domanda.revisione}, oggetto=processo)
        messages.success(request, "Checklist aggiornata per i nuovi piani. Gli audit esistenti conservano le loro domande.")
        return redirect("sistema_gestione:processo_dettaglio", pk=processo.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {"page_title": "Domanda del processo " + str(processo),
        "form": form, "indietro": reverse("sistema_gestione:processo_dettaglio", args=[processo.pk])})


@login_required
@require_POST
@transaction.atomic
def proponi_checklist(request, processo_pk):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non puoi gestire le checklist.")
    processo = get_object_or_404(Processo.objects.select_for_update(), pk=processo_pk, attivo=True)
    numero = service.proponi_domande(processo)
    if numero:
        service.registra_revisione(processo, request.user, "Proposte automatiche dalla scheda: da verificare e attivare")
        log_action(request, "audit_checklist_proposta", MODULE, {"domande": numero, "algoritmo": "scheda-v1"}, oggetto=processo)
    messages.info(request, f"{numero} nuove domande in bozza. Verifica criteri e punti norma, poi attivale. Le domande esistenti restano invariate.")
    return redirect("sistema_gestione:processo_dettaglio", pk=processo.pk)


@require_POST
@transaction.atomic
def esito_bozza(request, pk, esito_pk):
    if not request.user.is_authenticated:
        return JsonResponse({"errore": "Sessione scaduta. Accedi e riprova."}, status=401)
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    if not _assigned_executor(request, audit):
        return JsonResponse({"errore": "Non sei autorizzato a compilare questa verifica."}, status=403)
    if not _rapporto_modificabile(audit):
        return JsonResponse({"errore": "Il rapporto e firmato o non modificabile."}, status=409)
    esito = get_object_or_404(AuditEsito, pk=esito_pk, audit=audit)
    form = AuditEsitoForm(request.POST, instance=esito)
    if not form.is_valid():
        return JsonResponse({"errore": "Bozza non salvata", "errori": form.errors.get_json_data()}, status=409 if form.non_field_errors() else 400)
    esito = audit_service.salva_esito(form.save(commit=False), utente=request.user, genera_rilievo=False)
    log_action(request, "audit_bozza_salvata", MODULE, {"esito": esito.pk, "versione": esito.versione}, oggetto=audit)
    return JsonResponse({"versione": esito.versione, "salvato_il": timezone.localtime(esito.updated_at).strftime("%H:%M:%S"),
                         "mancanti": service.problemi_esito(esito)})


@login_required
@require_POST
@transaction.atomic
def allegato_carica(request, pk, esito_pk):
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    if not _assigned_executor(request, audit) or not _rapporto_modificabile(audit):
        return _nega(request, "Le evidenze si caricano durante la compilazione del rapporto.")
    esito = get_object_or_404(AuditEsito, pk=esito_pk, audit=audit)
    form = AllegatoEvidenzaForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "sistema_gestione/pages/audit_form.html", {"page_title": "Allega evidenza",
            "form": form, "indietro": _audit_url(audit, f"esito-{esito.pk}")})
    file = form.cleaned_data["file"]
    digest = sha256()
    for chunk in file.chunks():
        digest.update(chunk)
    file.seek(0)
    impronta = digest.hexdigest()
    if esito.allegati.filter(sha256=impronta).exists():
        messages.info(request, "Questa evidenza e gia allegata alla verifica.")
        return redirect(_audit_url(audit, f"esito-{esito.pk}"))
    allegato = AuditAllegato(esito=esito, nome=safe_filename(file.name), sha256=impronta,
                            dimensione=file.size, caricato_da=request.user)
    allegato.file.save(uuid4().hex + Path(allegato.nome).suffix.lower(), file, save=False)
    try:
        allegato.save()
    except Exception:
        allegato.file.delete(save=False)
        raise
    audit.riepilogo_generato = ""
    audit.save(update_fields=["riepilogo_generato"])
    log_action(request, "audit_evidenza_allegata", MODULE, {"allegato": allegato.pk, "sha256": impronta}, oggetto=audit)
    messages.success(request, "Evidenza archiviata con impronta SHA-256.")
    return redirect(_audit_url(audit, f"esito-{esito.pk}"))


@login_required
def allegato_download(request, pk, allegato_pk):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare questa evidenza.")
    allegato = get_object_or_404(AuditAllegato, pk=allegato_pk, esito__audit_id=pk)
    log_action(request, "audit_evidenza_scaricata", MODULE, {"allegato": allegato.pk}, oggetto=allegato.esito.audit)
    response = FileResponse(allegato.file.open("rb"), as_attachment=True, filename=allegato.nome)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
@transaction.atomic
def prepara_rapporto(request, pk):
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    if not _assigned_executor(request, audit) or not _rapporto_modificabile(audit):
        return _nega(request, "Non puoi preparare questo rapporto.")
    audit.riepilogo_generato = service.riepilogo_rapporto(audit)
    audit.save(update_fields=["riepilogo_generato", "updated_at"])
    log_action(request, "audit_rapporto_precompilato", MODULE, {"algoritmo": "riepilogo-v1"}, oggetto=audit)
    messages.success(request, "Riepilogo compilato dai dati registrati. Completa il giudizio e i punti di forza con la tua valutazione.")
    return redirect(_audit_url(audit, "rapporto"))


@login_required
@transaction.atomic
def verifica_efficacia(request, pk, esito_pk):
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    if not _assigned_executor(request, audit) and not _has_perm(request, PERM_AUDIT_APPROVA):
        return _nega(request, "Serve un auditor assegnato o un approvatore.")
    esito = get_object_or_404(AuditEsito, pk=esito_pk, audit=audit, ofi__isnull=False)
    if esito.responsabile_azione_id == request.user.pk:
        return _nega(request, "La verifica dell'efficacia richiede una persona diversa dal responsabile dell'azione.")
    form = VerificaEfficaciaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        verifica = form.save(commit=False)
        verifica.esito = esito
        verifica.verificato_da = request.user
        verifica.save()
        log_action(request, "audit_efficacia_verificata", MODULE,
                   {"rilievo": esito.ofi_id, "verifica": verifica.pk, "risultato": verifica.risultato}, oggetto=audit)
        messages.success(request, "Efficacia registrata nello storico. Il ciclo dell'azione si gestisce nel Registro OFI.")
        return redirect(_audit_url(audit, f"esito-{esito.pk}"))
    return render(request, "sistema_gestione/pages/audit_form.html", {"page_title": f"Efficacia rilievo MOD.174 n. {esito.ofi.numero}",
        "form": form, "indietro": _audit_url(audit, f"esito-{esito.pk}")})


@login_required
def priorita(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il programma audit.")
    return render(request, "sistema_gestione/pages/audit_priorita.html", {
        "proposte": service.priorita_processi(Processo.objects.filter(attivo=True)),
        "programmi": ProgrammaAudit.objects.filter(stato=ProgrammaAudit.STATO_BOZZA),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
    })


@login_required
@require_POST
@transaction.atomic
def applica_priorita(request):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _nega(request, "Non puoi modificare il programma.")
    try:
        programma_pk = int(request.POST.get("programma", ""))
        ids = {int(v) for v in request.POST.getlist("processi")}
    except (ValueError, TypeError):
        messages.error(request, "Seleziona un programma in bozza e i processi da pianificare.")
        return redirect("sistema_gestione:audit_priorita")
    programma = get_object_or_404(ProgrammaAudit.objects.select_for_update(), pk=programma_pk, stato=ProgrammaAudit.STATO_BOZZA)
    proposte = service.priorita_processi(Processo.objects.filter(attivo=True, pk__in=ids))
    inserite = 0
    for proposta in proposte:
        processo = proposta["processo"]
        data = proposta["data_proposta"]
        if data.year != programma.anno or proposta["programmato"]:
            continue
        # Riapplicare una proposta non duplica righe e non riscrive la pianificazione manuale.
        if programma.righe.filter(processo=processo).exists():
            continue
        riga = RigaProgramma.objects.create(programma=programma, processo=processo,
            area=f"{processo} (Rev.{processo.revisione})"[:255], enti=processo.enti,
            punti_9100=processo.punti_9100, punti_45001=processo.punti_45001,
            punti_27001=processo.punti_27001, punti_pdr125=processo.punti_pdr125,
            altre_normative=processo.procedure[:500], note="Proposta priorita-v1: " + "; ".join(proposta["motivi"]))
        CellaProgramma.objects.create(riga=riga, mese=data.month, stato=CellaProgramma.STATO_PR)
        inserite += 1
    log_action(request, "audit_priorita_applicata", MODULE, {"righe": inserite, "algoritmo": "priorita-v1"}, oggetto=programma)
    messages.info(request, f"{inserite} righe aggiunte. Saltati processi gia pianificati, gia presenti o con proposta fuori dall'anno selezionato.")
    return redirect("sistema_gestione:programma_dettaglio", pk=programma.pk)


@login_required
@require_POST
@transaction.atomic
def revisiona_rapporto(request, pk):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _nega(request, "La revisione di un rapporto firmato richiede un approvatore.")
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    if not audit.rapporto_firmato_auditor_il or not motivo or len(motivo) > 500:
        messages.error(request, "Serve un rapporto firmato e un motivo di revisione (massimo 500 caratteri).")
        return redirect(_audit_url(audit, "rapporto"))
    from .audit_exports import rapporto_audit_pdf
    numero = (audit.versioni_rapporto.aggregate(n=Max("numero"))["n"] or 0) + 1
    versione = AuditRapportoVersione(audit=audit, numero=numero, motivo=motivo, autore=request.user,
        copia_firmata=audit.copia_firmata_rapporto.name,
        snapshot={"riepilogo": audit.riepilogo_generato, "giudizio": audit.giudizio, "punti_forza": audit.punti_forza,
            "valutazione_rdd": audit.valutazione_rdd, "car_autorizzate": audit.car_autorizzate,
            "firma_auditor": str(audit.rapporto_firmato_auditor_il), "auditor_id": audit.rapporto_firmato_auditor_da_id,
            "convalida_ente": str(audit.rapporto_convalidato_ente_il), "ente_id": audit.rapporto_convalidato_ente_da_id,
            "valutazione_il": str(audit.rapporto_valutato_rdd_il), "rdd_id": audit.rapporto_valutato_rdd_da_id})
    versione.pdf.save(uuid4().hex + ".pdf", ContentFile(rapporto_audit_pdf(audit)), save=False)
    try:
        versione.save()
    except Exception:
        versione.pdf.delete(save=False)
        raise
    audit.stato = Audit.STATO_IN_CORSO
    for campo in ["rapporto_firmato_auditor", "rapporto_convalidato_ente", "rapporto_valutato_rdd"]:
        setattr(audit, campo + "_da", None)
        setattr(audit, campo + "_il", None)
    audit.copia_firmata_rapporto = ""
    audit.copia_firmata_rapporto_nome = ""
    audit.valutazione_rdd = ""
    audit.car_autorizzate = ""
    audit.save()
    log_action(request, "audit_rapporto_revisionato", MODULE, {"versione": numero, "motivo": motivo}, oggetto=audit)
    messages.success(request, "Versione precedente archiviata. La nuova redazione richiede tutte le firme del rapporto.")
    return redirect(_audit_url(audit, "rapporto"))


@login_required
def versione_download(request, pk, versione_pk, tipo):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Non puoi consultare il rapporto.")
    versione = get_object_or_404(AuditRapportoVersione, pk=versione_pk, audit_id=pk)
    if tipo not in {"pdf", "firmata"}:
        raise Http404
    file = versione.pdf if tipo == "pdf" else versione.copia_firmata
    if not file:
        raise Http404
    log_action(request, "audit_versione_scaricata", MODULE, {"versione": versione.numero, "tipo": tipo}, oggetto=versione.audit)
    response = FileResponse(file.open("rb"), as_attachment=True, filename=f"audit-{pk}-versione-{versione.numero}-{tipo}.pdf")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
