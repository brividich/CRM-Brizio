"""Logica del glossario: gestione varianti, import CSV, candidati dal corpus SGI,
proposte AI. Tutto ciò che è deterministico resta senza LLM; l'AI propone soltanto
e le proposte non diventano termini finché una persona non le accetta.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .chiave import normalizza_chiave
from .models import Termine, Variante

logger = logging.getLogger(__name__)

MODULO_AI = "glossario"
AZIONE_NUOVO = "nuovo_termine"
CATEGORIE = {c for c, _ in Termine.CATEGORIE}
TIPI_VARIANTE = {t for t, _ in Variante.TIPI}


# ── Termini e varianti ───────────────────────────────────────────────────────


def aggiungi_variante(termine: Termine, testo: str, tipo: str, lingua: str = "it") -> Variante:
    """Crea una variante. ValidationError se vuota, tipo ignoto o già di un altro termine
    (il conflitto è esplicito, mai risolto in silenzio)."""
    if tipo not in TIPI_VARIANTE:
        raise ValidationError({"tipo": f"Tipo di variante non valido: {tipo}"})
    variante = Variante(termine=termine, testo=(testo or "").strip()[:150], tipo=tipo, lingua=(lingua or "")[:2])
    variante.chiave = normalizza_chiave(variante.testo)
    variante.full_clean(exclude=["termine", "chiave"])  # conflitto chiave: messaggio esplicito in clean()
    variante.save()
    return variante


def valida(termine: Termine, user) -> None:
    termine.stato = Termine.VALIDATO
    termine.validato_da = user if getattr(user, "pk", None) else None
    termine.validato_il = timezone.now()
    termine.save(update_fields=["stato", "validato_da", "validato_il", "updated_at"])


def depreca(termine: Termine) -> None:
    termine.stato = Termine.DEPRECATO
    termine.save(update_fields=["stato", "updated_at"])


# ── Import CSV ───────────────────────────────────────────────────────────────

CSV_COLONNE = ["termine", "termine_en", "categoria", "definizione", "simbolo", "norma_rif", "varianti"]


@dataclass
class EsitoImport:
    importati: int = 0
    saltati: int = 0
    errori: list[str] = field(default_factory=list)
    righe: int = 0


def _parse_varianti(raw: str) -> list[tuple[str, str]]:
    out = []
    for pezzo in (raw or "").split("|"):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        tipo, sep, testo = pezzo.partition(":")
        if not sep:
            raise ValueError(f"variante «{pezzo}» senza tipo (formato tipo:testo)")
        tipo, testo = tipo.strip().lower(), testo.strip()
        if tipo not in TIPI_VARIANTE:
            raise ValueError(f"tipo di variante non valido «{tipo}»")
        if not testo:
            raise ValueError("variante vuota")
        out.append((tipo, testo))
    return out


def importa_csv(contenuto: str, *, dry_run: bool = False) -> EsitoImport:
    """Importa righe ``termine;termine_en;categoria;definizione;simbolo;norma_rif;varianti``.

    Le righe valide diventano termini in bozza (fonte import_csv). Una riga con
    errori (categoria ignota, definizione vuota, variante già di un altro termine)
    viene scartata per intero e riportata. ``dry_run``: tutto in una transazione
    annullata alla fine.
    """
    esito = EsitoImport()
    lettore = csv.DictReader(io.StringIO(contenuto.lstrip("﻿")), delimiter=";")
    mancanti = [c for c in CSV_COLONNE if c not in (lettore.fieldnames or [])]
    if mancanti:
        esito.errori.append(f"Intestazione: colonne mancanti {', '.join(mancanti)}")
        return esito

    with transaction.atomic():
        for n, riga in enumerate(lettore, start=2):
            esito.righe += 1
            termine_txt = (riga.get("termine") or "").strip()[:150]
            categoria = (riga.get("categoria") or "").strip()
            definizione = (riga.get("definizione") or "").strip()
            try:
                if not termine_txt:
                    raise ValueError("termine vuoto")
                if categoria not in CATEGORIE:
                    raise ValueError(f"categoria non valida «{categoria}»")
                if not definizione:
                    raise ValueError("definizione vuota")
                varianti = _parse_varianti(riga.get("varianti") or "")
            except ValueError as exc:
                esito.errori.append(f"Riga {n}: {exc}")
                continue
            if Termine.objects.filter(termine__iexact=termine_txt, categoria=categoria).exists():
                esito.saltati += 1
                continue
            try:
                with transaction.atomic():
                    termine = Termine(
                        termine=termine_txt, categoria=categoria, definizione=definizione,
                        termine_en=(riga.get("termine_en") or "").strip()[:150],
                        simbolo=(riga.get("simbolo") or "").strip()[:20],
                        norma_rif=(riga.get("norma_rif") or "").strip()[:60],
                        stato=Termine.BOZZA, fonte="import_csv",
                    )
                    termine.full_clean(exclude=["validato_da"])
                    termine.save()
                    for tipo, testo in varianti:
                        aggiungi_variante(termine, testo, tipo, "en" if tipo == "traduzione" else "it")
            except ValidationError as exc:
                messaggi = "; ".join(m for msgs in exc.message_dict.values() for m in msgs)
                esito.errori.append(f"Riga {n}: {messaggi}")
                continue
            esito.importati += 1
        if dry_run:
            transaction.set_rollback(True)
    return esito


# ── Candidati dal corpus SGI (deterministico) ────────────────────────────────

_STOPWORD = set("""
a ad al alla alle allo ai agli all anche che chi ci con contro cui da dal dalla dalle dai dagli degli
dei del della delle dello di e ed fra gli ha hanno ho i il in la le lo loro ma mi ne nei nel nella
nelle nello no non o od per piu più può puo quale quali quando quanto questa queste questi questo se
sia siano sono su sua sue sui sul sulla sulle suo suoi tra tutti tutte tutto un una uno vi viene
vengono essere stato stata stati come dove deve devono ogni altro altri altre ecc tale tali secondo
the and of to for with on by from this that are is be
""".split())

_PAROLA_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]{2,}")


def _parole_riga(riga: str) -> list[str]:
    return [p.strip("'’-").lower() for p in _PAROLA_RE.findall(riga)]


def _ngrammi(parole: list[str], n_max: int = 3):
    for n in range(1, n_max + 1):
        for i in range(len(parole) - n + 1):
            gram = parole[i:i + n]
            if gram[0] in _STOPWORD or gram[-1] in _STOPWORD:
                continue
            if all(len(p) < 3 for p in gram):
                continue
            yield " ".join(gram)


def _nomi_persone() -> set[str]:
    """Nomi e cognomi degli utenti del portale: mai proposti come termini (privacy)."""
    nomi: set[str] = set()
    try:
        from django.contrib.auth import get_user_model

        for first, last in get_user_model().objects.values_list("first_name", "last_name"):
            for parte in f"{first or ''} {last or ''}".split():
                if len(parte) >= 3:
                    nomi.add(normalizza_chiave(parte))
    except Exception:
        logger.debug("glossario: elenco nomi utenti non disponibile", exc_info=True)
    return nomi


def chiavi_note() -> set[str]:
    """Chiavi già coperte dal glossario: varianti e forme canoniche dei termini."""
    chiavi = set(Variante.objects.values_list("chiave", flat=True))
    chiavi.update(normalizza_chiave(t) for t in Termine.objects.values_list("termine", flat=True))
    return chiavi


def candidati(testi: list[str], *, min_documenti: int = 3, limit: int = 50) -> list[dict]:
    """N-grammi (1–3 parole) presenti in almeno ``min_documenti`` documenti e non ancora
    nel glossario, ordinati per frequenza documentale. Esclusi stopword ai bordi,
    numeri e nomi di persone note."""
    df: Counter = Counter()
    for testo in testi:
        visti: set[str] = set()
        for riga in (testo or "").splitlines():
            visti.update(_ngrammi(_parole_riga(riga)))
        df.update(visti)
    note = chiavi_note()
    persone = _nomi_persone()
    out = []
    for gram, n_doc in sorted(df.items(), key=lambda kv: (-kv[1], kv[0])):
        if n_doc < min_documenti:
            break
        chiave = normalizza_chiave(gram)
        if chiave in note or any(p in persone for p in chiave.split()):
            continue
        out.append({"testo": gram, "chiave": chiave, "documenti": n_doc})
        if len(out) >= limit:
            break
    return out


def testi_corpus_sgi() -> list[str]:
    """Testi persistiti dei documenti SGI correnti (A1). Lista vuota se la tabella
    non c'è o è vuota. Esclusi i documenti fuori dal RAG."""
    try:
        from procedure_refresh.models import SgiTestoEstratto

        return list(
            SgiTestoEstratto.objects.filter(
                revision__is_current=True, revision__document__is_active=True,
                revision__document__escludi_dal_rag=False,
            ).values_list("testo", flat=True)
        )
    except Exception:
        logger.debug("glossario: corpus SGI non disponibile", exc_info=True)
        return []


