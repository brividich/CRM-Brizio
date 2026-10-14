"""Organizzazione della sicurezza per la home (stanza «Persone & sicurezza»).

Le figure non si caricano a mano: sono i ruoli dell'ambito «Sicurezza ISO
45001» del catalogo ruoli in anagrafica (``AmbitoRuolo`` → ``RuoloOperativo``)
con i dipendenti che li ricoprono (``DipendenteRuoloOperativo``). Gli ex
dipendenti non compaiono, come nell'organigramma.

Si mostrano solo nome, ruolo, reparto ed email aziendale: le stesse
informazioni che il D.Lgs. 81/08 chiede di far conoscere ai lavoratori.
Nessun dato sanitario o HR.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# (parola chiave nel nome del ruolo, ordine, gruppo). La prima che combacia vince.
_FIGURE_NOTE: tuple[tuple[str, int, str], ...] = (
    ("datore", 10, "linea"),
    ("dirigent", 20, "linea"),
    ("aspp", 40, "servizio"),
    ("addetto servizio prevenzione", 40, "servizio"),
    ("rspp", 30, "servizio"),
    ("responsabile servizio prevenzione", 30, "servizio"),
    ("medico", 50, "servizio"),
    ("rls", 60, "rappresentanza"),
    ("rappresentante dei lavoratori", 60, "rappresentanza"),
    ("prepost", 70, "linea"),
    ("coordinat", 80, "emergenza"),
    ("emergenz", 85, "emergenza"),
    ("evacuazion", 86, "emergenza"),
    ("primo soccorso", 90, "emergenza"),
    ("antincendio", 95, "emergenza"),
)


def _norm(testo) -> str:
    return re.sub(r"\s+", " ", str(testo or "").strip().lower())


def _classifica(nome_ruolo: str) -> tuple[int, str]:
    nome = _norm(nome_ruolo)
    for chiave, ordine, gruppo in _FIGURE_NOTE:
        if chiave in nome:
            return ordine, gruppo
    return 200, "altro"


def _iniziali(nome: str) -> str:
    parole = [p for p in str(nome or "").split() if p[:1].isalpha()]
    return "".join(p[0] for p in parole[:2]).upper() or "?"


def ambito_sicurezza():
    """L'ambito «sicurezza sul lavoro» del catalogo ruoli, o ``None`` se non c'è."""
    from anagrafica.models import AmbitoRuolo

    qs = AmbitoRuolo.objects.filter(is_active=True).order_by("ordine", "nome")
    for ambito in qs:
        nome = _norm(ambito.nome)
        if "45001" in nome or ("sicurezza" in nome and "informazion" not in nome):
            return ambito
    return None


def _reparto_utente(legacy_user) -> str:
    """Reparto dell'utente collegato, dalla sua anagrafica (ponte ``utente_id``)."""
    if not legacy_user:
        return ""
    try:
        from core.legacy_models import AnagraficaDipendente

        row = AnagraficaDipendente.objects.filter(utente_id=int(legacy_user.id)).values("reparto").first()
        return str((row or {}).get("reparto") or "").strip()
    except Exception:
        logger.exception("Home: reparto dell'utente non letto")
        return ""


def build_sicurezza(legacy_user) -> dict:
    """Figure della sicurezza per la home.

    Ritorna ``{"ambito", "figure", "persone", "mie", "emergenza", "reparto"}``:

    - ``figure``: un elemento per ruolo, con ``persone`` (anche vuota: la
      posizione scoperta si vede), ordinati come una catena della sicurezza;
    - ``persone``: una scheda per coppia persona-ruolo, per la griglia;
    - ``mie``: le persone di riferimento dell'utente (il suo preposto per primo);
    - ``emergenza``: chi coordina le emergenze.
    """
    vuoto = {"ambito": None, "figure": [], "persone": [], "mie": [], "emergenza": [], "reparto": ""}
    ambito = ambito_sicurezza()
    if ambito is None:
        return vuoto

    from anagrafica.models import DipendenteRuoloOperativo, RuoloOperativo
    from anagrafica.services.organigramma_albero import cessati_legacy_ids
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    ruoli = list(RuoloOperativo.objects.filter(is_active=True, ambito=ambito))
    if not ruoli:
        return {**vuoto, "ambito": ambito}

    cessati = cessati_legacy_ids()
    titolari: dict[int, list[int]] = {r.id: [] for r in ruoli}
    for ruolo_id, lid in DipendenteRuoloOperativo.objects.filter(ruolo__in=ruoli).values_list(
        "ruolo_id", "legacy_anagrafica_id"
    ):
        if lid and int(lid) not in cessati:
            titolari[ruolo_id].append(int(lid))

    tutti = sorted({lid for ids in titolari.values() for lid in ids})
    righe = {}
    if tutti:
        try:
            righe = {int(r.get("id") or 0): r for r in fetch_anagrafica_rows(ids=tutti)}
        except Exception:
            logger.exception("Home: anagrafica delle figure della sicurezza non letta")

    reparto = _reparto_utente(legacy_user)
    reparto_n = _norm(reparto)

    figure: list[dict] = []
    for ruolo in ruoli:
        ordine, gruppo = _classifica(ruolo.nome)
        is_preposto = "prepost" in _norm(ruolo.nome)
        persone = []
        for lid in titolari[ruolo.id]:
            row = righe.get(lid)
            if row is not None and row.get("attivo") is False:
                continue
            nome = naming.nome_completo((row or {}).get("nome"), (row or {}).get("cognome")) if row else ""
            rep = str((row or {}).get("reparto") or "").strip()
            mio = bool(
                is_preposto and reparto_n
                and (_norm(rep) == reparto_n or reparto_n in _norm(ruolo.nome))
            )
            persone.append({
                "legacy_id": lid,
                "nome": nome or "—",
                "iniziali": _iniziali(nome),
                "email": str((row or {}).get("email_notifica") or "").strip(),
                "reparto": rep,
                "mio": mio,
            })
        persone.sort(key=lambda p: (not p["mio"], p["nome"]))
        figure.append({
            "id": ruolo.id,
            "nome": ruolo.nome,
            "descrizione": (ruolo.descrizione or "").strip(),
            "colore": ruolo.colore or "#64748b",
            "ordine": ordine,
            "gruppo": gruppo,
            "is_preposto": is_preposto,
            "persone": persone,
        })
    figure.sort(key=lambda f: (f["ordine"], f["nome"]))

    schede = [
        {**p, "ruolo": f["nome"], "colore": f["colore"], "gruppo": f["gruppo"], "is_preposto": f["is_preposto"]}
        for f in figure for p in f["persone"]
    ]
    schede.sort(key=lambda s: not s["mio"])

    # Persone di riferimento: il proprio preposto, poi una persona per ogni
    # figura di servizio e rappresentanza.
    mie = [s for s in schede if s["mio"]][:2]
    visti = {s["ruolo"] for s in mie}
    for f in figure:
        if f["gruppo"] in ("servizio", "rappresentanza") and f["persone"] and f["nome"] not in visti:
            mie.append({**f["persone"][0], "ruolo": f["nome"], "colore": f["colore"]})
            visti.add(f["nome"])

    emergenza = [
        {**p, "ruolo": f["nome"]}
        for f in figure if f["gruppo"] == "emergenza" and "coordinat" in _norm(f["nome"])
        for p in f["persone"]
    ]

    return {
        "ambito": ambito,
        "figure": figure,
        "persone": schede,
        "mie": mie[:6],
        "emergenza": emergenza[:3],
        "reparto": reparto,
    }
