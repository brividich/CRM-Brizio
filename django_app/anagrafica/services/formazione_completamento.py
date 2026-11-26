"""Un solo punto di uscita per ogni completamento (TrainingEmployeeRecord), da qualunque strada arrivi:
iscrizione a una sessione (aula, online), completamento diretto, e-learning, link aperto, import,
formazione pregressa del preinserimento.

Prima gli effetti stavano in due copie (``views/formazione._post_completamento`` e la coda di
``views/_helpers._crea_record_completamento_elearning``) che facevano cose diverse; gli import non ne
facevano nessuno (analisi 26/11/2026).

Effetti (tutti fail-safe: un errore qui non annulla mai il completamento):
- scadenze ricalcolate per persona × corso;
- qualifica collegata al corso, se il completamento è idoneo;
- un corso = un completamento: chiuse le assegnazioni aperte dello stesso corso e le iscrizioni alle
  sessioni online dello stesso corso;
- solo per i completamenti «di oggi» (non ``storico``): valutazione di efficacia e archiviazione
  dell'attestato, dopo il commit.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def dopo_completamento(record, user=None, *, storico: bool = False) -> None:
    if record is None:
        return
    corso = record.corso
    legacy_id = record.legacy_anagrafica_id

    from ..models_formazione import TrainingAssignment, TrainingDeadline

    TrainingDeadline.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).update(needs_refresh=True)
    try:
        from .training_deadline_service import refresh_deadlines
        refresh_deadlines(legacy_id=legacy_id, corso_id=corso.pk)
    except NotImplementedError:
        pass
    except Exception:
        logger.exception("Ricalcolo scadenze fallito per dip=%s corso=%s", legacy_id, corso.pk)

    try:
        if corso.qualifica_id and record.idoneo:
            from ..views._helpers import _upsert_dipendente_qualifica
            with transaction.atomic():
                qual, _ = _upsert_dipendente_qualifica(legacy_id, corso.qualifica, record.data_completamento,
                                                       record.data_scadenza, user=user)
                if qual.record_formazione_id != record.pk:
                    qual.record_formazione = record
                    qual.save(update_fields=["record_formazione"])
    except Exception:
        logger.exception("Allineamento qualifica fallito per record %s", record.pk)

    if record.idoneo:
        try:
            with transaction.atomic():
                TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id).exclude(
                    stato__in=("COMPLETATO", "ESONERATO")).update(stato="COMPLETATO")
                from .sessione_online import completa_iscrizioni_da_record
                completa_iscrizioni_da_record(record)
        except Exception:
            logger.exception("Assegnazioni / sessioni online non chiuse per record %s", record.pk)
        try:
            # Corso richiesto da una competenza: il completamento (anche e-learning o link aperto)
            # entra nelle righe aperte delle sessioni formative su mansioni.
            from .sessioni import collega_completamento
            with transaction.atomic():
                collega_completamento(record)
        except Exception:
            logger.exception("Completamento non collegato alle sessioni formative (record %s)", record.pk)

    if storico:
        return

    try:
        from .formazione_efficacia import pianifica_valutazione_efficacia
        with transaction.atomic():
            pianifica_valutazione_efficacia(record)
    except Exception:
        logger.exception("Valutazione di efficacia non pianificata per record %s", record.pk)

    def _archivia():
        try:
            from ..models_formazione import AttestatoFormazioneConfig
            cfg = AttestatoFormazioneConfig.get_instance()
            if cfg.auto_salva_attestato:
                from .attestato_pdf import archivia_attestato
                archivia_attestato(record, cfg=cfg, user=user)
        except Exception:
            logger.exception("Archiviazione automatica attestato fallita per record %s", record.pk)

    transaction.on_commit(_archivia)


def completamento_valido(corso, legacy_id, *, oggi=None):
    """Il completamento valido più recente della persona per il corso, da qualunque strada; None se
    non c'è o se è scaduto. Regola unica di «ha già fatto il corso»."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    if not legacy_id or corso is None:
        return None
    oggi = oggi or timezone.localdate()
    return (TrainingEmployeeRecord.objects
            .filter(corso=corso, legacy_anagrafica_id=legacy_id, idoneo=True)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
            .order_by("-data_completamento", "-pk").first())