# ── Proposte AI ──────────────────────────────────────────────────────────────

_PROMPT_AI = (
    "Sei un esperto di metalmeccanica e qualità. Per ciascun termine dell'elenco proponi una voce "
    "di glossario. Rispondi SOLO con un array JSON, un oggetto per termine, con le chiavi: "
    "\"candidato\" (il termine dell'elenco, identico), \"termine\" (forma canonica italiana), "
    "\"categoria\" (una delle categorie ammesse), \"definizione\" (max 400 caratteri, parole tue, "
    "nessun testo di norma, nessun valore numerico di tabella), \"varianti\" (array di oggetti "
    "{\"tipo\", \"testo\"}). Se un termine non è tecnico rispondi con \"categoria\": \"scarta\".\n"
    "Termini: {elenco}"
)


def _contesto_ai() -> str:
    righe = ["Categorie ammesse: " + ", ".join(sorted(CATEGORIE)),
             "Tipi di variante ammessi: " + ", ".join(sorted(TIPI_VARIANTE))]
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lezioni = lezioni_testo(MODULO_AI, AZIONE_NUOVO)
        if lezioni:
            righe.append(lezioni)
    except Exception:
        pass
    return "\n".join(righe)


def _estrai_json(testo: str):
    inizio, fine = testo.find("["), testo.rfind("]")
    if inizio == -1 or fine <= inizio:
        return None
    try:
        return json.loads(testo[inizio:fine + 1])
    except ValueError:
        return None


