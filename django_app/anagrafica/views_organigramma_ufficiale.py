"""Organigrammi ufficiali: elenco, versione in vigore, tela di disegno, stampa.

Vedere: chi vede l'organigramma (binding copiato dal diagramma). Disegnare e
pubblicare: chi gestisce l'anagrafica (binding copiato dalla modifica dei ruoli
e, dentro la vista, ``_is_anagrafica_admin``). Le chiamate della tela stanno sotto
``/api/`` e rispondono sempre in JSON, anche quando negano.
"""
from __future__ import annotations

import json
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from .models import AmbitoRuolo, OrganigrammaRevisione, OrganigrammaUfficiale
from .services import organigramma_ufficiale as svc
from .views import _helpers


def _puo_disegnare(request) -> bool:
    return _helpers._is_anagrafica_admin(request)


def _firma():
    """Modulo della firma su portale (import tardivo: quel modulo importa questo file)."""
    from . import views_organigramma_firma

    return views_organigramma_firma


def _json_negato(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "errore": "Accesso richiesto."}, status=401)
    if not _puo_disegnare(request):
        return JsonResponse({"ok": False, "errore": "Non hai il permesso di disegnare gli organigrammi."}, status=403)
    return None


def _org(pk: int) -> OrganigrammaUfficiale:
    return get_object_or_404(OrganigrammaUfficiale, pk=pk, is_active=True)


def _parse_ambito(raw) -> AmbitoRuolo | None:
    raw = str(raw or "").strip()
    if not raw.isdigit() or len(raw) > 9:
        return None
    return AmbitoRuolo.objects.filter(pk=int(raw), is_active=True).first()


# ── elenco ─────────────────────────────────────────────────────────────────

@login_required
def organigramma_ufficiale(request):
    organigrammi = list(
        OrganigrammaUfficiale.objects.filter(is_active=True).select_related("ambito", "bozza_aggiornata_da")
    )
    revisioni: dict[int, OrganigrammaRevisione] = {}
    for rev in OrganigrammaRevisione.objects.filter(organigramma__in=organigrammi).order_by("organigramma_id", "-numero"):
        revisioni.setdefault(rev.organigramma_id, rev)
    from timbri.models import DocumentoFirma

    vf = _firma()
    in_firma = {d.oggetto_id: d for d in DocumentoFirma.objects.filter(
        tipo=vf.CHIAVE, stato=DocumentoFirma.STATO_IN_FIRMA, oggetto_id__in=[o.pk for o in organigrammi]
    ).prefetch_related("caselle", "caselle__ruolo")}
    righe = []
    for org in organigrammi:
        rev = revisioni.get(org.pk)
        doc = in_firma.get(org.pk)
        corrente = vf.firme.casella_corrente(doc) if doc else None
        dati = rev.dati if rev else (org.bozza or svc.vuoto())
        ctx = svc.contesto(dati)
        n_avvisi = len(svc.avvisi(dati, ctx, org)) if (rev or org.bozza) else 0
        righe.append({
            "org": org, "rev": rev, "n_avvisi": n_avvisi,
            "pacchetto": svc.pacchetto(dati),
            "n_modifiche": len(svc.riepilogo(rev.dati if rev else None, org.bozza)) if org.bozza is not None else 0,
            "in_firma": doc, "casella": corrente,
            "tocca_a_me": bool(corrente and vf.firme.puo_firmare_casella(request.user, corrente)),
        })
    return render(request, "anagrafica/pages/organigramma_ufficiale_elenco.html", {
        "righe": righe,
        "n_pubblicati": sum(1 for r in righe if r["rev"]),
        "puo_disegnare": _puo_disegnare(request),
        "ambiti": AmbitoRuolo.objects.filter(is_active=True).order_by("ordine", "nome"),
        "da_firmare": sum(1 for r in righe if r["tocca_a_me"]),
        "puo_impostare_firme": vf.puo_impostare_firme(request),
        "firme_imp": vf.impostazioni_vista() if vf.puo_impostare_firme(request) else None,
        "firma_attiva": vf.firma_attiva(),
        "varianti_firma": [("FIRMA", "Firma"), ("TIMBRO", "Timbro"), ("SIGLA", "Sigla")],
    })


@login_required
@require_POST
def organigramma_ufficiale_nuovo(request):
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di creare organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    nome = " ".join((request.POST.get("nome") or "").split())[:150]
    if not nome:
        messages.error(request, "Il nome dell'organigramma è obbligatorio.")
        return redirect("anagrafica:organigramma_ufficiale")
    org = OrganigrammaUfficiale.objects.create(
        nome=nome,
        descrizione=" ".join((request.POST.get("descrizione") or "").split())[:300],
        ambito=_parse_ambito(request.POST.get("ambito")),
        bozza=svc.vuoto(), bozza_aggiornata_il=timezone.now(), bozza_aggiornata_da=request.user,
        creato_da=request.user,
    )
    log_action(request, "organigramma_ufficiale_creato", "anagrafica", {"nome": nome}, oggetto=org)
    return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)


