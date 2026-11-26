"""Ordini di produzione: elenco degli OP, scheda con i documenti di produzione, impostazioni."""
from __future__ import annotations

import os
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import ordini_produzione as op_db
from tasks.identity import normalize_part_number
from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.paginazione import pagina_elenco
from tasks.tech_paths import normalizza_percorso

from . import guida as guida_mod
from . import nuovo_op, services
from . import report_cmm_indice as cmm
from . import report_cmm_pagine as pagine_cmm
from .acl_bootstrap import PERM_ARTICOLI, PERM_DOCUMENTI, PERM_IMPOSTAZIONI, PERM_QUOTE
from .models import (
    ArticoloPN,
    AliasQuotaCMM, CartellaReportCMM, DocumentoOP, ImpostazioniQuoteCMM, NotaQuotaCMM, ReportCMM, TipoDocumento,
)


def _richiede(request, codice: str) -> None:
    """Oltre al cancello del middleware: chi scrive deve avere il permesso, sempre."""
    if not request_has_permission_code(request, codice):
        raise PermissionDenied


def _ctx(request, corrente: str, **extra) -> dict:
    return {
        "page_title": "Ordini di produzione",
        "prod_corrente": corrente,
        "prod_puo_documenti": request_has_permission_code(request, PERM_DOCUMENTI),
        "prod_puo_impostazioni": request_has_permission_code(request, PERM_IMPOSTAZIONI),
        "prod_puo_quote": request_has_permission_code(request, PERM_QUOTE),
        **extra,
    }


@login_required
@require_GET
def elenco(request):
    testo = (request.GET.get("q") or "").strip()
    stato = (request.GET.get("stato") or "").strip()
    disponibile = op_db.disponibile()
    manca = (request.GET.get("manca") or "").strip()
    righe = services.righe_elenco(request, testo, stato) if disponibile else []
    vede_kickoff = services._vede_kickoff(request)
    chips = services.conteggi_manca(righe, vede_kickoff)
    if manca not in {c["chiave"] for c in chips}:
        manca = ""
    righe_filtrate = services.filtra_manca(righe, manca)
    return render(request, "produzione/elenco.html", _ctx(
        request, "elenco", disponibile=disponibile, pagina=pagina_elenco(request, righe_filtrate),
        totale=len(righe_filtrate), totale_tutti=len(righe), chips=chips, manca=manca, vede_kickoff=vede_kickoff,
        q=testo, stato=stato, stati=op_db.stati() if disponibile else [], nuovo_op=nuovo_op.contesto(request),
    ))


@login_required
@require_GET
def pn_elenco(request):
    """Catalogo dei P/N: tutti gli articoli (OP, KICK-OFF, cartelle Collaudo) con riepilogo, filtri e ordine."""
    testo = (request.GET.get("q") or "").strip()
    vede_kickoff = services._vede_kickoff(request)
    dati = services.catalogo(request, testo, request.GET.get("mostra") or request.GET.get("manca", ""),
                             request.GET.get("cliente", ""), request.GET.get("ordina", ""))
    from datetime import timedelta

    report_mese = ReportCMM.objects.filter(righe__gt=0, escluso=False, data__gte=timezone.localdate() - timedelta(days=30)).count()
    filtro = {k: v for k, v in (("q", testo), ("mostra", dati["mostra"]), ("cliente", dati["cliente"]), ("ordina", dati["ordina"])) if v}
    return render(request, "produzione/pn_elenco.html", _ctx(
        request, "pn", pagina=pagina_elenco(request, dati["righe"]), totale=len(dati["righe"]), q=testo,
        conta=dati["conta"], mostra=dati["mostra"], clienti=dati["clienti"], cliente=dati["cliente"], ordina=dati["ordina"],
        aggiornato=dati["aggiornato"], report_mese=report_mese, vede_kickoff=vede_kickoff,
        chips_mostra=[{"chiave": k, "nome": v, "n": dati["conta"][k]} for k, v in services.MOSTRA_CATALOGO
                      if k != "senza_fai" or vede_kickoff],
        scelte_ordina=services.ORDINA_CATALOGO,
        query_filtri=urlencode({k: v for k, v in filtro.items() if k != "mostra"}), query_pagina=urlencode(filtro),
        puo_articoli=request_has_permission_code(request, PERM_ARTICOLI),
    ))


@login_required
@require_POST
def pn_sincronizza(request):
    """«Aggiorna il catalogo»: articoli nuovi dalle fonti e riepilogo (Cpk per 60 secondi al massimo)."""
    _richiede(request, PERM_ARTICOLI)
    from . import articoli

    esito = articoli.sincronizza(con_cpk_secondi=60)
    log_action(request, "produzione_articoli_sincronizza", "produzione", esito)
    messages.success(request, f"Catalogo aggiornato: {esito['articoli']} P/N, {esito['creati']} nuovi.")
    return redirect("produzione:pn_elenco")


