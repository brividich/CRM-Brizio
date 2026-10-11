"""Servizi applicativi per MOD.034, MOD.035A e MOD.035B.

Le transizioni sono atomiche, le revisioni approvate restano immutabili e i
rilievi OFI/NC confluiscono una sola volta nel Registro OFI (MOD.174).
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone as dt_timezone

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
            processo=riga.processo,
            ordine=riga.ordine,
            area=riga.area,
            enti=riga.enti,
            punti_9100=riga.punti_9100,
            punti_45001=riga.punti_45001,
            punti_14001=riga.punti_14001,
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
    _verifica_copertura_procedurale(programma)
    programma.stato = ProgrammaAudit.STATO_PROPOSTA
    programma.proposto_da = utente
    programma.proposto_il = timezone.now()
    programma.save(update_fields=["stato", "proposto_da", "proposto_il", "updated_at"])


@transaction.atomic
def approva_programma(programma: ProgrammaAudit, *, utente) -> None:
    if programma.stato != ProgrammaAudit.STATO_PROPOSTA:
        raise TransizioneNonAmmessa("Il programma non è in attesa di approvazione.")
    if programma.proposto_da_id and utente and programma.proposto_da_id == utente.pk:
        raise TransizioneNonAmmessa("L'approvazione deve essere di una persona diversa da chi ha proposto il programma.")
    _verifica_copertura_procedurale(programma)
    programma.approvato_da = utente
    programma.approvato_il = timezone.now()
    programma.save(update_fields=["approvato_da", "approvato_il", "updated_at"])


@transaction.atomic
def rifiuta_programma(programma: ProgrammaAudit, *, motivo: str, utente) -> None:
    """La Direzione respinge la proposta: torna in bozza con il motivo, le firme si azzerano."""
    motivo = (motivo or "").strip()
    if programma.stato != ProgrammaAudit.STATO_PROPOSTA:
        raise TransizioneNonAmmessa("Si può respingere solo un programma proposto.")
    if not motivo:
        raise TransizioneNonAmmessa("Indica il motivo per cui il programma torna in bozza.")
    programma.stato = ProgrammaAudit.STATO_BOZZA
    programma.motivo_rifiuto = motivo[:500]
    programma.proposto_da = programma.approvato_da = None
    programma.proposto_il = programma.approvato_il = None
    programma.save(update_fields=["stato", "motivo_rifiuto", "proposto_da", "proposto_il",
                                  "approvato_da", "approvato_il", "updated_at"])


@transaction.atomic
def convalida_programma(programma: ProgrammaAudit, *, utente) -> None:
    if programma.stato != ProgrammaAudit.STATO_PROPOSTA or not programma.approvato_il:
        raise TransizioneNonAmmessa("È necessaria prima l'approvazione della Direzione.")
    if utente and utente.pk in {programma.approvato_da_id, programma.proposto_da_id}:
        raise TransizioneNonAmmessa("La convalida RDD deve essere di una persona diversa da chi ha proposto e approvato il programma.")
    _verifica_copertura_procedurale(programma)
    ProgrammaAudit.objects.filter(
        anno=programma.anno, stato=ProgrammaAudit.STATO_APPROVATO,
    ).exclude(pk=programma.pk).update(stato=ProgrammaAudit.STATO_SUPERATO)
    programma.stato = ProgrammaAudit.STATO_APPROVATO
    programma.convalidato_da = utente
    programma.convalidato_il = timezone.now()
    programma.save(update_fields=["stato", "convalidato_da", "convalidato_il", "updated_at"])


PREFISSI_NUMERO = {Audit.TIPO_SISTEMA: "RAIS", Audit.TIPO_MANDATORIO_CLIENTE: "RAI", Audit.TIPO_STRAORDINARIO: "STR"}


def prossimo_numero_audit(anno: int, tipo: str = Audit.TIPO_SISTEMA) -> str:
    prefisso = f"{PREFISSI_NUMERO.get(tipo, 'RAIS')}-{anno}-"
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
def prepara_nuovo_audit(audit: Audit, *, cella: CellaProgramma | None = None, nuovo: bool = False) -> Audit:
    """Salva l'audit, collega la cella e genera apertura/chiusura e checklist.

    Su un piano nuovo propone anche i responsabili di processo e un'attività di agenda per
    processo: si correggono in bozza, non sostituiscono la pianificazione del Lead."""
    if not audit.numero:
        audit.numero = prossimo_numero_audit(audit.data_inizio.year, audit.tipo)
    audit.full_clean(exclude=["righe"])
    audit.save()
    if cella:
        audit.programma = cella.riga.programma
        audit.save(update_fields=["programma", "updated_at"])
        audit.righe.add(cella.riga)
        cella.audit = audit
        cella.save(update_fields=["audit"])
    AuditAgenda.objects.update_or_create(
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
    AuditAgenda.objects.update_or_create(
        audit=audit,
        processo_area="Riunione di chiusura",
        defaults={
            "quando": _datetime_locale(giorno_fine, time(16, 30)),
            "attivita": "Presentazione rilievi, classificazione NC/OFI, prossimi passi",
            "auditor": audit.lead_auditor.nome,
            "ordine": 900,
        },
    )
    if nuovo:
        _proponi_persone_e_agenda(audit)
    inizializza_checklist(audit)
    return audit


def _proponi_persone_e_agenda(audit: Audit) -> None:
    processi = list(audit.processi_catalogo.select_related("responsabile"))
    email_presenti = {p.email.strip().lower() for p in audit.persone.all() if p.email}
    for processo in processi:
        resp = processo.responsabile
        email = (getattr(resp, "email", "") or "").strip()
        if resp and email and email.lower() not in email_presenti:
            AuditPersona.objects.create(audit=audit, nome=_nome_utente(resp), email=email, user=resp,
                                        funzione_ente=f"Responsabile {processo.codice}", ruolo=AuditPersona.RUOLO_PROCESSO)
            email_presenti.add(email.lower())
    con_agenda = set(audit.agenda.filter(processo__isnull=False).values_list("processo_id", flat=True))
    giorno, ora = audit.data_inizio, time(10, 0)
    fine_giorno = audit.data_fine or audit.data_inizio
    for ordine, processo in enumerate(processi, start=1):
        if processo.pk in con_agenda:
            continue
        AuditAgenda.objects.create(
            audit=audit, processo=processo, processo_area=f"{processo.codice} - {processo.nome}"[:255],
            quando=_datetime_locale(giorno, ora), auditor=audit.lead_auditor.nome, ordine=100 + ordine,
            attivita="Da completare: campione, documenti e metodo di verifica del processo.",
        )
        # Slot di 90 minuti fino alle 15:00, poi il giorno successivo del piano; nell'ultimo giorno
        # gli slot restanti si accorciano a 30 minuti prima della riunione di chiusura (16:30).
        minuti = ora.hour * 60 + ora.minute + 90
        if minuti > 15 * 60 and giorno < fine_giorno:
            giorno, ora = giorno + timedelta(days=1), time(9, 30)
        elif minuti <= 15 * 60:
            ora = time(minuti // 60, minuti % 60)
        else:
            minuti = min(ora.hour * 60 + ora.minute + 30, 16 * 60)
            ora = time(minuti // 60, minuti % 60)


def genera_domande_followup(audit: Audit) -> int:
    """Domande di follow-up sui rilievi ancora aperti degli audit chiusi sugli stessi processi:
    NC/OFI con CAR non chiusa o ultima verifica di efficacia non positiva (ISO 19011 §6.3.1)."""
    processi = list(audit.processi_catalogo.all())
    if not processi:
        return 0
    gia = {e.domanda_snapshot.get("followup_di") for e in audit.esiti.all() if e.domanda_snapshot.get("followup_di")}
    # Un rilievo già verificato conforme in un follow-up di un audit chiuso non torna più.
    chiusi_conformi = {
        e.domanda_snapshot.get("followup_di") for e in AuditEsito.objects.filter(
            audit__stato=Audit.STATO_CHIUSO, esito__in=[AuditEsito.ESITO_CONFORME, AuditEsito.ESITO_PUNTO_FORZA],
            testo_aggiuntivo__startswith="Follow-up ",  # filtro portabile (niente lookup JSON su SQL Server)
        ).only("domanda_snapshot")
    } - {None}
    precedenti = AuditEsito.objects.filter(
        audit__stato=Audit.STATO_CHIUSO, audit__processi_catalogo__in=processi, esito__in=[AuditEsito.ESITO_NC, AuditEsito.ESITO_OFI],
        audit__data_inizio__lt=audit.data_inizio, audit__data_inizio__gte=audit.data_inizio - timedelta(days=3 * 365),
    ).exclude(audit=audit).select_related("audit", "ofi", "ofi__car_procedurale").prefetch_related("verifiche_efficacia").distinct()
    create = []
    for rilievo in precedenti:
        if rilievo.pk in gia or rilievo.pk in chiusi_conformi:
            continue
        if rilievo.ofi_id and rilievo.ofi.is_chiuso:
            continue  # voce MOD.174 chiusa con verifica: nessun follow-up
        car = getattr(rilievo.ofi, "car_procedurale", None) if rilievo.ofi_id else None
        ultima = rilievo.verifiche_efficacia.all()[0] if rilievo.verifiche_efficacia.all() else None
        if car is not None and car.chiusa_il and ultima and ultima.risultato == "EFFICACE":
            continue
        descrizione = (rilievo.scostamento or rilievo.evidenze or rilievo.testo or "").strip()[:200]
        create.append(AuditEsito(
            audit=audit, strutturato=True, punti_aggiuntivi=rilievo.clausola_effettiva[:100],
            testo_aggiuntivo=f"Follow-up {rilievo.audit.numero}: l'azione sul rilievo è attuata ed efficace?",
            domanda_snapshot={
                "followup_di": rilievo.pk, "punti": rilievo.clausola_effettiva,
                "domanda": f"Follow-up {rilievo.get_esito_display()} {rilievo.audit.numero} (§ {rilievo.clausola_effettiva}): «{descrizione}». L'azione è attuata ed efficace?",
                "criterio": f"Registro MOD.174 n. {rilievo.ofi.numero}" if rilievo.ofi_id else "Rilievo dell'audit precedente",
                "processo": rilievo.domanda_snapshot.get("processo", ""),
            },
        ))
    AuditEsito.objects.bulk_create(create)
    return len(create)


def modello_en9100_attivo() -> ChecklistModello | None:
    return ChecklistModello.objects.filter(
        codice=ChecklistModello.CODICE_EN9100_FOLDER_B, attivo=True,
    ).order_by("-revisione").first()


@transaction.atomic
def inizializza_checklist(audit: Audit) -> int:
    from .audit_automation import genera_checklist_processi
    nuovi_processi = genera_checklist_processi(audit) + genera_domande_followup(audit)
    if not audit.en9100:
        return nuovi_processi
    modello = modello_en9100_attivo()
    if not modello:
        return nuovi_processi
    create = []
    for sezione in modello.sezioni.prefetch_related("domande"):
        AuditSezioneCar.objects.get_or_create(audit=audit, sezione=sezione)
        for domanda in sezione.domande.filter(attiva=True):
            create.append(AuditEsito(audit=audit, domanda=domanda, strutturato=True, domanda_snapshot={"domanda": domanda.testo, "punti": domanda.punti, "revisione": modello.revisione, "criterio": sezione.criteri}))
    before = audit.esiti.count()
    AuditEsito.objects.bulk_create(create, ignore_conflicts=True)
    return audit.esiti.count() - before + nuovi_processi


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
    def token(value: str) -> tuple[str, ...]:
        normalizzato = unicodedata.normalize("NFKD", value or "")
        senza_accenti = "".join(c for c in normalizzato if not unicodedata.combining(c))
        return tuple(re.findall(r"[a-z0-9]+", senza_accenti.casefold()))

    ambito = set(token(processi))
    if not ambito:
        return []
    conflitti: list[str] = []
    candidati = [a for a in [lead, *list(auditor or [])] if a]
    visti: set[int] = set()
    for persona in candidati:
        if persona.pk in visti:
            continue
        visti.add(persona.pk)
        reparto_originale = reparto_auditor(persona)
        reparto = token(reparto_originale)
        if reparto and set(reparto).issubset(ambito):
            conflitti.append(f"{persona.nome} ({reparto_originale})")
    return conflitti


def auditor_non_qualificati(*, lead: Auditor | None, auditor, al=None) -> list[str]:
    """Auditor non qualificati; con ``al`` la scadenza della qualifica si confronta con quella data
    (l'ultimo giorno dell'audit), non con oggi."""
    candidati = [a for a in [lead, *list(auditor or [])] if a]
    out, visti = [], set()
    for persona in candidati:
        if persona.pk in visti:
            continue
        visti.add(persona.pk)
        scade_prima = bool(al and persona.qualifica_scadenza and persona.qualifica_scadenza < al)
        if not persona.qualificato or scade_prima:
            out.append(persona.nome + (f" (qualifica in scadenza il {persona.qualifica_scadenza:%d/%m/%Y})" if scade_prima else ""))
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
        # Il MOD.174 non ha un flag ISO 14001: la norma resta leggibile nel riferimento.
        "rif_norma": (esito.clausola_effettiva + (" (ISO 14001)" if audit.iso14001 else ""))[:200],
        "priorita": (RegistroOFI.PRIORITA_ALTA if esito.gravita == AuditEsito.GRAVITA_MAGGIORE
                     else RegistroOFI.PRIORITA_MEDIA),
        "ref": audit.numero[:100],
        "processo": audit.processi[:200],
        "opportunita": esito.evidenze,
        "proprietario": _nome_utente(esito.responsabile_azione)[:150],
        "data_richiesta": esito.scadenza_azione,
        "modulo_origine": "sistema_gestione",
        "content_type": ct,
        "object_id": esito.pk,
    }
    if esito.strutturato:
        from .audit_automation import testo_evidenza
        dati["opportunita"] = testo_evidenza(esito)
        dati["processo"] = esito.domanda_snapshot.get("processo", audit.processi)[:200]
    if esito.esito == AuditEsito.ESITO_NC and esito.gravita:
        dati["opportunita"] = f"[{esito.get_gravita_display()}] {dati['opportunita']}"
    for _tentativo in range(2):
        try:
            # Il savepoint rende recuperabile la transazione esterna anche su SQL Server.
            with transaction.atomic():
                voce = RegistroOFI.objects.create(numero=_prossimo_numero_ofi(), **dati)
            break
        except IntegrityError:
            if _tentativo:
                raise
    esito.ofi = voce
    esito.save(update_fields=["ofi", "updated_at"])
    return voce


@transaction.atomic
def salva_esito(esito: AuditEsito, *, utente, genera_rilievo=True, bozza_token: str = ""):
    from .audit_automation import problemi_esito
    esito.aggiornato_da = utente
    esito.versione += 1
    # Il token identifica SOLO l'ultimo autosalvataggio: qualunque altro salvataggio lo azzera,
    # così un retry vecchio torna a essere un conflitto di versione (niente lost update).
    esito.bozza_token = bozza_token
    esito.full_clean()
    esito.save()
    Audit.objects.filter(pk=esito.audit_id).update(riepilogo_generato="")
    if genera_rilievo and esito.esito in {AuditEsito.ESITO_OFI, AuditEsito.ESITO_NC} and not problemi_esito(esito):
        sincronizza_ofi(esito)
    return esito


def contatori_rilievi(audit: Audit) -> dict[str, int]:
    from django.db.models import Count, Q

    c = audit.esiti.aggregate(
        ofi=Count("pk", filter=Q(esito=AuditEsito.ESITO_OFI)),
        nc=Count("pk", filter=Q(esito=AuditEsito.ESITO_NC)),
        nc_maggiori=Count("pk", filter=Q(esito=AuditEsito.ESITO_NC, gravita=AuditEsito.GRAVITA_MAGGIORE)),
        nc_minori=Count("pk", filter=Q(esito=AuditEsito.ESITO_NC, gravita=AuditEsito.GRAVITA_MINORE)),
        osservazioni=Count("pk", filter=Q(esito=AuditEsito.ESITO_OSSERVAZIONE)),
        punti_forza=Count("pk", filter=Q(esito=AuditEsito.ESITO_PUNTO_FORZA)),
        conformi=Count("pk", filter=Q(esito=AuditEsito.ESITO_CONFORME)),
        na=Count("pk", filter=Q(esito=AuditEsito.ESITO_NA)),
    )
    return {k: v or 0 for k, v in c.items()}


def chiusura_richiede_car_approvate() -> bool:
    """Regola configurabile (SiteConfig): di default l'audit si chiude solo con il piano azioni
    approvato per ogni NC (ISO 19011 §6.6); l'efficacia si segue poi sulla CAR."""
    from core.models import SiteConfig

    return (SiteConfig.get(CHIAVE_CHIUSURA_CAR, "1") or "1").strip() not in {"0", "false", "no"}


