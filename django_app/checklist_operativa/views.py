from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user, is_legacy_admin

from .acl_bootstrap import PERM_CONFIGURAZIONE_MANAGE
from .forms import (
    ChecklistTaskTemplateForm,
    ChiusuraEventoForm,
    ChiusuraPropostaDecisioneForm,
    ChiusuraPropostaForm,
    ChiusuraVoceForm,
)
from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce
from .services import (
    ChecklistStatoError,
    annulla_conferma_voce,
    chiudi_evento,
    conferma_voce,
    crea_evento_con_voci,
    decidi_proposta,
    eventi_con_progresso,
    riapri_evento,
    salva_voce,
)


def _can_configure(request) -> bool:
    if not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    return request_has_permission_code(request, PERM_CONFIGURAZIONE_MANAGE)


def configurazione_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not _can_configure(request):
            return render(request, "core/pages/forbidden.html", status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


def _current_dipendente(request) -> AnagraficaDipendente | None:
    if not request.user.is_authenticated:
        return None
    return AnagraficaDipendente.objects.filter(utente_id=request.user.id).first()


# ---------------------------------------------------------------------------
# Gestione — i responsabili confermano i propri task
# ---------------------------------------------------------------------------

@login_required
def gestione_home(request):
    dipendente = _current_dipendente(request)
    oggi = timezone.localdate()

    evento_id = request.GET.get("evento")
    if evento_id:
        evento = get_object_or_404(ChiusuraEvento, pk=evento_id)
    else:
        evento = (
            ChiusuraEvento.objects.filter(stato=ChiusuraEvento.STATO_APERTA, data_inizio__gte=oggi)
            .order_by("data_inizio")
            .first()
        )
        if not evento:
            evento = (
                ChiusuraEvento.objects.filter(stato=ChiusuraEvento.STATO_APERTA)
                .order_by("-data_inizio")
                .first()
            )

    voci = []
    if evento and dipendente:
        voci = list(
            evento.voci.filter(responsabile=dipendente).select_related("confermato_da").order_by("ordine", "id")
        )

    altri_eventi = ChiusuraEvento.objects.filter(stato=ChiusuraEvento.STATO_APERTA).order_by("-data_inizio")

    context = {
        "evento": evento,
        "voci": voci,
        "dipendente": dipendente,
        "altri_eventi": altri_eventi,
        "proposta_form": ChiusuraPropostaForm(),
        "can_configure": _can_configure(request),
    }
    return render(request, "checklist_operativa/pages/gestione.html", context)


@login_required
@require_POST
def gestione_conferma(request, voce_id: int):
    dipendente = _current_dipendente(request)
    voce = get_object_or_404(ChiusuraVoce, pk=voce_id)
    if not dipendente or voce.responsabile_id != dipendente.pk:
        return render(request, "core/pages/forbidden.html", status=403)

    azione = request.POST.get("azione", "conferma")
    try:
        if azione == "annulla":
            annulla_conferma_voce(voce.pk)
            messages.info(request, "Conferma annullata.")
        else:
            conferma_voce(voce.pk, dipendente, note=request.POST.get("note", "").strip())
            messages.success(request, "Task confermato.")
    except ChecklistStatoError as exc:
        messages.error(request, str(exc))

    url = reverse("checklist_operativa:gestione")
    if voce.evento_id:
        url = f"{url}?evento={voce.evento_id}"
    return redirect(url)


@login_required
@require_POST
def gestione_proposta_nuova(request):
    form = ChiusuraPropostaForm(request.POST)
    evento_id = request.POST.get("evento_id") or None
    if form.is_valid():
        proposta = form.save(commit=False)
        proposta.proposto_da = request.user
        if evento_id:
            proposta.evento = get_object_or_404(ChiusuraEvento, pk=evento_id)
        proposta.save()
        messages.success(request, "Proposta inviata. Verrà valutata da chi gestisce la checklist.")
    else:
        messages.error(request, "Proposta non valida: controlla i campi.")

    url = reverse("checklist_operativa:gestione")
    if evento_id:
        url = f"{url}?evento={evento_id}"
    return redirect(url)


# ---------------------------------------------------------------------------
# Configurazione — riservata via ACL
# ---------------------------------------------------------------------------

@configurazione_required
def configurazione_home(request):
    context = {
        "templates": ChecklistTaskTemplate.objects.all().select_related("responsabile"),
        "eventi": eventi_con_progresso()[:20],
        "proposte_in_attesa": ChiusuraProposta.objects.filter(
            stato=ChiusuraProposta.STATO_IN_ATTESA
        ).count(),
    }
    return render(request, "checklist_operativa/pages/configurazione.html", context)


@configurazione_required
def configurazione_task_edit(request, pk: int | None = None):
    instance = get_object_or_404(ChecklistTaskTemplate, pk=pk) if pk else None
    if request.method == "POST":
        form = ChecklistTaskTemplateForm(request.POST, instance=instance)
        if form.is_valid():
            template = form.save(commit=False)
            if not pk:
                template.creato_da = request.user
            template.save()
            messages.success(request, "Mansione salvata.")
            return redirect("checklist_operativa:configurazione")
    else:
        form = ChecklistTaskTemplateForm(instance=instance)

    return render(request, "checklist_operativa/pages/task_form.html", {"form": form, "instance": instance})


@configurazione_required
@require_POST
def configurazione_task_toggle(request, pk: int):
    template = get_object_or_404(ChecklistTaskTemplate, pk=pk)
    template.attivo = not template.attivo
    template.save(update_fields=["attivo", "aggiornato_il"])
    return redirect("checklist_operativa:configurazione")


@configurazione_required
def configurazione_evento_nuovo(request):
    if request.method == "POST":
        form = ChiusuraEventoForm(request.POST)
        if form.is_valid():
            evento, count = crea_evento_con_voci(form.save(commit=False), user=request.user)
            messages.success(request, f"Evento creato con {count} mansioni generate dal template.")
            return redirect("checklist_operativa:evento_detail", pk=evento.pk)
    else:
        form = ChiusuraEventoForm()

    return render(request, "checklist_operativa/pages/evento_form.html", {"form": form})


@configurazione_required
def configurazione_evento_detail(request, pk: int):
    evento = get_object_or_404(eventi_con_progresso(), pk=pk)
    voci = evento.voci.select_related("responsabile", "confermato_da").order_by("ordine", "id")
    context = {
        "evento": evento,
        "voci": voci,
        "proposte": evento.proposte.select_related("proposto_da").order_by("-proposto_il"),
    }
    return render(request, "checklist_operativa/pages/evento_detail.html", context)


@configurazione_required
@require_POST
def configurazione_evento_chiudi(request, pk: int):
    evento = get_object_or_404(ChiusuraEvento, pk=pk)
    if chiudi_evento(evento.pk):
        messages.success(request, f"Evento '{evento.nome}' chiuso e archiviato.")
    else:
        messages.info(request, f"Evento '{evento.nome}' era già chiuso: nessuna modifica.")
    return redirect("checklist_operativa:riepilogo_detail", pk=evento.pk)


@configurazione_required
@require_POST
def configurazione_evento_riapri(request, pk: int):
    """Riapre un evento archiviato per sbaglio, tracciando chi l'ha fatto.

    Sta dietro lo stesso ACL della chiusura: è l'unica strada per tornare
    indietro senza passare dall'admin Django.
    """
    evento = get_object_or_404(ChiusuraEvento, pk=pk)
    if riapri_evento(evento.pk):
        log_action(
            request, "riapri_evento_chiusura", "checklist_operativa",
            {"evento": evento.nome, "data_inizio": str(evento.data_inizio)},
            oggetto=evento,
        )
        messages.success(request, f"Evento '{evento.nome}' riaperto: le conferme registrate restano.")
    else:
        messages.info(request, f"Evento '{evento.nome}' era già aperto: nessuna modifica.")
    return redirect("checklist_operativa:evento_detail", pk=evento.pk)


@configurazione_required
def configurazione_voce_edit(request, evento_pk: int, pk: int | None = None):
    evento = get_object_or_404(ChiusuraEvento, pk=evento_pk)
    instance = get_object_or_404(ChiusuraVoce, pk=pk, evento=evento) if pk else None
    # Un evento archiviato non riceve né modifica voci: si blocca già qui, così
    # non si apre nemmeno un form che poi non potrebbe salvare.
    if evento.is_chiusa:
        messages.error(request, f"La chiusura «{evento.nome}» è archiviata: non è più modificabile.")
        return redirect("checklist_operativa:evento_detail", pk=evento.pk)
    if request.method == "POST":
        form = ChiusuraVoceForm(request.POST, instance=instance)
        if form.is_valid():
            try:
                salva_voce(evento, form.save(commit=False))
            except ChecklistStatoError as exc:
                messages.error(request, str(exc))
                return redirect("checklist_operativa:evento_detail", pk=evento.pk)
            messages.success(request, "Voce salvata.")
            return redirect("checklist_operativa:evento_detail", pk=evento.pk)
    else:
        form = ChiusuraVoceForm(instance=instance)

    return render(
        request, "checklist_operativa/pages/voce_form.html",
        {"form": form, "evento": evento, "instance": instance},
    )


@configurazione_required
def configurazione_proposte(request):
    proposte = ChiusuraProposta.objects.select_related("evento", "proposto_da", "responsabile_suggerito").filter(
        stato=ChiusuraProposta.STATO_IN_ATTESA
    )
    return render(request, "checklist_operativa/pages/proposte.html", {"proposte": proposte})


@configurazione_required
def configurazione_proposta_decidi(request, pk: int):
    proposta = get_object_or_404(ChiusuraProposta, pk=pk)
    if request.method == "POST":
        form = ChiusuraPropostaDecisioneForm(request.POST)
        if form.is_valid():
            approva = form.cleaned_data["decisione"] == "approva"
            try:
                decidi_proposta(
                    proposta.pk,
                    approva=approva,
                    note_admin=form.cleaned_data["note_admin"],
                    aggiungi_al_template=form.cleaned_data["aggiungi_al_template"],
                    user=request.user,
                )
            except ChecklistStatoError as exc:
                messages.error(request, str(exc))
                return redirect("checklist_operativa:proposte")
            if approva:
                messages.success(request, "Proposta approvata.")
            else:
                messages.info(request, "Proposta rifiutata.")
            return redirect("checklist_operativa:proposte")
    else:
        form = ChiusuraPropostaDecisioneForm()

    return render(
        request, "checklist_operativa/pages/proposta_decidi.html", {"form": form, "proposta": proposta},
    )


# ---------------------------------------------------------------------------
# Riepilogo — storico chiusure
# ---------------------------------------------------------------------------

@configurazione_required
def riepilogo_list(request):
    return render(
        request, "checklist_operativa/pages/riepilogo.html", {"eventi": eventi_con_progresso()},
    )


@configurazione_required
def riepilogo_detail(request, pk: int):
    evento = get_object_or_404(eventi_con_progresso(), pk=pk)
    voci = evento.voci.select_related("responsabile", "confermato_da").order_by("ordine", "id")
    return render(
        request, "checklist_operativa/pages/riepilogo_dettaglio.html", {"evento": evento, "voci": voci},
    )


@configurazione_required
def riepilogo_detail_pdf(request, pk: int):
    """Il riepilogo di una chiusura come PDF, da archiviare.

    Il modulo ha sostituito un foglio Excel che veniva stampato e messo agli
    atti: senza un export, per un'evidenza d'audit resterebbe lo screenshot.
    """
    from core.table_pdf import render_table_pdf

    evento = get_object_or_404(eventi_con_progresso(), pk=pk)
    voci = evento.voci.select_related("responsabile", "confermato_da").order_by("ordine", "id")

    righe = [
        [
            voce.ordine,
            voce.descrizione,
            str(voce.responsabile) if voce.responsabile_id else "—",
            "Confermato" if voce.confermato else "Da fare",
            str(voce.confermato_da) if voce.confermato_da_id else "—",
            timezone.localtime(voce.confermato_il).strftime("%d/%m/%Y %H:%M") if voce.confermato_il else "—",
            voce.note or "",
        ]
        for voce in voci
    ]
    periodo = f"{evento.data_inizio:%d/%m/%Y}"
    if evento.data_fine:
        periodo += f" → {evento.data_fine:%d/%m/%Y}"
    sottotitolo = (
        f"{periodo} · {evento.get_stato_display()} · "
        f"completamento {evento.voci_confermate}/{evento.voci_totali} "
        f"({evento.percentuale_completamento}%)"
    )

    pdf = render_table_pdf(
        title=f"Checklist chiusura — {evento.nome}",
        subtitle=sottotitolo,
        headers=["Ord.", "Mansione", "Responsabile", "Stato", "Confermato da", "Quando", "Note"],
        rows=righe,
    )
    nome_file = get_valid_filename(f"checklist_{evento.nome}_{evento.data_inizio:%Y%m%d}") or "checklist"
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_file}.pdf"'
    return response
