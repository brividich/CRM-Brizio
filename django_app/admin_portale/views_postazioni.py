"""Postazioni condivise: configurazione (account, gruppo, inattività) e PIN degli operatori.

La logica di accesso sta in :mod:`core.postazioni`; qui ci sono solo le pagine
di amministrazione.
"""
from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from core import postazioni
from core.legacy_models import UtenteLegacy
from core.models import AccessGroup, PinPostazione, PostazioneCondivisa, Profile

from .decorators import legacy_admin_required

MINUTI_MIN, MINUTI_MAX = 1, 60


def _account_ammessi():
    """UtenteLegacy attivi che possono fare da account di una postazione (mai amministratori)."""
    privilegiati = set(
        Profile.objects.filter(Q(user__is_superuser=True) | Q(user__is_staff=True)).values_list("legacy_user_id", flat=True)
    )
    return [u for u in UtenteLegacy.objects.filter(attivo=True).order_by("nome", "id")
            if u.id not in privilegiati and not postazioni.e_amministratore(legacy_user=u)]


def _nomi_account(ids) -> dict[int, str]:
    return {u.id: (u.nome or u.email) for u in UtenteLegacy.objects.filter(id__in=list(ids))}


@legacy_admin_required
@require_GET
def postazioni_condivise(request):
    elenco = list(PostazioneCondivisa.objects.select_related("gruppo").order_by("nome"))
    nomi = _nomi_account(p.account_legacy_user_id for p in elenco)
    modifica = None
    if request.GET.get("modifica"):
        modifica = next((p for p in elenco if str(p.pk) == request.GET.get("modifica")), None)
    dettaglio = None
    if request.GET.get("operatori"):
        dettaglio = next((p for p in elenco if str(p.pk) == request.GET.get("operatori")), None)
    righe_operatori = []
    if dettaglio is not None:
        ops = postazioni.operatori(dettaglio)
        pin = {p.legacy_user_id: p for p in PinPostazione.objects.filter(legacy_user_id__in=[u.id for u in ops])}
        righe_operatori = [{"id": u.id, "nome": u.nome or u.email, "pin": pin.get(u.id)} for u in ops]
    return render(request, "admin_portale/pages/postazioni_condivise.html", {
        "page_title": "Postazioni condivise",
        "postazioni": [{"p": p, "account": nomi.get(p.account_legacy_user_id, f"utente #{p.account_legacy_user_id}"),
                        "operatori": len(postazioni.operatori(p))} for p in elenco],
        "modifica": modifica,
        "dettaglio": dettaglio,
        "righe_operatori": righe_operatori,
        "account_ammessi": _account_ammessi(),
        "gruppi": AccessGroup.objects.filter(is_active=True).order_by("label"),
        "minuti_min": MINUTI_MIN,
        "minuti_max": MINUTI_MAX,
        "max_tentativi": postazioni.MAX_TENTATIVI,
        "mostra_guida": request.GET.get("guida") == "1",
    })


def _salva(request) -> str:
    """Crea o modifica una postazione. Ritorna il messaggio d'errore, o stringa vuota."""
    pk = request.POST.get("id") or ""
    postazione = PostazioneCondivisa.objects.filter(pk=pk).first() if pk.isdigit() else PostazioneCondivisa()
    if pk and postazione is None:
        return "Postazione non trovata."
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        return "Dai un nome alla postazione."
    try:
        account_id = int(request.POST.get("account") or 0)
        gruppo_id = int(request.POST.get("gruppo") or 0)
        minuti = int(request.POST.get("minuti_inattivita") or 0)
    except ValueError:
        return "Valori non validi."
    if account_id not in {u.id for u in _account_ammessi()}:
        return "Scegli l'account della postazione fra gli utenti attivi (gli amministratori non sono ammessi)."
    if PostazioneCondivisa.objects.filter(account_legacy_user_id=account_id).exclude(pk=postazione.pk).exists():
        return "Questo account è già usato da un'altra postazione."
    gruppo = AccessGroup.objects.filter(pk=gruppo_id, is_active=True).first()
    if gruppo is None:
        return "Scegli il gruppo degli operatori."
    if not (MINUTI_MIN <= minuti <= MINUTI_MAX):
        return f"I minuti di inattività vanno da {MINUTI_MIN} a {MINUTI_MAX}."
    postazione.nome, postazione.account_legacy_user_id = nome, account_id
    postazione.gruppo, postazione.minuti_inattivita = gruppo, minuti
    postazione.attiva = request.POST.get("attiva") == "1"
    postazione.save()
    postazioni.registra_audit(request, "postazione_configurata", {
        "postazione": nome, "postazione_id": postazione.pk, "account_legacy_id": account_id,
        "gruppo": gruppo.code, "minuti_inattivita": minuti, "attiva": postazione.attiva,
    })
    return ""


@legacy_admin_required
@csrf_protect
@require_POST
def postazioni_condivise_azione(request):
    azione = request.POST.get("azione") or ""
    url = reverse("admin_portale:postazioni_condivise")
    if azione == "salva":
        errore = _salva(request)
        if errore:
            messages.error(request, errore)
            pk = request.POST.get("id") or ""
            return redirect(f"{url}?modifica={pk}" if pk.isdigit() else f"{url}?nuova=1")
        messages.success(request, "Postazione salvata. Vale dal prossimo accesso con l'account della postazione.")
        return redirect(url)

    postazione = PostazioneCondivisa.objects.filter(pk=request.POST.get("id") or 0).first()
    if azione == "elimina" and postazione is not None:
        postazioni.registra_audit(request, "postazione_eliminata", {"postazione": postazione.nome, "postazione_id": postazione.pk})
        postazione.delete()
        messages.success(request, "Postazione eliminata: le sessioni aperte da lì si chiudono alla prossima richiesta.")
        return redirect(url)
    if azione == "azzera_pin":
        try:
            legacy_id = int(request.POST.get("legacy_user_id") or 0)
        except ValueError:
            legacy_id = 0
        cancellati, _ = PinPostazione.objects.filter(legacy_user_id=legacy_id).delete()
        if cancellati:
            postazioni.registra_audit(request, "postazione_pin_azzerato", {"operatore_legacy_id": legacy_id})
            messages.success(request, "PIN azzerato: la persona ne imposterà uno nuovo con la propria password.")
        dest = f"{url}?operatori={postazione.pk}" if postazione is not None else url
        return redirect(dest)
    messages.error(request, "Azione non riconosciuta.")
    return redirect(url)
