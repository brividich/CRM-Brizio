"""Export PDF/Excel delle liste dei processi qualificati (MOD.128).

- ``mpq_processi``      → registro processi del cruscotto ``/anagrafica/mod128/`` (filtri ``stato``, ``scad``)
- ``mpq_matrice``       → matrice persone × processi ``/anagrafica/mod128/matrice/`` (``cliente``, ``solo``)
- ``mpq_elenco``        → elenco qualificati di un processo (``processo``)
- ``mpq_registro_righe``→ parti lavorate di un registro utensili MOD.176 (``registro``)

Colonne = quelle a schermo. Gate: chi apre i processi qualificati (lista e permesso MOD.128).
Il dossier completo di un processo (persone, macchine, utensili, Technical Plan) è un export a parte:
``views_mpq.mpq_processo_export``.
"""
from __future__ import annotations

from datetime import timedelta

from django.http import HttpRequest
from django.utils import timezone

from anagrafica.exports import ExportSpec, acl_gate, register

_GATE_LISTA = acl_gate("/anagrafica/mod128/")


def _gate(request: HttpRequest) -> bool:
    from anagrafica.views_mpq import _check_mpq_permission

    return _GATE_LISTA(request) and _check_mpq_permission(request)


def _d(valore) -> str:
    return valore.strftime("%d/%m/%Y") if valore else ""


def _intero(request, nome):
    valore = (request.GET.get(nome) or "").strip()
    return int(valore) if valore.isdigit() else None


# ── Registro processi (cruscotto) ────────────────────────────────────────────
def _processi_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models_mpq import ProcessoQualificato
    from anagrafica.views_mpq import _classifica_scadenza

    oggi = timezone.localdate()
    s30, s60 = oggi + timedelta(days=30), oggi + timedelta(days=60)
    stato = (request.GET.get("stato") or "").strip() if scope == "filtered" else ""
    scad = (request.GET.get("scad") or "").strip() if scope == "filtered" else ""
    righe = []
    for p in (ProcessoQualificato.objects.select_related("cliente")
              .annotate(n_abil=Count("abilitazioni", distinct=True)).order_by("cliente__nome", "nome")):
        scadenza = p.scadenza_effettiva
        classe, _label = _classifica_scadenza(scadenza, oggi, s30, s60)
        if stato and p.stato != stato:
            continue
        if scad == "scaduta" and classe != "scaduta":
            continue
        if scad == "60" and classe not in ("s30", "s60"):
            continue
        righe.append({"cliente": p.cliente.nome if p.cliente_id else "", "processo": p.nome,
                      "sezione": p.sezione_sigla if p.sezione_dedicata else "", "regime": p.get_regime_display(),
                      "livello": p.livello or "", "abilitati": p.n_abil, "scadenza": _d(scadenza),
                      "stato": p.get_stato_display()})
    return righe


def _processi_filtri(request: HttpRequest) -> str:
    from anagrafica.models_mpq import ProcessoQualificato

    stato = dict(ProcessoQualificato.STATO_CHOICES).get((request.GET.get("stato") or "").strip())
    if stato:
        return f"Stato: {stato}"
    return {"scaduta": "Processi scaduti", "60": "In scadenza entro 60 giorni"}.get(
        (request.GET.get("scad") or "").strip(), "")


register(ExportSpec(
    key="mpq_processi",
    title="Registro processi qualificati (MOD.128)",
    sheet_title="Processi",
    columns=[("Cliente/ente", "cliente"), ("Processo", "processo"), ("Sezione", "sezione"), ("Regime", "regime"),
             ("Livello", "livello"), ("Abilitati", "abilitati"), ("Scadenza", "scadenza"), ("Stato", "stato")],
    dataset=_processi_rows,
    filters_label=_processi_filtri,
    permission=_gate,
))


# ── Matrice persone × processi ───────────────────────────────────────────────
def _matrice(request: HttpRequest, scope: str):
    from anagrafica.services.mpq_persone import matrice
    from anagrafica.views_mpq import _nomi_map

    cliente_id = _intero(request, "cliente") if scope == "filtered" else None
    dati = matrice(cliente_id=cliente_id)
    nomi = _nomi_map([r["legacy_id"] for r in dati["righe"] if not r["esterno"]])
    righe = []
    for r in dati["righe"]:
        nome = f"{r['esterno']} (esterno)" if r["esterno"] else nomi.get(r["legacy_id"], f"#{r['legacy_id']}")
        celle = [r["celle"].get(p.pk) for p in dati["processi"]]
        problemi = sum(1 for c in celle if c and not c["operativa"])
        if scope == "filtered" and request.GET.get("solo") == "problemi" and not problemi:
            continue
        riga = {"persona": nome}
        for p, c in zip(dati["processi"], celle, strict=True):
            riga[f"p{p.pk}"] = (c["label"] + (f" · {_d(c['scadenza'])}" if c.get("scadenza") else "")) if c else ""
        righe.append(riga)
    righe.sort(key=lambda r: r["persona"].casefold())
    return dati["processi"], righe


