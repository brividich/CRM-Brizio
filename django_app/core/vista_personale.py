"""Vista personale: «cosa aspetta me», non «cosa posso vedere».

Le pagine personali («Le mie attività», la sezione in home, il pulsante «N da
approvare») riusano i controlli dei moduli. Quei controlli rispondono a «puoi
aprire/gestire?»: per un amministratore (ruolo legacy «admin», ruolo del portale
con ``amministratore``), un superuser o un ruolo con ``vede_tutto`` la risposta è
sempre sì, e le pagine personali si riempivano di voci di tutta l'azienda.

Dentro :func:`vista_personale` la persona conta solo per i ruoli che ha:

- ``is_legacy_admin`` risponde False (vale per tutti i chiamanti, anche il resolver ACL);
- ``request.user.is_superuser`` è False per la durata del blocco;
- il contesto dei permessi perde amministratore, superuser e ``vede_tutto``.

I permessi veri (aprire pagine, impostazioni) non cambiano: il blocco vale solo
per il calcolo delle voci personali e si chiude prima del rendering.
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from contextvars import ContextVar

_ATTIVA: ContextVar[bool] = ContextVar("vista_personale", default=False)
_ASSENTE = object()


def attiva() -> bool:
    """True dentro :func:`vista_personale`."""
    return _ATTIVA.get()


def _contesto_personale(request):
    from core.permessi.motore import contesto_per

    ctx = contesto_per(request)
    return dataclasses.replace(
        ctx,
        superuser=False,
        amministratore=False,
        ruoli=[dataclasses.replace(r, vede_tutto=False, amministratore=False) for r in ctx.ruoli],
    )


@contextmanager
def vista_personale(request):
    """Calcola le voci personali come se la persona non fosse amministratore."""
    if _ATTIVA.get():
        yield
        return
    user = getattr(request, "user", None)
    token = _ATTIVA.set(True)
    era_superuser = bool(getattr(user, "is_superuser", False))
    ctx_prima = getattr(user, "_permessi_contesto", _ASSENTE) if user is not None else _ASSENTE
    try:
        if user is not None and getattr(user, "is_authenticated", False):
            try:
                personale = _contesto_personale(request)
            except Exception:
                personale = None
            if era_superuser:
                user.is_superuser = False
            if personale is not None:
                try:
                    user._permessi_contesto = personale
                except AttributeError:
                    pass
        yield
    finally:
        _ATTIVA.reset(token)
        if user is not None:
            if era_superuser:
                user.is_superuser = True
            try:
                if ctx_prima is _ASSENTE:
                    if hasattr(user, "_permessi_contesto"):
                        del user._permessi_contesto
                else:
                    user._permessi_contesto = ctx_prima
            except AttributeError:
                pass
