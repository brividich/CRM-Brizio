"""Struttura del Mansionario (ruolo → mansione → competenze) e cambio ruoli in blocco.

- «Struttura»: editor unico per ruolo, con ogni mansione modificabile in linea
  (configurazione e competenze insieme), più export/import Excel della stessa
  struttura con anteprima.
- «Cambio ruoli in blocco»: aggiungere, sostituire o chiudere un ruolo per più
  persone, con anteprima.

Cancelli server-side: export per chi vede il Mansionario; tutto il resto per
l'amministrazione dell'anagrafica.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import AreaAziendale, CompetenzaSkm, Mansione, Reparto, RuoloOperativo
from .services import mansionario_struttura as svc
from .views_mansionario import LIVELLO_LABEL, _ids, _int_o_none, _nega, _opzioni_requisiti, _puo_gestire, _puo_vedere

MODULE = "anagrafica"
SESSIONE_IMPORT = "struttura_import_file"
MAX_FILE = 5 * 1024 * 1024
RIGHE_NUOVE = 1  # altre righe con «Aggiungi competenza»


def _is_admin(request) -> bool:
    return _puo_gestire(request)


# ═══════════════════════════════════════════════════════════════════════════
# Pagina «Struttura»
# ═══════════════════════════════════════════════════════════════════════════

def _gruppi() -> list[dict]:
    """Ruolo → mansioni (attive e spente), con i conteggi che servono all'elenco."""
    from django.db.models import Count, Q

    mansioni = list(
        CompetenzaSkm.objects.filter(tipo__in=svc.TIPI_MANSIONE)
        .select_related("asset", "reparto").prefetch_related("ruoli", "mansioni_rischio")
        .annotate(n_comp=Count("competenze", filter=Q(competenze__attiva=True), distinct=True),
                  n_persone=Count("abilitazioni", filter=Q(abilitazioni__in_lista=True), distinct=True))
        .order_by("display", "competenza_key")
    )
    ruoli = list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito", "riporta_a").order_by("nome"))
    per_ruolo: dict[int, list] = {r.pk: [] for r in ruoli}
    senza = []
    for m in mansioni:
        collegati = [r for r in m.ruoli.all() if r.pk in per_ruolo]
        if not collegati:
            senza.append(m)
        for r in collegati:
            per_ruolo[r.pk].append(m)
    gruppi = [{"ruolo": r, "mansioni": per_ruolo[r.pk]} for r in ruoli]
    # Prima i ruoli che hanno mansioni; i ruoli vuoti restano in fondo, compatti.
    gruppi.sort(key=lambda g: (not g["mansioni"], g["ruolo"].nome.casefold()))
    if senza:
        gruppi.append({"ruolo": None, "mansioni": senza})
    return gruppi


def _contesto_pagina(request, **extra) -> dict:
    gruppi = _gruppi()
    tutte = {m.pk: m for g in gruppi for m in g["mansioni"]}.values()
    return {
        "page_title": "Struttura del Mansionario",
        "gruppi": gruppi,
        "kpi": {
            "ruoli": sum(1 for g in gruppi if g["ruolo"] and g["mansioni"]),
            "mansioni": sum(1 for m in tutte if m.attiva),
            "competenze": sum(m.n_comp for m in tutte if m.attiva),
            "senza_competenze": sum(1 for m in tutte if m.attiva and not m.n_comp),
            "senza_ruolo": sum(len(g["mansioni"]) for g in gruppi if g["ruolo"] is None),
        },
        "ruoli_opts": [g["ruolo"] for g in gruppi if g["ruolo"]],
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
        "is_admin": _is_admin(request),
        **extra,
    }


@login_required
def struttura(request):
    if not _is_admin(request):
        return _nega(request, "La struttura del Mansionario la modifica l'amministrazione dell'anagrafica.")
    return render(request, "anagrafica/pages/mansionario_struttura.html", _contesto_pagina(request))


