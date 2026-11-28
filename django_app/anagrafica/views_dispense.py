"""«Corsi e dispense»: libreria delle dispense per i dipendenti (stanza Sapere, stile CN-SGI).

Rotte sotto ``/anagrafica/formazione/corsi-online/dispense/`` (prefisso condiviso dell'area
discente, ``core/middleware._ACL_SHARED_PREFIXES``): aperte a chi ha fatto l'accesso, chi vede
cosa è deciso qui (``services/dispense``). Le impostazioni della dispensa (visibilità, titolo,
«Ho letto») sono di chi gestisce la formazione, con ACL dalla rotta ``formazione_allegato_delete``.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from .models_formazione import TrainingAttachment, TrainingCourse, TrainingCourseType
from .services import dispense as srv

logger = logging.getLogger(__name__)


def _scaffali(atts) -> list[dict]:
    """Uno scaffale per tipo di corso con almeno una dispensa visibile."""
    per = {}
    oggi = timezone.localdate()
    for a in atts:
        sc = srv.scaffale_di(a.corso)
        s = per.setdefault(sc["id"], {**sc, "corsi": set(), "dispense": 0, "nuove": 0,
                                      "ordine": getattr(a.corso.tipo, "ordine", 999) if a.corso.tipo_id else 999})
        s["corsi"].add(a.corso_id)
        s["dispense"] += 1
        if (oggi - timezone.localtime(a.created_at).date()).days <= srv.GIORNI_NUOVE:
            s["nuove"] += 1
    out = sorted(per.values(), key=lambda s: (s["ordine"], s["nome"].casefold()))
    for s in out:
        s["n_corsi"] = len(s.pop("corsi"))
    return out


def _schede_corsi(corsi_ids, atts_per_corso, stati) -> list[dict]:
    corsi = TrainingCourse.objects.filter(pk__in=list(corsi_ids)).select_related("tipo").order_by("titolo")
    out = []
    for c in corsi:
        sc = srv.scaffale_di(c)
        dd = atts_per_corso.get(c.pk, [])
        out.append({"corso": c, "pk": c.pk, "code": c.codice, "title": c.titolo,
                    "scaffale": {"colore": sc["colore"], "sigla": sc["sigla"]},
                    "rev": {"revision_code": "", "revision_date": max((a.created_at for a in dd), default=None)},
                    "sezione_label": "",
                    "stato": stati.get(c.pk), "n": len(dd)})
    return out


@login_required
@require_GET
def dispense_libreria(request):
    ctx = srv.Contesto.da_request(request)
    atts = list(srv.visibili(ctx).order_by("-created_at", "-pk"))
    letture = srv.letture_di(ctx.legacy_id, [a.pk for a in atts])
    q = (request.GET.get("q") or "").strip()
    if q:
        srv.assicura_testi(atts)
        risultati = srv.cerca(q, atts)
        for r in risultati:
            r["d"] = srv.scheda(r["a"], letture=letture)
        return render(request, "anagrafica/dispense/libreria.html", {
            "page_title": "Corsi e dispense", "q": q, "risultati": risultati, "cerca": True})
    aperture = srv.aperture_recenti()
    schede = [srv.scheda(a, letture=letture, aperture=aperture) for a in atts]
    per_corso: dict[int, list] = {}
    for a in atts:
        per_corso.setdefault(a.corso_id, []).append(a)
    miei = [cid for cid in per_corso if cid in ctx.corsi]
    stati = srv.stato_corsi(ctx.legacy_id, miei)
    da_leggere = [d for d in schede if d["da_leggere"] and d["a"].corso_id in ctx.corsi]
    return render(request, "anagrafica/dispense/libreria.html", {
        "page_title": "Corsi e dispense",
        "scaffali": _scaffali(atts),
        "miei": _schede_corsi(miei, per_corso, stati),
        "da_leggere": da_leggere[:12],
        "nuove": [d for d in schede if d["nuova"]][:12],
        "consultate": sorted([d for d in schede if d["aperture"]], key=lambda d: -d["aperture"])[:12],
        "n_corsi": len(per_corso), "n_dispense": len(atts), "n_da_leggere": len(da_leggere),
    })


@login_required
@require_GET
def dispense_scaffale(request, tipo_id: int):
    ctx = srv.Contesto.da_request(request)
    tutte = list(srv.visibili(ctx))
    scaffali = _scaffali(tutte)
    scaffale = next((s for s in scaffali if s["id"] == tipo_id), None)
    if scaffale is None:
        if tipo_id and not TrainingCourseType.objects.filter(pk=tipo_id).exists():
            raise Http404()
        return redirect("anagrafica:dispense_libreria")
    atts = [a for a in tutte if srv.scaffale_di(a.corso)["id"] == tipo_id]
    per_corso: dict[int, list] = {}
    for a in atts:
        per_corso.setdefault(a.corso_id, []).append(a)
    filtro = (request.GET.get("q") or "").strip().casefold()
    corsi = _schede_corsi(per_corso, per_corso, srv.stato_corsi(ctx.legacy_id, per_corso))
    if filtro:
        corsi = [c for c in corsi if filtro in f"{c['code']} {c['title']}".casefold()]
    return render(request, "anagrafica/dispense/scaffale.html", {
        "page_title": f"{scaffale['nome']} · Corsi e dispense", "scaffale": scaffale, "scaffali": scaffali,
        "corsi": corsi, "filtro": request.GET.get("q", ""),
    })


def _azioni_corso(corso, ctx) -> list[dict]:
    """Il passo utile per la persona: corso online o lezione online dell'edizione."""
    out = []
    if not ctx.legacy_id:
        return out
    try:
        from .services.sessione_online import lezioni_della_persona
        for lz in lezioni_della_persona(ctx.legacy_id):
            if lz["sessione"].corso_id == corso.pk and not lz["finita"]:
                out.append({"label": "Vai alla lezione online", "url": lz["url"], "pri": True})
                return out
    except Exception:
        logger.warning("Lezioni online non calcolabili per le dispense", exc_info=True)
    if corso.is_elearning:
        from .services.elearning_fruizione import corso_pubblicato
        if corso_pubblicato(corso):
            fatto = srv.stato_corsi(ctx.legacy_id, [corso.pk]).get(corso.pk, {}).get("tono") == "ok"
            out.append({"label": "Rivedi il corso online" if fatto else "Fai il corso online",
                        "url": reverse("anagrafica:formazione_online_player", args=[corso.pk]), "pri": not fatto})
    return out


