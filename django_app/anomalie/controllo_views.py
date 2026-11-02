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
from .seriali import comprimi_seriali, espandi_voce, etichetta_blocco, normalizza_voci

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
    """Dal 16/10/2026 la mail parte solo a fine controllo, qualunque cosa chieda la pagina."""
    return AnomaliaControllo.MailMode.FINE


def _get_controllo(request, pk: int):
    """Il controllo è dell'operatore che l'ha aperto (o di un superuser)."""
    controllo = AnomaliaControllo.objects.filter(pk=pk).first()
    if controllo is None:
        return None, _err("Controllo non trovato", 404)
    if controllo.operatore_id != request.user.pk and not request.user.is_superuser:
        return None, _err("Permesso negato: il controllo è di un altro operatore", 403)
    return controllo, None


def _op_esiste(op_id: str) -> bool:
    from .views import _fetch_all_dict, _has_table

    if not op_id or not _has_table("ordini_produzione"):
        return False
    return bool(_fetch_all_dict("SELECT COUNT(*) AS n FROM ordini_produzione WHERE title = %s", [op_id])[0]["n"])


def _op_ancora_da_creare(op_id: str) -> bool:
    try:
        return not _op_esiste(op_id)
    except Exception:
        return False


def _apri_su_op_nuovo(request, dati) -> tuple[str, dict, JsonResponse | None]:
    """Controllo su un OP nuovo non ancora creato: ``(titolo, dati puliti, errore)``.
    Stesse regole di «+ Nuovo OP»; l'OP vero nasce al primo «Salva blocco»."""
    from .views import _can_create_anomalie_for_op, _op_role_codes_da_persone, titolo_nuovo_op

    if not isinstance(dati, dict):
        return "", {}, _err("Dati del nuovo OP non validi")
    campi = ("causale_doc", "anno", "numero", "fase", "pn", "capocommessa", "car", "note", "collaudo_benestare")
    pulito = {k: dati.get(k) for k in campi if k in dati}
    for k, label in (("pn", "P/N"), ("anno", "anno"), ("numero", "numero"), ("capocommessa", "Capocommessa"),
                     ("car", "CAR")):
        if not str(pulito.get(k) or "").strip():
            return "", {}, _err(f"{label} obbligatorio")
    titolo = titolo_nuovo_op(pulito)
    if _op_esiste(titolo):
        return "", {}, _err(f"L'OP {titolo} esiste già: sceglilo dall'elenco.", 409)
    puo = _can_create_anomalie_for_op(request, titolo) or bool(
        _op_role_codes_da_persone(request, pulito.get("capocommessa"), pulito.get("car")))
    if not puo:
        return "", {}, _err("Permesso negato: non autorizzato ad aprire segnalazioni su questo OP", 403)
    return titolo, pulito, None


def crea_op_del_controllo(request, controllo) -> tuple[dict | None, str]:
    """Primo «Salva blocco» su un OP nuovo: crea l'OP (o aggancia quello con lo stesso
    titolo, se nel frattempo l'ha creato qualcun altro) e svuota ``op_nuovo``."""
    from .views import _fetch_all_dict, crea_op_da_dati

    if not controllo.op_nuovo:
        return None, ""
    if _op_esiste(controllo.op_id):
        rows = _fetch_all_dict(
            "SELECT sharepoint_item_id, title, part_number, capocomessa, incaricato, stato "
            "FROM ordini_produzione WHERE title = %s", [controllo.op_id])
        r = rows[0] if rows else {}
        op = {"item_id": str(r.get("sharepoint_item_id") or ""), "id": r.get("title") or controllo.op_id,
              "pn": r.get("part_number") or "—", "capo": r.get("capocomessa") or "—",
              "car": r.get("incaricato") or "—", "stato": r.get("stato") or "Aperto"}
    else:
        esito = crea_op_da_dati(request, controllo.op_nuovo)
        if not esito["success"] or not esito.get("op"):
            return None, esito.get("error") or "Creazione OP non riuscita"
        op = esito["op"]
    controllo.op_id = str(op.get("id") or controllo.op_id)[:100]
    controllo.op_item_id = str(op.get("item_id") or "")[:100]
    controllo.op_nuovo = {}
    controllo.save(update_fields=["op_id", "op_item_id", "op_nuovo", "updated_at"])
    log_action(request, "anomalie_controllo_op_creato", "anomalie",
               {"controllo_id": controllo.pk, "op_id": controllo.op_id})
    return op, ""