def valida_proposta(voce: dict, candidati_ammessi: dict[str, str]) -> dict | None:
    """Proposta pulita o None. Il candidato deve essere uno di quelli chiesti,
    categoria e tipi nell'elenco chiuso, testi troncati, varianti già note scartate."""
    if not isinstance(voce, dict):
        return None
    chiave = normalizza_chiave(str(voce.get("candidato") or ""))
    if chiave not in candidati_ammessi:
        return None
    categoria = str(voce.get("categoria") or "").strip()
    if categoria not in CATEGORIE:
        return None
    termine = re.sub(r"\s+", " ", str(voce.get("termine") or "")).strip()[:150]
    definizione = re.sub(r"\s+", " ", str(voce.get("definizione") or "")).strip()[:600]
    if not termine or not definizione:
        return None
    note = chiavi_note()
    varianti = []
    for v in voce.get("varianti") or []:
        if not isinstance(v, dict):
            continue
        tipo, testo = str(v.get("tipo") or "").strip(), str(v.get("testo") or "").strip()[:150]
        k = normalizza_chiave(testo)
        if tipo in TIPI_VARIANTE and k and k not in note and f"{tipo}:{testo}" not in varianti:
            varianti.append(f"{tipo}:{testo}")
    return {"candidato": candidati_ammessi[chiave], "termine": termine, "categoria": categoria,
            "definizione": definizione, "varianti": varianti[:10]}


