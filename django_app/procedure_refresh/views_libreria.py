"""CN-SGI: pagine della libreria delle procedure (sola lettura della share).

- ``libreria``: ricerca, scaffali, letture da fare, nuove revisioni, più consultati;
- ``scaffale``: le sezioni di uno scaffale, a copertine o a elenco;
- ``cerca``: codice, titolo e testo dei PDF in vigore, con estratto e pagina;
- ``documento``: la scheda (pannello laterale via HTMX, pagina intera senza);
- ``apri``: il PDF in vigore, nel visualizzatore del browser;
- ``visibilita`` e ``scaffali``: gestione di chi vede cosa e dell'aspetto degli scaffali.

Ogni pagina filtra i documenti con :class:`procedure_refresh.libreria.Visibilita`:
un documento che l'utente non può vedere non compare e la sua scheda dà 404.
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.copertine import CopertinaNonValida
from core.copertine_librerie import ICONE, NOMI as ICONE_NOMI, risposta_logo, salva_logo, togli_logo

from . import esperienza as esp
from . import segnalazioni as _segn
from . import libreria as lib
from .guida import con_guida
from .models import (
    AssignmentStatus,
    ProcedureAssignment,
    ProcedureDocument,
    SgiDocumentoProcesso,
    SgiRiferimento,
    SgiScaffale,
    SgiVisibilita,
    SgiVisibilitaChi,
    SourceType,
)
from .views import _can_manage, _safe_sgi_pdf

VISTE = ("copertine", "elenco")
logger = logging.getLogger(__name__)


def _ultimo_controllo():
    from core.models import SiteConfig

    for chiave in ("pr_sgi_ultimo_controllo", "pr_sgi_last_sync"):
        raw = str(SiteConfig.get(chiave, "") or "").strip()
        if not raw:
            continue
        try:
            if raw.startswith("{"):
                raw = json.loads(raw).get("at", "")
            quando = datetime.fromisoformat(raw)
            if timezone.is_naive(quando):
                quando = timezone.make_aware(quando)
            return timezone.localtime(quando)
        except (ValueError, TypeError, AttributeError):
            continue
    return None


def _modifiche_mie(request, gestore: bool) -> int:
    """Quante modifiche ai documenti aspettano un'azione dell'utente (numero accanto a «Modifiche»)."""
    try:
        from . import modifiche as _mod

        return len(_mod.da_fare(request.user, gestore))
    except Exception:
        return 0


def _contesto_base(request, vis, docs, **extra):
    da_leggere = lib.letture_da_fare(request.user)
    ultimo = _ultimo_controllo()
    ctx = {
        "is_manager": vis.gestore,
        "puo_audit": vis.gestore or vis.vede_tutto,
        "n_segnalazioni_aperte": _segn.aperte() if vis.gestore else 0,
        "n_modifiche_mie": _modifiche_mie(request, vis.gestore),
        "ultimo_controllo": ultimo,
        # Più di 45 minuti senza controllo (ogni 15 previsto): il pallino diventa giallo e chi gestisce trova il perché in «Impostazioni».
        "controllo_vecchio": ultimo is None or timezone.now() - ultimo > timedelta(minutes=45),
        "oggi_str": timezone.localdate().strftime("%Y%m%d"),
        "n_da_leggere": sum(1 for d in docs if d.pk in da_leggere),
        "da_leggere_map": da_leggere,
        "nuove_map": lib.codici_nuove_revisioni(),
    }
    ctx.update(extra)
    return ctx


def _scaffali(docs, config, nuove) -> "OrderedDict[str, lib.Scaffale]":
    """Scaffali che contengono almeno un documento visibile, nell'ordine scelto da chi gestisce."""
    out: dict[str, lib.Scaffale] = {}
    sezioni: dict[str, dict[str, int]] = {}
    for d in docs:
        cartella = d.category or ""
        riga = config.get(cartella)
        if riga is not None and not riga.attivo:
            continue
        s = out.get(cartella)
        if s is None:
            s = out[cartella] = lib.scaffale_da(cartella, config)
            sezioni[cartella] = {}
        s.totale += 1
        if d.code in nuove:
            s.nuovi += 1
        sezioni[cartella][d.sezione or ""] = sezioni[cartella].get(d.sezione or "", 0) + 1
    for cartella, s in out.items():
        s.sezioni = sorted(
            ((raw, lib.etichetta_sezione(raw), n) for raw, n in sezioni[cartella].items()),
            key=lambda x: (x[0] == "", x[0].lower()),
        )
    ordinati = sorted(out.values(), key=lambda s: (s.cartella == "", s.ordine, s.nome.lower()))
    return OrderedDict((s.cartella, s) for s in ordinati)


def _decora(docs, scaffali, nuove, da_leggere, request=None):
    """Aggiunge ai documenti scaffale, sezione, tipo e stato (da leggere, nuova revisione, letta, preferito)."""
    preferiti = set(esp.preferiti_di(request.user)) if request is not None else set()
    lette = esp.lette_da(request.user, docs) if request is not None else set()
    for d in docs:
        d.scaffale = scaffali.get(d.category or "")
        d.sezione_label = lib.etichetta_sezione(d.sezione)
        d.nuova = d.code in nuove
        d.lettura = da_leggere.get(d.pk)
        d.letta = d.pk in lette
        d.preferito = d.pk in preferiti
        d.tipo = esp.tipo_documento(d)
    return docs