def _righe_da_db(mansione) -> list[dict]:
    from .services import mansionario_competenze as comp_svc
    return [{
        "id": v.pk, "nome": v.nome, "livello_minimo": v.livello_minimo, "bloccante": v.bloccante,
        "corso_id": v.corso_id, "qualifica_id": v.qualifica_id, "processo_id": v.processo_mpq_id,
        "ordine": v.ordine, "togli": False,
    } for v in comp_svc.competenze(mansione)]


def _righe_da_post(request) -> list[dict]:
    righe = []
    for i in range(int(_int_o_none(request.POST.get("n_righe")) or 0)):
        p = f"r{i}_"
        righe.append({
            "id": _int_o_none(request.POST.get(p + "id")),
            "nome": (request.POST.get(p + "nome") or "").strip(),
            "livello_minimo": (request.POST.get(p + "livello_minimo") or "U").strip().upper(),
            "bloccante": request.POST.get(p + "bloccante") == "on",
            "corso_id": _int_o_none(request.POST.get(p + "corso")),
            "qualifica_id": _int_o_none(request.POST.get(p + "qualifica")),
            "processo_id": _int_o_none(request.POST.get(p + "processo")),
            "ordine": _int_o_none(request.POST.get(p + "ordine")) or 0,
            "togli": request.POST.get(p + "togli") == "on",
        })
    return righe


def _render_editor(request, mansione, *, righe=None, config=None, errore="", salvato=""):
    if righe is None:
        righe = _righe_da_db(mansione)
    vuota = {"id": None, "nome": "", "livello_minimo": "U", "bloccante": False, "corso_id": None,
             "qualifica_id": None, "processo_id": None, "ordine": 0, "togli": False}
    righe = [r for r in righe if r.get("id") or r.get("nome")]
    n_salvate = sum(1 for r in righe if r.get("id") and not r.get("togli"))
    righe += [dict(vuota) for _ in range(RIGHE_NUOVE)]
    for i, r in enumerate(righe):
        r["i"] = i
    config = config or {
        "nome": mansione.nome,
        "ruoli": {r.pk for r in mansione.ruoli.all()},
        "rischi": {m.pk for m in mansione.mansioni_rischio.all()},
        "reparto": mansione.reparto_id,
        "area": mansione.area_id,
        "processo": mansione.processo_sgi_id,
        "abilitazione": mansione.abilitazione_con_scadenza,
        "attiva": mansione.attiva,
    }
    from sistema_gestione.models import Processo
    return render(request, "anagrafica/partials/_struttura_mansione.html", {
        "mansione": mansione, "righe": righe, "n_righe": len(righe), "config": config,
        "riga_vuota": {**vuota, "i": "__I__"},
        "errore": errore, "salvato": salvato,
        "nomi_precedenti": svc.nomi_precedenti(mansione),
        "completezza": svc.completezza(mansione, n_competenze=n_salvate,
                                       n_persone=mansione.abilitazioni.filter(in_lista=True).count()),
        "regole": svc.regole_correnti(),
        "livelli_label": list(LIVELLO_LABEL.items()),
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito").order_by("nome")),
        "rischi_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
        "aree_opts": list(AreaAziendale.objects.filter(is_active=True).select_related("reparto")
                          .order_by("reparto__nome", "nome")),
        "processi_opts": list(Processo.objects.filter(attivo=True).order_by("codice")),
        **_opzioni_requisiti(),
    })


