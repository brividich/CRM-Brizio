from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from core.audit import log_action
from gestione_specifiche.models import RegistroOFI
from .models import Audit, AuditPreparazione, AzioneCorrettivaAudit, RilevazioneKpi, AuditEsito, AuditVerificaEfficacia
from .procedure_forms import PreparazioneForm, CarForm, ProrogaForm, KpiForm
from .services.procedure import problemi_chiusura_car, risultato_kpi
from .audit_views import _assigned_executor
from .acl_bootstrap import PERM_AUDIT_VIEW, PERM_AUDIT_EDIT, PERM_AUDIT_APPROVA
from .views import _has_perm, _nega, MODULE


@login_required
@transaction.atomic
def preparazione(request, pk):
    audit = get_object_or_404(Audit.objects.select_for_update(), pk=pk)
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Accesso non consentito.")
    oggetto = AuditPreparazione.objects.filter(audit=audit).first() or AuditPreparazione(audit=audit)
    modificabile = _assigned_executor(request, audit) and audit.stato in [Audit.STATO_PIANIFICATO, Audit.STATO_PIANO_APPROVATO]
    form = PreparazioneForm(request.POST or None, instance=oggetto)
    if request.method == "POST":
        if not modificabile:
            return _nega(request, "Preparazione non modificabile.")
        if form.is_valid():
            p = form.save(commit=False)
            p.verificato_da = request.user
            p.save()
            log_action(request, "audit_preparazione", MODULE, {}, oggetto=audit)
            from .ai_preparazione import registra_esito

            registra_esito(p, user=request.user)
            return redirect("sistema_gestione:audit_dettaglio", pk=pk)
    precedenti = Audit.objects.filter(processi_catalogo__in=audit.processi_catalogo.all(), stato=Audit.STATO_CHIUSO, data_inizio__lt=audit.data_inizio).distinct().order_by("-data_inizio")[:10]
    ai_prep_url = reverse("sistema_gestione:procedura_preparazione_ai", args=[pk]) if modificabile else ""
    return render(request, "sistema_gestione/pages/procedura_form.html", {"page_title": "Preparazione MT CN 12 - " + audit.numero, "form": form, "modificabile": modificabile, "precedenti": precedenti, "indietro": reverse("sistema_gestione:audit_dettaglio", args=[pk]), "ai_prep_url": ai_prep_url})


@login_required
def preparazione_ai(request, pk):
    """Bozza della preparazione dall'AI locale, costruita sugli audit precedenti. Non salva nulla."""
    from django.http import HttpResponse, HttpResponseForbidden

    from .ai_preparazione import proponi_preparazione

    if request.method != "POST":
        return HttpResponse(status=405)
    audit = get_object_or_404(Audit, pk=pk)
    if not (_has_perm(request, PERM_AUDIT_VIEW) and _assigned_executor(request, audit)):
        return HttpResponseForbidden("Preparazione non modificabile.")
    proposta = proponi_preparazione(audit, user=request.user)
    log_action(request, "audit_preparazione_ai", MODULE, {"rilievi": len(proposta["storico"]["rilievi"]), "ai_disponibile": proposta["ai_disponibile"]}, oggetto=audit)
    return render(request, "sistema_gestione/components/_ai_preparazione_esito.html", {"p": proposta})