def _visibili(request):
    vis = lib.Visibilita(request)
    config = lib.scaffali_configurati()
    docs = [d for d in vis.filtra(lib.documenti_in_vigore())
            if (config.get(d.category or "") is None or config[d.category or ""].attivo)]
    return vis, config, docs


@login_required
@con_guida
def libreria(request):
    vis, config, docs = _visibili(request)
    nuove = lib.codici_nuove_revisioni()
    da_leggere = lib.letture_da_fare(request.user)
    scaffali = _scaffali(docs, config, nuove)
    _decora(docs, scaffali, nuove, da_leggere, request)

    oggi = timezone.localdate()
    for s in scaffali.values():
        cert = s.certificazione
        s.giorni_sorveglianza = (cert.prossima_sorveglianza - oggi).days if cert and cert.prossima_sorveglianza else None
        s.giorni_scadenza = (cert.scade_il - oggi).days if cert and cert.scade_il else None

    letture = sorted((d for d in docs if d.lettura), key=lambda d: (d.lettura.due_date or oggi))
    novita = sorted((d for d in docs if d.nuova), key=lambda d: nuove[d.code], reverse=True)[:14]
    aperture = lib.aperture_recenti()
    consultati = sorted((d for d in docs if aperture.get(d.pk)), key=lambda d: -aperture[d.pk])[:12]
    ordine_preferiti = {pk: i for i, pk in enumerate(esp.preferiti_di(request.user))}
    preferiti = sorted((d for d in docs if d.preferito), key=lambda d: ordine_preferiti.get(d.pk, 0))

    return render(request, "procedure_refresh/libreria/home.html", _contesto_base(
        request, vis, docs,
        scaffali=list(scaffali.values()),
        totale=len(docs),
        letture=letture,
        preferiti=preferiti,
        novita=novita,
        consultati=consultati,
        oggi=oggi,
    ))


@login_required
@con_guida
def scaffale(request, slug: str):
    vis, config, docs = _visibili(request)
    nuove = lib.codici_nuove_revisioni()
    da_leggere = lib.letture_da_fare(request.user)
    scaffali = _scaffali(docs, config, nuove)
    corrente = next((s for s in scaffali.values() if s.slug == slug), None)
    if corrente is None:
        raise Http404("Scaffale non disponibile.")
    _decora(docs, scaffali, nuove, da_leggere, request)
    miei = [d for d in docs if (d.category or "") == corrente.cartella]
    tipi_presenti = [(k, lab) for k, lab in esp.TIPI if any(d.tipo == k for d in miei)]
    tipo = request.GET.get("tipo") or ""
    if tipo not in {k for k, _lab in tipi_presenti}:
        tipo = ""
    cambiati = request.GET.get("cambiati") or ""
    if cambiati not in ("30", "90", "365"):
        cambiati = ""
    ordine = request.GET.get("ordine") or "codice"
    if ordine not in ("codice", "data", "consultati"):
        ordine = "codice"
    aperture = lib.aperture_recenti() if ordine == "consultati" else {}
    limite_data = timezone.localdate() - timedelta(days=int(cambiati)) if cambiati else None

    sezione = request.GET.get("sezione")
    sezioni_valide = {raw for raw, _l, _n in corrente.sezioni}
    if sezione is not None and sezione not in sezioni_valide:
        sezione = None
    vista = request.GET.get("vista") or request.COOKIES.get("cnsgi_vista") or "copertine"
    if vista not in VISTE:
        vista = "copertine"
    filtro = (request.GET.get("q") or "").strip()

    gruppi = []
    for raw, etichetta, _n in corrente.sezioni:
        if sezione is not None and raw != sezione:
            continue
        elenco = [d for d in miei if (d.sezione or "") == raw]
        if filtro:
            trovati = {r.doc.pk for r in lib.cerca(filtro, elenco, campo="titolo")}
            elenco = [d for d in elenco if d.pk in trovati]
        if tipo:
            elenco = [d for d in elenco if d.tipo == tipo]
        if limite_data:
            elenco = [d for d in elenco if d.rev.revision_date and d.rev.revision_date >= limite_data]
        if ordine == "data":
            elenco.sort(key=lambda d: d.rev.revision_date or timezone.localdate(), reverse=True)
        elif ordine == "consultati":
            elenco.sort(key=lambda d: -aperture.get(d.pk, 0))
        if elenco:
            gruppi.append({"raw": raw, "etichetta": etichetta, "documenti": elenco})

    cert = corrente.certificazione
    oggi = timezone.localdate()
    response = render(request, "procedure_refresh/libreria/scaffale.html", _contesto_base(
        request, vis, docs,
        scaffale=corrente,
        scaffali=list(scaffali.values()),
        gruppi=gruppi,
        sezione=sezione,
        vista=vista,
        filtro=filtro,
        tipo=tipo, tipi=tipi_presenti, cambiati=cambiati, ordine=ordine,
        n_scaffale=len(miei),
        giorni_sorveglianza=(cert.prossima_sorveglianza - oggi).days if cert and cert.prossima_sorveglianza else None,
    ))
    if request.GET.get("vista") in VISTE:
        response.set_cookie("cnsgi_vista", vista, max_age=3600 * 24 * 365, samesite="Lax")
    return response


