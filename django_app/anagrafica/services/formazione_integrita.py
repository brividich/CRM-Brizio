"""Integrità dei dati della formazione d'aula (MT CN 06 §9, MT CN 08 §7.3, MOD.040).

Tre responsabilità, tutte qui perché viste, comando e test leggano le stesse regole:

1. **Edizione chiusa.** Un'edizione COMPLETATA o approvata non si modifica più:
   calendario, iscritti e presenze sono l'evidenza degli attestati già emessi.
   Si corregge riaprendola con un motivo (``riapri_edizione``).
2. **Approvazione del MOD.040** (``approva_edizione``) con i controlli di
   completezza della registrazione richiesti da MT CN 06 §9.2
   (``requisiti_approvazione``), e verifica «assenza NC nei 6 mesi»
   (``registra_verifica_nc``).
3. **Annullamento motivato** di un completamento (``annulla_record``) al posto
   della cancellazione, e **controlli di integrità** sull'archivio
   (``controlli_integrita``) usati dalla pagina «Integrità dati» e dal comando
   ``verifica_integrita_formazione``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

__all__ = [
    "EdizioneChiusa",
    "motivo_blocco_edizione",
    "verifica_edizione_modificabile",
    "requisiti_approvazione",
    "approva_edizione",
    "riapri_edizione",
    "registra_verifica_nc",
    "annulla_record",
    "controlli_integrita",
    "correggi",
    "nome_utente",
]

STATI_FINALI_ISCRIZIONE = ("COMPLETATO", "NON_IDONEO", "ASSENTE", "RITIRATO")


class EdizioneChiusa(Exception):
    """L'edizione è chiusa: la modifica richiesta va fatta dopo averla riaperta."""


def nome_utente(user) -> str:
    if user is None:
        return ""
    nome = ""
    try:
        nome = (user.get_full_name() or "").strip()
    except Exception:
        nome = ""
    return (nome or getattr(user, "username", "") or "")[:200]


# ── 1. Edizione chiusa ──────────────────────────────────────────────────────

def motivo_blocco_edizione(sessione) -> str:
    """Testo da mostrare se l'edizione è chiusa, stringa vuota altrimenti."""
    if sessione is None:
        return ""
    if sessione.is_approvata:
        return (f"L'edizione «{sessione.codice_sessione}» è approvata (MOD.040): "
                "per correggerla riaprila indicando il motivo.")
    if sessione.stato == "COMPLETATA":
        return (f"L'edizione «{sessione.codice_sessione}» è completata: calendario, iscritti "
                "e presenze non si modificano più. Per correggerla riaprila indicando il motivo.")
    return ""


def verifica_edizione_modificabile(sessione) -> None:
    motivo = motivo_blocco_edizione(sessione)
    if motivo:
        raise EdizioneChiusa(motivo)


# ── 2. Approvazione MOD.040 ─────────────────────────────────────────────────

@dataclass
class EsitoRequisiti:
    mancanti: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mancanti


def requisiti_approvazione(sessione) -> EsitoRequisiti:
    """Contenuto minimo della registrazione (MT CN 06 §9.2): argomento, date,
    partecipanti, docente o tutor, esito. Più lo stato COMPLETATA."""
    esito = EsitoRequisiti()
    lezioni = list(sessione.lezioni.all())
    iscrizioni = list(sessione.iscrizioni.all())

    if sessione.stato != "COMPLETATA":
        esito.mancanti.append("l'edizione non è nello stato «Completata»")
    ha_argomento = sessione.programma.exists() or any((lz.argomento or "").strip() for lz in lezioni)
    if not ha_argomento:
        esito.mancanti.append("manca l'argomento: nessuna voce di programma e nessuna giornata con argomento")
    if not lezioni and not sessione.data_inizio:
        esito.mancanti.append("mancano le date")
    if not iscrizioni:
        esito.mancanti.append("nessun partecipante iscritto")
    ha_docente = bool(
        sessione.docente_id or sessione.docente_ente_id or (sessione.docente_nome or "").strip()
        or any(lz.docente_id or lz.docente_ente_id or (lz.docente_nome or "").strip() for lz in lezioni)
    )
    if not ha_docente:
        esito.mancanti.append("manca il docente o tutor (sull'edizione o su almeno una giornata)")
    aperti = [i for i in iscrizioni if i.stato not in STATI_FINALI_ISCRIZIONE]
    if aperti:
        esito.mancanti.append(
            f"{len(aperti)} partecipant{'e' if len(aperti) == 1 else 'i'} senza esito "
            "(ancora «Iscritto» o «In corso»)"
        )
    return esito


