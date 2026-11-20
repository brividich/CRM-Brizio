"""Controllo «modificato da altri» per i form lunghi di kickoff e incontri.

Due persone sullo stesso incontro: chi salvava per ultimo riscriveva tutto
l'ordine del giorno con quello che aveva in pagina, cancellando le note, le
spunte e i tempi registrati nel frattempo in «Conduci incontro». Ora la pagina
porta con sé l'impronta dei dati che mostra; al salvataggio la si ricalcola sul
database: se è cambiata non si salva niente e si chiede come procedere.

L'impronta copre solo i dati che il form modifica (più gli ``extra`` della
vista): un salvataggio estraneo, come l'avanzamento ricalcolato di una
attività, non fa scattare l'avviso.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time

CAMPO = "impronta"
CAMPO_FORZA = "forza"


def _norm(valore):
    if valore is None:
        return None
    if hasattr(valore, "pk"):
        return valore.pk
    if isinstance(valore, (datetime, date, time)):
        return valore.isoformat()
    if isinstance(valore, (str, int, float, bool)):
        return valore
    if isinstance(valore, dict):
        return {str(k): _norm(v) for k, v in valore.items()}
    if hasattr(valore, "__iter__"):
        elementi = [_norm(v) for v in valore]
        try:
            return sorted(elementi, key=lambda x: json.dumps(x, sort_keys=True, default=str))
        except TypeError:
            return elementi
    return str(valore)


def impronta(form, extra: dict | None = None, escludi: tuple[str, ...] = ()) -> str:
    """Impronta dei valori iniziali di un form non vincolato (più gli extra)."""
    dati = {}
    for nome, field in form.fields.items():
        if nome in escludi:
            continue
        valore = form.get_initial_for_field(field, nome)
        if callable(valore):
            valore = valore()
        if isinstance(valore, str) and nome.endswith("_raw"):
            # JSON (ordine del giorno): confrontato come struttura, non come testo.
            try:
                valore = json.loads(valore or "null")
            except ValueError:
                pass
        dati[nome] = _norm(valore)
    if extra:
        dati["_extra"] = _norm(extra)
    testo = json.dumps(dati, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:24]


def in_conflitto(request, attuale: str) -> bool:
    """True se la pagina era stata aperta su dati poi cambiati da altri.

    Una pagina aperta prima di questo controllo (nessuna impronta) o un
    «Salva comunque» esplicito non vengono fermati.
    """
    inviata = (request.POST.get(CAMPO) or "").strip()
    if not inviata or request.POST.get(CAMPO_FORZA) == "1":
        return False
    return inviata != attuale


def forzato(request) -> bool:
    return request.POST.get(CAMPO_FORZA) == "1" and bool((request.POST.get(CAMPO) or "").strip())
