"""Reparti scritti sugli asset non IT e il caporeparto a cui arrivano (Impostazioni › Reparti e capi).

Il campo «Reparto» dell'asset è testo libero: molti asset storici hanno codici
(«LOG», «TNC») o nomi scritti a mano («rettifiche», «mag 2») che non sono il nome
di un reparto o di un'area dell'anagrafica. Senza collegamento quelle macchine
non rispondono a nessun caporeparto e con ambito «Propri» non le vede nessuno.
Qui si elencano i testi in uso e si collegano a un'unità, senza riscrivere gli asset.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db.models import Q

from ..models import Asset, RepartoAssetCollegato
from . import responsabile_asset

STATO_RICONOSCIUTO = "riconosciuto"
STATO_COLLEGATO = "collegato"
STATO_DA_COLLEGARE = "da_collegare"
STATO_SENZA_CAPO = "senza_capo"


@dataclass
class RigaReparto:
    testo: str
    chiave: str
    asset: int
    stato: str
    unita: str = ""  # «r:<id>» / «a:<id>» del collegamento
    unita_nome: str = ""
    capo: str = ""
    suggerita: str = ""


def _asset_del_reparto():
    """Asset non IT senza persona assegnata: quelli che rispondono al caporeparto."""
    return Asset.objects.filter(asset_type__in=sorted(responsabile_asset.TIPI_REPARTO)).filter(
        assigned_legacy_user_id__isnull=True
    ).filter(
        Q(assignment_to="") | Q(assignment_to__isnull=True)
        | Q(assignment_to__startswith=responsabile_asset.PREFISSO_REPARTO)
    )


def testi_in_uso() -> Counter:
    """Testo del reparto (come scritto la prima volta) → quanti asset, per chiave normalizzata."""
    conta: Counter = Counter()
    testo_di: dict[str, str] = {}
    for reparto, assegnazione in _asset_del_reparto().values_list("reparto", "assignment_reparto"):
        testo = (reparto or assegnazione or "").strip()
        if not testo:
            continue
        chiave = responsabile_asset.chiave_reparto(testo)
        testo_di.setdefault(chiave, testo)
        conta[chiave] += 1
    return Counter({(chiave, testo_di[chiave]): n for chiave, n in conta.items()})


def unita_disponibili() -> list[dict]:
    """Reparti e aree attivi, per il menu del collegamento (valore «r:<id>» / «a:<id>»)."""
    from anagrafica.models import AreaAziendale, Reparto

    righe = [
        {"valore": f"r:{pk}", "nome": nome, "gruppo": "Reparti"}
        for pk, nome in Reparto.objects.filter(is_active=True).order_by("nome").values_list("pk", "nome")
    ]
    righe += [
        {"valore": f"a:{pk}", "nome": nome if not rep else f"{nome} ({rep})", "gruppo": "Aree"}
        for pk, nome, rep in AreaAziendale.objects.filter(is_active=True)
        .order_by("nome").values_list("pk", "nome", "reparto__nome")
    ]
    return righe


def _suggerisci(chiave: str, unita: list[dict], descrizioni: dict[str, str]) -> str:
    """Un'unità plausibile per un testo non riconosciuto: stessa sigla in descrizione o stesso inizio."""
    if chiave in descrizioni:
        return descrizioni[chiave]
    radice = chiave.replace(".", " ").split()[0] if chiave.split() else ""
    if len(radice) < 5:
        return ""
    for u in unita:
        nome = responsabile_asset.chiave_reparto(u["nome"].split(" (")[0])
        if len(nome) >= 5 and (nome.startswith(radice[:5]) or radice.startswith(nome[:5])):
            return u["valore"]
    return ""


def righe() -> tuple[list[RigaReparto], int]:
    """(una riga per testo in uso, asset senza reparto), da collegare prima."""
    from anagrafica.models import AreaAziendale, Reparto

    capi = responsabile_asset.capi_per_reparto()
    nomi_ufficiali = {
        responsabile_asset.chiave_reparto(n)
        for n in list(Reparto.objects.filter(is_active=True).values_list("nome", flat=True))
        + list(AreaAziendale.objects.filter(is_active=True).values_list("nome", flat=True))
    }
    descrizioni = {
        responsabile_asset.chiave_reparto(d): f"a:{pk}"
        for pk, d in AreaAziendale.objects.filter(is_active=True).exclude(descrizione="").values_list("pk", "descrizione")
        if len(d.split()) == 1
    }
    collegati = {
        c.chiave: c for c in RepartoAssetCollegato.objects.select_related("reparto", "area")
    }
    unita = unita_disponibili()
    risultato = []
    for (chiave, testo), n in testi_in_uso().items():
        capo = capi.get(chiave)
        riga = RigaReparto(testo=testo, chiave=chiave, asset=n, stato=STATO_DA_COLLEGARE,
                           capo=capo[1] if capo else "")
        collegato = collegati.get(chiave)
        if collegato is not None:
            riga.stato = STATO_COLLEGATO
            riga.unita = f"a:{collegato.area_id}" if collegato.area_id else f"r:{collegato.reparto_id}"
            riga.unita_nome = str(collegato.area or collegato.reparto)
        elif chiave in nomi_ufficiali:
            riga.stato = STATO_RICONOSCIUTO
        else:
            riga.suggerita = _suggerisci(chiave, unita, descrizioni)
        if riga.stato != STATO_DA_COLLEGARE and not capo:
            riga.stato = STATO_SENZA_CAPO
        risultato.append(riga)
    ordine = {STATO_DA_COLLEGARE: 0, STATO_SENZA_CAPO: 1, STATO_COLLEGATO: 2, STATO_RICONOSCIUTO: 3}
    risultato.sort(key=lambda r: (ordine[r.stato], -r.asset, r.chiave))
    senza = _asset_del_reparto().filter(
        Q(reparto="") | Q(reparto__isnull=True)
    ).filter(Q(assignment_reparto="") | Q(assignment_reparto__isnull=True)).count()
    return risultato, senza


def testi_da_collegare() -> int:
    """Quanti testi di reparto in uso non arrivano a nessun caporeparto (chip della lista asset)."""
    capi = responsabile_asset.capi_per_reparto()
    return sum(1 for (chiave, _testo) in testi_in_uso() if chiave not in capi)


def collega(testo: str, unita: str, utente: str = "") -> RepartoAssetCollegato | None:
    """Collega ``testo`` a ``unita`` («r:<id>» / «a:<id>»); ``unita`` vuota toglie il collegamento."""
    from anagrafica.models import AreaAziendale, Reparto

    chiave = responsabile_asset.chiave_reparto(testo)
    if not chiave:
        raise ValueError("Testo del reparto vuoto.")
    if not unita:
        RepartoAssetCollegato.objects.filter(chiave=chiave).delete()
        return None
    tipo, _sep, pk = unita.partition(":")
    if tipo not in ("r", "a") or not pk.isdigit():
        raise ValueError("Unità non valida.")
    reparto = Reparto.objects.filter(pk=int(pk), is_active=True).first() if tipo == "r" else None
    area = AreaAziendale.objects.filter(pk=int(pk), is_active=True).first() if tipo == "a" else None
    if reparto is None and area is None:
        raise ValueError("Reparto o area non trovati.")
    collegato, _creato = RepartoAssetCollegato.objects.update_or_create(
        chiave=chiave,
        defaults={"testo": testo.strip()[:120], "reparto": reparto, "area": area, "aggiornato_da": utente[:150]},
    )
    return collegato
