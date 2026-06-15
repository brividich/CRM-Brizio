"""
Configurazione dell'escalation "ticket urgenti non assegnati", gestita da UI.

Speculare a ``anomalie/escalation_config.py``: centralizza chiavi SiteConfig,
default e (de)serializzazione così che sia il task ``run_tickets_escalation`` sia
la pagina Impostazioni ticket leggano/scrivano dalla stessa fonte, senza toccare
CLI, .env o cron.

Cadenza: lo Schedule django-q resta sempre registrato (orario); il task aggiorna
SEMPRE i promemoria in dashboard e invia il RESOCONTO email solo se ``attivo`` è
on e siamo nel giorno lavorativo (lun-ven) all'``ora_invio`` configurata.

Criterio di escalation: un ticket entra nel set se è ancora APERTA, senza
assegnatario (``assegnato_a`` vuoto) ed è URGENTE (o ``incide_sicurezza``, che
forza URGENTE) da più di ``soglia_ore`` ore dalla creazione.
"""
from __future__ import annotations

# ── Chiavi SiteConfig ──────────────────────────────────────────────────────
KEY_ATTIVO = "tickets_escalation_attivo"
KEY_SOGLIA_ORE = "tickets_escalation_soglia_ore"
KEY_ORA_INVIO = "tickets_escalation_ora_invio"

DEFAULT_SOGLIA_ORE = 4
SOGLIA_MIN = 1
SOGLIA_MAX = 168  # 7 giorni

DEFAULT_ORA_INVIO = 8
ORA_MIN = 0
ORA_MAX = 23

# Etichetta cadenza mostrata in UI.
CADENZA_LABEL = "Ogni giorno lavorativo (lun-ven)"


def _parse_bool(raw: str, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "on", "yes", "si", "sì"}


def _clamp_int(raw, default: int, lo: int, hi: int) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


def get_escalation_config() -> dict:
    """Legge la configurazione corrente da SiteConfig con fallback ai default.

    Degrada in sicurezza (SiteConfig.get assorbe DatabaseError ritornando il default).
    """
    from core.models import SiteConfig

    soglia = _clamp_int(
        SiteConfig.get(KEY_SOGLIA_ORE, "") or DEFAULT_SOGLIA_ORE,
        DEFAULT_SOGLIA_ORE, SOGLIA_MIN, SOGLIA_MAX,
    )
    ora = _clamp_int(
        SiteConfig.get(KEY_ORA_INVIO, "") or DEFAULT_ORA_INVIO,
        DEFAULT_ORA_INVIO, ORA_MIN, ORA_MAX,
    )
    return {
        "attivo": _parse_bool(SiteConfig.get(KEY_ATTIVO, ""), default=False),
        "soglia_ore": soglia,
        "ora_invio": ora,
        "cadenza_label": CADENZA_LABEL,
    }


def save_escalation_config(*, attivo: bool, soglia_ore: int, ora_invio: int) -> bool:
    """Persiste la configurazione in SiteConfig. Ritorna True se tutto salvato."""
    from core.models import SiteConfig

    soglia = _clamp_int(soglia_ore, DEFAULT_SOGLIA_ORE, SOGLIA_MIN, SOGLIA_MAX)
    ora = _clamp_int(ora_invio, DEFAULT_ORA_INVIO, ORA_MIN, ORA_MAX)

    ok = True
    ok &= SiteConfig.set(
        KEY_ATTIVO, "1" if attivo else "0",
        "Ticket escalation: attiva/disattiva la mail di resoconto ticket urgenti non assegnati.",
    )
    ok &= SiteConfig.set(
        KEY_SOGLIA_ORE, str(soglia),
        "Ticket escalation: ore da APERTA senza assegnatario oltre cui il ticket urgente entra nel resoconto.",
    )
    ok &= SiteConfig.set(
        KEY_ORA_INVIO, str(ora),
        "Ticket escalation: ora di invio del resoconto giornaliero (giorni lavorativi).",
    )
    return ok
