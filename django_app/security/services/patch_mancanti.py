"""Patch mancanti WatchGuard raggruppate per patch e per PC (pagina Dispositivi › Patch e protezione).

Il raggruppamento (patch comprese in una più recente, CVE sfruttate, esiti) costa: si fa una volta e si
tiene in cache finché non cambiano le patch (nuova lettura o nuovo esito di installazione), al massimo
``CACHE_SECONDI``. In cache vanno solo dati semplici, mai oggetti del database.
"""

from __future__ import annotations

import hashlib

from django.core.cache import cache
from django.db.models import Count, Max

from security.models import WatchGuardPatch

CACHE_SECONDI = 600
ORDINE_CRITICITA = {201: 0, 202: 1, 203: 2, 204: 3}
CRITICITA_FILTRO = {"201": "Critica", "202": "Importante", "203": "Moderata", "204": "Bassa"}


def chiave_patch(nome: str, programma: str) -> str:
    return hashlib.sha1(f"{nome}\x1f{programma}".encode()).hexdigest()[:16]


def _chiave_cache() -> str:
    agg = WatchGuardPatch.objects.filter(presente=True).aggregate(n=Count("id"), v=Max("vista_il"), e=Max("esito_il"))
    return "sec:wgp:v1:" + hashlib.sha1(f"{agg['n']}|{agg['v']}|{agg['e']}".encode()).hexdigest()[:20]


def dati(*, rifai: bool = False) -> dict:
    """{"patch": [gruppo], "pc": [riga per PC]} dalla cache o ricalcolati."""
    chiave = _chiave_cache()
    if not rifai:
        trovati = cache.get(chiave)
        if trovati is not None:
            return trovati
    out = _calcola()
    cache.set(chiave, out, CACHE_SECONDI)
    return out


def _calcola() -> dict:
    from security.services import patch_kb

    aperte = list(WatchGuardPatch.objects.filter(presente=True).order_by("host").only(
        "id", "host", "host_display", "hub_asset_id", "nome", "programma", "versione", "rilasciata_il", "criticita",
        "di_sistema", "disponibilita", "cve", "kb", "download_url", "nome_file", "riavvio_automatico", "esito", "esito_il",
        "presente"))
    comprese = patch_kb.comprese(aperte)
    gruppi: dict = {}
    for p in aperte:
        g = gruppi.get((p.nome, p.programma))
        if g is None:
            g = gruppi[(p.nome, p.programma)] = {
                "id": chiave_patch(p.nome, p.programma), "nome": p.nome, "programma": p.programma,
                "criticita": p.criticita, "criticita_label": p.criticita_label, "rilasciata_il": p.rilasciata_il,
                "kb": p.kb, "di_sistema": p.di_sistema, "download_url": p.download_url, "nome_file": p.nome_file,
                "riavvio_automatico": p.riavvio_automatico, "cve": set(), "chiude_anche": set(), "compresa_in": {},
                "comprende": {}, "pc": [], "errori": 0}
        g["cve"].update(p.cve_lista)
        g["errori"] += int(p.esito_errore)
        compresa = comprese.get(p.pk)
        g["pc"].append({
            "host": p.host, "nome": p.host_display or p.host, "asset_id": p.hub_asset_id, "versione": p.versione,
            "esito": p.esito, "esito_label": p.esito_label, "esito_errore": p.esito_errore, "esito_il": p.esito_il,
            "stato": p.esito_label or p.disponibilita_label or "Da installare",
            "compresa": (compresa["in"].kb or compresa["in"].nome) if compresa else "",
            "compresa_perche": compresa["perche"] if compresa else ""})
        if compresa:
            sopra = compresa["in"]
            etichetta = sopra.kb or sopra.nome
            g["compresa_in"][etichetta] = g["compresa_in"].get(etichetta, 0) + 1
    for p in aperte:  # le CVE delle patch comprese le chiude anche quella che le comprende
        compresa = comprese.get(p.pk)
        if compresa:
            gs = gruppi[(compresa["in"].nome, compresa["in"].programma)]
            gs["chiude_anche"].update(set(p.cve_lista))
            gs["comprende"][p.kb or p.nome] = gs["comprende"].get(p.kb or p.nome, 0) + 1
    tutte = {c for g in gruppi.values() for c in g["cve"] | g["chiude_anche"]}
    from security.services.kev import kev_tra

    kev = kev_tra(tutte)
    for g in gruppi.values():
        g["chiude_anche"] -= g["cve"]
        g["kev"] = sorted((g["cve"] | g["chiude_anche"]) & kev)
        g["cve"] = sorted(g["cve"])
        g["chiude_anche"] = sorted(g["chiude_anche"])
        g["cve_totale"] = len(g["cve"]) + len(g["chiude_anche"])
        g["tutta_compresa"] = sum(g["compresa_in"].values()) == len(g["pc"])
        g["compresa_in"] = sorted(g["compresa_in"].items(), key=lambda x: -x[1])
        g["comprende"] = sorted(g["comprende"].items(), key=lambda x: -x[1])
        g["pc"].sort(key=lambda r: (not r["esito_errore"], r["nome"].casefold()))
        g["hosts"] = "|".join(r["nome"] for r in g["pc"])
    patch = sorted(gruppi.values(), key=lambda g: (g["tutta_compresa"], not g["kev"],
                                                   ORDINE_CRITICITA.get(g["criticita"], 4), -len(g["pc"]), g["nome"]))
    from security.services import patch_sla

    return {"patch": patch, "pc": _per_pc(patch), "ferme": patch_sla.ferme()["kpi"]}


