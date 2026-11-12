"""Ricerche live del pannello Reception (``/reception/api/``): JSON, stesso permesso del pannello.

- ``ospiti``: chi è già venuto (tabelle della reception), per compilare ingresso e pre-registrazione
  in un tocco. Mai gli ospiti anonimizzati.
- ``dipendenti``: anagrafica Novicrom in forza (senza data di cessazione), per aggiungere i referenti.
  L'email è ``email_notifica``: la colonna ``email`` è il login legacy, non un indirizzo.

Gate: ``core/middleware.py`` ``API_ACL_GATE_PATHS`` mappa il prefisso su ``/reception/``.
"""
from __future__ import annotations

from django.db.models import Max, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from core.naming import q_persona

from .models import Ospite, Referente, Visita

MAX_RISULTATI = 10


def _q(request) -> str:
    return " ".join((request.GET.get("q") or "").split())[:100]


def _anonimo():
    return JsonResponse({"error": "Accesso richiesto"}, status=401)


@require_GET
def ospiti(request):
    if not request.user.is_authenticated:
        return _anonimo()
    q = _q(request)
    if len(q) < 2:
        return JsonResponse({"results": []})
    filtro = q_persona(q, "nome", "cognome", "azienda") | Q(email__icontains=q)
    righe = (Ospite.objects.filter(filtro, anonimizzato=False)
             .annotate(ultima=Max("visite__ingresso")).order_by("-ultima", "cognome")[:MAX_RISULTATI])
    dentro = set(Visita.objects.filter(stato=Visita.DENTRO, ospite__in=[o.pk for o in righe]).values_list("ospite_id", flat=True))
    return JsonResponse({"results": [{
        "id": o.pk, "nome": o.nome, "cognome": o.cognome, "azienda": o.azienda, "email": o.email, "telefono": o.telefono,
        "ultima": o.ultima.strftime("%d/%m/%Y") if o.ultima else "", "dentro": o.pk in dentro,
    } for o in righe]})


def dati_dipendenti(q: str = "", ids: list[int] | None = None) -> list[dict]:
    """Dipendenti in forza dall'anagrafica: nome, cognome, email di notifica, reparto, telefono aziendale."""
    from anagrafica.models import DipendenteAnagraficaAziendale
    from core.legacy_models import AnagraficaDipendente
    from core.legacy_utils import legacy_table_has_column

    cessati = set(DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
                  .exclude(legacy_anagrafica_id__isnull=True).values_list("legacy_anagrafica_id", flat=True))
    campi = ["id", "nome", "cognome", "reparto"]
    if legacy_table_has_column("anagrafica_dipendenti", "email_notifica"):
        campi.append("email_notifica")
    righe = AnagraficaDipendente.objects.all()
    if ids is not None:
        righe = righe.filter(id__in=ids)
    else:
        righe = righe.filter(q_persona(q, "nome", "cognome", "reparto")).exclude(id__in=cessati)
    righe = list(righe.order_by("cognome", "nome").values(*campi)[: (None if ids is not None else MAX_RISULTATI)])
    telefoni = dict(DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=[r["id"] for r in righe])
                    .values_list("legacy_anagrafica_id", "telefono_aziendale"))
    return [{
        "id": r["id"], "nome": (r["nome"] or "").strip().title(), "cognome": (r["cognome"] or "").strip().title(),
        "reparto": (r["reparto"] or "").strip(), "email": (r.get("email_notifica") or "").strip().lower(),
        "telefono": (telefoni.get(r["id"]) or "").strip(), "cessato": r["id"] in cessati,
    } for r in righe]


@require_GET
def dipendenti(request):
    if not request.user.is_authenticated:
        return _anonimo()
    q = _q(request)
    if len(q) < 2:
        return JsonResponse({"results": []})
    risultati = dati_dipendenti(q)
    gia = {r.dipendente_id: r.pk for r in Referente.objects.filter(dipendente_id__in=[d["id"] for d in risultati])}
    per_email = {r.email.lower(): r.pk for r in Referente.objects.filter(email__in=[d["email"] for d in risultati if d["email"]])}
    for d in risultati:
        d["referente"] = gia.get(d["id"]) or per_email.get(d["email"])
    return JsonResponse({"results": risultati})
