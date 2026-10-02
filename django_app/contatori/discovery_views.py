"""UI discovery sulla route esistente, protetta dall'ACL del modulo."""
from uuid import UUID

from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from core.audit import log_action
from . import discovery_jobs, services
from .forms import CommunitySNMPForm, DiscoveryBackgroundForm
from .models import CommunitySNMP, DiscoverySNMP, ImpostazioniSNMP


def _scan(request, value):
    try:
        pk = UUID(str(value))
    except (ValueError, TypeError):
        raise Http404
    return get_object_or_404(DiscoverySNMP, pk=pk, richiesta_da=request.user)


def _community(value):
    try:
        pk = int(value)
    except (ValueError, TypeError):
        raise Http404
    return get_object_or_404(CommunitySNMP, pk=pk)


def contesto_discovery(request):
    cfg = ImpostazioniSNMP.get_solo()
    return {
        "background_form": DiscoveryBackgroundForm(initial={"versione": cfg.version}),
        "community_form": CommunitySNMPForm(),
        "catalogo": CommunitySNMP.objects.defer("segreto_cifrato"),
        "storico": DiscoverySNMP.objects.filter(richiesta_da=request.user).defer("hosts", "risultati")[:20],
        "version": cfg.version, "timeout": 2, "rete": "10.0.0.0/24",
    }


@never_cache
@sensitive_post_parameters("valore", "community")
def discovery(request):
    if not request.user.is_authenticated:
        return HttpResponse("Autenticazione richiesta", status=401)
    action = request.POST.get("azione", "rapida")
    if request.method == "POST" and action == "rapida":
        from .views import _discovery_rapida
        return _discovery_rapida(request)

    scan = None
    if request.GET.get("scan"):
        scan = _scan(request, request.GET["scan"])
    if request.method == "GET" and request.GET.get("partial") == "1":
        if scan is None:
            raise Http404
        return render(request, "contatori/_discovery_stato.html", {
            "scan": scan, "righe": services.abbina_discovery(scan.risultati)})

    context = contesto_discovery(request)
    if request.method == "POST":
        if action == "salva_community":
            instance = _community(request.POST["community_id"]) if request.POST.get("community_id") else None
            form = CommunitySNMPForm(request.POST, instance=instance)
            if form.is_valid():
                community = form.save()
                log_action(request, "community_salvata", "contatori", oggetto=community,
                           dettaglio={"attiva": community.attiva})
                return redirect(reverse("contatori:discovery") + "?catalogo_salvato=1")
            context.update(community_form=form, community_edit=instance)
        elif action == "avvia":
            form = DiscoveryBackgroundForm(request.POST)
            if form.is_valid():
                cfg = ImpostazioniSNMP.get_solo()
                with transaction.atomic():
                    scan, created = DiscoverySNMP.objects.get_or_create(
                        pk=form.cleaned_data["richiesta"], defaults={
                            "richiesta_da": request.user, "rete": form.cleaned_data["rete"],
                            "hosts": form.hosts, "community_ids": form.cleaned_data["communities"],
                            "versione": form.cleaned_data["versione"], "porta": cfg.port,
                            "timeout": form.cleaned_data["timeout"],
                        })
                    if scan.richiesta_da_id != request.user.pk:
                        raise Http404
                    if created:
                        discovery_jobs.dopo_commit(scan)
                        log_action(request, "discovery_avviata", "contatori", oggetto=scan)
                return redirect(reverse("contatori:discovery") + f"?scan={scan.pk}")
            context["background_form"] = form
        elif action in ("interrompi", "riprendi"):
            scan = _scan(request, request.POST.get("scan"))
            changed = (discovery_jobs.interrompi(scan) if action == "interrompi"
                       else discovery_jobs.riprendi(scan))
            if changed:
                log_action(request, "discovery_" + action, "contatori", oggetto=scan)
            return redirect(reverse("contatori:discovery") + f"?scan={scan.pk}")
        else:
            return HttpResponse("Azione non valida", status=400)
    elif request.GET.get("community"):
        community = _community(request.GET["community"])
        context.update(community_form=CommunitySNMPForm(instance=community), community_edit=community)

    context.update(scan=scan, righe=services.abbina_discovery(scan.risultati) if scan else None)
    return render(request, "contatori/discovery.html", context)
