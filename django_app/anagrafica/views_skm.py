"""Skill Matrix: scheda della cella e azioni dalla matrice (28/11/2026).

- ``skm_scheda`` (GET, parziale HTMX): persona × mansione con livello, richiesto,
  revisione, stato e storico; per chi gestisce i comandi di modifica.
- ``skm_azione`` (POST, permesso «Skill Matrix - Gestisci»): cambia livello, abilita,
  sospendi / riattiva, togli, prossima revisione, orario della persona, revisione in
  blocco. Ogni modifica a un'abilitazione scrive uno scatto nello storico con il
  motivo; le regole sono quelle del Mansionario (``services.mansionario_struttura``),
  così chi ha le competenze definite cambia livello solo da «Valuta».
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .acl_bootstrap import PERM_SKM_MANAGE, PERM_SKM_VIEW
from .models import AbilitazioneMacchina, AbilitazioneMacchinaStorico, CompetenzaSkm, ProfiloMansioniPersona
from .models_skillmatrix import ORARIO_CHOICES
from .services import skillmatrix_vista as vista
from .views.qualifiche import _check_skm_permission


def _abilitazione(lid: int, comp: CompetenzaSkm):
    q = Q(competenza=comp)
    if comp.asset_id:
        q |= Q(asset_id=comp.asset_id)
    return AbilitazioneMacchina.objects.filter(q, legacy_anagrafica_id=lid).order_by("-in_lista", "-pk").first()


def _nome(lid: int) -> str:
    p = vista._persone([lid]).get(lid)
    return p["vista"] if p else f"ID {lid}"


@login_required
def skm_scheda(request):
    if not _check_skm_permission(request, PERM_SKM_VIEW):
        return HttpResponseForbidden("Permesso negato")
    try:
        lid = int(request.GET.get("lid") or 0)
        comp = get_object_or_404(CompetenzaSkm.objects.select_related("asset", "reparto"), pk=int(request.GET.get("comp") or 0))
    except ValueError:
        return HttpResponseForbidden("Richiesta non valida")
    ab = _abilitazione(lid, comp)
    if ab is not None and not ab.in_lista:
        ab_fuori = ab
        ab = None
    else:
        ab_fuori = None
    q = Q(competenza=comp)
    if comp.asset_id:
        q |= Q(asset_id=comp.asset_id)
    storico = list(AbilitazioneMacchinaStorico.objects.filter(q, legacy_anagrafica_id=lid)
                   .order_by("-data_rilevazione", "-id")[:6])
    from .models import SkillMatrixConfig, VoceMacchinaCatalogo
    config = SkillMatrixConfig.get_instance()
    profilo = ProfiloMansioniPersona.objects.filter(legacy_anagrafica_id=lid).first()
    oggi = timezone.localdate()
    from .services import skillmatrix_requisiti as req
    reqs = req.requisiti_colonne([comp.pk]).get(comp.pk, [])
    esito = req.esito_cella(lid, ab.livello if ab else "", bool(ab and ab.stato != AbilitazioneMacchina.STATO_SOSPESA),
                            reqs, req.stati([lid], {comp.pk: reqs}, oggi=oggi))
    for r in esito["requisiti"]:
        r["url"] = req.url_requisito(r, lid)
    return render(request, "anagrafica/partials/_skm_scheda.html", {
        "requisiti": esito["requisiti"], "da_sospendere": esito["da_sospendere"],
        "lid": lid, "nome": _nome(lid), "comp": comp, "reparto": comp.reparto_effettivo or vista.SENZA_REPARTO,
        "ab": ab, "ab_fuori": ab_fuori, "storico": storico,
        "etichetta": config.etichetta(ab.livello) if ab and ab.livello else "",
        "etichetta_richiesto": config.etichetta(ab.livello_richiesto) if ab and ab.livello_richiesto else "",
        "arretrata": bool(ab and ab.prossima_revisione and ab.prossima_revisione < oggi),
        "con_competenze": VoceMacchinaCatalogo.objects.filter(mansione=comp, attiva=True).exists(),
        "livelli": [(k, config.etichetta(k)) for k in vista.LIVELLI],
        "orario": profilo.orario if profilo else "", "orari": ORARIO_CHOICES,
        "can_manage": _check_skm_permission(request, PERM_SKM_MANAGE),
        "next": request.GET.get("next") or reverse("anagrafica:skill_matrix_macchina"),
    })


def _torna(request, lid=None, comp=None):
    from core.redirects import safe_next
    url = safe_next(request, request.POST.get("next"), reverse("anagrafica:skill_matrix_macchina"))
    if lid and comp:
        url = url.split("#")[0]
        url += ("&" if "?" in url else "?") + f"apri={lid}-{comp}"
    return redirect(url + "#sm-matrice")


def _scatto(ab: AbilitazioneMacchina, livello: str, nota: str, user) -> None:
    chi = (getattr(user, "username", "") or "").strip()
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=ab.legacy_anagrafica_id, asset_id=ab.asset_id, competenza_id=ab.competenza_id,
        livello=livello, data_rilevazione=timezone.localdate(), fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
        note=(f"Skill Matrix: {nota}" + (f" ({chi})" if chi else ""))[:255],
    )


@login_required
@require_POST
def skm_azione(request):
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        messages.error(request, "Non hai i permessi per modificare la Skill Matrix.")
        return _torna(request)
    from .services import mansionario_struttura as ms

    azione = request.POST.get("azione") or ""
    motivo = (request.POST.get("motivo") or "").strip()

    if azione == "revisione_blocco":
        ids = [int(x) for x in (request.POST.get("persone") or "").split(",") if x.strip().isdigit()]
        try:
            giorno = date.fromisoformat(request.POST.get("data") or "")
        except ValueError:
            messages.error(request, "Data della revisione non valida.")
            return _torna(request)
        n = AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=ids, in_lista=True).update(prossima_revisione=giorno)
        messages.success(request, f"Prossima rivalutazione al {giorno:%d/%m/%Y} per {n} abilitazioni di {len(ids)} persone.")
        return _torna(request)

    try:
        lid = int(request.POST.get("lid") or 0)
        comp = get_object_or_404(CompetenzaSkm, pk=int(request.POST.get("comp") or 0))
    except ValueError:
        messages.error(request, "Richiesta non valida.")
        return _torna(request)

    if azione == "orario":
        valore = request.POST.get("orario") or ""
        if valore not in {k for k, _ in ORARIO_CHOICES} | {""}:
            messages.error(request, "Orario non valido.")
        else:
            profilo, _ = ProfiloMansioniPersona.objects.get_or_create(legacy_anagrafica_id=lid)
            profilo.orario = valore
            profilo.updated_by = request.user
            profilo.save(update_fields=["orario", "updated_at", "updated_by"])
            messages.success(request, f"Orario di {_nome(lid)}: {valore or 'non indicato'}.")
        return _torna(request, lid, comp.pk)

    if azione in ("livello", "abilita", "togli") and not motivo:
        messages.error(request, "Scrivi il motivo: finisce nello storico dell'abilitazione.")
        return _torna(request, lid, comp.pk)

    ab = _abilitazione(lid, comp)
    try:
        with transaction.atomic():
            if azione == "abilita":
                livello = (request.POST.get("livello") or "").upper()
                ab = ms.assegna(comp, legacy_anagrafica_id=lid, livello=livello, user=request.user)
                ultimo = AbilitazioneMacchinaStorico.objects.filter(legacy_anagrafica_id=lid).order_by("-id").first()
                if ultimo is not None:
                    AbilitazioneMacchinaStorico.objects.filter(pk=ultimo.pk).update(
                        note=(f"{ultimo.note} · {motivo}")[:255])
                messages.success(request, f"{_nome(lid)} abilitato su {comp.nome} ({ab.livello}).")
            elif ab is None or not ab.in_lista:
                messages.error(request, "La persona non è in lista su questa mansione.")
            elif azione == "livello":
                prima = ms.cambia_livello(ab, request.POST.get("livello") or "", user=request.user)
                if prima is None:
                    messages.info(request, "Livello invariato.")
                else:
                    ultimo = AbilitazioneMacchinaStorico.objects.filter(legacy_anagrafica_id=lid).order_by("-id").first()
                    AbilitazioneMacchinaStorico.objects.filter(pk=ultimo.pk).update(note=(f"{ultimo.note} · {motivo}")[:255])
                    messages.success(request, f"Livello di {_nome(lid)} su {comp.nome}: {prima or '—'} → {ab.livello}.")
            elif azione == "togli":
                ms.togli(ab)
                ultimo = AbilitazioneMacchinaStorico.objects.filter(legacy_anagrafica_id=lid).order_by("-id").first()
                AbilitazioneMacchinaStorico.objects.filter(pk=ultimo.pk).update(note=(f"{ultimo.note} · {motivo}")[:255])
                messages.success(request, f"{_nome(lid)} tolto da {comp.nome}.")
            elif azione in ("sospendi", "riattiva"):
                nuovo = AbilitazioneMacchina.STATO_SOSPESA if azione == "sospendi" else AbilitazioneMacchina.STATO_ATTIVA
                if ab.stato != nuovo:
                    ab.stato = nuovo
                    ab.save(update_fields=["stato", "updated_at"])
                    _scatto(ab, ab.livello, ("sospesa" if azione == "sospendi" else "riattivata")
                            + (f" · {motivo}" if motivo else ""), request.user)
                messages.success(request, f"Abilitazione {'sospesa' if azione == 'sospendi' else 'riattivata'}.")
            elif azione == "revisione":
                try:
                    giorno = date.fromisoformat(request.POST.get("data") or "")
                except ValueError:
                    messages.error(request, "Data non valida.")
                else:
                    ab.prossima_revisione = giorno
                    ab.save(update_fields=["prossima_revisione", "updated_at"])
                    messages.success(request, f"Prossima rivalutazione al {giorno:%d/%m/%Y}.")
            else:
                messages.error(request, "Azione non riconosciuta.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return _torna(request, lid, comp.pk)


# ---------------------------------------------------------------------------
# Emissioni del MOD.187 (MT CN 06 §8.4-8.5): emetti, elenco, firma, PDF
# ---------------------------------------------------------------------------

def _emissione(pk: int):
    from .models import EmissioneSkm
    return get_object_or_404(EmissioneSkm, pk=pk)


def _firma_contesto(request, e) -> dict:
    """Caselle e comandi di firma dell'emissione (stessa grafica dell'organigramma)."""
    from timbri import firme
    from timbri.models import DocumentoFirma

    from .services import skillmatrix_emissioni as em
    doc = em.documento(e)
    if doc is None:
        return {"doc": None}
    corrente = firme.casella_corrente(doc) if doc.stato == DocumentoFirma.STATO_IN_FIRMA else None
    caselle = []
    for c in doc.caselle.all():
        if c.mittente:
            chi = firme.nome_utente(doc.creato_da) if doc.creato_da else ""
        else:
            chi = ", ".join(firme.nome_utente(u) for u in firme.utenti_del_ruolo(c.ruolo)[:4])
        caselle.append({
            "c": c, "chi": chi, "corrente": corrente is not None and c.pk == corrente.pk,
            "url_firma": reverse("anagrafica:skm_emissione_immagine", args=[c.pk, "firma"]) if c.immagine_firma else "",
            "url_timbro": reverse("anagrafica:skm_emissione_immagine", args=[c.pk, "timbro"]) if c.immagine_timbro else "",
        })
    mia = corrente is not None and firme.puo_firmare_casella(request.user, corrente)
    return {
        "doc": doc, "caselle": caselle, "corrente": corrente, "mia": mia,
        "puo_respingere": mia and not corrente.mittente,
        "opzioni": firme.opzioni(request.user, corrente) if mia else [],
        "usa_totp": firme.usa_totp(request.user),
        "mittente_nome": firme.nome_utente(doc.creato_da) if doc.creato_da else "—",
    }


def contesto_invio(request) -> dict:
    """Per il dialogo «Emetti MOD.187»: caselle richieste e immagini di chi emette."""
    from timbri import firme
    from timbri.models import CasellaFirma

    from .services import skillmatrix_emissioni as em
    imp = firme.impostazione(em.CHIAVE)
    if not imp["attiva"]:
        return {"attiva": False}
    caselle = []
    for c in imp["caselle"]:
        ruolo = None if c["mittente"] else firme._ruolo_della_casella(c)
        persone = [] if c["mittente"] else [firme.nome_utente(u) for u in firme.utenti_del_ruolo(ruolo)]
        caselle.append({**c, "ruolo_obj": ruolo, "persone": persone,
                        "problema": (not c["mittente"]) and (ruolo is None or not persone)})
    prima = caselle[0] if caselle else None
    opzioni = []
    if prima and prima["mittente"]:
        opzioni = firme.opzioni(request.user, CasellaFirma(varianti=",".join(prima["varianti"])))
    return {"attiva": True, "caselle": caselle, "firma_subito": bool(prima and prima["mittente"]),
            "opzioni": opzioni, "usa_totp": firme.usa_totp(request.user)}


@login_required
@require_POST
def skm_emetti(request):
    """Congela la matrice (tutta o un reparto) e la manda in firma: Redazione subito, poi RDD."""
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        return HttpResponseForbidden("Permesso negato")
    from core.audit import log_action
    from timbri import firme

    from .services import skillmatrix_emissioni as em
    reparto = (request.POST.get("reparto") or "").strip()
    try:
        data_emissione = date.fromisoformat((request.POST.get("data_emissione") or "").strip())
    except ValueError:
        data_emissione = timezone.localdate()
    torna = request.POST.get("next") or reverse("anagrafica:skm_emissioni")
    if not torna.startswith("/"):
        torna = reverse("anagrafica:skm_emissioni")
    try:
        e = em.emetti(request, vista.costruisci(reparto=reparto), reparto=reparto, data_emissione=data_emissione,
                      nota=(request.POST.get("nota") or "").strip(), user=request.user)
    except firme.FirmaNegata as exc:
        messages.error(request, str(exc))
        return redirect(torna)
    log_action(request, "skill_matrix_emissione", "anagrafica",
               {"numero": e.numero, "reparto": e.reparto, "stato": e.stato})
    if e.stato == e.STATO_EMESSA:
        messages.success(request, f"MOD.187 n.{e.numero} emesso ({e.ambito}).")
    else:
        doc = em.documento(e)
        if doc is not None:
            firme.avvisa_prossimi(doc, reverse("anagrafica:skm_emissione", args=[e.pk]))
        messages.success(request, f"MOD.187 n.{e.numero} inviato in firma: chi approva ha ricevuto la notifica.")
    return redirect("anagrafica:skm_emissione", pk=e.pk)


@login_required
def skm_emissioni(request):
    """Elenco delle emissioni del MOD.187 con lo stato di ogni reparto."""
    if not _check_skm_permission(request, PERM_SKM_VIEW):
        messages.error(request, "Non hai i permessi per la Skill Matrix.")
        return redirect("anagrafica:index")
    from .models import EmissioneSkm
    from .services import skillmatrix_emissioni as em
    stati = em.stato_reparti(vista.costruisci())
    return render(request, "anagrafica/pages/skm_emissioni.html", {
        "emissioni": list(EmissioneSkm.objects.select_related("creata_da")[:200]),
        "reparti": sorted(stati.items(), key=lambda kv: (not kv[1]["modificata"], kv[0].casefold())),
        "n_da_emettere": sum(1 for v in stati.values() if v["modificata"] and not v["in_firma"]),
        "reparti_nomi": sorted(stati, key=str.casefold),
        "can_manage": _check_skm_permission(request, PERM_SKM_MANAGE),
        "invio": contesto_invio(request),
        "oggi": timezone.localdate(),
        "firma_attiva": em.firma_attiva(),
    })


def _azione_firma(request, e):
    from core.audit import log_action
    from timbri import firme
    from timbri.models import DocumentoFirma

    from .models import EmissioneSkm
    from .services import skillmatrix_emissioni as em
    doc = em.documento(e)
    azione = request.POST.get("azione")
    if doc is None or doc.stato != DocumentoFirma.STATO_IN_FIRMA:
        raise firme.FirmaNegata("Questa emissione non è in firma.")
    url = reverse("anagrafica:skm_emissione", args=[e.pk])
    if azione == "firma":
        doc = firme.firma(request, doc, user=request.user, scelta=request.POST.get("scelta") or "",
                          segreto=request.POST.get("segreto") or "",
                          dichiarazione=request.POST.get("dichiarazione") == "1")
        log_action(request, "skill_matrix_emissione_firmata", "anagrafica", {"numero": e.numero, "impronta": doc.impronta})
        if doc.stato == DocumentoFirma.STATO_FIRMATO:
            if doc.creato_da and doc.creato_da_id != request.user.pk:
                firme.notifica(doc.creato_da, "firma_completata", f"Firmato ed emesso: {doc.titolo}", url)
            messages.success(request, f"Firmato: il MOD.187 n.{e.numero} è emesso.")
        else:
            firme.avvisa_prossimi(doc, url)
            messages.success(request, "Firma apposta: passa alla casella successiva.")
    elif azione == "respingi":
        firme.respingi(doc, user=request.user, motivo=request.POST.get("motivo") or "")
        em.chiudi_senza_firma(e, EmissioneSkm.STATO_RESPINTA)
        log_action(request, "skill_matrix_emissione_respinta", "anagrafica", {"numero": e.numero})
        if doc.creato_da:
            firme.notifica(doc.creato_da, "firma_respinta", f"Respinto: {doc.titolo}", url)
        messages.success(request, "Emissione respinta: chi l'ha emessa riceve il motivo.")
    elif azione == "ritira":
        if not (doc.creato_da_id == request.user.pk or _check_skm_permission(request, PERM_SKM_MANAGE)):
            raise firme.FirmaNegata("Può ritirare solo chi l'ha emessa o chi gestisce la Skill Matrix.")
        firme.ritira(doc, user=request.user, motivo=request.POST.get("motivo") or "")
        em.chiudi_senza_firma(e, EmissioneSkm.STATO_RITIRATA)
        log_action(request, "skill_matrix_emissione_ritirata", "anagrafica", {"numero": e.numero})
        messages.success(request, "Emissione ritirata.")
    else:
        raise firme.FirmaNegata("Azione non riconosciuta.")


@login_required
def skm_emissione(request, pk: int):
    """Un'emissione: riepilogo, cosa cambia dalla precedente, firme; Firma / Respingi / Ritira.

    Firmare e respingere: chi deve firmare la casella in attesa (controllo in
    ``timbri.firme``), anche senza poter gestire la Skill Matrix.
    """
    from timbri import firme

    from .models import EmissioneSkm
    from .services import skillmatrix_emissioni as em
    e = _emissione(pk)
    vede = _check_skm_permission(request, PERM_SKM_VIEW)
    if request.method == "POST":
        try:
            _azione_firma(request, e)
        except firme.FirmaNegata as exc:
            messages.error(request, str(exc))
        return redirect("anagrafica:skm_emissione", pk=e.pk)
    ctx = _firma_contesto(request, e)
    coinvolto = ctx.get("doc") is not None and (ctx["doc"].creato_da_id == request.user.pk or any(
        firme.puo_firmare_casella(request.user, x["c"]) for x in ctx["caselle"]))
    if not (vede or coinvolto):
        messages.error(request, "Non hai i permessi per la Skill Matrix.")
        return redirect("anagrafica:index")
    precedente = EmissioneSkm.objects.filter(stato=EmissioneSkm.STATO_EMESSA, numero__lt=e.numero)
    if e.reparto:
        precedente = precedente.filter(Q(reparto="") | Q(reparto__iexact=e.reparto))
    else:
        precedente = precedente.filter(reparto="")
    precedente = precedente.first()
    prima = em.solo_reparto(precedente.contenuto, e.reparto) if precedente else None
    cambi = em.differenze(prima, e.contenuto)
    return render(request, "anagrafica/pages/skm_emissione.html", {
        "e": e, "precedente": precedente, "cambi": cambi[:300], "n_cambi": len(cambi),
        "n_persone": len(e.contenuto.get("righe", [])), "n_colonne": len(e.contenuto.get("colonne", [])),
        "can_manage": _check_skm_permission(request, PERM_SKM_MANAGE),
        "puo_ritirare": ctx.get("doc") is not None and ctx["doc"].stato == "IN_FIRMA" and (
            ctx["doc"].creato_da_id == request.user.pk
                                                         or _check_skm_permission(request, PERM_SKM_MANAGE)),
        **ctx,
    })


@login_required
def skm_emissione_pdf(request, pk: int):
    """PDF MOD.187 dell'emissione: la copia congelata con la firma di Approvazione nella casella «Firma CEO»."""
    if not _check_skm_permission(request, PERM_SKM_VIEW):
        return HttpResponseForbidden("Permesso negato")
    from django.http import HttpResponse

    from .services import skillmatrix_emissioni as em
    from .services import skillmatrix_pdf as pdf
    e = _emissione(pk)
    doc = em.documento(e)
    firma, firme_testo = None, ""
    if doc is not None:
        firmate = [c for c in doc.caselle.all() if c.stato == c.STATO_FIRMATA]
        firme_testo = " · ".join(f"{c.etichetta}: {c.nome_firmatario} {timezone.localtime(c.firmata_il):%d/%m/%Y}"
                                 for c in firmate if c.firmata_il)
        appr = firmate[-1] if firmate and e.stato == e.STATO_EMESSA else None
        if appr is not None:
            firma = {}
            for chiave, campo in (("firma", appr.immagine_firma), ("timbro", appr.immagine_timbro)):
                if campo:
                    try:
                        with campo.open("rb") as fh:
                            firma[chiave] = fh.read()
                    except (FileNotFoundError, OSError):
                        pass
    if e.stato == e.STATO_EMESSA:
        piede = f"Emissione n.{e.numero} del {e.data_emissione:%d/%m/%Y} · approvata da {e.approvata_da or '—'}"
    else:
        piede = f"Emissione n.{e.numero} · {e.get_stato_display().upper()}: NON VALIDA COME EMISSIONE"
    if firme_testo:
        piede += f" · {firme_testo}"
    if doc is not None:
        piede += f" · codice verifica {doc.codice_verifica}"
    contenuto = pdf.pdf_mod187(e.contenuto, data_documento=e.data_emissione, reparto=e.reparto, firma=firma,
                               piede=piede)
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="MOD.187_emissione_{e.numero}.pdf"'
    return resp


