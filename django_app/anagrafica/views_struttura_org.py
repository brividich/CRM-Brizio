"""Struttura organizzativa (struttura della Qualità): pagina dedicata, revisioni, conferme HSE.

Cancelli server-side:
- vedere: chi vede il Mansionario (amministrazione anagrafica o dati HR);
- modificare reparti, aree, ruoli: amministrazione dell'anagrafica;
- modificare i processi (owner, tipo): amministrazione anagrafica o chi gestisce
  il catalogo processi del Sistema di Gestione (stessa riga, stessa revisione);
- emettere una revisione: SOLO chi ricopre oggi il ruolo MSM;
- confermare le mansioni di rischio: HSE (ESM/ESO) o chi gestisce i requisiti
  delle mansioni di rischio.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import AreaAziendale, CompetenzaSkm, Mansione, Reparto, RuoloOperativo, StrutturaRevisione
from .services import struttura_revisioni as rev
from .services import struttura_rischi as rischi
from .services import struttura_vista as vista
from .views_mansionario import _ids, _int_o_none, _nega, _puo_gestire, _puo_vedere

MODULE = "anagrafica"
SIGLE_HSE = {"ESM", "ESO"}


def _puo_processi(request) -> bool:
    if _puo_gestire(request):
        return True
    from sistema_gestione.acl_bootstrap import PERM_AUDIT_EDIT
    from sistema_gestione.views import _has_perm

    return _has_perm(request, PERM_AUDIT_EDIT)


def _sigle_utente(request) -> set[str]:
    from core.operational_roles import get_roles_for_user

    return {s for s in get_roles_for_user(request.user).values_list("sigla", flat=True) if s}


def _puo_confermare_rischi(request) -> bool:
    from .views import _helpers

    return _helpers._can_edit_formazione(request) or bool(_sigle_utente(request) & SIGLE_HSE)


def _torna(sezione: str):
    return redirect(reverse("anagrafica:struttura_org") + f"#{sezione}")


# ═══════════════════════════════════════════════════════════════════════════
# Pagina dedicata
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def struttura_org(request):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    mansioni = vista._mansioni()
    alb, procs, rls = vista.albero(mansioni), vista.processi(mansioni), vista.ruoli(mansioni)
    ultima = rev.ultima()
    modifiche = rev.confronto(ultima.dati, rev.fotografia()) if ultima else None
    from sistema_gestione.models import Processo

    return render(request, "anagrafica/pages/struttura_org.html", {
        "page_title": "Struttura organizzativa",
        "albero": alb, "processi": procs, "ruoli": rls,
        "da_completare": vista.da_completare(mansioni),
        "kpi": vista.kpi(alb, procs, rls, mansioni),
        "ultima": ultima,
        "n_modifiche": sum(len(s["aggiunte"]) + len(s["tolte"]) + len(s["cambiate"]) for s in modifiche or []),
        "is_admin": _puo_gestire(request),
        "puo_processi": _puo_processi(request),
        "puo_rischi": _puo_confermare_rischi(request),
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).order_by("nome")),
        "classi": RuoloOperativo.CLASSE_CHOICES,
        "tipi_processo": Processo.TIPO_CHOICES,
    })


@login_required
@require_POST
def struttura_reparto_salva(request, reparto_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Il ruolo responsabile del reparto lo cambia l'amministrazione dell'anagrafica.")
    reparto = get_object_or_404(Reparto, pk=reparto_id)
    ruolo_id = _int_o_none(request.POST.get("ruolo_responsabile"))
    reparto.ruolo_responsabile = RuoloOperativo.objects.filter(pk=ruolo_id, is_active=True).first() if ruolo_id else None
    reparto.save(update_fields=["ruolo_responsabile"])  # il segnale allinea «Responsabilità del reparto»
    log_action(request, "struttura_reparto_responsabile", MODULE,
               {"reparto": reparto.pk, "ruolo": reparto.ruolo_responsabile_id}, oggetto=reparto)
    messages.success(request, f"Reparto {reparto.nome}: ruolo responsabile "
                              f"{reparto.ruolo_responsabile.etichetta if reparto.ruolo_responsabile_id else 'tolto'}.")
    return _torna(f"rep-{reparto.pk}")


@login_required
@require_POST
def struttura_area_salva(request, area_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Il ruolo responsabile dell'area lo cambia l'amministrazione dell'anagrafica.")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    ruolo_id = _int_o_none(request.POST.get("ruolo_responsabile"))
    area.ruolo_responsabile = RuoloOperativo.objects.filter(pk=ruolo_id, is_active=True).first() if ruolo_id else None
    area.save(update_fields=["ruolo_responsabile"])
    log_action(request, "struttura_area_responsabile", MODULE,
               {"area": area.pk, "ruolo": area.ruolo_responsabile_id}, oggetto=area)
    messages.success(request, f"Area {area.nome}: ruolo responsabile "
                              f"{area.ruolo_responsabile.etichetta if area.ruolo_responsabile_id else 'come il reparto'}.")
    return _torna(f"rep-{area.reparto_id}" if area.reparto_id else "reparti")


@login_required
@require_POST
def struttura_ruolo_salva(request, ruolo_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Sigla e classificazione dei ruoli le cambia l'amministrazione dell'anagrafica.")
    from .services import struttura_ruoli

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    classe = request.POST.get("classe") or ""
    if classe not in dict(RuoloOperativo.CLASSE_CHOICES):
        classe = ""
    nome = " ".join((request.POST.get("nome") or "").split()) or ruolo.nome
    try:
        struttura_ruoli.rinomina(ruolo, nome, sigla=request.POST.get("sigla") or "", user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna("ruoli")
    ruolo.classe = classe
    campi = ["classe"]
    if "riporta_a" in request.POST:  # dalla scheda del ruolo
        capo_id = _int_o_none(request.POST.get("riporta_a"))
        capo = RuoloOperativo.objects.filter(pk=capo_id, is_active=True).exclude(pk=ruolo.pk).first() if capo_id else None
        # Niente cicli: il capo scelto non può stare sotto questo ruolo.
        giro, passo = capo, 0
        while giro is not None and passo < 50:
            if giro.pk == ruolo.pk:
                messages.error(request, "«Riporta a» creerebbe un giro nella gerarchia: non salvato.")
                return _torna("ruoli")
            giro, passo = giro.riporta_a, passo + 1
        ruolo.riporta_a = capo
        campi.append("riporta_a")
    ruolo.save(update_fields=campi)
    log_action(request, "struttura_ruolo_salva", MODULE, {"ruolo": ruolo.pk, "nome": ruolo.nome, "sigla": ruolo.sigla,
               "classe": classe, "riporta_a": ruolo.riporta_a_id}, oggetto=ruolo)
    messages.success(request, f"Ruolo «{ruolo.etichetta}» aggiornato.")
    return _torna("ruoli")


@login_required
@require_POST
def struttura_processo_salva(request, processo_id: int):
    """Owner e tipo del processo: stessa riga e stessa revisione della scheda del Sistema di Gestione."""
    if not _puo_processi(request):
        return _nega(request, "Non hai i permessi per modificare i processi.")
    from sistema_gestione.models import Processo
    from sistema_gestione.services.processi import salva_processo

    processo = get_object_or_404(Processo, pk=processo_id)
    owner_id = _int_o_none(request.POST.get("ruolo_owner"))
    tipo = request.POST.get("tipo") or ""
    if tipo not in dict(Processo.TIPO_CHOICES):
        tipo = ""
    owner = RuoloOperativo.objects.filter(pk=owner_id, is_active=True).first() if owner_id else None
    if (processo.ruolo_owner_id, processo.tipo) == (owner.pk if owner else None, tipo):
        messages.info(request, f"{processo.nome}: niente da cambiare.")
        return _torna("processi")
    processo.ruolo_owner, processo.tipo = owner, tipo
    try:
        salva_processo(processo, motivo=request.POST.get("motivo") or "", user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna("processi")
    log_action(request, "struttura_processo_salva", MODULE,
               {"processo": processo.pk, "owner": owner.pk if owner else None, "tipo": tipo,
                "revisione": processo.revisione}, oggetto=processo)
    messages.success(request, f"{processo.nome}: salvato come revisione {processo.revisione} della scheda processo.")
    return _torna("processi")


# ═══════════════════════════════════════════════════════════════════════════
# Schede laterali (ruolo, mansione, reparto)
# ═══════════════════════════════════════════════════════════════════════════

def _scheda(request, template: str, ctx: dict):
    from core.legacy_utils import get_legacy_user, is_legacy_admin

    # Il link a «Ruoli e permessi» solo a chi può aprirla (stesso controllo della pagina).
    vede_accessi = bool(request.user.is_superuser) or is_legacy_admin(get_legacy_user(request.user))
    ctx.update({"is_admin": _puo_gestire(request), "vede_accessi": vede_accessi})
    return render(request, f"anagrafica/partials/struttura_scheda_{template}.html", ctx)


@login_required
def struttura_scheda_ruolo(request, ruolo_id: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    from .services import struttura_schede as schede

    ruolo = get_object_or_404(RuoloOperativo.objects.select_related("ambito", "riporta_a"), pk=ruolo_id)
    ctx = schede.scheda_ruolo(ruolo)
    ctx.update({"classi": RuoloOperativo.CLASSE_CHOICES,
                "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).exclude(pk=ruolo.pk).order_by("nome"))})
    return _scheda(request, "ruolo", ctx)


@login_required
def struttura_scheda_mansione(request, mansione_id: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    from .services import struttura_schede as schede
    from .services.mansionario_struttura import TIPI_MANSIONE

    mansione = get_object_or_404(
        CompetenzaSkm.objects.select_related("area__reparto", "reparto", "processo_sgi", "asset", "deriva_da"),
        pk=mansione_id, tipo__in=TIPI_MANSIONE)
    return _scheda(request, "mansione", schede.scheda_mansione(mansione))


@login_required
def struttura_scheda_reparto(request, reparto_id: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    from .services import struttura_schede as schede

    reparto = get_object_or_404(Reparto.objects.select_related("ruolo_responsabile"), pk=reparto_id)
    return _scheda(request, "reparto", schede.scheda_reparto(reparto))


@login_required
@require_POST
def struttura_reparto_rinomina(request, reparto_id: int):
    """Rinomina con propagazione: schede, anagrafica, macchine, timbri, pratiche aperte."""
    if not _puo_gestire(request):
        return _nega(request, "Il nome del reparto lo cambia l'amministrazione dell'anagrafica.")
    from .services.struttura_aree import rinomina_reparto

    reparto = get_object_or_404(Reparto, pk=reparto_id)
    vecchio = reparto.nome
    try:
        esito = rinomina_reparto(reparto, request.POST.get("nome") or "", user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna(f"rep-{reparto.pk}")
    log_action(request, "struttura_reparto_rinomina", MODULE, {"reparto": reparto.pk, "da": vecchio,
               "a": reparto.nome, **esito}, oggetto=reparto)
    if reparto.nome != vecchio:
        messages.success(request, f"Reparto «{vecchio}» ora si chiama «{reparto.nome}»: aggiornate "
                                  f"{esito.get('schede', 0)} schede e {esito.get('macchine', 0)} macchine.")
    return _torna(f"rep-{reparto.pk}")


@login_required
def struttura_report_persone(request):
    """Excel «Ruoli, mansioni e competenze per persona» (dati personali: chi vede la struttura)."""
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    from django.utils import timezone

    from core.excel_export import make_xlsx_response

    from .services import struttura_report

    reparto_id = _int_o_none(request.GET.get("reparto"))
    reparto = Reparto.objects.filter(pk=reparto_id).first() if reparto_id else None
    righe = struttura_report.righe(reparto_id=reparto.pk if reparto else None)
    log_action(request, "struttura_report_persone", MODULE, {"reparto": reparto.pk if reparto else None,
                                                              "righe": len(righe)})
    return make_xlsx_response(
        filename=f"ruoli-mansioni-persone-{timezone.localdate():%Y%m%d}.xlsx",
        columns=struttura_report.COLONNE, rows=righe, sheet_title="Persone",
        title="Ruoli, mansioni e competenze per persona",
        subtitle=f"Struttura organizzativa al {timezone.localdate():%d/%m/%Y}",
        filters_label=f"Reparto: {reparto.nome}" if reparto else "Tutti i reparti",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Revisioni
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def struttura_revisioni(request):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alle revisioni della struttura.")
    puo = rev.puo_emettere(request.user)
    if request.method == "POST":
        if not puo:
            return _nega(request, "Solo chi ricopre il ruolo MSM emette una revisione della struttura.")
        try:
            nuova = rev.emetti(request.user, request.POST.get("motivo") or "")
        except (ValueError, PermissionError) as exc:
            messages.error(request, str(exc))
        else:
            log_action(request, "struttura_revisione_emessa", MODULE,
                       {"numero": nuova.numero, "motivo": nuova.motivo, "riepilogo": nuova.riepilogo}, oggetto=nuova)
            messages.success(request, f"Emessa la Rev. {nuova.numero} della struttura.")
            return redirect("anagrafica:struttura_revisione", numero=nuova.numero)
    ultima = rev.ultima()
    return render(request, "anagrafica/pages/struttura_revisioni.html", {
        "page_title": "Revisioni della struttura",
        "revisioni": StrutturaRevisione.objects.all(),
        "ultima": ultima,
        "modifiche": rev.confronto(ultima.dati if ultima else {}, rev.fotografia()),
        "puo_emettere": puo,
    })


@login_required
def struttura_revisione(request, numero: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alle revisioni della struttura.")
    r = get_object_or_404(StrutturaRevisione, numero=numero)
    altra_n = _int_o_none(request.GET.get("confronta"))
    altra = StrutturaRevisione.objects.filter(numero=altra_n).first() if altra_n else (
        StrutturaRevisione.objects.filter(numero__lt=r.numero).order_by("-numero").first())
    differenze = rev.confronto(altra.dati, r.dati) if altra else None
    return render(request, "anagrafica/pages/struttura_revisione.html", {
        "page_title": f"Struttura Rev. {r.numero}",
        "r": r, "altra": altra, "differenze": differenze,
        "revisioni": StrutturaRevisione.objects.exclude(pk=r.pk),
    })


@login_required
def struttura_revisione_pdf(request, numero: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alle revisioni della struttura.")
    r = get_object_or_404(StrutturaRevisione, numero=numero)
    resp = HttpResponse(rev.pdf(r), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="struttura-organizzativa-rev{r.numero}.pdf"'
    log_action(request, "struttura_revisione_pdf", MODULE, {"numero": r.numero}, oggetto=r)
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# Conferme HSE delle mansioni di rischio
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def struttura_rischi(request):
    if not (_puo_confermare_rischi(request) or _puo_vedere(request)):
        return _nega(request, "Non hai accesso alle mansioni di rischio proposte.")
    puo = _puo_confermare_rischi(request)
    if request.method == "POST":
        if not puo:
            return _nega(request, "Le mansioni di rischio le conferma HSE.")
        if request.POST.get("azione") == "conferma_selezionate":
            fatte = rischi.conferma_proposte(_ids(request, "mansioni"))
            if fatte:
                log_action(request, "struttura_rischi_confermati", MODULE, {"mansioni": fatte})
                messages.success(request, f"Confermate {len(fatte)} proposte.")
            else:
                messages.error(request, "Spunta almeno una mansione con una proposta.")
            return redirect("anagrafica:struttura_rischi")
        mansione = get_object_or_404(CompetenzaSkm, pk=_int_o_none(request.POST.get("mansione")))
        if request.POST.get("azione") == "scarta":
            rischi.scarta(mansione)
            log_action(request, "struttura_rischio_scartato", MODULE, {"mansione": mansione.pk}, oggetto=mansione)
            messages.info(request, f"«{mansione.nome}»: proposta scartata.")
        else:
            try:
                nomi = rischi.conferma(mansione, _ids(request, "rischi"))
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                log_action(request, "struttura_rischio_confermato", MODULE,
                           {"mansione": mansione.pk, "mansioni_rischio": nomi}, oggetto=mansione)
                messages.success(request, f"«{mansione.nome}»: confermato {', '.join(nomi)}.")
        return redirect("anagrafica:struttura_rischi")
    return render(request, "anagrafica/pages/struttura_rischi.html", {
        "page_title": "Mansioni di rischio da confermare",
        "righe": list(rischi.da_confermare()),
        "rischi_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "puo": puo,
    })
