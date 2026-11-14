"""MOD.128 — utensili critici, Technical Plan e MOD.176 RUC (MT CN 69 §8).

Pagine sotto il processo: consultarle chiede il permesso visualizza MOD.128, modificarle
il permesso gestisci MOD.128 (stessi binding ACL del resto del modulo).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models_mpq import (
    ProcessoQualificato,
    RegistroUtensile,
    TechnicalPlan,
    TechnicalPlanPasso,
    TechnicalPlanRevisione,
    UtensileCritico,
)
from .services import mpq_utensili
from .views_mpq import _check_manage, _check_mpq_permission, _mpq_denied, _mpq_log
from .views_mpq_qualifiche import _form_page


def _url_utensili(processo_id):
    return reverse("anagrafica:mpq_utensili", args=[processo_id])


@login_required
def mpq_utensili(request, processo_id: int):
    """Utensili critici, Technical Plan e registri MOD.176 del processo."""
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    proc = get_object_or_404(ProcessoQualificato.objects.select_related("cliente"), pk=processo_id)
    plans = list(proc.technical_plan.prefetch_related("revisioni"))
    for tp in plans:
        revs = list(tp.revisioni.all())
        tp.corrente = next((r for r in revs if r.stato == TechnicalPlanRevisione.STATO_APPROVATA), None)
        tp.in_attesa = next((r for r in revs if r.stato == TechnicalPlanRevisione.STATO_BOZZA), None)
    registri = list(RegistroUtensile.objects.filter(passo__revisione__plan__processo=proc)
                    .exclude(stato=RegistroUtensile.STATO_CHIUSO)
                    .select_related("passo", "passo__utensile", "passo__revisione__plan")
                    .prefetch_related("righe"))
    return render(request, "anagrafica/pages/mpq_utensili.html", {
        "processo": proc, "utensili": list(proc.utensili_critici.all()), "plans": plans,
        "registri": registri, "can_manage": _check_manage(request),
    })


@login_required
def mpq_utensile_form(request, processo_id: int, utensile_id: int | None = None):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import UtensileCriticoForm

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    obj = get_object_or_404(UtensileCritico, pk=utensile_id, processo=proc) if utensile_id else None
    form = UtensileCriticoForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        u = form.save(commit=False)
        u.processo = proc
        if UtensileCritico.objects.filter(processo=proc, codice=u.codice).exclude(pk=u.pk).exists():
            form.add_error("codice", "Codice già presente fra gli utensili critici del processo.")
        else:
            u.save()
            _mpq_log(request, processo=proc, evento="Utensile critico " + ("modificato" if obj else "aggiunto"),
                     dettaglio=str(u))
            messages.success(request, "Utensile critico salvato.")
            return redirect(_url_utensili(proc.id))
    return _form_page(request, form, ("Modifica" if obj else "Nuovo") + f" utensile critico · {proc.nome}",
                      _url_utensili(proc.id))


@login_required
def mpq_tp_nuovo(request, processo_id: int):
    """Nuovo Technical Plan con la prima revisione (in attesa di approvazione)."""
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import TechnicalPlanForm

    proc = get_object_or_404(ProcessoQualificato, pk=processo_id)
    form = TechnicalPlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tp = form.save(commit=False)
        tp.processo = proc
        tp.save()
        mpq_utensili.nuova_revisione(tp, modifiche="Prima emissione")
        _mpq_log(request, processo=proc, evento="Technical Plan creato", dettaglio=str(tp))
        messages.success(request, "Technical Plan creato: aggiungi i passi e registra l'approvazione.")
        return redirect("anagrafica:mpq_tp", tp_id=tp.id)
    return _form_page(request, form, f"Nuovo Technical Plan · {proc.nome}", _url_utensili(proc.id))


@login_required
def mpq_tp(request, tp_id: int):
    """Technical Plan: revisioni, passi della revisione scelta, approvazione, nuova revisione, MOD.176."""
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    from .forms_mpq import TechnicalPlanPassoForm

    tp = get_object_or_404(TechnicalPlan.objects.select_related("processo"), pk=tp_id)
    revisioni = list(tp.revisioni.order_by("-numero"))
    scelta = request.GET.get("rev") or ""
    rev = next((r for r in revisioni if str(r.numero) == scelta), None)
    rev = rev or next((r for r in revisioni if r.stato == TechnicalPlanRevisione.STATO_BOZZA), None) \
        or next((r for r in revisioni if r.stato == TechnicalPlanRevisione.STATO_APPROVATA), None) \
        or (revisioni[0] if revisioni else None)
    passi = list(rev.passi.select_related("utensile").prefetch_related("registri__righe")) if rev else []
    return render(request, "anagrafica/pages/mpq_tp.html", {
        "tp": tp, "processo": tp.processo, "revisioni": revisioni, "rev": rev, "passi": passi,
        "can_manage": _check_manage(request), "oggi": timezone.localdate(),
        "passo_form": TechnicalPlanPassoForm(processo=tp.processo) if rev and rev.stato == rev.STATO_BOZZA else None,
    })


def _rev_bozza(rev_id):
    return get_object_or_404(TechnicalPlanRevisione.objects.select_related("plan__processo"), pk=rev_id,
                             stato=TechnicalPlanRevisione.STATO_BOZZA)


@login_required
@require_POST
def mpq_tp_passo_add(request, rev_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    from .forms_mpq import TechnicalPlanPassoForm

    rev = _rev_bozza(rev_id)
    form = TechnicalPlanPassoForm(request.POST, processo=rev.plan.processo)
    if form.is_valid():
        p = form.save(commit=False)
        p.revisione = rev
        p.ordine = rev.passi.count()
        p.save()
        messages.success(request, "Passo aggiunto.")
    else:
        messages.error(request, "Passo non valido: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
    return redirect(reverse("anagrafica:mpq_tp", args=[rev.plan_id]) + f"?rev={rev.numero}")


@login_required
@require_POST
def mpq_tp_passo_delete(request, passo_id: int):
    if not _check_manage(request):
        return _mpq_denied(request)
    p = get_object_or_404(TechnicalPlanPasso.objects.select_related("revisione"), pk=passo_id,
                          revisione__stato=TechnicalPlanRevisione.STATO_BOZZA)
    rev = p.revisione
    p.delete()
    messages.success(request, "Passo tolto.")
    return redirect(reverse("anagrafica:mpq_tp", args=[rev.plan_id]) + f"?rev={rev.numero}")


@login_required
@require_POST
def mpq_tp_approva(request, rev_id: int):
    """Registra l'approvazione del Certify Agent (nome, data, documento firmato)."""
    if not _check_manage(request):
        return _mpq_denied(request)
    rev = _rev_bozza(rev_id)
    chi = (request.POST.get("approvato_da") or "").strip()
    if not chi:
        messages.error(request, "Scrivi chi ha approvato (Certify Agent del cliente).")
        return redirect(reverse("anagrafica:mpq_tp", args=[rev.plan_id]) + f"?rev={rev.numero}")
    if not rev.passi.exists():
        messages.error(request, "Una revisione senza passi non si approva.")
        return redirect(reverse("anagrafica:mpq_tp", args=[rev.plan_id]) + f"?rev={rev.numero}")
    from datetime import date

    try:
        data = date.fromisoformat(request.POST.get("data") or "")
    except ValueError:
        data = timezone.localdate()
    mpq_utensili.approva(rev, approvato_da=chi[:150], data=data, documento=request.FILES.get("documento"))
    _mpq_log(request, processo=rev.plan.processo, evento="Technical Plan approvato",
             dettaglio=f"{rev.plan} rev. {rev.numero} da {chi}")
    messages.success(request, f"Revisione {rev.numero} approvata: è quella valida in produzione.")
    return redirect("anagrafica:mpq_tp", tp_id=rev.plan_id)