@login_required
def struttura_mansione(request, mansione_id: int):
    """Frammento dell'editor: GET lo mostra, POST salva tutto insieme (tutto o niente)."""
    if not _is_admin(request):
        return HttpResponse("Non hai i permessi per modificare il Mansionario.", status=403)
    mansione = get_object_or_404(
        CompetenzaSkm.objects.select_related("asset", "reparto").prefetch_related("ruoli", "mansioni_rischio"),
        pk=mansione_id, tipo__in=svc.TIPI_MANSIONE,
    )
    if request.method != "POST":
        return _render_editor(request, mansione)
    righe = _righe_da_post(request)
    config = {
        "nome": (request.POST.get("nome") or "").strip(),
        "ruoli": set(_ids(request, "ruoli")),
        "rischi": set(_ids(request, "mansioni_rischio")),
        "reparto": _int_o_none(request.POST.get("reparto")),
        "area": _int_o_none(request.POST.get("area")),
        "processo": _int_o_none(request.POST.get("processo_sgi")),
        "abilitazione": request.POST.get("abilitazione_con_scadenza") == "on",
        "attiva": request.POST.get("attiva") == "on",
    }
    try:
        conta = svc.salva_editor(
            mansione, nome=config["nome"], ruoli_ids=config["ruoli"], rischi_ids=config["rischi"],
            reparto_id=config["reparto"], attiva=config["attiva"], righe=righe,
            struttura={"area_id": config["area"], "processo_id": config["processo"],
                       "abilitazione": config["abilitazione"]},
        )
    except ValueError as exc:
        return _render_editor(request, mansione, righe=righe, config=config, errore=f"Niente salvato. {exc}")
    log_action(request, "mansionario_struttura_salva", MODULE, {
        "mansione": mansione.pk, "ruoli": sorted(config["ruoli"]), "mansioni_rischio": sorted(config["rischi"]),
        "attiva": config["attiva"], **conta, "nome": mansione.nome,
    }, oggetto=mansione)
    mansione.refresh_from_db()
    parti = [f"{conta['nuove']} nuove" if conta["nuove"] else "", f"{conta['tolte']} tolte" if conta["tolte"] else ""]
    return _render_editor(request, mansione, salvato="Salvato." + (
        f" Rinominata: prima «{conta['nome_prima']}»." if conta["nome_prima"] else "") + (
        " Competenze: " + ", ".join(p for p in parti if p) + "." if any(parti) else ""))


def _righe_wizard(request) -> list[dict]:
    """Competenze dal wizard: un solo requisito formale per riga, «corso:12», «qualifica:3», «mpq:5»."""
    righe = []
    for i in range(min(int(_int_o_none(request.POST.get("n_righe")) or 0), 60)):
        p = f"r{i}_"
        nome = (request.POST.get(p + "nome") or "").strip()
        if not nome:
            continue
        tipo, _, rid = (request.POST.get(p + "requisito") or "").partition(":")
        rid = _int_o_none(rid)
        righe.append({
            "id": None, "nome": nome,
            "livello_minimo": (request.POST.get(p + "livello_minimo") or "U").strip().upper(),
            "bloccante": request.POST.get(p + "bloccante") == "on",
            "corso_id": rid if tipo == "corso" else None,
            "qualifica_id": rid if tipo == "qualifica" else None,
            "processo_id": rid if tipo == "mpq" else None,
            "requisito": request.POST.get(p + "requisito") or "",
            "ordine": (len(righe) + 1) * 10, "togli": False,
        })
    return righe


def _render_wizard(request, *, dati=None, errore="", passo=1):
    dati = dati or {"nome": "", "ruoli": set(), "reparto": None, "rischi": set(), "righe": []}
    esistenti = list(CompetenzaSkm.objects.filter(tipo__in=svc.TIPI_MANSIONE).values_list("display", flat=True))
    return render(request, "anagrafica/pages/mansionario_nuova.html", {
        "page_title": "Nuova mansione",
        "dati": dati, "errore": errore, "passo": passo,
        "nomi_esistenti": sorted({n.strip() for n in esistenti if n}),
        "livelli_label": list(LIVELLO_LABEL.items()),
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito").order_by("nome")),
        "rischi_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
        "regole": svc.regole_correnti(),
        **_opzioni_requisiti(),
    })


