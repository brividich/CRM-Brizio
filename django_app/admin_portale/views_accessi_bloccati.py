"""Accessi bloccati: chi ha sbagliato la password (axes) e il pulsante «Sblocca».

Il blocco è di django-axes (``AXES_FAILURE_LIMIT`` tentativi per nome utente + IP,
dura ``AXES_COOLOFF_TIME`` ore); qui si vede chi è bloccato o vicino al blocco e lo
si sblocca senza il terminale del server. Ogni sblocco finisce nell'audit.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action
from core.legacy_models import UtenteLegacy
from core.models import Profile

from .decorators import legacy_admin_required

GIORNI_STORICO = 7


def _limite() -> int:
    return int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)


def _durata() -> timedelta:
    valore = getattr(settings, "AXES_COOLOFF_TIME", 1)
    return valore if isinstance(valore, timedelta) else timedelta(hours=float(valore or 1))


def _persone(usernames) -> dict[str, dict]:
    """Nome, tipo di account e ultimo accesso per ogni nome utente usato nei tentativi."""
    nomi = {str(u or "").strip().lower() for u in usernames if u}
    if not nomi:
        return {}
    legacy = {}
    for u in UtenteLegacy.objects.all().only("id", "nome", "email", "password", "attivo"):
        email = str(u.email or "").strip().lower()
        # Si entra con l'email, con l'alias (la parte prima della @) o, per gli storici, con il nome.
        chiavi = {email, email.split("@", 1)[0], str(u.nome or "").strip().lower()} - {""}
        for chiave in chiavi & nomi:
            legacy[chiave] = u
    ultimo = dict(
        Profile.objects.filter(legacy_user_id__in=[u.id for u in legacy.values()])
        .values_list("legacy_user_id", "user__last_login")
    )
    utenti_django = {
        str(n).lower(): last
        for n, last in get_user_model().objects.filter(username__in=list(nomi)).values_list("username", "last_login")
    }
    esito = {}
    for nome in nomi:
        u = legacy.get(nome)
        esito[nome] = {
            "nome": (u.nome or u.email) if u else "",
            "attivo": bool(u.attivo) if u else None,
            "ad": bool(u and str(u.password or "").strip() == "*AD_MANAGED*"),
            "esiste": u is not None or nome in utenti_django,
            "ultimo_accesso": ultimo.get(u.id) if u else utenti_django.get(nome),
        }
    return esito


def _righe() -> list[dict]:
    from axes.models import AccessAttempt

    adesso = timezone.now()
    limite, durata = _limite(), _durata()
    tentativi = list(
        AccessAttempt.objects.filter(attempt_time__gte=adesso - timedelta(days=GIORNI_STORICO)).order_by("-attempt_time")
    )
    persone = _persone(a.username for a in tentativi)
    righe = []
    for a in tentativi:
        fine = a.attempt_time + durata
        bloccato = a.failures_since_start >= limite and fine > adesso
        righe.append({
            "id": a.pk,
            "username": a.username or "",
            "ip": a.ip_address or "",
            "errori": a.failures_since_start,
            "ultimo": a.attempt_time,
            "pagina": a.path_info or "",
            "bloccato": bloccato,
            "fine_blocco": fine if bloccato else None,
            "persona": persone.get(str(a.username or "").strip().lower()) or {},
        })
    righe.sort(key=lambda r: (not r["bloccato"], -r["ultimo"].timestamp()))
    return righe


@legacy_admin_required
@require_GET
def accessi_bloccati(request):
    righe = _righe()
    return render(request, "admin_portale/pages/accessi_bloccati.html", {
        "page_title": "Accessi bloccati",
        "righe": righe,
        "n_bloccati": sum(1 for r in righe if r["bloccato"]),
        "limite": _limite(),
        "durata_minuti": int(_durata().total_seconds() // 60),
        "giorni_storico": GIORNI_STORICO,
        "mostra_guida": request.GET.get("guida") == "1",
    })


@legacy_admin_required
@require_POST
def accessi_bloccati_sblocca(request):
    from axes.models import AccessAttempt

    tentativo = AccessAttempt.objects.filter(pk=request.POST.get("tentativo") or 0).first()
    if tentativo is None:
        messages.warning(request, "Il blocco non c'è più: scaduto o già tolto.")
        return redirect("admin_portale:accessi_bloccati")
    dettaglio = {
        "username": tentativo.username, "ip": tentativo.ip_address,
        "errori": tentativo.failures_since_start, "ultimo_tentativo": tentativo.attempt_time.isoformat(),
    }
    tentativo.delete()
    log_action(request, "accesso_sbloccato", "admin_portale", dettaglio)
    messages.success(
        request,
        f"Sbloccato «{dettaglio['username']}» dall'IP {dettaglio['ip'] or '—'}: può riprovare subito "
        f"({_limite()} tentativi a disposizione).",
    )
    return redirect("admin_portale:accessi_bloccati")
