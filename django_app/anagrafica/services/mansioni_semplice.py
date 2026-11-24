"""«Mansioni» in vista semplice: un elenco, la mansione scelta a destra con le sue competenze.

Le righe sono quelle del Mansionario (``mansionario_struttura.riepilogo`` + segnali di
``carico_mansioni``): stessi numeri della vista completa. Qui si aggiungono solo le competenze di
ogni mansione, lette con una query sola.
"""
from __future__ import annotations

from django.urls import reverse

from ..models_skillmatrix import VoceMacchinaCatalogo
from . import esplora_semplice
from . import esplora_struttura as es

SEMPLICE, COMPLETA = "semplice", "completa"
CHIAVE_SESSIONE = "mansioni_vista"

# Filtri dell'elenco: (etichetta, regola sulla riga). Il numero accanto all'etichetta usa la stessa regola.
FILTRI = {
    "senza-competenze": ("Senza competenze", lambda r: not r["competenze"]),
    "senza-persone": ("Senza persone", lambda r: not r["in_lista"] and not r["mansione"].is_responsabilita),
    "da-guardare": ("Da guardare", lambda r: bool(r.get("da_guardare"))),
}


# ``?flag=`` arriva da Dashboard e Centri di costo: quelli che la vista semplice sa filtrare.
FLAG_SEMPLICI = {"da-guardare": "da-guardare"}


def vista_scelta(request) -> str:
    """Semplice di default; la scelta fatta con ``?vista=`` resta per la sessione.

    Un ``?flag=`` che solo la vista completa sa filtrare la apre per questa volta, senza cambiare la scelta.
    """
    flag = request.GET.get("flag")
    if flag and flag not in FLAG_SEMPLICI and "vista" not in request.GET:
        return COMPLETA
    chiesta = request.GET.get("vista")
    if chiesta in (SEMPLICE, COMPLETA):
        request.session[CHIAVE_SESSIONE] = chiesta
    return COMPLETA if request.session.get(CHIAVE_SESSIONE) == COMPLETA else SEMPLICE


def _competenze(ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for v in (VoceMacchinaCatalogo.objects.filter(mansione_id__in=ids, attiva=True)
              .only("pk", "nome", "livello_minimo", "bloccante", "mansione_id").order_by("ordine", "pk")):
        out.setdefault(v.mansione_id, []).append(
            {"nome": v.nome, "livello": esplora_semplice.livello(v.livello_minimo), "bloccante": v.bloccante})
    return out


def _stato(r) -> dict:
    if FILTRI["senza-persone"][1](r):
        return {"nome": "Senza persone", "tono": "danger"}
    if FILTRI["senza-competenze"][1](r):
        return {"nome": "Senza competenze", "tono": "warning"}
    if FILTRI["da-guardare"][1](r):
        return {"nome": "Da guardare", "tono": "warning"}
    return {"nome": "Completa", "tono": "ok"}


def costruisci(righe: list[dict], *, filtro: str, scelta_id: int | None, puo_esplora: bool, puo_richieste: bool,
               ruolo_id: int | None = None) -> dict:
    """Contesto della vista semplice: elenco filtrato, conteggi dei filtri, mansione scelta.

    ``ruolo_id`` restringe l'elenco alle mansioni di quel ruolo (i link «ruolo» delle altre pagine).
    """
    ruolo = None
    if ruolo_id is not None:
        ruolo = next((x for r in righe for x in r["ruoli"] if x.pk == ruolo_id), None)
        if ruolo is not None:
            righe = [r for r in righe if any(x.pk == ruolo_id for x in r["ruoli"])]
    competenze = _competenze([r["mansione"].pk for r in righe])
    url_scheda = reverse("anagrafica:mansionario_mansione", args=[0])
    url_richieste = reverse("anagrafica:richieste")
    for r in righe:
        m = r["mansione"]
        r["competenze"] = competenze.get(m.pk, [])
        r["stato_semplice"] = _stato(r)
        ruoli = ", ".join(x.nome for x in r["ruoli"])
        r["ruoli_testo"] = ruoli
        area = m.area.nome if m.area_id else ""
        campi = [("Mansione", m.nome), ("Reparto", r["reparto"] or "Nessuno")]
        if area and area != r["reparto"]:
            campi.append(("Area", area))
        campi += [
            ("Ruolo", ruoli or "Nessuno"),
            ("Competenze richieste", str(len(r["competenze"]))),
            ("Persone", str(r["in_lista"])),
            ("Operative", str(r.get("operativi", 0))),
            ("Stato", r["stato_semplice"]["nome"]),
        ]
        azioni = [{"nome": "Apri la mansione", "url": url_scheda.replace("/0/", f"/{m.pk}/")}]
        collegate = []
        if puo_esplora:
            collegate.append({"nome": "Esplora la struttura", "spiega": "Aperta su questa mansione", "url": es.url(mansione=m.pk)})
        if puo_richieste:
            collegate.append({"nome": "Richieste su questa mansione", "spiega": "Assegnazioni, sospensioni, rimozioni",
                              "url": f"{url_richieste}?mansione={m.pk}"})
        r["scheda"] = {"campi": campi, "azioni": azioni, "collegate": collegate}
        r["testo"] = " ".join([m.nome, r["reparto"] or "", area, ruoli])
    conteggi = {k: sum(1 for r in righe if regola(r)) for k, (_, regola) in FILTRI.items()}
    if filtro in FILTRI:
        elenco = [r for r in righe if FILTRI[filtro][1](r)]
    else:
        filtro, elenco = "", righe
    scelta = next((r for r in elenco if r["mansione"].pk == scelta_id), elenco[0] if elenco else None)
    return {
        "elenco": elenco,
        "n_tutte": len(righe),
        "filtro": filtro,
        "ruolo": ruolo,
        "filtri": [{"chiave": k, "nome": n, "n": conteggi[k]} for k, (n, _) in FILTRI.items()],
        "scelta": scelta,
        "legenda": esplora_semplice.LEGENDA,
    }