def proponi_con_ai(candidati_batch: list[str], *, user=None) -> int:
    """Chiede all'LLM le proposte per un batch di candidati e le registra in
    AiProposta (in attesa di decisione). Ritorna quante proposte sono state registrate.
    Fail-safe: AI non disponibile o JSON malformato -> 0, nessuna eccezione."""
    from ai_assistant.apprendimento import registra_proposta
    from ai_assistant.services import OllamaChatError, chat_with_ollama

    ammessi = {normalizza_chiave(c): c for c in candidati_batch if normalizza_chiave(c)}
    if not ammessi:
        return 0
    prompt = _PROMPT_AI.replace("{elenco}", "; ".join(ammessi.values()))
    try:
        risposta = chat_with_ollama(prompt, runtime_context=_contesto_ai(), timeout=80)
    except OllamaChatError as exc:
        logger.info("glossario: AI non disponibile: %s", exc)
        return 0
    except Exception:
        logger.exception("glossario: chiamata AI fallita")
        return 0
    voci = _estrai_json(risposta.content or "")
    if not isinstance(voci, list):
        return 0
    registrate = 0
    for voce in voci:
        pulita = valida_proposta(voce, ammessi)
        if pulita is None:
            continue
        if registra_proposta(modulo=MODULO_AI, azione=AZIONE_NUOVO,
                             oggetto_ref=f"cand:{normalizza_chiave(pulita['candidato'])}"[:80],
                             proposta=pulita, user=user):
            registrate += 1
    return registrate


_CAMPI_DECISIONE = ["termine", "categoria", "definizione", "varianti"]


# ── Parole comuni (varianti presenti in troppi chunk SGI) ──────────────────────
VARIANTI_COMUNI_CACHE_KEY = "glossario_tecnico:varianti_comuni"
SOGLIA_PAROLA_COMUNE = 0.20


def calcola_varianti_comuni(testi: list[str], *, soglia: float = SOGLIA_PAROLA_COMUNE) -> dict:
    """Varianti dei termini (bozze e validati con «usa nell'assistente») presenti in più
    di ``soglia`` dei chunk SGI. Salva il risultato in cache per la pagina «Da rivedere».
    Solo segnalazione: decide la Qualità se togliere «usa nell'assistente»."""
    from django.core.cache import cache

    from ai_assistant import glossario_rag

    voci = glossario_rag.carica_voci(stati=[Termine.BOZZA, Termine.VALIDATO])
    esito = {
        "calcolato": timezone.now().isoformat(timespec="minutes"),
        "chunk_sgi": len(testi),
        "soglia": soglia,
        "voci": glossario_rag.varianti_comuni(testi, voci, soglia),
    }
    cache.set(VARIANTI_COMUNI_CACHE_KEY, esito, timeout=None)
    return esito


def varianti_comuni_salvate() -> dict | None:
    from django.core.cache import cache

    try:
        return cache.get(VARIANTI_COMUNI_CACHE_KEY)
    except Exception:
        return None


def proposte_in_attesa():
    from ai_assistant.models import AiProposta

    return AiProposta.objects.filter(modulo=MODULO_AI, azione=AZIONE_NUOVO, esito=AiProposta.IN_ATTESA)


@transaction.atomic
def accetta_proposta(proposta, user, dati: dict | None = None) -> Termine:
    """Crea il termine (bozza validata dalla persona che accetta) dalla proposta,
    eventualmente corretta, e registra la decisione per le lezioni future."""
    from ai_assistant.apprendimento import registra_decisione

    dati = dict(dati or proposta.proposta)
    termine = Termine(
        termine=str(dati.get("termine") or "")[:150], categoria=dati.get("categoria") or "",
        definizione=str(dati.get("definizione") or ""), fonte="ai_proposta", stato=Termine.BOZZA,
    )
    termine.full_clean(exclude=["validato_da"])
    termine.save()
    for voce in dati.get("varianti") or []:
        tipo, _sep, testo = str(voce).partition(":")
        aggiungi_variante(termine, testo, tipo, "en" if tipo == "traduzione" else "it")
    valida(termine, user)
    registra_decisione(modulo=MODULO_AI, azione=AZIONE_NUOVO, oggetto_ref=proposta.oggetto_ref,
                       decisione={k: dati.get(k) for k in _CAMPI_DECISIONE}, user=user, campi=_CAMPI_DECISIONE)
    return termine


def scarta_proposta(proposta, user) -> None:
    from ai_assistant.apprendimento import registra_decisione

    registra_decisione(modulo=MODULO_AI, azione=AZIONE_NUOVO, oggetto_ref=proposta.oggetto_ref,
                       decisione={}, user=user)
