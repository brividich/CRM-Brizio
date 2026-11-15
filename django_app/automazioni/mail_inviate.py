"""Registro «Mail inviate»: una riga per ogni mail partita, con esito.

Ogni ``EmailMessage.send`` del portale scrive la sua riga da sé (``core.mail_registro``,
origine «modulo»). Le azioni delle automazioni, le mail dirette delle assenze, le mail
Anomalie e ``core.email_utils.send_hub_mail`` chiamano poi :func:`registra`, che
completa quella riga con tipo di mail, regola, run log e richiesta. Best-effort:
un errore di scrittura viene solo loggato, l'invio non ne risente.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterable

from django.db import transaction

logger = logging.getLogger(__name__)

ORIGINI = {
    "automazione": "Automazione",
    "modulo": "Mail dei moduli",
    "hub": "Promemoria e avvisi dei moduli",
    "approvazione": "Richiesta di approvazione",
    "assenze_modifica": "Assenze · richiesta modificata",
    "assenze_eliminazione": "Assenze · richiesta eliminata",
    "assenze_sollecito": "Assenze · sollecito al capo",
    "assenze_esito": "Assenze · esito al dipendente",
    "assenze_certificato": "Assenze · certificato medico mancante",
    # Modulo Anomalie: "anomalie_" + AnomalieEmailLog.Kind.
    "anomalie_mail_action": "Anomalie · link di decisione al capocommessa",
    "anomalie_conferma_aggiornamenti": "Anomalie · conferma aggiornamenti",
    "anomalie_escalation_resoconto": "Anomalie · resoconto escalation",
    "anomalie_ricorrenza_pn": "Anomalie · difetto ricorrente per P/N",
    "anomalie_digest_settimanale": "Anomalie · digest settimanale",
    "anomalie_op_completato": "Anomalie · OP completato",
    "anomalie_alert_admin": "Anomalie · avviso invio non riuscito",
    "anomalie_altro": "Anomalie · altre mail",
}


def _elenco(indirizzi: Iterable[str] | str | None) -> str:
    if not indirizzi:
        return ""
    if isinstance(indirizzi, str):
        indirizzi = [indirizzi]
    return ", ".join(dict.fromkeys(str(i).strip().lower() for i in indirizzi if str(i or "").strip()))


def _crea_riga(*, origine, destinatari, oggetto="", copia=None, sorgente="", record_id=None,
               errore="", regola=None, run_log=None, regola_id=None, run_log_id=None):
    """Crea la riga (savepoint); None se la scrittura fallisce."""
    try:
        from .models import EmailInviata

        with transaction.atomic():
            return EmailInviata.objects.create(
                origine=str(origine)[:40],
                sorgente=str(sorgente or "")[:60],
                record_id="" if record_id in (None, "") else str(record_id)[:60],
                destinatari=_elenco(destinatari),
                copia=_elenco(copia),
                oggetto=str(oggetto or "")[:255],
                esito=EmailInviata.ESITO_ERRORE if errore else EmailInviata.ESITO_INVIATA,
                errore=str(errore or "")[:2000],
                regola_id=getattr(regola, "pk", None) or regola_id,
                run_log_id=getattr(run_log, "pk", None) or run_log_id,
            )
    except Exception:
        logger.warning("mail_inviate: riga del registro non scritta (%s)", origine, exc_info=True)
        return None


def registra(
    *,
    origine: str,
    destinatari: Iterable[str] | str | None,
    oggetto: str = "",
    copia: Iterable[str] | str | None = None,
    sorgente: str = "",
    record_id=None,
    errore: str = "",
    regola=None,
    run_log=None,
) -> None:
    """Scrive la riga del registro, o completa quella appena scritta dall'invio. Non solleva mai."""
    # Mail di un flusso gestito (non di una regola): vincono codice, regola e run log del
    # flusso, così resta collegata anche se il chiamante passa il tipo di mail in Sorgente.
    flusso = {} if getattr(regola, "pk", None) else flusso_della_mail(oggetto)
    if flusso.get("code"):
        sorgente = flusso["code"]
    if flusso:
        if not getattr(regola, "pk", None) and flusso.get("rule_id"):
            regola = _Rif(flusso["rule_id"])
        if not getattr(run_log, "pk", None) and flusso.get("run_log_id"):
            run_log = _Rif(flusso["run_log_id"])
    try:
        from core.mail_registro import prendi_pendente

        pk = prendi_pendente(oggetto, destinatari)
    except Exception:
        pk = None
    if pk:
        try:
            from .models import EmailInviata

            campi = {"origine": str(origine)[:40]}
            if sorgente:
                campi["sorgente"] = str(sorgente)[:60]
            if record_id not in (None, ""):
                campi["record_id"] = str(record_id)[:60]
            if getattr(regola, "pk", None):
                campi["regola_id"] = regola.pk
            if getattr(run_log, "pk", None):
                campi["run_log_id"] = run_log.pk
            if errore:
                campi.update(esito=EmailInviata.ESITO_ERRORE, errore=str(errore)[:2000])
            with transaction.atomic():
                if EmailInviata.objects.filter(pk=pk).update(**campi):
                    return
        except Exception:
            logger.warning("mail_inviate: riga dell'invio non completata (%s)", origine, exc_info=True)
    _crea_riga(origine=origine, destinatari=destinatari, oggetto=oggetto, copia=copia, sorgente=sorgente,
               record_id=record_id, errore=errore, regola=regola, run_log=run_log)


