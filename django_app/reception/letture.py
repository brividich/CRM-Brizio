"""Le letture di ``fornitori.guestportal`` sulle tabelle dell'HUB: stessi tipi, stessi risultati.

Così Accessi esterni, Presenti, evacuazione e schede fornitore non cambiano al passaggio. Le date
tornano senza fuso, come quelle lette da MySQL.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import DittaAccreditata, Visita


def _ora_locale(valore):
    if valore is None:
        return None
    return timezone.localtime(valore).replace(tzinfo=None) if timezone.is_aware(valore) else valore


def _accesso(v: Visita):
    from fornitori.guestportal import Accesso

    anonimo = v.ospite.anonimizzato
    azienda = ((v.ditta.nome if v.ditta_id else "") or v.ospite.azienda or "").strip()
    return Accesso(
        visita_id=v.pk, stato=v.stato, tipo=v.tipo, nome=v.ospite.nome_completo or "—",
        azienda="" if anonimo else azienda, referente=v.referente_nome.strip(), motivo=v.motivo.strip(),
        badge=v.cartellino.strip(), ingresso=_ora_locale(v.ingresso), uscita=_ora_locale(v.uscita),
        ditta_gp_id=v.ditta_id,
    )


def _base():
    return Visita.objects.select_related("ospite", "ditta")


def _inizio_giorno(giorno: date) -> datetime:
    return timezone.make_aware(datetime.combine(giorno, time.min))


def presenti_ora() -> list:
    return [_accesso(v) for v in _base().filter(stato=Visita.DENTRO).order_by("ingresso", "pk")]


def storico(*, dal: date, al: date, testo: str = "", tipo: str = "", limite: int = 500) -> tuple[list, bool]:
    righe = _base().filter(ingresso__gte=_inizio_giorno(dal), ingresso__lt=_inizio_giorno(al + timedelta(days=1)))
    if tipo:
        righe = righe.filter(tipo=tipo)
    testo = (testo or "").strip()
    if testo:
        righe = righe.filter(
            Q(ospite__anonimizzato=False) & (Q(ospite__nome__icontains=testo) | Q(ospite__cognome__icontains=testo)
                                             | Q(ospite__azienda__icontains=testo) | Q(ditta__nome__icontains=testo))
            | Q(referente_nome__icontains=testo) | Q(motivo__icontains=testo)
        )
    trovate = list(righe.order_by("-ingresso", "-pk")[:int(limite) + 1])
    return [_accesso(v) for v in trovate[:limite]], len(trovate) > limite


def visita(visita_id: int):
    v = _base().filter(pk=visita_id).first()
    return _accesso(v) if v else None


def ditte() -> list[tuple[int, str]]:
    return [(pk, (nome or "").strip()) for pk, nome in
            DittaAccreditata.objects.filter(attiva=True).order_by("nome").values_list("pk", "nome")]


def _filtro_ditta(ditte_gp: list[int], nomi: list[str]) -> Q | None:
    """Fornitore abbinato oppure nome della ditta/azienda uguale a una ragione sociale."""
    filtro = Q()
    vuoto = True
    ditte_gp = [int(x) for x in ditte_gp if x]
    if ditte_gp:
        filtro |= Q(ditta_id__in=ditte_gp)
        vuoto = False
    for nome in sorted({(n or "").strip() for n in nomi if (n or "").strip()}, key=str.lower):
        filtro |= Q(ditta__nome__iexact=nome) | Q(ospite__anonimizzato=False, ospite__azienda__iexact=nome)
        vuoto = False
    return None if vuoto else filtro


def ingressi_ditta(*, ditte_gp: list[int], nomi: list[str], dal: date, al: date, limite: int = 200) -> list:
    filtro = _filtro_ditta(ditte_gp, nomi)
    if filtro is None:
        return []
    righe = _base().filter(filtro, ingresso__gte=_inizio_giorno(dal), ingresso__lt=_inizio_giorno(al + timedelta(days=1)))
    return [_accesso(v) for v in righe.order_by("-ingresso", "-pk")[:int(limite)]]


def tecnici_ditta(*, ditte_gp: list[int], nomi: list[str], limite: int = 300) -> tuple[list, bool]:
    from fornitori.guestportal import TecnicoDitta

    filtro = _filtro_ditta(ditte_gp, nomi)
    if filtro is None:
        return [], False
    persone: dict[int, dict] = {}
    for v in _base().filter(filtro, ospite__anonimizzato=False):
        p = persone.setdefault(v.ospite_id, {"nome": v.ospite.nome_completo, "ingressi": 0, "minuti": 0,
                                             "primo": None, "ultimo": None, "dentro": False})
        p["dentro"] = p["dentro"] or v.stato == Visita.DENTRO
        if not v.ingresso:
            continue
        p["ingressi"] += 1
        quando = _ora_locale(v.ingresso)
        p["primo"] = min(p["primo"], quando) if p["primo"] else quando
        p["ultimo"] = max(p["ultimo"], quando) if p["ultimo"] else quando
        if v.uscita:
            p["minuti"] += max(0, int((v.uscita - v.ingresso).total_seconds() // 60))
    ordinate = sorted(persone.values(), key=lambda p: p["ultimo"] or datetime.min, reverse=True)
    return [TecnicoDitta(**p) for p in ordinate[:limite]], len(ordinate) > limite
