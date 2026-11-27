"""Organigramma ufficiale: disegno a mano, avvisi, riepilogo delle modifiche, pubblicazione.

Il disegno è un dizionario JSON::

    {"v": 1, "nodi": [
        {"id": "n1", "tipo": "box" | "gruppo", "x": 0, "y": 0, "w": 220, "h": 60,
         "ruolo": 3 | None, "persona": 41 | None, "mansione": 7 | None,
         "titolo": "", "sotto": "",          # testo libero (o sostituisce quello calcolato)
         "padre": "n0" | None, "staff": False, # collegamento verso il riquadro superiore
         "gruppo": "g1" | None,                # gruppo che contiene il riquadro
         "colore": "#0f2a5c", "stile": "pieno" | "bordo" | "tratteggio",
         "reparto": "",                         # intestazione del riquadro (es. SALES DEPT)
         "ruoli_extra": [4, 9],                 # altri ruoli del responsabile (es. MSM + BDO)
         "tutti_titolari": False,               # responsabili = tutti i titolari del ruolo
         "elenco_ruoli": [12],                  # collaboratori: titolari di questi ruoli, si aggiorna da solo
         "elenco_righe": ["Testo – SIGLA"],     # righe scritte a mano in fondo all'elenco
         "elenco_nascosti": [41],               # persone tolte dall'elenco automatico
         "elenco_sigle": True,                  # sigla del ruolo accanto ai nomi dell'elenco
         "icona": "" | "capo" | ...,            # una di ICONE
         "lato": False,                         # linea che arriva di lato dal tronco del superiore
         "tronco": "centro" | "sinistra" | "destra"},  # da dove scende la linea verso i sottoposti
    ],
     "foglio": {"stile": "hub" | "documento", "titolo": "", "sottotitolo": "", "intestazione": "",
                "azienda": "", "piede": "", "logo": True, "ruoli_blu": True}}

Niente di quello che c'è qui scrive su ruoli, «riporta a», assegnazioni o
permessi: il disegno li *legge* per nomi, foto e avvisi.
"""
from __future__ import annotations

import re
from datetime import date

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import naming

VERSIONE = 1
MAX_NODI = 600
STILI = ("pieno", "bordo", "tratteggio")
TRONCHI = ("centro", "sinistra", "destra")
STILI_FOGLIO = ("hub", "documento")
#: Icone disponibili nei riquadri (i disegni stanno nel partial _org_uff_render.html).
ICONE = ("capo", "medico", "rspp", "preposto", "antincendio", "primo_soccorso", "rls", "lavoratori",
         "persona", "ufficio", "qualita", "ingranaggio")
MAX_LISTA_RUOLI = 12
MAX_RIGHE = 80
COLORE_DEFAULT = "#0f2a5c"
#: Colori proposti nella tela (il server accetta qualunque esadecimale).
PALETTE = ("#0f2a5c", "#2563eb", "#4f46e5", "#0d9488", "#16a34a", "#f97316", "#be123c", "#64748b")

_RE_ID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_RE_COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")


# ── pulizia del disegno che arriva dal browser ─────────────────────────────

def _int(v, minimo: int, massimo: int, default: int) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(minimo, min(massimo, n))


