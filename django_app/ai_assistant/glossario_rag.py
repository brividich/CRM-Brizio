"""Glossario tecnico nel retrieval RAG (fase B2, roadmap 3.1).

Dietro ``OLLAMA_RAG_GLOSSARIO_ENABLED`` (default spento). Con il flag acceso il
tokenizer BM25 riceve, oltre ai token di sempre, dei token canonici:

- ``gl_<id>`` per ogni variante/termine del glossario trovato nel testo (lamatura,
  spot face e ⌴ diventano lo stesso ``gl_<id>``). Solo termini **validati** con
  ``usa_nel_rag``; le bozze entrano solo con ``OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE``
  (strumento di misura in dev, **mai** in produzione).
- pattern dimensionali protetti, che oggi il tokenizer scarta (token < 3 caratteri):
  classi ISO 286 accanto a un numero o a ⌀ (``⌀20 H7`` -> ``iso286_h7``), filetti
  metrici (``M8`` -> ``filetto_m8``, ``M8x1.25`` -> anche ``filetto_m8x1_25``),
  rugosità (``Ra 0,8`` -> ``rug_ra`` e ``rug_ra_0_8``).

Lo stesso pre-pass si applica a query e indice (passa da ``services._tokenize``).
Il testo dei chunk non cambia, quindi gli embeddings restano validi. Fail-safe:
glossario assente o errore -> nessun token aggiuntivo. Import lazy di
``glossario_tecnico``: nessuna dipendenza tra app a livello di modulo.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

VERSION_CACHE_KEY = "glossario_tecnico:rag_version"
_RICONTROLLO_VERSIONE_S = 30.0

# ── Pattern protetti ─────────────────────────────────────────────────────────
_NUM = r"\d{1,4}(?:[.,]\d{1,3})?"
# Filetto metrico: M seguita dal diametro, passo facoltativo (M8, M8x1, M8 x 1,25).
_FILETTO_RE = re.compile(
    r"(?<![A-Za-z0-9.])M(\d{1,3})(?:\s*[x×X]\s*(\d{1,2}(?:[.,]\d{1,3})?))?(?![A-Za-z0-9])"
)
# Classe di tolleranza ISO 286 (lettere senza I, L, O, Q, W) subito dopo una quota:
# "⌀20 H7", "20 g6", "20H7/g6". Il numero non deve seguire un punto o una lettera
# (esclude "MOD.093", "Rev.21", "CN 06" seguito da testo).
_CLASSE = r"[A-HJKMNP-VX-Za-hjkmnp-vx-z]{1,2}"
_ISO286_RE = re.compile(
    r"(?:[⌀Øø∅]\s*)?(?<![A-Za-z0-9.,_])" + _NUM + r"\s*(" + _CLASSE + r")(\d{1,2})"
    r"(?:\s*/\s*(" + _CLASSE + r")(\d{1,2}))?(?![A-Za-z0-9_])"
)
_RUGOSITA_RE = re.compile(r"(?<![A-Za-z0-9])(Ra|Rz)\s*(\d{1,3}(?:[.,]\d{1,3})?)(?![A-Za-z0-9])")


def _num_token(value: str) -> str:
    return re.sub(r"[.,]", "_", value)


def token_protetti(testo: str) -> list[str]:
    """Token per filetti, classi ISO 286 e rugosità trovati nel testo originale."""
    out: list[str] = []
    for m in _FILETTO_RE.finditer(testo):
        out.append(f"filetto_m{m.group(1)}")
        if m.group(2):
            out.append(f"filetto_m{m.group(1)}x{_num_token(m.group(2))}")
    for m in _ISO286_RE.finditer(testo):
        out.append(f"iso286_{m.group(1).lower()}{m.group(2)}")
        if m.group(3):
            out.append(f"iso286_{m.group(3).lower()}{m.group(4)}")
    for m in _RUGOSITA_RE.finditer(testo):
        sigla = m.group(1).lower()
        out.append(f"rug_{sigla}")
        out.append(f"rug_{sigla}_{_num_token(m.group(2))}")
    return out


# ── Varianti del glossario ───────────────────────────────────────────────────


def _piega(testo: str) -> str:
    """Stessa normalizzazione della chiave delle varianti: senza accenti, minuscolo."""
    testo = unicodedata.normalize("NFKD", testo or "")
    testo = "".join(ch for ch in testo if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", testo).casefold())


@dataclass
class Voce:
    id: int
    termine: str
    termine_en: str = ""
    categoria: str = ""
    definizione: str = ""
    simbolo: str = ""
    norma_rif: str = ""
    varianti: list[str] = field(default_factory=list)
    esempio_disegno: str = ""


@dataclass
class _Matcher:
    piegato: re.Pattern | None
    esatto: re.Pattern | None
    simboli: re.Pattern | None
    mappa_piegato: dict[str, int]
    mappa_esatto: dict[str, int]
    mappa_simboli: dict[str, int]


_STATO: dict = {"versione": None, "controllato": 0.0, "matcher": None, "voci": None}


def attivo() -> bool:
    return bool(getattr(settings, "OLLAMA_RAG_GLOSSARIO_ENABLED", False))


def includi_bozze() -> bool:
    return bool(getattr(settings, "OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE", False))


def versione() -> str:
    try:
        return str(cache.get(VERSION_CACHE_KEY) or "0")
    except Exception:
        return "0"


def bump_versione() -> None:
    """Chiamato dai signal del glossario: invalida regex e indice."""
    try:
        cache.set(VERSION_CACHE_KEY, str(time.time_ns()), timeout=None)
    except Exception:
        pass
    _STATO.update({"versione": None, "controllato": 0.0, "matcher": None, "voci": None})


def carica_voci(stati: list[str] | None = None) -> list[Voce]:
    """Termini usabili nel RAG: validati con usa_nel_rag (più le bozze solo con
    OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE). ``stati`` forza l'elenco (revisione).
    Lista vuota se l'app non c'è."""
    try:
        from glossario_tecnico.models import Termine

        if stati is None:
            stati = ["validato", "bozza"] if includi_bozze() else ["validato"]
        qs = Termine.objects.filter(stato__in=stati, usa_nel_rag=True).prefetch_related("varianti")
        return [
            Voce(id=t.pk, termine=t.termine, termine_en=t.termine_en, categoria=t.get_categoria_display(),
                 definizione=t.definizione, simbolo=t.simbolo, norma_rif=t.norma_rif,
                 varianti=[v.testo for v in t.varianti.all()], esempio_disegno=t.esempio_disegno)
            for t in qs
        ]
    except Exception:
        logger.debug("glossario_rag: glossario non disponibile", exc_info=True)
        return []


def _e_simbolo(testo: str) -> bool:
    return bool(testo) and not any(ch.isalnum() for ch in testo)


def _e_esatta(testo: str) -> bool:
    """Sigle corte (NC, Ra, IT, FAI, MT): confronto con maiuscole/minuscole esatte, così
    «IT» non scatta su «it» e «FAI» non scatta sul verbo «fai»."""
    compatto = testo.replace(".", "")
    return len(compatto) <= 3 and compatto.isalnum() and any(ch.isupper() for ch in testo)


def _alternanza(chiavi) -> str:
    return "|".join(re.escape(k) for k in sorted(chiavi, key=len, reverse=True))


def _costruisci(voci: list[Voce]) -> _Matcher:
    piegato: dict[str, int] = {}
    esatto: dict[str, int] = {}
    simboli: dict[str, int] = {}
    for voce in voci:
        testi = [voce.termine, voce.simbolo, *voce.varianti]
        for testo in testi:
            testo = (testo or "").strip()
            if not testo:
                continue
            if _e_simbolo(testo):
                simboli.setdefault(testo, voce.id)
            elif _e_esatta(testo):
                esatto.setdefault(testo, voce.id)
            else:
                chiave = _piega(testo).strip()
                if len(chiave) >= 3:
                    piegato.setdefault(chiave, voce.id)
    return _Matcher(
        piegato=re.compile(r"(?<![a-z0-9])(?:" + _alternanza(piegato) + r")(?![a-z0-9])") if piegato else None,
        esatto=re.compile(r"(?<![A-Za-z0-9])(?:" + _alternanza(esatto) + r")(?![A-Za-z0-9])") if esatto else None,
        simboli=re.compile(_alternanza(simboli)) if simboli else None,
        mappa_piegato=piegato, mappa_esatto=esatto, mappa_simboli=simboli,
    )


def _matcher() -> _Matcher | None:
    adesso = time.monotonic()
    if _STATO["matcher"] is not None and adesso - _STATO["controllato"] < _RICONTROLLO_VERSIONE_S:
        return _STATO["matcher"]
    ver = versione() + ("+bozze" if includi_bozze() else "")
    if _STATO["matcher"] is None or _STATO["versione"] != ver:
        voci = carica_voci()
        _STATO.update({"voci": voci, "matcher": _costruisci(voci), "versione": ver})
    _STATO["controllato"] = adesso
    return _STATO["matcher"]


def token_glossario(testo: str) -> list[str]:
    """Token ``gl_<id>`` per le varianti trovate nel testo."""
    m = _matcher()
    if m is None:
        return []
    out: list[str] = []
    if m.piegato is not None:
        out.extend(f"gl_{m.mappa_piegato[x.group(0)]}" for x in m.piegato.finditer(_piega(testo)))
    nfc = unicodedata.normalize("NFC", testo)
    if m.esatto is not None:
        out.extend(f"gl_{m.mappa_esatto[x.group(0)]}" for x in m.esatto.finditer(nfc))
    if m.simboli is not None:
        out.extend(f"gl_{m.mappa_simboli[x.group(0)]}" for x in m.simboli.finditer(nfc))
    return out


def varianti_comuni(testi: list[str], voci: list[Voce], soglia: float) -> list[dict]:
    """Varianti (o termini) trovate in più di ``soglia`` (0–1) dei testi, con le stesse
    regole del pre-pass. Solo segnalazione per la revisione: nessuna esclusione."""
    if not testi or not voci:
        return []
    m = _costruisci(voci)
    frequenza: dict[tuple[str, str], int] = {}
    for testo in testi:
        trovate: set[tuple[str, str]] = set()
        if m.piegato is not None:
            trovate.update(("p", x.group(0)) for x in m.piegato.finditer(_piega(testo)))
        nfc = unicodedata.normalize("NFC", testo)
        if m.esatto is not None:
            trovate.update(("e", x.group(0)) for x in m.esatto.finditer(nfc))
        if m.simboli is not None:
            trovate.update(("s", x.group(0)) for x in m.simboli.finditer(nfc))
        for chiave in trovate:
            frequenza[chiave] = frequenza.get(chiave, 0) + 1
    mappe = {"p": m.mappa_piegato, "e": m.mappa_esatto, "s": m.mappa_simboli}
    nomi = {v.id: v.termine for v in voci}
    n = len(testi)
    out = []
    for (gruppo, testo), conteggio in frequenza.items():
        if conteggio / n > soglia:
            termine_id = mappe[gruppo][testo]
            out.append({"termine_id": termine_id, "termine": nomi.get(termine_id, ""), "testo": testo,
                        "chunk": conteggio, "quota": round(conteggio / n, 3)})
    return sorted(out, key=lambda r: (-r["quota"], r["testo"]))


def token_aggiuntivi(testo: str) -> list[str]:
    """Pre-pass completo (pattern protetti + glossario). Vuoto a flag spento. Mai eccezioni."""
    if not attivo() or not testo:
        return []
    try:
        return token_protetti(testo) + token_glossario(testo)
    except Exception:
        logger.debug("glossario_rag: pre-pass fallito", exc_info=True)
        return []


def firma() -> tuple:
    """Parte della firma dell'indice RAG: cambia se cambia il glossario o i flag."""
    if not attivo():
        return ()
    return ("glossario", versione(), includi_bozze())


def voci_per_chunk() -> list[Voce]:
    if not attivo():
        return []
    _matcher()
    return list(_STATO.get("voci") or [])