@login_required
@con_guida
def cerca(request):
    vis, config, docs = _visibili(request)
    nuove = lib.codici_nuove_revisioni()
    scaffali = _scaffali(docs, config, nuove)
    _decora(docs, scaffali, nuove, lib.letture_da_fare(request.user), request)

    q = (request.GET.get("q") or "").strip()[:120]
    campo = request.GET.get("in") or "tutto"
    if campo not in ("tutto", "titolo", "testo"):
        campo = "tutto"
    filtro_scaffali = [s for s in request.GET.getlist("s") if s in {x.slug for x in scaffali.values()}]
    base = [d for d in docs if not filtro_scaffali or (d.scaffale and d.scaffale.slug in filtro_scaffali)]
    risultati = lib.cerca(q, base, campo=campo) if q else []

    conteggi = {}
    if q:
        for r in (lib.cerca(q, docs, campo=campo) if filtro_scaffali else risultati):
            if r.doc.scaffale:
                conteggi[r.doc.scaffale.slug] = conteggi.get(r.doc.scaffale.slug, 0) + 1
    faccette = [{"s": s, "n": conteggi.get(s.slug, 0), "on": s.slug in filtro_scaffali} for s in scaffali.values()]
    live = bool(getattr(request, "htmx", False))
    if q and not live:
        log_action(request, "cerca", "procedure_refresh", {"message": "Ricerca CN-SGI", "q": q, "risultati": len(risultati)})
    for r in risultati:
        for e in r.estratti:
            e["prima_html"] = esp.con_glossario(e["prima"])
            e["dopo_html"] = esp.con_glossario(e["dopo"])

    ctx = _contesto_base(
        request, vis, docs,
        q=q, campo=campo, risultati=risultati, faccette=faccette, filtro_scaffali=filtro_scaffali,
    )
    if live:
        return render(request, "procedure_refresh/libreria/_risultati.html", ctx)
    return render(request, "procedure_refresh/libreria/cerca.html", ctx)


@login_required
def suggerimenti(request):
    """Tendina live della ricerca: documenti per codice e titolo mentre si scrive (HTMX)."""
    vis, config, docs = _visibili(request)
    q = (request.GET.get("q") or "").strip()[:120]
    trovati = []
    if len(q) >= 2:
        nuove = lib.codici_nuove_revisioni()
        scaffali = _scaffali(docs, config, nuove)
        _decora(docs, scaffali, nuove, {})
        risultati = lib.cerca(q, docs, campo="titolo")
        trovati = [] if risultati.approssimati else list(risultati[:8])
    return render(request, "procedure_refresh/libreria/_suggerimenti.html", {"q": q, "trovati": trovati})


def _documento_visibile(request, pk: int):
    vis = lib.Visibilita(request)
    doc = get_object_or_404(ProcedureDocument.objects.prefetch_related("revisions"), pk=pk)
    config = lib.scaffali_configurati()
    riga = config.get(doc.category or "")
    if not vis.puo_vedere(doc) or (riga is not None and not riga.attivo and not vis.gestore):
        raise Http404("Documento non disponibile.")
    rev = next((r for r in doc.revisions.all() if r.is_current), None)
    if rev is None:
        raise Http404("Documento senza revisione in vigore.")
    doc.rev = rev
    return vis, config, doc, rev


