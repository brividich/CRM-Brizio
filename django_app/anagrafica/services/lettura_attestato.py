"""Proposta dei campi di un attestato di formazione ricevuto da un ente esterno.

Dal testo del documento (``core.lettura_documenti``) ricava, senza AI generativa:

- **dipendente**: dal codice fiscale (corrispondenza esatta in anagrafica civile)
  oppure da cognome e nome scritti per intero; solo dipendenti non cessati;
- **corso**: codice del corso scritto nel documento, altrimenti le parole del
  titolo (almeno il 60% delle parole significative presenti);
- **date**: completamento («svolto/tenuto/conseguito/in data…»), rilascio, e la
  scadenza letta (solo informativa: la scadenza vera la calcola il portale dalla
  validità del corso);
- **ore**, **ente** (aziende formative e fornitori in anagrafica), **numero**.

È una proposta: la pagina la mostra, una persona sceglie e conferma. Il codice
fiscale serve solo a riconoscere la persona e non viene mai restituito.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.lettura_documenti import (
    Lettura,
    contiene_parola,
    data_dopo_etichetta,
    date_nel_testo,
    normalizza,
)

_CF_RE = re.compile(r"\b([A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z])\b")
_ORE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:ORE|H)\b")
_ORE_ETICHETTA_RE = re.compile(r"\b(?:DURATA|ORE)\s*(?:COMPLESSIVA|TOTALI|DEL CORSO)?\s*[:=]?\s*(\d{1,3}(?:[.,]\d{1,2})?)\b")
_NUMERO_RE = re.compile(
    r"\b(?:ATTESTATO|CERTIFICATO|REGISTRO)?\s*(?:N\.|N°|NR\.?|NUM\.?|NUMERO|PROT\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-.]{2,30})"
)
_ETICHETTE_COMPLETAMENTO = (
    r"SVOLT[OA]\b", r"TENUT[OA]\b", r"FREQUENTAT[OA]\b", r"CONSEGUIT[OA]\b", r"SOSTENUT[OA]\b",
    r"DATA DEL CORSO", r"DATA CORSO", r"DATA (?:DELL')?ESAME", r"IN DATA", r"IL GIORNO", r"\bDAL\b",
)
_ETICHETTE_RILASCIO = (r"RILASCIAT[OA]", r"DATA (?:DI )?RILASCIO", r"EMESS[OA]", r"\bLI\b", r"\bLÌ\b")
_ETICHETTE_SCADENZA = (r"SCADENZA", r"VALID[OA] FINO", r"VALIDIT[AÀ]", r"AGGIORNAMENTO ENTRO", r"DA RINNOVARE")
_PAROLE_VUOTE = {"CORSO", "DI", "DEL", "DELLA", "DELLE", "DEI", "PER", "IN", "E", "AI", "SUI", "SULLA", "FORMAZIONE", "ADDETTI", "LAVORATORI"}


def _dipendenti(testo_norm: str) -> list[dict]:
    from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from core.naming import nome_completo

    cessati = set(
        DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
    )
    righe = {int(r["id"]): r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("id")}

    def _voce(lid: int, motivo: str) -> dict:
        r = righe.get(lid, {})
        return {"legacy_id": lid, "nome": nome_completo(r.get("nome") or "", r.get("cognome") or "") or f"#{lid}",
                "reparto": str(r.get("reparto") or ""), "motivo": motivo}

    cf_letti = set(_CF_RE.findall(testo_norm.replace(" ", "")))
    trovati: list[dict] = []
    if cf_letti:
        for lid in DipendenteAnagraficaCivile.objects.filter(codice_fiscale__in=cf_letti).values_list(
            "legacy_anagrafica_id", flat=True
        ):
            if lid not in cessati:
                trovati.append(_voce(lid, "codice fiscale"))
    if trovati:
        return trovati
    for lid, r in righe.items():
        if lid in cessati:
            continue
        nome, cognome = str(r.get("nome") or "").strip(), str(r.get("cognome") or "").strip()
        if len(nome) < 2 or len(cognome) < 2:
            continue
        if contiene_parola(testo_norm, f"{cognome} {nome}") or contiene_parola(testo_norm, f"{nome} {cognome}"):
            trovati.append(_voce(lid, "nome e cognome"))
    return trovati[:5]


def _parole(testo: str) -> set[str]:
    return {p for p in re.findall(r"[A-Z0-9]{3,}", normalizza(testo)) if p not in _PAROLE_VUOTE}


def _corsi(testo_norm: str) -> list[dict]:
    from anagrafica.models_formazione import TrainingCourse

    parole_testo = set(re.findall(r"[A-Z0-9]{3,}", testo_norm))
    candidati = []
    for corso in TrainingCourse.objects.filter(is_active=True).exclude(stato="ARCHIVIATO").only(
        "id", "codice", "titolo", "validita_mesi", "durata_ore_teorica"
    ):
        if corso.codice and len(corso.codice) >= 3 and contiene_parola(testo_norm, corso.codice):
            candidati.append((2.0, corso, "codice del corso"))
            continue
        parole = _parole(corso.titolo)
        if len(parole) >= 2:
            quota = len(parole & parole_testo) / len(parole)
            if quota >= 0.6:
                candidati.append((quota, corso, "titolo del corso"))
    candidati.sort(key=lambda c: (-c[0], c[1].titolo))
    return [
        {"id": c.id, "label": f"{c.codice} · {c.titolo}", "motivo": motivo,
         "validita_mesi": c.validita_mesi, "durata_ore": str(c.durata_ore_teorica or "")}
        for _, c, motivo in candidati[:3]
    ]


def _ente(testo_norm: str) -> str:
    from anagrafica.models import Fornitore
    from anagrafica.models_formazione import TrainingProvider

    for nome in TrainingProvider.objects.filter(is_active=True).values_list("nome", flat=True):
        if contiene_parola(testo_norm, nome):
            return nome
    for nome in Fornitore.objects.filter(is_active=True).values_list("ragione_sociale", flat=True):
        if contiene_parola(testo_norm, nome):
            return nome
    return ""


def _ore(testo_norm: str) -> str:
    m = _ORE_ETICHETTA_RE.search(testo_norm) or _ORE_RE.search(testo_norm)
    if not m:
        return ""
    try:
        valore = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return ""
    return str(valore.normalize()) if 0 < valore <= 500 else ""


def _numero(testo_norm: str) -> str:
    m = _NUMERO_RE.search(testo_norm)
    if not m:
        return ""
    numero = m.group(1).strip(".-/")
    # Una data scambiata per numero non è un numero di attestato.
    return "" if re.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}", numero) else numero


def proponi(lettura: Lettura) -> dict:
    """Campi proposti per registrare l'attestato (nessuna scrittura)."""
    t = lettura.normalizzato
    oggi = timezone.localdate()
    completamento = data_dopo_etichetta(t, _ETICHETTE_COMPLETAMENTO)
    rilascio = data_dopo_etichetta(t, _ETICHETTE_RILASCIO)
    scadenza = data_dopo_etichetta(t, _ETICHETTE_SCADENZA)
    passate = [d for _, d in date_nel_testo(t) if d <= oggi]
    if completamento is None or completamento > oggi:
        completamento = rilascio if rilascio and rilascio <= oggi else (max(passate) if passate else None)
    avvisi = list(lettura.avvisi)
    dipendenti = _dipendenti(t) if t.strip() else []
    corsi = _corsi(t) if t.strip() else []
    if t.strip() and not dipendenti:
        avvisi.append("Nessun dipendente riconosciuto: sceglilo dall'elenco.")
    if t.strip() and not corsi:
        avvisi.append("Nessun corso riconosciuto: sceglilo dall'elenco.")
    return {
        "dipendenti": dipendenti,
        "corsi": corsi,
        "data_completamento": completamento.isoformat() if completamento else "",
        "data_rilascio": rilascio.isoformat() if rilascio else "",
        "data_scadenza_letta": scadenza.isoformat() if scadenza else "",
        "ore": _ore(t),
        "ente": _ente(t) if t.strip() else "",
        "numero": _numero(t),
        "ocr": lettura.ocr,
        "pagine": lettura.pagine,
        "avvisi": avvisi,
        # Il testo letto torna alla pagina per il controllo, con il codice fiscale coperto.
        "testo": re.sub(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b", "[codice fiscale]", lettura.testo[:3000]),
    }
