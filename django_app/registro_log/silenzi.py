"""Regole di silenzio del catalogo: eventi ripetuti che non serve vedere.

Le regole non cancellano né marcano niente: si applicano al momento della lettura (``escludi``),
quindi togliere o far scadere una regola rimette subito in vista gli eventi, anche quelli passati.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

DURATE = (("", "Sempre"), ("7", "7 giorni"), ("30", "30 giorni"), ("90", "90 giorni"))


def regole_in_vigore() -> list:
    from .models import RegolaSilenzio

    ora = timezone.now()
    return list(RegolaSilenzio.objects.filter(attiva=True).filter(Q(scade_il__isnull=True) | Q(scade_il__gt=ora)))


def q_regola(r) -> Q:
    q = Q(categoria=r.categoria)
    if r.account:
        q &= Q(account__iexact=r.account) | Q(account__iendswith="\\" + r.account)
    if r.host:
        q &= Q(host__iexact=r.host) | Q(host__istartswith=r.host + ".")
    if r.testo:
        q &= Q(descrizione__icontains=r.testo)
    return q


def q_silenziati(regole=None) -> Q | None:
    regole = regole_in_vigore() if regole is None else regole
    if not regole:
        return None
    q = Q()
    for r in regole:
        q |= q_regola(r)
    return q


def escludi(qs, regole=None):
    """Il queryset senza gli eventi silenziati."""
    q = q_silenziati(regole)
    return qs.exclude(q) if q is not None else qs


def solo_silenziati(qs, regole=None):
    q = q_silenziati(regole)
    return qs.filter(q) if q is not None else qs.none()


def crea(*, categoria: str, account: str, host: str, testo: str, motivo: str, giorni: str, utente: str):
    from .models import RegolaSilenzio

    scade = timezone.now() + timedelta(days=int(giorni)) if (giorni or "").isdigit() else None
    return RegolaSilenzio.objects.create(categoria=categoria, account=account[:150], host=host[:255], testo=testo[:200],
                                         motivo=motivo[:500], creata_da=utente[:150], scade_il=scade)


def nome_breve(host: str) -> str:
    """``DC01.esempio.local`` → ``DC01``: la regola vale anche per il nome completo."""
    return (host or "").split(".")[0]


def corrisponde(r, *, categoria: str, account: str, host: str, descrizione: str) -> bool:
    """La stessa regola di :func:`q_regola`, su una riga già letta."""
    if r.categoria != categoria:
        return False
    if r.account:
        a = (account or "").lower()
        if not (a == r.account.lower() or a.endswith("\\" + r.account.lower())):
            return False
    if r.host:
        h = (host or "").lower()
        if not (h == r.host.lower() or h.startswith(r.host.lower() + ".")):
            return False
    return not r.testo or r.testo.lower() in (descrizione or "").lower()


def silenziato(regole, **campi) -> bool:
    return any(corrisponde(r, **campi) for r in regole)
