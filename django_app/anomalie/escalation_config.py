"""
Configurazione del promemoria/escalation anomalie "OP da controllare", gestita da UI.

Centralizza chiavi SiteConfig, default e (de)serializzazione tipizzata così che sia il
management command/task `run_anomalie_escalation` sia la pagina Impostazioni del modulo
anomalie leggano/scrivano dalla stessa fonte, senza toccare CLI, .env o cron.

Cadenza fissa: il resoconto email parte alle ore `ora_invio` (default 06:00) di ogni
giorno lavorativo (lun-ven). Lo Schedule django-q resta sempre registrato (orario) e il
task si auto-silenzia sull'email se `attivo` è off o se non è giorno/ora di invio; i
promemoria in dashboard vengono comunque aggiornati a ogni run.

I destinatari "supervisori" NON stanno qui: sono nella config liste anomalie alla chiave
`escalation_supervisori` (vedi ANOMALIE_LIST_KEYS in anomalie/views.py), coerente con le
altre liste email (es. rdc_segnalazione).
"""
from __future__ import annotations

# ── Chiavi SiteConfig ──────────────────────────────────────────────────────
KEY_ATTIVO = "anomalie_escalation_attivo"
KEY_SOGLIA_ORE = "anomalie_escalation_soglia_ore"
KEY_ORA_INVIO = "anomalie_escalation_ora_invio"

DEFAULT_SOGLIA_ORE = 24
SOGLIA_MIN = 1
SOGLIA_MAX = 720  # 30 giorni

DEFAULT_ORA_INVIO = 6
ORA_MIN = 0
ORA_MAX = 23

# Stato avanzamento che identifica un'anomalia "da gestire" (mai toccata dal CC/CAR).
STATO_DA_GESTIRE = "In attesa"

# Chiave della config liste anomalie per i destinatari supervisori del resoconto.
LISTA_SUPERVISORI_KEY = "escalation_supervisori"

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
        "Anomalie escalation: attiva/disattiva la mail di resoconto OP da controllare.",
    )
    ok &= SiteConfig.set(
        KEY_SOGLIA_ORE, str(soglia),
        "Anomalie escalation: ore in stato 'In attesa' oltre cui l'OP entra nel resoconto.",
    )
    ok &= SiteConfig.set(
        KEY_ORA_INVIO, str(ora),
        "Anomalie escalation: ora di invio del resoconto giornaliero (giorni lavorativi).",
    )
    return ok