@login_required
@con_guida
def documento(request, pk: int):
    vis, config, doc, rev = _documento_visibile(request, pk)
    nuove = lib.codici_nuove_revisioni()
    doc.scaffale = lib.scaffale_da(doc.category or "", config)
    doc.sezione_label = lib.etichetta_sezione(doc.sezione)
    doc.nuova = doc.code in nuove
    try:
        rev.testo_estratto  # noqa: B018 - carica la relazione se c'è
    except Exception:
        pass

    # Cita / è citato da (solo documenti che chi guarda può vedere).
    cita, visti = [], set()
    for r in SgiRiferimento.objects.filter(da_revisione=rev).select_related("a_documento").order_by("codice_citato"):
        d = r.a_documento
        if d is not None:
            if d.pk in visti or not vis.puo_vedere(d):
                continue
            visti.add(d.pk)
            cita.append({"doc": d, "codice": d.code, "titolo": d.title, "sezione": r.sezione})
        elif r.tipo_risoluzione != "famiglia":
            cita.append({"doc": None, "codice": r.codice_citato, "titolo": "", "sezione": r.sezione})
    citato_da, visti = [], set()
    for r in (SgiRiferimento.objects.filter(a_documento=doc, da_revisione__is_current=True)
              .select_related("da_revisione__document").order_by("da_revisione__document__code")):
        d = r.da_revisione.document
        if d.pk == doc.pk or d.pk in visti or not d.is_active or not vis.puo_vedere(d):
            continue
        visti.add(d.pk)
        citato_da.append({"doc": d, "codice": d.code, "titolo": d.title, "sezione": r.sezione})
    processi = list(
        SgiDocumentoProcesso.objects.filter(documento=doc, confermato=True).select_related("processo")
    )

    from .collegamenti import moduli_del_documento

    moduli = moduli_del_documento(doc)
    revisioni = sorted(doc.revisions.all(), key=lambda r: (r.is_current, r.revision_date), reverse=True)
    lettura = lib.letture_da_fare(request.user).get(doc.pk)
    confermata = None
    if lettura is None and request.user.is_authenticated:
        confermata = (
            ProcedureAssignment.objects.filter(user=request.user, revision=rev, status=AssignmentStatus.READ_CONFIRMED)
            .order_by("-read_confirmed_at").first()
        )
    stato_gestore = None
    if vis.gestore:
        qs = ProcedureAssignment.objects.filter(revision=rev).exclude(status=AssignmentStatus.CANCELLED)
        totale = qs.count()
        lette = qs.filter(status=AssignmentStatus.READ_CONFIRMED).count()
        stato_gestore = {
            "totale": totale, "lette": lette, "pct": round(lette * 100 / totale) if totale else 0,
            "regola": vis.regola(doc),
        }

    pagina_raw = request.GET.get("pagina") or ""
    pagina = int(pagina_raw) if pagina_raw.isdigit() and 0 < int(pagina_raw) < 10000 else None
    rev_prec = esp.revisione_precedente(doc, rev)
    cambiamenti = None
    if rev_prec is not None and getattr(rev, "testo_estratto", None) is not None:
        try:
            cambiamenti = esp.differenze(rev_prec.testo_estratto.testo, rev.testo_estratto.testo)
        except Exception:
            cambiamenti = None

    from . import modifiche as _mod

    in_lavorazione = _mod.in_lavorazione_per(doc)
    if in_lavorazione is not None:
        in_lavorazione.puo_aprire = vis.gestore or _mod.puo_vedere(in_lavorazione, request.user, False)
    recepite = _segn.recepite_in(rev)
    n_rilettura = len(_segn.da_rileggere(doc, rev)) if vis.gestore else 0
    ctx = {
        "doc": doc, "rev": rev, "is_manager": vis.gestore,
        "rev_prec": rev_prec, "cambiamenti": cambiamenti,
        "in_lavorazione": in_lavorazione,
        "recepite": recepite, "n_rilettura": n_rilettura, "giorni_rilettura": _segn.GIORNI_RILETTURA,
        "mostra_cambia": cambiamenti is not None or bool(recepite) or bool(n_rilettura),
        "preferito": doc.pk in set(esp.preferiti_di(request.user)),
        "mappa": esp.mappa(doc.code, cita, citato_da),
        "chiedi_url": reverse("ai_assistant:chat"),
        "chiedi_prefisso": "Nel documento " + doc.code + " (" + doc.title + "): ",
        "etichetta_url": reverse("procedure_refresh:libreria_etichetta", args=[doc.pk]),
        "indice": lib.indice_documento(rev),
        "cita": cita, "citato_da": citato_da, "processi": processi,
        "moduli": moduli,
        "compila": next((m for m in moduli if m["compila"]), None),
        "n_collegamenti": len(cita) + len(citato_da) + len(processi) + len(moduli),
        "revisioni": revisioni, "lettura": lettura, "confermata": confermata,
        "stato_gestore": stato_gestore,
        "pagina": pagina,
        "scheda": request.GET.get("scheda") or ("anteprima" if pagina else "panoramica"),
        "pdf_url": reverse("procedure_refresh:libreria_apri", args=[doc.pk]),
    }
    if getattr(request, "htmx", False):
        return render(request, "procedure_refresh/libreria/_scheda.html", ctx)
    ctx.update(_contesto_base(request, vis, [doc]))
    return render(request, "procedure_refresh/libreria/documento.html", ctx)


@login_required
def documento_da_codice(request):
    """``?c=<codice>``: porta alla scheda del documento (link dalle fonti dell'assistente AI)."""
    codice = (request.GET.get("c") or "").strip()[:60]
    doc = ProcedureDocument.objects.filter(code=codice, is_active=True).only("pk").first() if codice else None
    if doc is None:
        messages.info(request, f"Nessun documento in vigore con il codice «{codice}»." if codice else "Codice mancante.")
        from urllib.parse import urlencode

        return redirect(f"{reverse('procedure_refresh:libreria_cerca')}?{urlencode({'q': codice})}")
    return redirect("procedure_refresh:libreria_documento", pk=doc.pk)


@login_required
@xframe_options_sameorigin
def apri(request, pk: int):
    """Il PDF in vigore del documento, nel browser (inline). Solo revisione corrente, mai SUPERATO."""
    from procedure_refresh.management.commands.import_sgi_da_share import _SUPERATO_RE

    _vis, _config, doc, rev = _documento_visibile(request, pk)
    log_action(request, "apri", "procedure_refresh", {
        "message": "Apertura documento CN-SGI", "document_id": doc.pk, "code": doc.code, "revision": rev.revision_code,
    })
    lib.conta_apertura(doc)
    if rev.source_type == SourceType.SHAREPOINT and rev.source_url:
        return redirect(rev.source_url)
    if rev.source_type == SourceType.FILESERVER and rev.source_path and not _SUPERATO_RE.search(rev.source_path):
        path = _safe_sgi_pdf(rev.source_path)
        if path is not None:
            try:
                response = FileResponse(open(path, "rb"), content_type="application/pdf", filename=(rev.file_name or path.name))
            except OSError:
                path = None
            else:
                response["Content-Disposition"] = response["Content-Disposition"].replace("attachment", "inline")
                response["X-Content-Type-Options"] = "nosniff"
                return response
        motivo = lib.perche_file_non_apribile(rev.source_path)
        logger.warning("CN-SGI: %s non apribile (%s): %s", doc.code, motivo, rev.source_path)
        return render(request, "procedure_refresh/libreria/file_non_disponibile.html", {
            "doc": doc, "rev": rev, "motivo": motivo, "is_manager": _vis.gestore,
        }, status=503 if motivo == "permesso" else 404)
    raise Http404("File non disponibile.")