@login_required
@require_POST
def organigramma_ufficiale_modifica(request, pk: int):
    org = _org(pk)
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di modificare gli organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    if request.POST.get("azione") == "archivia":
        org.is_active = False
        org.save(update_fields=["is_active"])
        log_action(request, "organigramma_ufficiale_archiviato", "anagrafica", {"nome": org.nome}, oggetto=org)
        messages.success(request, f"«{org.nome}» archiviato: non compare più nell'elenco.")
        return redirect("anagrafica:organigramma_ufficiale")
    nome = " ".join((request.POST.get("nome") or "").split())[:150]
    if nome:
        org.nome = nome
    org.descrizione = " ".join((request.POST.get("descrizione") or "").split())[:300]
    org.ambito = _parse_ambito(request.POST.get("ambito"))
    org.save(update_fields=["nome", "descrizione", "ambito"])
    messages.success(request, "Dati dell'organigramma aggiornati.")
    return redirect(request.POST.get("torna") == "disegna"
                    and reverse("anagrafica:organigramma_ufficiale_disegna", args=[org.pk])
                    or reverse("anagrafica:organigramma_ufficiale"))


# ── versione in vigore e stampa ────────────────────────────────────────────

def _revisione_richiesta(request, org):
    raw = (request.GET.get("rev") or "").strip()
    if raw.isdigit() and len(raw) < 7:
        return get_object_or_404(OrganigrammaRevisione, organigramma=org, numero=int(raw))
    return org.revisione_in_vigore()


@login_required
def organigramma_ufficiale_vedi(request, pk: int):
    org = _org(pk)
    rev = _revisione_richiesta(request, org)
    if rev is None:
        if _puo_disegnare(request):
            return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
        raise Http404("Organigramma non ancora pubblicato.")
    in_vigore = org.revisione_in_vigore()
    doc_firma = _firma().doc_in_firma(org)
    confronto = None
    raw = (request.GET.get("confronta") or "").strip()
    if raw.isdigit() and len(raw) < 7:
        altra = OrganigrammaRevisione.objects.filter(organigramma=org, numero=int(raw)).first()
        if altra is not None:
            vecchia, nuova = sorted([altra, rev], key=lambda r: r.numero)
            confronto = {"da": vecchia, "a": nuova, "righe": svc.riepilogo(vecchia.dati, nuova.dati)}
    return render(request, "anagrafica/pages/organigramma_ufficiale_vedi.html", {
        "org": org, "rev": rev, "in_vigore": in_vigore,
        "pacchetto": svc.pacchetto(rev.dati),
        "revisioni": list(org.revisioni.select_related("pubblicata_da")),
        "confronto": confronto,
        "puo_disegnare": _puo_disegnare(request),
        "firme_rev": _firma().firme_della_revisione(rev, request.user),
        "in_firma": doc_firma,
        "in_firma_link": bool(doc_firma and (_puo_disegnare(request) or _firma()._coinvolto(request.user, doc_firma))),
    })


#: Formati di stampa: dimensioni del foglio utile in mm (margini di 8 mm già tolti) e voce di @page.
FORMATI = {
    "A3": {"w": 404, "h": 281, "page": "A3 landscape", "nome": "A3"},
    "A4": {"w": 281, "h": 194, "page": "A4 landscape", "nome": "A4 orizzontale"},
    "A4v": {"w": 194, "h": 281, "page": "A4 portrait", "nome": "A4 verticale"},
}


def _pagina(org, rev, dati, bozza: bool, *, user=None, doc_firma=None) -> dict:
    p = svc.pacchetto(dati)
    foglio = p["dati"]["foglio"]
    vf = _firma()
    if doc_firma is not None:
        firme_pag = {"doc": doc_firma, "caselle": vf.caselle_vista(doc_firma, user)}
    else:
        firme_pag = vf.firme_della_revisione(rev, user) if rev else None
    return {
        "org": org, "rev": rev, "bozza": bozza, "pacchetto": p, "foglio": foglio, "firme": firme_pag,
        "titolo": foglio["titolo"] or org.nome,
        "intestazione": foglio["intestazione"] or "Organigramma",
        "piede": svc.testo_piede(foglio, rev.numero if rev else None, org.nome),
    }