class ArticoloForm(forms.ModelForm):
    class Meta:
        model = ArticoloPN
        fields = ("descrizione", "cliente", "disegno", "revisione", "materiale", "famiglia", "stato", "note")


@login_required
@require_POST
def pn_anagrafica(request, pn: str):
    """Salva l'anagrafica del P/N dal pannello «Anagrafica» della scheda."""
    _richiede(request, PERM_ARTICOLI)
    pn = normalize_part_number(pn)
    articolo, _ = ArticoloPN.objects.get_or_create(pn=pn, defaults={"origine": "manuale"})
    prima = {f: getattr(articolo, f) for f in ArticoloForm.Meta.fields}
    form = ArticoloForm(request.POST, instance=articolo)
    if not form.is_valid():
        messages.error(request, "Anagrafica non salvata: " + "; ".join(f"{k}: {' '.join(v)}" for k, v in form.errors.items()))
        return redirect(services.url_pn(pn))
    articolo = form.save(commit=False)
    articolo.modificato_da = request.user
    articolo.save()
    cambi = {f: [prima[f], getattr(articolo, f)] for f in prima if prima[f] != getattr(articolo, f)}
    log_action(request, "produzione_articolo_salva", "produzione", {"pn": pn, "cambi": cambi})
    messages.success(request, "Anagrafica del P/N salvata.")
    return redirect(services.url_pn(pn))


def _periodo(request):
    """``?da=AAAA-MM-GG&a=AAAA-MM-GG`` (dalla mappa di Quote CMM), altrimenti ``None``."""
    from datetime import date

    try:
        da, a = date.fromisoformat(request.GET.get("da", "")), date.fromisoformat(request.GET.get("a", ""))
    except ValueError:
        return None
    return (da, a) if da <= a else None


@login_required
@require_GET
def pn_scheda(request, pn: str | None = None):
    """Scheda del P/N a sezioni (``?sez=``). L'indirizzo vecchio ``/pn/scheda/?pn=`` porta a quello stabile."""
    if pn is None:
        vecchio = (request.GET.get("pn") or "").strip()
        if not vecchio:
            raise Http404
        return redirect(services.url_pn(normalize_part_number(vecchio), request.GET.get("sez", "")), permanent=True)
    if not op_db.disponibile():
        raise Http404
    dati = services.scheda_pn(request, pn)
    if dati is None:
        raise Http404
    sezioni = dict(services.SEZIONI_PN)
    sezione = request.GET.get("sez", "")
    if sezione not in sezioni:
        sezione = ""
    conta = {"op": len(dati["ops"]), "report": dati["report_cmm"]["n"], "programmi": len(dati["programmi"]),
             "fai": len(dati["fai_pn"])}
    if sezione == "report":
        qs = cmm.ReportCMM.objects.filter(pn=dati["pn"], righe__gt=0, escluso=False)
        periodo = _periodo(request)
        if periodo:
            qs = qs.filter(data__gte=periodo[0], data__lte=periodo[1])
            dati["periodo"] = periodo
        dati["report_cmm"]["ultimi"] = list(qs.order_by("-data", "-id")[:60])
        dati["programmi_cmm"] = cmm.programmi_del_pn(dati["pn"])
    if sezione == "qualita":
        dati["qualita"] = pagine_cmm.qualita_pn(dati["pn"], request.GET.get("q", ""))
        dati["vista_qualita"] = "tabella" if request.GET.get("vista") == "tabella" else "carta"
    tab = [{"chiave": k, "nome": v, "n": conta.get(k), "url": services.url_pn(dati["pn"], k)}
           for k, v in services.SEZIONI_PN
           if k in ("", "op", "report") or (k == "qualita" and dati["report_cmm"]["n"]) or (k in ("programmi", "fai") and dati["vede_kickoff"])]
    return render(request, "produzione/pn_scheda.html", _ctx(
        request, "pn", sezione=sezione, sezioni=tab, puo_articoli=request_has_permission_code(request, PERM_ARTICOLI),
        form_articolo=ArticoloForm(instance=dati["articolo"]) if dati["articolo"] else ArticoloForm(), **dati))