@login_required
@require_GET
def api_controlli(request):
    """Controlli ancora aperti dell'utente sull'OP (per riprenderli) e fasi già usate."""
    from .views import _can_create_anomalie_for_op

    op_id = _txt(request.GET.get("op_id"), 100)
    if not op_id:
        return _err("op_id obbligatorio")
    if not _can_create_anomalie_for_op(request, op_id) and not _op_ancora_da_creare(op_id):
        return _err("Permesso negato: non autorizzato ad aprire segnalazioni su questo OP", 403)
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
        "destinatari": cs.destinatari_display(controllo.op_id, controllo.destinatari_extra),
    })


@login_required
@require_GET
def api_destinatari_op(request):
    """Chi riceverà la mail del controllo su un OP: serve alla pagina prima ancora
    che il controllo esista, per mostrare i destinatari già in fase di avvio."""
    from .views import _can_create_anomalie_for_op

    op_id = _txt(request.GET.get("op_id"), 100)
    if not op_id:
        return _err("op_id obbligatorio")
    if not _can_create_anomalie_for_op(request, op_id):
        return _err("Permesso negato: non autorizzato ad aprire segnalazioni su questo OP", 403)
    return JsonResponse({"success": True, "destinatari": cs.destinatari_display(op_id)})


@login_required
@require_GET
def api_persone(request):
    """Ricerca persone (anagrafica con email di notifica) da aggiungere in copia;
    con ``ruolo=capocommessa`` l'elenco dei capicommessa configurati."""
    if request.GET.get("ruolo") == "capocommessa":
        return JsonResponse({"success": True, "results": cs.capi_commessa_persone()})
    return JsonResponse({"success": True, "results": cs.cerca_persone(request.GET.get("q"))})


@login_required
@require_POST
def api_controllo_apri(request):
    from .views import _can_create_anomalie_for_op, _current_user_identity

    data = _body(request)
    op_id = _txt(data.get("op_id"), 100)
    fase = _txt(data.get("fase"), 100)
    op_nuovo = {}
    if data.get("op_nuovo"):
        if not fase:
            return _err("Indica la fase del controllo")
        op_id, op_nuovo, errore = _apri_su_op_nuovo(request, data.get("op_nuovo"))
        if errore:
            return errore
    if not op_id:
        return _err("op_id obbligatorio")
    if not fase:
        return _err("Indica la fase del controllo")
    if not op_nuovo and not _can_create_anomalie_for_op(request, op_id):
        return _err("Permesso negato: non autorizzato ad aprire segnalazioni su questo OP", 403)
    extra, rifiutati = cs.normalizza_destinatari_extra(data.get("destinatari_extra"))
    if rifiutati:
        return _err("Indirizzi non collegati a nessuna persona in anagrafica: " + ", ".join(rifiutati))
    identity = _current_user_identity(request)
    controllo = AnomaliaControllo.objects.create(
        op_id=op_id,
        op_item_id="" if op_nuovo else _txt(data.get("op_item_id"), 100),
        op_nuovo=op_nuovo,
        fase=fase,
        mail_mode=_mail_mode(data.get("mail_mode")),
        destinatari_extra=extra,
        operatore=request.user,
        operatore_display=_txt(identity.get("name") or request.user.get_full_name() or request.user.username, 200),
    )
    log_action(request, "anomalie_controllo_aperto", "anomalie", {
        "controllo_id": controllo.pk, "op_id": op_id, "fase": fase, "mail_mode": controllo.mail_mode,
        "destinatari_extra": [d["email"] for d in extra],
    })
    return JsonResponse({"success": True, "controllo": cs.serializza_controllo(controllo)})


