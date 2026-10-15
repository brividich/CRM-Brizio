"""Import di piu' fatture fornitore in una volta: lettura, anteprima, salvataggio.

I file non vengono conservati: si leggono, i dati estratti restano in sessione fino
alla conferma e ogni fattura si salva con gli stessi form della pagina «Nuova
fattura» (stessi controlli: numero gia' presente nel trimestre, contratto
sconosciuto, chiusura fuori trimestre). Una fattura con avvisi non e' selezionata
in automatico: si apre e si controlla prima di salvarla.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction

from .fattura_import import MAX_BYTES, FatturaNonLeggibile, leggi_fattura
from .models import Fattura

MAX_FILE = 30
CHIAVE_SESSIONE = "contatori_import_fatture"
CONTATORI_RIGA = ("a4_bn", "a3_bn", "a4_col", "a3_col")
CAMPI_RIGA = ("contratto", "descrizione", *CONTATORI_RIGA)

PRONTA, DA_VERIFICARE, GIA_PRESENTE, NON_LEGGIBILE = "pronta", "da_verificare", "gia_presente", "non_leggibile"


def _iso(valore):
    return valore.isoformat() if isinstance(valore, date) else (valore or "")


def leggi_file(files) -> list[dict]:
    """Legge ogni file caricato: [{file, testata, righe, avvisi, errore}] serializzabile."""
    voci = []
    for caricato in list(files)[:MAX_FILE]:
        voce = {"file": caricato.name[:120], "testata": {}, "righe": [], "avvisi": [], "errore": ""}
        try:
            if caricato.size > MAX_BYTES:
                raise FatturaNonLeggibile("file troppo grande (massimo 5 MB)")
            letta = leggi_fattura(caricato.name, caricato.read())
        except FatturaNonLeggibile as e:
            voce["errore"] = str(e)
        else:
            voce["testata"] = {k: _iso(v) for k, v in letta["testata"].items()}
            voce["righe"] = [{"contratto": r.get("contratto", ""), "descrizione": r.get("descrizione", ""),
                              **{c: int(r.get(c) or 0) for c in CONTATORI_RIGA}}
                             for r in letta["righe"]]
            voce["avvisi"] = list(letta["avvisi"])
        voci.append(voce)
    return voci


def classifica(voci: list[dict]) -> list[dict]:
    """Aggiunge a ogni voce `stato`, `indice` e i totali per l'anteprima."""
    visti = set()
    for i, voce in enumerate(voci):
        voce["indice"] = i
        t = voce["testata"]
        chiave = (t.get("numero"), t.get("trimestre"))
        if voce["errore"]:
            voce["stato"] = NON_LEGGIBILE
        elif chiave in visti or (all(chiave) and Fattura.objects.filter(
                numero=chiave[0], trimestre=chiave[1]).exists()):
            voce["stato"] = GIA_PRESENTE
        elif voce["avvisi"] or not all(chiave):
            voce["stato"] = DA_VERIFICARE
        else:
            voce["stato"] = PRONTA
        if all(chiave):
            visti.add(chiave)
        voce["date"] = {k: date.fromisoformat(t[k]).strftime("%d/%m/%Y")
                        for k in ("data", "periodo_dal", "periodo_al") if t.get(k)}
        voce["contratti"] = len(voce["righe"])
        voce["copie"] = sum(int(r.get(c) or 0) for r in voce["righe"]
                            for c in CONTATORI_RIGA)
    return voci


def dati_form(voce: dict) -> tuple[dict, list[dict]]:
    """(initial della testata, initial delle righe) per precompilare «Nuova fattura»."""
    testata = {k: v for k, v in voce["testata"].items() if v}
    for campo in ("data", "periodo_dal", "periodo_al"):
        if testata.get(campo):
            testata[campo] = date.fromisoformat(testata[campo])
    return testata, [dict(r) for r in voce["righe"]]


def salva(voce: dict):
    """Salva una fattura letta con i form della pagina. Ritorna (fattura, errori)."""
    from .forms import FatturaForm, RigaFatturaForm

    testata = {campo: voce["testata"].get(campo) or "" for campo in FatturaForm.Meta.fields}
    form = FatturaForm(data=testata)
    righe = [RigaFatturaForm(data={c: r.get(c, "") for c in CAMPI_RIGA}) for r in voce["righe"]
             if any(int(r.get(c) or 0) for c in CONTATORI_RIGA)]
    errori = []
    if not form.is_valid():
        errori += [f"{form.fields[c].label if c in form.fields else c}: {' '.join(e)}"
                   for c, e in form.errors.items()]
    for riga in righe:
        if not riga.is_valid():
            contratto = riga.data.get("contratto") or "?"
            errori += [f"contratto {contratto}: {' '.join(e)}" for e in riga.errors.values()]
    if not righe:
        errori.append("nessuna riga con letture")
    if errori:
        return None, errori
    with transaction.atomic():
        fattura = form.save()
        for riga in righe:
            riga.instance.fattura = fattura
            riga.save()
    return fattura, []