class _Rif:
    """Riferimento per chiave (regola/run log) senza caricare l'oggetto."""

    def __init__(self, pk):
        self.pk = pk


def flussi_per_riga(righe) -> None:
    """Aggancia a ogni riga il flusso che l'ha mandata (``riga.flusso``), anche per le
    righe senza regola, risalendo dal codice del flusso salvato in Sorgente."""
    from django.db.models import Q

    from .managed_flows import catalog
    from .models import ManagedFlow

    cat = catalog()
    righe = list(righe)
    codici = {r.sorgente for r in righe if r.sorgente in cat}
    regole = {r.regola_id for r in righe if r.regola_id}
    legami = ManagedFlow.objects.select_related("rule").filter(
        Q(code__in=codici) | Q(rule_id__in=regole)
    ) if (codici or regole) else []
    per_codice = {b.code: b for b in legami}
    per_regola = {b.rule_id: b for b in per_codice.values()}
    # Righe senza regola e senza codice del flusso (scritte prima del 15/11 o fuori dal
    # flusso, es. comando dall'Utilità di pianificazione): si riconoscono dall'oggetto.
    da_oggetto = {r.pk: flusso_da_oggetto(r.oggetto) for r in righe if not r.regola_id and r.sorgente not in cat}
    mancanti = {c for c in da_oggetto.values() if c} - set(per_codice)
    if mancanti:
        for b in ManagedFlow.objects.select_related("rule").filter(code__in=mancanti):
            per_codice[b.code] = b
    for r in righe:
        if r.regola_id:
            # Una regola esplicita vince sempre (es. AU34 eseguita dal processore della coda).
            b = per_regola.get(r.regola_id)
        else:
            b = per_codice.get(r.sorgente) or per_codice.get(da_oggetto.get(r.pk) or "")
        if b is not None:
            r.flusso = {
                "codice": b.code,
                "nome": cat.get(b.code, {}).get("label") or b.rule.name,
                "rule_id": b.rule_id,
                "attivo": bool(b.rule.is_active and not b.rule.is_draft),
            }
        elif r.regola_id and r.regola is not None:
            r.flusso = {"codice": "", "nome": r.regola.name, "rule_id": r.regola_id,
                        "attivo": bool(r.regola.is_active and not r.regola.is_draft)}
        else:
            r.flusso = None


# Il processore della coda è un flusso «contenitore»: le mail delle regole che esegue
# appartengono alle regole, non a lui.
FLUSSI_CONTENITORE = {"automation_queue"}

