"""Report «Ruoli, mansioni e competenze per persona» (Excel).

Una riga per persona in forza: reparto, area, ruolo della struttura, mansioni
con livello e semaforo, mansioni previste dal ruolo non ancora assegnate,
mansione di rischio. Stessa regola delle proposte della scheda dipendente
(``struttura_persona.proposte``), calcolata in memoria: poche query per tutto.
"""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Q
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    CompetenzaSkm,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    SkillMatrixConfig,
)
from .mansionario_struttura import TIPI_MANSIONE

COLONNE = [
    "Cognome e nome", "Reparto", "Area", "Ruolo", "Diretto / indiretto", "Incarichi",
    "Mansioni", "Operative", "In addestramento", "Sospese", "Da assegnare",
    "Mansioni (livello)", "Previste dal ruolo, non assegnate", "Mansione di rischio",
]


def _proposta_valida(m: CompetenzaSkm, area) -> bool:
    if area is None:
        return True
    return m.area_id == area.pk or (m.area_id is None and m.reparto_id in (area.reparto_id, None))


def righe(*, reparto_id: int | None = None) -> list[list]:
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    persone = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo", True) and r.get("id")]
    ids = [int(r["id"]) for r in persone]
    aziendale = {a.legacy_anagrafica_id: a for a in DipendenteAnagraficaAziendale.objects.filter(
        legacy_anagrafica_id__in=ids).select_related("area_aziendale__reparto")}
    if reparto_id:
        persone = [r for r in persone if (a := aziendale.get(int(r["id"]))) and a.area_aziendale_id
                   and a.area_aziendale.reparto_id == reparto_id]

    oggi = timezone.localdate()
    ruoli_di: dict[int, list] = defaultdict(list)
    for a in (DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                      legacy_anagrafica_id__in=ids)
              .select_related("ruolo", "ruolo__ambito").order_by("ruolo__nome")):
        ruoli_di[a.legacy_anagrafica_id].append(a)

    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    abil_di: dict[int, list] = defaultdict(list)
    for ab in (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=ids, in_lista=True,
                                                   competenza__isnull=False)
               .select_related("competenza").order_by("competenza__display")):
        abil_di[ab.legacy_anagrafica_id].append(ab)

    mansioni = list(CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True,
                                                 responsabilita_reparto__isnull=True,
                                       responsabilita_area__isnull=True)
                    .prefetch_related("ruoli").order_by("display"))
    per_ruolo: dict[int, list] = defaultdict(list)
    for m in mansioni:
        for r in m.ruoli.all():
            per_ruolo[r.pk].append(m)

    out = []
    for r in sorted(persone, key=lambda r: (str(r.get("cognome") or "").casefold(), str(r.get("nome") or "").casefold())):
        lid = int(r["id"])
        az = aziendale.get(lid)
        area = az.area_aziendale if az and az.area_aziendale_id else None
        reparto = area.reparto.nome if area and area.reparto_id else (az.area if az else "") or str(r.get("reparto") or "")
        assegnazioni = ruoli_di.get(lid, [])
        struttura = [a for a in assegnazioni if a.ruolo.alimenta_ruolo_principale]
        incarichi = [a.ruolo.nome for a in assegnazioni if not a.ruolo.alimenta_ruolo_principale]
        abil = abil_di.get(lid, [])
        operative = sum(1 for a in abil if a.stato != AbilitazioneMacchina.STATO_SOSPESA and a.is_operativa(soglia))
        sospese = sum(1 for a in abil if a.stato == AbilitazioneMacchina.STATO_SOSPESA)
        assegnate = {a.competenza_id for a in abil}
        previste = {m.pk: m for a in struttura for m in per_ruolo.get(a.ruolo_id, [])
                    if m.pk not in assegnate and _proposta_valida(m, area)}
        out.append([
            naming.nome_completo(r.get("nome"), r.get("cognome")),
            reparto,
            area.nome if area else "",
            ", ".join(a.ruolo.etichetta for a in struttura),
            ", ".join(sorted({a.ruolo.get_classe_display() for a in struttura if a.ruolo.classe})),
            ", ".join(incarichi),
            len(abil), operative, len(abil) - operative - sospese, sospese, len(previste),
            "; ".join(f"{a.competenza.nome} [{a.livello or '-'}]" for a in abil),
            "; ".join(sorted((m.nome for m in previste.values()), key=str.casefold)),
            str(r.get("mansione") or ""),
        ])
    return out