CHIAVE_CHIUSURA_CAR = "sistema_gestione.audit_chiusura_richiede_car_approvate"


def problemi_chiusura_audit(audit: Audit) -> list[str]:
    if not chiusura_richiede_car_approvate():
        return []
    problemi = []
    for esito in audit.esiti.filter(esito=AuditEsito.ESITO_NC).select_related("ofi", "ofi__car_procedurale"):
        car = getattr(esito.ofi, "car_procedurale", None) if esito.ofi_id else None
        if not esito.ofi_id:
            problemi.append(f"{esito.clausola_effettiva}: la NC non è nel Registro OFI.")
        elif car is None:
            problemi.append(f"{esito.clausola_effettiva}: apri la CAR della NC n. {esito.ofi.numero}.")
        elif not car.approvata_il:
            problemi.append(f"{esito.clausola_effettiva}: il piano azioni della NC n. {esito.ofi.numero} non è ancora approvato.")
    return problemi


def verifica_completezza(audit: Audit) -> dict:
    """Un'unica fonte per guida in pagina e blocchi server prima delle firme."""
    piano, rapporto = [], []
    def manca(lista, condizione, testo, sezione):
        if condizione:
            lista.append({"testo": testo, "sezione": sezione})
    manca(piano, not audit.processi_snapshot, "Seleziona i processi dal catalogo nel piano.", "campo")
    manca(piano, not audit.punti_norma.strip(), "Indica i punti norma da verificare.", "campo")
    manca(piano, not audit.procedure_criteri.strip(), "Indica procedure e criteri di verifica.", "campo")
    manca(piano, not audit.sede.strip(), "Definisci la sede dell'audit.", "campo")
    manca(piano, not any((audit.metodo_intervista, audit.metodo_esame_documenti,
                         audit.metodo_osservazione_diretta, audit.metodo_verifica_evidenze)),
          "Seleziona almeno un metodo di audit.", "campo")
    manca(piano, not audit.persone.filter(ruolo=AuditPersona.RUOLO_AUDITATO).exists(),
          "Inserisci almeno una persona auditata.", "persone")
    manca(piano, not audit.persone.filter(ruolo=AuditPersona.RUOLO_PROCESSO).exists(),
          "Inserisci il responsabile del processo tra le persone coinvolte.", "persone")
    manca(piano, not audit.agenda.exclude(processo_area__in=["Riunione di apertura", "Riunione di chiusura"]).exists(),
          "Pianifica almeno un'attività di verifica oltre alle riunioni.", "agenda")
    processi_ids = {p["id"] for p in audit.processi_snapshot}
    for voce in audit.agenda.all():
        giorno = timezone.localtime(voce.quando).date()
        manca(piano, not audit.data_inizio <= giorno <= (audit.data_fine or audit.data_inizio),
              f"Correggi la data in agenda: {voce.processo_area}.", "agenda")
        manca(piano, bool(voce.processo_id) and voce.processo_id not in processi_ids,
              f"L'attivita {voce.processo_area} riguarda un processo rimosso dal piano.", "agenda")
    team = list(audit.auditor.all())
    manca(piano, audit.lead_auditor.interno and not any(a.pk != audit.lead_auditor_id for a in team),
          "MT CN 12: affianca al responsabile almeno un altro auditor qualificato.", "campo")
    conflitti = conflitti_imparzialita(processi=audit.processi, lead=audit.lead_auditor, auditor=team)
    utenti = {a.user_id for a in [audit.lead_auditor, *team] if a.user_id}
    conflitti.extend(str(p) for p in audit.processi_catalogo.all() if p.responsabile_id in utenti)
    if conflitti:
        from .programma import deroga_imparzialita_ammessa

        if not (deroga_imparzialita_ammessa() and audit.imparzialita_deroga_motivo.strip()):
            manca(piano, True, "MT CN 12: risolvi il conflitto di indipendenza del team: " + ", ".join(conflitti), "campo")
        elif not audit.imparzialita_deroga_approvata_il:
            manca(piano, True, "Deroga d'indipendenza motivata in attesa dell'approvazione RDD: " + ", ".join(conflitti), "campo")
    non_qualificati = auditor_non_qualificati(lead=audit.lead_auditor, auditor=audit.auditor.all(),
                                              al=audit.data_fine or audit.data_inizio)
    manca(piano, bool(non_qualificati), "Verifica le qualifiche del team: " + ", ".join(non_qualificati), "campo")
    norme = audit.norme_codici
    non_abilitati = sorted({a.nome for a in [audit.lead_auditor, *team] if not a.abilitato_per(norme)})
    manca(piano, bool(non_abilitati), "Il team non è abilitato per tutte le norme dell'audit: " + ", ".join(non_abilitati), "campo")
    esiti = list(audit.esiti.prefetch_related("allegati"))
    from .audit_automation import problemi_esito
    completi = sum(not problemi_esito(e) for e in esiti)
    manca(rapporto, not esiti, "Carica una checklist prima di firmare il rapporto.", "checklist")
    for esito in esiti:
        if esito.strutturato:
            for problema in problemi_esito(esito):
                rapporto.append({"testo": f"{esito.punti}: {problema}.", "sezione": f"esito-{esito.pk}"})
        manca(rapporto, not esito.strutturato and not esito.esito, f"{esito.punti}: scegli un esito.", f"esito-{esito.pk}")
        manca(rapporto, not esito.strutturato and bool(esito.esito) and not esito.evidenze.strip(),
              f"{esito.punti}: registra evidenze o motivazione N/A.", f"esito-{esito.pk}")
        manca(rapporto, esito.esito in {AuditEsito.ESITO_NC, AuditEsito.ESITO_OFI} and not esito.ofi_id,
              f"{esito.punti}: manca il collegamento al Registro OFI.", f"esito-{esito.pk}")
    manca(rapporto, not audit.giudizio.strip(), "Scrivi il giudizio conclusivo del rapporto.", "rapporto")
    return {"piano": piano, "rapporto": rapporto, "completi": completi, "totale": len(esiti),
            "percentuale": round(100 * completi / len(esiti)) if esiti else 0,
            "chiusura": problemi_chiusura_audit(audit) if audit.stato == Audit.STATO_RAPPORTO else []}


