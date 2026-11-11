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
import time
from datetime import date, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import MicrosoftCvrfMese, MicrosoftKbSostituzione

logger = logging.getLogger(__name__)

MSRC_BASE = "https://api.msrc.microsoft.com/cvrf/v3.0"
MSRC_TIMEOUT = (15, 60)  # connessione, lettura fra due blocchi
MSRC_GIORNI = 400  # i documenti dell'ultimo anno (le catene di sostituzione dei cumulativi sono mensili)
MSRC_RILETTURA = timedelta(hours=20)
# CurrentReleaseDate non leggibile: non si sa se il documento è cambiato, si rilegge al massimo una volta a settimana
MSRC_RILETTURA_SENZA_DATA = timedelta(days=7)
MSRC_DOCUMENTI_PER_GIRO = 2  # ogni documento pesa decine di MB: gli altri mesi al giro dopo (lo stato è per mese)
MSRC_TEMPO_MAX = 240  # secondi per tutti i documenti di un giro (timeout della coda del giro WatchGuard: 600 s)
MSRC_MAX_BYTES = 200 * 1024 * 1024
_BLOCCO = 1024 * 1024
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

class TempoEsaurito(RuntimeError):
    """Il download non è finito nel tempo del giro: il documento si legge al giro dopo."""


def _scarica(url: str, scadenza: float | None = None):
    """JSON di un documento dell'API CVRF, scaricato a blocchi su file temporaneo (non tutto in memoria)."""
    import json
    import tempfile

    import requests

    if not url.startswith(MSRC_BASE + "/"):
        raise ValueError("solo l'API CVRF di Microsoft")
    with requests.get(url, timeout=MSRC_TIMEOUT, headers={"Accept": "application/json"}, stream=True) as resp:
        resp.raise_for_status()
        with tempfile.TemporaryFile() as tmp:
            letti = 0
            for blocco in resp.iter_content(chunk_size=_BLOCCO):
                letti += len(blocco)
                if letti > MSRC_MAX_BYTES:
                    raise ValueError(f"documento Microsoft oltre {MSRC_MAX_BYTES // (1024 * 1024)} MB")
                if scadenza is not None and time.monotonic() > scadenza:
                    raise TempoEsaurito("download interrotto: tempo del giro esaurito")
                tmp.write(blocco)
            tmp.seek(0)
            return json.load(tmp)


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


def _da_leggere(stato, aggiornato, now) -> bool:
    if not stato or not stato.letto_il:
        return True
    if aggiornato is None:
        # data di Microsoft non leggibile: mai «uguale a quella salvata» per sempre, ma nemmeno ogni giorno
        return now - stato.letto_il >= MSRC_RILETTURA_SENZA_DATA
    return stato.aggiornato_il != aggiornato and now - stato.letto_il >= MSRC_RILETTURA


def _data(valore):
    try:
        return parse_datetime(str(valore or ""))
    except ValueError:  # data con forma giusta ma valori impossibili
        return None


def sincronizza_msrc(now=None, *, scarica=None, clock=time.monotonic) -> dict:
    """Documenti CVRF dell'ultimo anno nuovi o aggiornati → ``MicrosoftKbSostituzione``.

    Al massimo ``MSRC_DOCUMENTI_PER_GIRO`` documenti e ``MSRC_TEMPO_MAX`` secondi per giro, i più recenti
    prima: i mesi rimasti si leggono ai giri successivi (lo stato di ogni mese è in ``MicrosoftCvrfMese``).
    """
    now = now or timezone.now()
    scadenza = clock() + MSRC_TEMPO_MAX
    if scarica is None:
        def scarica(url):
            return _scarica(url, scadenza=scadenza)
    elenco = (scarica(f"{MSRC_BASE}/updates") or {}).get("value") or []
    candidati = []
    for voce in elenco:
        mese = str(voce.get("ID") or "")
        inizio = _data(voce.get("InitialReleaseDate"))
        if not _MESE_RE.match(mese) or not inizio or inizio < now - timedelta(days=MSRC_GIORNI):
            continue
        aggiornato = _data(voce.get("CurrentReleaseDate"))
        if _da_leggere(MicrosoftCvrfMese.objects.filter(mese=mese).first(), aggiornato, now):
            candidati.append((inizio, mese, aggiornato))
    candidati.sort(reverse=True)
    letti, nuove, rimandati = [], 0, 0
    for _inizio, mese, aggiornato in candidati:
        if len(letti) >= MSRC_DOCUMENTI_PER_GIRO or clock() >= scadenza:
            rimandati += 1
            continue
        try:
            doc = scarica(f"{MSRC_BASE}/cvrf/{mese}") or {}
        except TempoEsaurito:
            rimandati += 1
            continue
        coppie = sostituzioni_da_cvrf(doc)
        kbs, esistenti = sorted({k for k, _ in coppie}), set()
        for i in range(0, len(kbs), 500):  # mai oltre i 2100 parametri di SQL Server
            esistenti |= set(MicrosoftKbSostituzione.objects.filter(kb__in=kbs[i:i + 500]).values_list("kb", "sostituita"))
        mancanti = [MicrosoftKbSostituzione(kb=k, sostituita=s, mese=mese) for k, s in sorted(coppie - esistenti)]
        MicrosoftKbSostituzione.objects.bulk_create(mancanti, batch_size=500)
        nuove += len(mancanti)
        MicrosoftCvrfMese.objects.update_or_create(mese=mese, defaults={
            "aggiornato_il": aggiornato, "letto_il": now, "sostituzioni": len(coppie)})
        letti.append(mese)
    out = {"documenti_letti": letti, "sostituzioni_nuove": nuove,
           "sostituzioni_totali": MicrosoftKbSostituzione.objects.count()}
    if rimandati:
        out["documenti_rimandati"] = rimandati
    return out
