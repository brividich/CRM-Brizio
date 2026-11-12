"""«Non voglio più aggiornamenti su questo OP».

Il pulsante nelle mail porta a una pagina con il login: la stessa mail arriva a più
persone (A + copia), quindi è l'accesso a dire chi ha cliccato, non il link. Un inoltro
non può silenziare qualcun altro e non serve nessuna superficie pubblica.

Cosa smette di arrivare per quell'OP: copia della mail di decisione, riepilogo modifiche,
decisioni all'operatore, OP completato, resoconto giornaliero.

Cosa resta, di proposito:
- la mail di decisione a chi deve decidere (il destinatario «A»): altrimenti non la
  vedrebbe nessuno;
- il riepilogo con RDC o segnalazione cliente alla lista dedicata: è un compito;
- «Segnala a CAR»: è una richiesta esplicita del capocommessa;
- le notifiche nel portale.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from django.urls import reverse

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_OP = 100


def op_pulito(op_id) -> str:
    """OP dal parametro dell'URL: "" se assente o troppo lungo."""
    value = str(op_id or "").strip()
    return value if len(value) <= MAX_OP else ""


def _op_key(op_id) -> str:
    return str(op_id or "").strip().lower()


def email_silenziate(op_id) -> set[str]:
    """Indirizzi (minuscoli) che hanno silenziato l'OP. In caso di errore nessuno:
    meglio una mail in più che una mail persa."""
    from .mail_action_models import AnomaliaOpSilenziata

    key = _op_key(op_id)
    if not key:
        return set()
    try:
        return set(AnomaliaOpSilenziata.objects.filter(op_key=key).values_list("email", flat=True))
    except Exception:
        logger.warning("silenzia_op: elenco non leggibile op=%s", op_id, exc_info=True)
        return set()


def togli_silenziati(op_id, emails, *, tieni=()) -> list[str]:
    """``emails`` senza chi ha silenziato l'OP, tranne gli indirizzi in ``tieni``."""
    emails = list(emails or [])
    silenziate = email_silenziate(op_id) - {str(e or "").strip().lower() for e in tieni}
    if not silenziate:
        return emails
    return [e for e in emails if str(e or "").strip().lower() not in silenziate]


def indirizzi_utente(user) -> list[str]:
    """Indirizzi con cui l'utente riceve le mail: email di notifica e email dell'utente."""
    trovati: list[str] = []
    try:
        legacy_id = int(user.profile.legacy_user_id)
    except Exception:
        legacy_id = None
    if legacy_id:
        try:
            from core.legacy_models import AnagraficaDipendente

            a = AnagraficaDipendente.objects.filter(utente_id=legacy_id).only("email_notifica").first()
            trovati.append(str(getattr(a, "email_notifica", "") or ""))
        except Exception:
            logger.warning("silenzia_op: email di notifica non letta", exc_info=True)
    trovati.append(str(getattr(user, "email", "") or ""))
    out: list[str] = []
    for email in trovati:
        email = email.strip().lower()
        # L'email dell'utente può contenere il login legacy: passa solo un indirizzo vero.
        if _EMAIL_RE.match(email) and len(email) <= 254 and email not in out:
            out.append(email)
    return out


def silenzia(op_id, user, nome: str = "") -> int:
    """Silenzia l'OP per tutti gli indirizzi dell'utente; ritorna quanti sono."""
    from .mail_action_models import AnomaliaOpSilenziata

    op = str(op_id or "").strip()
    indirizzi = indirizzi_utente(user)
    for email in indirizzi:
        AnomaliaOpSilenziata.objects.get_or_create(
            op_key=_op_key(op), email=email,
            defaults={"op_id": op, "utente": user, "nome": str(nome or "")[:200]},
        )
    return len(indirizzi)


def riattiva(op_id, user) -> int:
    from .mail_action_models import AnomaliaOpSilenziata

    deleted, _ = AnomaliaOpSilenziata.objects.filter(
        op_key=_op_key(op_id), email__in=indirizzi_utente(user),
    ).delete()
    return deleted


def op_silenziati_utente(user) -> list[str]:
    from .mail_action_models import AnomaliaOpSilenziata

    out: list[str] = []
    for op in AnomaliaOpSilenziata.objects.filter(email__in=indirizzi_utente(user)).values_list("op_id", flat=True):
        if op not in out:
            out.append(op)
    return out


def elenco() -> list:
    """Tutti gli OP silenziati, per il pannello Notifiche."""
    from .mail_action_models import AnomaliaOpSilenziata

    try:
        return list(AnomaliaOpSilenziata.objects.all()[:500])
    except Exception:
        logger.warning("silenzia_op: elenco pannello non leggibile", exc_info=True)
        return []


def link_silenzia(op_id, *, base: str | None = None) -> str:
    """Link del pulsante nelle mail; "" se manca ``SITE_URL``."""
    from core.accounts.portal_links import portal_link

    op = op_pulito(op_id)
    if not op:
        return ""
    return portal_link(f"{reverse('anomalie_op_silenzia')}?op={quote(op, safe='')}", base=base)