@login_required
@require_GET
def dispense_corso(request, corso_id: int):
    ctx = srv.Contesto.da_request(request)
    corso = get_object_or_404(TrainingCourse.objects.select_related("tipo"), pk=corso_id)
    atts = list(srv.visibili(ctx).filter(corso=corso).order_by("tipo", "titolo", "pk"))
    if not atts:
        raise Http404("Nessuna dispensa per questo corso")
    letture = srv.letture_di(ctx.legacy_id, [a.pk for a in atts])
    schede = [srv.scheda(a, letture=letture) for a in atts]
    scelta = None
    if (request.GET.get("d") or "").isdigit():
        scelta = next((d for d in schede if d["pk"] == int(request.GET["d"])), None)
    scelta = scelta or schede[0]
    pagina = request.GET.get("p") if (request.GET.get("p") or "").isdigit() else ""
    return render(request, "anagrafica/dispense/corso.html", {
        "page_title": f"{corso.codice} · Corsi e dispense", "corso": corso, "scaffale": srv.scaffale_di(corso),
        "stato": srv.stato_corsi(ctx.legacy_id, [corso.pk]).get(corso.pk), "azioni": _azioni_corso(corso, ctx),
        "dispense": schede, "scelta": scelta, "pagina": pagina, "puo_confermare": bool(ctx.legacy_id),
        "is_gestore": ctx.tutto,
    })