def approva_edizione(sessione, user, note: str = "") -> int:
    """Approva il MOD.040 dell'edizione. Ritorna i completamenti validati.

    I completamenti dell'edizione ancora senza validazione prendono la stessa
    firma: l'approvazione MSM/MSO è la loro validazione formale (§9.3)."""
    from ..models_formazione import TrainingEmployeeRecord

    if sessione.is_approvata:
        raise ValueError("L'edizione è già approvata.")
    req = requisiti_approvazione(sessione)
    if not req.ok:
        raise ValueError("Approvazione non possibile: " + "; ".join(req.mancanti) + ".")
    adesso = timezone.now()
    with transaction.atomic():
        sessione.approvata_il = adesso
        sessione.approvata_da = user
        sessione.approvata_da_nome = nome_utente(user)
        sessione.approvazione_note = (note or "").strip()
        sessione.save(update_fields=["approvata_il", "approvata_da", "approvata_da_nome",
                                     "approvazione_note", "updated_at"])
        validati = 0
        for rec in TrainingEmployeeRecord.objects.filter(sessione=sessione, validato_da__isnull=True):
            rec.validato_da = user
            rec.validato_il = timezone.localdate()
            rec.save(update_fields=["validato_da", "validato_il"])
            validati += 1
    return validati


def riapri_edizione(sessione, user, motivo: str) -> dict:
    """Riapre un'edizione chiusa. Il motivo è obbligatorio e torna al chiamante
    per il registro attività: l'approvazione revocata resta leggibile lì."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indica il motivo della riapertura.")
    if not sessione.is_chiusa:
        raise ValueError("L'edizione non è chiusa.")
    traccia = {
        "stato_precedente": sessione.stato,
        "approvata_il": sessione.approvata_il.isoformat() if sessione.approvata_il else None,
        "approvata_da": sessione.approvata_da_nome,
        "motivo": motivo,
    }
    sessione.stato = "IN_CORSO"
    sessione.approvata_il = None
    sessione.approvata_da = None
    sessione.approvata_da_nome = ""
    sessione.approvazione_note = ""
    sessione.save(update_fields=["stato", "approvata_il", "approvata_da", "approvata_da_nome",
                                 "approvazione_note", "updated_at"])
    return traccia


def registra_verifica_nc(sessione, user, esito: str, note: str = "") -> None:
    validi = {c for c, _ in sessione.VERIFICA_NC_CHOICES}
    if esito not in validi:
        raise ValueError("Esito della verifica NC non valido.")
    if esito == "NO" and not (note or "").strip():
        raise ValueError("Con NC riconducibili alla formazione descrivi l'esito e l'azione decisa.")
    sessione.verifica_nc_esito = esito
    sessione.verifica_nc_note = (note or "").strip()
    sessione.verifica_nc_il = timezone.localdate()
    sessione.verifica_nc_da = user
    sessione.verifica_nc_da_nome = nome_utente(user)
    sessione.save(update_fields=["verifica_nc_esito", "verifica_nc_note", "verifica_nc_il",
                                 "verifica_nc_da", "verifica_nc_da_nome", "updated_at"])


# ── 3. Annullamento motivato ────────────────────────────────────────────────

def annulla_record(record, user, motivo: str) -> dict:
    """Annulla un completamento senza cancellarlo.

    - il record esce da requisiti, scadenze, libretto ed export;
    - l'iscrizione collegata torna «In corso» e si stacca, così il corso si
      può chiudere di nuovo con i dati giusti;
    - la qualifica che aveva questo record come prova torna sul completamento
      valido precedente, oppure resta da verificare.
    Ritorna un riepilogo per messaggio e registro attività."""
    from ..models import DipendenteQualifica
    from ..models_formazione import TrainingEmployeeRecord

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indica il motivo dell'annullamento.")
    if record.is_annullato:
        raise ValueError("Il completamento è già annullato.")
    if record.sessione_id and record.sessione.is_approvata:
        raise EdizioneChiusa(motivo_blocco_edizione(record.sessione))

    riepilogo = {"record_id": record.pk, "corso": record.course_code_snapshot or record.corso.codice,
                 "legacy_anagrafica_id": record.legacy_anagrafica_id,
                 "data_completamento": record.data_completamento.isoformat(), "motivo": motivo,
                 "qualifica": ""}
    with transaction.atomic():
        enrollment = record.enrollment
        record.annullato_il = timezone.now()
        record.annullato_da = user
        record.annullato_da_nome = nome_utente(user)
        record.annullato_motivo = motivo
        record.enrollment = None
        # save() rifirma da sé il codice di verifica quando c'è.
        record.save(update_fields=["annullato_il", "annullato_da", "annullato_da_nome",
                                   "annullato_motivo", "enrollment"])
        if enrollment is not None and enrollment.stato == "COMPLETATO":
            enrollment.stato = "IN_CORSO"
            enrollment.save(update_fields=["stato", "updated_at"])

        for qual in DipendenteQualifica.objects.filter(record_formazione_id=record.pk):
            precedente = (
                TrainingEmployeeRecord.objects
                .filter(corso_id=record.corso_id, legacy_anagrafica_id=record.legacy_anagrafica_id, idoneo=True)
                .order_by("-data_completamento", "-id").first()
            )
            if precedente is not None:
                qual.record_formazione = precedente
                qual.data_conseguimento = precedente.data_completamento
                qual.data_scadenza = precedente.data_scadenza
                qual.save(update_fields=["record_formazione", "data_conseguimento", "data_scadenza"])
                riepilogo["qualifica"] = f"«{qual.tipo}» riallineata al completamento del {precedente.data_completamento:%d/%m/%Y}"
            else:
                qual.record_formazione = None
                campi = ["record_formazione"]
                if hasattr(qual, "verificata"):
                    qual.verificata = False
                    campi.append("verificata")
                qual.save(update_fields=campi)
                riepilogo["qualifica"] = f"«{qual.tipo}» senza altra prova formativa: da verificare"

    try:
        from .training_deadline_service import refresh_deadlines
        refresh_deadlines(legacy_id=record.legacy_anagrafica_id, corso_id=record.corso_id)
    except Exception:
        logger.exception("Ricalcolo scadenze dopo annullamento del record %s fallito", record.pk)
    return riepilogo


# ── Controlli di integrità ──────────────────────────────────────────────────

@dataclass
class Controllo:
    codice: str
    titolo: str
    riferimento: str
    spiegazione: str
    n: int = 0
    esempi: list = field(default_factory=list)
    correggibile: bool = False
    gravita: str = "media"   # alta | media | bassa


def _esempi(qs, n: int = 10) -> list:
    return list(qs.order_by().values_list("pk", flat=True)[:n])


def controlli_integrita(oggi: date | None = None) -> list[Controllo]:
    """Controlli in sola lettura. Ogni voce dice cosa non torna, il riferimento
    SGI e se il comando sa correggerla da solo (``--correggi``)."""
    from ..models_formazione import (
        TrainingEmployeeRecord, TrainingEnrollment, TrainingLesson, TrainingLessonAttendance,
        TrainingRequirementRule, TrainingSession, aggiungi_mesi,
    )

    oggi = oggi or timezone.localdate()
    out: list[Controllo] = []

    qs = TrainingSession.objects.filter(data_fine__lt=F("data_inizio"))
    out.append(Controllo("sessione_date_invertite", "Edizioni con fine prima dell'inizio", "MT CN 06 §9.2",
                         "La data di fine precede quella di inizio.", qs.count(), _esempi(qs), True, "alta"))

    qs = TrainingLesson.objects.filter(Q(data__lt=F("sessione__data_inizio")) | Q(data__gt=F("sessione__data_fine")))
    out.append(Controllo("lezioni_fuori_intervallo", "Giornate fuori dalle date dell'edizione", "MT CN 06 §9.2",
                         "La giornata cade prima dell'inizio o dopo la fine dell'edizione.",
                         qs.count(), _esempi(qs), True, "media"))

    qs = TrainingLesson.objects.filter(ora_fine__lte=F("ora_inizio"))
    out.append(Controllo("lezioni_durata_nulla", "Giornate senza durata (ora fine ≤ ora inizio)", "MT CN 06 §9.2",
                         "Spesso import storici con orario 09:00–09:00: la giornata vale 0 ore e la "
                         "percentuale di presenza perde significato. Va corretto l'orario a mano.",
                         qs.count(), _esempi(qs), False, "media"))

    iscritti = set(TrainingEnrollment.objects.values_list("sessione_id", "legacy_anagrafica_id"))
    non_iscritti = [pk for pk, sid, lid in TrainingLessonAttendance.objects
                    .values_list("pk", "lezione__sessione_id", "legacy_anagrafica_id")
                    if (sid, lid) not in iscritti]
    out.append(Controllo("presenze_non_iscritti", "Presenze di persone non iscritte", "MT CN 06 §9.2",
                         "Una presenza senza iscrizione non entra nel calcolo della frequenza.",
                         len(non_iscritti), non_iscritti[:10], False, "media"))

    qs = TrainingLessonAttendance.objects.filter(stato_presenza__startswith="ASSENTE", ore_effettive__gt=0)
    out.append(Controllo("assenti_con_ore", "Assenze con ore registrate", "MT CN 08 §7.3",
                         "Assente con ore effettive maggiori di zero: le ore vengono azzerate.",
                         qs.count(), _esempi(qs), True, "bassa"))

    oltre = [p.pk for p in TrainingLessonAttendance.objects.filter(ore_effettive__isnull=False)
             .select_related("lezione").only("ore_effettive", "lezione__ora_inizio", "lezione__ora_fine",
                                             "lezione__pausa_minuti")
             if p.lezione.durata_ore > 0 and float(p.ore_effettive) > p.lezione.durata_ore + 0.01]
    out.append(Controllo("presenze_oltre_durata", "Presenze con più ore della giornata", "MT CN 08 §7.3",
                         "Ore effettive superiori alla durata formativa della giornata: vengono "
                         "riportate alla durata della giornata.", len(oltre), oltre[:10], True, "media"))

    qs = TrainingEnrollment.objects.filter(stato="COMPLETATO", record_completamento__isnull=True)
    out.append(Controllo("completati_senza_record", "Iscrizioni «Completato» senza completamento a libretto",
                         "MT CN 06 §9.2", "Lo stato dice completato ma nessun record è a libretto: "
                         "riaprire l'iscrizione e chiuderla di nuovo.", qs.count(), _esempi(qs), False, "alta"))

    doppi = (TrainingEmployeeRecord.objects.values("corso_id", "legacy_anagrafica_id", "data_completamento")
             .order_by().annotate(n=Count("id")).filter(n__gt=1))
    out.append(Controllo("record_doppi", "Completamenti doppi (persona, corso, data)", "MT CN 08 §7.3",
                         "Due completamenti uguali: si sistemano con «manage.py pulisci_scadenze_hr --doppioni», "
                         "che tiene il più collegato e lascia a mano i casi dubbi.",
                         doppi.count(), [], False, "media"))

    qs = TrainingEmployeeRecord.objects.filter(data_completamento__gt=oggi)
    out.append(Controllo("record_futuri", "Completamenti con data futura", "MT CN 06 §9.2",
                         "Un completamento non può essere avvenuto dopo oggi: correggere la data o annullarlo.",
                         qs.count(), _esempi(qs), False, "alta"))

    qs = TrainingEmployeeRecord.objects.filter(sessione__isnull=False, data_completamento__lt=F("sessione__data_inizio"))
    out.append(Controllo("record_prima_edizione", "Completamenti datati prima dell'inizio dell'edizione",
                         "MT CN 06 §9.2", "La data di completamento precede l'inizio dell'edizione.",
                         qs.count(), _esempi(qs), False, "media"))

    incoerenti = []
    for r in TrainingEmployeeRecord.objects.only("data_completamento", "data_scadenza", "validity_months_snapshot"):
        m = r.validity_months_snapshot
        if m is None:
            continue
        attesa = aggiungi_mesi(r.data_completamento, m) if m else None
        if attesa != r.data_scadenza:
            incoerenti.append(r.pk)
    out.append(Controllo("scadenze_incoerenti", "Scadenze diverse da completamento + validità", "MT CN 06 §9.2",
                         "La scadenza scritta non corrisponde alla validità del corso al momento del "
                         "completamento. Può essere voluta (attestato esterno): verificare prima di correggere.",
                         len(incoerenti), incoerenti[:10], False, "media"))

    qs = TrainingSession.objects.filter(stato="COMPLETATA").annotate(np=Count("lezioni__presenze")).filter(np=0)
    out.append(Controllo("completate_senza_presenze", "Edizioni completate senza presenze", "MT CN 06 §9.2",
                         "Nessuna presenza registrata: il registro firme è l'evidenza della partecipazione.",
                         qs.count(), _esempi(qs), False, "media"))

    qs = TrainingSession.objects.filter(docente__isnull=True, docente_ente__isnull=True, docente_nome="")
    qs = qs.exclude(lezioni__docente__isnull=False).exclude(lezioni__docente_ente__isnull=False)
    out.append(Controllo("edizioni_senza_docente", "Edizioni senza docente o tutor", "MT CN 06 §9.2",
                         "La registrazione deve riportare il docente o tutor.",
                         qs.distinct().count(), _esempi(qs.distinct()), False, "media"))

    qs = TrainingSession.objects.filter(stato="PIANIFICATA", data_fine__lt=oggi)
    out.append(Controllo("pianificate_passate", "Edizioni passate ancora «Pianificata»", "MT CN 06 §9.1",
                         "L'edizione è finita ma risulta solo pianificata.", qs.count(), _esempi(qs), False, "bassa"))

    qs = TrainingSession.objects.filter(stato="COMPLETATA", approvata_il__isnull=True)
    out.append(Controllo("completate_non_approvate", "Edizioni completate da approvare (MOD.040)", "MT CN 06 §9.3",
                         "MSM o MSO approvano il registro con una verifica formale.",
                         qs.count(), _esempi(qs), False, "bassa"))

    limite = aggiungi_mesi(oggi, -TrainingSession.MESI_VERIFICA_NC)
    qs = TrainingSession.objects.filter(approvata_il__isnull=False, verifica_nc_esito="", data_fine__lte=limite)
    out.append(Controllo("verifiche_nc_dovute", "Verifiche «assenza NC a 6 mesi» dovute", "MOD.040",
                         "Sono passati 6 mesi dalla fine dell'edizione: registrare l'esito della verifica.",
                         qs.count(), _esempi(qs), False, "bassa"))

    qs = TrainingRequirementRule.objects.filter(override_frequenza_mesi__isnull=False, is_active=True)
    out.append(Controllo("override_frequenza", "Regole con «frequenza diversa dal corso»", "—",
                         "Il campo non è applicato al calcolo delle scadenze (vale la validità del corso): "
                         "spostare la frequenza sul corso o creare un corso dedicato.",
                         qs.count(), _esempi(qs), False, "bassa"))
    return out


def correggi(oggi: date | None = None) -> dict[str, int]:
    """Correzioni deterministiche, senza margine di interpretazione:

    - edizione con date invertite → si scambiano;
    - giornata fuori intervallo → l'intervallo dell'edizione si allarga a coprirla;
    - assente con ore → ore azzerate;
    - ore oltre la durata della giornata → riportate alla durata;
    - poi ricalcolo di ore e percentuale delle iscrizioni toccate.
    Tutto il resto richiede una persona e resta nel report."""
    from ..models_formazione import TrainingEnrollment, TrainingLesson, TrainingLessonAttendance, TrainingSession
    from ..views import _ricalcola_presenza_enrollment
    from decimal import Decimal

    fatti = {"sessione_date_invertite": 0, "lezioni_fuori_intervallo": 0,
             "assenti_con_ore": 0, "presenze_oltre_durata": 0, "iscrizioni_ricalcolate": 0}
    da_ricalcolare: set[tuple[int, int]] = set()
    with transaction.atomic():
        for s in TrainingSession.objects.filter(data_fine__lt=F("data_inizio")):
            s.data_inizio, s.data_fine = s.data_fine, s.data_inizio
            s.save(update_fields=["data_inizio", "data_fine"])
            fatti["sessione_date_invertite"] += 1
        for lz in TrainingLesson.objects.filter(
            Q(data__lt=F("sessione__data_inizio")) | Q(data__gt=F("sessione__data_fine"))
        ).select_related("sessione"):
            s = lz.sessione
            s.data_inizio = min(s.data_inizio, lz.data)
            s.data_fine = max(s.data_fine, lz.data)
            s.save(update_fields=["data_inizio", "data_fine"])
            fatti["lezioni_fuori_intervallo"] += 1
        for p in TrainingLessonAttendance.objects.filter(stato_presenza__startswith="ASSENTE", ore_effettive__gt=0) \
                .select_related("lezione"):
            p.ore_effettive = None
            p.save(update_fields=["ore_effettive"])
            da_ricalcolare.add((p.lezione.sessione_id, p.legacy_anagrafica_id))
            fatti["assenti_con_ore"] += 1
        for p in TrainingLessonAttendance.objects.filter(ore_effettive__isnull=False).select_related("lezione"):
            durata = p.lezione.durata_ore
            if durata > 0 and float(p.ore_effettive) > durata + 0.01:
                p.ore_effettive = Decimal(str(durata))
                p.save(update_fields=["ore_effettive"])
                da_ricalcolare.add((p.lezione.sessione_id, p.legacy_anagrafica_id))
                fatti["presenze_oltre_durata"] += 1
        for sid, lid in da_ricalcolare:
            enr = TrainingEnrollment.objects.filter(sessione_id=sid, legacy_anagrafica_id=lid).first()
            if enr is not None:
                _ricalcola_presenza_enrollment(enr)
                fatti["iscrizioni_ricalcolate"] += 1
    return fatti
