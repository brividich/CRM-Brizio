"""Mansionario: ruolo → mansione (macchina o processo) → persone.

Spec ``docs/superpowers/specs/2026-10-15-mansionario-ruolo-mansione-competenze-rischio-design.md``,
fase 2. La mansione è una colonna della skill matrix MOD.187 (``CompetenzaSkm``
di tipo macchina o processo, il «contatore» non è una mansione). Ha uno o più
ruoli, le mansioni di rischio che comporta (catalogo ``Mansione``) e un reparto:
quello dell'asset per le macchine, scelto per i processi.

Le persone sono le abilitazioni «in lista» sulla colonna (``AbilitazioneMacchina``,
legata alla colonna da ``competenza``; per le macchine vale anche l'asset).
Nessun dato sanitario: qui ci sono solo livelli di esperienza I/L/U/O.
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
    ordinale_livello,
)

TIPI_MANSIONE = (CompetenzaSkm.TIPO_MACCHINA, CompetenzaSkm.TIPO_PROCESSO)
LIVELLI = [c for c, _ in LivelloSkm.choices]  # I, L, U, O


def mansioni(*, solo_attive: bool = True):
    qs = (
        CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE)
        .select_related("asset", "reparto")
        .prefetch_related("ruoli", "mansioni_rischio")
        .order_by("tipo", "display", "competenza_key")
    )
    return qs.filter(attiva=True) if solo_attive else qs


def _abilitazioni_in_lista(competenze) -> dict[int, list[AbilitazioneMacchina]]:
    ids = [c.pk for c in competenze]
    out: dict[int, list] = {}
    if not ids:
        return out
    for ab in AbilitazioneMacchina.objects.filter(competenza_id__in=ids, in_lista=True):
        out.setdefault(ab.competenza_id, []).append(ab)
    return out


def riepilogo(*, solo_attive: bool = True) -> list[dict]:
    """Una riga per mansione con i conteggi per livello e gli operativi (una query per tutte)."""
    config = SkillMatrixConfig.get_instance()
    soglia = config.soglia_operativa_ordinale
    comps = list(mansioni(solo_attive=solo_attive))
    per_comp = _abilitazioni_in_lista(comps)
    righe = []
    for c in comps:
        abil = per_comp.get(c.pk, [])
        livelli = Counter(a.livello for a in abil)
        operativi = sum(1 for a in abil if a.is_operativa(soglia))
        righe.append({
            "mansione": c,
            "nome": c.nome,
            "tipo": c.tipo,
            "reparto": c.reparto_effettivo,
            "ruoli": list(c.ruoli.all()),
            "rischi": list(c.mansioni_rischio.all()),
            "livelli": {lv: livelli.get(lv, 0) for lv in LIVELLI},
            "in_lista": len(abil),
            "operativi": operativi,
            "uomo_solo": operativi < config.soglia_uomo_solo,
        })
    return righe


def kpi(righe: list[dict]) -> dict:
    return {
        "mansioni": len(righe),
        "senza_ruolo": sum(1 for r in righe if not r["ruoli"]),
        "senza_rischio": sum(1 for r in righe if not r["rischi"]),
        "scoperte": sum(1 for r in righe if not r["operativi"]),
    }


def persone(mansione: CompetenzaSkm) -> list[dict]:
    """Chi è in lista sulla mansione, con livello e stato (nomi dall'anagrafica)."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    abil = list(AbilitazioneMacchina.objects.filter(competenza=mansione, in_lista=True))
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=[a.legacy_anagrafica_id for a in abil])} if abil else {}
    out = [{
        "abilitazione": a,
        "legacy_id": a.legacy_anagrafica_id,
        "nome": nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}",
        "livello": a.livello,
        "operativa": a.is_operativa(soglia),
        "sospesa": a.stato == AbilitazioneMacchina.STATO_SOSPESA,
        "data_assegnazione": a.data_assegnazione,
        "prossima_revisione": a.prossima_revisione,
    } for a in abil]
    out.sort(key=lambda p: (-ordinale_livello(p["livello"]), p["nome"].casefold()))
    return out


@transaction.atomic
def salva_configurazione(mansione: CompetenzaSkm, *, ruoli_ids, rischi_ids, reparto_id=None, attiva=True) -> None:
    from ..models import Mansione, Reparto, RuoloOperativo

    mansione.ruoli.set(RuoloOperativo.objects.filter(pk__in=list(ruoli_ids), is_active=True))
    mansione.mansioni_rischio.set(Mansione.objects.filter(pk__in=list(rischi_ids), is_active=True))
    # Il reparto si sceglie solo per i processi senza asset: per le macchine vale l'asset.
    if not mansione.asset_id:
        mansione.reparto = Reparto.objects.filter(pk=reparto_id).first() if reparto_id else None
    mansione.attiva = bool(attiva)
    mansione.save(update_fields=["reparto", "attiva", "updated_at"])


@transaction.atomic
def assegna(mansione: CompetenzaSkm, *, legacy_anagrafica_id: int, livello: str, user=None) -> AbilitazioneMacchina:
    """Mette la persona in lista sulla mansione col livello dato (crea o aggiorna) e lo storicizza."""
    livello = (livello or "").strip().upper()
    if livello not in LIVELLI:
        raise ValueError(f"Livello non valido: {livello!r}")
    oggi = timezone.localdate()
    chiave = {"asset_id": mansione.asset_id} if mansione.asset_id else {"competenza": mansione}
    ab = AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_anagrafica_id, **chiave).first()
    if ab is None:
        ab = AbilitazioneMacchina(legacy_anagrafica_id=legacy_anagrafica_id, asset_id=mansione.asset_id,
                                  competenza=mansione, data_assegnazione=oggi)
    ab.competenza = mansione
    ab.livello = livello
    ab.in_lista = True
    ab.stato = AbilitazioneMacchina.STATO_ATTIVA
    if ab.data_assegnazione is None:
        ab.data_assegnazione = oggi
    ab.save()
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=legacy_anagrafica_id, asset_id=mansione.asset_id, competenza=mansione,
        livello=livello, data_rilevazione=oggi, fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
        note="Mansionario: assegnazione",
    )
    return ab


@transaction.atomic
def togli(abilitazione: AbilitazioneMacchina) -> None:
    """Toglie la persona dalla lista della mansione (la riga resta, con lo storico)."""
    abilitazione.in_lista = False
    abilitazione.save(update_fields=["in_lista", "updated_at"])
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=abilitazione.legacy_anagrafica_id, asset_id=abilitazione.asset_id,
        competenza_id=abilitazione.competenza_id, livello="", data_rilevazione=timezone.localdate(),
        fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE, note="Mansionario: tolto dalla lista",
    )


def reparto_principale(legacy_anagrafica_id: int) -> str:
    """Reparto della mansione con il livello più alto; a parità, la più vecchia (D13)."""
    abil = list(
        AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_anagrafica_id, in_lista=True,
                                            competenza__isnull=False)
        .select_related("competenza__asset", "competenza__reparto")
    )
    if not abil:
        return ""
    lontano = timezone.localdate().replace(year=9999)
    abil.sort(key=lambda a: (-ordinale_livello(a.livello), a.data_assegnazione or lontano, a.pk))
    return abil[0].competenza.reparto_effettivo
