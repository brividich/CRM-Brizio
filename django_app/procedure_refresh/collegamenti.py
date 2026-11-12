"""CN-SGI fase 2: le procedure collegate ai moduli dell'HUB.

- :data:`MODULI_HUB`: i moduli che possono «applicare» una procedura, con l'indirizzo
  da aprire e i prefissi delle loro pagine;
- :func:`proposte`: collegamenti suggeriti da parole chiave del codice e del titolo
  (deterministico, niente AI), da confermare a mano in «Collegamenti ai moduli»;
- :func:`procedure_della_pagina`: le procedure da mostrare sulla pagina di un modulo
  (cache breve, solo documenti aperti a tutti: quelli riservati restano nella libreria).
"""
from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

CACHE_KEY = "cnsgi_procedure_moduli_v1"
CACHE_SECONDI = 300
MAX_ETICHETTE = 3


@dataclass(frozen=True)
class ModuloHub:
    chiave: str
    nome: str
    href: str
    prefissi: tuple[str, ...]


MODULI_HUB: tuple[ModuloHub, ...] = (
    ModuloHub("anomalie", "Gestione anomalie", "/anomalie-menu", ("/anomalie", "/gestione-anomalie")),
    ModuloHub("registro_ofi", "Registro OFI", "/ofi-registro/", ("/ofi-registro/",)),
    ModuloHub("produzione", "Ordini di produzione", "/produzione/", ("/produzione/",)),
    ModuloHub("kickoff", "KICK-OFF commesse", "/tasks/projects/", ("/tasks/",)),
    ModuloHub("gestione_specifiche", "Gestione specifiche", "/gestione-specifiche/", ("/gestione-specifiche/",)),
    ModuloHub("fornitori", "Fornitori", "/fornitori/", ("/fornitori/",)),
    ModuloHub("attrezzature", "Attrezzature e tarature", "/attrezzature/", ("/attrezzature/",)),
    ModuloHub("assets", "Asset e manutenzione", "/assets/lista/", ("/assets/",)),
    ModuloHub("sistema_gestione", "Sistema di gestione e audit", "/sistema-gestione/", ("/sistema-gestione/",)),
    ModuloHub("dpi", "DPI", "/dpi/", ("/dpi/",)),
    ModuloHub("reception", "Reception", "/reception/", ("/reception/",)),
    ModuloHub("rilevazione_incidenti", "Rilevazione incidenti", "/rilevazione-incidenti/", ("/rilevazione-incidenti/",)),
    ModuloHub("diario_preposto", "Diario del preposto", "/diario-preposto/", ("/diario-preposto/",)),
    ModuloHub("schede_sicurezza", "Schede di sicurezza", "/schede-sicurezza/", ("/schede-sicurezza/",)),
    ModuloHub("rentri", "RENTRI rifiuti", "/rentri/", ("/rentri/",)),
    ModuloHub("scadenzario", "Scadenzario", "/scadenze/", ("/scadenze/",)),
    ModuloHub("security", "SOC sicurezza informatica", "/soc/", ("/soc/",)),
    ModuloHub("tickets", "Ticket IT", "/tickets/", ("/tickets/",)),
    ModuloHub("anagrafica", "Anagrafica e formazione", "/anagrafica/", ("/anagrafica/",)),
    ModuloHub("assenze", "Assenze", "/assenze/", ("/assenze/",)),
)
PER_CHIAVE = {m.chiave: m for m in MODULI_HUB}

# Parole chiave (minuscolo, senza accenti) → modulo. «compila» = il modello cartaceo
# corrisponde a un modulo digitale dell'HUB (vale solo per i codici MOD.).
REGOLE: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("dpi",), "dpi", True),
    (("ingress", "visitator", "ospit"), "reception", False),
    (("non conformit", "azioni corrett", "azione corrett"), "anomalie", True),
    (("miglioramento", "ofi"), "registro_ofi", False),
    (("incident",), "rilevazione_incidenti", True),
    (("asset", "manutenzion", "macchin"), "assets", True),
    (("approvvigion", "fornitor", "acquist"), "fornitori", False),
    (("apparecchiature di misura", "taratur", "strument"), "attrezzature", False),
    (("specific",), "gestione_specifiche", True),
    (("audit", "riesame", "rischi"), "sistema_gestione", False),
    (("acquisizione ordini", "first article", "riesame del contratto", "piano della qualita", "piano qualita"), "kickoff", False),
    (("ordine di lavorazione", "lavorazione", "tracciabil", "messa in lavoro", "produzione"), "produzione", True),
    (("formazione", "competenz", "selezione", "assunzion"), "anagrafica", False),
    (("genitorialit", "conciliazione"), "assenze", False),
    (("requisiti legali", "scadenz"), "scadenzario", False),
    (("rifiut",), "rentri", False),
    (("isms", "sicurezza delle informazioni", "backup", "request for change", "porte"), "security", False),
    (("preposto",), "diario_preposto", False),
    (("schede di sicurezza", "sostanze", "chimic"), "schede_sicurezza", False),
)


def _piega(testo: str) -> str:
    from procedure_refresh.libreria import _piega as piega

    return piega(testo)


