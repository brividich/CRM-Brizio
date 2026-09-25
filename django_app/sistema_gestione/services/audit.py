"""Servizi applicativi per MOD.034, MOD.035A e MOD.035B.

Le transizioni sono atomiche, le revisioni approvate restano immutabili e i
rilievi OFI/NC confluiscono una sola volta nel Registro OFI (MOD.174).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from gestione_specifiche.date_utils import festivi_it

from ..models import (
    Audit,
    AuditAgenda,
    AuditEsito,
    AuditPersona,
    AuditSezioneCar,
    Auditor,
    CellaProgramma,
    ChecklistModello,
    ProgrammaAudit,
    RigaProgramma,
    SoaRevisione,
)


class TransizioneNonAmmessa(ValueError):
    pass


def _nome_utente(user) -> str:
    if not user:
        return ""
    return (user.get_full_name() or user.get_username()).strip()


def esclusioni_soa_in_vigore() -> str:
    revisione = SoaRevisione.objects.filter(stato=SoaRevisione.STATO_APPROVATA).order_by("-numero").first()
    if not revisione:
        return ""
    voci = revisione.voci.filter(livello=0).select_related("controllo").order_by("controllo__ordine")
    return "; ".join(f"{v.controllo.codice} {v.controllo.titolo}" for v in voci)


@transaction.atomic
def nuovo_programma(*, anno: int, utente) -> ProgrammaAudit:
    if ProgrammaAudit.objects.filter(anno=anno).exists():
        raise TransizioneNonAmmessa("Per questo anno esiste già un programma: apri una nuova revisione.")
    return ProgrammaAudit.objects.create(
        anno=anno,
        revisione=0,
        preparato_da=utente,
        esclusioni_27002=esclusioni_soa_in_vigore(),
    )


@transaction.atomic
def nuova_revisione_programma(programma: ProgrammaAudit, *, motivo: str, utente) -> ProgrammaAudit:
    motivo = (motivo or "").strip()
    if not motivo:
        raise TransizioneNonAmmessa("Il motivo della riprogrammazione è obbligatorio.")
    if programma.stato != ProgrammaAudit.STATO_APPROVATO:
        raise TransizioneNonAmmessa("Si può revisionare solo un programma approvato.")
    if ProgrammaAudit.objects.filter(anno=programma.anno, stato__in=[
        ProgrammaAudit.STATO_BOZZA, ProgrammaAudit.STATO_PROPOSTA,
    ]).exists():
        raise TransizioneNonAmmessa("Esiste già una revisione di lavoro per questo anno.")
    nuova = ProgrammaAudit.objects.create(
        anno=programma.anno,
        revisione=programma.revisione + 1,
        stato=ProgrammaAudit.STATO_BOZZA,
        motivo_revisione=motivo,
        rif_riesame=programma.rif_riesame,
        periodi=programma.periodi,
        esclusioni_27002=programma.esclusioni_27002,
        preparato_da=utente,
    )
    mappa: dict[int, RigaProgramma] = {}
    for riga in programma.righe.order_by("ordine", "id"):
        copia = RigaProgramma.objects.create(
            programma=nuova,
            ordine=riga.ordine,
            area=riga.area,
            enti=riga.enti,
            punti_9100=riga.punti_9100,
            punti_45001=riga.punti_45001,
            punti_27001=riga.punti_27001,
            punti_pdr125=riga.punti_pdr125,
            altre_normative=riga.altre_normative,
            note=riga.note,
        )
        mappa[riga.pk] = copia
    CellaProgramma.objects.bulk_create([
        CellaProgramma(riga=mappa[cella.riga_id], mese=cella.mese, stato=cella.stato)
        for cella in CellaProgramma.objects.filter(riga__programma=programma).select_related("riga")
    ])
    return nuova


@transaction.atomic
def proponi_programma(programma: ProgrammaAudit, *, utente) -> None:
    if programma.stato != ProgrammaAudit.STATO_BOZZA:
        raise TransizioneNonAmmessa("Solo una bozza può essere proposta.")
    if not programma.righe.exists():
        raise TransizioneNonAmmessa("Aggiungi almeno una riga al programma.")
    programma.stato = ProgrammaAudit.STATO_PROPOSTA
    programma.proposto_da = utente
    programma.proposto_il = timezone.now()
    programma.save(update_fields=["stato", "proposto_da", "proposto_il", "updated_at"])


@transaction.atomic
def approva_programma(programma: ProgrammaAudit, *, utente) -> None:
    if programma.stato != ProgrammaAudit.STATO_PROPOSTA:
        raise TransizioneNonAmmessa("Il programma non è in attesa di approvazione.")
    programma.approvato_da = utente
    programma.approvato_il = timezone.now()
    programma.save(update_fields=["approvato_da", "approvato_il", "updated_at"])


@transaction.atomic
def convalida_programma(programma: ProgrammaAudit, *, utente) -> None:
    if programma.stato != ProgrammaAudit.STATO_PROPOSTA or not programma.approvato_il:
        raise TransizioneNonAmmessa("È necessaria prima l'approvazione della Direzione.")
    ProgrammaAudit.objects.filter(
        anno=programma.anno, stato=ProgrammaAudit.STATO_APPROVATO,
    ).exclude(pk=programma.pk).update(stato=ProgrammaAudit.STATO_SUPERATO)
    programma.stato = ProgrammaAudit.STATO_APPROVATO
    programma.convalidato_da = utente
    programma.convalidato_il = timezone.now()
    programma.save(update_fields=["stato", "convalidato_da", "convalidato_il", "updated_at"])


def prossimo_numero_audit(anno: int) -> str:
    prefisso = f"RAIS-{anno}-"
    ultimo = (
        Audit.objects.filter(numero__startswith=prefisso)
        .order_by("-numero").values_list("numero", flat=True).first()
    )
    progressivo = 1
    if ultimo:
        match = re.search(r"(\d+)$", ultimo)
        if match:
            progressivo = int(match.group(1)) + 1
    return f"{prefisso}{progressivo:02d}"


def _datetime_locale(data, ora: time):
    valore = datetime.combine(data, ora)
    return timezone.make_aware(valore) if timezone.is_naive(valore) else valore


@transaction.atomic
def prepara_nuovo_audit(audit: Audit, *, cella: CellaProgramma | None = None) -> Audit:
    """Salva l'audit, collega la cella e genera apertura/chiusura e checklist."""
    if not audit.numero:
        audit.numero = prossimo_numero_audit(audit.data_inizio.year)
    audit.full_clean(exclude=["righe"])
    audit.save()
    if cella:
        audit.programma = cella.riga.programma
        audit.save(update_fields=["programma", "updated_at"])
        audit.righe.add(cella.riga)
        cella.audit = audit
        cella.save(update_fields=["audit"])
    AuditAgenda.objects.get_or_create(
        audit=audit,
        processo_area="Riunione di apertura",
        defaults={
            "quando": _datetime_locale(audit.data_inizio, time(9, 0)),
            "attivita": "Presentazione obiettivi, campo, metodi, agenda",
            "auditor": audit.lead_auditor.nome,
            "ordine": 10,
        },
    )
    giorno_fine = audit.data_fine or audit.data_inizio
    AuditAgenda.objects.get_or_create(
        audit=audit,
        processo_area="Riunione di chiusura",
        defaults={
            "quando": _datetime_locale(giorno_fine, time(16, 30)),
            "attivita": "Presentazione rilievi, classificazione NC/OFI, prossimi passi",
            "auditor": audit.lead_auditor.nome,
            "ordine": 900,
        },
    )
    inizializza_checklist(audit)
    return audit