def _matrice_colonne(request: HttpRequest) -> list[tuple[str, str]]:
    from anagrafica.services.mpq_persone import matrice

    scope = (request.GET.get("scope") or "filtered").strip()
    processi = matrice(cliente_id=_intero(request, "cliente") if scope == "filtered" else None)["processi"]
    return [("Persona", "persona")] + [(f"{p.nome} ({p.cliente.nome})" if p.cliente_id else p.nome, f"p{p.pk}")
                                       for p in processi]


register(ExportSpec(
    key="mpq_matrice",
    title="Matrice persone × processi qualificati",
    sheet_title="Matrice",
    columns=[("Persona", "persona")],
    columns_fn=_matrice_colonne,
    dataset=lambda request, scope: _matrice(request, scope)[1],
    filters_label=lambda request: " · ".join(x for x in (
        "Cliente selezionato" if _intero(request, "cliente") else "",
        "Solo persone con problemi" if request.GET.get("solo") == "problemi" else "") if x),
    permission=_gate,
))


# ── Elenco qualificati di un processo ────────────────────────────────────────
def _elenco_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models_mpq import AbilitazioneProcesso, ProcessoQualificato
    from anagrafica.services.mpq_macchine import righe_macchine
    from anagrafica.services.mpq_persone import contesto_processo, stato_persona
    from anagrafica.views_mpq import _nomi_map

    proc = ProcessoQualificato.objects.filter(pk=_intero(request, "processo") or 0).first()
    if proc is None:
        return []
    oggi = timezone.localdate()
    abil = list(proc.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA)
                .prefetch_related("ruoli_processo", "certificazioni"))
    nomi = _nomi_map([a.legacy_anagrafica_id for a in abil])
    ctx = contesto_processo(proc, abil)
    righe = []
    for a in abil:
        st = stato_persona(a, oggi=oggi, contesto=ctx)
        nome = a.nominativo_esterno or nomi.get(a.legacy_anagrafica_id, f"#{a.legacy_anagrafica_id}")
        for ruolo in [r.nome for r in a.ruoli_processo.all()] or ["Senza ruolo"]:
            righe.append({"tipo": "Persona", "gruppo": ruolo, "nome": nome, "stato": st["label"],
                          "scadenza": _d(st.get("scadenza"))})
    righe.sort(key=lambda r: (r["gruppo"].lower(), r["nome"].lower()))
    for r in righe_macchine(proc, oggi=oggi):
        if r["qualifica"] is None:
            continue
        righe.append({"tipo": "Macchina", "gruppo": r["asset"].reparto or "", "nome": f"{r['asset'].asset_tag} — {r['asset'].name}",
                      "stato": r["stato"]["label"], "scadenza": _d(r["stato"].get("scadenza"))})
    return righe


def _elenco_titolo(request: HttpRequest) -> str:
    from anagrafica.models_mpq import ProcessoQualificato

    proc = ProcessoQualificato.objects.filter(pk=_intero(request, "processo") or 0).first()
    return f"Processo: {proc.nome}" if proc else ""


register(ExportSpec(
    key="mpq_elenco",
    title="Elenco qualificati del processo (MOD.128)",
    sheet_title="Elenco qualificati",
    columns=[("Tipo", "tipo"), ("Ruolo / reparto", "gruppo"), ("Persona / macchina", "nome"),
             ("Qualifica", "stato"), ("Scadenza", "scadenza")],
    dataset=_elenco_rows,
    filters_label=_elenco_titolo,
    permission=_gate,
))


# ── Parti lavorate di un registro utensili MOD.176 ───────────────────────────
def _registro_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models_mpq import RegistroUtensile

    reg = RegistroUtensile.objects.filter(pk=_intero(request, "registro") or 0).first()
    if reg is None:
        return []
    return [{"data": _d(r.data), "pn": r.part_number, "op": r.ordine_produzione or "", "seriale": r.seriale or "",
             "quantita": r.quantita, "operatore": r.operatore or "", "note": r.note or ""}
            for r in reg.righe.order_by("data", "id")]


def _registro_titolo(request: HttpRequest) -> str:
    from anagrafica.models_mpq import RegistroUtensile

    reg = RegistroUtensile.objects.filter(pk=_intero(request, "registro") or 0).select_related(
        "passo__revisione__plan").first()
    return f"{reg.identificativo} · P/N {reg.passo.revisione.plan.part_number}" if reg else ""


register(ExportSpec(
    key="mpq_registro_righe",
    title="Registro utensili MOD.176 — parti lavorate",
    sheet_title="MOD.176",
    columns=[("Data", "data"), ("P/N", "pn"), ("OP / commessa", "op"), ("Matricola / seriale", "seriale"),
             ("Quantità", "quantita"), ("Operatore", "operatore"), ("Note", "note")],
    dataset=_registro_rows,
    filters_label=_registro_titolo,
    permission=_gate,
))