@login_required
def struttura_nuova(request):
    """Wizard «Nuova mansione»: nome → ruoli e reparto → rischio → competenze → riepilogo.

    Un solo POST alla fine; si crea tutto o niente (mansione di tipo processo:
    le macchine nascono dalla skill matrix).
    """
    if not _is_admin(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    if request.method != "POST":
        return _render_wizard(request)
    from django.db import transaction

    righe = _righe_wizard(request)
    dati = {
        "nome": (request.POST.get("nome") or "").strip(),
        "ruoli": set(_ids(request, "ruoli")),
        "reparto": _int_o_none(request.POST.get("reparto")),
        "rischi": set(_ids(request, "mansioni_rischio")),
        "righe": righe,
    }
    passo = 1
    try:
        with transaction.atomic():
            m = svc.crea_processo(dati["nome"], reparto_id=dati["reparto"], ruoli_ids=dati["ruoli"])
            passo = 4
            conta = svc.salva_editor(m, nome=m.nome, ruoli_ids=dati["ruoli"], rischi_ids=dati["rischi"],
                                     reparto_id=dati["reparto"], attiva=True, righe=righe)
    except ValueError as exc:
        return _render_wizard(request, dati=dati, errore=f"Niente creato. {exc}", passo=passo)
    log_action(request, "mansionario_struttura_nuova", MODULE, {
        "mansione": m.pk, "nome": m.nome, "ruoli": sorted(dati["ruoli"]), "reparto": dati["reparto"],
        "mansioni_rischio": sorted(dati["rischi"]), "competenze": conta["nuove"], "da": "wizard",
    }, oggetto=m)
    messages.success(request, f"Mansione «{m.nome}» creata"
                              + (f" con {conta['nuove']} competenz{'a' if conta['nuove'] == 1 else 'e'}" if conta["nuove"] else "")
                              + ": ora aggiungi le persone.")
    return redirect("anagrafica:mansionario_mansione", mansione_id=m.pk)


# ═══════════════════════════════════════════════════════════════════════════
# Export / import Excel
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def struttura_export(request):
    if not _puo_vedere(request):
        return _nega(request)
    from core.excel_export import XLSX_CONTENT_TYPE
    from .services import struttura_excel

    resp = HttpResponse(struttura_excel.esporta_xlsx(), content_type=XLSX_CONTENT_TYPE)
    resp["Content-Disposition"] = f'attachment; filename="struttura-mansionario-{date.today():%Y%m%d}.xlsx"'
    log_action(request, "mansionario_struttura_export", MODULE, {})
    return resp


@login_required
@require_POST
def struttura_import(request):
    if not _is_admin(request):
        return _nega(request, "Non hai i permessi per importare la struttura.")
    from .services import struttura_excel

    azione = request.POST.get("azione")
    if azione == "applica":
        salvato = request.session.get(SESSIONE_IMPORT) or {}
        if not salvato or salvato.get("sha") != request.POST.get("sha"):
            messages.error(request, "Il file della prova non c'è più: ricaricalo e rifai la prova.")
            return redirect(reverse("anagrafica:mansionario_struttura") + "#importa")
        contenuto = base64.b64decode(salvato["dati"])
        nome_file = salvato.get("nome", "")
    else:
        f = request.FILES.get("file")
        if f is None:
            messages.error(request, "Scegli il file Excel.")
            return redirect(reverse("anagrafica:mansionario_struttura") + "#importa")
        if not f.name.lower().endswith(".xlsx"):
            messages.error(request, "Serve un file .xlsx (Excel).")
            return redirect(reverse("anagrafica:mansionario_struttura") + "#importa")
        if f.size > MAX_FILE:
            messages.error(request, "Il file supera i 5 MB.")
            return redirect(reverse("anagrafica:mansionario_struttura") + "#importa")
        contenuto, nome_file = f.read(), f.name
    try:
        esito = struttura_excel.importa(contenuto, applica=azione == "applica")
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("anagrafica:mansionario_struttura") + "#importa")
    sha = hashlib.sha256(contenuto).hexdigest()
    if esito.applicato:
        request.session.pop(SESSIONE_IMPORT, None)
        log_action(request, "mansionario_struttura_import", MODULE, {
            "file": nome_file[:120], "sha256": sha, "conteggi": esito.conteggi(), "errori": esito.errori,
        })
        messages.success(request, f"Struttura importata: {esito.cambi} righe registrate"
                                  + (f", {esito.errori} scartate." if esito.errori else "."))
    else:
        request.session[SESSIONE_IMPORT] = {"sha": sha, "nome": nome_file[:120],
                                            "dati": base64.b64encode(contenuto).decode()}
    righe = sorted(esito.righe, key=lambda r: ({"errore": 0, "nuovo": 1, "modificato": 2}.get(r.azione, 3),
                                               r.foglio, r.numero))
    return render(request, "anagrafica/pages/mansionario_struttura.html", _contesto_pagina(
        request, esito=esito, esito_righe=righe, esito_conteggi=esito.conteggi(), sha=sha, nome_file=nome_file,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Cambio ruoli in blocco
# ═══════════════════════════════════════════════════════════════════════════

def _data(valore):
    try:
        return date.fromisoformat((valore or "").strip())
    except ValueError:
        return None


@login_required
def ruoli_in_blocco(request):
    if not _is_admin(request):
        return _nega(request, "Il cambio ruoli in blocco è dell'amministrazione dell'anagrafica.")
    from django.utils import timezone

    from .services import ruoli_in_blocco as blocco

    sorgente = request.POST if request.method == "POST" else request.GET
    filtri = {
        "reparto": (sorgente.get("reparto") or "").strip(),
        "ruolo_id": _int_o_none(sorgente.get("filtro_ruolo")),
        "cerca": (sorgente.get("cerca") or "").strip(),
    }
    scelta = {
        "ruolo_id": _int_o_none(sorgente.get("ruolo")),
        "modo": sorgente.get("modo") or blocco.AGGIUNGI,
        "data": sorgente.get("data") or timezone.localdate().isoformat(),
        "note": (sorgente.get("note") or "").strip()[:500],
        "persone": set(_ids(request, "persone")) if request.method == "POST" else set(),
    }
    esiti, applicato = None, False
    if request.method == "POST":
        ruolo = RuoloOperativo.objects.filter(pk=scelta["ruolo_id"]).select_related("ambito").first()
        applica = request.POST.get("azione") == "applica"
        if ruolo is None:
            messages.error(request, "Scegli il ruolo.")
        else:
            try:
                esiti = blocco.esegui(scelta["persone"], ruolo=ruolo, modo=scelta["modo"], data=_data(scelta["data"]),
                                      note=scelta["note"], user=request.user, applica=applica)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                applicato = applica
                if applica:
                    fatti = sum(1 for e in esiti if e.azione == "cambia")
                    errori = sum(1 for e in esiti if e.azione == "errore")
                    log_action(request, "ruoli_in_blocco", MODULE, {
                        "ruolo": ruolo.pk, "modo": scelta["modo"], "data": scelta["data"],
                        "persone": sorted(scelta["persone"]), "registrati": fatti, "errori": errori,
                    }, oggetto=ruolo)
                    messages.success(request, f"{fatti} persone aggiornate" + (f", {errori} con errore." if errori else "."))
    persone = blocco.persone(reparto=filtri["reparto"], ruolo_id=filtri["ruolo_id"], cerca=filtri["cerca"])
    return render(request, "anagrafica/pages/ruoli_in_blocco.html", {
        "page_title": "Cambio ruoli in blocco",
        "persone": persone,
        "filtri": filtri,
        "scelta": scelta,
        "esiti": esiti,
        "applicato": applicato,
        "modi": list(blocco.MODI.items()),
        "max_persone": blocco.MAX_PERSONE,
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito").order_by("nome")),
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
    })