@login_required
@require_POST
def segnala(request, pk: int):
    """Segnalazione di modifica dalla scheda: arriva a chi gestisce CN-SGI. La share non cambia."""
    from .models import ProcedureChangeRequest

    _vis, _config, doc, rev = _documento_visibile(request, pk)
    testo = (request.POST.get("testo") or "").strip()[:4000]
    sezione = (request.POST.get("sezione") or "").strip()[:40]
    if not testo:
        messages.error(request, "Scrivi cosa cambieresti nel documento.")
        return redirect("procedure_refresh:libreria_documento", pk=doc.pk)
    if sezione:
        testo = f"[{sezione}] {testo}"
    cr = ProcedureChangeRequest.objects.create(document=doc, revision=rev, created_by=request.user, testo=testo)
    from .segnalazioni import avvisa_nuova

    avvisa_nuova(cr, escludi_user_id=request.user.pk)
    log_action(request, "segnalazione_modifica", "procedure_refresh", {
        "message": "Segnalazione di modifica dalla libreria CN-SGI", "document_id": doc.pk, "code": doc.code, "segnalazione_id": cr.pk,
    })
    messages.success(request, f"Segnalazione su {doc.code} inviata a chi gestisce CN-SGI.")
    return redirect("procedure_refresh:libreria_documento", pk=doc.pk)


# ---------------------------------------------------------------------------
# Gestione: chi vede cosa, scaffali
# ---------------------------------------------------------------------------


def _solo_gestori(request):
    if not _can_manage(request):
        messages.error(request, "Solo chi gestisce CN-SGI può aprire questa pagina.")
        return redirect("procedure_refresh:libreria")
    return None


def _ruoli_attivi():
    from core.models import AccessGroup

    return list(AccessGroup.objects.filter(is_active=True).order_by("-priority", "label"))


@login_required
@con_guida
def visibilita(request):
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    config = lib.scaffali_configurati()
    docs = lib.documenti_in_vigore()
    scaffali = _scaffali(docs, {k: v for k, v in config.items()}, {})
    for d in docs:
        d.sezione_label = lib.etichetta_sezione(d.sezione)

    if request.method == "POST":
        return _salva_regola(request, scaffali, docs)

    regole = list(SgiVisibilita.objects.select_related("documento").prefetch_related("ruoli"))
    tutti = lib.visibilita_di_tutti()
    per_regola: dict[int, int] = {}
    for d in docs:
        r = tutti.regola(d)
        if r is not None:
            per_regola[r.pk] = per_regola.get(r.pk, 0) + 1
    for r in regole:
        s = scaffali.get(r.scaffale)
        r.scaffale_nome = s.nome if s else (lib.identita_da_cartella(r.scaffale)["nome"])
        r.sezione_label = lib.etichetta_sezione(r.sezione) if r.sezione else ""
        r.n_documenti = per_regola.get(r.pk, 0)
    riservati = sum(1 for d in docs if tutti.regola(d) is not None)

    modifica = None
    if request.GET.get("modifica", "").isdigit():
        modifica = next((r for r in regole if r.pk == int(request.GET["modifica"])), None)
    return render(request, "procedure_refresh/libreria/visibilita.html", {
        "is_manager": True,
        "regole": regole,
        "scaffali": list(scaffali.values()),
        "documenti": docs,
        "ruoli": _ruoli_attivi(),
        "riservati": riservati,
        "totale": len(docs),
        "modifica": modifica,
        "modifica_ruoli": {g.pk for g in modifica.ruoli.all()} if modifica else set(),
        "chi_choices": SgiVisibilitaChi.choices,
    })


def _salva_regola(request, scaffali, docs):
    cartella = request.POST.get("scaffale", "")
    sezione = request.POST.get("sezione", "")
    doc_id = request.POST.get("documento", "")
    chi = request.POST.get("chi", SgiVisibilitaChi.RUOLI)
    ruoli_ids = [int(x) for x in request.POST.getlist("ruoli") if x.isdigit()]
    note = (request.POST.get("note") or "").strip()[:300]
    url = reverse("procedure_refresh:libreria_visibilita")

    s = scaffali.get(cartella)
    if s is None:
        messages.error(request, "Scegli uno scaffale.")
        return redirect(url)
    documento = None
    if doc_id.isdigit():
        documento = next((d for d in docs if d.pk == int(doc_id) and (d.category or "") == cartella), None)
        if documento is None:
            messages.error(request, "Il documento scelto non è in questo scaffale.")
            return redirect(url)
        sezione = ""
    elif sezione and sezione not in {raw for raw, _l, _n in s.sezioni}:
        messages.error(request, "La sezione scelta non è in questo scaffale.")
        return redirect(url)
    if chi not in SgiVisibilitaChi.values:
        chi = SgiVisibilitaChi.RUOLI
    from core.models import AccessGroup

    ruoli = list(AccessGroup.objects.filter(pk__in=ruoli_ids, is_active=True))
    if chi == SgiVisibilitaChi.RUOLI and not ruoli:
        messages.error(request, "Scegli almeno un ruolo, oppure «Solo chi gestisce CN-SGI».")
        return redirect(url)

    with transaction.atomic():
        regola = SgiVisibilita.objects.filter(scaffale=cartella, sezione=sezione, documento=documento).first()
        nuova = regola is None
        if nuova:
            regola = SgiVisibilita(scaffale=cartella, sezione=sezione, documento=documento)
        regola.chi = chi
        regola.note = note
        regola.aggiornata_da = request.user
        regola.save()
        regola.ruoli.set(ruoli if chi == SgiVisibilitaChi.RUOLI else [])
    cache.delete("cnsgi_codici_riservati")

    dove = documento.code if documento else (f"{s.nome} › {lib.etichetta_sezione(sezione)}" if sezione else s.nome)
    chi_txt = ", ".join(g.label for g in ruoli) if chi == SgiVisibilitaChi.RUOLI else "solo chi gestisce CN-SGI"
    log_action(request, "visibilita", "procedure_refresh", {
        "message": "Regola di visibilità CN-SGI " + ("creata" if nuova else "modificata"),
        "dove": dove, "chi": chi_txt, "regola_id": regola.pk,
    })
    messages.success(request, f"Regola salvata: {dove} → {chi_txt}.")
    return redirect(url)