def invalida_approvazione_piano(audit):
    """Ogni variazione al piano in bozza richiede una nuova firma Lead."""
    audit.piano_approvato_lead_da = None
    audit.piano_approvato_lead_il = None
    audit.comunicazione_il = None
    audit.comunicazione_metodo = ""
    # Una deroga d'indipendenza vale per il team e il campo approvati: si riapprova.
    audit.imparzialita_deroga_approvata_da = None
    audit.imparzialita_deroga_approvata_il = None
    audit.save(update_fields=["piano_approvato_lead_da", "piano_approvato_lead_il",
                              "comunicazione_il", "comunicazione_metodo",
                              "imparzialita_deroga_approvata_da", "imparzialita_deroga_approvata_il", "updated_at"])


def _ics_testo(valore: str) -> str:
    """Escape RFC 5545 per TEXT: barra rovescia, punto e virgola, virgola, a capo."""
    return (str(valore or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics(audit: Audit, destinatari: list[str] | None = None, *, annulla: bool = False) -> bytes:
    inizio = _datetime_locale(audit.data_inizio, time(9, 0)).astimezone(dt_timezone.utc)
    fine = _datetime_locale(audit.data_fine or audit.data_inizio, time(17, 0)).astimezone(dt_timezone.utc)
    stamp = timezone.now().astimezone(dt_timezone.utc)
    righe = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NOVICROM HUB//Audit//IT",
        "METHOD:CANCEL" if annulla else "METHOD:REQUEST",
        "BEGIN:VEVENT", f"UID:audit-{audit.pk}@novicrom-hub", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
        *(["STATUS:CANCELLED"] if annulla else []),
        # SEQUENCE crescente: una nuova comunicazione aggiorna l'evento invece di duplicarlo.
        f"SEQUENCE:{int(stamp.timestamp())}",
        f"DTSTART:{inizio:%Y%m%dT%H%M%SZ}", f"DTEND:{fine:%Y%m%dT%H%M%SZ}",
        f"SUMMARY:{_ics_testo('Audit ' + audit.numero)}", f"LOCATION:{_ics_testo(audit.sede)}",
        f"DESCRIPTION:{_ics_testo(audit.processi)}",
    ]
    righe += [f"ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{email}" for email in (destinatari or [])]
    righe += ["END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(righe).encode("utf-8")


def comunica_audit(audit: Audit, *, metodo: str, deroga_motivo: str = "") -> int:
    oggi = timezone.localdate()
    preavviso = giorni_lavorativi_di_preavviso(oggi, audit.data_inizio)
    if preavviso < 5 or (audit.data_inizio - oggi).days < 7:
        raise ValidationError(
            f"Restano {preavviso} giorni lavorativi: riprogramma il piano per rispettare almeno 5 giorni lavorativi e una settimana (MT CN 12 / MOD.035A)."
        )
    destinatari = sorted({
        p.email.strip() for p in audit.persone.filter(ruolo=AuditPersona.RUOLO_AUDITATO) if p.email.strip()
    })
    if not destinatari:
        raise ValidationError("Inserisci almeno una persona auditata con indirizzo email.")
    # Solo stato e validazione: l'invio (email o Graph) avviene dopo il commit, fuori dal lock.
    audit.comunicazione_il = timezone.now()
    audit.comunicazione_metodo = metodo
    audit.preavviso_deroga_motivo = (deroga_motivo or "").strip()
    audit.save(update_fields=["comunicazione_il", "comunicazione_metodo", "preavviso_deroga_motivo", "updated_at"])
    return destinatari


def invia_email_comunicazione(audit: Audit, *, metodo: str, destinatari: list[str], annullamento: bool = False) -> int:
    """Email del piano (o del suo annullamento) con eventuale invito/cancellazione .ics."""
    from core.email_utils import send_hub_mail

    allegati = []
    if metodo == Audit.COM_CALENDARIO:
        allegati.append((f"audit-{audit.numero}.ics", _ics(audit, destinatari, annulla=annullamento),
                         "text/calendar; method=CANCEL" if annullamento else "text/calendar; method=REQUEST"))
    if annullamento:
        oggetto = f"Audit {audit.numero} annullato"
        corpo = (f"L'audit {audit.numero} del {audit.data_inizio:%d/%m/%Y} è stato annullato.\n"
                 f"Motivo: {audit.motivo_annullamento}.")
    else:
        oggetto = f"Piano di audit {audit.numero}"
        corpo = (f"È stato pianificato l'audit {audit.numero} per il {audit.data_inizio:%d/%m/%Y}.\n"
                 f"Processi/aree: {audit.processi}.\nSede: {audit.sede or 'da definire'}.")
    return send_hub_mail(subject=oggetto, body_text=corpo, recipients=destinatari, title="Piano di audit",
                         email_type="Sistema di gestione", attachments=allegati)


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
                f"NC: {audit.esiti.filter(esito=AuditEsito.ESITO_NC).count()}.\n"
                "I rilievi che ti riguardano sono nel portale: Sistema di gestione › Audit › I miei rilievi "
                "(/sistema-gestione/audit/miei-rilievi/)."
            ),
            recipients=sorted(destinatari),
            title="Rapporto di audit interno",
            email_type="Sistema di gestione",
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 - l'audit resta chiuso; l'invio mancato si registra
        import logging

        logging.getLogger(__name__).exception("Distribuzione del rapporto %s non riuscita", audit.numero)


def _verifica_copertura_procedurale(programma):
    from .procedure import verifica_copertura
    try:
        verifica_copertura(programma)
    except ValidationError as exc:
        raise TransizioneNonAmmessa("; ".join(exc.messages)) from exc
