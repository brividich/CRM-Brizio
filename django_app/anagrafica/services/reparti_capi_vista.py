"""«Reparti e capi»: per ogni reparto la riga dell'elenco, la scheda di destra e le cose da fare.

Non ricalcola niente: legge le schede di ``views_capi_reparti._contesto`` e le regole dei filtri
(``FILTRI_REPARTI``), così elenco, filtri e numeri restano la stessa cosa.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from . import esplora_struttura as es
from .organizzazione_panoramica import _puo_aprire


def _quanti(n: int, uno: str, tanti: str) -> str:
    return f"{n} {uno if n == 1 else tanti}"


def arricchisci(request, ctx: dict, *, da_sistemare, scelto: int | None) -> None:
    """Aggiunge a ogni scheda ``riga`` (colonne dell'elenco), ``scheda`` (destra) e ``aperto``."""
    is_admin = ctx["is_admin"]
    permessi: dict[str, bool] = {}

    def puo(nome_rotta: str) -> bool:
        if nome_rotta not in permessi:
            permessi[nome_rotta] = _puo_aprire(request, reverse(nome_rotta))
        return permessi[nome_rotta]

    for s in ctx["schede"]:
        r = s["reparto"]
        aree = [a["area"] for a in s["aree"]]
        centri = {}
        for a in aree:
            if a.centro_di_costo_id:
                centri[a.centro_di_costo_id] = a.centro_di_costo.nome
        capi = [p["nome"] for p in s["capi"]]
        if not r.is_active:
            stato = {"nome": "Non attivo", "tono": ""}
        elif da_sistemare(s):
            stato = {"nome": "Da sistemare", "tono": "warning"}
        else:
            stato = {"nome": "Completo", "tono": "ok"}
        ruolo = r.ruolo_responsabile.nome if r.ruolo_responsabile_id else ""
        s["riga"] = {
            "centri": ", ".join(sorted(centri.values(), key=str.casefold)),
            "capo": capi[0] if capi else "",
            "ruolo": ruolo,
            "stato": stato,
            "testo": " ".join([r.nome, *capi, *(a.nome for a in aree), *centri.values()]),
        }
        campi = [
            ("Reparto", r.nome),
            ("Centro di costo", s["riga"]["centri"] or "Nessuno"),
            ("Responsabile", capi[0] if capi else "Nessuno"),
        ]
        if len(capi) > 1:
            campi.append(("Co-capi", ", ".join(capi[1:])))
        campi += [
            ("Ruolo responsabile", ruolo or "Da scegliere"),
            ("Persone", str(s["persone"])),
            ("Aree", ", ".join(a.nome for a in aree) or "Nessuna"),
            ("Stato", stato["nome"]),
        ]
        if s["senza_capo"]:
            campi.append(("Persone senza capo", str(s["senza_capo"])))

        collegate = []
        # «Esplora la struttura» lavora per area: si apre su quella che coincide col reparto, o sulla prima.
        area = next((a["area"] for a in s["aree"] if a["coincide"]), aree[0] if aree else None)
        if area is not None and puo("anagrafica:esplora_struttura"):
            collegate.append({"nome": "Esplora la struttura", "spiega": f"Aperta su {area.nome}", "url": es.url(area=area.pk)})
        if puo("anagrafica:dipendenti_report"):
            collegate.append({"nome": "Persone del reparto", "spiega": _quanti(s["persone"], "persona", "persone"),
                              "url": f"{reverse('anagrafica:dipendenti_report')}?{urlencode({'reparto': r.nome})}"})
        if centri and puo("anagrafica:centri_costo"):
            cid, nome = sorted(centri.items(), key=lambda x: x[1].casefold())[0]
            collegate.append({"nome": f"Centro di costo {nome}", "spiega": "Reparti e persone del centro",
                              "url": f"{reverse('anagrafica:centri_costo')}?centro={cid}#cc-{cid}"})
        if puo("anagrafica:organigramma"):
            collegate.append({"nome": "Organigramma", "spiega": "Chi riporta a chi", "url": reverse("anagrafica:organigramma")})
        if is_admin:
            collegate.append({"nome": "Capo di ogni persona", "spiega": "Da dove arriva il capo, persona per persona",
                              "url": reverse("anagrafica:coerenza_capi")})
        s["scheda"] = {"campi": campi, "collegate": collegate}
        s["aperto"] = r.pk == scelto


def da_fare(ctx: dict) -> list[dict]:
    """Solo le righe con qualcosa da fare, con il numero dei filtri della pagina."""
    kpi = ctx["kpi"]
    base = reverse("anagrafica:aree_list")
    righe = [
        {"n": kpi["da_sistemare"], "titolo": "Reparti da sistemare",
         "sotto": "Manca il ruolo responsabile o nessuno ha la mansione",
         "url": f"{base}?filtro=da_sistemare#schede", "azione": "Apri"},
        {"n": kpi["senza_capo"], "titolo": "Persone senza capo", "sotto": f"Su {kpi['persone']} in forza",
         "url": f"{reverse('anagrafica:coerenza_capi')}?filtro=senza" if ctx["is_admin"] else "", "azione": "Risolvi"},
        {"n": len(ctx["aree_senza_reparto"]), "titolo": "Aree senza reparto", "sotto": "Non hanno un capo",
         "url": "#senza-reparto", "azione": "Vedi"},
    ]
    return [x for x in righe if x["n"]]