@login_required
@require_POST
def mpq_tp_revisione(request, tp_id: int):
    """Nuova revisione (modifica al processo): parte dai passi di quella valida."""
    if not _check_manage(request):
        return _mpq_denied(request)
    tp = get_object_or_404(TechnicalPlan, pk=tp_id)
    if tp.revisioni.filter(stato=TechnicalPlanRevisione.STATO_BOZZA).exists():
        messages.error(request, "C'è già una revisione in attesa di approvazione.")
        return redirect("anagrafica:mpq_tp", tp_id=tp.id)
    modifiche = (request.POST.get("modifiche") or "").strip()
    if not modifiche:
        messages.error(request, "Scrivi cosa cambia nella nuova revisione.")
        return redirect("anagrafica:mpq_tp", tp_id=tp.id)
    rev = mpq_utensili.nuova_revisione(tp, modifiche=modifiche)
    _mpq_log(request, processo=tp.processo, evento="Technical Plan: nuova revisione", dettaglio=f"{tp} rev. {rev.numero}")
    messages.success(request, f"Revisione {rev.numero} creata: correggi i passi e registra l'approvazione.")
    return redirect(reverse("anagrafica:mpq_tp", args=[tp.id]) + f"?rev={rev.numero}")


@login_required
@require_POST
def mpq_registro_apri(request, passo_id: int):
    """Nuovo MOD.176 per un utensile/kit montato su un passo della revisione valida."""
    if not _check_manage(request):
        return _mpq_denied(request)
    passo = get_object_or_404(TechnicalPlanPasso.objects.select_related("revisione__plan"), pk=passo_id,
                              revisione__stato=TechnicalPlanRevisione.STATO_APPROVATA)
    ident = (request.POST.get("identificativo") or "").strip()
    if not ident:
        messages.error(request, "Scrivi la marcatura o il codice del kit.")
        return redirect("anagrafica:mpq_tp", tp_id=passo.revisione.plan_id)
    reg = RegistroUtensile.objects.create(passo=passo, identificativo=ident[:80])
    _mpq_log(request, processo=passo.revisione.plan.processo, evento="MOD.176 aperto", dettaglio=ident)
    return redirect("anagrafica:mpq_registro", reg_id=reg.id)