@login_required
@require_POST
def api_controllo_impostazioni(request, pk: int):
    """Cambio fase, modalità mail o destinatari aggiuntivi: vale per le mail da qui in avanti."""
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
    if "destinatari_extra" in data:
        extra, rifiutati = cs.normalizza_destinatari_extra(data.get("destinatari_extra"))
        if rifiutati:
            return _err("Indirizzi non collegati a nessuna persona in anagrafica: " + ", ".join(rifiutati))
        controllo.destinatari_extra = extra
        fields.append("destinatari_extra")
        log_action(request, "anomalie_controllo_destinatari", "anomalie", {
            "controllo_id": controllo.pk, "op_id": controllo.op_id,
            "destinatari_extra": [d["email"] for d in extra],
        })
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
            # Flag «su tutti i seriali del blocco» (default sì); se spento, i S/N scelti.
            tutti = item.get("tutti", True) is not False
            scelti = item.get("seriali") if isinstance(item.get("seriali"), list) else []
            anomalie.append({"local_id": local_id, "testo": testo, "tutti": tutti, "seriali": scelti})
    if not any(a["testo"] for a in anomalie):
        return _err("Descrivi almeno un'anomalia")
    if any(not a["testo"] for a in anomalie):
        return _err("Ogni anomalia deve avere una descrizione")

    # Seriali di ciascuna anomalia: tutti quelli del blocco oppure solo una parte.
    chiavi_blocco: dict[str, str] = {}
    for voce in voci:
        for t in espandi_voce(voce):
            chiavi_blocco.setdefault(t.lower(), t)
    token_blocco = list(chiavi_blocco.values())
    for n, a in enumerate(anomalie, start=1):
        a["sn"] = label
        a["copertura"] = None
        if a["tutti"]:
            continue
        scelti_lower = {t.lower() for v in normalizza_voci(a["seriali"]) for t in espandi_voce(v)}
        subset = [t for t in token_blocco if t.lower() in scelti_lower]
        if not subset:
            return _err(f"Anomalia {n}: scegli su quali seriali è presente (o riattiva «Su tutti i seriali del blocco»)")
        if len(subset) < len(chiavi_blocco):
            a["sn"] = etichetta_blocco(comprimi_seriali(subset))
            a["copertura"] = subset

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

    # Ogni S/N del blocco dovrebbe avere almeno un'anomalia: se no, avviso da confermare
    # (di solito è un seriale da togliere dal blocco o una selezione dimenticata).
    scoperti = cs.seriali_senza_anomalia(voci, [a["copertura"] for a in anomalie])
    if scoperti and not data.get("conferma_seriali_scoperti"):
        return JsonResponse({
            "success": False,
            "code": "seriali_scoperti",
            "error": "Alcuni seriali del blocco non hanno nessuna anomalia.",
            "seriali_scoperti": scoperti,
        }, status=409)

    op_creato = None
    if controllo.op_nuovo:
        op_creato, errore_op = crea_op_del_controllo(request, controllo)
        if errore_op:
            return _err(f"OP non creato: {errore_op}", 400)

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
                str(prima.get("descrizione") or "").strip() == descrizione and str(prima.get("seriale") or "") == a["sn"]
            ):
                AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=a["local_id"]).update(ordine_nel_blocco=ordine)
                risultati.append({"local_id": a["local_id"], "ok": True, "invariata": True})
                continue
        esito = _salva_riga_anomalia(request, {
            "item_id": f"local:{a['local_id']}" if a["local_id"] else "",
            "op_id": controllo.op_id,
            "op_item_id": controllo.op_item_id,
            "sn": a["sn"],
            "desc": descrizione,
            "note": "",
            "avanzamento": "In attesa",
            "pezzi_prec": False,
            "aprire_rdc": False,
            "segnalare": False,
            "chiudere": False,
        }, notifica_debounce=False, da_controllo=True)
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
    if not errori and controllo.bozza:
        cs.salva_bozza(controllo, {})
    log_action(request, "anomalie_controllo_blocco", "anomalie", {
        "controllo_id": controllo.pk, "blocco_id": blocco.pk, "op_id": controllo.op_id,
        "seriali": label, "anomalie": [r.get("local_id") for r in risultati], "errori": len(errori),
        "stato_superficie": stati, "seriali_ripetuti": sorted(ripetuti),
        "seriali_scoperti": scoperti,
    })
    controllo.refresh_from_db()
    return JsonResponse({
        "success": not errori,
        "error": "; ".join(errori),
        "blocco_id": blocco.pk,
        "risultati": risultati,
        "controllo": cs.serializza_controllo(controllo),
        "op_creato": op_creato,
    }, status=200 if not errori else 207)