def _id_pos(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 2_000_000_000 else None


def _testo(v, lung: int) -> str:
    return " ".join(str(v or "").split())[:lung]


def foglio_default() -> dict:
    return {"stile": "hub", "titolo": "", "sottotitolo": "", "intestazione": "", "azienda": "",
            "piede": "", "logo": True, "ruoli_blu": True}


def vuoto() -> dict:
    return {"v": VERSIONE, "nodi": [], "foglio": foglio_default()}


def _lista_id(v, massimo: int) -> list[int]:
    out: list[int] = []
    for x in v if isinstance(v, list) else []:
        i = _id_pos(x)
        if i and i not in out:
            out.append(i)
        if len(out) >= massimo:
            break
    return out


def normalizza_foglio(raw) -> dict:
    """Impostazioni del foglio (stile, intestazione, piè di pagina) pulite."""
    raw = raw if isinstance(raw, dict) else {}
    f = foglio_default()
    f["stile"] = raw.get("stile") if raw.get("stile") in STILI_FOGLIO else "hub"
    for k, lung in (("titolo", 120), ("sottotitolo", 120), ("intestazione", 80), ("azienda", 80), ("piede", 160)):
        f[k] = _testo(raw.get(k), lung)
    f["logo"] = bool(raw.get("logo", True))
    f["ruoli_blu"] = bool(raw.get("ruoli_blu", True))
    return f


def normalizza(raw) -> dict:
    """Disegno pulito: campi noti, numeri nei limiti, riferimenti validi, niente cicli.

    Solleva ``ValueError`` se ``raw`` non ha nemmeno la forma di un disegno.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("nodi"), list):
        raise ValueError("Disegno non valido.")
    if len(raw["nodi"]) > MAX_NODI:
        raise ValueError(f"Troppi riquadri (massimo {MAX_NODI}).")
    nodi: list[dict] = []
    visti: set[str] = set()
    for n in raw["nodi"]:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        if not _RE_ID.match(nid) or nid in visti:
            continue
        visti.add(nid)
        tipo = "gruppo" if n.get("tipo") == "gruppo" else "box"
        colore = str(n.get("colore") or "")
        nodi.append({
            "id": nid,
            "tipo": tipo,
            "x": _int(n.get("x"), -5000, 20000, 0),
            "y": _int(n.get("y"), -5000, 20000, 0),
            "w": _int(n.get("w"), 80, 4000, 320 if tipo == "gruppo" else 220),
            "h": _int(n.get("h"), 36, 4000, 180 if tipo == "gruppo" else 60),
            "ruolo": _id_pos(n.get("ruolo")) if tipo == "box" else None,
            "persona": _id_pos(n.get("persona")) if tipo == "box" else None,
            "mansione": _id_pos(n.get("mansione")) if tipo == "box" else None,
            "titolo": _testo(n.get("titolo"), 120),
            "sotto": _testo(n.get("sotto"), 120) if tipo == "box" else "",
            "padre": str(n.get("padre") or "") or None,
            "staff": bool(n.get("staff")),
            "gruppo": str(n.get("gruppo") or "") or None,
            "colore": colore if _RE_COLORE.match(colore) else COLORE_DEFAULT,
            "stile": n.get("stile") if n.get("stile") in STILI else "bordo",
            "reparto": _testo(n.get("reparto"), 80) if tipo == "box" else "",
            "ruoli_extra": _lista_id(n.get("ruoli_extra"), 6) if tipo == "box" else [],
            "tutti_titolari": bool(n.get("tutti_titolari")) if tipo == "box" else False,
            "elenco_ruoli": _lista_id(n.get("elenco_ruoli"), MAX_LISTA_RUOLI) if tipo == "box" else [],
            "elenco_righe": [
                _testo(r, 120) for r in (n.get("elenco_righe") if isinstance(n.get("elenco_righe"), list) else [])
            ][:MAX_RIGHE] if tipo == "box" else [],
            "elenco_nascosti": _lista_id(n.get("elenco_nascosti"), 300) if tipo == "box" else [],
            "elenco_sigle": n.get("elenco_sigle") is not False,
            "icona": n.get("icona") if tipo == "box" and n.get("icona") in ICONE else "",
            "lato": bool(n.get("lato")),
            "tronco": n.get("tronco") if n.get("tronco") in TRONCHI else "centro",
        })
    per_id = {n["id"]: n for n in nodi}
    for n in nodi:
        if n["padre"] not in per_id or n["padre"] == n["id"]:
            n["padre"] = None
        g = per_id.get(n["gruppo"] or "")
        if n["tipo"] == "gruppo" or g is None or g["tipo"] != "gruppo":
            n["gruppo"] = None
        if not n["padre"]:
            n["staff"] = n["lato"] = False
        if n["staff"]:
            n["lato"] = False
        if n["ruolo"] in n["ruoli_extra"]:
            n["ruoli_extra"].remove(n["ruolo"])
    # Cicli nei collegamenti: si spezza il collegamento che chiude il giro.
    for n in nodi:
        visitati = {n["id"]}
        cur = per_id.get(n["padre"] or "")
        while cur is not None:
            if cur["id"] in visitati:
                n["padre"], n["staff"], n["lato"] = None, False, False
                break
            visitati.add(cur["id"])
            cur = per_id.get(cur["padre"] or "")
    return {"v": VERSIONE, "nodi": nodi, "foglio": normalizza_foglio(raw.get("foglio"))}


# ── nomi, foto e dati del portale letti dal disegno ────────────────────────

def _persone_info(ids: set[int]) -> dict[int, dict]:
    from .organigramma_albero import _ids_con_foto, _nome_map

    if not ids:
        return {}
    nomi = _nome_map(ids)
    foto = _ids_con_foto(ids)
    return {
        lid: {"nome": nomi.get(lid, ""), "foto": (
            reverse("anagrafica:foto_dipendente", args=[lid]) + f"?m={foto[lid]}" if lid in foto else "")}
        for lid in ids
    }


def _cessazioni(ids: set[int]) -> dict[int, date]:
    from anagrafica.models import DipendenteAnagraficaAziendale

    if not ids:
        return {}
    return {
        int(lid): d
        for lid, d in DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id__in=sorted(ids), data_cessazione__isnull=False,
        ).values_list("legacy_anagrafica_id", "data_cessazione")
    }


def contesto(*disegni: dict) -> dict:
    """Tutto quello che serve per etichette e avvisi dei disegni dati, in poche letture."""
    from anagrafica.models import Mansione, RuoloOperativo
    from core.operational_roles import _assegnazioni_in_corso

    ruoli_ids, persone_ids, mansioni_ids = set(), set(), set()
    for d in disegni:
        for n in (d or {}).get("nodi", []):
            if n.get("ruolo"):
                ruoli_ids.add(n["ruolo"])
            ruoli_ids.update(n.get("ruoli_extra") or [])
            ruoli_ids.update(n.get("elenco_ruoli") or [])
            if n.get("persona"):
                persone_ids.add(n["persona"])
            if n.get("mansione"):
                mansioni_ids.add(n["mansione"])
    ruoli = {r.pk: r for r in RuoloOperativo.objects.filter(pk__in=ruoli_ids)} if ruoli_ids else {}
    mansioni = {m.pk: m for m in Mansione.objects.filter(pk__in=mansioni_ids)} if mansioni_ids else {}
    titolari: set[tuple[int, int]] = set()
    if persone_ids:
        titolari = {
            (int(r), int(p)) for r, p in _assegnazioni_in_corso()
            .filter(legacy_anagrafica_id__in=sorted(persone_ids))
            .values_list("ruolo_id", "legacy_anagrafica_id")
        }
    # Quante persone in forza ricoprono i ruoli disegnati senza una persona.
    n_titolari: dict[int, int] = {}
    if ruoli_ids:
        from .organigramma_albero import cessati_legacy_ids

        cessati = cessati_legacy_ids()
        for rid, lid in _assegnazioni_in_corso().filter(ruolo_id__in=sorted(ruoli_ids)).values_list(
                "ruolo_id", "legacy_anagrafica_id"):
            if lid and int(lid) not in cessati:
                n_titolari[rid] = n_titolari.get(rid, 0) + 1
    return {
        "ruoli": ruoli, "mansioni": mansioni, "persone": _persone_info(persone_ids),
        "cessati": _cessazioni(persone_ids), "titolari": titolari, "n_titolari": n_titolari,
    }


def nomi_per_tela(ctx: dict) -> dict:
    """Nomi di persone, ruoli e mansioni del disegno anche se non sono più nei cataloghi della barra."""
    return {
        "persone": {str(k): v for k, v in ctx["persone"].items()},
        "ruoli": {str(k): r.nome for k, r in ctx["ruoli"].items()},
        "mansioni": {str(k): m.nome for k, m in ctx["mansioni"].items()},
    }


def etichetta(nodo: dict, ctx: dict) -> dict:
    """Titolo, sottotitolo, iniziale e foto di un riquadro, come li disegna la tela."""
    if nodo.get("tipo") == "gruppo":
        return {"titolo": nodo.get("titolo") or "Gruppo", "sotto": "", "iniziale": "", "foto": ""}
    ruolo = ctx["ruoli"].get(nodo.get("ruolo") or 0)
    mansione = ctx["mansioni"].get(nodo.get("mansione") or 0)
    persona = ctx["persone"].get(nodo.get("persona") or 0)
    nome_ruolo = ruolo.nome if ruolo else ""
    nome_mansione = mansione.nome if mansione else ""
    nome_persona = (persona or {}).get("nome") or (f"Persona n. {nodo['persona']}" if nodo.get("persona") else "")
    if nome_persona:
        titolo, sotto = nome_persona, nome_ruolo or nome_mansione
    elif nome_ruolo:
        n = ctx.get("n_titolari", {}).get(ruolo.pk, 0)
        titolo = nome_ruolo
        sotto = nome_mansione or (("1 persona" if n == 1 else f"{n} persone") if n else "Posizione scoperta")
    elif nome_mansione:
        titolo, sotto = nome_mansione, "Mansione"
    else:
        titolo, sotto = "", ""
    titolo = nodo.get("titolo") or titolo or "Riquadro"
    sotto = nodo.get("sotto") or sotto
    return {
        "titolo": titolo, "sotto": sotto,
        "iniziale": (titolo[:1] or "?").upper(), "foto": (persona or {}).get("foto", ""),
    }


def avvisi(dati: dict, ctx: dict, organigramma=None) -> list[dict]:
    """Dove il disegno non corrisponde più ai dati del portale. Non corregge niente."""
    out: list[dict] = []
    for n in dati.get("nodi", []):
        if n["tipo"] != "box":
            continue
        pid, rid, mid = n.get("persona"), n.get("ruolo"), n.get("mansione")
        nome = (ctx["persone"].get(pid) or {}).get("nome") or (f"Persona n. {pid}" if pid else "")
        if pid and pid in ctx["cessati"]:
            out.append({"nodo": n["id"], "testo": f"{nome}: cessato il {ctx['cessati'][pid]:%d/%m/%Y}"})
        elif pid and not (ctx["persone"].get(pid) or {}).get("nome"):
            out.append({"nodo": n["id"], "testo": f"{nome}: non più in anagrafica"})
        ruolo = ctx["ruoli"].get(rid or 0)
        if rid and ruolo is None:
            out.append({"nodo": n["id"], "testo": f"Ruolo n. {rid} eliminato dal catalogo"})
        elif ruolo is not None and not ruolo.is_active:
            out.append({"nodo": n["id"], "testo": f"Ruolo «{ruolo.nome}» disattivato nel catalogo"})
        elif ruolo is not None and pid and pid not in ctx["cessati"] and (rid, pid) not in ctx["titolari"]:
            out.append({"nodo": n["id"], "testo": f"{nome} non ha il ruolo «{ruolo.nome}» nella scheda"})
        for altro in list(n.get("ruoli_extra") or []) + list(n.get("elenco_ruoli") or []):
            r = ctx["ruoli"].get(altro)
            if r is None:
                out.append({"nodo": n["id"], "testo": f"Ruolo n. {altro} eliminato dal catalogo"})
            elif not r.is_active:
                out.append({"nodo": n["id"], "testo": f"Ruolo «{r.nome}» disattivato nel catalogo"})
        mansione = ctx["mansioni"].get(mid or 0)
        if mid and mansione is None:
            out.append({"nodo": n["id"], "testo": f"Mansione n. {mid} eliminata"})
        elif mansione is not None and not mansione.is_active:
            out.append({"nodo": n["id"], "testo": f"Mansione «{mansione.nome}» disattivata"})
    ambito = getattr(organigramma, "ambito", None)
    if ambito is not None:
        out.extend(_ruoli_non_disegnati(dati, ambito))
    return out


def _ruoli_non_disegnati(dati: dict, ambito) -> list[dict]:
    from django.db.models import Q

    from anagrafica.models import RuoloOperativo
    from core.operational_roles import _assegnazioni_in_corso
    from .organigramma_albero import cessati_legacy_ids

    disegnati: set[int] = set()
    for n in dati.get("nodi", []):
        if n.get("ruolo"):
            disegnati.add(n["ruolo"])
        disegnati.update(n.get("ruoli_extra") or [])
        disegnati.update(n.get("elenco_ruoli") or [])
    filtro = Q(ambito_id=ambito.pk) | Q(ambito_id=None) if ambito.alimenta_scheda else Q(ambito_id=ambito.pk)
    ruoli = {r.pk: r.nome for r in RuoloOperativo.objects.filter(filtro, is_active=True)}
    cessati = cessati_legacy_ids()
    conteggio: dict[int, int] = {}
    for rid, lid in _assegnazioni_in_corso().filter(ruolo_id__in=list(ruoli)).values_list(
            "ruolo_id", "legacy_anagrafica_id"):
        if int(lid or 0) not in cessati:
            conteggio[rid] = conteggio.get(rid, 0) + 1
    mancanti = sorted((nome, rid) for rid, nome in ruoli.items() if rid not in disegnati and conteggio.get(rid))
    out = []
    for nome, rid in mancanti[:30]:
        n = conteggio[rid]
        out.append({"nodo": None, "testo": f"«{nome}» non è nel disegno ({n} {'persona' if n == 1 else 'persone'})"})
    if len(mancanti) > 30:
        out.append({"nodo": None, "testo": f"… e altri {len(mancanti) - 30} ruoli dell'ambito non disegnati"})
    return out


# ── riepilogo delle modifiche fra la revisione in vigore e la bozza ────────

_CONTENUTO = ("ruolo", "persona", "mansione", "titolo", "sotto", "reparto", "ruoli_extra", "tutti_titolari",
              "elenco_ruoli", "elenco_righe", "elenco_nascosti", "elenco_sigle")
_GRAFICA = ("x", "y", "w", "h", "lato", "tronco")
_ASPETTO = ("colore", "stile", "icona")
_NOMI_FOGLIO = {"stile": "stile", "titolo": "titolo", "sottotitolo": "sottotitolo", "intestazione": "intestazione",
                "azienda": "azienda", "piede": "piè di pagina", "logo": "logo", "ruoli_blu": "colore dei ruoli"}


def riepilogo(prima: dict | None, dopo: dict | None) -> list[dict]:
    """Elenco leggibile delle modifiche: aggiunto, tolto, spostato, rinominato, modificato, solo grafica."""
    prima = prima or vuoto()
    dopo = dopo or vuoto()
    ctx = contesto(prima, dopo)
    p = {n["id"]: n for n in prima.get("nodi", [])}
    d = {n["id"]: n for n in dopo.get("nodi", [])}

    def nome(nodo: dict | None) -> str:
        if not nodo:
            return "nessuno"
        e = etichetta(nodo, ctx)
        if nodo["tipo"] == "gruppo":
            return f"gruppo «{e['titolo']}»"
        testo = f"{e['titolo']} ({e['sotto']})" if e["sotto"] else e["titolo"]
        return f"{nodo['reparto']}: {testo}" if nodo.get("reparto") else testo

    def dove(nodo: dict, tutti: dict) -> str:
        parti = []
        if nodo.get("padre"):
            parti.append(("staff di " if nodo.get("staff") else "sotto ") + nome(tutti.get(nodo["padre"])))
        if nodo.get("gruppo"):
            parti.append("nel " + nome(tutti.get(nodo["gruppo"])))
        return ", ".join(parti)

    out: list[dict] = []
    for nid, n in d.items():
        if nid not in p:
            titolo = nome(n)
            out.append({"tipo": "aggiunto", "titolo": titolo[:1].upper() + titolo[1:], "dettaglio": dove(n, d)})
    for nid, n in p.items():
        if nid not in d:
            titolo = nome(n)
            dett = dove(n, p)
            out.append({"tipo": "tolto", "titolo": titolo[:1].upper() + titolo[1:],
                        "dettaglio": f"era {dett}" if dett else ""})
    grafica = aspetto = 0
    for nid, n in d.items():
        v = p.get(nid)
        if v is None:
            continue
        if any(v.get(k) != n.get(k) for k in _CONTENUTO):
            if n["tipo"] == "gruppo":
                out.append({"tipo": "rinominato", "titolo": f"«{v.get('titolo') or 'Gruppo'}» → «{n.get('titolo') or 'Gruppo'}»",
                            "dettaglio": "gruppo"})
            else:
                out.append({"tipo": "modificato", "titolo": nome(n), "dettaglio": f"prima: {nome(v)}"})
        spostamenti = []
        if (v.get("padre"), v.get("staff")) != (n.get("padre"), n.get("staff")):
            da = ("staff di " if v.get("staff") else "sotto ") + nome(p.get(v["padre"])) if v.get("padre") else "nessun collegamento"
            a = ("staff di " if n.get("staff") else "sotto ") + nome(d.get(n["padre"])) if n.get("padre") else "nessun collegamento"
            spostamenti.append(f"da {da} → {a}")
        if v.get("gruppo") != n.get("gruppo"):
            da = "nel " + nome(p.get(v["gruppo"])) if v.get("gruppo") else "fuori dai gruppi"
            a = "nel " + nome(d.get(n["gruppo"])) if n.get("gruppo") else "fuori dai gruppi"
            spostamenti.append(f"da {da} → {a}")
        if spostamenti:
            titolo = nome(n)
            out.append({"tipo": "spostato", "titolo": titolo[:1].upper() + titolo[1:], "dettaglio": "; ".join(spostamenti)})
        elif any(v.get(k) != n.get(k) for k in _GRAFICA):
            grafica += 1
        if any(v.get(k) != n.get(k) for k in _ASPETTO):
            aspetto += 1
    if grafica or aspetto:
        parti = []
        if grafica:
            parti.append(f"{grafica} {'riquadro riposizionato' if grafica == 1 else 'riquadri riposizionati'}")
        if aspetto:
            parti.append(f"{aspetto} {'colore o stile cambiato' if aspetto == 1 else 'colori o stili cambiati'}")
        out.append({"tipo": "grafica", "titolo": ", ".join(parti), "dettaglio": "non cambia la struttura"})
    fp, fd = normalizza_foglio(prima.get("foglio")), normalizza_foglio(dopo.get("foglio"))
    cambiati = [k for k in fd if fp[k] != fd[k]]
    if cambiati:
        dett = ("stile " + ("Documento" if fd["stile"] == "documento" else "HUB")) if "stile" in cambiati else ""
        out.append({"tipo": "grafica", "titolo": "Foglio: " + ", ".join(_NOMI_FOGLIO[k] for k in cambiati),
                    "dettaglio": dett or "intestazione e piè di pagina"})
    ordine = {"aggiunto": 0, "spostato": 1, "rinominato": 2, "modificato": 3, "tolto": 4, "grafica": 5}
    out.sort(key=lambda r: ordine[r["tipo"]])
    return out


# ── disegno pronto per la pagina pubblicata e per la stampa ────────────────
#
# Riquadri, elenchi e linee li disegna nel browser lo stesso script della tela
# (partial _org_uff_render.html): qui si prepara solo il catalogo dei nomi.

def catalogo(*disegni: dict) -> dict:
    """Nomi, sigle e titolari che servono per disegnare i riquadri dati, nel formato dello script."""
    from anagrafica.models import Mansione, RuoloOperativo
    from core.operational_roles import _assegnazioni_in_corso
    from .organigramma_albero import cessati_legacy_ids

    ruoli_ids, persone_ids, mansioni_ids, con_titolari = set(), set(), set(), set()
    for d in disegni:
        for n in (d or {}).get("nodi", []):
            if n.get("ruolo"):
                ruoli_ids.add(n["ruolo"])
                con_titolari.add(n["ruolo"])
            ruoli_ids.update(n.get("ruoli_extra") or [])
            for r in (n.get("elenco_ruoli") or []):
                ruoli_ids.add(r)
                con_titolari.add(r)
            if n.get("persona"):
                persone_ids.add(n["persona"])
            if n.get("mansione"):
                mansioni_ids.add(n["mansione"])
    titolari: dict[int, list[int]] = {}
    if con_titolari:
        cessati = cessati_legacy_ids()
        for rid, lid in _assegnazioni_in_corso().filter(ruolo_id__in=sorted(con_titolari)).values_list(
                "ruolo_id", "legacy_anagrafica_id"):
            if not lid or int(lid) in cessati:
                continue
            elenco = titolari.setdefault(rid, [])
            if int(lid) not in elenco:
                elenco.append(int(lid))
                persone_ids.add(int(lid))
    ruoli = {
        str(r.pk): {"nome": r.nome, "sigla": r.sigla or "", "attivo": r.is_active, "titolari": titolari.get(r.pk, [])}
        for r in RuoloOperativo.objects.filter(pk__in=ruoli_ids)
    } if ruoli_ids else {}
    mansioni = {str(m.pk): m.nome for m in Mansione.objects.filter(pk__in=mansioni_ids)} if mansioni_ids else {}
    return {
        "ruoli": ruoli, "mansioni": mansioni,
        "persone": {str(k): v for k, v in _persone_info(persone_ids).items()},
    }


def pacchetto(dati: dict | None) -> dict:
    """Quello che riceve lo script di disegno: disegno pulito più catalogo dei nomi."""
    dati = normalizza(dati) if dati else vuoto()
    return {"dati": dati, "cat": catalogo(dati)}


def testo_piede(foglio: dict | None, rev_numero: int | None, nome: str) -> str:
    """Piè di pagina della stampa: «{rev}» nel testo diventa «Rev.N» (o «Bozza»)."""
    rev = f"Rev.{rev_numero}" if rev_numero else "Bozza"
    piede = (foglio or {}).get("piede") or ""
    if not piede:
        return f"{nome} – {rev}"
    return piede.replace("{rev}", rev) if "{rev}" in piede else f"{piede} – {rev}"


# ── cataloghi per la barra della tela ──────────────────────────────────────

def cataloghi(ambito=None) -> dict:
    """Ruoli (con i titolari), persone in forza e mansioni da trascinare sulla tela."""
    from django.db.models import Q

    from anagrafica.models import Mansione, RuoloOperativo
    from core.operational_roles import _assegnazioni_in_corso
    from .organigramma_albero import _ids_con_foto, cessati_legacy_ids

    persone: list[dict] = []
    try:
        from core.persone_tendine import anagrafica_in_forza

        for r in anagrafica_in_forza().values("id", "nome", "cognome"):
            persone.append({"id": int(r["id"]), "nome": naming.nome_completo(r["nome"], r["cognome"])})
    except Exception:  # tabella legacy assente (sviluppo/test): la barra resta senza persone
        persone = []
    foto = _ids_con_foto([p["id"] for p in persone])
    for p in persone:
        p["foto"] = (reverse("anagrafica:foto_dipendente", args=[p["id"]]) + f"?m={foto[p['id']]}"
                     if p["id"] in foto else "")
    nomi = {p["id"]: p["nome"] for p in persone}

    qs = RuoloOperativo.objects.filter(is_active=True)
    cessati = cessati_legacy_ids()
    titolari: dict[int, list[int]] = {}
    for rid, lid in _assegnazioni_in_corso().values_list("ruolo_id", "legacy_anagrafica_id"):
        if lid and int(lid) not in cessati:
            titolari.setdefault(rid, []).append(int(lid))
    ambito_ids: set[int] = set()
    if ambito is not None:
        filtro = Q(ambito_id=ambito.pk) | Q(ambito_id=None) if ambito.alimenta_scheda else Q(ambito_id=ambito.pk)
        ambito_ids = set(qs.filter(filtro).values_list("pk", flat=True))
    ruoli = [
        {"id": r.pk, "nome": r.nome, "sigla": r.sigla or "", "ambito": r.pk in ambito_ids,
         "titolari": [{"id": lid, "nome": nomi.get(lid, "")} for lid in titolari.get(r.pk, [])]}
        for r in qs.order_by("nome")
    ]
    ruoli_di: dict[int, list[int]] = {}
    for r in ruoli:
        for t in r["titolari"]:
            ruoli_di.setdefault(t["id"], []).append(r["id"])
    for p in persone:
        p["ruoli"] = ruoli_di.get(p["id"], [])
    mansioni = [{"id": m.pk, "nome": m.nome} for m in Mansione.objects.filter(is_active=True).order_by("nome")]
    return {"ruoli": ruoli, "persone": persone, "mansioni": mansioni}


# ── pubblicazione ──────────────────────────────────────────────────────────

def ultimo_disegno(org) -> dict:
    rev = org.revisione_in_vigore()
    return rev.dati if rev else vuoto()


def salva_bozza(org, dati: dict, user) -> None:
    org.bozza = normalizza(dati)
    org.bozza_aggiornata_il = timezone.now()
    org.bozza_aggiornata_da = user if getattr(user, "is_authenticated", False) else None
    org.save(update_fields=["bozza", "bozza_aggiornata_il", "bozza_aggiornata_da"])


@transaction.atomic
def pubblica(org, *, nota: str, approvato_da: str, data_emissione: date, user, dati: dict | None = None):
    """La bozza (o il disegno firmato in ``dati``) diventa la revisione successiva; la bozza si chiude."""
    from anagrafica.models import OrganigrammaRevisione, OrganigrammaUfficiale

    org = OrganigrammaUfficiale.objects.select_for_update().get(pk=org.pk)
    if dati is None and org.bozza is None:
        raise ValueError("Non c'è una bozza da pubblicare.")
    dati = normalizza(dati if dati is not None else org.bozza)
    if not dati["nodi"]:
        raise ValueError("Il disegno è vuoto: aggiungi almeno un riquadro prima di pubblicare.")
    ultima = org.revisioni.order_by("-numero").values_list("numero", flat=True).first() or 0
    rev = OrganigrammaRevisione.objects.create(
        organigramma=org, numero=ultima + 1, dati=dati, nota=_testo(nota, 2000),
        approvato_da=_testo(approvato_da, 200), data_emissione=data_emissione,
        pubblicata_da=user if getattr(user, "is_authenticated", False) else None,
    )
    org.bozza = None
    org.bozza_aggiornata_il = None
    org.bozza_aggiornata_da = None
    org.save(update_fields=["bozza", "bozza_aggiornata_il", "bozza_aggiornata_da"])
    return rev