@login_required
@require_POST
def visibilita_elimina(request, pk: int):
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    regola = get_object_or_404(SgiVisibilita, pk=pk)
    dettaglio = str(regola)
    regola.delete()
    cache.delete("cnsgi_codici_riservati")
    log_action(request, "visibilita", "procedure_refresh", {"message": "Regola di visibilità CN-SGI tolta", "regola": dettaglio})
    messages.success(request, "Regola tolta: quei documenti tornano visibili secondo le regole rimaste.")
    return redirect("procedure_refresh:libreria_visibilita")


@login_required
@con_guida
def scaffali_gestione(request):
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    from sistema_gestione.models import Certificazione

    if request.method == "POST":
        if request.POST.get("azione") == "allinea":
            nuovi = lib.assicura_scaffali()
            sezioni = lib.aggiorna_sezioni()
            messages.success(request, f"Allineato dal database: {nuovi} scaffali nuovi, {sezioni} documenti con sezione aggiornata.")
            return redirect("procedure_refresh:libreria_scaffali")
        cert_ids = set(Certificazione.objects.values_list("pk", flat=True))
        for s in SgiScaffale.objects.all():
            p = f"s{s.pk}_"
            if p + "nome" not in request.POST:
                continue
            s.nome = (request.POST.get(p + "nome") or s.nome).strip()[:120] or s.nome
            s.sigla = (request.POST.get(p + "sigla") or "").strip()[:20]
            s.norma = (request.POST.get(p + "norma") or "").strip()[:160]
            colore = (request.POST.get(p + "colore") or "").strip()
            if len(colore) == 7 and colore.startswith("#"):
                s.colore = colore
            ordine = request.POST.get(p + "ordine", "")
            s.ordine = int(ordine) if ordine.isdigit() else s.ordine
            cert = request.POST.get(p + "certificazione", "")
            s.certificazione_id = int(cert) if cert.isdigit() and int(cert) in cert_ids else None
            s.attivo = bool(request.POST.get(p + "attivo"))
            icona = (request.POST.get(p + "icona") or "").strip()
            s.icona = icona if icona in ICONE_NOMI else ""
            if request.POST.get(p + "togli_logo"):
                togli_logo(s)
            elif request.FILES.get(p + "logo"):
                try:
                    salva_logo(s, request.FILES[p + "logo"])
                except CopertinaNonValida as exc:
                    messages.error(request, f"{s.nome}: {exc}")
            s.save()
        log_action(request, "modifica", "procedure_refresh", {"message": "Scaffali CN-SGI aggiornati"})
        messages.success(request, "Scaffali salvati.")
        return redirect("procedure_refresh:libreria_scaffali")

    conteggi: dict[str, int] = {}
    for d in lib.documenti_in_vigore():
        conteggi[d.category or ""] = conteggi.get(d.category or "", 0) + 1
    righe = list(SgiScaffale.objects.select_related("certificazione"))
    for r in righe:
        r.n_documenti = conteggi.get(r.cartella, 0)
    for r in righe:
        r.logo_url = lib._logo_url(r)
    return render(request, "procedure_refresh/libreria/scaffali.html", {
        "is_manager": True,
        "righe": righe,
        "icone": ICONE,
        "certificazioni": list(Certificazione.objects.filter(attiva=True).order_by("norma", "ente")),
        "senza_cartella": conteggi.get("", 0),
    })


@login_required
def scaffale_logo(request, pk: int):
    """Logo della copertina di uno scaffale (storage privato, solo utenti del portale)."""
    s = get_object_or_404(SgiScaffale, pk=pk)
    return risposta_logo(s.logo)


# ---------------------------------------------------------------------------
# Fase 2: collegamenti ai moduli dell'HUB, pacchetto audit
# ---------------------------------------------------------------------------


