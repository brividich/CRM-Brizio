"""F2b — Importer baseline Skill Matrix MOD.187 (dal seed CSV).

**Sicuro di default**: pianifica e NON scrive a meno di ``apply=True``. Ingerisce i
4 CSV seed (catalogo, operatori, matrice livelli, storico delta) e produce la
baseline ufficiale: ``AbilitazioneMacchina`` (snapshot più recente) + lo storico
append-only per ENTRAMBI gli snapshot.

Regole (cfr. README_skm_csv + BUILD_SPEC §F2b):
- operatori risolti per **nome** → ``legacy_anagrafica_id`` (anagrafica pulita,
  nessun gate); nome non risolto = **riportato** (mai drop silenzioso);
- macchine: solo competenze con **match asset confermato** (``match_confermato`` e
  ``asset``); macchina referenziata senza match confermato = **riga bloccata** e
  elencata (non si inventa l'asset);
- CAR (``is_car=SI``) → ``conteggiabile_nel_carico=False``; academy inclusi;
- cella vuota = NON in lista (nessun record), non livello 0;
- "corsi attivati" = contatore (``SkmCorsiAttivati``), non abilitazione;
- righe ``processo`` della matrice: NON entrano nello strato macchina (decisione
  F0 #4) → **contate e riportate**, non importate qui;
- idempotente: re-run non duplica (``update_or_create`` / storico per data).

NON gestisce gli alias storici delle macchine rinominate oltre a quanto già fatto
dal match asset (``CompetenzaSkm`` collega su CODICE via ``sincronizza_catalogo``).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CompetenzaSkm,
    SkmCorsiAttivati,
)
from .skillmatrix_seed import sincronizza_catalogo

SNAPSHOT_BASELINE = "2026-04-30"


def _repo_root() -> Path:
    return Path(settings.BASE_DIR).parent


def _default_dir() -> Path:
    return _repo_root() / "docs" / "anagrafica" / "skillmatrix"


def normalizza_nome(s: str | None) -> str:
    """Uppercase, spazi collassati: per il match operatore→anagrafica."""
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _mappa_nomi_legacy() -> tuple[dict, dict]:
    """Costruisce {nome_norm: legacy_id} da fetch_anagrafica_rows.

    Indicizza sia "COGNOME NOME" sia "NOME COGNOME". Ritorna (mappa, ambigui)."""
    from core.legacy_anagrafica import fetch_anagrafica_rows

    mappa: dict[str, int] = {}
    ambigui: dict[str, int] = {}
    for r in fetch_anagrafica_rows(deduplicate=True):
        rid = r.get("id")
        if not rid:
            continue
        nome = normalizza_nome(r.get("nome"))
        cognome = normalizza_nome(r.get("cognome"))
        chiavi = {f"{cognome} {nome}".strip(), f"{nome} {cognome}".strip()}
        for k in chiavi:
            if not k:
                continue
            if k in mappa and mappa[k] != int(rid):
                ambigui[k] = ambigui.get(k, 1) + 1
            else:
                mappa[k] = int(rid)
    return mappa, ambigui


def _leggi_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def importa_skill_matrix(*, base_dir=None, apply: bool = False,
                         baseline: str = SNAPSHOT_BASELINE) -> dict:
    """Pianifica (e con ``apply`` esegue) l'import baseline. Ritorna un dict-piano."""
    d = Path(base_dir) if base_dir else _default_dir()
    op_rows = _leggi_csv(d / "skm_operatori.csv")
    mat_rows = _leggi_csv(d / "skm_matrice_livelli.csv")
    delta_rows = _leggi_csv(d / "skm_storico_delta.csv")

    stats: dict = {
        "apply": apply,
        "baseline": baseline,
        "operatori": {"totale": len(op_rows), "risolti": 0, "non_risolti": [], "ambigui": []},
        "abilitazioni": {"create": 0, "aggiornate": 0, "in_lista": 0},
        "macchine_bloccate": [],
        "processi_saltati": 0,
        "competenze_sconosciute": [],
        "contatori": 0,
        "storico": {"scatti": 0, "snapshots": []},
        "coerenza_storico": {"verificate": 0, "mismatch": []},
    }
    if not op_rows or not mat_rows:
        stats["errore"] = f"Seed mancante o vuoto in {d} (operatori/matrice)."
        return stats

    # 1) Catalogo + match asset (idempotente; non scrive baseline).
    sincronizza_catalogo()
    comp_by_key = {c.competenza_key: c for c in CompetenzaSkm.objects.select_related("asset").all()}

    # 2) Operatori → legacy_id.
    nomi, ambigui_idx = _mappa_nomi_legacy()
    op_info: dict[str, dict] = {}
    for row in op_rows:
        nome = normalizza_nome(row.get("nome"))
        legacy = nomi.get(nome)
        is_car = (row.get("is_car") or "").strip().upper() in {"SI", "SÌ", "S", "TRUE", "1"}
        if legacy is None:
            stats["operatori"]["non_risolti"].append(nome)
            continue
        if nome in ambigui_idx:
            stats["operatori"]["ambigui"].append(nome)
        op_info[nome] = {
            "legacy_id": legacy,
            "is_car": is_car,
            "reparto": (row.get("reparto_area") or "").strip(),
            "car_rif": normalizza_nome(row.get("car_di_riferimento")),
        }
        stats["operatori"]["risolti"] += 1

    # 3) Pianifica abilitazioni (snapshot baseline) + storico (tutti gli snapshot).
    macch_bloccate: set[str] = set()
    sconosciute: set[str] = set()
    ab_plan: list[dict] = []     # baseline → AbilitazioneMacchina
    stor_plan: list[dict] = []   # tutti gli snapshot → storico
    contatori: dict[int, int] = {}

    for row in mat_rows:
        nome = normalizza_nome(row.get("operatore"))
        key = (row.get("competenza_key") or "").strip()
        livello = (row.get("livello") or "").strip().upper()
        snapshot = (row.get("snapshot") or "").strip()
        op = op_info.get(nome)
        if op is None:
            continue  # nome già contato tra i non_risolti
        comp = comp_by_key.get(key)
        if comp is None:
            sconosciute.add(key)
            continue
        if comp.tipo == CompetenzaSkm.TIPO_CONTATORE:
            if snapshot == baseline:
                try:
                    contatori[op["legacy_id"]] = int(float(row.get("valore_grezzo") or 0))
                except (TypeError, ValueError):
                    pass
            continue
        if comp.tipo == CompetenzaSkm.TIPO_PROCESSO:
            if snapshot == baseline and livello:
                stats["processi_saltati"] += 1
            continue
        # tipo == macchina
        if not (comp.match_confermato and comp.asset_id):
            macch_bloccate.add(key)
            continue
        if not livello:
            continue  # cella vuota = NON in lista
        # storico per ogni snapshot con livello
        stor_plan.append({
            "legacy_id": op["legacy_id"], "asset_id": comp.asset_id,
            "livello": livello, "data": snapshot,
            "car_legacy_id": nomi.get(op["car_rif"]),
        })
        if snapshot == baseline:
            ab_plan.append({
                "legacy_id": op["legacy_id"], "asset_id": comp.asset_id,
                "livello": livello, "conteggiabile": not op["is_car"],
                "car_legacy_id": nomi.get(op["car_rif"]),
            })

    stats["macchine_bloccate"] = sorted(macch_bloccate)
    stats["competenze_sconosciute"] = sorted(sconosciute)
    stats["contatori"] = len(contatori)
    stats["abilitazioni"]["in_lista"] = len(ab_plan)
    stats["storico"]["scatti"] = len(stor_plan)
    stats["storico"]["snapshots"] = sorted({s["data"] for s in stor_plan})

    # 4) Coerenza storico (delta atteso vs i 2 snapshot della matrice).
    liv_per_coppia: dict[tuple[str, str, str], str] = {}
    for row in mat_rows:
        liv_per_coppia[(
            normalizza_nome(row.get("operatore")),
            (row.get("competenza_key") or "").strip(),
            (row.get("snapshot") or "").strip(),
        )] = (row.get("livello") or "").strip().upper()
    for row in delta_rows:
        nome = normalizza_nome(row.get("operatore"))
        key = (row.get("competenza_key") or "").strip()
        atteso_2024 = (row.get("liv_2024_04_22") or "").strip().upper()
        atteso_2026 = (row.get("liv_2026_04_30") or "").strip().upper()
        got_2024 = liv_per_coppia.get((nome, key, "2024-04-22"), "")
        got_2026 = liv_per_coppia.get((nome, key, "2026-04-30"), "")
        stats["coerenza_storico"]["verificate"] += 1
        if got_2024 != atteso_2024 or got_2026 != atteso_2026:
            stats["coerenza_storico"]["mismatch"].append(
                f"{nome}/{key}: matrice({got_2024}->{got_2026}) vs delta({atteso_2024}->{atteso_2026})"
            )

    if not apply:
        return stats

    # 5) Scrittura baseline (transazionale, idempotente).
    with transaction.atomic():
        for p in ab_plan:
            _, creato = AbilitazioneMacchina.objects.update_or_create(
                legacy_anagrafica_id=p["legacy_id"], asset_id=p["asset_id"],
                defaults={
                    "livello": p["livello"], "in_lista": True,
                    "stato": AbilitazioneMacchina.STATO_ATTIVA,
                    "conteggiabile_nel_carico": p["conteggiabile"],
                    "car_legacy_id": p["car_legacy_id"],
                },
            )
            if creato:
                stats["abilitazioni"]["create"] += 1
            else:
                stats["abilitazioni"]["aggiornate"] += 1
        for s in stor_plan:
            AbilitazioneMacchinaStorico.objects.get_or_create(
                legacy_anagrafica_id=s["legacy_id"], asset_id=s["asset_id"],
                data_rilevazione=s["data"], fonte=AbilitazioneMacchinaStorico.FONTE_IMPORT,
                defaults={"livello": s["livello"], "car_legacy_id": s["car_legacy_id"]},
            )
        for legacy_id, numero in contatori.items():
            SkmCorsiAttivati.objects.update_or_create(
                legacy_anagrafica_id=legacy_id, defaults={"numero": numero},
            )
    return stats
