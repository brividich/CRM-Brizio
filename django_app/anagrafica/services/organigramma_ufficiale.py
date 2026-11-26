"""Organigramma ufficiale: disegno a mano, avvisi, riepilogo delle modifiche, pubblicazione.

Il disegno è un dizionario JSON::

    {"v": 1, "nodi": [
        {"id": "n1", "tipo": "box" | "gruppo", "x": 0, "y": 0, "w": 220, "h": 60,
         "ruolo": 3 | None, "persona": 41 | None, "mansione": 7 | None,
         "titolo": "", "sotto": "",          # testo libero (o sostituisce quello calcolato)
         "padre": "n0" | None, "staff": False, # collegamento verso il riquadro superiore
         "gruppo": "g1" | None,                # gruppo che contiene il riquadro
         "colore": "#0f2a5c", "stile": "pieno" | "bordo" | "tratteggio"},
    ]}

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


def vuoto() -> dict:
    return {"v": VERSIONE, "nodi": []}


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
        })
    per_id = {n["id"]: n for n in nodi}
    for n in nodi:
        if n["padre"] not in per_id or n["padre"] == n["id"]:
            n["padre"] = None
        g = per_id.get(n["gruppo"] or "")
        if n["tipo"] == "gruppo" or g is None or g["tipo"] != "gruppo":
            n["gruppo"] = None
        if not n["padre"]:
            n["staff"] = False
    # Cicli nei collegamenti: si spezza il collegamento che chiude il giro.
    for n in nodi:
        visitati = {n["id"]}
        cur = per_id.get(n["padre"] or "")
        while cur is not None:
            if cur["id"] in visitati:
                n["padre"], n["staff"] = None, False
                break
            visitati.add(cur["id"])
            cur = per_id.get(cur["padre"] or "")
    return {"v": VERSIONE, "nodi": nodi}


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

    disegnati = {n.get("ruolo") for n in dati.get("nodi", []) if n.get("ruolo")}
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

_CONTENUTO = ("ruolo", "persona", "mansione", "titolo", "sotto")
_GRAFICA = ("x", "y", "w", "h")
_ASPETTO = ("colore", "stile")


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
        return f"{e['titolo']} ({e['sotto']})" if e["sotto"] else e["titolo"]

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
    ordine = {"aggiunto": 0, "spostato": 1, "rinominato": 2, "modificato": 3, "tolto": 4, "grafica": 5}
    out.sort(key=lambda r: ordine[r["tipo"]])
    return out


# ── disegno pronto per la pagina pubblicata e per la stampa ────────────────

def _linea(padre: dict, figlio: dict) -> dict:
    if figlio.get("staff"):
        y = figlio["y"] + figlio["h"] / 2
        destra = figlio["x"] + figlio["w"] / 2 >= padre["x"] + padre["w"] / 2
        x2 = figlio["x"] if destra else figlio["x"] + figlio["w"]
        if padre["y"] <= y <= padre["y"] + padre["h"]:
            x1 = padre["x"] + padre["w"] if destra else padre["x"]
            return {"d": f"M{x1:.0f} {y:.0f} H{x2:.0f}", "staff": True}
        x1 = padre["x"] + padre["w"] / 2
        y1 = padre["y"] + padre["h"] if y > padre["y"] else padre["y"]
        return {"d": f"M{x1:.0f} {y1:.0f} V{y:.0f} H{x2:.0f}", "staff": True}
    x1, y1 = padre["x"] + padre["w"] / 2, padre["y"] + padre["h"]
    x2, y2 = figlio["x"] + figlio["w"] / 2, figlio["y"]
    m = (y1 + y2) / 2 if y2 > y1 else y1 + 14
    return {"d": f"M{x1:.0f} {y1:.0f} V{m:.0f} H{x2:.0f} V{y2:.0f}", "staff": False}


def disegno(dati: dict | None, ctx: dict | None = None, margine: int = 24) -> dict:
    """Riquadri con etichette e linee, spostati in modo che il disegno parta da (margine, margine)."""
    dati = dati or vuoto()
    nodi = [dict(n) for n in dati.get("nodi", [])]
    if not nodi:
        return {"nodi": [], "linee": [], "w": 0, "h": 0}
    ctx = ctx if ctx is not None else contesto(dati)
    minx = min(n["x"] for n in nodi)
    miny = min(n["y"] for n in nodi)
    for n in nodi:
        n["x"] += margine - minx
        n["y"] += margine - miny
        n["e"] = etichetta(n, ctx)
    per_id = {n["id"]: n for n in nodi}
    linee = [_linea(per_id[n["padre"]], n) for n in nodi if n.get("padre") in per_id]
    w = max(n["x"] + n["w"] for n in nodi) + margine
    h = max(n["y"] + n["h"] for n in nodi) + margine
    # I gruppi sotto, i riquadri sopra: l'ordine di disegno è quello della pagina.
    nodi.sort(key=lambda n: 0 if n["tipo"] == "gruppo" else 1)
    return {"nodi": nodi, "linee": linee, "w": w, "h": h}


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
        {"id": r.pk, "nome": r.nome, "ambito": r.pk in ambito_ids,
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
def pubblica(org, *, nota: str, approvato_da: str, data_emissione: date, user):
    """La bozza diventa la revisione successiva; la bozza si chiude."""
    from anagrafica.models import OrganigrammaRevisione, OrganigrammaUfficiale

    org = OrganigrammaUfficiale.objects.select_for_update().get(pk=org.pk)
    if org.bozza is None:
        raise ValueError("Non c'è una bozza da pubblicare.")
    dati = normalizza(org.bozza)
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
