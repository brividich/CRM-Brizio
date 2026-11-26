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

    from ..models_formazione import TrainingDeadline

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

    # Chiude solo un completamento valido oggi (idoneo, non scaduto, non nel futuro) e solo ciò che è
    # nato prima di esso: un completamento storico o importato non chiude il rinnovo aperto dopo.
    if record_valido(record):
        try:
            with transaction.atomic():
                chiudi_aperti(record)
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


def record_valido(record, *, oggi=None) -> bool:
    """Regola unica: un completamento vale oggi se è idoneo, non annullato, non scaduto e non ha una
    data futura. Stessa regola di :func:`completamento_valido` per un record già in mano."""
    from django.utils import timezone

    if record is None or not record.idoneo or getattr(record, "annullato_il", None):
        return False
    oggi = oggi or timezone.localdate()
    dc = _data_di(record.data_completamento)
    if dc is None or dc > oggi:
        return False
    return record.data_scadenza is None or record.data_scadenza >= oggi


def copre_oltre_preavviso(record, *, oggi=None) -> bool:
    """Il completamento tiene la persona in regola oltre ``GIORNI_PREAVVISO`` (o non scade): non
    c'è niente da rinnovare, quindi chiude anche ciò che è stato aperto dopo la sua data."""
    from datetime import timedelta

    from django.utils import timezone

    from ..scadenze_soglie import GIORNI_PREAVVISO

    if record.data_scadenza is None:
        return True
    oggi = oggi or timezone.localdate()
    return record.data_scadenza > oggi + timedelta(days=GIORNI_PREAVVISO)


def nato_entro(record, quando) -> bool:
    """``quando`` (data o datetime d'inizio di un'assegnazione / iscrizione) è nel ciclo del
    completamento: nato non dopo la data del completamento. Senza data: sì. Un completamento che
    copre oltre il preavviso chiude tutto (vedi :func:`copre_oltre_preavviso`); uno vicino alla
    scadenza non chiude il rinnovo aperto dopo."""
    if copre_oltre_preavviso(record):
        return True
    q = _data_di(quando)
    dc = _data_di(record.data_completamento)
    return q is None or dc is None or q <= dc


def chiudi_aperti(record) -> None:
    """Un corso = un completamento: con un completamento valido si chiudono le assegnazioni aperte,
    le iscrizioni e-learning e le iscrizioni alle sessioni online dello stesso corso e persona.
    Se il completamento scade entro il preavviso, solo quelle nate entro la sua data: il rinnovo
    aperto dopo resta aperto (un completamento storico o importato non lo chiude)."""
    from ..models_formazione import TrainingAssignment

    if not record_valido(record):
        return
    aperte = TrainingAssignment.objects.filter(
        corso_id=record.corso_id, legacy_anagrafica_id=record.legacy_anagrafica_id,
    ).exclude(stato__in=("COMPLETATO", "ESONERATO"))
    if not copre_oltre_preavviso(record):
        aperte = aperte.filter(data_assegnazione__lte=record.data_completamento)
    aperte.update(stato="COMPLETATO")
    chiudi_iscrizioni_elearning(record)
    from .sessione_online import completa_iscrizioni_da_record
    completa_iscrizioni_da_record(record)


def completamento_riusabile(corso, legacy_id, *, oggi=None):
    """Il completamento valido che una nuova fruizione dello stesso corso può riusare invece di
    crearne un altro; None se si deve registrare un nuovo completamento, cioè se:

    - non c'è un completamento valido;
    - scade entro ``GIORNI_PREAVVISO`` (è un rinnovo);
    - c'è un'assegnazione aperta del corso nata dopo quel completamento (rinnovo assegnato)."""
    from datetime import timedelta

    from django.utils import timezone

    from ..models_formazione import TrainingAssignment
    from ..scadenze_soglie import GIORNI_PREAVVISO

    oggi = oggi or timezone.localdate()
    rec = completamento_valido(corso, legacy_id, oggi=oggi)
    if rec is None:
        return None
    if rec.data_scadenza is not None and rec.data_scadenza <= oggi + timedelta(days=GIORNI_PREAVVISO):
        return None
    if (TrainingAssignment.objects.filter(corso=corso, legacy_anagrafica_id=legacy_id,
                                          data_assegnazione__gt=rec.data_completamento)
            .exclude(stato__in=("COMPLETATO", "ESONERATO")).exists()):
        return None
    return rec