def _logo_url() -> str:
    """Logo caricato in Impostazioni grafiche del portale; altrimenti quello di serie."""
    from django.templatetags.static import static

    try:
        from core.branding import get_portal_branding

        return get_portal_branding().brand_logo_full or static("core/img/logo_novicrom.png")
    except Exception:  # impostazioni non leggibili: logo di serie
        return static("core/img/logo_novicrom.png")


@login_required
def organigramma_ufficiale_stampa(request, pk: int):
    """Una pagina per organigramma: questo e quelli in ``?con=2,5`` (revisione in vigore), in un solo PDF."""
    org = _org(pk)
    bozza = request.GET.get("bozza") == "1"
    in_firma = request.GET.get("firma") == "1"
    if in_firma:
        doc = _firma().doc_in_firma(org)
        if doc is None or not (_puo_disegnare(request) or _firma()._coinvolto(request.user, doc)):
            raise Http404()
        pagine = [_pagina(org, None, (doc.contenuto or {}).get("dati"), True, user=request.user, doc_firma=doc)]
    elif bozza:
        if not _puo_disegnare(request):
            raise Http404()
        pagine = [_pagina(org, None, org.bozza or svc.ultimo_disegno(org), True)]
    else:
        rev = _revisione_richiesta(request, org)
        if rev is None:
            raise Http404("Organigramma non ancora pubblicato.")
        pagine = [_pagina(org, rev, rev.dati, False, user=request.user)]
    altri = [int(x) for x in (request.GET.get("con") or "").split(",") if x.strip().isdigit() and len(x.strip()) < 9]
    con = []
    for altro in OrganigrammaUfficiale.objects.filter(pk__in=altri, is_active=True).exclude(pk=org.pk):
        r = altro.revisione_in_vigore()
        if r is not None:
            con.append((altri.index(altro.pk), _pagina(altro, r, r.dati, False, user=request.user)))
    pagine += [p for _, p in sorted(con, key=lambda x: x[0])]
    predefinito = "A4v" if pagine[0]["foglio"]["stile"] == "documento" else "A3"
    chiave = request.GET.get("formato") if request.GET.get("formato") in FORMATI else predefinito
    query = request.GET.copy()
    query.pop("formato", None)
    return render(request, "anagrafica/pages/organigramma_ufficiale_stampa.html", {
        "org": org, "pagine": pagine, "bozza": bozza or in_firma, "in_firma": in_firma, "formato": FORMATI[chiave], "chiave": chiave,
        "formati": [(k, v["nome"]) for k, v in FORMATI.items()], "query": query.urlencode(),
        "logo_url": _logo_url(),
        "oggi": date.today(),
    })


# ── tela di disegno ────────────────────────────────────────────────────────

@login_required
def organigramma_ufficiale_disegna(request, pk: int):
    org = _org(pk)
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di disegnare gli organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    if _firma().doc_in_firma(org) is not None:
        messages.info(request, "Questa bozza è in firma: per modificarla ritira prima la richiesta di firma.")
        return redirect("anagrafica:organigramma_ufficiale_firma", pk=org.pk)
    in_vigore = org.revisione_in_vigore()
    dati = org.bozza if org.bozza is not None else (in_vigore.dati if in_vigore else svc.vuoto())
    dati = svc.normalizza(dati)
    ctx = svc.contesto(dati)
    stato = {
        "disegno": dati,
        "cataloghi": svc.cataloghi(org.ambito),
        "avvisi": svc.avvisi(dati, ctx, org),
        "nomi": svc.nomi_per_tela(ctx),
        "n_modifiche": len(svc.riepilogo(in_vigore.dati if in_vigore else None, dati)) if org.bozza is not None else 0,
        "palette": list(svc.PALETTE),
        "url": {
            "bozza": reverse("anagrafica:organigramma_ufficiale_bozza", args=[org.pk]),
            "riepilogo": reverse("anagrafica:organigramma_ufficiale_riepilogo", args=[org.pk]),
            "stampa": reverse("anagrafica:organigramma_ufficiale_stampa", args=[org.pk]) + "?bozza=1",
        },
        "salvata_il": timezone.localtime(org.bozza_aggiornata_il).strftime("%H:%M") if org.bozza_aggiornata_il else "",
        "bozza_aperta": org.bozza is not None,
    }
    return render(request, "anagrafica/pages/organigramma_ufficiale_disegna.html", {
        "org": org, "in_vigore": in_vigore, "stato": stato,
        "prossimo_numero": (in_vigore.numero + 1) if in_vigore else 1,
        "oggi": date.today(),
        "ambiti": AmbitoRuolo.objects.filter(is_active=True).order_by("ordine", "nome"),
        "invio": _firma().contesto_invio(request, org),
    })


