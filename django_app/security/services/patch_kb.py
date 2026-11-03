"""Patch già comprese in una più recente: quando installarne una chiude anche l'altra.

WatchGuard elenca le patch Microsoft una per una (``WatchGuardPatch``) e non dice che un aggiornamento cumulativo
comprende quelli prima. Due fonti, in quest'ordine:

* **Build di Windows nel nome.** «October 26, 2026-KB5134133 (OS Builds 26300.9725, 26200.9725 and 26100.9725)»:
  un cumulativo dello stesso ramo (26100) con revisione più alta (9725 > 9711) comprende tutti i precedenti,
  anche i fuori ciclo e le anteprime che Microsoft non mette nel Security Update Guide.
* **Security Update Guide di Microsoft** (API CVRF pubblica, campo ``Supercedence``) → ``MicrosoftKbSostituzione``:
  «la KB X sostituisce la KB Y», anche per .NET, SQL Server e Office dove il nome non porta il build.
  Si legge con l'interruttore ``watchguard.api.msrc`` nel giro WatchGuard: un documento al mese, riscaricato
  solo quando Microsoft lo aggiorna e al massimo una volta al giorno (ogni documento pesa decine di MB).

Una patch è «compresa» solo in un'altra patch **mancante sullo stesso PC**: è quella da installare. Le anteprime
(«Preview», facoltative e non ancora di produzione) non si propongono mai come patch da installare al posto di un'altra.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import MicrosoftCvrfMese, MicrosoftKbSostituzione

logger = logging.getLogger(__name__)

MSRC_BASE = "https://api.msrc.microsoft.com/cvrf/v3.0"
MSRC_TIMEOUT = 180
MSRC_GIORNI = 400  # i documenti dell'ultimo anno (le catene di sostituzione dei cumulativi sono mensili)
MSRC_RILETTURA = timedelta(hours=20)
_MESE_RE = re.compile(r"^\d{4}-[A-Z][a-z]{2}$")
_KB_RE = re.compile(r"(?<![a-z0-9])kb[\s-]?(\d{6,8})(?!\d)", re.IGNORECASE)
_BUILD_RE = re.compile(r"OS Builds? ([^)]*)", re.IGNORECASE)
_RAMO_RE = re.compile(r"\b(\d{5})\.(\d+)\b")


# --- Lettura dal nome --------------------------------------------------------------------------

def kb_da_testo(*testi) -> str:
    """«KB5134133» dal nome della patch o dal nome del file (windows11.0-kb5134133-x64.msu); '' se non c'è."""
    for testo in testi:
        trovato = _KB_RE.search(str(testo or ""))
        if trovato:
            return f"KB{trovato.group(1)}"
    return ""


def build_da_nome(nome: str) -> dict:
    """{ramo: revisione} dai build di Windows nel nome: «OS Builds 26200.9725 and 26100.9725» → {26200: 9725, 26100: 9725}."""
    trovato = _BUILD_RE.search(str(nome or ""))
    if not trovato:
        return {}
    return {int(ramo): int(rev) for ramo, rev in _RAMO_RE.findall(trovato.group(1))}


def anteprima(nome: str) -> bool:
    return "preview" in str(nome or "").lower()


def _piu_recente_per_build(nuova: dict, vecchia: dict) -> bool:
    comuni = nuova.keys() & vecchia.keys()
    return bool(comuni) and all(nuova[r] > vecchia[r] for r in comuni)


# --- Sostituzioni Microsoft --------------------------------------------------------------------

def mappa_sostituzioni(kbs=None) -> dict:
    """{kb: {kb sostituite, anche a catena}} per le KB richieste (tutte se ``kbs`` è None)."""
    dirette: dict = {}
    for kb, sost in MicrosoftKbSostituzione.objects.values_list("kb", "sostituita"):
        dirette.setdefault(kb, set()).add(sost)
    out = {}
    for kb in (dirette if kbs is None else kbs):
        visti, da_fare = set(), list(dirette.get(kb, ()))
        while da_fare and len(visti) < 500:
            k = da_fare.pop()
            if k not in visti:
                visti.add(k)
                da_fare.extend(dirette.get(k, ()))
        visti.discard(kb)
        out[kb] = visti
    return out


# --- Patch comprese ----------------------------------------------------------------------------

