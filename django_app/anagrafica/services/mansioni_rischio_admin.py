"""Gestione delle mansioni di rischio: salvataggio, anteprima dell'effetto, esposti.

Una modifica a una mansione di rischio (fattori, protocollo visite, DPI, regole)
o ai suoi collegamenti con le mansioni lavorative cambia i requisiti di tutti i
dipendenti di quelle mansioni. Prima di salvare, l'**anteprima** dice cosa
succederà («genera N nuove visite e M corsi»); dopo il salvataggio il
riallineamento degli adempimenti gira in background (``riallineamento``).
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction

from . import mansionario, requisiti, riallineamento
from .cambio_mansione import requisito_soddisfatto

_DOMINI = {"visite": "VISITA", "corsi": "FORMAZIONE", "dpi": "DPI"}


@dataclass
class Dati:
    codice: str
    nome: str
    descrizione: str = ""
    livello_rischio_dvr: str = ""
    dvr_revisione: str = ""
    dvr_data: object = None
    is_active: bool = True
    fattori: list[int] = field(default_factory=list)
    visite: list[int] = field(default_factory=list)
    categorie_dpi: list[int] = field(default_factory=list)
    mansioni: list[int] = field(default_factory=list)


@dataclass
class Effetto:
    dipendenti: int = 0
    mansioni: int = 0
    nuove: Counter = field(default_factory=Counter)        # dominio -> n adempimenti da creare
    non_piu_dovute: Counter = field(default_factory=Counter)
    gia_soddisfatte: int = 0
    senza_assegnazione: int = 0

    @property
    def frase(self) -> str:
        if not self.dipendenti:
            return "Nessun dipendente coinvolto: la modifica non genera adempimenti."
        parti = [f"{self.nuove.get('visite', 0)} nuove visite", f"{self.nuove.get('corsi', 0)} corsi",
                 f"{self.nuove.get('dpi', 0)} DPI"]
        frase = f"Questa modifica tocca {self.dipendenti} dipendenti e genera " + ", ".join(parti)
        tolte = sum(self.non_piu_dovute.values())
        if tolte:
            frase += f"; {tolte} adempimenti aperti diventano non più dovuti"
        return frase + "."


def _applica(mr, dati: Dati, user=None):
    from ..models_mansioni_rischio import MansioneLavorativaRischio

    for campo in ("codice", "nome", "descrizione", "livello_rischio_dvr", "dvr_revisione", "dvr_data", "is_active"):
        setattr(mr, campo, getattr(dati, campo))
    if mr.pk is None and getattr(user, "is_authenticated", False):
        mr.created_by = user
    mr.full_clean(exclude=["origine_mansione", "created_by"])
    mr.save()
    mr.fattori.set(dati.fattori)
    mr.visite.set(dati.visite)
    try:
        mr.categorie_dpi.set(dati.categorie_dpi)
    except Exception:
        pass
    attuali = set(mr.link_mansioni.values_list("mansione_id", flat=True))
    volute = set(dati.mansioni)
    mr.link_mansioni.filter(mansione_id__in=attuali - volute).delete()
    for mansione_id in volute - attuali:
        MansioneLavorativaRischio.objects.create(
            mansione_id=mansione_id, mansione_rischio=mr,
            ordine=MansioneLavorativaRischio.objects.filter(mansione_id=mansione_id).count(),
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
    return mr


def _mansioni_coinvolte(mr, dati: Dati) -> set[int]:
    prima = set(mr.link_mansioni.values_list("mansione_id", flat=True)) if mr.pk else set()
    return prima | set(dati.mansioni)


def anteprima(mr, dati: Dati) -> Effetto:
    """Effetto della modifica, calcolato applicandola in una transazione annullata."""
    effetto = Effetto()
    coinvolte = _mansioni_coinvolte(mr, dati)
    effetto.mansioni = len(coinvolte)
    if not coinvolte:
        return effetto
    foto = riallineamento.fotografa_mansioni(coinvolte)
    ctx = requisiti.ambito()
    tutti = {d.id: d for d in ctx._tutti()}
    # Copia: la transazione si annulla, ma l'istanza in memoria resterebbe
    # modificata (e una nuova riceverebbe un pk che non esiste).
    mr = copy.copy(mr)
    with transaction.atomic():
        _applica(mr, dati)
        for mansione_id in coinvolte:
            dopo = mansionario.requisiti_mansione(mansione_id)
            prima = foto.get(mansione_id, {})
            for legacy_id in riallineamento.dipendenti_della_mansione([mansione_id]):
                effetto.dipendenti += 1
                card = riallineamento.card_aperta(legacy_id)
                if card is None:
                    effetto.senza_assegnazione += 1
                persona = tutti.get(ctx.canonico(legacy_id))
                for dominio, tipo in _DOMINI.items():
                    gia = set(prima.get(dominio, []))
                    for obj in dopo[dominio]:
                        if obj.pk in gia:
                            continue
                        if persona is not None and requisito_soddisfatto(
                            tipo, obj.pk, ctx=ctx, persona=persona, dal=ctx.today,
                            mansione=card.mansione if card else "", entro=ctx.today,
                        ):
                            effetto.gia_soddisfatte += 1
                        else:
                            effetto.nuove[dominio] += 1
                    ora = {o.pk for o in dopo[dominio]}
                    if card is not None:
                        effetto.non_piu_dovute[dominio] += card.adempimenti.filter(
                            attivo=True, stato="APERTO", tipo=tipo,
                            riferimento_id__in=[pk for pk in gia if pk not in ora],
                        ).count()
        transaction.set_rollback(True)
    return effetto


def salva(mr, dati: Dati, *, user=None) -> tuple[object, bool]:
    """Salva e accoda il riallineamento dei dipendenti coinvolti (dopo il commit)."""
    coinvolte = _mansioni_coinvolte(mr, dati)
    foto = riallineamento.fotografa_mansioni(coinvolte) if coinvolte else {}
    foto_mr = riallineamento.fotografa_mansioni_rischio([mr.pk]) if mr.pk else {}
    nuova = mr.pk is None
    with transaction.atomic():
        mr = _applica(mr, dati, user=user)
        if foto or foto_mr:
            riallineamento.accoda_riallineamento(
                foto, causa=f"Modifica mansione di rischio «{mr.nome}»",
                user_id=getattr(user, "pk", None), prima_mr=foto_mr,
            )
    return mr, nuova


def esposti(mr) -> list[dict]:
    """Dipendenti esposti alla mansione di rischio: via mansione lavorativa o override."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    nomi = {n.strip().casefold(): n for n in mr.mansioni_lavorative.values_list("nome", flat=True)}
    aggiunti = {o.legacy_anagrafica_id: o for o in mr.override_dipendenti.filter(attivo=True, azione="ADD")}
    esclusi = set(mr.override_dipendenti.filter(attivo=True, azione="EXCLUDE").values_list("legacy_anagrafica_id", flat=True))
    out = []
    for row in fetch_anagrafica_rows(deduplicate=True):
        if not row.get("attivo", True):
            continue
        lid = int(row.get("id") or 0)
        mansione = str(row.get("mansione") or "").strip()
        via = None
        if mansione.casefold() in nomi and lid not in esclusi:
            via = f"Mansione «{mansione}»"
        elif lid in aggiunti:
            via = f"Aggiunta individuale dal {aggiunti[lid].data_inizio:%d/%m/%Y}"
        if via:
            out.append({"legacy_id": lid, "nome": naming.nome_completo(row.get("nome"), row.get("cognome")),
                        "mansione": mansione, "reparto": row.get("reparto") or "", "via": via})
    out.sort(key=lambda r: (r["nome"] or "").casefold())
    return out
