"""Completamenti in blocco dello storico, dalla Verifica (anteprima, spunta, conferma).

Nati dai log di utilizzo dell'11-20/11/2026: chi tiene il registro apriva le
righe storiche una per una solo per

- scegliere l'unità di misura (42 modifiche: lo storico importato non la ha, ma
  la descrizione del codice la scrive, «12.01.01 Sfridi Ferro Kg»);
- spostare il numero FIR dalla rettifica R allo scarico effettivo M della stessa
  coppia (l'import lo aveva messo sulla R).

Regole comuni: gli annullati non si toccano; ogni riga cambiata ha la sua voce
di audit (vecchio → nuovo, visibile nella scheda); se SharePoint è configurato la
riga resta segnata da reinviare, come nel consolidamento in blocco.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from django.db import transaction
from django.utils import timezone

from core.audit import log_action

from .fili import chiave
from .models import RegistroRifiuti

__all__ = ["proposte_unita", "applica_unita", "coppie_fir", "applica_fir"]

# Unità come parola finale («… Ferro Kg») o attaccata in maiuscolo («lampadineKg»):
# «… Metal» o «… Alluminio» non sono litri.
_UNITA_TESTO = re.compile(
    r"(?:(?<=\s)(?i:(kg|kgs|lt|l|litri|mc|m3|m³|t|ton))|(?<=[a-zà-ù])(Kg|KG|Lt|LT))\.?\s*$"
)
_DA_TESTO = {"kg": "kg", "kgs": "kg", "lt": "l", "l": "l", "litri": "l", "mc": "m3", "m3": "m3", "m³": "m3",
             "t": "t", "ton": "t"}


def unita_da_testo(codice: str) -> str:
    """«12.01.01 Sfridi Ferro Kg» → «kg»; «Luci led e lampadineKg» → «kg»; niente → ""."""
    m = _UNITA_TESTO.search(" ".join((codice or "").split()))
    return _DA_TESTO.get((m.group(1) or m.group(2)).lower(), "") if m else ""


def _nota_sync(testo: str) -> str:
    from .sharepoint import _graph_configured

    return testo if _graph_configured() else ""


def proposte_unita() -> list[dict]:
    """Per ogni codice CER con righe senza unità: quante sono e l'unità proposta.

    La proposta è l'unità già scelta a mano sulle altre righe dello stesso codice
    (vince sulla descrizione: per l'acqua emulsionata «… Lt» è stato scelto kg);
    senza righe scelte, quella scritta in fondo alla descrizione.
    """
    attive = list(RegistroRifiuti.objects.attivi().exclude(codice="").only("codice", "unita", "salva"))
    scelte: dict[str, Counter] = defaultdict(Counter)
    vuote: dict[str, list] = defaultdict(list)
    for r in attive:
        k = chiave(r.codice)
        if not k:
            continue
        if r.unita:
            scelte[k][r.unita] += 1
        else:
            vuote[k].append(r)
    etichette = dict(RegistroRifiuti.UNITA_CHOICES)
    out = []
    for k, righe in sorted(vuote.items(), key=lambda kv: -len(kv[1])):
        dal_testo = Counter(unita_da_testo(r.codice) for r in righe if unita_da_testo(r.codice))
        if scelte[k]:
            unita, n = scelte[k].most_common(1)[0]
            fonte = f"come le altre {n} registrazioni dello stesso codice"
        elif dal_testo:
            unita = dal_testo.most_common(1)[0][0]
            fonte = "dalla descrizione del codice"
        else:
            unita, fonte = "", "da scegliere"
        out.append({
            "chiave": k,
            "testo": Counter(" ".join(r.codice.split()) for r in righe).most_common(1)[0][0],
            "righe": len(righe),
            "consolidate": sum(1 for r in righe if r.salva),
            "unita": unita,
            "unita_label": etichette.get(unita, ""),
            "fonte": fonte,
            "dal_testo": dal_testo.most_common(1)[0][0] if dal_testo else "",
            "dal_testo_label": etichette.get(dal_testo.most_common(1)[0][0], "") if dal_testo else "",
        })
    return out


def applica_unita(request, scelte: dict[str, str], utente: str) -> dict:
    """Scrive l'unità scelta sulle righe valide senza unità dei codici scelti (`chiave → unità`)."""
    valide = dict(RegistroRifiuti.UNITA_CHOICES)
    pulite = {k: u for k, u in scelte.items() if u in valide}
    nota = _nota_sync("Da reinviare dopo il completamento delle unità")
    adesso = timezone.now()
    cambiate = 0
    with transaction.atomic():
        for r in RegistroRifiuti.objects.attivi().filter(unita="").exclude(codice="").order_by("id"):
            unita = pulite.get(chiave(r.codice))
            if not unita:
                continue
            r.unita = unita
            r.updated_at = adesso
            campi = ["unita", "updated_at"]
            if nota:
                r.sync_errore = nota
                campi.append("sync_errore")
            r.save(update_fields=campi)
            log_action(
                request, "rentri_unita_completata", "rentri",
                {"id_registrazione": r.id_registrazione, "tipo": r.tipo,
                 "modifiche": {"unita": {"old": "", "new": unita}}, "consolidato": r.salva},
                oggetto=r,
            )
            cambiate += 1
    esito = {"codici": len(pulite), "righe": cambiate, "da": utente}
    log_action(request, "rentri_unita_completate", "rentri", esito)
    return esito


def coppie_fir() -> list[dict]:
    """Coppie R+M con lo stesso numero, FIR sulla R e M senza FIR, entrambe bozze."""
    per_id: dict[str, list] = defaultdict(list)
    for r in RegistroRifiuti.objects.attivi().filter(tipo__in=["R", "M"]).exclude(id_registrazione=""):
        per_id[r.id_registrazione].append(r)
    out = []
    for numero, righe in sorted(per_id.items()):
        tipi = {r.tipo: r for r in righe}
        if len(righe) != 2 or set(tipi) != {"R", "M"}:
            continue
        rett, eff = tipi["R"], tipi["M"]
        if not rett.arrivo_fir.strip() or eff.arrivo_fir.strip() or rett.bloccato or eff.bloccato:
            continue
        out.append({"numero": numero, "r": rett, "m": eff, "fir": " ".join(rett.arrivo_fir.split())})
    return out


def applica_fir(request, numeri: list[str], utente: str) -> dict:
    """Sposta il FIR dalla R alla M delle coppie scelte (ricontrollate qui, non dal modulo)."""
    scelti = set(numeri)
    nota = _nota_sync("Da reinviare dopo lo spostamento del FIR")
    adesso = timezone.now()
    spostati = 0
    with transaction.atomic():
        for c in coppie_fir():
            if c["numero"] not in scelti:
                continue
            rett, eff = c["r"], c["m"]
            vecchio_r = rett.arrivo_fir
            eff.arrivo_fir, rett.arrivo_fir = c["fir"][:200], ""
            for r in (eff, rett):
                r.updated_at = adesso
                campi = ["arrivo_fir", "updated_at"]
                if nota:
                    r.sync_errore = nota
                    campi.append("sync_errore")
                r.save(update_fields=campi)
            log_action(request, "rentri_fir_spostato", "rentri",
                       {"id_registrazione": eff.id_registrazione, "tipo": "M",
                        "modifiche": {"arrivo_fir": {"old": "", "new": eff.arrivo_fir}}, "da": "R"}, oggetto=eff)
            log_action(request, "rentri_fir_spostato", "rentri",
                       {"id_registrazione": rett.id_registrazione, "tipo": "R",
                        "modifiche": {"arrivo_fir": {"old": vecchio_r, "new": ""}}, "a": "M"}, oggetto=rett)
            spostati += 1
    esito = {"coppie": spostati, "da": utente}
    log_action(request, "rentri_fir_spostati", "rentri", esito)
    return esito