@login_required
@con_guida
def collegamenti_moduli(request):
    """Gestione dei collegamenti procedura ↔ modulo dell'HUB, con le proposte da confermare."""
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    from . import collegamenti as col
    from .models import SgiDocumentoModulo

    docs = lib.documenti_in_vigore()
    per_id = {d.pk: d for d in docs}
    url = reverse("procedure_refresh:libreria_collegamenti")

    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "conferma":
            n = 0
            for valore in request.POST.getlist("proposta"):
                doc_id, _sep, resto = valore.partition(":")
                modulo, _sep, compila = resto.partition(":")
                if not doc_id.isdigit() or int(doc_id) not in per_id or modulo not in col.PER_CHIAVE:
                    continue
                _riga, creato = SgiDocumentoModulo.objects.get_or_create(
                    documento=per_id[int(doc_id)], modulo=modulo,
                    defaults={"compila": compila == "1", "origine": SgiDocumentoModulo.ORIGINE_PROPOSTA, "creato_da": request.user},
                )
                n += int(creato)
            col.svuota_cache()
            log_action(request, "modifica", "procedure_refresh", {"message": "Collegamenti CN-SGI confermati", "n": n})
            messages.success(request, f"Collegamenti confermati: {n}.")
        elif azione == "aggiungi":
            doc_id = request.POST.get("documento", "")
            modulo = request.POST.get("modulo", "")
            if not doc_id.isdigit() or int(doc_id) not in per_id or modulo not in col.PER_CHIAVE:
                messages.error(request, "Scegli un documento e un modulo.")
                return redirect(url)
            riga, creato = SgiDocumentoModulo.objects.get_or_create(
                documento=per_id[int(doc_id)], modulo=modulo, defaults={"creato_da": request.user},
            )
            riga.compila = bool(request.POST.get("compila"))
            riga.save(update_fields=["compila"])
            col.svuota_cache()
            log_action(request, "modifica", "procedure_refresh", {
                "message": "Collegamento CN-SGI " + ("creato" if creato else "aggiornato"),
                "documento": riga.documento.code, "modulo": modulo,
            })
            messages.success(request, f"{riga.documento.code} collegato a {col.PER_CHIAVE[modulo].nome}.")
        elif azione == "togli":
            riga = SgiDocumentoModulo.objects.filter(pk=request.POST.get("riga") or 0).select_related("documento").first()
            if riga is not None:
                dettaglio = f"{riga.documento.code} → {riga.modulo}"
                riga.delete()
                col.svuota_cache()
                log_action(request, "modifica", "procedure_refresh", {"message": "Collegamento CN-SGI tolto", "collegamento": dettaglio})
                messages.success(request, "Collegamento tolto.")
        return redirect(url)

    righe = list(SgiDocumentoModulo.objects.select_related("documento").order_by("modulo", "documento__code"))
    gruppi = []
    for m in col.MODULI_HUB:
        mie = [r for r in righe if r.modulo == m.chiave]
        if mie:
            gruppi.append({"modulo": m, "righe": mie})
    return render(request, "procedure_refresh/libreria/collegamenti.html", {
        "is_manager": True,
        "gruppi": gruppi,
        "n_collegamenti": len(righe),
        "proposte": col.proposte(docs),
        "documenti": docs,
        "moduli": col.MODULI_HUB,
    })


@login_required
@con_guida
def audit(request, slug: str):
    """Pacchetto per l'audit di uno scaffale: revisioni in vigore, processi, presa visione. Esporta in Excel."""
    from django.db.models import Count, Q

    vis, config, docs = _visibili(request)
    if not (vis.gestore or vis.vede_tutto):
        messages.error(request, "Il pacchetto audit è per chi gestisce CN-SGI e per i ruoli che vedono tutto.")
        return redirect("procedure_refresh:libreria")
    nuove = lib.codici_nuove_revisioni()
    scaffali = _scaffali(docs, config, nuove)
    corrente = next((s for s in scaffali.values() if s.slug == slug), None)
    if corrente is None:
        raise Http404("Scaffale non disponibile.")
    _decora(docs, scaffali, nuove, {})
    miei = sorted((d for d in docs if (d.category or "") == corrente.cartella), key=lambda d: ((d.sezione or "") == "", (d.sezione or "").lower(), d.code))

    stato = {
        r["revision_id"]: r
        for r in ProcedureAssignment.objects.filter(revision_id__in=[d.rev.pk for d in miei])
        .exclude(status=AssignmentStatus.CANCELLED)
        .values("revision_id")
        .annotate(totale=Count("id"), lette=Count("id", filter=Q(status=AssignmentStatus.READ_CONFIRMED)))
    }
    processi: dict[int, list[str]] = {}
    for p in SgiDocumentoProcesso.objects.filter(documento__in=miei, confermato=True).select_related("processo"):
        processi.setdefault(p.documento_id, []).append(str(p.processo))
    oggi = timezone.localdate()
    anno_fa = oggi - timedelta(days=365)
    tot_assegnate = tot_lette = 0
    for d in miei:
        s = stato.get(d.rev.pk) or {"totale": 0, "lette": 0}
        d.pv_totale, d.pv_lette = s["totale"], s["lette"]
        d.pv_pct = round(d.pv_lette * 100 / d.pv_totale) if d.pv_totale else None
        d.processi = processi.get(d.pk, [])
        tot_assegnate += d.pv_totale
        tot_lette += d.pv_lette

    if request.GET.get("formato") == "xlsx":
        from core.excel_export import make_xlsx_response

        log_action(request, "esporta", "procedure_refresh", {"message": "Pacchetto audit CN-SGI in Excel", "scaffale": corrente.cartella})
        return make_xlsx_response(
            filename=f"pacchetto-audit-{corrente.slug}-{oggi:%Y%m%d}.xlsx",
            columns=["Sezione", "Codice", "Titolo", "Revisione", "Data revisione", "Processi", "Prese visione confermate", "Prese visione chieste"],
            rows=[[d.sezione_label, d.code, d.title, d.rev.revision_code,
                   d.rev.revision_date.strftime("%d/%m/%Y") if d.rev.revision_date else "",
                   ", ".join(d.processi), d.pv_lette, d.pv_totale] for d in miei],
            title=f"Pacchetto audit · {corrente.nome}" + (f" · {corrente.norma}" if corrente.norma else ""),
        )

    cert = corrente.certificazione
    return render(request, "procedure_refresh/libreria/audit.html", _contesto_base(
        request, vis, docs,
        scaffale=corrente,
        scaffali_audit=list(scaffali.values()),
        documenti=miei,
        revisionati_anno=sum(1 for d in miei if d.rev.revision_date and d.rev.revision_date >= anno_fa),
        pct_lette=round(tot_lette * 100 / tot_assegnate) if tot_assegnate else None,
        giorni_sorveglianza=(cert.prossima_sorveglianza - oggi).days if cert and cert.prossima_sorveglianza else None,
    ))