def comprese(patches) -> dict:
    """{pk della patch: {"in": patch che la comprende, "perche": testo}} fra le patch mancanti degli stessi PC.

    Se la patch che la comprende è a sua volta compresa in un'altra, vince l'ultima della catena.
    """
    patches = [p for p in patches if p.presente]
    try:
        catene = mappa_sostituzioni({p.kb for p in patches if p.kb})
    except Exception:  # noqa: BLE001 - senza la tabella Microsoft resta la regola dei build
        logger.exception("patch_kb: sostituzioni Microsoft non lette")
        catene = {}
    per_host: dict = {}
    for p in patches:
        per_host.setdefault(p.host, []).append(p)
    diretta: dict = {}
    for righe in per_host.values():
        build = {p.pk: build_da_nome(p.nome) for p in righe}
        for vecchia in righe:
            candidate = []
            for nuova in righe:
                if nuova.pk == vecchia.pk or anteprima(nuova.nome):
                    continue
                if build[vecchia.pk] and _piu_recente_per_build(build[nuova.pk], build[vecchia.pk]):
                    candidate.append((nuova, "build"))
                elif vecchia.kb and nuova.kb and vecchia.kb != nuova.kb and vecchia.kb in catene.get(nuova.kb, ()):
                    candidate.append((nuova, "microsoft"))
            if candidate:
                diretta[vecchia.pk] = max(candidate, key=lambda c: (c[0].rilasciata_il or date.min,
                                                                    max(build[c[0].pk].values(), default=0)))
    out = {}
    for pk, (sopra, perche) in diretta.items():
        passi = 0
        while sopra.pk in diretta and passi < 20:
            sopra, passi = diretta[sopra.pk][0], passi + 1
        out[pk] = {"in": sopra, "perche": _PERCHE[perche]}
    return out


_PERCHE = {
    "build": "aggiornamento cumulativo di Windows con build più recente",
    "microsoft": "Microsoft la indica come sostitutiva (Security Update Guide)",
}


# --- Lettura dal Security Update Guide ---------------------------------------------------------

def _scarica(url: str):
    import requests

    if not url.startswith(MSRC_BASE + "/"):
        raise ValueError("solo l'API CVRF di Microsoft")
    resp = requests.get(url, timeout=MSRC_TIMEOUT, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def sostituzioni_da_cvrf(doc: dict) -> set:
    """{(kb, sostituita)} dalle correzioni del fornitore (Remediations di tipo 2) di un documento CVRF."""
    coppie = set()
    for vuln in doc.get("Vulnerability") or []:
        for rem in vuln.get("Remediations") or []:
            if rem.get("Type") != 2:
                continue
            kb = str((rem.get("Description") or {}).get("Value") or "").strip()
            if not kb.isdigit():
                continue
            for sost in re.findall(r"\d{6,8}", str(rem.get("Supercedence") or "")):
                if sost != kb:
                    coppie.add((f"KB{kb}", f"KB{sost}"))
    return coppie


def sincronizza_msrc(now=None, *, scarica=None) -> dict:
    """Documenti CVRF dell'ultimo anno nuovi o aggiornati → ``MicrosoftKbSostituzione``."""
    now = now or timezone.now()
    scarica = scarica or _scarica
    elenco = (scarica(f"{MSRC_BASE}/updates") or {}).get("value") or []
    letti, nuove = [], 0
    for voce in elenco:
        mese = str(voce.get("ID") or "")
        inizio = parse_datetime(str(voce.get("InitialReleaseDate") or ""))
        if not _MESE_RE.match(mese) or not inizio or inizio < now - timedelta(days=MSRC_GIORNI):
            continue
        aggiornato = parse_datetime(str(voce.get("CurrentReleaseDate") or ""))
        stato = MicrosoftCvrfMese.objects.filter(mese=mese).first()
        if stato and stato.letto_il and (stato.aggiornato_il == aggiornato or now - stato.letto_il < MSRC_RILETTURA):
            continue
        coppie = sostituzioni_da_cvrf(scarica(f"{MSRC_BASE}/cvrf/{mese}") or {})
        esistenti = set(MicrosoftKbSostituzione.objects.filter(kb__in={k for k, _ in coppie})
                        .values_list("kb", "sostituita")) if coppie else set()
        mancanti = [MicrosoftKbSostituzione(kb=k, sostituita=s, mese=mese) for k, s in sorted(coppie - esistenti)]
        MicrosoftKbSostituzione.objects.bulk_create(mancanti, batch_size=500)
        nuove += len(mancanti)
        MicrosoftCvrfMese.objects.update_or_create(mese=mese, defaults={
            "aggiornato_il": aggiornato, "letto_il": now, "sostituzioni": len(coppie)})
        letti.append(mese)
    return {"documenti_letti": letti, "sostituzioni_nuove": nuove,
            "sostituzioni_totali": MicrosoftKbSostituzione.objects.count()}
