"""Registro «Mail inviate» agganciato all'invio: nessuna mail del portale resta fuori.

``installa()`` (da ``CoreConfig.ready``) avvolge ``EmailMessage.send``: ogni messaggio
partito (o fallito) scrive una riga in ``automazioni.EmailInviata`` con origine
``modulo`` e, come sorgente, l'app che ha chiamato l'invio. I punti che registravano
già da sé (azioni delle regole, assenze, anomalie, ``send_hub_mail``) chiamano
``automazioni.mail_inviate.registra`` subito dopo l'invio: quella chiamata completa
la riga appena scritta (stesso oggetto e destinatari) invece di crearne una seconda.

Best-effort: un errore del registro viene solo loggato, l'invio non ne risente.
Del messaggio si salvano destinatari, oggetto ed esito, mai il testo.
"""
from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar

logger = logging.getLogger(__name__)

ORIGINE_MODULO = "modulo"

# Righe scritte dall'aggancio e non ancora completate da ``registra``: (pk, oggetto, indirizzi, istante).
_pendenti: ContextVar[list | None] = ContextVar("mail_registro_pendenti", default=None)
_MAX_PENDENTI = 20
_SCADENZA_SECONDI = 120

_MODULI_TECNICI = (
    "django.", "core.mail_registro", "core.email_utils", "automazioni.mail_inviate",
    "smtplib", "email.", "ssl", "socket", "threading", "concurrent.", "unittest.",
)


def _indirizzi(msg) -> list[str]:
    try:
        return [str(x).strip().lower() for x in msg.recipients() if str(x or "").strip()]
    except Exception:
        return []


def _modulo_chiamante() -> str:
    """App che ha chiamato ``send`` (la prima cornice fuori da Django e dal registro)."""
    try:
        frame = sys._getframe(2)
    except ValueError:
        return ""
    while frame is not None:
        nome = str(frame.f_globals.get("__name__") or "")
        if nome and not nome.startswith(_MODULI_TECNICI) and nome != "__main__":
            return nome.split(".")[0][:60]
        frame = frame.f_back
    return ""


def _scrivi(msg, *, errore: str = "") -> None:
    try:
        from automazioni.mail_inviate import _crea_riga
        from automazioni.managed_flows import codice_flusso_corrente

        sorgente = codice_flusso_corrente() or _modulo_chiamante()
        bcc = [str(x).strip().lower() for x in (getattr(msg, "bcc", None) or []) if str(x or "").strip()]
        riga = _crea_riga(
            origine=ORIGINE_MODULO,
            destinatari=list(getattr(msg, "to", None) or []),
            copia=list(getattr(msg, "cc", None) or []) + bcc,
            oggetto=str(getattr(msg, "subject", "") or ""),
            sorgente=sorgente,
            errore=errore,
        )
        if riga is None:
            return
        elenco = [p for p in (_pendenti.get() or []) if time.monotonic() - p[3] < _SCADENZA_SECONDI]
        elenco.append((riga.pk, str(msg.subject or "").strip()[:255], set(_indirizzi(msg)), time.monotonic()))
        _pendenti.set(elenco[-_MAX_PENDENTI:])
    except Exception:
        logger.warning("mail_registro: riga non scritta", exc_info=True)


def prendi_pendente(oggetto: str, destinatari) -> int | None:
    """PK della riga scritta dall'aggancio per la stessa mail (e la toglie dalle pendenti)."""
    elenco = _pendenti.get()
    if not elenco:
        return None
    oggetto = str(oggetto or "").strip()[:255]
    if isinstance(destinatari, str):
        destinatari = [destinatari]
    cercati = {str(x).strip().lower() for x in (destinatari or []) if str(x or "").strip()}
    adesso = time.monotonic()
    for i, (pk, ogg, indirizzi, istante) in enumerate(elenco):
        if adesso - istante >= _SCADENZA_SECONDI or ogg != oggetto:
            continue
        if cercati and indirizzi and not (cercati & indirizzi):
            continue
        _pendenti.set(elenco[:i] + elenco[i + 1:])
        return pk
    return None


def installa() -> None:
    """Avvolge ``EmailMessage.send`` una volta sola (idempotente)."""
    from django.core.mail.message import EmailMessage

    if getattr(EmailMessage.send, "_hub_registro", False):
        return
    originale = EmailMessage.send

    def send(self, fail_silently=False):
        if not self.recipients():
            return originale(self, fail_silently=fail_silently)
        try:
            inviate = originale(self, fail_silently=fail_silently)
        except Exception as exc:
            _scrivi(self, errore=f"{type(exc).__name__}: {exc}"[:2000])
            raise
        _scrivi(self, errore="" if inviate else "Nessuna mail consegnata al server di posta.")
        return inviate

    send._hub_registro = True
    send.__wrapped__ = originale
    EmailMessage.send = send
