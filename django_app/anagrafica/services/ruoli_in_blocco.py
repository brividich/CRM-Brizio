"""Cambio di ruolo per più persone insieme, con anteprima.

Tre operazioni, ciascuna sul percorso che la scheda usa per una persona sola:

- **aggiungi**: il ruolo si somma a quelli in essere (``assicura_assegnazione``);
  diventa il ruolo principale solo se la persona non ne ha uno;
- **sostituisci**: nuovo ruolo principale con uno spostamento organizzativo
  (``assegnazioni.crea_assegnazione``), che chiude il ruolo di prima il giorno
  prima della decorrenza e lascia reparto, area e mansione come sono;
- **chiudi**: conclude il ruolo alla data indicata (resta nello storico); se era
  il principale subentra il primo ruolo rimasto dello stesso organigramma.

Ogni persona si registra nel suo savepoint: un errore su una non ferma le altre.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import DipendenteRuoloOperativo, RuoloOperativo

AGGIUNGI, SOSTITUISCI, CHIUDI = "aggiungi", "sostituisci", "chiudi"
MODI = {
    AGGIUNGI: "Aggiungi il ruolo",
    SOSTITUISCI: "Sostituisci il ruolo principale",
    CHIUDI: "Chiudi il ruolo",
}
MAX_PERSONE = 300


@dataclass
class Esito:
    legacy_id: int
    nome: str
    prima: str
    azione: str          # "cambia", "salta", "errore"
    dettaglio: str


def ruoli_in_essere(legacy_ids) -> dict[int, list[DipendenteRuoloOperativo]]:
    oggi = timezone.localdate()
    out: dict[int, list] = {}
    for a in (DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id__in=list(legacy_ids))
              .select_related("ruolo", "ruolo__ambito").order_by("ruolo__nome")):
        if a.data_fine is None or a.data_fine >= oggi:
            out.setdefault(a.legacy_anagrafica_id, []).append(a)
    return out


def persone(*, reparto: str = "", ruolo_id: int | None = None, cerca: str = "", area_id: int | None = None,
            mansione_id: int | None = None, senza_ruoli: bool = False, con_mansioni: bool = False) -> list[dict]:
    """Dipendenti attivi con reparto, area, ruolo principale e ruoli in essere (filtri facoltativi).

    ``con_mansioni`` aggiunge le mansioni in lista (per la pagina in blocco, non per l'import).
    """
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from ..models import AbilitazioneMacchina, DipendenteAnagraficaAziendale

    righe = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo", True) and r.get("id")]
    ids = [int(r["id"]) for r in righe]
    ruoli = ruoli_in_essere(ids)
    aziendale = {a.legacy_anagrafica_id: a for a in DipendenteAnagraficaAziendale.objects.filter(
        legacy_anagrafica_id__in=ids).select_related("area_aziendale")}
    mansioni: dict[int, list[str]] = {}
    if con_mansioni or mansione_id:
        for lid, mid, nome_m, key in (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=ids, in_lista=True,
                                                                         competenza__isnull=False)
                                      .values_list("legacy_anagrafica_id", "competenza_id", "competenza__display",
                                                   "competenza__competenza_key")):
            mansioni.setdefault(lid, []).append((mid, nome_m or key))
    cerca = (cerca or "").strip().casefold()
    out = []
    for r in righe:
        lid = int(r["id"])
        rep = (r.get("reparto") or "").strip()
        if reparto and rep.casefold() != reparto.casefold():
            continue
        az = aziendale.get(lid)
        if area_id and not (az and az.area_aziendale_id == area_id):
            continue
        assegnati = ruoli.get(lid, [])
        if ruolo_id and not any(a.ruolo_id == ruolo_id for a in assegnati):
            continue
        if senza_ruoli and assegnati:
            continue
        sue = mansioni.get(lid, [])
        if mansione_id and not any(mid == mansione_id for mid, _n in sue):
            continue
        nome = naming.nome_completo(r.get("nome"), r.get("cognome"))
        area = az.area_aziendale.nome if az and az.area_aziendale_id else ""
        if cerca and cerca not in f"{nome} {rep} {area}".casefold():
            continue
        out.append({
            "legacy_id": lid, "nome": nome, "reparto": rep, "area": area,
            "principale": ((az.ruolo_aziendale if az else "") or "").strip(),
            "ruoli": [a.ruolo.nome for a in assegnati],
            "mansioni": sorted((n for _m, n in sue), key=str.casefold),
        })
    out.sort(key=lambda p: p["nome"].casefold())
    return out


def _controlla(ruolo: RuoloOperativo, modo: str, data) -> None:
    if modo not in MODI:
        raise ValueError("Scegli che cosa fare.")
    if data is None:
        raise ValueError("Indica la data.")
    if modo == SOSTITUISCI and not ruolo.alimenta_ruolo_principale:
        raise ValueError(
            f"«{ruolo.nome}» è un ruolo dell'organigramma {ruolo.ambito_label}: non diventa il ruolo "
            "principale. Usa «Aggiungi il ruolo».")
    if modo == CHIUDI and data > timezone.localdate():
        raise ValueError("Un ruolo si chiude a una data di oggi o passata.")
    if modo != CHIUDI and not ruolo.is_active:
        raise ValueError(f"Il ruolo «{ruolo.nome}» è spento.")


def _previsione(p: dict, assegnati: list, ruolo: RuoloOperativo, modo: str, data) -> tuple[str, str]:
    """(azione, dettaglio) senza scrivere niente."""
    ha = any(a.ruolo_id == ruolo.pk for a in assegnati)
    if modo == AGGIUNGI:
        if ha:
            return "salta", "lo ricopre già"
        diventa = ruolo.alimenta_ruolo_principale and not p["principale"]
        return "cambia", "aggiunto" + (", diventa il ruolo principale" if diventa else "")
    if modo == SOSTITUISCI:
        if p["principale"].casefold() == ruolo.nome.casefold():
            return "salta", "è già il suo ruolo principale"
        prima = p["principale"] or "nessuno"
        return "cambia", f"principale {prima} → {ruolo.nome} dal {data:%d/%m/%Y}"
    if not ha:
        return "salta", "non ricopre questo ruolo"
    era_principale = p["principale"].casefold() == ruolo.nome.casefold()
    return "cambia", f"concluso il {data:%d/%m/%Y}" + (" (era il principale)" if era_principale else "")


def esegui(legacy_ids, *, ruolo: RuoloOperativo, modo: str, data, note: str = "", user=None,
           applica: bool = False) -> list[Esito]:
    """Anteprima (``applica=False``) o registrazione del cambio per ogni persona scelta."""
    _controlla(ruolo, modo, data)
    ids = list(dict.fromkeys(int(i) for i in legacy_ids))
    if not ids:
        raise ValueError("Scegli almeno una persona.")
    if len(ids) > MAX_PERSONE:
        raise ValueError(f"Al massimo {MAX_PERSONE} persone alla volta.")
    per_id = {p["legacy_id"]: p for p in persone()}
    ruoli = ruoli_in_essere(ids)
    esiti = []
    for lid in ids:
        p = per_id.get(lid)
        if p is None:
            esiti.append(Esito(lid, f"#{lid}", "", "errore", "non è un dipendente attivo"))
            continue
        azione, dettaglio = _previsione(p, ruoli.get(lid, []), ruolo, modo, data)
        if applica and azione == "cambia":
            try:
                with transaction.atomic():
                    dettaglio = _applica_una(lid, p, ruolo, modo, data, note, user) or dettaglio
            except Exception as exc:  # una persona non ferma le altre; il motivo si mostra
                azione, dettaglio = "errore", str(exc) or exc.__class__.__name__
        esiti.append(Esito(lid, p["nome"], p["principale"], azione, dettaglio))
    return esiti


def _applica_una(lid: int, p: dict, ruolo: RuoloOperativo, modo: str, data, note: str, user) -> str:
    from . import ruoli_sync

    if modo == AGGIUNGI:
        ruoli_sync.assicura_assegnazione(lid, ruolo.nome, user=user, data_inizio=data)
        if ruoli_sync.dopo_assegnazione(lid, ruolo, user=user):
            return "aggiunto, diventa il ruolo principale"
        return ""
    if modo == SOSTITUISCI:
        from .assegnazioni import crea_assegnazione

        crea_assegnazione(lid, data_inizio=data, ruolo_aziendale=ruolo.nome,
                          note=(note or "Cambio ruolo in blocco")[:500], user=user)
        return ""
    ruoli_sync.chiudi_assegnazione(lid, ruolo.nome, data_fine=data)
    if ruoli_sync.ruolo_principale(lid).casefold() == ruolo.nome.casefold():
        rimasti = [a for a in ruoli_sync.ruoli_che_alimentano(lid) if a.ruolo_id != ruolo.pk]
        nuovo = rimasti[0].ruolo.nome if rimasti else ""
        ruoli_sync._scrivi_principale(lid, nuovo, user=user)
        return f"concluso; ruolo principale ora {nuovo or 'vuoto'}"
    return ""