def _per_pc(patch: list[dict]) -> list[dict]:
    righe: dict = {}
    for g in patch:
        for r in g["pc"]:
            x = righe.setdefault(r["host"], {"host": r["host"], "nome": r["nome"], "asset_id": r["asset_id"], "patch": 0,
                                             "kev": 0, "critiche": 0, "errori": 0, "comprese": 0, "cve": set()})
            x["patch"] += 1
            x["kev"] += int(bool(g["kev"]) and not r["compresa"])
            x["critiche"] += int(g["criticita"] == 201)
            x["errori"] += int(r["esito_errore"])
            x["comprese"] += int(bool(r["compresa"]))
            x["cve"].update(g["cve"])
    for x in righe.values():
        x["cve"] = len(x["cve"])
    return sorted(righe.values(), key=lambda x: (-x["kev"], -x["errori"], -x["critiche"], -x["patch"], x["nome"].casefold()))


def cerca_patch(g: dict, q: str) -> bool:
    """Ricerca: KB, nome, programma, CVE corrette (anche tramite le patch comprese) o PC."""
    if q in g["nome"].upper() or q in (g["programma"] or "").upper() or (g["kb"] and q in g["kb"].upper()):
        return True
    if any(q in c for c in g["cve"]) or any(q in c for c in g["chiude_anche"]):
        return True
    if any(q in kb.upper() for kb, _ in g["comprende"]) or any(q in kb.upper() for kb, _ in g["compresa_in"]):
        return True
    return any(q in r["nome"].upper() for r in g["pc"])


def filtra_patch(patch: list[dict], *, q="", criticita="", kev=False, errori=False, nascondi_comprese=False) -> list[dict]:
    q = q.upper()
    out = []
    for g in patch:
        if criticita and str(g["criticita"]) != criticita:
            continue
        if kev and not g["kev"]:
            continue
        if errori and not g["errori"]:
            continue
        if nascondi_comprese and g["tutta_compresa"]:
            continue
        if q and not cerca_patch(g, q):
            continue
        out.append(g)
    return out


def trova(chiave: str) -> dict | None:
    return next((g for g in dati()["patch"] if g["id"] == chiave), None)
