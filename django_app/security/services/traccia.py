"""Traccia sigillata delle decisioni del SOC (ISO/IEC 27001:2022, controlli 8.8 e 8.15).

Ogni decisione, automatica o a mano, che cambia lo stato di un rilievo di sicurezza (alert,
caso, PC di una CVE, accettazione del rischio, termine di correzione) resta nella timeline del
SOC **e** nell'audit del portale (``core.audit.log_action``, modulo ``security``), che viene
sigillato ogni mese (``core/audit_sigilli``): la timeline si legge, l'audit si dimostra.

Qui passa solo l'essenziale: identificativi, codice della regola, motivo, riferimento alla
prova, chi ha deciso. Mai corpi di mail, payload o dati personali. Mai bloccante: se l'audit
non si scrive, la decisione del SOC resta valida e l'errore va nel log.
"""
from __future__ import annotations

import logging

from core.audit import log_action

logger = logging.getLogger(__name__)

MODULO = "security"
SISTEMA = "system"

# Azioni registrate (prefisso ``soc_`` come le decisioni sulle proposte dell'AI già in audit).
ALERT_STATO = "soc_alert_stato"
ALERT_AUTO_RISOLTO = "soc_alert_auto_risolto"
CASO_STATO = "soc_caso_stato"
CASO_AUTO_CHIUSO = "soc_caso_auto_chiuso"
CVE_PC_ESCLUSO = "soc_cve_pc_escluso"
CVE_PC_INCLUSO = "soc_cve_pc_incluso"
CVE_RECIDIVA = "soc_cve_recidiva"
CVE_TERMINE_SCADUTO = "soc_cve_termine_scaduto"
CVE_TERMINE_RIENTRATO = "soc_cve_termine_rientrato"
RISCHIO_ACCETTATO = "soc_rischio_accettato"
RISCHIO_REVOCATO = "soc_rischio_revocato"
RISCHIO_SCADUTO = "soc_rischio_scaduto"
RISCHIO_IN_SCADENZA = "soc_rischio_in_scadenza"


def _pulito(valore):
    """Valori brevi e serializzabili: l'audit non è un archivio di payload."""
    if isinstance(valore, (list, tuple, set)):
        return [_pulito(v) for v in list(valore)[:50]]
    if isinstance(valore, dict):
        return {str(k): _pulito(v) for k, v in list(valore.items())[:30]}
    if hasattr(valore, "isoformat"):
        return valore.isoformat()
    if isinstance(valore, str):
        return valore[:500]
    return valore


def registra(azione, dettaglio=None, *, oggetto=None, request=None, attore=""):
    """Una riga di audit sigillato per una decisione del SOC.

    ``attore`` è chi ha deciso quando non c'è una richiesta (``system`` per gli automatismi,
    il nome utente per le azioni dei servizi chiamati dalle viste); con ``request`` l'audit
    legge da solo l'utente, l'IP e l'eventuale impersonazione.
    """
    payload = {str(k): _pulito(v) for k, v in (dettaglio or {}).items() if v not in (None, "", [], {})}
    if attore and "actor" not in payload:
        payload["actor"] = str(attore)[:150]
    elif request is None and "actor" not in payload:
        payload["actor"] = SISTEMA
    try:
        log_action(request, azione, MODULO, payload, oggetto=oggetto)
    except Exception:  # noqa: BLE001 - l'audit non deve mai fermare la decisione
        logger.exception("Traccia SOC non scritta: %s", azione)
