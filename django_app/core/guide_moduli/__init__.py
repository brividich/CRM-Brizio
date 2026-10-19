"""Centro guide: una guida per ogni modulo, divisa per chi la legge.

Ogni modulo ha un file in ``core/guide_moduli/contenuti/`` con un dizionario
``GUIDA``:

- ``slug``, ``titolo``, ``area``, ``sintesi``: identità e riga dell'indice;
- ``url``: nome della rotta che apre il modulo («Apri il modulo»);
- ``prefissi``: inizio degli indirizzi del modulo, per il pulsante «?» della
  barra in alto (il prefisso più lungo vince);
- ``dettaglio``: guide di dettaglio già presenti nel modulo, come lista di
  ``(etichetta, nome_rotta, query)``;
- ``uso``: capitoli per chi usa il modulo tutti i giorni;
- ``admin``: capitoli per chi lo configura (amministratori);
- ``problemi``: sintomo → perché succede → cosa fare, per l'amministratore
  che deve risolvere un problema da solo;
- ``solo_admin``: la guida intera è per amministratori (es. il manuale di
  emergenza): chi non lo è non la vede nell'indice e riceve 403.

I capitoli hanno la forma delle altre guide del portale (``timbri/guida.py``,
``core/guida_pdf.py``): ``{"id", "titolo", "blocchi"}`` con blocchi ``("p",
testo)``, ``("passi", [voci])`` numerati, ``("ul", [voci])``, ``("nota",
testo)`` e ``("def", [(termine, spiegazione)])``. Testo semplice, niente HTML.
Le etichette citate sono quelle dei pulsanti veri: se ne cambia una, va
aggiornata anche qui.
"""
from __future__ import annotations

import importlib
from functools import lru_cache

# Ordine dell'indice: per area, poi come compaiono nel menu.
_MODULI = (
    "home",
    "anagrafica",
    "assenze",
    "timbri",
    "notizie",
    "tickets",
    "tasks",
    "anomalie",
    "assets",
    "attrezzature",
    "carichi_macchina",
    "contatori",
    "fornitori",
    "checklist_operativa",
    "dpi",
    "diario_preposto",
    "rilevazione_incidenti",
    "schede_sicurezza",
    "procedure_refresh",
    "rentri",
    "sistema_gestione",
    "gestione_specifiche",
    "report_conformita",
    "suggestion_corner",
    "glossario",
    "security",
    "ai_assistant",
    "automazioni",
    "amministrazione",
    "dati_bi",
    "emergenza",
)

AREE = (
    "Per tutti",
    "Persone e HR",
    "Produzione e operations",
    "Sicurezza sul lavoro",
    "Qualità e sistema di gestione",
    "IT e sicurezza informatica",
    "Amministrazione del portale",
)

VISTE = (
    ("uso", "Come si usa"),
    ("admin", "Amministratore e configurazione"),
    ("problemi", "Se qualcosa non va"),
)

# Capitolo finale di ogni guida d'uso: uguale per tutti i moduli.
CAPITOLO_AIUTO = {
    "id": "aiuto",
    "titolo": "Se qualcosa non funziona",
    "blocchi": [
        ("passi", [
            "Ricarica la pagina (tasto F5). Molti problemi spariscono così.",
            "Se compare «Accesso negato», non hai il permesso per quella pagina: chiedilo al tuo responsabile "
            "o all'amministratore del portale, indicando il nome della pagina.",
            "Se un pulsante non fa nulla o vedi un errore, clicca sul tuo nome in alto a destra e scegli "
            "«Segnala un problema». Scrivi cosa stavi facendo: la pagina viene allegata da sola.",
            "Per una domanda veloce («come si fa…?») apri l'Assistente AI con l'icona a forma di stella in alto "
            "o con i tasti Alt+A.",
        ]),
        ("nota", "Non mandare password, codici o dati sanitari nelle segnalazioni o all'assistente."),
    ],
}


def _carica(nome: str) -> dict:
    modulo = importlib.import_module(f"{__name__}.contenuti.{nome}")
    guida = dict(modulo.GUIDA)
    guida.setdefault("prefissi", ())
    guida.setdefault("dettaglio", [])
    guida.setdefault("admin", [])
    guida.setdefault("problemi", [])
    guida.setdefault("solo_admin", False)
    return guida


@lru_cache(maxsize=1)
def tutte() -> tuple[dict, ...]:
    return tuple(_carica(nome) for nome in _MODULI)


def per_slug(slug: str) -> dict | None:
    for guida in tutte():
        if guida["slug"] == slug:
            return guida
    return None


def per_path(path: str) -> dict | None:
    """La guida del modulo a cui appartiene l'indirizzo (prefisso più lungo)."""
    path = path or "/"
    migliore, lunghezza = None, 0
    for guida in tutte():
        for prefisso in guida["prefissi"]:
            if path.startswith(prefisso) and len(prefisso) > lunghezza:
                migliore, lunghezza = guida, len(prefisso)
    return migliore


def per_area() -> list[tuple[str, list[dict]]]:
    gruppi = {area: [] for area in AREE}
    for guida in tutte():
        gruppi.setdefault(guida["area"], []).append(guida)
    return [(area, elenco) for area, elenco in gruppi.items() if elenco]


def capitoli_uso(guida: dict) -> list[dict]:
    if guida["solo_admin"]:
        return list(guida["uso"])
    return list(guida["uso"]) + [CAPITOLO_AIUTO]


def capitoli_problemi(guida: dict) -> list[dict]:
    """I problemi come capitoli, per pagina, PDF e assistente AI."""
    capitoli = []
    for i, problema in enumerate(guida["problemi"], 1):
        blocchi = []
        if problema.get("perche"):
            blocchi.append(("p", "Perché succede: " + problema["perche"]))
        blocchi.append(("passi", list(problema["fare"])))
        if problema.get("nota"):
            blocchi.append(("nota", problema["nota"]))
        capitoli.append({"id": f"problema-{i}", "titolo": problema["sintomo"], "blocchi": blocchi})
    return capitoli


def capitoli(guida: dict, vista: str) -> list[dict]:
    if vista == "admin":
        return list(guida["admin"])
    if vista == "problemi":
        return capitoli_problemi(guida)
    return capitoli_uso(guida)


def puo_vedere_admin(request) -> bool:
    """Le parti per amministratori: superuser o amministratori del portale."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    from core.legacy_utils import get_legacy_user, is_legacy_admin

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    return is_legacy_admin(legacy_user)