@login_required
@require_GET
def pn_quote(request):
    """Analisi quote del P/N: la pagina si disegna nel browser con i dati di ``api_quote``."""
    from tasks.identity import normalize_part_number

    pn = normalize_part_number(request.GET.get("pn") or "")
    if not pn:
        raise Http404
    programmi = cmm.programmi_del_pn(pn)
    prog = (request.GET.get("prog") or "").strip()
    if prog not in {p["programma_base"] for p in programmi}:
        prog = programmi[0]["programma_base"] if programmi else ""
    stato = {k: (request.GET.get(k) or "").strip()[:2000] for k in ("q", "nom", "r", "tab", "per", "da", "a", "op", "cmp", "f", "ord",
                                                                   "rs", "tutte", "esclusi")}
    stato["prog"] = prog
    return render(request, "produzione/quote.html", _ctx(
        request, "pn", pn=pn, programmi=programmi, prog=prog, stato=stato,
        cartella=CartellaReportCMM.objects.filter(pn=pn).order_by("-letta_il").first(), attivo=cmm.attivo(),
    ))


def _data_get(request, chiave: str):
    from datetime import date

    try:
        return date.fromisoformat((request.GET.get(chiave) or "").strip()[:10])
    except ValueError:
        return None


@require_GET
def api_quote(request):
    """Misure di un programma del P/N in JSON (pagina «Analisi quote»). Risponde sempre in JSON."""
    from tasks.identity import normalize_part_number

    # Il permesso «Elenco e scheda OP» lo controlla il middleware ACL (rotta legata, risposta JSON sotto /api/).
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    pn = normalize_part_number(request.GET.get("pn") or "")
    prog = (request.GET.get("prog") or "").strip()[:200]
    if not pn or not prog:
        return JsonResponse({"ok": False, "error": "Servono P/N e programma."}, status=400)
    dati = cmm.dati_programma(pn, prog, _data_get(request, "da"), _data_get(request, "a"))
    return JsonResponse({"ok": True, **dati})


def _json_corpo(request) -> dict:
    import json

    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _json_err(msg: str, status: int = 400):
    return JsonResponse({"ok": False, "error": msg}, status=status)


@require_GET
def api_quote_candidati(request):
    """Tutte le quote dei programmi del P/N, per «È la stessa quota di…»."""
    from django.db.models import Max

    from tasks.identity import normalize_part_number

    if not request.user.is_authenticated:
        return _json_err("Autenticazione richiesta.", 401)
    pn = normalize_part_number(request.GET.get("pn") or "")
    if not pn:
        return _json_err("Serve il P/N.")
    from .models import MisuraCMM

    righe = (MisuraCMM.objects.filter(report__pn=pn, report__righe__gt=0)
             .values("report__programma_base", "chiave", "nominale").annotate(nome=Max("nome"), tol_sup=Max("tol_sup"),
                                                                             tol_inf=Max("tol_inf"))
             .order_by("report__programma_base", "chiave")[:3000])
    return JsonResponse({"ok": True, "quote": [
        {"prog": r["report__programma_base"], "id": cmm.id_quota(r["chiave"], r["nominale"]), "nome": r["nome"],
         "nominale": r["nominale"], "ts": r["tol_sup"], "ti": r["tol_inf"]} for r in righe]})


@require_POST
def api_quote_nota(request):
    """Nota su una quota (evento sul grafico) dal report indicato."""
    from tasks.identity import normalize_part_number

    if not request.user.is_authenticated:
        return _json_err("Autenticazione richiesta.", 401)
    d = _json_corpo(request)
    pn = normalize_part_number(d.get("pn") or "")
    testo = str(d.get("testo") or "").strip()[:160]
    report = ReportCMM.objects.filter(pk=d.get("report"), pn=pn).first() if str(d.get("report") or "").isdigit() else None
    if not pn or not testo or report is None:
        return _json_err("Servono il testo e il S/N da cui vale la nota.")
    nota = NotaQuotaCMM.objects.create(pn=pn, programma_base=str(d.get("prog") or report.programma_base)[:200],
                                       quota=str(d.get("quota") or "")[:230], report=report, testo=testo,
                                       creato_da=request.user)
    log_action(request, "produzione_quota_nota", "produzione", {"pn": pn, "quota": nota.quota, "testo": testo})
    return JsonResponse({"ok": True, "id": nota.pk})


@require_POST
def api_quote_nota_elimina(request, pk: int):
    if not request.user.is_authenticated:
        return _json_err("Autenticazione richiesta.", 401)
    nota = NotaQuotaCMM.objects.filter(pk=pk).first()
    if nota is None:
        return _json_err("Nota non trovata.", 404)
    if nota.creato_da_id != request.user.pk and not request_has_permission_code(request, PERM_QUOTE):
        return _json_err("Solo chi l'ha scritta (o chi gestisce le quote) può togliere la nota.", 403)
    log_action(request, "produzione_quota_nota_elimina", "produzione", {"pn": nota.pn, "testo": nota.testo})
    nota.delete()
    return JsonResponse({"ok": True})


