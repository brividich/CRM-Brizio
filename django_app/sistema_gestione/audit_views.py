"""Viste fail-closed della Fase 2: audit interni EN 9100."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_APPROVA, PERM_AUDIT_EDIT, PERM_AUDIT_ESEGUI, PERM_AUDIT_VIEW
from .audit_exports import piano_audit_pdf, programma_pdf, rapporto_audit_pdf
from .audit_forms import (
    AuditAgendaForm,
    AuditDomandaAggiuntivaForm,
    AuditEsitoForm,
    AuditForm,
    AuditPersonaForm,
    AuditRapportoForm,
    AuditorForm,
    ComunicazioneAuditForm,
    ProgrammaAuditForm,
    RigaProgrammaForm,
    ValutazioneRddForm,
)
from .forms import CopiaFirmataForm
from .models import (
    Audit,
    AuditAgenda,
    AuditEsito,
    AuditPersona,
    Auditor,
    CellaProgramma,
    ProgrammaAudit,
    RigaProgramma,
)
from .services import audit as service
from .views import MODULE, _has_perm, _nega


def _deny(request):
    return _nega(request, "Non hai i permessi richiesti per gli audit interni.")


def _assigned_executor(request, audit: Audit) -> bool:
    return _has_perm(request, PERM_AUDIT_ESEGUI) and (
        request.user.is_superuser or audit.utente_e_auditor(request.user)
    )


def _audit_url(audit: Audit, anchor: str = "") -> str:
    url = reverse("sistema_gestione:audit_dettaglio", kwargs={"pk": audit.pk})
    return f"{url}#{anchor}" if anchor else url


@login_required
def audit_index(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    oggi = timezone.localdate()
    anno = int(request.GET.get("anno") or oggi.year)
    programmi = ProgrammaAudit.objects.filter(anno=anno).order_by("-revisione")
    audit = Audit.objects.filter(data_inizio__year=anno).select_related("lead_auditor", "programma")
    return render(request, "sistema_gestione/pages/audit_index.html", {
        "page_title": "Audit interni",
        "anno": anno,
        "programmi": programmi,
        "audit_list": audit,
        "auditor_attivi": Auditor.objects.filter(attivo=True).count(),
        "audit_chiusi": audit.filter(stato=Audit.STATO_CHIUSO).count(),
        "audit_programmati": audit.exclude(stato=Audit.STATO_ANNULLATO).count(),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
        "puo_eseguire": _has_perm(request, PERM_AUDIT_ESEGUI),
        "puo_approvare": _has_perm(request, PERM_AUDIT_APPROVA),
    })


# ---------------------------------------------------------------------------
# Auditor
# ---------------------------------------------------------------------------

@login_required
def auditor_elenco(request):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    return render(request, "sistema_gestione/pages/auditor_elenco.html", {
        "page_title": "Auditor",
        "auditor_list": Auditor.objects.select_related("user", "approvato_ceo_da"),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
        "puo_approvare": _has_perm(request, PERM_AUDIT_APPROVA),
    })


@login_required
def auditor_modifica(request, pk: int | None = None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    auditor = get_object_or_404(Auditor, pk=pk) if pk else Auditor()
    form = AuditorForm(request.POST or None, instance=auditor)
    if request.method == "POST" and form.is_valid():
        auditor = form.save()
        log_action(request, "auditor_salvato", MODULE, {"auditor": auditor.nome}, oggetto=auditor)
        messages.success(request, "Auditor salvato.")
        return redirect("sistema_gestione:auditor_elenco")
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Nuovo auditor" if not pk else f"Auditor - {auditor.nome}",
        "form": form,
        "indietro": reverse("sistema_gestione:auditor_elenco"),
    })


@login_required
@require_POST
def auditor_approva_esterno(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _deny(request)
    auditor = get_object_or_404(Auditor, pk=pk, interno=False)
    auditor.approvato_ceo_da = request.user
    auditor.approvato_ceo_il = timezone.now()
    auditor.save(update_fields=["approvato_ceo_da", "approvato_ceo_il", "updated_at"])
    log_action(request, "auditor_esterno_approvato", MODULE, {"auditor": auditor.nome}, oggetto=auditor)
    messages.success(request, "Auditor esterno approvato dalla Direzione.")
    return redirect("sistema_gestione:auditor_elenco")


# ---------------------------------------------------------------------------
# Programma MOD.034
# ---------------------------------------------------------------------------

@login_required
def programma_nuovo(request):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    form = ProgrammaAuditForm(request.POST or None, initial={
        "anno": timezone.localdate().year,
        "esclusioni_27002": service.esclusioni_soa_in_vigore(),
    })
    if request.method == "POST" and form.is_valid():
        try:
            programma = service.nuovo_programma(anno=form.cleaned_data["anno"], utente=request.user)
        except service.TransizioneNonAmmessa as exc:
            form.add_error("anno", str(exc))
        else:
            programma.rif_riesame = form.cleaned_data["rif_riesame"]
            programma.periodi = form.cleaned_data["periodi"]
            programma.esclusioni_27002 = form.cleaned_data["esclusioni_27002"]
            programma.save()
            log_action(request, "programma_audit_creato", MODULE, {"anno": programma.anno}, oggetto=programma)
            return redirect("sistema_gestione:programma_dettaglio", pk=programma.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Nuovo programma audit (MOD.034)", "form": form,
        "indietro": reverse("sistema_gestione:audit_index"),
    })


@login_required
def programma_dettaglio(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    programma = get_object_or_404(
        ProgrammaAudit.objects.select_related(
            "preparato_da", "proposto_da", "approvato_da", "convalidato_da",
        ), pk=pk,
    )
    if request.method == "POST":
        if not _has_perm(request, PERM_AUDIT_EDIT) or not programma.modificabile:
            return _deny(request)
        form = ProgrammaAuditForm(request.POST, instance=programma)
        if form.is_valid():
            form.save()
            log_action(request, "programma_audit_modificato", MODULE, {"campi": form.changed_data}, oggetto=programma)
            messages.success(request, "Programma aggiornato.")
            return redirect("sistema_gestione:programma_dettaglio", pk=pk)
    else:
        form = ProgrammaAuditForm(instance=programma)
    celle = {
        (c.riga_id, c.mese): c
        for c in CellaProgramma.objects.filter(riga__programma=programma).select_related("audit")
    }
    righe = []
    for riga in programma.righe.all():
        righe.append({"riga": riga, "mesi": [celle.get((riga.pk, mese)) for mese in range(1, 13)]})
    return render(request, "sistema_gestione/pages/programma_dettaglio.html", {
        "page_title": str(programma), "programma": programma, "righe": righe, "mesi": range(1, 13),
        "form": form, "form_firmata": CopiaFirmataForm(),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT) and programma.modificabile,
        "puo_gestire": _has_perm(request, PERM_AUDIT_EDIT),
        "puo_approvare": _has_perm(request, PERM_AUDIT_APPROVA),
    })


@login_required
def programma_riga(request, programma_pk: int, pk: int | None = None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=programma_pk, stato=ProgrammaAudit.STATO_BOZZA)
    riga = get_object_or_404(RigaProgramma, pk=pk, programma=programma) if pk else RigaProgramma(programma=programma)
    form = RigaProgrammaForm(request.POST or None, instance=riga)
    if request.method == "POST" and form.is_valid():
        riga = form.save(commit=False)
        riga.programma = programma
        riga.save()
        log_action(request, "programma_riga_salvata", MODULE, {"area": riga.area}, oggetto=programma)
        return redirect("sistema_gestione:programma_dettaglio", pk=programma.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Riga del programma", "form": form,
        "indietro": reverse("sistema_gestione:programma_dettaglio", kwargs={"pk": programma.pk}),
    })


@login_required
@require_POST
def programma_cella(request, riga_pk: int, mese: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    riga = get_object_or_404(RigaProgramma.objects.select_related("programma"), pk=riga_pk)
    if not riga.programma.modificabile or mese not in range(1, 13):
        return _deny(request)
    stato = (request.POST.get("stato") or "").upper()
    if not stato:
        CellaProgramma.objects.filter(riga=riga, mese=mese, audit__isnull=True).delete()
    elif stato in dict(CellaProgramma.STATO_CHOICES):
        CellaProgramma.objects.update_or_create(riga=riga, mese=mese, defaults={"stato": stato})
    else:
        messages.error(request, "Stato cella non valido.")
    log_action(request, "programma_cella_modificata", MODULE, {"riga": riga.pk, "mese": mese, "stato": stato}, oggetto=riga.programma)
    return redirect("sistema_gestione:programma_dettaglio", pk=riga.programma_id)


def _programma_transizione(request, pk: int, azione, evento: str, messaggio: str):
    if not _has_perm(request, PERM_AUDIT_APPROVA if evento in {"programma_approvato", "programma_convalidato"} else PERM_AUDIT_EDIT):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=pk)
    try:
        azione(programma)
    except service.TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, evento, MODULE, {"stato": programma.stato}, oggetto=programma)
        messages.success(request, messaggio)
    return redirect("sistema_gestione:programma_dettaglio", pk=pk)


@login_required
@require_POST
def programma_proponi(request, pk: int):
    return _programma_transizione(
        request, pk, lambda p: service.proponi_programma(p, utente=request.user),
        "programma_proposto", "Programma proposto alla Direzione.",
    )


@login_required
@require_POST
def programma_approva(request, pk: int):
    return _programma_transizione(
        request, pk, lambda p: service.approva_programma(p, utente=request.user),
        "programma_approvato", "Approvazione della Direzione registrata.",
    )


@login_required
@require_POST
def programma_convalida(request, pk: int):
    return _programma_transizione(
        request, pk, lambda p: service.convalida_programma(p, utente=request.user),
        "programma_convalidato", "Programma convalidato e in vigore.",
    )


@login_required
@require_POST
def programma_nuova_revisione(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=pk)
    try:
        nuova = service.nuova_revisione_programma(
            programma, motivo=request.POST.get("motivo", ""), utente=request.user,
        )
    except service.TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
        return redirect("sistema_gestione:programma_dettaglio", pk=pk)
    log_action(request, "programma_revisionato", MODULE, {"da": pk, "motivo": nuova.motivo_revisione}, oggetto=nuova)
    return redirect("sistema_gestione:programma_dettaglio", pk=nuova.pk)


@login_required
def programma_export_pdf(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=pk)
    log_action(request, "programma_pdf", MODULE, {"anno": programma.anno, "revisione": programma.revisione}, oggetto=programma)
    response = HttpResponse(programma_pdf(programma), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="MOD034_{programma.anno}_Rev{programma.revisione}.pdf"'
    return response


@login_required
@require_POST
def programma_carica_firmata(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=pk)
    form = CopiaFirmataForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(form.errors.get("file", ["File non valido."])))
    else:
        file = form.cleaned_data["file"]
        programma.copia_firmata.save(f"MOD034_{programma.anno}_Rev{programma.revisione}_firmato.pdf", file, save=False)
        programma.copia_firmata_nome = Path(file.name).name[:255]
        programma.copia_firmata_caricata_il = timezone.now()
        programma.save()
        log_action(request, "programma_copia_firmata", MODULE, {}, oggetto=programma)
        messages.success(request, "Copia firmata caricata.")
    return redirect("sistema_gestione:programma_dettaglio", pk=pk)


@login_required
def programma_copia_firmata(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    programma = get_object_or_404(ProgrammaAudit, pk=pk)
    if not programma.copia_firmata:
        raise Http404
    return FileResponse(programma.copia_firmata.open("rb"), content_type="application/pdf", as_attachment=True,
                        filename=f"MOD034_{programma.anno}_Rev{programma.revisione}_firmato.pdf")


# ---------------------------------------------------------------------------
# Piano, esecuzione e rapporto del singolo audit
# ---------------------------------------------------------------------------

def _initial_da_cella(cella: CellaProgramma) -> dict:
    riga, anno = cella.riga, cella.riga.programma.anno
    giorno = date(anno, cella.mese, 15)
    return {
        "programma": riga.programma,
        "righe": [riga],
        "en9100": bool(riga.punti_9100), "iso45001": bool(riga.punti_45001),
        "iso27001": bool(riga.punti_27001), "pdr125": bool(riga.punti_pdr125),
        "processi": riga.area + (f" - {riga.enti}" if riga.enti else ""),
        "punti_norma": "; ".join(filter(None, [riga.punti_9100, riga.punti_45001, riga.punti_27001, riga.punti_pdr125])),
        "procedure_criteri": riga.altre_normative,
        "data_inizio": giorno,
    }


@login_required
def audit_modifica(request, pk: int | None = None):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk) if pk else Audit(created_by=request.user)
    if pk and audit.stato != Audit.STATO_PIANIFICATO:
        messages.error(request, "Il piano non è più modificabile.")
        return redirect("sistema_gestione:audit_dettaglio", pk=pk)
    cella = None
    if not pk and request.GET.get("cella"):
        cella = get_object_or_404(CellaProgramma.objects.select_related("riga__programma"), pk=request.GET["cella"])
    initial = _initial_da_cella(cella) if cella else None
    form = AuditForm(request.POST or None, instance=audit, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            audit = form.save(commit=False)
            if not audit.numero:
                audit.numero = service.prossimo_numero_audit(audit.data_inizio.year)
            audit.created_by = audit.created_by or request.user
            audit.save()
            form.save_m2m()
            service.prepara_nuovo_audit(audit, cella=cella)
        conflitti = service.conflitti_imparzialita(
            processi=audit.processi, lead=audit.lead_auditor, auditor=audit.auditor.all(),
        )
        if conflitti and audit.imparzialita_deroga_motivo:
            log_action(request, "audit_deroga_imparzialita", MODULE, {
                "conflitti": conflitti, "motivo": audit.imparzialita_deroga_motivo,
            }, oggetto=audit)
        non_qualificati = service.auditor_non_qualificati(
            lead=audit.lead_auditor, auditor=audit.auditor.all(),
        )
        if non_qualificati:
            messages.warning(request, "Auditor non ancora qualificati: " + ", ".join(non_qualificati))
        log_action(request, "audit_salvato", MODULE, {"numero": audit.numero}, oggetto=audit)
        messages.success(request, "Piano di audit salvato.")
        return redirect("sistema_gestione:audit_dettaglio", pk=audit.pk)
    return render(request, "sistema_gestione/pages/audit_form.html", {
        "page_title": "Nuovo audit" if not pk else f"Modifica {audit.numero}",
        "form": form, "indietro": reverse("sistema_gestione:audit_index"),
    })


@login_required
def audit_dettaglio(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(
        Audit.objects.select_related("programma", "lead_auditor__user").prefetch_related(
            "auditor__user", "persone", "agenda", "esiti__domanda__sezione", "car_sezioni__sezione",
        ), pk=pk,
    )
    gruppi = []
    by_section = {}
    for esito in audit.esiti.all():
        sezione = esito.sezione_effettiva
        if sezione:
            by_section.setdefault(sezione, []).append(esito)
    car = {c.sezione_id: c for c in audit.car_sezioni.all()}
    for sezione in sorted(by_section, key=lambda s: (s.ordine, s.pk)):
        gruppi.append({"sezione": sezione, "esiti": by_section[sezione], "car": car.get(sezione.pk)})
    return render(request, "sistema_gestione/pages/audit_dettaglio.html", {
        "page_title": f"Audit {audit.numero}", "audit": audit, "gruppi": gruppi,
        "contatori": service.contatori_rilievi(audit),
        "form_persona": AuditPersonaForm(), "form_agenda": AuditAgendaForm(),
        "form_comunicazione": ComunicazioneAuditForm(initial={"metodo": Audit.COM_EMAIL}),
        "form_rapporto": AuditRapportoForm(instance=audit),
        "form_domanda": AuditDomandaAggiuntivaForm(audit=audit),
        "form_valutazione": ValutazioneRddForm(instance=audit),
        "form_firmata": CopiaFirmataForm(),
        "puo_modificare": _has_perm(request, PERM_AUDIT_EDIT),
        "puo_eseguire": _assigned_executor(request, audit),
        "puo_approvare": _has_perm(request, PERM_AUDIT_APPROVA),
    })


@login_required
@require_POST
def audit_persona_salva(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk, stato=Audit.STATO_PIANIFICATO)
    form = AuditPersonaForm(request.POST)
    if form.is_valid():
        persona = form.save(commit=False)
        persona.audit = audit
        persona.save()
        log_action(request, "audit_persona_aggiunta", MODULE, {"ruolo": persona.ruolo}, oggetto=audit)
    else:
        messages.error(request, "Persona non valida: " + " ".join(sum(form.errors.values(), [])))
    return redirect(_audit_url(audit, "persone"))


@login_required
@require_POST
def audit_agenda_salva(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk, stato=Audit.STATO_PIANIFICATO)
    form = AuditAgendaForm(request.POST)
    if form.is_valid():
        voce = form.save(commit=False)
        voce.audit = audit
        voce.save()
    else:
        messages.error(request, "Voce agenda non valida.")
    return redirect(_audit_url(audit, "agenda"))


@login_required
@require_POST
def audit_approva_lead(request, pk: int):
    audit = get_object_or_404(Audit.objects.select_related("lead_auditor"), pk=pk)
    if not _assigned_executor(request, audit) or (
        not request.user.is_superuser and audit.lead_auditor.user_id != request.user.id
    ):
        return _deny(request)
    if audit.stato != Audit.STATO_PIANIFICATO:
        messages.error(request, "Stato non compatibile con l'approvazione del piano.")
    else:
        audit.piano_approvato_lead_da = request.user
        audit.piano_approvato_lead_il = timezone.now()
        audit.save(update_fields=["piano_approvato_lead_da", "piano_approvato_lead_il", "updated_at"])
        log_action(request, "audit_piano_approvato_lead", MODULE, {}, oggetto=audit)
    return redirect(_audit_url(audit, "approvazioni"))


@login_required
@require_POST
def audit_approva_direzione(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk)
    if audit.stato != Audit.STATO_PIANIFICATO or not audit.piano_approvato_lead_il:
        messages.error(request, "Serve prima l'approvazione del Lead Auditor.")
    else:
        audit.piano_approvato_direzione_da = request.user
        audit.piano_approvato_direzione_il = timezone.now()
        audit.stato = Audit.STATO_PIANO_APPROVATO
        audit.save(update_fields=[
            "piano_approvato_direzione_da", "piano_approvato_direzione_il", "stato", "updated_at",
        ])
        log_action(request, "audit_piano_approvato_direzione", MODULE, {}, oggetto=audit)
    return redirect(_audit_url(audit, "approvazioni"))


@login_required
@require_POST
def audit_comunica(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk)
    form = ComunicazioneAuditForm(request.POST)
    if form.is_valid():
        try:
            service.comunica_audit(
                audit, metodo=form.cleaned_data["metodo"], deroga_motivo=form.cleaned_data["deroga_motivo"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            if audit.preavviso_deroga_motivo:
                log_action(request, "audit_deroga_preavviso", MODULE, {
                    "motivo": audit.preavviso_deroga_motivo,
                }, oggetto=audit)
            log_action(request, "audit_comunicato", MODULE, {"metodo": form.cleaned_data["metodo"]}, oggetto=audit)
            messages.success(request, "Piano comunicato agli auditati.")
    return redirect(_audit_url(audit, "comunicazione"))


@login_required
@require_POST
def audit_avvia(request, pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit):
        return _deny(request)
    if audit.stato != Audit.STATO_PIANO_APPROVATO:
        messages.error(request, "Il piano deve essere approvato dalla Direzione.")
    else:
        audit.stato = Audit.STATO_IN_CORSO
        audit.save(update_fields=["stato", "updated_at"])
        service.inizializza_checklist(audit)
        log_action(request, "audit_avviato", MODULE, {}, oggetto=audit)
    return redirect(_audit_url(audit, "checklist"))


@login_required
@require_POST
def audit_esito_salva(request, pk: int, esito_pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit) or audit.stato not in {Audit.STATO_IN_CORSO, Audit.STATO_RAPPORTO}:
        return _deny(request)
    esito = get_object_or_404(AuditEsito, pk=esito_pk, audit=audit)
    form = AuditEsitoForm(request.POST, instance=esito)
    if form.is_valid():
        service.salva_esito(form.save(commit=False), utente=request.user)
        log_action(request, "audit_esito_salvato", MODULE, {"esito": esito.esito, "punti": esito.punti}, oggetto=audit)
        messages.success(request, "Esito salvato.")
    else:
        messages.error(request, "Esito non valido: " + " ".join(sum(form.errors.values(), [])))
    return redirect(_audit_url(audit, f"esito-{esito.pk}"))


@login_required
@require_POST
def audit_domanda_aggiuntiva(request, pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit) or audit.stato != Audit.STATO_IN_CORSO:
        return _deny(request)
    form = AuditDomandaAggiuntivaForm(request.POST, audit=audit)
    if form.is_valid():
        esito = form.save(commit=False)
        esito.audit = audit
        service.salva_esito(esito, utente=request.user)
        messages.success(request, "Domanda aggiuntiva registrata.")
    else:
        messages.error(request, "Domanda aggiuntiva non valida.")
    return redirect(_audit_url(audit, "checklist"))


@login_required
@require_POST
def audit_car_sezione(request, pk: int, car_pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit):
        return _deny(request)
    car = get_object_or_404(audit.car_sezioni, pk=car_pk)
    car.car_aperta = request.POST.get("car_aperta") == "1"
    car.save(update_fields=["car_aperta"])
    log_action(request, "audit_car_sezione", MODULE, {"sezione": car.sezione.codice, "aperta": car.car_aperta}, oggetto=audit)
    return redirect(_audit_url(audit, "checklist"))


@login_required
@require_POST
def audit_rapporto_salva(request, pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit) or audit.stato not in {Audit.STATO_IN_CORSO, Audit.STATO_RAPPORTO}:
        return _deny(request)
    form = AuditRapportoForm(request.POST, instance=audit)
    if form.is_valid():
        audit = form.save(commit=False)
        audit.stato = Audit.STATO_RAPPORTO
        audit.save()
        log_action(request, "audit_rapporto_preparato", MODULE, {}, oggetto=audit)
        messages.success(request, "Rapporto salvato e inviato alla firma.")
    return redirect(_audit_url(audit, "rapporto"))


@login_required
@require_POST
def audit_firma_rapporto(request, pk: int):
    audit = get_object_or_404(Audit, pk=pk)
    if not _assigned_executor(request, audit) or audit.stato != Audit.STATO_RAPPORTO:
        return _deny(request)
    audit.rapporto_firmato_auditor_da = request.user
    audit.rapporto_firmato_auditor_il = timezone.now()
    audit.save(update_fields=["rapporto_firmato_auditor_da", "rapporto_firmato_auditor_il", "updated_at"])
    log_action(request, "audit_rapporto_firmato", MODULE, {}, oggetto=audit)
    return redirect(_audit_url(audit, "rapporto"))


@login_required
@require_POST
def audit_convalida_ente(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk, stato=Audit.STATO_RAPPORTO)
    if not audit.rapporto_firmato_auditor_il:
        messages.error(request, "Serve prima la firma dell'auditor.")
    else:
        audit.rapporto_convalidato_ente_da = request.user
        audit.rapporto_convalidato_ente_il = timezone.now()
        audit.save(update_fields=["rapporto_convalidato_ente_da", "rapporto_convalidato_ente_il", "updated_at"])
        log_action(request, "audit_rapporto_convalidato_ente", MODULE, {}, oggetto=audit)
    return redirect(_audit_url(audit, "rapporto"))


@login_required
@require_POST
def audit_valuta_rdd(request, pk: int):
    if not _has_perm(request, PERM_AUDIT_APPROVA):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk, stato=Audit.STATO_RAPPORTO)
    if not audit.rapporto_firmato_auditor_il or not audit.rapporto_convalidato_ente_il:
        messages.error(request, "Servono firma dell'auditor e convalida del responsabile dell'ente.")
        return redirect(_audit_url(audit, "rapporto"))
    form = ValutazioneRddForm(request.POST, instance=audit)
    if form.is_valid():
        audit = form.save(commit=False)
        audit.rapporto_valutato_rdd_da = request.user
        audit.rapporto_valutato_rdd_il = timezone.now()
        audit.stato = Audit.STATO_CHIUSO
        audit.save()
        service.distribuisci_rapporto(audit)
        log_action(request, "audit_chiuso", MODULE, {}, oggetto=audit)
        messages.success(request, "Audit chiuso e rapporto distribuito.")
    return redirect(_audit_url(audit, "rapporto"))


@login_required
def audit_export(request, pk: int, documento: str):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk)
    if documento == "piano":
        body, name = piano_audit_pdf(audit), f"MOD035A_{audit.numero}.pdf"
    elif documento == "rapporto":
        body, name = rapporto_audit_pdf(audit), f"MOD035B_{audit.numero}.pdf"
    else:
        raise Http404
    log_action(request, "audit_pdf", MODULE, {"documento": documento}, oggetto=audit)
    response = HttpResponse(body, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@login_required
@require_POST
def audit_carica_firmata(request, pk: int, documento: str):
    if not _has_perm(request, PERM_AUDIT_EDIT):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk)
    form = CopiaFirmataForm(request.POST, request.FILES)
    if form.is_valid() and documento in {"piano", "rapporto"}:
        file = form.cleaned_data["file"]
        campo = "copia_firmata_piano" if documento == "piano" else "copia_firmata_rapporto"
        nome_campo = campo + "_nome"
        getattr(audit, campo).save(f"{documento}_{audit.numero}_firmato.pdf", file, save=False)
        setattr(audit, nome_campo, Path(file.name).name[:255])
        audit.save(update_fields=[campo, nome_campo, "updated_at"])
        log_action(request, "audit_copia_firmata", MODULE, {"documento": documento}, oggetto=audit)
        messages.success(request, "Copia firmata caricata.")
    else:
        messages.error(request, "File non valido.")
    return redirect(_audit_url(audit, "documenti"))


@login_required
def audit_copia_firmata(request, pk: int, documento: str):
    if not _has_perm(request, PERM_AUDIT_VIEW):
        return _deny(request)
    audit = get_object_or_404(Audit, pk=pk)
    campo = {"piano": "copia_firmata_piano", "rapporto": "copia_firmata_rapporto"}.get(documento)
    if not campo or not getattr(audit, campo):
        raise Http404
    return FileResponse(getattr(audit, campo).open("rb"), content_type="application/pdf", as_attachment=True,
                        filename=f"{documento}_{audit.numero}_firmato.pdf")
