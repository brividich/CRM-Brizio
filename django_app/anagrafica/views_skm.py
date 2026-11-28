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
    return render(request, "anagrafica/partials/_skm_scheda.html", {
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