# Oggetti delle mail di flussi pianificati che non sono digest (vedi schedules.DIGEST_OGGETTO).
ALTRI_OGGETTI: dict[str, tuple[str, ...]] = {
    "infra_health_alert": ("[SERVER CRITICO] ‹…›",),
    "backup_health_alert": ("[BACKUP CRITICO] ‹…›",),
}

_MODELLI: list | None = None


def _modelli_oggetto() -> list:
    """(regex, codice) dagli oggetti censiti: N = numero, gg-mm-aaaa = data, ‹…› = testo."""
    global _MODELLI
    if _MODELLI is None:
        import re

        from .schedules import DIGEST_OGGETTO

        segnaposto = {"gg-mm-aaaa": r"\d{2}-\d{2}-\d{4}", "N": r"\d+"}
        pezzi_rx = re.compile(r"(‹[^›]*›|gg-mm-aaaa|(?<![A-Za-z])N(?![A-Za-z]))")
        modelli = []
        for codice, serie in list(DIGEST_OGGETTO.items()) + list(ALTRI_OGGETTI.items()):
            for testo in serie:
                parti = []
                for pezzo in pezzi_rx.split(testo):
                    if pezzo.startswith("‹"):
                        parti.append(".+")
                    elif pezzo in segnaposto:
                        parti.append(segnaposto[pezzo])
                    else:
                        parti.append(re.escape(pezzo))
                modelli.append((re.compile("".join(parti) + r"\s*$"), codice))
        _MODELLI = modelli
    return _MODELLI


def flusso_da_oggetto(oggetto: str) -> str:
    """Codice del flusso pianificato riconosciuto dall'oggetto della mail ('' se nessuno o più d'uno)."""
    testo = str(oggetto or "").strip()
    if not testo:
        return ""
    trovati = {codice for rx, codice in _modelli_oggetto() if rx.match(testo)}
    return trovati.pop() if len(trovati) == 1 else ""


def flusso_della_mail(oggetto: str = "") -> dict:
    """Flusso a cui appartiene una mail in uscita: quello in esecuzione (non la coda) o,
    fuori da un flusso, quello riconosciuto dall'oggetto. ``{}`` se nessuno."""
    try:
        from .managed_flows import flusso_corrente

        flusso = flusso_corrente() or {}
        if flusso.get("code") and flusso["code"] not in FLUSSI_CONTENITORE:
            return flusso
        regola = _regola_in_corso.get()
        if regola and regola.get("rule_id"):
            # Mail partita durante un'azione di una regola (es. AU eseguita dalla coda).
            return {"code": "", **regola}
        codice = flusso_da_oggetto(oggetto)
        if codice:
            from .models import ManagedFlow

            rule_id = ManagedFlow.objects.filter(code=codice).values_list("rule_id", flat=True).first()
            return {"code": codice, "rule_id": rule_id, "run_log_id": None}
    except Exception:
        logger.warning("mail_inviate: flusso della mail non determinato", exc_info=True)
    return {}


def prefissi_oggetto(codice: str) -> list[str]:
    """Parte fissa iniziale degli oggetti censiti di un flusso (per filtrare le righe senza regola)."""
    import re

    from .schedules import DIGEST_OGGETTO

    serie = DIGEST_OGGETTO.get(codice) or ALTRI_OGGETTI.get(codice) or ()
    prefissi = []
    for testo in serie:
        fisso = re.split(r"‹|gg-mm-aaaa|(?<![A-Za-z])N(?![A-Za-z])", testo, maxsplit=1)[0]
        if len(fisso.strip()) >= 6:
            prefissi.append(fisso)
    return prefissi


_regola_in_corso = ContextVar("mail_inviate_regola_in_corso", default=None)


@contextmanager
def regola_in_corso(rule_id, run_log_id):
    """Durante un'azione di una regola le mail in uscita si collegano a regola e run log."""
    token = _regola_in_corso.set({"rule_id": rule_id, "run_log_id": run_log_id} if rule_id else None)
    try:
        yield
    finally:
        _regola_in_corso.reset(token)
