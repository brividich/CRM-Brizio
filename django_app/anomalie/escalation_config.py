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

# ── Automazioni aggiuntive (tutte spente di default) ───────────────────────
# Girano dentro lo stesso task orario `anomalie_escalation`: nessuno Schedule nuovo.
KEY_RICORRENZA_ATTIVO = "anomalie_auto_ricorrenza_attivo"
KEY_RICORRENZA_N = "anomalie_auto_ricorrenza_n"
KEY_RICORRENZA_GIORNI = "anomalie_auto_ricorrenza_giorni"
KEY_RDC_ATTIVO = "anomalie_auto_rdc_attivo"
KEY_RDC_GIORNI = "anomalie_auto_rdc_giorni"
KEY_DIGEST_ATTIVO = "anomalie_auto_digest_attivo"
KEY_OP_COMPLETATO_ATTIVO = "anomalie_auto_op_completato_attivo"

DEFAULT_RICORRENZA_N = 3
RICORRENZA_N_MIN, RICORRENZA_N_MAX = 2, 50
DEFAULT_RICORRENZA_GIORNI = 30
RICORRENZA_GIORNI_MIN, RICORRENZA_GIORNI_MAX = 1, 365
DEFAULT_RDC_GIORNI = 3
RDC_GIORNI_MIN, RDC_GIORNI_MAX = 1, 60


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
        "ricorrenza_attivo": _parse_bool(SiteConfig.get(KEY_RICORRENZA_ATTIVO, ""), default=False),
        "ricorrenza_n": _clamp_int(
            SiteConfig.get(KEY_RICORRENZA_N, "") or DEFAULT_RICORRENZA_N,
            DEFAULT_RICORRENZA_N, RICORRENZA_N_MIN, RICORRENZA_N_MAX,
        ),
        "ricorrenza_giorni": _clamp_int(
            SiteConfig.get(KEY_RICORRENZA_GIORNI, "") or DEFAULT_RICORRENZA_GIORNI,
            DEFAULT_RICORRENZA_GIORNI, RICORRENZA_GIORNI_MIN, RICORRENZA_GIORNI_MAX,
        ),
        "rdc_attivo": _parse_bool(SiteConfig.get(KEY_RDC_ATTIVO, ""), default=False),
        "rdc_giorni": _clamp_int(
            SiteConfig.get(KEY_RDC_GIORNI, "") or DEFAULT_RDC_GIORNI,
            DEFAULT_RDC_GIORNI, RDC_GIORNI_MIN, RDC_GIORNI_MAX,
        ),
        "digest_attivo": _parse_bool(SiteConfig.get(KEY_DIGEST_ATTIVO, ""), default=False),
        "op_completato_attivo": _parse_bool(SiteConfig.get(KEY_OP_COMPLETATO_ATTIVO, ""), default=False),
    }


def save_automazioni_config(payload: dict) -> bool:
    """Persiste le automazioni aggiuntive; le chiavi assenti dal payload restano invariate."""
    from core.models import SiteConfig

    if not isinstance(payload, dict):
        return False
    ok = True
    flags = {
        "ricorrenza_attivo": (KEY_RICORRENZA_ATTIVO, "Anomalie: allarme difetto ricorrente per P/N."),
        "rdc_attivo": (KEY_RDC_ATTIVO, "Anomalie: promemoria RDC richiesto senza numero."),
        "digest_attivo": (KEY_DIGEST_ATTIVO, "Anomalie: digest settimanale KPI ai supervisori."),
        "op_completato_attivo": (KEY_OP_COMPLETATO_ATTIVO, "Anomalie: mail a CC/CAR quando un OP ha tutte le anomalie chiuse."),
    }
    for field, (key, desc) in flags.items():
        if field in payload:
            ok &= SiteConfig.set(key, "1" if bool(payload.get(field)) else "0", desc)
    numbers = {
        "ricorrenza_n": (KEY_RICORRENZA_N, DEFAULT_RICORRENZA_N, RICORRENZA_N_MIN, RICORRENZA_N_MAX,
                         "Anomalie: numero di anomalie sullo stesso P/N che fa scattare l'allarme."),
        "ricorrenza_giorni": (KEY_RICORRENZA_GIORNI, DEFAULT_RICORRENZA_GIORNI, RICORRENZA_GIORNI_MIN,
                              RICORRENZA_GIORNI_MAX, "Anomalie: finestra in giorni dell'allarme ricorrenza P/N."),
        "rdc_giorni": (KEY_RDC_GIORNI, DEFAULT_RDC_GIORNI, RDC_GIORNI_MIN, RDC_GIORNI_MAX,
                       "Anomalie: giorni oltre cui un RDC richiesto senza numero genera il promemoria."),
    }
    for field, (key, default, lo, hi, desc) in numbers.items():
        if field in payload:
            ok &= SiteConfig.set(key, str(_clamp_int(payload.get(field), default, lo, hi)), desc)
    return ok


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