def collega_iscrizione_a_completamento(enr):
    """Chi ha già un completamento riusabile del corso (vedi :func:`completamento_riusabile`) non
    ne crea un secondo dal portale: l'iscrizione e-learning si chiude su quel completamento.
    Ritorna il completamento (None se il corso è da fare)."""
    rec = completamento_riusabile(enr.corso, enr.legacy_anagrafica_id)
    if rec is None:
        return None
    if enr.stato != "COMPLETATO" or enr.record_completamento_id != rec.pk:
        enr.stato = "COMPLETATO"
        enr.record_completamento = rec
        enr.data_completamento = enr.data_completamento or _data_di(rec.data_completamento)
        enr.save(update_fields=["stato", "record_completamento", "data_completamento", "updated_at"])
    return rec


def chiudi_iscrizioni_elearning(record) -> int:
    """Iscrizioni e-learning aperte dello stesso corso e persona, nate entro il completamento:
    chiuse su quel completamento (un corso = un completamento). Solo per completamenti validi."""
    from ..models_formazione import TrainingElearningEnrollment

    if not record_valido(record):
        return 0
    n = 0
    for e in (TrainingElearningEnrollment.objects
              .filter(corso_id=record.corso_id, legacy_anagrafica_id=record.legacy_anagrafica_id)
              .exclude(stato="COMPLETATO")):
        if not nato_entro(record, e.data_iscrizione):
            continue
        e.stato = "COMPLETATO"
        e.record_completamento = record
        if not e.data_completamento:
            e.data_completamento = _data_di(record.data_completamento)
        e.save(update_fields=["stato", "record_completamento", "data_completamento", "updated_at"])
        n += 1
    return n


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
            .filter(corso=corso, legacy_anagrafica_id=legacy_id, idoneo=True, data_completamento__lte=oggi)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
            .order_by("-data_completamento", "-pk").first())


def ids_con_completamento_valido(corso, legacy_ids, *, oggi=None) -> set[int]:
    """Le persone (fra ``legacy_ids``) che hanno un completamento valido del corso."""
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    oggi = oggi or timezone.localdate()
    return set(TrainingEmployeeRecord.objects
               .filter(corso=corso, legacy_anagrafica_id__in=list(legacy_ids), idoneo=True,
                       data_completamento__lte=oggi)
               .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
               .values_list("legacy_anagrafica_id", flat=True))


def ids_in_regola(corso, legacy_ids, *, oggi=None) -> set[int]:
    """Le persone (fra ``legacy_ids``) già in regola col corso: completamento valido che non scade
    entro ``GIORNI_PREAVVISO`` (o senza scadenza). Non vanno riassegnate: non è ancora un rinnovo."""
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord
    from ..scadenze_soglie import GIORNI_PREAVVISO

    oggi = oggi or timezone.localdate()
    oltre = oggi + timedelta(days=GIORNI_PREAVVISO)
    return set(TrainingEmployeeRecord.objects
               .filter(corso=corso, legacy_anagrafica_id__in=list(legacy_ids), idoneo=True,
                       data_completamento__lte=oggi)
               .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gt=oltre))
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
    for r in (TrainingEmployeeRecord.objects.filter(corso=corso, legacy_anagrafica_id__in=ids,
                                                    data_completamento__lte=oggi)
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


def ids_con_completamento_valido_multi(corsi_ids, legacy_ids, *, oggi=None) -> set[tuple[int, int]]:
    """``{(legacy_id, corso_id)}`` con un completamento valido, per molti corsi e persone insieme.

    Stessa regola di :func:`ids_con_completamento_valido` (idoneo, non annullato,
    completato entro oggi, senza scadenza o non ancora scaduto) in poche query a
    blocchi di 1000 id (limite parametri di SQL Server): per Mansionario e gate
    Skill Matrix, che prima leggevano la cache ``TrainingDeadline``.
    """
    from django.db.models import Q
    from django.utils import timezone

    from ..models_formazione import TrainingEmployeeRecord

    oggi = oggi or timezone.localdate()
    corsi = sorted({int(c) for c in corsi_ids if c})
    ids = sorted({int(i) for i in legacy_ids if i})
    out: set[tuple[int, int]] = set()
    if not corsi or not ids:
        return out
    for i in range(0, len(ids), 1000):
        blocco = ids[i:i + 1000]
        out.update(
            TrainingEmployeeRecord.objects
            .filter(corso_id__in=corsi, legacy_anagrafica_id__in=blocco, idoneo=True,
                    data_completamento__lte=oggi)
            .filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=oggi))
            .values_list("legacy_anagrafica_id", "corso_id")
            .distinct()
        )
    return out
