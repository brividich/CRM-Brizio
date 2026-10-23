"""Postazioni condivise: configurazione (PC dal registro asset, account, gruppo, inattività), operatori e PIN.

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

from assets.models import Asset
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


TIPI_ASSET_PC = (Asset.TYPE_PC, Asset.TYPE_NOTEBOOK)


def _asset_ammessi(corrente_id=None):
    """PC e portatili del registro asset non dismessi (più quello già collegato, anche se dismesso)."""
    filtro = Q(asset_type__in=TIPI_ASSET_PC) & ~Q(status=Asset.STATUS_RETIRED)
    if corrente_id:
        filtro |= Q(pk=corrente_id)
    return Asset.objects.filter(filtro).order_by("name", "asset_tag")


def _scheda_asset(asset) -> dict | None:
    """Quello che la postazione prende dall'asset: dati della macchina, MAC e IP con la fonte."""
    if asset is None:
        return None
    return {
        "asset": asset,
        "modello": " ".join(v for v in (asset.manufacturer, asset.model) if v),
        "mac": sorted(postazioni.mac_dell_asset(asset)),
        "ip": postazioni.ip_dell_asset(asset),
    }


@legacy_admin_required
@require_GET
def postazioni_condivise(request):
    elenco = list(PostazioneCondivisa.objects.select_related("gruppo", "asset").order_by("nome"))
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
                        "ip": sorted(postazioni.ip_della_postazione(p)),
                        "operatori": len(postazioni.operatori(p))} for p in elenco],
        "modifica": modifica,
        "scheda_asset": _scheda_asset(modifica.asset if modifica else None),
        "asset_ammessi": _asset_ammessi(modifica.asset_id if modifica else None),
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
    try:
        account_id = int(request.POST.get("account") or 0)
        gruppo_id = int(request.POST.get("gruppo") or 0)
        minuti = int(request.POST.get("minuti_inattivita") or 0)
        asset_id = int(request.POST.get("asset") or 0) or None
    except ValueError:
        return "Valori non validi."
    asset = None
    if asset_id:
        asset = _asset_ammessi(postazione.asset_id).filter(pk=asset_id).first()
        if asset is None:
            return "Scegli il PC fra i PC e i portatili del registro asset."
        gia = PostazioneCondivisa.objects.filter(asset=asset).exclude(pk=postazione.pk).first()
        if gia is not None:
            return f"L'asset {asset.asset_tag} è già la postazione «{gia.nome}»."
    nome = (request.POST.get("nome") or "").strip()[:100] or (asset.name[:100] if asset else "")
    if not nome:
        return "Dai un nome alla postazione."
    testo_ip = (request.POST.get("ip_pc") or "").strip()
    ip_pc = postazioni.ip_normalizzato(testo_ip)
    if testo_ip and not ip_pc:
        return f"«{testo_ip}» non è un indirizzo IP valido (es. 192.168.10.25)."
    postazione.asset, postazione.ip_pc = asset, ip_pc
    ip_validi = postazioni.ip_della_postazione(postazione)
    if not ip_validi:
        if asset is not None:
            return (f"L'asset {asset.asset_tag} non ha un IP (né nei punti rete né dal DHCP): "
                    "aggiungilo all'asset o scrivilo a mano in «IP a mano».")
        return "Collega il PC del registro asset o indica l'indirizzo IP del PC (es. 192.168.10.25)."
    for altra in PostazioneCondivisa.objects.exclude(pk=postazione.pk).select_related("asset"):
        comuni = ip_validi & postazioni.ip_della_postazione(altra)
        if comuni:
            return f"Il PC {', '.join(sorted(comuni))} è già registrato come «{altra.nome}»."
    if account_id not in {u.id for u in _account_ammessi()}:
        return "Scegli l'account della postazione fra gli utenti attivi (gli amministratori non sono ammessi)."
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
        "postazione": nome, "postazione_id": postazione.pk, "account_legacy_id": account_id, "ip_pc": ip_pc,
        "asset_id": postazione.asset_id, "ip_validi": sorted(ip_validi),
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
        "postazioni": PostazioneCondivisa.objects.select_related("asset").order_by("nome"),
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