@login_required
@transaction.atomic
def car(request, pk):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Accesso non consentito.")
    registro = get_object_or_404(RegistroOFI.objects.select_for_update(), pk=pk)
    oggetto = AzioneCorrettivaAudit.objects.filter(registro=registro).first() or AzioneCorrettivaAudit(registro=registro, data_richiesta=timezone.localdate())
    approva = _has_perm(request, PERM_AUDIT_APPROVA)
    modifica = _has_perm(request, PERM_AUDIT_EDIT) or approva or (oggetto.pk and oggetto.responsabile_id == request.user.pk)
    modificabile = modifica and not oggetto.chiusa_il and not registro.is_chiuso
    azione = request.POST.get("azione", "salva")
    form = CarForm(request.POST if request.method == "POST" and azione == "salva" else None, instance=oggetto)
    proroga = ProrogaForm(request.POST if request.method == "POST" and azione == "proroga" else None)
    if request.method == "POST":
        if not modificabile:
            return _nega(request, "CAR non modificabile.")
        if azione != "salva":
            if not approva:
                return _nega(request, "Operazione riservata a RSGQ/Direzione.")
            if request.POST.get("versione") != str(oggetto.versione):
                messages.error(request, "La CAR e cambiata: rileggi i dati aggiornati prima di approvare, prorogare o chiudere.")
                return redirect("sistema_gestione:procedura_car", pk=pk)
        if azione == "salva" and form.is_valid():
            oggetto = form.save(commit=False)
            if set(form.changed_data) & {"responsabile", "causa", "contenimento", "azione", "analizzata_il", "origine_esterna", "approvazione_esterna"}:
                oggetto.approvata_da = None
                oggetto.approvata_il = None
            oggetto.versione += 1
            oggetto.save()
            registro.data_richiesta = oggetto.scadenza_chiusura
            registro.save(update_fields=["data_richiesta", "updated_at"])
            log_action(request, "car_salvata", MODULE, {"versione": oggetto.versione}, oggetto=registro)
            return redirect("sistema_gestione:procedura_car", pk=pk)
        elif azione == "approva" and oggetto.pk:
            if not approva:
                return _nega(request, "Approvazione riservata a RSGQ/Direzione.")
            if not all([oggetto.causa.strip(), oggetto.contenimento.strip(), oggetto.azione.strip(), oggetto.analizzata_il]) or (oggetto.origine_esterna and not oggetto.approvazione_esterna.strip()):
                messages.error(request, "Completa analisi, contenimento, azione, data e l'eventuale approvazione esterna.")
            else:
                oggetto.approvata_da = request.user
                oggetto.approvata_il = timezone.now()
                oggetto.versione += 1
                oggetto.save()
                log_action(request, "car_azione_approvata", MODULE, {}, oggetto=registro)
                return redirect("sistema_gestione:procedura_car", pk=pk)
        elif azione == "proroga" and oggetto.pk:
            if not approva:
                return _nega(request, "La proroga richiede approvazione RSGQ/Direzione.")
            if proroga.is_valid():
                data = proroga.cleaned_data["proroga_al"]
                if data <= max(oggetto.scadenza_chiusura, timezone.localdate()):
                    proroga.add_error("proroga_al", "Indica una data futura successiva alla scadenza attuale.")
                else:
                    precedente = oggetto.scadenza_chiusura.isoformat()
                    oggetto.proroga_al = data
                    oggetto.motivo_proroga = proroga.cleaned_data["motivo"]
                    oggetto.proroga_da = request.user
                    oggetto.proroga_il = timezone.now()
                    oggetto.versione += 1
                    oggetto.save()
                    registro.data_richiesta = data
                    registro.save(update_fields=["data_richiesta", "updated_at"])
                    log_action(request, "car_proroga_approvata", MODULE, {"precedente": precedente, "nuova": data.isoformat(), "motivo": oggetto.motivo_proroga}, oggetto=registro)
                    return redirect("sistema_gestione:procedura_car", pk=pk)
        elif azione == "chiudi" and oggetto.pk:
            if not approva:
                return _nega(request, "La verifica richiede il ruolo RSGQ/Direzione.")
            problemi = problemi_chiusura_car(oggetto, request.user)
            if problemi:
                messages.error(request, " ".join(problemi))
            else:
                oggetto.chiusa_da = request.user
                oggetto.chiusa_il = timezone.now()
                oggetto.versione += 1
                oggetto.save()
                registro.fase = RegistroOFI.FASE_CHIUSO
                registro.data_chiusura = timezone.localdate()
                registro.verifica = oggetto.evidenza_efficacia
                registro.save(update_fields=["fase", "data_chiusura", "verifica", "updated_at"])
                for esito in AuditEsito.objects.filter(ofi=registro):
                    AuditVerificaEfficacia.objects.create(esito=esito, risultato="EFFICACE", metodo="Verifica indipendente CAR MT CN 11", evidenza=oggetto.evidenza_efficacia, data_verifica=timezone.localdate(), verificato_da=request.user)
                log_action(request, "car_efficacia_verificata", MODULE, {}, oggetto=registro)
                return redirect("sistema_gestione:procedura_car", pk=pk)
    return render(request, "sistema_gestione/pages/procedura_form.html", {"page_title": "CAR MT CN 11 - Registro " + str(registro.numero), "form": form, "car": oggetto, "modificabile": modificabile, "approva": approva, "proroga": proroga, "oggi": timezone.localdate(), "indietro": reverse("registro_ofi:dettaglio", args=[pk])})


@login_required
def kpi(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _nega(request, "Accesso non consentito.")
    modificabile = _has_perm(request, PERM_AUDIT_EDIT)
    form = KpiForm(request.POST or None)
    if request.method == "POST":
        if not modificabile:
            return _nega(request, "Non puoi registrare indicatori.")
        if form.is_valid():
            r = form.save(commit=False)
            r.autore = request.user
            r.save()
            log_action(request, "kpi_registrato", MODULE, {"codice": r.codice}, oggetto=r)
            return redirect("sistema_gestione:procedura_kpi")
    rilevazioni = [{"r": r, "risultato": risultato_kpi(r)} for r in RilevazioneKpi.objects.select_related("processo", "autore")[:100]]
    return render(request, "sistema_gestione/pages/procedura_form.html", {"page_title": "Indicatori di processo - MT CN 13", "form": form, "modificabile": modificabile, "rilevazioni": rilevazioni, "indietro": reverse("sistema_gestione:audit_index")})