def ids_con_completamento_valido(corso, legacy_ids, *, oggi=None) -> set[int]:
    """Le persone (fra ``legacy_ids``) che hanno un completamento valido del corso."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    oggi = oggi or timezone.localdate()
    return set(TrainingEmployeeRecord.objects
               .filter(corso=corso, legacy_anagrafica_id__in=list(legacy_ids), idoneo=True)
               .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
               .values_list("legacy_anagrafica_id", flat=True))


# ─────────────────────────────────────────────────────────────────────────────
# Stato persona × corso: una sola regola per scheda corso, iscritti, corso online, cruscotti
# ─────────────────────────────────────────────────────────────────────────────

COMPLETATO, SCADUTO, DA_REGISTRARE, IN_CORSO, DA_FARE = (
    "COMPLETATO", "SCADUTO", "DA_REGISTRARE", "IN_CORSO", "DA_FARE")
ETICHETTE_STATO_PERSONA = {
    COMPLETATO: "Completato",
    SCADUTO: "Scaduto",
    DA_REGISTRARE: "Da registrare",
    IN_CORSO: "In corso",
    DA_FARE: "Da fare",
}
TONO_STATO_PERSONA = {
    COMPLETATO: "success", SCADUTO: "danger", DA_REGISTRARE: "warning", IN_CORSO: "info", DA_FARE: "neutral",
}
# Etichette di dettaglio per chi non ha (ancora) un completamento: l'ultimo esito.
_DETTAGLIO_DA_FARE = {
    "NON_IDONEO": "Non idoneo", "ASSENTE": "Assente", "RITIRATO": "Ritirato", "NON_SUPERATO": "Non superato",
}


class StatoPersonaCorso:
    """Esito di :func:`stato_persona_corso`: ``codice`` (una delle costanti), ``etichetta`` leggibile,
    ``data`` (completamento, scadenza o verifica superata), ``record`` (il completamento che conta)."""

    __slots__ = ("codice", "etichetta", "data", "record")

    def __init__(self, codice: str, etichetta: str = "", data=None, record=None):
        self.codice = codice
        self.etichetta = etichetta or ETICHETTE_STATO_PERSONA[codice]
        self.data = data
        self.record = record

    @property
    def tono(self) -> str:
        return TONO_STATO_PERSONA[self.codice]

    @property
    def completato(self) -> bool:
        return self.codice == COMPLETATO

    def __repr__(self) -> str:
        return f"StatoPersonaCorso({self.codice!r}, {self.data!r})"


def _data_di(valore):
    if valore is None:
        return None
    if hasattr(valore, "hour"):
        from django.utils import timezone
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def stati_persona_corso(corso, legacy_ids, *, iscrizioni=None, oggi=None) -> dict:
    """Lo stato persona × corso per molti dipendenti in poche query. Regola unica:

    - COMPLETATO: c'è un completamento idoneo non scaduto (da qualunque strada);
    - DA_REGISTRARE: verifica / test superato (aula, lezione online, e-learning, link aperto
      abbinato) più recente dell'ultimo completamento, ma senza completamento a libretto;
    - SCADUTO: l'ultimo completamento idoneo è scaduto;
    - IN_CORSO: iscrizione aperta (aula, lezione online, e-learning) o assegnazione in corso;
    - DA_FARE: tutto il resto (l'etichetta dice l'ultimo esito: non idoneo, assente, ...).

    ``iscrizioni``: le TrainingEnrollment del corso già lette (evita una query)."""
    from django.utils import timezone

    from ..models_elearning import TrainingElearningRispostaAperta
    from ..models_formazione import (
        TrainingAssignment,
        TrainingElearningEnrollment,
        TrainingEmployeeRecord,
        TrainingEnrollment,
    )

    ids = {int(i) for i in legacy_ids if i}
    if corso is None or not ids:
        return {}
    oggi = oggi or timezone.localdate()

    ultimo_valido: dict = {}
    ultimo_idoneo: dict = {}
    ultimo_qualsiasi: dict = {}
    enr_con_record: set = set()
    for r in (TrainingEmployeeRecord.objects.filter(corso=corso, legacy_anagrafica_id__in=ids)
              .order_by("-data_completamento", "-pk")):
        lid = r.legacy_anagrafica_id
        if r.enrollment_id:
            enr_con_record.add(r.enrollment_id)
        ultimo_qualsiasi.setdefault(lid, r)
        if r.idoneo:
            ultimo_idoneo.setdefault(lid, r)
            if r.data_scadenza is None or r.data_scadenza >= oggi:
                ultimo_valido.setdefault(lid, r)

    superata: dict = {}   # lid -> data della verifica superata più recente senza record (None se ignota)
    aperta: dict = {}     # lid -> "IN_CORSO" | "ISCRITTO"
    esito: dict = {}      # lid -> ultimo esito negativo (etichetta di DA_FARE)

    def _segna_superata(lid, quando):
        if lid not in superata or (quando and (superata[lid] is None or quando > superata[lid])):
            superata[lid] = quando

    def _segna_aperta(lid, stato):
        if stato == "IN_CORSO" or lid not in aperta:
            aperta[lid] = stato

    if iscrizioni is None:
        iscrizioni = (TrainingEnrollment.objects.filter(sessione__corso=corso, legacy_anagrafica_id__in=ids)
                      .select_related("avanzamento_online"))
    # Le iscrizioni di edizioni annullate non contano: né «in corso» né esito.
    from ..models_formazione import TrainingSession
    sess_annullate = set(TrainingSession.objects.filter(corso=corso, stato="ANNULLATA").values_list("pk", flat=True))
    for e in iscrizioni:
        lid = e.legacy_anagrafica_id
        if lid not in ids or e.pk in enr_con_record or e.sessione_id in sess_annullate:
            continue
        try:
            prog = e.avanzamento_online
        except Exception:
            prog = None
        superata_il = getattr(prog, "superata_il", None)
        if e.stato == "COMPLETATO" or e.verifica_superata or superata_il:
            _segna_superata(lid, e.data_verifica or _data_di(superata_il) or _data_di(getattr(e, "updated_at", None)))
        elif e.stato in ("ISCRITTO", "IN_CORSO"):
            _segna_aperta(lid, e.stato)
        elif e.stato in _DETTAGLIO_DA_FARE:
            esito.setdefault(lid, e.stato)

    for e in TrainingElearningEnrollment.objects.filter(corso=corso, legacy_anagrafica_id__in=ids).values(
            "legacy_anagrafica_id", "stato", "data_completamento", "record_completamento_id"):
        lid = e["legacy_anagrafica_id"]
        if e["stato"] == "COMPLETATO":
            if not e["record_completamento_id"]:
                _segna_superata(lid, e["data_completamento"])
        elif e["stato"] in ("ISCRITTO", "IN_CORSO"):
            _segna_aperta(lid, e["stato"])
        elif e["stato"] in _DETTAGLIO_DA_FARE:
            esito.setdefault(lid, e["stato"])

    for r in (TrainingElearningRispostaAperta.objects
              .filter(corso=corso, legacy_anagrafica_id__in=ids, superato=True, record__isnull=True)
              .exclude(stato=TrainingElearningRispostaAperta.SCARTATA).values("legacy_anagrafica_id", "inviato_il")):
        _segna_superata(r["legacy_anagrafica_id"], _data_di(r["inviato_il"]))

    for a in TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id__in=ids, stato="IN_CORSO").values(
            "legacy_anagrafica_id"):
        _segna_aperta(a["legacy_anagrafica_id"], "IN_CORSO")

    out: dict = {}
    for lid in ids:
        rec = ultimo_valido.get(lid)
        if rec is not None:
            out[lid] = StatoPersonaCorso(COMPLETATO, data=rec.data_completamento, record=rec)
            continue
        scaduto = ultimo_idoneo.get(lid)
        if lid in superata:
            quando = superata[lid]
            if scaduto is None or (quando is not None and quando > scaduto.data_completamento):
                out[lid] = StatoPersonaCorso(DA_REGISTRARE, data=quando)
                continue
        if scaduto is not None:
            out[lid] = StatoPersonaCorso(SCADUTO, data=scaduto.data_scadenza, record=scaduto)
            continue
        if lid in aperta:
            out[lid] = StatoPersonaCorso(IN_CORSO, "Iscritto" if aperta[lid] == "ISCRITTO" else "")
            continue
        ultimo = ultimo_qualsiasi.get(lid)
        if ultimo is not None:
            out[lid] = StatoPersonaCorso(DA_FARE, "Non idoneo", data=ultimo.data_completamento, record=ultimo)
            continue
        out[lid] = StatoPersonaCorso(DA_FARE, _DETTAGLIO_DA_FARE.get(esito.get(lid), ""))
    return out


def stato_persona_corso(corso, legacy_id, *, iscrizioni=None, oggi=None) -> StatoPersonaCorso:
    """Lo stato di una persona per un corso (vedi :func:`stati_persona_corso`)."""
    if not legacy_id or corso is None:
        return StatoPersonaCorso(DA_FARE)
    return stati_persona_corso(corso, [legacy_id], iscrizioni=iscrizioni, oggi=oggi).get(
        int(legacy_id), StatoPersonaCorso(DA_FARE))