def proposte(documenti) -> list[dict]:
    """Collegamenti suggeriti per i documenti dati che non sono già collegati a quel modulo."""
    from procedure_refresh.models import SgiDocumentoModulo

    esistenti = set(SgiDocumentoModulo.objects.values_list("documento_id", "modulo"))
    out = []
    for d in documenti:
        testo = _piega(f"{d.code} {d.title}")
        visti = set()
        for parole, modulo, compila in REGOLE:
            if modulo in visti or (d.pk, modulo) in esistenti:
                continue
            parola = next((p for p in parole if p in testo), None)
            if parola is None:
                continue
            visti.add(modulo)
            out.append({
                "doc": d, "modulo": PER_CHIAVE[modulo], "parola": parola,
                "compila": compila and d.code.upper().startswith("MOD"),
            })
    return out


def svuota_cache() -> None:
    cache.delete(CACHE_KEY)
    cache.delete("cnsgi_codici_riservati")


def _mappa() -> dict[str, list[dict]]:
    """Modulo → procedure collegate (documenti attivi con revisione corrente), dalla cache."""
    dati = cache.get(CACHE_KEY)
    if dati is not None:
        return dati
    from procedure_refresh.models import SgiDocumentoModulo

    dati = {}
    try:
        righe = (
            SgiDocumentoModulo.objects.filter(documento__is_active=True)
            .select_related("documento")
            .prefetch_related("documento__revisions")
            .order_by("documento__code")
        )
        for r in righe:
            d = r.documento
            rev = next((x for x in d.revisions.all() if x.is_current), None)
            if rev is None:
                continue
            dati.setdefault(r.modulo, []).append({
                "id": d.pk, "codice": d.code, "titolo": d.title, "rev": rev.revision_code,
                "compila": r.compila, "categoria": d.category, "sezione": d.sezione,
                "escludi": bool(d.escludi_dal_rag),
            })
    except Exception:
        dati = {}
    cache.set(CACHE_KEY, dati, CACHE_SECONDI)
    return dati


def modulo_del_percorso(percorso: str) -> ModuloHub | None:
    percorso = percorso or ""
    migliore = None
    lunghezza = 0
    for m in MODULI_HUB:
        for p in m.prefissi:
            if percorso.startswith(p) and len(p) > lunghezza:
                migliore, lunghezza = m, len(p)
    return migliore


def procedure_della_pagina(percorso: str) -> tuple[ModuloHub | None, list[dict]]:
    """Le procedure da mostrare accanto al sotto-menu della pagina (solo quelle aperte a tutti)."""
    modulo = modulo_del_percorso(percorso)
    if modulo is None:
        return None, []
    elenco = _mappa().get(modulo.chiave, [])
    if not elenco:
        return modulo, []
    riservati = _codici_riservati()
    visibili = [p for p in elenco if not p["escludi"] and p["codice"] not in riservati]
    return modulo, visibili


def _codici_riservati() -> set[str]:
    riservati = cache.get("cnsgi_codici_riservati")
    if riservati is None:
        try:
            from procedure_refresh.libreria import codici_riservati

            riservati = sorted(codici_riservati())
        except Exception:
            riservati = []
        cache.set("cnsgi_codici_riservati", riservati, 60)
    return set(riservati)


_SUFFISSI_SOCIETA = ("s.p.a.", "spa", "s.r.l.", "srl", "s.a.s.", "sas", "gmbh", "ltd", "inc", "s.a.", "group", "gruppo")


def _nome_cliente(testo: str) -> str:
    t = _piega(testo).replace(".", " ").replace(",", " ").replace("_", " ").replace("-", " ")
    parole = [p for p in t.split() if p and p not in {s.replace(".", "") for s in _SUFFISSI_SOCIETA}]
    return " ".join(parole)


def documenti_per_kickoff(request, cliente: str, limite: int = 6) -> list[dict]:
    """Per la panoramica del kickoff: piani qualità del cliente e procedure collegate al KICK-OFF.

    Il piano qualità si riconosce dalla cartella del cliente nello scaffale dei Piani Qualità
    (o dal titolo) che contiene il nome del cliente della commessa, o viceversa. Solo documenti
    che chi guarda può vedere.
    """
    from django.urls import reverse

    from procedure_refresh.libreria import Visibilita, documenti_in_vigore, etichetta_sezione, identita_da_cartella

    nome = _nome_cliente(cliente or "")
    vis = Visibilita(request)
    piani, procedure = [], []
    collegati = {p["id"] for p in _mappa().get("kickoff", [])}
    for d in documenti_in_vigore():
        scaffale = identita_da_cartella(d.category)["nome"].lower()
        e_piano = "piani" in scaffale
        if e_piano and nome and len(nome) >= 3:
            cartella = _nome_cliente(d.sezione or "")
            titolo = _nome_cliente(d.title)
            if not ((cartella and (cartella in nome or nome in cartella)) or nome in titolo):
                continue
        elif d.pk not in collegati:
            continue
        if not vis.puo_vedere(d):
            continue
        voce = {
            "codice": d.code, "titolo": d.title, "rev": d.rev.revision_code,
            "dove": etichetta_sezione(d.sezione) if e_piano else identita_da_cartella(d.category)["nome"],
            "href": reverse("procedure_refresh:libreria_documento", args=[d.pk]),
        }
        (piani if e_piano else procedure).append(voce)
    return (piani + procedure)[:limite]


def moduli_del_documento(doc) -> list[dict]:
    """I moduli dell'HUB collegati al documento, per la scheda."""
    from procedure_refresh.models import SgiDocumentoModulo

    out = []
    for r in SgiDocumentoModulo.objects.filter(documento=doc):
        m = PER_CHIAVE.get(r.modulo)
        if m is not None:
            out.append({"modulo": m, "compila": r.compila})
    return sorted(out, key=lambda x: x["modulo"].nome)