def modello_en9100_attivo() -> ChecklistModello | None:
    return ChecklistModello.objects.filter(
        codice=ChecklistModello.CODICE_EN9100_FOLDER_B, attivo=True,
    ).order_by("-revisione").first()


@transaction.atomic
def inizializza_checklist(audit: Audit) -> int:
    if not audit.en9100:
        return 0
    modello = modello_en9100_attivo()
    if not modello:
        return 0
    create = []
    for sezione in modello.sezioni.prefetch_related("domande"):
        AuditSezioneCar.objects.get_or_create(audit=audit, sezione=sezione)
        for domanda in sezione.domande.filter(attiva=True):
            create.append(AuditEsito(audit=audit, domanda=domanda))
    before = audit.esiti.count()
    AuditEsito.objects.bulk_create(create, ignore_conflicts=True)
    return audit.esiti.count() - before


def giorni_lavorativi_di_preavviso(data_comunicazione, data_audit) -> int:
    """Giorni lavorativi interi tra comunicazione e audit, estremi esclusi."""
    if not data_comunicazione or not data_audit or data_audit <= data_comunicazione:
        return 0
    giorno = data_comunicazione + timedelta(days=1)
    totale = 0
    while giorno < data_audit:
        if giorno.weekday() < 5 and giorno not in festivi_it(giorno.year):
            totale += 1
        giorno += timedelta(days=1)
    return totale