@login_required
def mpq_registro(request, reg_id: int):
    """MOD.176 RUC: parti lavorate con l'utensile/kit fino al TCP."""
    if not _check_mpq_permission(request):
        return _mpq_denied(request)
    from .forms_mpq import RegistroRigaForm

    reg = get_object_or_404(RegistroUtensile.objects.select_related(
        "passo", "passo__utensile", "passo__revisione__plan__processo"), pk=reg_id)
    can = _check_manage(request)
    form = RegistroRigaForm(request.POST or None, initial={"data": timezone.localdate()})
    if request.method == "POST":
        if not can:
            return _mpq_denied(request)
        if request.POST.get("azione") == "chiudi":
            mpq_utensili.chiudi(reg)
            _mpq_log(request, processo=reg.passo.revisione.plan.processo, evento="MOD.176 chiuso",
                     dettaglio=reg.identificativo)
            messages.success(request, "Registro chiuso: consegnalo a IN1 per l'archivio del P/N.")
            return redirect("anagrafica:mpq_registro", reg_id=reg.id)
        if form.is_valid():
            try:
                esito = mpq_utensili.registra_riga(reg, **form.cleaned_data)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                if esito["oltre"]:
                    messages.warning(request, f"TCP superato di {esito['oltre']} {reg.passo.get_tcp_unita_display()}: "
                                              "cambia l'utensile e segnala a Qualità.")
                elif esito["tcp_raggiunto"]:
                    messages.warning(request, "TCP raggiunto: cambia l'utensile e chiudi il registro.")
                else:
                    messages.success(request, "Riga registrata.")
                return redirect("anagrafica:mpq_registro", reg_id=reg.id)
    righe = list(reg.righe.all())
    usato = sum(r.quantita for r in righe)
    limite = reg.passo.tcp_limite
    return render(request, "anagrafica/pages/mpq_registro.html", {
        "reg": reg, "righe": righe, "usato": usato, "limite": limite,
        "percentuale": min(100, round(usato * 100 / limite)) if limite else None,
        "form": form if can and reg.stato == RegistroUtensile.STATO_IN_USO else None, "can_manage": can,
        "processo": reg.passo.revisione.plan.processo, "tp": reg.passo.revisione.plan,
    })