@require_POST
def api_quote_alias(request):
    """Unisce la quota d'origine (anche di un altro programma del P/N) alla quota di destinazione."""
    from tasks.identity import normalize_part_number

    if not request.user.is_authenticated:
        return _json_err("Autenticazione richiesta.", 401)
    if not request_has_permission_code(request, PERM_QUOTE):
        return _json_err("Serve il permesso «Gestire le quote CMM».", 403)
    d = _json_corpo(request)
    pn = normalize_part_number(d.get("pn") or "")
    campi = {k: str(d.get(k) or "").strip()[:230] for k in ("prog_origine", "quota_origine", "prog_destinazione", "quota_destinazione")}
    if not pn or not all(campi.values()):
        return _json_err("Mancano le quote da unire.")
    if (campi["prog_origine"], campi["quota_origine"]) == (campi["prog_destinazione"], campi["quota_destinazione"]):
        return _json_err("È la stessa quota.")
    if AliasQuotaCMM.objects.filter(pn=pn, prog_origine=campi["prog_destinazione"], quota_origine=campi["quota_destinazione"]).exists():
        return _json_err("La quota di destinazione è già unita a un'altra: scegli quella.")
    al, _ = AliasQuotaCMM.objects.update_or_create(
        pn=pn, prog_origine=campi["prog_origine"], quota_origine=campi["quota_origine"],
        defaults={"prog_destinazione": campi["prog_destinazione"], "quota_destinazione": campi["quota_destinazione"],
                  "creato_da": request.user})
    log_action(request, "produzione_quota_unisci", "produzione", {"pn": pn, **campi})
    return JsonResponse({"ok": True, "id": al.pk})


@require_POST
def api_quote_alias_elimina(request, pk: int):
    if not request.user.is_authenticated:
        return _json_err("Autenticazione richiesta.", 401)
    if not request_has_permission_code(request, PERM_QUOTE):
        return _json_err("Serve il permesso «Gestire le quote CMM».", 403)
    al = AliasQuotaCMM.objects.filter(pk=pk).first()
    if al is None:
        return _json_err("Unione non trovata.", 404)
    log_action(request, "produzione_quota_separa", "produzione", {"pn": al.pn, "origine": al.quota_origine,
                                                                   "destinazione": al.quota_destinazione})
    al.delete()
    return JsonResponse({"ok": True})


MOTIVI_ESCLUSIONE = (
    "Rilavorazione: conta la misura dopo",
    "Misura di prova / programma in messa a punto",
    "Doppione dello stesso report",
    "Pezzo scartato",
    "Altro",
)


@login_required
@require_POST
def report_escludi(request, pk: int):
    """Esclude il report dall'analisi (o lo riammette). Il PDF resta dov'è."""
    _richiede(request, PERM_QUOTE)
    report = get_object_or_404(ReportCMM, pk=pk)
    if request.POST.get("azione") == "riammetti":
        report.escluso, report.escluso_motivo, report.escluso_nota = False, "", ""
        report.escluso_da, report.escluso_il = request.user, timezone.now()
        messages.success(request, f"{report.seriale or report.file} di nuovo nell'analisi.")
    else:
        motivo = (request.POST.get("motivo") or "").strip()
        report.escluso = True
        report.escluso_motivo = motivo if motivo in MOTIVI_ESCLUSIONE else "Altro"
        report.escluso_nota = (request.POST.get("nota") or "").strip()[:300]
        report.escluso_da, report.escluso_il = request.user, timezone.now()
        messages.success(request, f"{report.seriale or report.file} escluso dall'analisi.")
    report.save(update_fields=["escluso", "escluso_motivo", "escluso_nota", "escluso_da", "escluso_il"])
    log_action(request, "produzione_report_cmm_escludi", "produzione",
               {"id": report.pk, "file": report.file, "escluso": report.escluso, "motivo": report.escluso_motivo})
    return redirect("produzione:report_cmm", report.pk)


@login_required
@require_GET
def quote_cruscotto(request):
    """Quote CMM di tutti i P/N, dalla situazione più grave."""
    righe = cmm.cruscotto()
    filtro = request.GET.get("f") or "guardare"
    visibili = [r for r in righe if r["da_guardare"]] if filtro == "guardare" else righe
    return render(request, "produzione/quote_cruscotto.html", _ctx(
        request, "quote", righe=visibili, filtro=filtro, n_guardare=sum(1 for r in righe if r["da_guardare"]), n_tutti=len(righe),
        settimane=cmm.settimane_mappa(), quote_guardare=cmm.quote_da_guardare_tutte([r["pn"] for r in righe if r["da_guardare"]]),
        tot={"pn": len(righe), "fuori": sum(1 for r in righe if r["fuori_rec"]), "cpk": sum(r["cpk_bassi"] for r in righe),
             "deriva": sum(r["deriva"] for r in righe)},
        oggi=ReportCMM.objects.filter(letto_il__date=timezone.localdate(), righe__gt=0).count(), attivo=cmm.attivo(),
    ))