def reparto_auditor(auditor: Auditor) -> str:
    """Risoluzione corretta user -> Profile.legacy_user_id -> reparto; mai ID diretti."""
    if not auditor.user_id:
        return ""
    try:
        from core.legacy_models import AnagraficaDipendente
        from core.models import Profile, UserExtraInfo

        profile = Profile.objects.filter(user_id=auditor.user_id).only("legacy_user_id").first()
        if not profile:
            return ""
        extra = UserExtraInfo.objects.filter(legacy_user_id=profile.legacy_user_id).only("reparto").first()
        if extra and extra.reparto.strip():
            return extra.reparto.strip()
        anagrafica = AnagraficaDipendente.objects.filter(
            utente_id=profile.legacy_user_id,
        ).only("reparto").first()
        return (anagrafica.reparto or "").strip() if anagrafica else ""
    except Exception:
        return ""


def conflitti_imparzialita(*, processi: str, lead: Auditor | None, auditor) -> list[str]:
    ambito = " ".join((processi or "").casefold().split())
    conflitti: list[str] = []
    candidati = [a for a in [lead, *list(auditor or [])] if a]
    visti: set[int] = set()
    for persona in candidati:
        if persona.pk in visti:
            continue
        visti.add(persona.pk)
        reparto = " ".join(reparto_auditor(persona).casefold().split())
        if reparto and (reparto in ambito or ambito in reparto):
            conflitti.append(f"{persona.nome} ({reparto_auditor(persona)})")
    return conflitti


def auditor_non_qualificati(*, lead: Auditor | None, auditor) -> list[str]:
    candidati = [a for a in [lead, *list(auditor or [])] if a]
    out, visti = [], set()
    for persona in candidati:
        if persona.pk in visti:
            continue
        visti.add(persona.pk)
        if not persona.qualificato:
            out.append(persona.nome)
    return out


def _prossimo_numero_ofi() -> int:
    from gestione_specifiche.registro_ofi import prossimo_numero

    return prossimo_numero()


@transaction.atomic
def sincronizza_ofi(esito: AuditEsito):
    """Crea una sola voce MOD.174 per gli esiti OFI/NC e la collega."""
    from gestione_specifiche.models import RegistroOFI

    esito = AuditEsito.objects.select_for_update().select_related("audit", "domanda__sezione", "sezione").get(pk=esito.pk)
    if esito.esito not in {AuditEsito.ESITO_OFI, AuditEsito.ESITO_NC}:
        return esito.ofi
    if esito.ofi_id:
        return esito.ofi
    ct = ContentType.objects.get_for_model(AuditEsito)
    esistente = RegistroOFI.objects.filter(content_type=ct, object_id=esito.pk).first()
    if esistente:
        esito.ofi = esistente
        esito.save(update_fields=["ofi", "updated_at"])
        return esistente
    audit = esito.audit
    tipo = RegistroOFI.TIPO_NC if esito.esito == AuditEsito.ESITO_NC else RegistroOFI.TIPO_OFI
    dati = {
        "data_apertura": audit.data_inizio,
        "tipo": tipo,
        "norma_en9100": audit.en9100,
        "norma_iso45001": audit.iso45001,
        "norma_iso27001": audit.iso27001,
        "rif_norma": esito.punti[:200],
        "ref": audit.numero[:100],
        "processo": audit.processi[:200],
        "opportunita": esito.evidenze,
        "modulo_origine": "sistema_gestione",
        "content_type": ct,
        "object_id": esito.pk,
    }
    for _tentativo in range(2):
        try:
            voce = RegistroOFI.objects.create(numero=_prossimo_numero_ofi(), **dati)
            break
        except IntegrityError:
            if _tentativo:
                raise
    esito.ofi = voce
    esito.save(update_fields=["ofi", "updated_at"])
    return voce


@transaction.atomic
def salva_esito(esito: AuditEsito, *, utente):
    esito.aggiornato_da = utente
    esito.full_clean()
    esito.save()
    if esito.esito in {AuditEsito.ESITO_OFI, AuditEsito.ESITO_NC}:
        sincronizza_ofi(esito)
    return esito


