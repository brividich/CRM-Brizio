"""Differenze «prima → dopo» per il registro delle modifiche di kickoff e incontri.

Il registro scriveva solo «Kickoff modificato» (al più i nomi dei campi): per
sapere che cosa era cambiato bisognava chiederlo a chi l'aveva fatto. Qui si
confronta il valore iniziale del form con quello salvato, con le etichette
che l'utente vede in pagina.
"""
from __future__ import annotations

from datetime import date, datetime, time

MAX_VALORE = 160


def _breve(testo: str) -> str:
    testo = " ".join(str(testo).split())
    return testo if len(testo) <= MAX_VALORE else testo[: MAX_VALORE - 1] + "…"


def _valore(field, valore) -> str:
    if valore is None or valore == "" or valore == [] or valore == ():
        return "—"
    if isinstance(valore, bool):
        return "Sì" if valore else "No"
    if isinstance(valore, datetime):
        return valore.strftime("%d/%m/%Y %H:%M")
    if isinstance(valore, date):
        return valore.strftime("%d/%m/%Y")
    if isinstance(valore, time):
        return valore.strftime("%H:%M")
    queryset = getattr(field, "queryset", None)
    etichetta = getattr(field, "label_from_instance", None) or str
    if hasattr(valore, "__iter__") and not isinstance(valore, (str, bytes, dict)):
        elementi = list(valore)
        ids = [e for e in elementi if not hasattr(e, "pk")]
        oggetti = [e for e in elementi if hasattr(e, "pk")]
        if ids and queryset is not None:
            oggetti += list(queryset.model._default_manager.filter(pk__in=ids))
        nomi = sorted(etichetta(o) for o in oggetti)
        return _breve(", ".join(nomi)) if nomi else "—"
    if hasattr(valore, "pk"):
        return _breve(etichetta(valore))
    if queryset is not None and str(valore).isdigit():
        obj = queryset.model._default_manager.filter(pk=valore).first()
        return _breve(etichetta(obj)) if obj else str(valore)
    scelte = getattr(field, "choices", None)
    if scelte:
        try:
            mappa = {str(k): v for k, v in scelte}
        except (TypeError, ValueError):
            mappa = {}
        if str(valore) in mappa:
            return _breve(mappa[str(valore)])
    return _breve(valore)


def differenze_form(form, escludi: tuple[str, ...] = (), etichette: dict[str, str] | None = None) -> dict[str, dict]:
    """{etichetta campo: {"old", "new"}} per i campi davvero cambiati.

    Stessa forma di ``dettaglio["modifiche"]`` dei segnali automatici
    (``core.audit``), con valori già leggibili.
    """
    out: dict[str, dict] = {}
    for nome in form.changed_data:
        if nome in escludi or nome not in form.fields:
            continue
        field = form.fields[nome]
        prima = _valore(field, form.get_initial_for_field(field, nome))
        dopo = _valore(field, form.cleaned_data.get(nome))
        if prima != dopo:
            out[str((etichette or {}).get(nome) or field.label or nome)] = {"old": prima, "new": dopo}
    return out


def differenza_elenco(etichetta: str, prima: list[str], dopo: list[str]) -> dict[str, dict]:
    """Elenchi di nomi (punti ODG, tappe): chi è entrato e chi è uscito."""
    entrati = [x for x in dopo if x not in prima]
    usciti = [x for x in prima if x not in dopo]
    if not entrati and not usciti:
        return {}
    return {etichetta: {
        "old": _breve(", ".join(prima)) or "—",
        "new": _breve(", ".join(dopo)) or "—",
        "aggiunti": entrati,
        "tolti": usciti,
    }}


def differenza_valore(etichetta: str, prima, dopo) -> dict[str, dict]:
    a, b = _valore(None, prima), _valore(None, dopo)
    return {etichetta: {"old": a, "new": b}} if a != b else {}


def righe_modifiche(modifiche) -> list[tuple[str, str]]:
    """Righe «campo: prima → dopo» per il registro del modulo."""
    if not isinstance(modifiche, dict):
        return []
    righe = []
    for campo, diff in modifiche.items():
        if isinstance(diff, dict) and ("old" in diff or "new" in diff):
            if diff.get("aggiunti") or diff.get("tolti"):
                parti = []
                if diff.get("aggiunti"):
                    parti.append("aggiunti: " + ", ".join(map(str, diff["aggiunti"])))
                if diff.get("tolti"):
                    parti.append("tolti: " + ", ".join(map(str, diff["tolti"])))
                testo = "; ".join(parti)
            else:
                testo = f"{diff.get('old') or '—'} → {diff.get('new') or '—'}"
            righe.append((str(campo), _breve(testo)))
        else:
            righe.append((str(campo), _breve(diff)))
    return righe