@login_required
@require_GET
@xframe_options_sameorigin
def dispensa_file(request, attachment_id: int):
    """Il file della dispensa: in linea per PDF e immagini (lettore), ``?scarica=1`` come allegato."""
    ctx = srv.Contesto.da_request(request)
    att = get_object_or_404(TrainingAttachment.objects.select_related("corso"), pk=attachment_id)
    if not srv.puo_vedere(att, ctx) or not att.file:
        raise Http404()
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        return HttpResponse("File non trovato sul server.", status=404)
    scarica = request.GET.get("scarica") == "1"
    srv.registra_apertura(att, request, ctx.legacy_id)
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_DISPENSA_APERTA", "anagrafica",
                   {"attachment_id": att.pk, "corso_id": att.corso_id, "scarica": scarica})
    except Exception:
        logger.warning("Audit FORMAZIONE_DISPENSA_APERTA fallito", exc_info=True)
    from core.download_security import harden_file_response
    nome = att.nome_originale or f"dispensa_{att.pk}.pdf"
    resp = FileResponse(fh, as_attachment=scarica, filename=nome)
    resp["Cache-Control"] = "private, no-store"
    return harden_file_response(resp, nome, inline=not scarica)


@login_required
@require_POST
def dispensa_letta(request, attachment_id: int):
    ctx = srv.Contesto.da_request(request)
    att = get_object_or_404(TrainingAttachment.objects.select_related("corso"), pk=attachment_id)
    if not srv.puo_vedere(att, ctx):
        raise Http404()
    if not ctx.legacy_id:
        messages.error(request, "Il tuo profilo non è collegato a un'anagrafica dipendente: la lettura non si può registrare.")
    elif srv.registra_lettura(att, ctx.legacy_id, request.user):
        try:
            from core.audit import log_action
            log_action(request, "FORMAZIONE_DISPENSA_LETTA", "anagrafica", {"attachment_id": att.pk, "corso_id": att.corso_id})
        except Exception:
            logger.warning("Audit FORMAZIONE_DISPENSA_LETTA fallito", exc_info=True)
        messages.success(request, f"Lettura di «{att.nome_visibile}» registrata nel tuo libretto formativo.")
    url = reverse("anagrafica:dispense_corso", args=[att.corso_id]) + f"?d={att.pk}"
    return redirect(url)


@login_required
@require_POST
def formazione_allegato_dispensa(request, attachment_id: int):
    """Impostazioni della dispensa dalla scheda corso: titolo, visibilità, «Ho letto»."""
    from .views._helpers import _can_edit_formazione
    att = get_object_or_404(TrainingAttachment, pk=attachment_id, corso__isnull=False)
    if not _can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare il materiale del corso.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=att.corso_id)
    if att.tipo == TrainingAttachment.Tipo.REGISTRO_FIRMATO:
        messages.error(request, "Un registro firme non si rende visibile ai dipendenti.")
        return redirect("anagrafica:formazione_corso_detail", corso_id=att.corso_id)
    si = lambda k: request.POST.get(k) in ("1", "on", "true")  # noqa: E731
    att.titolo = (request.POST.get("titolo") or "").strip()[:200]
    att.visibile_dipendenti = si("visibile")
    att.solo_chi_ha_corso = si("solo_chi_ha_corso")
    att.richiedi_lettura = si("richiedi_lettura")
    att.save(update_fields=["titolo", "visibile_dipendenti", "solo_chi_ha_corso", "richiedi_lettura"])
    if att.visibile_dipendenti and att.testo_estratto_il is None:
        srv.estrai_testo(att)
    try:
        from core.audit import log_action
        log_action(request, "FORMAZIONE_DISPENSA_IMPOSTATA", "anagrafica", {
            "attachment_id": att.pk, "corso_id": att.corso_id, "visibile": att.visibile_dipendenti,
            "solo_chi_ha_corso": att.solo_chi_ha_corso, "richiedi_lettura": att.richiedi_lettura})
    except Exception:
        logger.warning("Audit FORMAZIONE_DISPENSA_IMPOSTATA fallito", exc_info=True)
    messages.success(request, f"«{att.nome_visibile}»: " + ("visibile ai dipendenti." if att.visibile_dipendenti else "solo per chi gestisce la formazione."))
    return redirect(reverse("anagrafica:formazione_corso_detail", args=[att.corso_id]) + "#materiale-corso")