def _apri_file(campo):
    from django.http import Http404
    try:
        return campo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404() from None


@login_required
def skm_emissione_immagine(request, casella_id: int, variante: str):
    """Immagine di firma copiata nella casella di un'emissione."""
    from django.http import FileResponse, Http404

    from timbri import firme
    from timbri.models import CasellaFirma

    from .services import skillmatrix_emissioni as em
    casella = get_object_or_404(CasellaFirma.objects.select_related("documento"), pk=casella_id,
                                documento__tipo=em.CHIAVE)
    vede = _check_skm_permission(request, PERM_SKM_VIEW)
    if not firme.puo_vedere_immagine(request.user, casella, vede_documento=vede,
                                     gestisce=_check_skm_permission(request, PERM_SKM_MANAGE)):
        raise Http404()
    campo = {"firma": casella.immagine_firma, "timbro": casella.immagine_timbro}.get(variante)
    if not campo:
        raise Http404()
    risposta = FileResponse(_apri_file(campo), content_type="image/png")
    risposta["Cache-Control"] = "private, max-age=300"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta


@login_required
def skm_mia_immagine(request, image_id: int):
    """Anteprima di una delle proprie immagini del Registro timbri, per scegliere con cosa firmare."""
    from django.http import FileResponse, Http404

    from timbri import firme
    img = next((i for i in firme.immagini_proprie(request.user).values() if i.pk == image_id), None)
    if img is None:
        raise Http404()
    risposta = FileResponse(_apri_file(img.image), content_type="image/png")
    risposta["Cache-Control"] = "private, no-store"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta
