"""Sincronizzazione del catalogo competenze MOD.187 → ``CompetenzaSkm``.

Popola/aggiorna il catalogo (lo "specchietto" di abbinamento competenza→asset)
**dagli asset live** dell'ambiente in cui gira (dev o prod), così l'abbinamento
è sempre coerente con il parco macchine reale. Sorgente del catalogo: il modulo
imballato ``anagrafica.skillmatrix_catalogo`` (nessun dato personale, sempre
disponibile in prod dove ``docs/`` è escluso dal pacchetto).

Idempotente. **Non scrive baseline** (nessuna ``AbilitazioneMacchina``): tocca
solo ``CompetenzaSkm`` (catalogo + cache match). Le conferme manuali
(``match_confermato=True``) vengono **preservate** dai re-run.
"""
from __future__ import annotations

from anagrafica.skillmatrix_catalogo import CATALOGO_MOD187
from anagrafica.services.skillmatrix_match import (
    CONF_ESATTO,
    IndiceAssetSkm,
    match_competenza,
)


def sincronizza_catalogo(*, catalogo=None, dry_run: bool = False) -> dict:
    """Upsert del catalogo e (ri)calcolo del match per le macchine.

    Ritorna un dict di statistiche. Per le righe già confermate a mano non
    ricalcola il match (preserva la decisione umana).
    """
    from assets.models import Asset
    from anagrafica.models import CompetenzaSkm, TipoQualifica

    catalogo = catalogo if catalogo is not None else CATALOGO_MOD187

    assets = list(Asset.objects.all().only("id", "asset_tag", "name", "asset_type"))
    asset_per_id = {a.id: a for a in assets}
    indice = IndiceAssetSkm.costruisci(assets)
    tq_per_nome = {t.nome.casefold(): t for t in TipoQualifica.objects.all().only("id", "nome")}

    stats = {
        "creati": 0, "aggiornati": 0,
        "macchine": 0, "esatti": 0, "parziali": 0, "assenti": 0, "confermati": 0,
        "processi": 0, "processi_collegati": 0, "contatori": 0,
    }

    for c in catalogo:
        key = (c.get("competenza_key") or "").strip()
        if not key:
            continue
        tipo = (c.get("tipo") or "").strip().lower()
        obj = CompetenzaSkm.objects.filter(competenza_key=key).first()
        created = obj is None
        if obj is None:
            obj = CompetenzaSkm(competenza_key=key)
        obj.display = (c.get("display") or "").strip()
        obj.tipo = tipo or CompetenzaSkm.TIPO_MACCHINA
        obj.alias_storici = (c.get("alias_storici") or "").strip()
        obj.note = (c.get("note") or "").strip()

        if tipo == CompetenzaSkm.TIPO_MACCHINA:
            stats["macchine"] += 1
            if not obj.match_confermato:
                r = match_competenza(c.get("codice", ""), obj.display, indice)
                obj.match_confidenza = r.confidenza
                obj.match_strategia = r.strategia
                obj.asset = asset_per_id.get(getattr(r.asset, "id", None)) if r.asset else None
                # "esatto" = pre-approvato (la spec): auto-conferma se c'è l'asset.
                if r.confidenza == CONF_ESATTO and obj.asset is not None:
                    obj.match_confermato = True
            # statistiche sullo stato corrente
            stats[{"esatto": "esatti", "parziale": "parziali", "assente": "assenti"}.get(
                obj.match_confidenza, "parziali")] += 1
            if obj.match_confermato:
                stats["confermati"] += 1
        elif tipo == CompetenzaSkm.TIPO_PROCESSO:
            stats["processi"] += 1
            obj.match_confidenza = CompetenzaSkm.CONF_NA
            if not obj.match_confermato:
                tq = tq_per_nome.get(obj.display.casefold()) or tq_per_nome.get(key.casefold())
                obj.tipo_qualifica = tq
                if tq:
                    stats["processi_collegati"] += 1
        else:  # contatore
            stats["contatori"] += 1
            obj.match_confidenza = CompetenzaSkm.CONF_NA

        if not dry_run:
            obj.save()
        stats["creati" if created else "aggiornati"] += 1

    return stats