@login_required
@require_GET
def quote_pdf(request):
    """PDF «Studio di capacità» con i filtri della pagina Analisi quote."""
    from datetime import date, timedelta

    from tasks.identity import normalize_part_number

    from . import pdf_capacita

    pn = normalize_part_number(request.GET.get("pn") or "")
    prog = (request.GET.get("prog") or "").strip()[:200]
    if not pn or not prog:
        raise Http404
    da, a = _data_get(request, "da"), _data_get(request, "a")
    per = request.GET.get("per") or ""
    if per.isdigit():
        da, a = timezone.localdate() - timedelta(days=int(per)), None
    dati = cmm.dati_programma(pn, prog, da, a)
    op = {x for x in (request.GET.get("op") or "").split("~") if x}
    tieni = None
    if request.GET.get("tutte") != "1":
        tieni = set(cmm.ultima_per_seriale(dati["report"]))
    scelti = [int(x) for x in (request.GET.get("rs") or "").split("~") if x.isdigit()]
    if scelti:
        ids = set(scelti)
        tieni = {i for i in (tieni if tieni is not None else range(len(dati["report"]))) if dati["report"][i][0] in ids}
    quote = {x for x in (request.GET.get("quote") or "").split("~") if x}
    righe = pdf_capacita.righe_capacita(dati, quote or None, op, tieni)
    date_rep = [r[3] for r in dati["report"] if r[3]]
    filtri = " · ".join(filter(None, [
        f"{date.fromisoformat(min(date_rep)):%d/%m/%Y}–{date.fromisoformat(max(date_rep)):%d/%m/%Y}" if date_rep else "",
        f"OP {', '.join(sorted(op))}" if op else "tutti gli OP",
        (f"{len(quote)} quote scelte" if len(quote) > 1 else "1 quota scelta") if quote else f"{len(righe)} quote",
        "ultima misura per S/N" if request.GET.get("tutte") != "1" else "tutte le misure",
    ]))
    contenuto = pdf_capacita.genera(pn, dati, righe, filtri, request.user.get_full_name() or request.user.get_username())
    log_action(request, "produzione_quote_pdf", "produzione", {"pn": pn, "prog": prog, "quote": len(righe)})
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="Capacita_{pn}_{prog}.pdf"'
    return resp


@login_required
@require_POST
def pn_leggi_report(request):
    """Accoda la lettura dei report CMM della cartella del P/N."""
    from tasks.identity import normalize_part_number

    pn = normalize_part_number(request.POST.get("pn") or "")
    if not pn or not cmm.attivo():
        raise Http404
    from .tasks import accoda_lettura_pn

    if accoda_lettura_pn(pn):
        log_action(request, "produzione_report_cmm_leggi", "produzione", {"pn": pn})
        messages.success(request, "Lettura dei report avviata: ricarica la pagina tra qualche minuto.")
    else:
        messages.info(request, "La lettura dei report di questo P/N è già in corso.")
    return redirect(f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn})}")


@login_required
@require_GET
def report_cmm(request, pk: int):
    """Un report CMM come protocollo: testata con l'esito, quote per gruppo del report con grafico di deviazione,
    pannello di dettaglio della quota scelta (andamento sugli ultimi 30 pezzi, Cpk, deriva); pezzo prima / dopo,
    confronti pronti e link all'anomalia."""
    report = get_object_or_404(ReportCMM, pk=pk)
    dati = pagine_cmm.righe_report(report)
    filtro = request.GET.get("f", "")
    righe = dati["righe"]
    if filtro == "fuori":
        righe = [r for r in righe if r["m"].fuori or r["m"].da_verificare]
    elif filtro == "limite":
        righe = [r for r in righe if r["limite"] or r["m"].fuori]
    elif filtro == "cambiate":
        righe = [r for r in righe if r["delta"] is not None and r["m"].tol_sup != r["m"].tol_inf
                 and abs(r["delta"]) / (r["m"].tol_sup - r["m"].tol_inf) > pagine_cmm.SOGLIA_CAMBIO]
    else:
        filtro = ""
    op = op_db.per_titolo(report.op) if report.op and op_db.disponibile() else None
    url_anomalia = ""
    if op:
        url_anomalia = f"{reverse('apertura_segnalazione')}?{urlencode({'op_id': op['id'], 'report_cmm': report.pk})}"
    conta = dati["conta"]
    if not report.righe:
        esito = ("vuoto", "—")
    elif report.escluso:
        esito = ("escluso", "ESCLUSO")
    elif conta["fuori"]:
        esito = ("nok", "NOK")
    elif conta["verifica"]:
        esito = ("verifica", "DA VERIFICARE")
    else:
        esito = ("ok", "OK")
    return render(request, "produzione/report_cmm.html", _ctx(
        request, "pn", report=report, righe=righe, gruppi=pagine_cmm.gruppi(righe), esito=esito,
        pannello=pagine_cmm.pannello(righe, report), conta=conta, filtro=filtro, prima=dati["prima"],
        dopo=dati["dopo"], proposte=pagine_cmm.proposte(report), op=op, motivi=MOTIVI_ESCLUSIONE,
        url_anomalia=url_anomalia,
        altri=[r for r in pagine_cmm.report_del_pezzo(report.pn, report.seriale) if r.pk != report.pk][:20] if report.seriale else [],
    ))


