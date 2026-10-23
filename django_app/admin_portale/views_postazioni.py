"""Postazioni condivise: configurazione (PC, account, gruppo, inattività), operatori abilitati e PIN.

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
from core.models import AccessGroup, OperatorePostazione, PinPostazione, PostazioneCondivisa, Profile

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
        # Tutti i membri del gruppo, con la spunta «può usare questo PC».
        ops = postazioni.candidati(dettaglio)
        abilitati = set(OperatorePostazione.objects.filter(postazione=dettaglio).values_list("legacy_user_id", flat=True))
        pin = {p.legacy_user_id: p for p in PinPostazione.objects.filter(legacy_user_id__in=[u.id for u in ops])}
        righe_operatori = [{"id": u.id, "nome": u.nome or u.email, "pin": pin.get(u.id), "abilitato": u.id in abilitati}
                           for u in ops]
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
        # Aiuta a registrare il PC da cui si sta configurando.
        "ip_questo_pc": postazioni.ip_richiesta(request),
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
    ip_pc = postazioni.ip_normalizzato(request.POST.get("ip_pc"))
    if not ip_pc:
        return "Indica l'indirizzo IP del PC (es. 192.168.10.25)."
    if PostazioneCondivisa.objects.filter(ip_pc=ip_pc).exclude(pk=postazione.pk).exists():
        return f"Il PC {ip_pc} è già registrato come un'altra postazione."
    if account_id not in {u.id for u in _account_ammessi()}:
        return "Scegli l'account della postazione fra gli utenti attivi (gli amministratori non sono ammessi)."
    gruppo = AccessGroup.objects.filter(pk=gruppo_id, is_active=True).first()
    if gruppo is None:
        return "Scegli il gruppo degli operatori."
    if not (MINUTI_MIN <= minuti <= MINUTI_MAX):
        return f"I minuti di inattività vanno da {MINUTI_MIN} a {MINUTI_MAX}."
    postazione.nome, postazione.account_legacy_user_id, postazione.ip_pc = nome, account_id, ip_pc
    postazione.gruppo, postazione.minuti_inattivita = gruppo, minuti
    postazione.attiva = request.POST.get("attiva") == "1"
    postazione.save()
    postazioni.registra_audit(request, "postazione_configurata", {
        "postazione": nome, "postazione_id": postazione.pk, "account_legacy_id": account_id, "ip_pc": ip_pc,
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
    if azione == "operatori" and postazione is not None:
        ammessi = {u.id for u in postazioni.candidati(postazione)}
        scelti = {int(v) for v in request.POST.getlist("abilitati") if str(v).isdigit()} & ammessi
        attuali = set(OperatorePostazione.objects.filter(postazione=postazione).values_list("legacy_user_id", flat=True))
        OperatorePostazione.objects.filter(postazione=postazione, legacy_user_id__in=attuali - scelti).delete()
        OperatorePostazione.objects.bulk_create(
            [OperatorePostazione(postazione=postazione, legacy_user_id=i) for i in sorted(scelti - attuali)])
        postazioni.registra_audit(request, "postazione_operatori", {
            "postazione": postazione.nome, "postazione_id": postazione.pk,
            "aggiunti": sorted(scelti - attuali), "tolti": sorted(attuali - scelti),
        })
        messages.success(request, f"Operatori del PC salvati: {len(scelti)} abilitati.")
        return redirect(f"{url}?operatori={postazione.pk}")
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


GIORNI_REGISTRO = (7, 30, 90, 365)


def _filtri_registro(request) -> tuple[int | None, int]:
    try:
        pid = int(request.GET.get("postazione") or 0) or None
    except ValueError:
        pid = None
    try:
        giorni = int(request.GET.get("giorni") or 30)
    except ValueError:
        giorni = 30
    return pid, giorni if giorni in GIORNI_REGISTRO else 30


@legacy_admin_required
@require_GET
def postazioni_registro(request):
    """Registro d'uso: chi ha usato quale PC e quando, più PIN sbagliati/bloccati e sessioni da altri PC."""
    pid, giorni = _filtri_registro(request)
    dati = postazioni.registro_uso(pid, giorni)
    return render(request, "admin_portale/pages/postazioni_registro.html", {
        "page_title": "Registro d'uso delle postazioni",
        "postazioni": PostazioneCondivisa.objects.order_by("nome"),
        "postazione_id": pid,
        "giorni": giorni,
        "giorni_scelte": GIORNI_REGISTRO,
        "sessioni": dati["sessioni"],
        "eventi": dati["eventi"],
        "querystring": request.GET.urlencode(),
    })


@legacy_admin_required
@require_GET
def postazioni_registro_excel(request):
    from django.utils import timezone

    from core.excel_export import make_xlsx_response

    pid, giorni = _filtri_registro(request)
    dati = postazioni.registro_uso(pid, giorni)

    def _ora(valore):
        return timezone.localtime(valore).strftime("%d/%m/%Y %H:%M") if valore else ""

    righe = [[s["postazione"], s["operatore"], _ora(s["entrata"]), _ora(s["uscita"]),
              s["durata_minuti"] if s["durata_minuti"] is not None else "", s["uscita_motivo"] or "non registrata"]
             for s in dati["sessioni"]]
    pc = PostazioneCondivisa.objects.filter(pk=pid).values_list("nome", flat=True).first() if pid else "tutte"
    return make_xlsx_response(
        filename=f"registro-postazioni-{giorni}gg.xlsx",
        columns=["Postazione", "Operatore", "Entrata", "Uscita", "Durata (min)", "Uscita"],
        rows=righe,
        sheet_title="Registro d'uso",
        title="Registro d'uso delle postazioni condivise",
        subtitle=f"Ultimi {giorni} giorni",
        filters_label=f"Postazione: {pc}",
    )
