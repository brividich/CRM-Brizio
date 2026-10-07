"""API dell'inserimento anomalie a blocchi («controllo OP»).

Flusso della pagina «Nuova segnalazione»:
1. ``apri``: l'operatore sceglie OP, fase e modalità mail → nasce il controllo;
2. ``blocco``: per ogni gruppo di seriali salva le anomalie (una riga legacy
   ciascuna, stesso percorso di ``api_salva``); il blocco si «congela» e si
   può riaprire finché il capocommessa non ha deciso;
3. ``termina``: chiude il controllo e manda subito le mail ancora in coda.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from . import controllo_service as cs
from .quality_models import AnomaliaBlocco, AnomaliaControllo, AnomaliaSegnalazioneMeta
from .seriali import etichetta_blocco, normalizza_voci

logger = logging.getLogger(__name__)

MAX_ANOMALIE_PER_BLOCCO = 50


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": msg}, status=status)


def _body(request) -> dict:
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _txt(value, max_len: int) -> str:
    return str(value or "").strip()[:max_len]


def _mail_mode(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in AnomaliaControllo.MailMode.values else AnomaliaControllo.MailMode.SUBITO


def _get_controllo(request, pk: int):
    """Il controllo è dell'operatore che l'ha aperto (o di un superuser)."""
    controllo = AnomaliaControllo.objects.filter(pk=pk).first()
    if controllo is None:
        return None, _err("Controllo non trovato", 404)
    if controllo.operatore_id != request.user.pk and not request.user.is_superuser:
        return None, _err("Permesso negato: il controllo è di un altro operatore", 403)
    return controllo, None


@login_required
@require_GET
def api_controlli(request):
    """Controlli ancora aperti dell'utente sull'OP (per riprenderli) e fasi già usate."""
    from .views import _can_edit_anomalie_for_op

    op_id = _txt(request.GET.get("op_id"), 100)
    if not op_id:
        return _err("op_id obbligatorio")
    if not _can_edit_anomalie_for_op(request, op_id):
        return _err("Permesso negato: non autorizzato a modificare questo OP", 403)
    recenti = timezone.now() - timedelta(days=7)
    aperti = AnomaliaControllo.objects.filter(
        op_id__iexact=op_id, operatore=request.user, terminato_at__isnull=True, created_at__gte=recenti,
    ).order_by("-id")[:5]
    fasi = list(dict.fromkeys(
        AnomaliaControllo.objects.filter(op_id__iexact=op_id).order_by("-id").values_list("fase", flat=True)[:30]
    ))
    return JsonResponse({
        "success": True,
        "controlli": [cs.serializza_controllo(c, con_allegati=False) for c in aperti],
        "fasi": fasi,
    })


@login_required
@require_GET
def api_controllo_dettaglio(request, pk: int):
    controllo, error = _get_controllo(request, pk)
    if error:
        return error
    return JsonResponse({
        "success": True,
        "controllo": cs.serializza_controllo(controllo),
        "destinatari": cs.destinatari_display(controllo.op_id),
    })


@login_required
@require_POST
def api_controllo_apri(request):
    from .views import _can_edit_anomalie_for_op, _current_user_identity

    data = _body(request)
    op_id = _txt(data.get("op_id"), 100)
    fase = _txt(data.get("fase"), 100)
    if not op_id:
        return _err("op_id obbligatorio")
    if not fase:
        return _err("Indica la fase del controllo")
    if not _can_edit_anomalie_for_op(request, op_id):
        return _err("Permesso negato: non autorizzato a modificare questo OP", 403)
    identity = _current_user_identity(request)
    controllo = AnomaliaControllo.objects.create(
        op_id=op_id,
        op_item_id=_txt(data.get("op_item_id"), 100),
        fase=fase,
        mail_mode=_mail_mode(data.get("mail_mode")),
        operatore=request.user,
        operatore_display=_txt(identity.get("name") or request.user.get_full_name() or request.user.username, 200),
    )
    log_action(request, "anomalie_controllo_aperto", "anomalie", {
        "controllo_id": controllo.pk, "op_id": op_id, "fase": fase, "mail_mode": controllo.mail_mode,
    })
    return JsonResponse({"success": True, "controllo": cs.serializza_controllo(controllo)})


@login_required
@require_POST
def api_controllo_impostazioni(request, pk: int):
    """Cambio fase o modalità mail: vale per i blocchi salvati da qui in avanti."""
    controllo, error = _get_controllo(request, pk)
    if error:
        return error
    if controllo.terminato_at:
        return _err("Il controllo è già terminato", 409)
    data = _body(request)
    fields = ["updated_at"]
    if "fase" in data:
        fase = _txt(data.get("fase"), 100)
        if not fase:
            return _err("Indica la fase del controllo")
        controllo.fase = fase
        fields.append("fase")
    if "mail_mode" in data:
        controllo.mail_mode = _mail_mode(data.get("mail_mode"))
        fields.append("mail_mode")
    controllo.save(update_fields=fields)
    return JsonResponse({"success": True, "controllo": cs.serializza_controllo(controllo, con_allegati=False)})


@login_required
@require_POST
def api_controllo_blocco(request, pk: int):
    """Salva (nuovo o riaperto) un blocco di seriali con le sue anomalie."""
    from .views import _salva_riga_anomalia

    controllo, error = _get_controllo(request, pk)
    if error:
        return error
    if controllo.terminato_at:
        return _err("Il controllo è già terminato", 409)
    data = _body(request)

    voci = normalizza_voci(data.get("seriali") if isinstance(data.get("seriali"), list) else [])
    if not voci:
        return _err("Inserisci almeno un seriale")
    label = etichetta_blocco(voci)
    stati = [s for s in (_txt(v, 60) for v in (data.get("stato_superficie") or [])) if s][:10]
    anomalie_in = data.get("anomalie") if isinstance(data.get("anomalie"), list) else []
    anomalie = []
    for item in anomalie_in[:MAX_ANOMALIE_PER_BLOCCO]:
        if not isinstance(item, dict):
            continue
        testo = _txt(item.get("testo"), 4000)
        local_id = item.get("local_id")
        local_id = int(local_id) if str(local_id or "").isdigit() else None
        if testo or local_id:
            anomalie.append({"local_id": local_id, "testo": testo})
    if not any(a["testo"] for a in anomalie):
        return _err("Descrivi almeno un'anomalia")
    if any(not a["testo"] for a in anomalie):
        return _err("Ogni anomalia deve avere una descrizione")

    blocco = None
    esistenti: dict[int, dict] = {}
    gestite: set[int] = set()
    if data.get("blocco_id"):
        blocco = AnomaliaBlocco.objects.filter(pk=data.get("blocco_id"), controllo=controllo).first()
        if blocco is None:
            return _err("Blocco non trovato", 404)
        ids_blocco = list(
            AnomaliaSegnalazioneMeta.objects.filter(blocco=blocco).values_list("anomalia_id", flat=True)
        )
        esistenti = cs.carica_righe(ids_blocco)
        gestite = {i for i, row in esistenti.items() if cs.riga_gestita(row)}
        stati_prima = blocco.stato_superficie if isinstance(blocco.stato_superficie, list) else []
        if gestite and (label != blocco.seriale_label or stati != stati_prima):
            return _err(
                "Il capocommessa ha già deciso su almeno un'anomalia del blocco: seriali e stato superficie non si possono più cambiare.",
                409,
            )
        for a in anomalie:
            if a["local_id"] and a["local_id"] not in esistenti:
                return _err("Anomalia non appartenente al blocco", 400)
            if a["local_id"] in gestite:
                _stati, testo_prima = cs.separa_descrizione(esistenti[a["local_id"]].get("descrizione"))
                if a["testo"] != testo_prima:
                    return _err(f"L'anomalia #{a['local_id']} è già stata gestita dal capocommessa e non si può modificare.", 409)
    elif any(a["local_id"] for a in anomalie):
        return _err("Anomalia non appartenente al blocco", 400)

    # Stato superficie obbligatorio per blocco (se la configurazione ne prevede).
    # Un blocco già deciso dal capocommessa resta com'era: non si può più cambiare.
    bloccato = bool(blocco is not None and gestite)
    if not stati and not bloccato and cs.stati_superficie_configurati():
        return _err("Indica lo stato superficie del blocco", 400)

    # Stesso S/N in più blocchi: ammesso (es. due fasi o due stati superficie diversi)
    # ma solo dopo che l'operatore l'ha confermato esplicitamente.
    ripetuti = cs.seriali_ripetuti(controllo, voci, escludi_blocco_id=blocco.pk if blocco else None)
    if ripetuti and not data.get("conferma_seriali_ripetuti"):
        return JsonResponse({
            "success": False,
            "code": "seriali_ripetuti",
            "error": "Alcuni seriali sono già in un altro blocco di questo controllo.",
            "seriali_ripetuti": [{"seriale": t, "blocco": n} for t, n in ripetuti.items()],
        }, status=409)

    with transaction.atomic():
        if blocco is None:
            ultimo = controllo.blocchi.order_by("-ordine").values_list("ordine", flat=True).first()
            blocco = AnomaliaBlocco.objects.create(
                controllo=controllo,
                ordine=(ultimo or 0) + 1,
                fase=controllo.fase,
                seriali=voci,
                seriale_label=label,
                stato_superficie=stati,
            )
        else:
            blocco.seriali = voci
            blocco.seriale_label = label
            blocco.stato_superficie = stati
            blocco.save(update_fields=["seriali", "seriale_label", "stato_superficie", "updated_at"])

    risultati = []
    da_notificare = []
    for ordine, a in enumerate(anomalie, start=1):
        descrizione = cs.componi_descrizione(a["testo"], stati)
        prima = esistenti.get(a["local_id"]) if a["local_id"] else None
        if prima is not None:
            if cs.riga_gestita(prima) or (
                str(prima.get("descrizione") or "").strip() == descrizione and str(prima.get("seriale") or "") == label
            ):
                AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=a["local_id"]).update(ordine_nel_blocco=ordine)
                risultati.append({"local_id": a["local_id"], "ok": True, "invariata": True})
                continue
        esito = _salva_riga_anomalia(request, {
            "item_id": f"local:{a['local_id']}" if a["local_id"] else "",
            "op_id": controllo.op_id,
            "op_item_id": controllo.op_item_id,
            "sn": label,
            "desc": descrizione,
            "note": "",
            "avanzamento": "In attesa",
            "pezzi_prec": False,
            "aprire_rdc": False,
            "segnalare": False,
            "chiudere": False,
        }, notifica_debounce=False)
        if not esito.get("success"):
            risultati.append({"local_id": a["local_id"], "ok": False, "error": esito.get("error", "")})
            continue
        local_id = esito.get("local_id")
        if not local_id:
            # La riga potrebbe essere stata scritta senza che il DB ne restituisse l'id:
            # meglio un errore leggibile che un 500 (e nessun collegamento a caso).
            risultati.append({"local_id": None, "ok": False, "error": "Il database non ha restituito il numero dell'anomalia salvata"})
            continue
        AnomaliaSegnalazioneMeta.objects.update_or_create(
            anomalia_id=local_id,
            defaults={
                "controllo": controllo,
                "blocco": blocco,
                "ordine_nel_blocco": ordine,
                "fase": blocco.fase,
            },
        )
        _sync_scheda(local_id)
        da_notificare.append(local_id)
        risultati.append({"local_id": local_id, "ok": True, "creata": bool(esito.get("created"))})

    if da_notificare:
        cs.accoda_notifica(controllo, da_notificare)
    errori = [r["error"] for r in risultati if not r["ok"]]
    log_action(request, "anomalie_controllo_blocco", "anomalie", {
        "controllo_id": controllo.pk, "blocco_id": blocco.pk, "op_id": controllo.op_id,
        "seriali": label, "anomalie": [r.get("local_id") for r in risultati], "errori": len(errori),
        "stato_superficie": stati, "seriali_ripetuti": sorted(ripetuti),
    })
    controllo.refresh_from_db()
    return JsonResponse({
        "success": not errori,
        "error": "; ".join(errori),
        "blocco_id": blocco.pk,
        "risultati": risultati,
        "controllo": cs.serializza_controllo(controllo),
    }, status=200 if not errori else 207)


def _sync_scheda(local_id: int) -> None:
    """Scheda qualità / NC dell'OP: stesso aggancio di ``api_salva``, mai bloccante."""
    try:
        from .qualita_service import sync_da_anomalia

        with transaction.atomic():
            scheda = sync_da_anomalia(local_id)
            if scheda and scheda.nc_id:
                AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=local_id).update(nc_id=scheda.nc_id)
    except Exception:
        logger.warning("controllo: scheda qualita' non aggiornata id=%s", local_id, exc_info=True)


@login_required
@require_POST
def api_controllo_termina(request, pk: int):
    controllo, error = _get_controllo(request, pk)
    if error:
        return error
    if controllo.terminato_at is None:
        controllo.terminato_at = timezone.now()
        controllo.save(update_fields=["terminato_at", "updated_at"])
    esito = {"sent": False, "reason": "nessuna_anomalia"}
    if controllo.da_notificare:
        esito = cs.invia_mail_controllo(controllo)
    log_action(request, "anomalie_controllo_terminato", "anomalie", {
        "controllo_id": controllo.pk, "op_id": controllo.op_id, "mail": esito,
    })
    controllo.refresh_from_db()
    return JsonResponse({
        "success": True,
        "mail": esito,
        "controllo": cs.serializza_controllo(controllo, con_allegati=False),
    })