@require_POST
def organigramma_ufficiale_bozza(request, pk: int):
    negato = _json_negato(request)
    if negato:
        return negato
    org = OrganigrammaUfficiale.objects.filter(pk=pk, is_active=True).first()
    if org is None:
        return JsonResponse({"ok": False, "errore": "Organigramma non trovato."}, status=404)
    if _firma().doc_in_firma(org) is not None:
        return JsonResponse({"ok": False, "errore": "La bozza è in firma: ritira la richiesta per modificarla."}, status=409)
    if len(request.body) > 2_000_000:
        return JsonResponse({"ok": False, "errore": "Disegno troppo grande."}, status=400)
    try:
        dati = json.loads(request.body.decode("utf-8") or "{}")
        svc.salva_bozza(org, dati.get("disegno") if isinstance(dati, dict) else None, request.user)
    except (ValueError, UnicodeDecodeError) as exc:
        return JsonResponse({"ok": False, "errore": str(exc) or "Disegno non valido."}, status=400)
    in_vigore = org.revisione_in_vigore()
    ctx = svc.contesto(org.bozza)
    return JsonResponse({
        "ok": True,
        "salvata_il": timezone.localtime(org.bozza_aggiornata_il).strftime("%H:%M"),
        "avvisi": svc.avvisi(org.bozza, ctx, org),
        "n_modifiche": len(svc.riepilogo(in_vigore.dati if in_vigore else None, org.bozza)),
    })


@require_GET
def organigramma_ufficiale_riepilogo(request, pk: int):
    negato = _json_negato(request)
    if negato:
        return negato
    org = OrganigrammaUfficiale.objects.filter(pk=pk, is_active=True).first()
    if org is None:
        return JsonResponse({"ok": False, "errore": "Organigramma non trovato."}, status=404)
    in_vigore = org.revisione_in_vigore()
    bozza = org.bozza if org.bozza is not None else svc.ultimo_disegno(org)
    return JsonResponse({
        "ok": True,
        "da": f"Rev.{in_vigore.numero}" if in_vigore else "nessuna revisione",
        "righe": svc.riepilogo(in_vigore.dati if in_vigore else None, bozza),
        "avvisi": svc.avvisi(bozza, svc.contesto(bozza), org),
    })


@login_required
@require_POST
def organigramma_ufficiale_pubblica(request, pk: int):
    org = _org(pk)
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di pubblicare gli organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    if _firma().firma_attiva():
        messages.error(request, "Gli organigrammi si pubblicano con la firma su portale: usa «Invia in firma».")
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    try:
        data_emissione = date.fromisoformat((request.POST.get("data_emissione") or "").strip())
    except ValueError:
        data_emissione = date.today()
    try:
        rev = svc.pubblica(
            org, nota=request.POST.get("nota") or "", approvato_da=request.POST.get("approvato_da") or "",
            data_emissione=data_emissione, user=request.user,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    log_action(request, "organigramma_ufficiale_pubblicato", "anagrafica",
               {"nome": org.nome, "revisione": rev.numero}, oggetto=org)
    messages.success(request, f"Pubblicata la Rev.{rev.numero} di «{org.nome}».")
    return redirect("anagrafica:organigramma_ufficiale_vedi", pk=org.pk)


@login_required
@require_POST
def organigramma_ufficiale_scarta(request, pk: int):
    org = _org(pk)
    if not _puo_disegnare(request):
        messages.error(request, "Non hai il permesso di modificare gli organigrammi.")
        return redirect("anagrafica:organigramma_ufficiale")
    if _firma().doc_in_firma(org) is not None:
        messages.error(request, "La bozza è in firma: ritira prima la richiesta di firma.")
        return redirect("anagrafica:organigramma_ufficiale_firma", pk=org.pk)
    if org.revisione_in_vigore() is None:
        messages.error(request, "L'organigramma non ha revisioni pubblicate: archivialo invece di scartare la bozza.")
        return redirect("anagrafica:organigramma_ufficiale_disegna", pk=org.pk)
    org.bozza = None
    org.bozza_aggiornata_il = None
    org.bozza_aggiornata_da = None
    org.save(update_fields=["bozza", "bozza_aggiornata_il", "bozza_aggiornata_da"])
    log_action(request, "organigramma_ufficiale_bozza_scartata", "anagrafica", {"nome": org.nome}, oggetto=org)
    messages.success(request, "Bozza scartata: resta in vigore l'ultima revisione pubblicata.")
    return redirect("anagrafica:organigramma_ufficiale_vedi", pk=org.pk)
