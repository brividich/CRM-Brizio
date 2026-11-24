"""«Centri di costo»: l'albero di ogni centro (reparto → ruolo → mansione) e la sua scheda.

Stessi dati e stessi conteggi di «Esplora la struttura» (``esplora_struttura.Dati``): i reparti
del centro, i ruoli di ogni reparto con le persone in forza, le mansioni di ogni ruolo. Ogni riga
porta a «Esplora la struttura» aperta su quel punto.
"""
from __future__ import annotations

from collections import Counter

from django.urls import reverse

from ..models import AbilitazioneMacchina
from . import esplora_struttura as es
from . import struttura_vista


def _quanti(n: int, uno: str, tanti: str) -> str:
    return f"{n} {uno if n == 1 else tanti}"


def _persone_per_mansione(d) -> Counter:
    """Persone in forza che hanno ogni mansione in lista."""
    conta: Counter = Counter()
    for mansione_id, persona in (AbilitazioneMacchina.objects.filter(in_lista=True, competenza__isnull=False)
                                 .values_list("competenza_id", "legacy_anagrafica_id")):
        if persona in d.in_forza:
            conta[mansione_id] += 1
    return conta


def alberi(d, centri_ids) -> dict[int, list[dict]]:
    """Per ogni centro: i suoi reparti, ognuno con i ruoli e le mansioni."""
    per_mansione = _persone_per_mansione(d)
    aree_per_centro = {cid: d.aree_centro(cid) for cid in centri_ids}
    responsabili = {a.pk: es._responsabili(d, a) for aree in aree_per_centro.values() for a in aree}
    nomi = struttura_vista._nomi(sorted({i for ids in responsabili.values() for i in ids}))
    out: dict[int, list[dict]] = {}
    for cid, aree in aree_per_centro.items():
        reparti = []
        for area in sorted(aree, key=lambda a: a.nome.casefold()):
            ruoli = []
            for rid, info in d.ruoli_area(area).items():
                ruolo = d.ruoli.get(rid)
                mansioni = sorted(info["mansioni"], key=lambda m: m.nome.casefold())
                ruoli.append({
                    "nome": es._etichetta_ruolo(ruolo) if ruolo else es.ETICHETTE_SENZA["ruolo"],
                    "senza": ruolo is None,
                    "persone": _quanti(len(info["persone"]), "persona", "persone"),
                    "url": es.url(centro=cid, area=area.pk, ruolo=rid),
                    "mansioni": [{"nome": m.nome, "persone": _quanti(per_mansione.get(m.pk, 0), "persona", "persone"),
                                  "url": es.url(centro=cid, area=area.pk, ruolo=rid, mansione=m.pk)} for m in mansioni],
                })
            ruoli.sort(key=lambda r: (r["senza"], r["nome"].casefold()))
            reparti.append({
                "area": area, "nome": area.nome, "url": es.url(centro=cid, area=area.pk),
                "persone": _quanti(len(d.persone_area(area.pk)), "persona", "persone"),
                "responsabile": ", ".join(nomi.get(i) or f"#{i}" for i in responsabili[area.pk]),
                "ruoli": ruoli,
            })
        out[cid] = reparti
    return out


def scheda(centro, righe: list, *, segnali, costi, puo_costi: bool) -> dict:
    """I dati etichettati del centro e le pagine collegate, già aperte su quel centro."""
    ruoli = sorted({r.nome for riga in righe for r in riga["ruoli"]}, key=str.casefold)
    campi = [("Centro di costo", centro.nome)]
    if centro.descrizione:
        campi.append(("Descrizione", centro.descrizione))
    campi += [
        ("Stato", "Attivo" if centro.is_active else "Non attivo"),
        ("Reparti", ", ".join(r["area"].nome for r in righe) or "Nessuno"),
        ("Persone", str(sum(r["persone"] for r in righe))),
        ("Ruoli previsti", ", ".join(ruoli) or "Nessuno"),
    ]
    if segnali and segnali.get("mansioni"):
        campi.append(("Mansioni", str(segnali["mansioni"])))
        if segnali.get("da_guardare"):
            campi.append(("Mansioni da guardare", str(segnali["da_guardare"])))
    if puo_costi and costi:
        campi += [("RML del mese", f"{costi['rml']:.2f} €".replace(".", ",")),
                  ("Costo orario medio", f"{costi['costo_medio']:.2f} €/h".replace(".", ","))]
    from urllib.parse import urlencode

    filtro = urlencode({"centro_costo": centro.nome})
    collegate = [
        {"nome": "Esplora la struttura", "spiega": "Aperta su questo centro di costo",
         "url": es.url(centro=centro.pk)},
        {"nome": "Persone del centro", "spiega": "Elenco con reparto e ruolo",
         "url": f"{reverse('anagrafica:dipendenti_report')}?{filtro}"},
    ]
    if puo_costi:
        collegate.append({"nome": "Costo orario del centro", "spiega": "Dipendenti e RML del mese",
                          "url": f"{reverse('anagrafica:costo_orario')}?{filtro}"})
    collegate += [
        {"nome": "Reparti e capi", "spiega": "Responsabili e ruoli dei reparti", "url": reverse("anagrafica:aree_list")},
        {"nome": "Prova un cambiamento", "spiega": "Confronto oggi e dopo, prima di cambiare",
         "url": reverse("anagrafica:prospetti")},
    ]
    return {"campi": campi, "collegate": collegate}
