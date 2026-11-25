"""Formazione › Tipi di corso: elenco dei tipi, tipo per piano, piani doppi da accorpare."""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_formazione import TrainingCourseType, TrainingPlan
from .services import formazione_tipi as servizio
from .views import _helpers

logger = logging.getLogger(__name__)


def _nome_utente(user) -> str:
    return (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or "")[:160]


@login_required
def formazione_tipi_corso(request):
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per la sezione formazione.")
        return redirect("anagrafica:index")
    piani = servizio.piani_con_conteggi()
    doppi, prova = servizio.doppioni(), servizio.piani_di_prova()
    return render(request, "anagrafica/pages/formazione_tipi_corso.html", {
        "tipi": servizio.tipi_con_conteggi(),
        "piani": piani,
        "n_senza_tipo": sum(p["senza_tipo"] for p in piani),
        "doppioni": doppi,
        "prova": prova,
        "n_da_rivedere": len(doppi) + len(prova),
        "is_editor": _helpers._can_edit_formazione(request),
        "modifica": request.GET.get("modifica") or "",
    })


@login_required
@require_POST
def formazione_tipi_corso_azione(request):
    if not _helpers._can_edit_formazione(request):
        messages.error(request, "Non hai i permessi per modificare i tipi di corso.")
        return redirect("anagrafica:formazione_tipi_corso")
    p = request.POST
    azione = p.get("azione")
    try:
        if azione in ("crea", "modifica"):
            nome = (p.get("nome") or "").strip()[:80]
            if not nome:
                raise servizio.TipiError("Scrivi il nome del tipo.")
            tipo = (get_object_or_404(TrainingCourseType, pk=p.get("tipo_id") or 0) if azione == "modifica"
                    else TrainingCourseType(ordine=(TrainingCourseType.objects.count() + 1) * 10))
            if TrainingCourseType.objects.filter(nome__iexact=nome).exclude(pk=tipo.pk).exists():
                raise servizio.TipiError(f"Esiste già un tipo «{nome}».")
            tipo.nome = nome
            tipo.descrizione = (p.get("descrizione") or "").strip()[:200]
            colore = (p.get("colore") or "").strip()
            if len(colore) == 7 and colore.startswith("#"):
                tipo.colore = colore
            tipo.save()
            messages.success(request, f"Tipo «{tipo.nome}» salvato.")
        elif azione == "elimina":
            tipo = get_object_or_404(TrainingCourseType, pk=p.get("tipo_id") or 0)
            n = tipo.corsi.count()
            tipo.delete()
            messages.success(request, f"Tipo «{tipo.nome}» eliminato"
                             + (f": {n} corsi restano senza tipo." if n else "."))
        elif azione == "assegna_piano":
            piano = get_object_or_404(TrainingPlan, pk=p.get("piano_id") or 0)
            tipo = get_object_or_404(TrainingCourseType, pk=p.get("tipo_id") or 0)
            n = servizio.assegna_tipo_a_piano(piano, tipo, solo_senza_tipo=p.get("tutti") != "1")
            messages.success(request, f"{n} corsi del piano «{piano.nome}» ora sono «{tipo.nome}».")
        elif azione == "accorpa":
            togli = get_object_or_404(TrainingPlan, pk=p.get("togli") or 0)
            tieni = get_object_or_404(TrainingPlan, pk=p.get("tieni") or 0)
            esito = servizio.accorpa(togli, tieni)
            messages.success(request, f"«{togli.nome}» accorpato in «{tieni.nome}»: {esito['corsi']} corsi, "
                                      f"{esito['regole']} regole, {esito['assegnazioni']} assegnazioni spostate.")
        elif azione == "non_doppi":
            a = get_object_or_404(TrainingPlan, pk=p.get("togli") or 0)
            b = get_object_or_404(TrainingPlan, pk=p.get("tieni") or 0)
            servizio.segna_non_doppi(a, b, _nome_utente(request.user))
            messages.info(request, "Segnati come piani diversi: non verranno più proposti.")
        else:
            raise servizio.TipiError("Azione non riconosciuta.")
    except servizio.TipiError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:formazione_tipi_corso")
    try:
        log_action(request, f"formazione_tipi_{azione}", "anagrafica",
                   {k: v for k, v in p.items() if k != "csrfmiddlewaretoken"})
    except Exception:
        logger.exception("Audit tipi di corso non registrato")
    return redirect("anagrafica:formazione_tipi_corso")