@login_required
@require_GET
def report_confronta(request):
    """Da 2 a 6 report affiancati, quota per quota (``?r=<id>&r=<id>…``); ``formato=csv`` per Excel."""
    reports = pagine_cmm.report_da_confrontare(request.GET.getlist("r"))
    solo = request.GET.get("solo") == "1"
    if len(reports) < 2:
        messages.info(request, "Per confrontare servono almeno due report: spunta le righe nell'elenco e premi «Confronta».")
        if reports:
            return redirect("produzione:report_cmm", reports[0].pk)
        return redirect("produzione:quote_cruscotto")
    dati = pagine_cmm.confronta(reports, solo_cambiate=solo)
    if request.GET.get("formato") == "csv":
        import csv

        risposta = HttpResponse(content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = 'attachment; filename="confronto_report_cmm.csv"'
        risposta.write("﻿")
        w = csv.writer(risposta, delimiter=";")
        w.writerow(["Quota", "Nominale", "Limite inferiore", "Limite superiore"]
                   + [f"{r.seriale or r.file} {r.data:%d/%m/%Y}" if r.data else (r.seriale or r.file) for r in reports]
                   + ["Differenza ultimo-primo", "% tolleranza"])
        num = lambda v: "" if v is None else f"{v:.4f}".replace(".", ",")
        for riga in dati["righe"]:
            w.writerow([riga["nome"], num(riga["nominale"]), num(riga["lsl"]), num(riga["usl"])]
                       + [num(v["x"]) if v else "" for v in riga["valori"]]
                       + [num(riga["delta"]), "" if riga["delta_pct"] is None else riga["delta_pct"]])
        return risposta
    pn = reports[0].pn
    colori = ["#2563eb", "#0d9488", "#d97706", "#9333ea", "#db2777", "#4b5563"]
    colonne = [{"r": r, "colore": colori[i]} for i, r in enumerate(reports)]
    for riga in dati["righe"]:
        riga["celle"] = list(zip(riga["valori"], colori))
    ids = [r.pk for r in reports]
    return render(request, "produzione/report_confronta.html", _ctx(
        request, "pn", pn=pn, colonne=colonne, righe=dati["righe"], totale=dati["totale"], cambiate=dati["cambiate"],
        solo=solo, proposte=pagine_cmm.proposte(reports[-1]), ids=ids, query_ids="&".join(f"r={i}" for i in ids),
        soglia=round(pagine_cmm.SOGLIA_CAMBIO * 100), massimo=pagine_cmm.MAX_CONFRONTO,
    ))


@login_required
@require_GET
def report_cmm_pdf(request, pk: int):
    """Il PDF dalla share, solo se sta sotto la cartella dei report."""
    report = get_object_or_404(ReportCMM, pk=pk)
    percorso = cmm.percorso_sicuro(report.percorso)
    if not percorso:
        if cmm.attivo() and not os.path.isdir(cmm.radice()):
            messages.error(request, "Il PDF non si apre: il portale non riesce a leggere la cartella dei report CMM "
                                    "(serve il permesso di lettura per l'utente del portale). L'analisi funziona lo stesso.")
        else:
            messages.error(request, "Il PDF non è più nella cartella dei report CMM (spostato o rinominato).")
        return redirect("produzione:report_cmm", report.pk)
    log_action(request, "produzione_report_cmm_pdf", "produzione", {"id": report.pk, "file": report.file})
    return FileResponse(open(percorso, "rb"), content_type="application/pdf", filename=report.file, as_attachment=False)


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoOP
        fields = ("tipo", "titolo", "revisione", "data", "percorso", "note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attuale = self.instance.tipo_id if self.instance.pk else None
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(attivo=True) | TipoDocumento.objects.filter(pk=attuale)

    def clean_percorso(self):
        try:
            return normalizza_percorso(self.cleaned_data.get("percorso"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


def _op_o_404(pk: int) -> dict:
    op = op_db.per_id(pk)
    if op is None:
        raise Http404
    return op


SEZIONI_OP = (("", "Pezzi"), ("report", "Report CMM"), ("documenti", "Documenti"), ("fai", "FAI"), ("programmi", "Programmi"))


def _render_scheda(request, op: dict, sezione: str, status: int = 200, **extra):
    """Scheda dell'OP a sezioni (``?sez=``): Pezzi (matrice pezzi × fasi e cronologia), Report CMM, Documenti,
    FAI e Programmi (questi due per chi vede i KICK-OFF)."""
    dati = services.scheda(request, op)
    sezioni = dict(SEZIONI_OP)
    if sezione not in sezioni or (sezione in ("fai", "programmi") and not dati["vede_kickoff"]):
        sezione = ""
    if not sezione:
        dati["matrice"] = pagine_cmm.matrice_op(op["op"], op_db.anomalie_aperte_per_seriale(op))
        dati["cronologia"] = pagine_cmm.cronologia_op(op["op"], dati["documenti"])
    conta = {"report": len(dati["report_cmm"]), "documenti": len(dati["documenti"]), "fai": len(dati["fai_pn"]),
             "programmi": len(dati["programmi"])}
    url = reverse("produzione:scheda", args=[op["id"]])
    tab = [{"chiave": k, "nome": v, "n": conta.get(k), "url": f"{url}?sez={k}" if k else url}
           for k, v in SEZIONI_OP if k not in ("fai", "programmi") or dati["vede_kickoff"]]
    return render(request, "produzione/scheda.html", _ctx(request, "scheda", sezione=sezione, sezioni=tab, **dati, **extra),
                  status=status)


@login_required
@require_GET
def scheda(request, pk: int):
    op = _op_o_404(pk)
    modifica = None
    if (request.GET.get("documento") or "").isdigit():
        modifica = DocumentoOP.objects.filter(pk=int(request.GET["documento"]), op__iexact=op["op"]).first()
    form = DocumentoForm(instance=modifica) if modifica else DocumentoForm()
    apri = request.GET.get("aggiungi") == "1"
    sezione = "documenti" if (modifica or apri) else request.GET.get("sez", "")
    return _render_scheda(request, op, sezione, form=form, modifica=modifica, tipi=TipoDocumento.objects.filter(attivo=True),
                          apri_form=apri)


@login_required
@require_POST
def documento(request, pk: int):
    """Nuovo documento dell'OP, o modifica di quello indicato in ``documento``."""
    _richiede(request, PERM_DOCUMENTI)
    op = _op_o_404(pk)
    istanza = None
    if (request.POST.get("documento") or "").isdigit():
        istanza = get_object_or_404(DocumentoOP, pk=int(request.POST["documento"]), op__iexact=op["op"])
    form = DocumentoForm(request.POST, instance=istanza)
    if not form.is_valid():
        return _render_scheda(request, op, "documenti", status=400, form=form, modifica=istanza,
                              tipi=TipoDocumento.objects.filter(attivo=True), apri_form=True)
    doc = form.save(commit=False)
    doc.op = op["op"]
    if istanza is None:
        doc.creato_da = request.user
    doc.save()
    log_action(request, "produzione_documento_salva", "produzione",
               {"id": doc.pk, "op": doc.op, "tipo": doc.tipo.etichetta, "nuovo": istanza is None})
    messages.success(request, f"{doc.tipo.etichetta} salvato.")
    return redirect(f"{reverse('produzione:scheda', args=[pk])}?sez=documenti")


@login_required
@require_POST
def documento_elimina(request, pk: int, doc_id: int):
    _richiede(request, PERM_DOCUMENTI)
    op = _op_o_404(pk)
    doc = get_object_or_404(DocumentoOP, pk=doc_id, op__iexact=op["op"])
    log_action(request, "produzione_documento_elimina", "produzione",
               {"id": doc.pk, "op": doc.op, "tipo": doc.tipo.etichetta, "titolo": doc.titolo})
    doc.delete()
    messages.success(request, "Documento eliminato.")
    return redirect(f"{reverse('produzione:scheda', args=[pk])}?sez=documenti")


@login_required
def impostazioni(request):
    _richiede(request, PERM_IMPOSTAZIONI)
    if request.method == "POST":
        azione = request.POST.get("azione")
        etichetta = (request.POST.get("etichetta") or "").strip()[:80]
        descrizione = (request.POST.get("descrizione") or "").strip()[:255]
        ordine = int(request.POST["ordine"]) if (request.POST.get("ordine") or "").isdigit() else 100
        if azione == "nuovo":
            if not etichetta:
                messages.error(request, "Scrivi il nome del tipo.")
            elif TipoDocumento.objects.filter(etichetta__iexact=etichetta).exists():
                messages.error(request, f"Il tipo «{etichetta}» c'è già.")
            else:
                TipoDocumento.objects.create(etichetta=etichetta, descrizione=descrizione, ordine=ordine)
                messages.success(request, f"Tipo «{etichetta}» aggiunto.")
        elif azione == "avvisi":
            imp = ImpostazioniQuoteCMM.attuali()
            imp.avvisa_fuori = request.POST.get("avvisa_fuori") == "1"
            imp.avvisa_deriva = request.POST.get("avvisa_deriva") == "1"
            imp.save()
            from django.contrib.auth import get_user_model

            ids = [int(x) for x in request.POST.getlist("destinatari") if x.isdigit()]
            imp.destinatari.set(get_user_model().objects.filter(pk__in=ids))
            messages.success(request, "Avvisi delle quote CMM salvati.")
        elif azione == "salva" and (request.POST.get("id") or "").isdigit():
            tipo = get_object_or_404(TipoDocumento, pk=int(request.POST["id"]))
            if etichetta and not TipoDocumento.objects.filter(etichetta__iexact=etichetta).exclude(pk=tipo.pk).exists():
                tipo.etichetta = etichetta
            tipo.descrizione, tipo.ordine = descrizione, ordine
            tipo.attivo = request.POST.get("attivo") == "1"
            tipo.save()
            messages.success(request, f"Tipo «{tipo.etichetta}» salvato.")
        log_action(request, "produzione_impostazioni", "produzione", {"azione": azione, "etichetta": etichetta})
        return redirect("produzione:impostazioni")
    from core.persone_tendine import etichetta_utente, ordina_persone, utenti_in_forza

    imp = ImpostazioniQuoteCMM.attuali()
    scelti = set(imp.destinatari.values_list("id", flat=True))
    persone = [{"id": u.pk, "nome": etichetta_utente(u), "scelto": u.pk in scelti}
               for u in ordina_persone(utenti_in_forza(), etichetta_utente)]
    return render(request, "produzione/impostazioni.html", _ctx(
        request, "impostazioni", tipi=TipoDocumento.objects.all(), avvisi=imp, persone=persone,
    ))


@require_POST
def op_nuovo(request):
    """Crea un OP dal pannello laterale: risponde sempre in JSON."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    if not nuovo_op.puo_creare(request):
        return JsonResponse({"ok": False, "error": "Non hai il permesso di creare OP."}, status=403)
    op, errori = nuovo_op.crea(request, request.POST)
    if errori:
        return JsonResponse({"ok": False, "errori": errori, "error": errori.get("__all__", "")}, status=400)
    log_action(request, "produzione_op_crea", "produzione", {"op": op["op"], "id": op["id"]})
    return JsonResponse({"ok": True, "op": op})


@login_required
@require_GET
def guida(request):
    if (request.GET.get("formato") or "") == "pdf":
        from core.guida_pdf import render_guida_pdf

        contenuto = render_guida_pdf(
            titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO, sezioni=guida_mod.SEZIONI,
            generato_da=request.user.get_username(), generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        resp = HttpResponse(contenuto, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="Guida_Ordini_di_produzione.pdf"'
        return resp
    return render(request, "produzione/guida.html", _ctx(
        request, "guida", sezioni=guida_mod.SEZIONI, titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO,
    ))


@login_required
@require_GET
def pezzo(request):
    """Pagina del pezzo (``?pn=&sn=``): esito, matrice quote × report (% di tolleranza, deviazione o valore), report,
    storia e pezzi dello stesso OP; ``formato=pdf``."""
    pn = normalize_part_number(request.GET.get("pn") or "")
    sn = (request.GET.get("sn") or "").strip()
    dati = pagine_cmm.pezzo(pn, sn, request.GET.get("solo", "")) if pn and sn else None
    if dati is None:
        raise Http404("Nessun report CMM per questo pezzo.")
    if request.GET.get("formato") == "pdf":
        from . import pdf_pezzo

        contenuto = pdf_pezzo.genera(dati, request.user.get_full_name() or request.user.get_username())
        log_action(request, "produzione_pezzo_pdf", "produzione", {"pn": pn, "sn": dati["sn"]})
        resp = HttpResponse(contenuto, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="Scheda_pezzo_{pn}_{dati["sn"]}.pdf"'
        return resp
    for riga in dati["righe"]:
        riga["celle"] = list(zip(riga["valori"], dati["intestazioni_fasi"]))
    op = op_db.per_titolo(dati["ultimo"].op) if dati["ultimo"].op and op_db.disponibile() else None
    url_anomalia = ""
    if op:
        url_anomalia = f"{reverse('apertura_segnalazione')}?{urlencode({'op_id': op['id'], 'report_cmm': dati['ultimo'].pk})}"
    return render(request, "produzione/pezzo.html", _ctx(
        request, "pn", op=op, url_anomalia=url_anomalia, url_pn=services.url_pn(pn),
        query_base=urlencode({"pn": pn, "sn": dati["sn"]}), ids_confronto="&".join(f"r={c.pk}" for c in dati["colonne"][-6:]),
        **dati))
