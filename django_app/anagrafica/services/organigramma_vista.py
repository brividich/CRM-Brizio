"""Organigramma (vista Elenco): la scheda del reparto scelto, le pagine collegate e le cose da fare.

Legge i blocchi già calcolati da ``views.struttura.organigramma``: non cambia chi è capo né chi sta
in quale reparto.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from core.naming import nome_completo

from .organizzazione_panoramica import _puo_aprire


def _nome(riga: dict | None) -> str:
    return nome_completo(riga.get("nome"), riga.get("cognome")) if riga else ""


def arricchisci(request, blocchi: list[dict], *, is_admin: bool, scelto: int | None) -> dict | None:
    """Aggiunge ``scheda`` e ``testo`` a ogni blocco; restituisce il blocco scelto (o ``None``)."""
    permessi: dict[str, bool] = {}

    def puo(nome_rotta: str) -> bool:
        if nome_rotta not in permessi:
            permessi[nome_rotta] = _puo_aprire(request, reverse(nome_rotta))
        return permessi[nome_rotta]

    scelta = None
    for b in blocchi:
        r = b["reparto"]
        ruolo = r.ruolo_responsabile if r.ruolo_responsabile_id else None
        sopra = ruolo.riporta_a if ruolo is not None and ruolo.riporta_a_id else None
        aree = [a.nome for a in b["aree_aziendali"]]
        campi = [
            ("Reparto", r.nome),
            ("Responsabile", _nome(b["capo"]) or "Nessuno"),
            ("Ruolo responsabile", ruolo.nome if ruolo else "Da scegliere"),
            ("Riporta a", sopra.nome if sopra else "Nessuno"),
            ("Persone", str(b["n_totale"])),
            ("Aree", ", ".join(aree) or "Nessuna"),
        ]
        azioni = []
        if b["capo"] and puo("anagrafica:dipendenti_list"):
            azioni.append({"nome": f"Scheda di {_nome(b['capo'])}",
                           "url": reverse("anagrafica:dipendente_detail", args=[b["capo"]["id"]])})
        collegate = []
        if puo("anagrafica:aree_list"):
            collegate.append({"nome": f"Reparto {r.nome}", "spiega": "Responsabile, aree e ruolo, da gestire",
                              "url": f"{reverse('anagrafica:aree_list')}?reparto={r.pk}#rep-{r.pk}"})
        if puo("anagrafica:dipendenti_report"):
            collegate.append({"nome": "Persone del reparto", "spiega": "Elenco con ruolo e area",
                              "url": f"{reverse('anagrafica:dipendenti_report')}?{urlencode({'reparto': r.nome})}"})
        if puo("anagrafica:organigramma_albero"):
            collegate.append({"nome": "Albero dei ruoli", "spiega": "Chi riporta a chi, ruolo per ruolo",
                              "url": reverse("anagrafica:organigramma_albero")})
        if puo("anagrafica:prospetti"):
            collegate.append({"nome": "Prova un cambiamento", "spiega": "Sposta una persona e guarda che cosa cambia",
                              "url": reverse("anagrafica:prospetti")})
        if is_admin:
            collegate.append({"nome": "Capo di ogni persona", "spiega": "Da dove arriva il capo, persona per persona",
                              "url": reverse("anagrafica:coerenza_capi")})
        b["scheda"] = {"campi": campi, "azioni": azioni, "collegate": collegate}
        b["testo"] = " ".join([r.nome, *aree, _nome(b["capo"]), *(_nome(m) for m in b["membri"])])
        if r.pk == scelto:
            scelta = b
    return scelta


def da_fare(blocchi: list[dict], n_non_mappati: int) -> list[dict]:
    senza_capo = sum(1 for b in blocchi if not b["capo"])
    righe = [
        {"n": senza_capo, "titolo": "Reparti senza responsabile", "sotto": "Nessun capo assegnato",
         "url": f"{reverse('anagrafica:aree_list')}?filtro=da_sistemare#schede", "azione": "Assegna"},
        {"n": n_non_mappati, "titolo": "Persone con reparto non a catalogo", "sotto": "Il reparto del gestionale non è tra i reparti",
         "url": "#non-mappati", "azione": "Vedi"},
    ]
    return [x for x in righe if x["n"]]