def contatori_rilievi(audit: Audit) -> dict[str, int]:
    return {
        "ofi": audit.esiti.filter(esito=AuditEsito.ESITO_OFI).count(),
        "nc": audit.esiti.filter(esito=AuditEsito.ESITO_NC).count(),
        "conformi": audit.esiti.filter(esito=AuditEsito.ESITO_CONFORME).count(),
        "na": audit.esiti.filter(esito=AuditEsito.ESITO_NA).count(),
    }


def _ics(audit: Audit) -> bytes:
    inizio = _datetime_locale(audit.data_inizio, time(9, 0)).astimezone(timezone.utc)
    fine = _datetime_locale(audit.data_fine or audit.data_inizio, time(17, 0)).astimezone(timezone.utc)
    stamp = timezone.now().astimezone(timezone.utc)
    testo = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NOVICROM HUB//Audit//IT", "METHOD:REQUEST",
        "BEGIN:VEVENT", f"UID:audit-{audit.pk}@novicrom-hub", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
        f"DTSTART:{inizio:%Y%m%dT%H%M%SZ}", f"DTEND:{fine:%Y%m%dT%H%M%SZ}",
        f"SUMMARY:Audit {audit.numero}", f"LOCATION:{audit.sede}",
        f"DESCRIPTION:{audit.processi}", "END:VEVENT", "END:VCALENDAR", "",
    ])
    return testo.encode("utf-8")


def comunica_audit(audit: Audit, *, metodo: str, deroga_motivo: str = "") -> int:
    oggi = timezone.localdate()
    preavviso = giorni_lavorativi_di_preavviso(oggi, audit.data_inizio)
    if preavviso < 5 and not (deroga_motivo or "").strip():
        raise ValidationError(
            f"Restano {preavviso} giorni lavorativi: indica il motivo della deroga al preavviso minimo di 5 giorni."
        )
    destinatari = sorted({
        p.email.strip() for p in audit.persone.filter(ruolo=AuditPersona.RUOLO_AUDITATO) if p.email.strip()
    })
    if not destinatari:
        raise ValidationError("Inserisci almeno una persona auditata con indirizzo email.")
    from core.email_utils import send_hub_mail

    allegati = []
    if metodo == Audit.COM_CALENDARIO:
        allegati.append((f"audit-{audit.numero}.ics", _ics(audit), "text/calendar; method=REQUEST"))
    inviati = send_hub_mail(
        subject=f"Piano di audit {audit.numero}",
        body_text=(
            f"È stato pianificato l'audit {audit.numero} per il {audit.data_inizio:%d/%m/%Y}.\n"
            f"Processi/aree: {audit.processi}.\nSede: {audit.sede or 'da definire'}."
        ),
        recipients=destinatari,
        title="Piano di audit",
        email_type="Sistema di gestione",
        attachments=allegati,
    )
    audit.comunicazione_il = timezone.now()
    audit.comunicazione_metodo = metodo
    audit.preavviso_deroga_motivo = (deroga_motivo or "").strip()
    audit.save(update_fields=[
        "comunicazione_il", "comunicazione_metodo", "preavviso_deroga_motivo", "updated_at",
    ])
    return inviati


def distribuisci_rapporto(audit: Audit) -> None:
    destinatari = {
        p.email.strip() for p in audit.persone.filter(
            ruolo__in=[AuditPersona.RUOLO_PROCESSO, AuditPersona.RUOLO_AUDITATO],
        ) if p.email.strip()
    }
    msm = str(os.environ.get("SISTEMA_GESTIONE_AUDIT_EMAIL_MSM", "") or "").strip()
    if msm:
        destinatari.add(msm)
    if not destinatari:
        return
    try:
        from core.email_utils import send_hub_mail

        send_hub_mail(
            subject=f"Rapporto audit {audit.numero} chiuso",
            body_text=(
                f"Il rapporto dell'audit {audit.numero} è stato chiuso e valutato.\n"
                f"OFI: {audit.esiti.filter(esito=AuditEsito.ESITO_OFI).count()} - "
                f"NC: {audit.esiti.filter(esito=AuditEsito.ESITO_NC).count()}."
            ),
            recipients=sorted(destinatari),
            title="Rapporto di audit interno",
            email_type="Sistema di gestione",
            fail_silently=True,
        )
    except Exception:
        return