@login_required
@require_POST
def api_controllo_bozza(request, pk: int):
    """Salvataggio automatico del blocco in scrittura (``{"bozza": {...}}``; vuoto = cancella)."""
    controllo, error = _get_controllo(request, pk)
    if error:
        return error
    if controllo.terminato_at:
        return _err("Il controllo è già terminato", 409)
    if not cs.salva_bozza(controllo, _body(request).get("bozza")):
        return _err("Bozza troppo grande", 413)
    return JsonResponse({"success": True, "bozza_at": controllo.bozza_at.isoformat() if controllo.bozza_at else ""})


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


MAX_CLONA = 200


@login_required
@require_GET
def api_clona_dati(request):
    """Dati per clonare un OP: OP di origine e blocchi con le anomalie scelte.

    Le anomalie dello stesso blocco di seriali restano insieme (stessi S/N e stato
    superficie, ognuna con i suoi S/N se non vale per tutti); quelle nate fuori da
    un controllo diventano un blocco ciascuna. La fase proposta è la più usata.
    """
    from collections import Counter

    from .seriali import espandi_seriale_composito
    from .views import _can_view_anomalie_for_op, _fetch_all_dict, _list_attachments_for_local, _row_capocommessa

    op_id = _txt(request.GET.get("op_id"), 100)
    try:
        ids = [int(x) for x in str(request.GET.get("anomalie") or "").split(",") if x.strip()][:MAX_CLONA]
    except ValueError:
        return _err("Elenco anomalie non valido")
    if not op_id or not ids:
        return _err("OP e anomalie da copiare obbligatori")
    if not _can_view_anomalie_for_op(request, op_id):
        return _err("Permesso negato: non puoi consultare le anomalie di questo OP", 403)

    righe = {
        i: r for i, r in cs.carica_righe(ids).items()
        if str(r.get("ex_op_nominativo") or "").strip().lower() == op_id.lower()
    }
    metas = {
        m.anomalia_id: m
        for m in AnomaliaSegnalazioneMeta.objects.filter(anomalia_id__in=list(righe)).select_related("blocco")
    }
    blocchi: list[dict] = []
    per_chiave: dict[str, dict] = {}
    fasi: Counter = Counter()
    for i in dict.fromkeys(ids):
        row = righe.get(i)
        if row is None:
            continue
        meta = metas.get(i)
        stati, testo = cs.separa_descrizione(row.get("descrizione"))
        if meta and meta.fase:
            fasi[meta.fase] += 1
        if meta and meta.blocco_id:
            chiave = f"b{meta.blocco_id}"
            info = cs.seriali_anomalia(row.get("seriale"), meta.blocco)
            voci = list(meta.blocco.seriali) if isinstance(meta.blocco.seriali, list) else []
            stati_blocco = list(meta.blocco.stato_superficie) if isinstance(meta.blocco.stato_superficie, list) else []
            copertura = {"tutti": info["tutti"], "seriali": [] if info["tutti"] else info["seriali"]}
        else:
            chiave = f"r{i}"
            voci = comprimi_seriali(espandi_seriale_composito(row.get("seriale")))
            stati_blocco = stati
            copertura = {"tutti": True, "seriali": []}
        blocco = per_chiave.get(chiave)
        if blocco is None:
            blocco = {"seriali": voci, "stato_superficie": stati_blocco, "anomalie": []}
            per_chiave[chiave] = blocco
            blocchi.append(blocco)
        blocco["anomalie"].append({
            "origine_id": i,
            "testo": testo,
            **copertura,
            "allegati": len(_list_attachments_for_local(i)),
        })

    op_info = {"id": op_id, "pn": "", "capo": "", "car": "", "stato": ""}
    try:
        rows = _fetch_all_dict("SELECT TOP 1 * FROM ordini_produzione WHERE title = %s", [op_id])
    except Exception:
        rows = []
    if rows:
        r = rows[0]
        op_info.update({
            "pn": str(r.get("part_number") or "").strip(),
            "capo": str(_row_capocommessa(r) or "").strip(),
            "car": str(r.get("incaricato") or "").strip(),
            "stato": str(r.get("stato") or "").strip(),
        })
    return JsonResponse({
        "success": True,
        "op": op_info,
        "fase": fasi.most_common(1)[0][0] if fasi else "",
        "fasi": list(fasi),
        "blocchi": blocchi,
    })