# ---------------------------------------------------------------------------
# Secondo giro di UI: preferiti, etichette QR, da rivedere
# ---------------------------------------------------------------------------


@login_required
@require_POST
def rilettura(request, pk: int):
    """«Chiedi la rilettura»: presa visione della revisione in vigore per chi aveva letto le precedenti."""
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    _vis, _config, doc, rev = _documento_visibile(request, pk)
    giorni = request.POST.get("giorni", "")
    campagna, n = _segn.crea_rilettura(
        doc, rev, da_utente=request.user, giorni=int(giorni) if giorni.isdigit() else _segn.GIORNI_RILETTURA,
    )
    if campagna is None:
        messages.info(request, f"Nessuno da avvisare: chi aveva letto {doc.code} ha già la nuova revisione da leggere.")
        return redirect("procedure_refresh:libreria_documento", pk=doc.pk)
    log_action(request, "assegna", "procedure_refresh", {
        "message": "Rilettura CN-SGI creata", "document_id": doc.pk, "code": doc.code, "campaign_id": campagna.pk, "persone": n,
    })
    messages.success(request, f"Rilettura di {doc.code} chiesta a {n} person{'a' if n == 1 else 'e'}, entro il {campagna.due_date:%d/%m/%Y}.")
    return redirect("procedure_refresh:campaign_detail", pk=campagna.pk)


@login_required
@require_POST
def preferito(request, pk: int):
    """Mette o toglie il documento da «I miei documenti» (stella nella scheda)."""
    from .models import SgiPreferito

    _vis, _config, doc, _rev = _documento_visibile(request, pk)
    riga = SgiPreferito.objects.filter(user=request.user, documento=doc).first()
    if riga is not None:
        riga.delete()
        attivo = False
    else:
        SgiPreferito.objects.get_or_create(user=request.user, documento=doc)
        attivo = True
    if getattr(request, "htmx", False):
        return render(request, "procedure_refresh/libreria/_stella.html", {"doc": doc, "preferito": attivo})
    messages.success(request, f"{doc.code} {'aggiunto a' if attivo else 'tolto da'} «I miei documenti».")
    return redirect("procedure_refresh:libreria_documento", pk=doc.pk)


def _etichetta(request, d) -> dict:
    url = request.build_absolute_uri(reverse("procedure_refresh:libreria_documento", args=[d.pk]))
    return {"doc": d, "url": url, "qr": esp.qr_svg(url)}


@login_required
def etichetta(request, pk: int):
    """Etichetta stampabile con QR e codice di un documento, da affiggere in reparto."""
    _vis, config, doc, _rev = _documento_visibile(request, pk)
    doc.scaffale = lib.scaffale_da(doc.category or "", config)
    return render(request, "procedure_refresh/libreria/etichette.html", {
        "etichette": [_etichetta(request, doc)], "titolo": f"Etichetta {doc.code}",
        "torna": reverse("procedure_refresh:libreria_documento", args=[doc.pk]),
    })


@login_required
def etichette_scaffale(request, slug: str):
    """Etichette QR di tutto uno scaffale o di una sua sezione (``?sezione=``)."""
    vis, config, docs = _visibili(request)
    nuove = lib.codici_nuove_revisioni()
    scaffali = _scaffali(docs, config, nuove)
    corrente = next((s for s in scaffali.values() if s.slug == slug), None)
    if corrente is None:
        raise Http404("Scaffale non disponibile.")
    _decora(docs, scaffali, nuove, {})
    sezione = request.GET.get("sezione")
    elenco = [d for d in docs if (d.category or "") == corrente.cartella and (sezione is None or (d.sezione or "") == sezione)]
    elenco.sort(key=lambda d: ((d.sezione or "") == "", (d.sezione or "").lower(), d.code))
    return render(request, "procedure_refresh/libreria/etichette.html", {
        "etichette": [_etichetta(request, d) for d in elenco[:120]],
        "titolo": f"Etichette · {corrente.nome}" + (f" · {lib.etichetta_sezione(sezione)}" if sezione is not None else ""),
        "torna": reverse("procedure_refresh:libreria_scaffale", args=[corrente.slug]),
    })


@login_required
@con_guida
def da_rivedere(request):
    """Per chi gestisce: documenti non revisionati da anni e codici citati che non esistono."""
    blocco = _solo_gestori(request)
    if blocco:
        return blocco
    vis, config, docs = _visibili(request)
    nuove = lib.codici_nuove_revisioni()
    scaffali = _scaffali(docs, config, nuove)
    _decora(docs, scaffali, nuove, {})
    oggi = timezone.localdate()
    vecchi = esp.da_rivedere(docs)
    for d in vecchi:
        d.anni = round((oggi - d.rev.revision_date).days / 365, 1)
    return render(request, "procedure_refresh/libreria/da_rivedere.html", _contesto_base(
        request, vis, docs,
        vecchi=vecchi,
        anni=esp.ANNI_DA_RIVEDERE,
        mancanti=esp.citati_mancanti(),
    ))
