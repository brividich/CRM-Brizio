"""
Configurazione dei solleciti di presa visione, gestita da UI.

Speculare a ``tickets/escalation_config.py``: centralizza chiavi SiteConfig,
default e (de)serializzazione così che sia il task ``run_assignment_lifecycle``
sia la card Impostazioni della dashboard admin leggano/scrivano dalla stessa
fonte, senza toccare CLI, .env o cron.

Nota ISO 9001/EN 9100: la marcatura OVERDUE delle assegnazioni scadute gira
SEMPRE (è lo stato dei dati, evidenza di distribuzione controllata); ``attivo``
governa solo l'invio delle email di sollecito.
"""
from __future__ import annotations

# ── Chiavi SiteConfig ──────────────────────────────────────────────────────
KEY_ATTIVO = "pr_reminder_attivo"
KEY_PRE_GIORNI = "pr_reminder_pre_giorni"
KEY_POST_CADENZA = "pr_reminder_post_cadenza_giorni"
KEY_DIGEST_GIORNO = "pr_reminder_digest_giorno"
KEY_DIGEST_DESTINATARI = "pr_reminder_digest_destinatari"

DEFAULT_PRE_GIORNI = [7, 2]
PRE_GIORNI_MIN = 0
PRE_GIORNI_MAX = 60
PRE_GIORNI_MAX_SOGLIE = 5

DEFAULT_POST_CADENZA = 7
POST_CADENZA_MIN = 1
POST_CADENZA_MAX = 60

# Giorni della settimana ammessi per il digest (vuoto = digest disattivo).
GIORNI_VALIDI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
DEFAULT_DIGEST_GIORNO = "lun"


def _parse_bool(raw, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "on", "yes", "si", "sì"}


def _clamp_int(raw, default: int, lo: int, hi: int) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


def _parse_pre_giorni(raw) -> list[int]:
    """CSV "7,2" -> [7, 2] (dedup, clamp, max N soglie, ordinati decrescenti)."""
    if raw is None or str(raw).strip() == "":
        return list(DEFAULT_PRE_GIORNI)
    values: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
        except ValueError:
            continue
        values.add(max(PRE_GIORNI_MIN, min(v, PRE_GIORNI_MAX)))
    if not values:
        return list(DEFAULT_PRE_GIORNI)
    return sorted(values, reverse=True)[:PRE_GIORNI_MAX_SOGLIE]


def _parse_destinatari(raw) -> list[str]:
    """CSV email -> lista normalizzata (trim, lowercase, dedup, ordine stabile)."""
    seen: list[str] = []
    for part in str(raw or "").split(","):
        email = part.strip().lower()
        if email and "@" in email and email not in seen:
            seen.append(email)
    return seen


def get_reminder_config() -> dict:
    """Legge la configurazione corrente da SiteConfig con fallback ai default."""
    from core.models import SiteConfig

    giorno = str(SiteConfig.get(KEY_DIGEST_GIORNO, DEFAULT_DIGEST_GIORNO) or "").strip().lower()
    if giorno not in GIORNI_VALIDI:
        giorno = ""  # valore non riconosciuto o vuoto = digest disattivo

    return {
        "attivo": _parse_bool(SiteConfig.get(KEY_ATTIVO, ""), default=False),
        "pre_giorni": _parse_pre_giorni(SiteConfig.get(KEY_PRE_GIORNI, "")),
        "post_cadenza_giorni": _clamp_int(
            SiteConfig.get(KEY_POST_CADENZA, "") or DEFAULT_POST_CADENZA,
            DEFAULT_POST_CADENZA, POST_CADENZA_MIN, POST_CADENZA_MAX,
        ),
        "digest_giorno": giorno,
        "digest_destinatari": _parse_destinatari(SiteConfig.get(KEY_DIGEST_DESTINATARI, "")),
    }


def save_reminder_config(
    *,
    attivo: bool,
    pre_giorni,
    post_cadenza_giorni,
    digest_giorno: str,
    digest_destinatari: str,
) -> bool:
    """Persiste la configurazione in SiteConfig. Ritorna True se tutto salvato.

    ``pre_giorni`` accetta CSV o lista; ``digest_destinatari`` CSV email.
    """
    from core.models import SiteConfig

    if isinstance(pre_giorni, (list, tuple)):
        pre_raw = ",".join(str(v) for v in pre_giorni)
    else:
        pre_raw = str(pre_giorni or "")
    pre = _parse_pre_giorni(pre_raw)
    post = _clamp_int(post_cadenza_giorni, DEFAULT_POST_CADENZA, POST_CADENZA_MIN, POST_CADENZA_MAX)
    giorno = str(digest_giorno or "").strip().lower()
    if giorno not in GIORNI_VALIDI:
        giorno = ""
    destinatari = _parse_destinatari(digest_destinatari)

    ok = True
    ok &= SiteConfig.set(
        KEY_ATTIVO, "1" if attivo else "0",
        "Presa visione: attiva/disattiva le email di sollecito (la marcatura Scaduta gira sempre).",
    )
    ok &= SiteConfig.set(
        KEY_PRE_GIORNI, ",".join(str(v) for v in pre),
        "Presa visione: soglie giorni pre-scadenza per i promemoria (CSV, es. 7,2).",
    )
    ok &= SiteConfig.set(
        KEY_POST_CADENZA, str(post),
        "Presa visione: ogni quanti giorni sollecitare le assegnazioni scadute.",
    )
    ok &= SiteConfig.set(
        KEY_DIGEST_GIORNO, giorno,
        "Presa visione: giorno della settimana del digest inadempienti ai gestori (vuoto = off).",
    )
    ok &= SiteConfig.set(
        KEY_DIGEST_DESTINATARI, ",".join(destinatari),
        "Presa visione: destinatari (email, CSV) del digest inadempienti.",
    )
    return ok
