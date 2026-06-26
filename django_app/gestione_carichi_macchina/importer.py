"""Orchestrazione dell'import di Carichi_macchina.xlsx.

Due livelli separati:
- READER (openpyxl): legge il workbook -> lista di `Voce`. Il layout esatto del foglio
  e' un'ASSUNZIONE documentata (vedi `leggi_workbook`) DA CALIBRARE sul file reale.
- ALGORITMO (`importa`): consuma le `Voce` e popola il DB in modo IDEMPOTENTE
  (dedup storico, affinita', pool di equivalenza, report dei codici non mappati).
  Non dipende da openpyxl -> testabile con liste di Voce costruite a mano.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime

from django.db import transaction

from .asset_resolver import (
    CONF_ALTA, IndiceAsset, normalizza_codice_attacco, risolvi,
)
from .parsing import build_vocabolario, parse_cell, parse_cicli, scegli_famiglia

# --- mappa sezione foglio -> categoria di pianificazione -------------------
_SEZIONE_CATEGORIA = {
    "macchine 4 axis": "4_axis",
    "4 axis": "4_axis",
    "torni fresa": "torni_fresa",
    "macchine 5 axis": "5_axis",
    "5 axis": "5_axis",
    "alesatrici": "alesatrici",
    "torni": "torni",
}
# ordine specifico-prima (torni fresa prima di torni, ecc.)
_SEZIONE_ORDINE = (
    "macchine 4 axis", "torni fresa", "macchine 5 axis", "alesatrici",
    "4 axis", "5 axis", "torni",
)
_RE_NOTTE = re.compile(r"nottur|week\s*[- ]?\s*end|weekend", re.IGNORECASE)
_RE_TITLE_DATE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?")
# Titoli reali tipo "AGG 22 GIU", "AGG 16 GIUG", "AGG 24LUG" (mese italiano abbreviato,
# anche senza spazio, senza anno). NB: e' solo un FALLBACK: la snapshot_date primaria si
# ricava dalle date reali delle colonne-giorno (anno corretto, vedi _leggi_fogli).
_MESI_IT = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}
_RE_TITLE_MESE = re.compile(
    r"(\d{1,2})\s*(gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)", re.IGNORECASE,
)


@dataclass
class Voce:
    codice_macchina: str
    categoria: str
    turno: str           # giorno | notte
    data: date
    testo: str
    snapshot_idx: int    # 0 = snapshot piu' recente (piano vivo)
    snapshot_date: date | None = None


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def categoria_da_sezione(label: str) -> str | None:
    norm = _collapse(label).lower()
    if norm in _SEZIONE_CATEGORIA:
        return _SEZIONE_CATEGORIA[norm]
    for key in _SEZIONE_ORDINE:
        if key in norm:
            return _SEZIONE_CATEGORIA[key]
    return None


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return ""
    return str(v).strip()


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _parse_title_date(title: str) -> date | None:
    t = title or ""
    m = _RE_TITLE_DATE.search(t)
    if m:
        d, mth, y = m.group(1), m.group(2), m.group(3)
        try:
            anno = int(y) if y else date.today().year
            if anno < 100:
                anno += 2000
            return date(anno, int(mth), int(d))
        except ValueError:
            return None
    # fallback: mese italiano abbreviato senza anno -> anno corrente (best effort).
    # In pratica conta poco: per i fogli reali la snapshot_date arriva dalle colonne-giorno.
    mm = _RE_TITLE_MESE.search(t)
    if mm:
        try:
            return date(date.today().year, _MESI_IT[mm.group(2).lower()], int(mm.group(1)))
        except ValueError:
            return None
    return None


def leggi_workbook(path: str) -> tuple[list[Voce], list[str], list[str], list[str]]:
    """Legge il workbook -> (voci, titoli, backlog, cicli_lines).

    - voci: lavori della matrice (macchine x giorni), tutti gli snapshot.
    - titoli: titoli dei fogli AGG in ordine (primo = piu' recente).
    - backlog/cicli_lines: testi delle sezioni in coda al foglio, SOLO dal foglio piu'
      recente (snapshot 0).

    LAYOUT (calibrato sul file reale):
    - fogli-snapshot col titolo che inizia per 'AGG';
    - riga-date = prima riga con >=2 celle data; la sua col 0 puo' portare la prima sezione;
    - col A: intestazione di sezione | codice macchina | 'notturno/week end' | (in coda)
      righe di backlog ordini | sezione 'CICLI ...:';
    - una riga e' una MACCHINA solo se ha lavori nelle colonne-giorno; altrimenti, prima dei
      CICLI, e' una riga di backlog.
    """
    import openpyxl  # import locale: dipendenza usata solo dal reader

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    voci: list[Voce] = []
    titoli: list[str] = []
    backlog: list[str] = []
    cicli_lines: list[str] = []
    try:
        _leggi_fogli(wb, voci, titoli, backlog, cicli_lines)
    finally:
        # read_only tiene aperto il file: senza close() perde l'handle (e su Windows
        # blocca la cancellazione del file).
        wb.close()
    return voci, titoli, backlog, cicli_lines


def _riga_ha_giorni(row, day_cols: dict[int, date]) -> bool:
    return any((c < len(row)) and _cell_str(row[c]) for c in day_cols)


_RE_INIZIA_QTA = re.compile(r"^\s*\d")


def _pare_lavoro_non_macchina(first: str) -> bool:
    """True se la riga col-A e' una DESCRIZIONE di lavoro/ordine, non un codice macchina.

    I codici-officina sono mnemonici corti e maiuscoli (``CNV``, ``MZ5``, ``DIXI80``,
    ``MK1 HSK``, ``HH ISO40``, ``TORNIO TRAD 1``). Le righe d'ordine (``6 ragni ferrari``,
    ``carrier AVIO EURODRONE``, ``MONO V2 LAMBORGHINI``) a volte hanno contenuto nelle
    colonne-giorno e sfuggono al filtro backlog (``_riga_ha_giorni``), finendo per essere
    prese per macchine. Questo guard le riconosce e le rimanda al backlog.

    Conservativo per costruzione: scarta solo i casi CHIARI (quantita' iniziale, testo
    lungo, troppe parole) cosi' da non perdere nessun codice-macchina reale. Qualche
    descrizione ambigua e corta puo' restare: e' innocua (non mappa ad asset -> saltata).
    """
    s = (first or "").strip()
    if not s:
        return False
    if _RE_INIZIA_QTA.match(s):    # "6 ragni", "11 carrier", "2+4 motori", "12 ZENZERI"
        return True
    if len(s.split()) > 3:         # "Nuovo assieme basamento APRILIA 850", "Alberi corti Alluminio FR"
        return True
    if len(s) > 16:               # "carrier AVIO EURODRONE", "MONO V2 LAMBORGHINI"
        return True
    return False


def _leggi_fogli(wb, voci, titoli, backlog, cicli_lines) -> None:
    from .parsing import RE_CICLI_HDR

    snap_idx = 0
    for ws in wb.worksheets:
        if not ws.title.strip().lower().startswith("agg"):
            continue
        titoli.append(ws.title)
        snap_date = _parse_title_date(ws.title)  # fallback dal titolo (mese IT incl.)
        day_cols: dict[int, date] = {}
        header_found = False
        cicli_mode = False
        current_cat: str | None = None
        last_machine: str | None = None
        for row in ws.iter_rows(values_only=True):
            if not header_found:
                dcols = {i: _as_date(c) for i, c in enumerate(row) if _as_date(c)}
                if len(dcols) >= 2:
                    day_cols = dcols
                    header_found = True
                    # snapshot_date PRIMARIA dalla data reale piu' recente del foglio:
                    # anno corretto, nessuna inferenza dal titolo "AGG 22 GIU".
                    snap_date = max(day_cols.values())
                    cat0 = categoria_da_sezione(_cell_str(row[0]) if row else "")
                    if cat0:
                        current_cat = cat0
                continue
            first = _cell_str(row[0]) if row else ""
            norm = _collapse(first).lower()
            if not norm:
                continue

            if cicli_mode:
                if snap_idx == 0:
                    cicli_lines.append(first)
                continue
            if RE_CICLI_HDR.match(first):       # inizio sezione CICLI
                cicli_mode = True
                if snap_idx == 0:
                    cicli_lines.append(first)
                continue

            cat = categoria_da_sezione(norm)
            if cat:
                current_cat = cat
                last_machine = None
                continue

            if _RE_NOTTE.search(norm):
                macchina, turno = last_machine, "notte"
            else:
                # macchina solo se ci sono lavori nei giorni; altrimenti e' backlog ordini
                if not _riga_ha_giorni(row, day_cols):
                    if snap_idx == 0:
                        backlog.append(first)
                    continue
                # ... e solo se col-A somiglia a un codice-macchina: una riga d'ordine con
                # contenuto nelle colonne-giorno ("6 ragni ferrari") non e' una macchina.
                if _pare_lavoro_non_macchina(first):
                    if snap_idx == 0:
                        backlog.append(first)
                    continue
                macchina, turno = first, "giorno"
                last_machine = first
            if not macchina or current_cat is None:
                continue
            for col, giorno in day_cols.items():
                if col >= len(row):
                    continue
                testo = _cell_str(row[col])
                if not testo:
                    continue
                voci.append(Voce(
                    codice_macchina=macchina, categoria=current_cat, turno=turno,
                    data=giorno, testo=testo, snapshot_idx=snap_idx,
                    snapshot_date=snap_date,
                ))
        snap_idx += 1


def fondi_edizioni(
    letture: list[tuple[list[Voce], list[str], list[str], list[str]]],
) -> tuple[list[Voce], list[str], list[str], list[str]]:
    """Fonde più edizioni del foglio per un import **cumulativo** dagli snapshot storici.

    `letture` = lista di tuple `(voci, titoli, backlog, cicli_lines)`, una per file
    (l'output di `leggi_workbook`). Ritorna un'unica tupla `(voci, titoli, backlog,
    cicli_lines)` in cui:

    - l'edizione **più recente** (massima `snapshot_date` tra i suoi fogli `AGG`)
      fornisce il **piano vivo**: le sue voci mantengono lo `snapshot_idx` (0 = vivo) e
      i suoi `titoli`/`backlog`/`cicli_lines` sono quelli restituiti;
    - le edizioni più **vecchie** diventano **solo storico** (`snapshot_idx` forzato a
      >= 1): arricchiscono affinità/recency/pool ma non ridefiniscono il piano corrente,
      né il backlog/cicli.

    Il dedup di `importa` su `(macchina, data, testo)` riconcilia automaticamente le
    settimane in comune tra edizioni (nessun doppio conteggio): le settimane presenti
    **solo** nelle edizioni vecchie aggiungono occorrenze e date allo storico, le altre
    incrementano soltanto `settimane_presente`.

    Recency: si usa la data degli snapshot `AGG`. Se i titoli non contengono date
    parsabili la recency è indeterminata e vale l'ordine d'ingresso (elenca per primo il
    file più recente). Il sort è stabile, quindi a parità di data l'ordine è preservato.
    """
    letture = [l for l in letture if l and l[0]]
    if not letture:
        return [], [], [], []

    def _recency(lettura) -> date:
        ds = [v.snapshot_date for v in lettura[0] if v.snapshot_date]
        return max(ds) if ds else date.min

    ordinati = sorted(letture, key=_recency, reverse=True)  # stabile: tie = ordine d'ingresso
    voci_out: list[Voce] = list(ordinati[0][0])  # edizione viva: snapshot_idx invariato
    for voci, *_ in ordinati[1:]:
        # storico puro: mai snapshot 0 (non tocca piano vivo/backlog/cicli)
        voci_out.extend(replace(v, snapshot_idx=max(1, v.snapshot_idx)) for v in voci)
    _voci0, titoli, backlog, cicli_lines = ordinati[0]
    return voci_out, titoli, backlog, cicli_lines


def _stato_ferma(testo: str) -> str:
    from .models import Macchina
    t = testo.lower()
    if "manuten" in t:
        return Macchina.STATO_MANUTENZIONE
    return Macchina.STATO_GUASTO


@transaction.atomic
def importa(voci: list[Voce], titoli: list[str] | None = None, *,
           backlog: list[str] | None = None, cicli_lines: list[str] | None = None,
           dry_run: bool = False) -> dict:
    """Popola il DB in modo idempotente. Ritorna un report sintetico."""
    from .models import (
        FamigliaPezzo, Macchina, MacchinaAlias, MacchinaFamigliaAffinita,
        Pianificazione,
    )
    from assets.models import Asset

    report: dict = {
        "voci": len(voci),
        "codici": 0,
        "macchine_mappate": 0,
        "non_mappati": [],          # [(codice, confidenza, motivo)]
        "famiglie": 0,
        "pianificazioni_live": 0,
        "affinita": 0,
        "pool": 0,
        "commesse": 0,
        "cicli": 0,
        "operazioni": 0,
    }

    # --- A. risoluzione macchine -----------------------------------------
    indice = IndiceAsset.costruisci(Asset.objects.all())
    # categoria + ordine prevalenti dalla sezione del foglio (snapshot vivo)
    cat_per_codice: dict[str, Counter] = defaultdict(Counter)
    att_per_codice: dict[str, Counter] = defaultdict(Counter)
    ordine_live: dict[str, int] = {}
    for v in voci:
        code_n, attacco = normalizza_codice_attacco(v.codice_macchina)
        cat_per_codice[code_n][v.categoria] += 1
        if attacco:
            att_per_codice[code_n][attacco] += 1
        if v.snapshot_idx == 0 and code_n not in ordine_live:
            ordine_live[code_n] = len(ordine_live)

    mappa: dict[str, object] = {}
    codici = sorted(cat_per_codice.keys())
    report["codici"] = len(codici)
    for code_n in codici:
        alias = (MacchinaAlias.objects.filter(codice_foglio=code_n)
                 .select_related("macchina").first())
        if alias:
            mappa[code_n] = alias.macchina
            continue
        r = risolvi(code_n, indice)
        if r.asset is None:
            mappa[code_n] = None
            report["non_mappati"].append((code_n, r.confidenza, r.motivo))
            continue
        categoria = cat_per_codice[code_n].most_common(1)[0][0]
        attacco = att_per_codice[code_n].most_common(1)[0][0] if att_per_codice.get(code_n) else Macchina.ATTACCO_NA
        if attacco not in dict(Macchina.ATTACCO_CHOICES):
            attacco = Macchina.ATTACCO_NA
        macchina, _ = Macchina.objects.get_or_create(
            asset=r.asset,
            defaults={"categoria": categoria, "attacco": attacco,
                      "ordine_sezione": ordine_live.get(code_n, 0)},
        )
        MacchinaAlias.objects.get_or_create(
            codice_foglio=code_n,
            defaults={"macchina": macchina, "fonte": r.fonte,
                      "da_confermare": r.confidenza != CONF_ALTA},
        )
        mappa[code_n] = macchina
    report["macchine_mappate"] = sum(1 for m in mappa.values() if m is not None)

    # --- B. vocabolario famiglia (due passate) ---------------------------
    noti, freq = build_vocabolario([v.testo for v in voci])
    fam_cache: dict[str, object] = {}

    def get_famiglia(nome: str):
        if nome not in fam_cache:
            fam_cache[nome], _ = FamigliaPezzo.objects.get_or_create(nome=nome)
        return fam_cache[nome]

    # --- C. dedup storico + affinita' ------------------------------------
    # chiave (macchina_id, data, testo_lower) -> settimane_presente + parse
    dedup: dict[tuple, dict] = {}
    for v in voci:
        m = mappa.get(normalizza_codice_attacco(v.codice_macchina)[0])
        if m is None:
            continue
        p = parse_cell(v.testo)
        if p.macchina_ferma:
            continue
        key = (m.id, v.data, v.testo.lower())
        if key in dedup:
            dedup[key]["settimane"] += 1
            continue
        fam_nome = scegli_famiglia(p, noti, freq)
        dedup[key] = {
            "macchina": m, "data": v.data, "parse": p,
            "famiglia": fam_nome, "settimane": 1, "turno": v.turno,
        }

    # affinita' per (macchina, famiglia)
    aff: dict[tuple, dict] = {}
    for info in dedup.values():
        fam_nome = info["famiglia"]
        if not fam_nome:
            continue
        k = (info["macchina"].id, fam_nome)
        a = aff.setdefault(k, {"macchina": info["macchina"], "fam": fam_nome,
                               "occ": 0, "ore": [], "ultima": None, "date": set()})
        a["occ"] += 1
        if info["parse"].ore:
            a["ore"].append(info["parse"].ore)
        a["ultima"] = max(a["ultima"], info["data"]) if a["ultima"] else info["data"]
        a["date"].add(info["data"])

    # --- D. pool di equivalenza (euristico, da_confermare) ---------------
    # stessa famiglia + stesse occorrenze + insiemi di date disgiunti
    pool_assign: dict[tuple, str] = {}
    per_fam: dict[str, list] = defaultdict(list)
    for k, a in aff.items():
        per_fam[a["fam"]].append((k, a))
    pool_count = 0
    for fam_nome, items in per_fam.items():
        per_occ: dict[int, list] = defaultdict(list)
        for k, a in items:
            per_occ[a["occ"]].append((k, a))
        for occ, group in per_occ.items():
            if len(group) < 2:
                continue
            disgiunti = all(
                group[i][1]["date"].isdisjoint(group[j][1]["date"])
                for i in range(len(group)) for j in range(i + 1, len(group))
            )
            if disgiunti:
                pool_id = f"{fam_nome}#{occ}"
                pool_count += 1
                for k, _a in group:
                    pool_assign[k] = pool_id
    report["pool"] = pool_count

    # --- E. scritture: famiglie, affinita', pianificazioni live ----------
    for k, a in aff.items():
        fam = get_famiglia(a["fam"])
        ore_medie = round(sum(a["ore"]) / len(a["ore"]), 2) if a["ore"] else None
        MacchinaFamigliaAffinita.objects.update_or_create(
            macchina=a["macchina"], famiglia=fam,
            defaults={
                "occorrenze": a["occ"], "ore_medie": ore_medie,
                "ultima_data": a["ultima"],
                "pool_equivalenza": pool_assign.get(k, ""),
                "da_confermare": k in pool_assign,
            },
        )
    report["affinita"] = len(aff)
    report["famiglie"] = FamigliaPezzo.objects.count()

    # snapshot vivo -> pianificazioni (rispetta righe manuali/ai)
    for v in voci:
        if v.snapshot_idx != 0:
            continue
        m = mappa.get(normalizza_codice_attacco(v.codice_macchina)[0])
        if m is None:
            continue
        p = parse_cell(v.testo)
        if p.macchina_ferma:
            m.stato_pianificazione = _stato_ferma(v.testo)
            m.save(update_fields=["stato_pianificazione", "updated_at"])
            continue
        fam_nome = scegli_famiglia(p, noti, freq)
        fam = get_famiglia(fam_nome) if fam_nome else None
        settimane = dedup.get((m.id, v.data, v.testo.lower()), {}).get("settimane", 1)
        esistente = Pianificazione.objects.filter(
            macchina=m, data=v.data, turno=v.turno, testo_originale=v.testo,
        ).first()
        if esistente and esistente.fonte != Pianificazione.FONTE_IMPORT:
            continue  # non sovrascrivere edit manuali/ai
        valori = {
            "famiglia": fam, "qta": p.qta, "ore": p.ore,
            "fase": p.fase or Pianificazione.FASE_NA,
            "settimane_presente": settimane,
            "fonte": Pianificazione.FONTE_IMPORT,
        }
        Pianificazione.objects.update_or_create(
            macchina=m, data=v.data, turno=v.turno, testo_originale=v.testo,
            defaults=valori,
        )
        report["pianificazioni_live"] += 1

    # --- F. backlog ordini -> Commesse ; CICLI -> CicloStandard/Operazione
    from .models import CicloStandard, Commessa, Operazione

    for testo in (backlog or []):
        testo = (testo or "").strip()
        if not testo:
            continue
        pc = parse_cell(testo)
        Commessa.objects.update_or_create(
            nome=testo[:200],
            defaults={"pezzo": testo[:200], "quantita": pc.qta, "stato": Commessa.STATO_APERTA},
        )
        report["commesse"] += 1

    for c in parse_cicli(cicli_lines or []):
        fam_nome = scegli_famiglia(parse_cell(c["pezzo"]), noti, freq) if c["pezzo"] else None
        fam = get_famiglia(fam_nome) if fam_nome else None
        codice = (f'{c["cliente"]} {c["pezzo"]}').strip()[:64]
        note = ((f'Cliente: {c["cliente"]}\n') if c["cliente"] else "") + "\n".join(c["note"])
        ciclo, _ = CicloStandard.objects.update_or_create(
            codice=codice,
            defaults={"nome": c["pezzo"][:200], "famiglia": fam, "note": note.strip()},
        )
        report["cicli"] += 1
        for op in c["operazioni"]:
            mac = mappa.get(normalizza_codice_attacco(op["macchina"])[0]) if op["macchina"] else None
            Operazione.objects.update_or_create(
                ciclo=ciclo, seq=op["seq"],
                defaults={"macchina_preferita": mac, "regola_sostituzione": op["regola"],
                          "tempo_cent_cad": op["tempo"]},
            )
            report["operazioni"] += 1

    report["famiglie"] = FamigliaPezzo.objects.count()

    if dry_run:
        transaction.set_rollback(True)
    return report
