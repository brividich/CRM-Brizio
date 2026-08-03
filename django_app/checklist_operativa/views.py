from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acl_v2 import request_has_permission_code
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


def _genera_voci_da_template(evento: ChiusuraEvento) -> int:
    count = 0
    for template in ChecklistTaskTemplate.objects.filter(attivo=True).order_by("ordine", "id"):
        ChiusuraVoce.objects.create(
            evento=evento,
            template=template,
            ordine=template.ordine,
            descrizione=template.descrizione,
            responsabile=template.responsabile,
        )
        count += 1
    return count


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
    if azione == "annulla":
        voce.annulla_conferma()
        messages.info(request, "Conferma annullata.")
    else:
        voce.conferma(dipendente, note=request.POST.get("note", "").strip())
        messages.success(request, "Task confermato.")

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
        "eventi": ChiusuraEvento.objects.all()[:20],
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
            evento = form.save(commit=False)
            evento.creato_da = request.user
            evento.save()
            count = _genera_voci_da_template(evento)
            messages.success(request, f"Evento creato con {count} mansioni generate dal template.")
            return redirect("checklist_operativa:evento_detail", pk=evento.pk)
    else:
        form = ChiusuraEventoForm()

    return render(request, "checklist_operativa/pages/evento_form.html", {"form": form})


@configurazione_required
def configurazione_evento_detail(request, pk: int):
    evento = get_object_or_404(ChiusuraEvento, pk=pk)
    voci = evento.voci.select_related("responsabile", "confermato_da").order_by("ordine", "id")
    context = {
        "evento": evento,
        "voci": voci,
        "proposte": evento.proposte.order_by("-proposto_il"),
    }
    return render(request, "checklist_operativa/pages/evento_detail.html", context)


@configurazione_required
@require_POST
def configurazione_evento_chiudi(request, pk: int):
    evento = get_object_or_404(ChiusuraEvento, pk=pk)
    evento.stato = ChiusuraEvento.STATO_CHIUSA
    evento.save(update_fields=["stato"])
    messages.success(request, f"Evento '{evento.nome}' chiuso e archiviato.")
    return redirect("checklist_operativa:riepilogo_detail", pk=evento.pk)


@configurazione_required
def configurazione_voce_edit(request, evento_pk: int, pk: int | None = None):
    evento = get_object_or_404(ChiusuraEvento, pk=evento_pk)
    instance = get_object_or_404(ChiusuraVoce, pk=pk, evento=evento) if pk else None
    if request.method == "POST":
        form = ChiusuraVoceForm(request.POST, instance=instance)
        if form.is_valid():
            voce = form.save(commit=False)
            voce.evento = evento
            voce.save()
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
            decisione = form.cleaned_data["decisione"]
            proposta.note_admin = form.cleaned_data["note_admin"]
            proposta.gestito_da = request.user
            proposta.gestito_il = timezone.now()

            if decisione == "approva":
                proposta.stato = ChiusuraProposta.STATO_APPROVATA
                proposta.aggiungi_al_template = form.cleaned_data["aggiungi_al_template"]

                if proposta.aggiungi_al_template:
                    nuovo_template = ChecklistTaskTemplate.objects.create(
                        descrizione=proposta.descrizione,
                        responsabile=proposta.responsabile_suggerito,
                        creato_da=request.user,
                        note=f"Da proposta #{proposta.pk} di {proposta.proposto_da}",
                    )
                    proposta.template_generato = nuovo_template

                if proposta.evento_id:
                    nuova_voce = ChiusuraVoce.objects.create(
                        evento=proposta.evento,
                        template=proposta.template_generato,
                        descrizione=proposta.descrizione,
                        responsabile=proposta.responsabile_suggerito,
                    )
                    proposta.voce_generata = nuova_voce

                messages.success(request, "Proposta approvata.")
            else:
                proposta.stato = ChiusuraProposta.STATO_RIFIUTATA
                messages.info(request, "Proposta rifiutata.")

            proposta.save()
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
    eventi = ChiusuraEvento.objects.all()
    return render(request, "checklist_operativa/pages/riepilogo.html", {"eventi": eventi})


@configurazione_required
def riepilogo_detail(request, pk: int):
    evento = get_object_or_404(ChiusuraEvento, pk=pk)
    voci = evento.voci.select_related("responsabile", "confermato_da").order_by("ordine", "id")
    return render(
        request, "checklist_operativa/pages/riepilogo_dettaglio.html", {"evento": evento, "voci": voci},
    )
