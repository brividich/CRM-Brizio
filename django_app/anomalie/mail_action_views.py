"""Vista per azione anomalie via link email (token monouso, nessun login richiesto).

URL: /gestione-anomalie/mail-action/<token>/

Il token stesso è l'unica autorizzazione. L'identità viene tracciata tramite
i metadati del token (recipient_display, recipient_email) e l'IP del richiedente.
"""
from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.audit import log_action
from core.public_headers import risposta_pubblica, risposta_pubblica_con_form

from .guida import sezione as guida_sezione

logger = logging.getLogger(__name__)

# Azioni che modificano lo stato: monouso.
_DISPOSITIVE_ACTIONS = {"prendi_in_carico", "approva", "respingi", "richiedi_modifica", "chiudi", "aggiorna_avanzamento"}
_STATO_FIELD = "avanzamento"
# Azioni in cui la nota generale del form vale come nota di ogni anomalia.
_NOTE_GLOBALE_ACTIONS = {"approva", "respingi", "richiedi_modifica"}

# Mapping azione → valore da scrivere nel campo avanzamento (tabella legacy)
# aggiorna_avanzamento non ha default: il valore arriva sempre per-riga dal form.
_ACTION_TO_AVANZAMENTO = {
    "prendi_in_carico": "In attesa",
    "approva": "Accetto lo stato",
    "chiudi": "Finito trattato",
}


@risposta_pubblica_con_form
@require_http_methods(["GET", "POST"])
def mail_action_view(request: HttpRequest, token: str) -> HttpResponse:
    """Pagina portale raggiunta dal link email con token anomalie. Nessun login richiesto."""
    from .mail_action_models import AnomaliaActionLog, AnomaliaMailActionToken

    try:
        token_obj = AnomaliaMailActionToken.objects.get(token=token)
    except AnomaliaMailActionToken.DoesNotExist:
        return _render_error(request, "Token non valido o inesistente.", "invalid")

    if token_obj.is_revoked:
        return _render_error(request, "Questo link è stato revocato.", "revoked")

    if timezone.now() > token_obj.expires_at:
        return _render_error(request, "Questo link è scaduto.", "expired")

    action = token_obj.action
    op_id = token_obj.op_id
    is_dispositive = action in _DISPOSITIVE_ACTIONS

    # Per azioni già usate: mostra riepilogo senza permettere di rifare
    if token_obj.is_used:
        logs = list(
            AnomaliaActionLog.objects.filter(token=token_obj).order_by("created_at")[:20]
        )
        return render(
            request,
            "anomalie/pages/mail_action_done.html",
            {
                "token": token_obj,
                "action_logs": logs,
                "already_done": True,
            },
        )

    # Se il token ha un op_id, carica TUTTE le anomalie aperte dell'OP dal DB.
    # Così la mail-action mostra sempre lo snapshot live completo, non solo quelle
    # presenti in anomalie_ids al momento della creazione del token.
    if op_id:
        anomalie_live = _load_anomalie_live_by_op(op_id)
        if not anomalie_live:
            # Fallback: prova con gli ID salvati nel token (caso OP senza match)
            anomalie_live = _load_anomalie_live(token_obj.anomalie_ids, op_id)
    else:
        anomalie_live = _load_anomalie_live(token_obj.anomalie_ids, op_id)

    if request.method == "POST":
        return _handle_post(request, token_obj, anomalie_live)

    gruppi = _raggruppa(token_obj, anomalie_live)

    return render(
        request,
        "anomalie/pages/mail_action_form.html",
        {
            "token": token_obj,
            "anomalie": anomalie_live,
            "gruppi": gruppi,
            "ha_nuove": any(g.get("nuovo") for g in gruppi),
            "action": action,
            "action_label": _action_label(action),
            "op_id": op_id,
            "op_nominativo": token_obj.op_nominativo,
            "is_dispositive": is_dispositive,
            "can_edit": True,  # il token valido è l'unica autorizzazione su questa pagina pubblica
            # Pagina pubblica: la guida non può rimandare a una pagina col login,
            # quindi il paragrafo che la riguarda viene mostrato qui.
            "guida": guida_sezione("mail"),
        },
    )


def _handle_post(request: HttpRequest, token_obj, anomalie_live: list[dict]) -> HttpResponse:
    from .mail_action_models import AnomaliaActionLog

    action = token_obj.action
    is_dispositive = action in _DISPOSITIVE_ACTIONS

    # Double-check con refresh per prevenire doppia sottomissione
    token_obj.refresh_from_db()
    if token_obj.is_used:
        return _render_error(request, "Questa azione è già stata registrata.", "already_used")
    if token_obj.is_revoked or timezone.now() > token_obj.expires_at:
        return _render_error(request, "Il link non è più valido.", "expired")

    note = (request.POST.get("note") or "").strip()[:2000]
    nuovo_avanzamento = (request.POST.get("avanzamento") or "").strip()

    # Aggiornamenti individuali per riga: {str(id): {"avanzamento": ..., "note": ...}}
    aggiornamenti_json_raw = (request.POST.get("aggiornamenti_json") or "{}").strip()
    try:
        aggiornamenti_per_id: dict = json.loads(aggiornamenti_json_raw) if aggiornamenti_json_raw else {}
    except (ValueError, TypeError):
        aggiornamenti_per_id = {}

    if action == "visualizza":
        _write_action_log(
            request=request,
            token_obj=token_obj,
            anomalie=anomalie_live,
            action=action,
            note=note,
            previous_status="",
            new_status="",
            source=AnomaliaActionLog.Source.MAIL_ACTION,
        )
        # visualizza è sola lettura: il token non viene marcato come usato
        return redirect(reverse("anomalie_mail_action_done", kwargs={"token": token_obj.token}))

    # Azioni dispositive: aggiorna il DB legacy e marca il token monouso
    if is_dispositive:
        # Stessa regola della pagina: una nota scritta non lascia l'anomalia «In attesa».
        from .segnalato_service import STATI_RISPOSTA
        from .views import MSG_NOTA_STATO_IN_ATTESA, MSG_RISPOSTA_SENZA_STATO, _nota_con_stato_in_attesa

        stato_live = {str(a.get("id")): str(a.get(_STATO_FIELD) or "") for a in anomalie_live}
        default_avanzamento = nuovo_avanzamento or _ACTION_TO_AVANZAMENTO.get(action, "")
        for anomalia_id, per_riga in aggiornamenti_per_id.items():
            if str(anomalia_id) not in stato_live or not isinstance(per_riga, dict):
                continue
            riga_note = str(per_riga.get("note") or "").strip() or (note if action in _NOTE_GLOBALE_ACTIONS else "")
            # Avanzamento vuoto = «invariato»: vale quello attuale.
            riga_avanzamento = (
                str(per_riga.get("avanzamento") or "").strip() or default_avanzamento or stato_live[str(anomalia_id)]
            )
            in_attesa_di_segnalazione = any(per_riga.get(k) for k in ("aprire_rdc", "segnalare", "segnala_terzista"))
            if not in_attesa_di_segnalazione and _nota_con_stato_in_attesa(riga_note, riga_avanzamento):
                return _render_error(
                    request, f"Anomalia #{anomalia_id}: {MSG_NOTA_STATO_IN_ATTESA} Torna indietro e correggi.", "invalid",
                )
            if ((str(per_riga.get("risposta_cliente") or "").strip() or str(per_riga.get("risposta_terzista") or "").strip())
                    and not per_riga.get("chiudi_manuale") and riga_avanzamento.strip().lower() in STATI_RISPOSTA):
                return _render_error(
                    request, f"Anomalia #{anomalia_id}: {MSG_RISPOSTA_SENZA_STATO} Torna indietro e correggi.", "invalid",
                )
            # Prima decisione «Azione di recupero»: si chiude solo con l'azione effettuata.
            if (per_riga.get("chiudere") or per_riga.get("chiudi_manuale")) and not per_riga.get("aprire_rdc"):
                from .tempi_service import MSG_SERVE_AZIONE, serve_azione_per_chiudere
                if serve_azione_per_chiudere(int(anomalia_id)):
                    return _render_error(
                        request, f"Anomalia #{anomalia_id}: {MSG_SERVE_AZIONE} Si registra dal portale.", "invalid",
                    )
        # Presa in carico atomica del token PRIMA di toccare le anomalie: con due invii
        # simultanei (doppio click, due schede) solo uno passa. Se l'applicazione
        # solleva un'eccezione il token torna disponibile per un nuovo tentativo.
        if not _claim_token(token_obj, request):
            return _render_error(request, "Questa azione è già stata registrata.", "already_used")
        try:
            return _apply_dispositive(request, token_obj, anomalie_live, action, note, nuovo_avanzamento, aggiornamenti_per_id)
        except Exception:
            _release_token(token_obj)
            raise
    _write_action_log(
        request=request,
        token_obj=token_obj,
        anomalie=anomalie_live,
        action=action,
        note=note,
        previous_status="",
        new_status="",
        source=AnomaliaActionLog.Source.MAIL_ACTION,
    )
    return redirect(reverse("anomalie_mail_action_done", kwargs={"token": token_obj.token}))


def _claim_token(token_obj, request: HttpRequest) -> bool:
    from .mail_action_models import AnomaliaMailActionToken

    now = timezone.now()
    claimed = AnomaliaMailActionToken.objects.filter(
        pk=token_obj.pk, is_used=False, is_revoked=False, expires_at__gte=now,
    ).update(
        is_used=True,
        used_at=now,
        ip_address_used=_get_ip(request),
        user_agent_used=request.META.get("HTTP_USER_AGENT", "")[:500],
    )
    if claimed:
        token_obj.refresh_from_db()
    return bool(claimed)


def _release_token(token_obj) -> None:
    from .mail_action_models import AnomaliaMailActionToken

    AnomaliaMailActionToken.objects.filter(pk=token_obj.pk).update(is_used=False, used_at=None)
    logger.warning("mail_action: applicazione fallita, token %s… rilasciato", str(token_obj.token)[:8])


def _segna_decise_e_azioni(anomalie_live) -> None:
    """Per «Applica la stessa decisione anche a…»: ``decisa`` (il capocommessa ha già
    deciso qualcosa) e ``serve_azione`` (prima decisione «Azione di recupero» senza
    azione effettuata: la decisione si applica ma l'anomalia resta aperta)."""
    from .controllo_service import riga_gestita

    serve: set[int] = set()
    try:
        from .quality_models import AnomaliaSchedaQualita
        from .tempi_service import AVANZAMENTO_RECUPERO

        ids = [int(a["id"]) for a in anomalie_live if a.get("id")]
        serve = set(AnomaliaSchedaQualita.objects.filter(
            anomalia_id__in=ids, primo_avanzamento__iexact=AVANZAMENTO_RECUPERO, azione_effettuata_il__isnull=True,
        ).values_list("anomalia_id", flat=True)) if ids else set()
    except Exception:
        logger.warning("mail_action: verifica azione effettuata non riuscita", exc_info=True)
    for a in anomalie_live:
        a["decisa"] = riga_gestita(a)
        a["serve_azione"] = int(a.get("id") or 0) in serve


def _salva_allegati_mail(request, token_obj, anomalia_id: int) -> None:
    """Allegati della decisione caricati dal link mail (foto, PDF, mail .msg/.eml).

    Stesse regole della pagina (formati, dimensione, cartella); solo anomalie della
    pagina del token, perché il chiamante passa da ``anomalie_live``. Mai bloccante.
    """
    files = request.FILES.getlist(f"allegati_{anomalia_id}")
    if not files:
        return
    try:
        from .views import _attachment_dir_for_local, salva_file_allegati

        folder = _attachment_dir_for_local(anomalia_id, create=True)
        salvati, nomi, errori = salva_file_allegati(anomalia_id, folder, files, per_decisione=True)
        log_action(request, azione="anomalia_allegato_upload_mail", modulo="anomalie", dettaglio={
            "local_id": anomalia_id, "op_id": token_obj.op_id, "files": nomi, "errori": errori,
            "token": token_obj.token[:8], "recipient": token_obj.recipient_display,
        })
    except Exception:
        logger.warning("mail_action: allegati non salvati id=%s", anomalia_id, exc_info=True)


def _salva_segnalati_mail(token_obj, anomalia_id: int, stato: dict) -> None:
    """«Segnala a terzista», «Segnalato…» e risposte dal form del link mail. Mai bloccante."""
    from . import segnalato_service as segn

    chi_utente = (token_obj.recipient_display or token_obj.recipient_email or "Capocommessa")[:200]
    try:
        from .qualita_service import get_or_create_scheda
        from .quality_models import AnomaliaSchedaQualita

        scheda, _ = get_or_create_scheda(anomalia_id)
        if scheda is not None and scheda.segnala_terzista != stato["terzista"]:
            AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(
                segnala_terzista=stato["terzista"], updated_at=timezone.now())
        for chi in segn.DESTINATARI:
            if stato["segnalati"][chi] != stato["gia"][chi]:
                segn.registra_segnalato(anomalia_id, chi, stato["segnalati"][chi], chi_utente)
            if stato["risposte"][chi]:
                segn.registra_risposta(anomalia_id, chi, stato["risposte"][chi], utente_display=chi_utente)
    except Exception:
        logger.warning("mail_action: segnalato/risposte non salvati id=%s", anomalia_id, exc_info=True)


def _apply_dispositive(request, token_obj, anomalie_live, action, note, nuovo_avanzamento, aggiornamenti_per_id):
    from .mail_action_models import AnomaliaActionLog

    results = []
    default_avanzamento = nuovo_avanzamento or _ACTION_TO_AVANZAMENTO.get(action, "")
    for anomalia in anomalie_live:
        anomalia_id = anomalia.get("id")
        if not anomalia_id:
            continue
        # Solo le anomalie che il capocommessa ha salvato nella pagina cambiano
        # flag, note e numero RDC; le altre ricevono al massimo l'avanzamento
        # di default dell'azione (prima i flag non toccati venivano azzerati).
        toccata = str(anomalia_id) in aggiornamenti_per_id
        per_riga = aggiornamenti_per_id.get(str(anomalia_id)) or {}
        if not isinstance(per_riga, dict):
            per_riga, toccata = {}, False
        riga_avanzamento = str(per_riga.get("avanzamento") or "").strip()[:100] or default_avanzamento
        segn_stato = None
        if toccata:
            from . import segnalato_service as segn

            riga_note = str(per_riga.get("note") or "").strip()[:2000]
            if not riga_note and note and action in _NOTE_GLOBALE_ACTIONS:
                riga_note = note
            # In attesa di risposta la nota già mandata resta com'era.
            if segn.nota_congelata(anomalia.get(_STATO_FIELD), anomalia.get("note_capocommessa")):
                riga_note = None
            riga_aprire_rdc = bool(per_riga.get("aprire_rdc"))
            riga_segnalare = bool(per_riga.get("segnalare"))
            riga_chiudere = bool(per_riga.get("chiudere"))
            riga_numero_rdc = str(per_riga.get("numero_rdc") or "").strip()[:100]
            gia = segn.stato_segnalati(anomalia_id)
            riga_terzista = bool(per_riga["segnala_terzista"]) if "segnala_terzista" in per_riga else gia["segnala_terzista"]
            richiesti = {"cliente": riga_segnalare, "terzista": riga_terzista}
            segnalati = {chi: (bool(per_riga.get(f"segnalato_{chi}")) if f"segnalato_{chi}" in per_riga and richiesti[chi]
                               else gia[chi]) for chi in segn.DESTINATARI}
            appena = [chi for chi in segn.DESTINATARI if segnalati[chi] and not gia[chi]]
            if appena:
                riga_avanzamento = segn.avanzamento_dopo_segnalato(riga_avanzamento, appena, anomalia.get(_STATO_FIELD) or "")
            segn_stato = {"terzista": riga_terzista, "segnalati": segnalati, "gia": gia,
                          "risposte": {chi: str(per_riga.get(f"risposta_{chi}") or "").strip()[:4000]
                                       for chi in segn.DESTINATARI}}
            # Stessa regola della pagina: RDC senza numero o cliente/terzista non ancora
            # avvisati lasciano l'anomalia aperta; «Chiudi» a mano chiude comunque.
            if per_riga.get("chiudi_manuale"):
                riga_chiudere = True
            elif riga_chiudere and action != "chiudi":
                from .views import chiusura_automatica

                riga_chiudere = chiusura_automatica(
                    riga_aprire_rdc, riga_numero_rdc, riga_segnalare, segnalati["cliente"],
                    riga_avanzamento or anomalia.get(_STATO_FIELD) or "", riga_terzista, segnalati["terzista"],
                )
        else:
            riga_note = note if (note and action in _NOTE_GLOBALE_ACTIONS) else None
            riga_aprire_rdc = riga_segnalare = riga_chiudere = None
            riga_numero_rdc = None
            if not riga_avanzamento and action != "chiudi":
                continue
        descrizioni_risposte = per_riga.get("descrizioni_risposte", {})
        prev = anomalia.get(_STATO_FIELD) or ""
        ok = _apply_action_to_anomalia(
            anomalia_id=anomalia_id,
            op_id=token_obj.op_id,
            action=action,
            nuovo_avanzamento=riga_avanzamento,
            note=riga_note,
            aprire_rdc=riga_aprire_rdc,
            segnalare=riga_segnalare,
            chiudere=riga_chiudere,
            numero_rdc=riga_numero_rdc,
        )
        if ok and isinstance(descrizioni_risposte, dict):
            try:
                from .quality_models import AnomaliaDescrizione
                risposta_da = token_obj.recipient_display or token_obj.recipient_email or "Capocommessa"
                for detail_id, response_text in descrizioni_risposte.items():
                    response_text = str(response_text or "").strip()[:5000]
                    if not response_text or not str(detail_id).isdigit():
                        continue
                    AnomaliaDescrizione.objects.filter(
                        pk=int(detail_id), segnalazione__anomalia_id=anomalia_id,
                    ).exclude(risposta_capocommessa=response_text).update(
                        risposta_capocommessa=response_text,
                        risposta_da=risposta_da[:200],
                        risposta_il=timezone.now(),
                        updated_at=timezone.now(),
                    )
            except Exception:
                logger.exception("mail_action: salvataggio risposte descrizione fallito id=%s", anomalia_id)
        if ok and segn_stato is not None:
            _salva_segnalati_mail(token_obj, int(anomalia_id), segn_stato)
        if ok:
            _salva_allegati_mail(request, token_obj, int(anomalia_id))
        if ok:
            # Scheda qualita' e tempi (prima decisione, attesa cliente, chiusura).
            try:
                from django.db import transaction

                from .qualita_service import sync_da_anomalia
                with transaction.atomic():
                    sync_da_anomalia(int(anomalia_id))
            except Exception:
                logger.warning("mail_action: scheda/tempi non aggiornati id=%s", anomalia_id, exc_info=True)
        results.append({
            "id": anomalia_id,
            "ok": ok,
            "prev": prev,
            "new": (riga_avanzamento or prev) if ok else prev,
            "toccata": toccata,
        })

    _write_action_log(
        request=request,
        token_obj=token_obj,
        anomalie=anomalie_live,
        action=action,
        note=note,
        previous_status=", ".join({r["prev"] for r in results if r["prev"]}),
        new_status=", ".join({r["new"] for r in results if r["new"] and r["ok"]}),
        source=AnomaliaActionLog.Source.MAIL_ACTION,
    )
    log_action(
        request,
        azione=f"anomalia_mail_action_{action}",
        modulo="anomalie",
        dettaglio={
            "op_id": token_obj.op_id,
            "anomalie_ids": token_obj.anomalie_ids,
            "note": note,
            "results": results,
            "token": token_obj.token[:8],
            "recipient": token_obj.recipient_display,
        },
    )

    # Mail di conferma post-aggiornamento al segnalante + CC/CAR + lista fissa.
    piano_operatori: list[dict] = []
    try:
        from anomalie.mail_action_service import send_anomalie_update_confirmation
        by_id = {str(a.get("id")): a for a in anomalie_live}
        updates_summary = []
        for r in results:
            if not r.get("ok"):
                continue
            a = by_id.get(str(r["id"]), {})
            per_riga = aggiornamenti_per_id.get(str(r["id"])) or {}
            if not isinstance(per_riga, dict):
                per_riga = {}
            updates_summary.append({
                "id": r["id"],
                "seriale": a.get("seriale") or "",
                "descrizione": a.get("descrizione") or "",
                "avanzamento": r.get("new") or "",
                "note": str(per_riga.get("note") or note or "").strip(),
                "numero_rdc": str(per_riga.get("numero_rdc") or "").strip(),
                "aprire_rdc": bool(per_riga.get("aprire_rdc")) if r.get("toccata") else bool(a.get("aprire_rdc")),
                "segnalare": bool(per_riga.get("segnalare")) if r.get("toccata") else bool(a.get("segnalare_cliente")),
                "chiudere": bool(per_riga.get("chiudere")) or action == "chiudi",
            })
        if updates_summary:
            # Automazione «decisioni all'operatore»: chi ha segnalato riceve una mail
            # dedicata con le decisioni e per questo esce dal riepilogo generico.
            try:
                from anomalie.automazioni_service import prepara_decisioni_operatore
                piano_operatori = prepara_decisioni_operatore(
                    token_obj.op_id, updates_summary, deciso_da_email=token_obj.recipient_email or "",
                )
            except Exception:
                logger.warning("mail_action: decisioni all'operatore non preparate op=%s", token_obj.op_id, exc_info=True)
            send_anomalie_update_confirmation(
                op_id=token_obj.op_id,
                op_nominativo=token_obj.op_nominativo or "",
                anomalie_rows=anomalie_live,
                updates_summary=updates_summary,
                source_label=f"Risposta da mail ({token_obj.recipient_display})",
                exclude_emails=[g["email"] for g in piano_operatori if g.get("email")],
            )
    except Exception:
        logger.warning("mail_action: invio conferma aggiornamento fallito op=%s", token_obj.op_id, exc_info=True)
    try:
        if piano_operatori:
            from anomalie.automazioni_service import invia_decisioni_operatore
            invia_decisioni_operatore(
                token_obj.op_id, piano_operatori,
                deciso_da=token_obj.recipient_display or token_obj.recipient_email or "",
            )
    except Exception:
        logger.warning("mail_action: decisioni all'operatore non inviate op=%s", token_obj.op_id, exc_info=True)
    return redirect(reverse("anomalie_mail_action_done", kwargs={"token": token_obj.token}))


@risposta_pubblica
@require_http_methods(["GET"])
def mail_action_done_view(request: HttpRequest, token: str) -> HttpResponse:
    """Pagina di conferma dopo azione completata. Nessun login richiesto."""
    from .mail_action_models import AnomaliaActionLog, AnomaliaMailActionToken

    try:
        token_obj = AnomaliaMailActionToken.objects.get(token=token)
    except AnomaliaMailActionToken.DoesNotExist:
        return _render_error(request, "Token non trovato.", "invalid")

    logs = list(
        AnomaliaActionLog.objects.filter(token=token_obj).order_by("created_at")[:20]
    )
    return render(
        request,
        "anomalie/pages/mail_action_done.html",
        {
            "token": token_obj,
            "action_logs": logs,
            "already_done": False,
        },
    )


@risposta_pubblica
@require_http_methods(["GET"])
def mail_action_allegato_view(request: HttpRequest, token: str) -> HttpResponse:
    """Foto e allegati delle anomalie mostrate dalla pagina a token. Nessun login.

    La pagina raggiunta dalla mail mostrava le foto tramite
    ``/api/anomalie/allegati/file``, che richiede il login: chi apriva il link
    dalla mail senza sessione vedeva immagini rotte. Qui l'autorizzazione e' la
    stessa della pagina — il token, valido e non revocato — ristretta alle sole
    anomalie che quel token mostra: quelle salvate nel token o quelle dell'OP
    del token. Immagini e PDF inline, tutto il resto scaricato come allegato
    opaco (``core.download_security``).
    """
    from django.http import FileResponse, Http404

    from core.download_security import harden_file_response

    from .mail_action_models import AnomaliaMailActionToken
    from .views import _anomaly_local_row, _attachment_display_name, _resolve_anomalia_attachment_path

    token_obj = AnomaliaMailActionToken.objects.filter(token=token).first()
    if token_obj is None or token_obj.is_revoked or timezone.now() > token_obj.expires_at:
        raise Http404("Link non valido o scaduto.")

    local_id_raw = str(request.GET.get("local_id") or "").strip()
    file_id = str(request.GET.get("file_id") or "").strip()
    if not local_id_raw.isdigit() or not file_id:
        raise Http404("Allegato non trovato.")
    local_id = int(local_id_raw)
    if not _token_shows_anomalia(token_obj, local_id, _anomaly_local_row(local_id)):
        raise Http404("Allegato non trovato.")

    path = _resolve_anomalia_attachment_path(local_id, file_id)
    if not path:
        raise Http404("Allegato non trovato.")
    display_name = _attachment_display_name(path.name)
    try:
        log_action(
            request,
            "anomalia_allegato_open_mail_action",
            "anomalie",
            {
                "local_id": local_id,
                "op_id": token_obj.op_id,
                "file_id": file_id,
                "file_name": display_name,
                "token": str(token_obj.token)[:8],
                "recipient": token_obj.recipient_display,
            },
        )
    except Exception:
        pass
    # Mail salvate (.msg, .eml) e testi si scaricano, mai aperti nel browser.
    from .views import ESITI_SOLO_DOWNLOAD
    response = FileResponse(path.open("rb"), as_attachment=path.suffix.lower() in ESITI_SOLO_DOWNLOAD,
                            filename=display_name)
    return harden_file_response(response, display_name, inline=True)


def _token_shows_anomalia(token_obj, local_id: int, row: dict | None) -> bool:
    """L'anomalia e' fra quelle che la pagina del token mostra?

    Stesso perimetro di :func:`mail_action_view`: le anomalie salvate nel token
    oppure quelle dell'OP del token. Un token non apre gli allegati di altri OP.
    """
    if not row:
        return False
    for value in token_obj.anomalie_ids or []:
        try:
            if int(value) == local_id:
                return True
        except (TypeError, ValueError):
            continue
    op_token = str(token_obj.op_id or "").strip().lower()
    op_row = str(row.get("ex_op_nominativo") or "").strip().lower()
    return bool(op_token) and op_token == op_row


# ── Helpers ────────────────────────────────────────────────────────────────


def _render_error(request: HttpRequest, messaggio: str, codice: str) -> HttpResponse:
    return render(
        request,
        "anomalie/pages/mail_action_error.html",
        {"messaggio": messaggio, "codice": codice},
        status=400 if codice in ("invalid", "wrong_user", "forbidden", "already_used") else 410,
    )


_BASE_COLS = (
    "id, ex_op_nominativo, seriale, descrizione, note_capocommessa,"
    " avanzamento, pezzo_recuperato, aprire_rdc, segnalare_cliente, chiudere"
)


def _select_cols() -> str:
    """Colonne lette dalla tabella legacy; ``numero_rdc`` solo se esiste."""
    try:
        from core.legacy_utils import legacy_table_columns
        if "numero_rdc" in (legacy_table_columns("anomalie") or set()):
            return _BASE_COLS + ", numero_rdc"
    except Exception:
        pass
    return _BASE_COLS


def _load_anomalie_live(anomalie_ids: list, op_id: str) -> list[dict]:
    """Carica le righe anomalie live dalla tabella legacy SQL."""
    if not anomalie_ids:
        return []
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            placeholders = ",".join(["%s"] * len(anomalie_ids))
            cur.execute(
                f"SELECT {_select_cols()} FROM anomalie WHERE id IN ({placeholders}) ORDER BY id",
                anomalie_ids,
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        logger.exception("mail_action: impossibile caricare anomalie live ids=%s", anomalie_ids)
        return []


def _load_anomalie_live_by_op(op_id: str) -> list[dict]:
    """Carica tutte le anomalie aperte dell'OP dal DB (matching su ex_op_nominativo)."""
    if not op_id:
        return []
    try:
        from django.db import connections, connection as _conn
        op_expr = "LOWER(ex_op_nominativo)" if _conn.vendor == "sqlite" else "LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX)))"
        with connections["default"].cursor() as cur:
            cur.execute(
                f"SELECT {_select_cols()} FROM anomalie WHERE {op_expr} = LOWER(%s)"
                " AND (chiudere IS NULL OR chiudere = 0) ORDER BY id",
                [op_id],
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        logger.exception("mail_action: impossibile caricare anomalie per op_id=%s", op_id)
        return []


def _raggruppa(token_obj, anomalie_live: list[dict]) -> list[dict]:
    """Anomalie per blocco di seriali: prima i blocchi con le anomalie della mail
    («da decidere»), poi le altre anomalie aperte dell'OP."""
    if not anomalie_live:
        return []
    nuove = set()
    for value in token_obj.anomalie_ids or []:
        try:
            nuove.add(int(value))
        except (TypeError, ValueError):
            continue
    try:
        from anomalie.views import _list_attachments_for_local

        from .controllo_service import gruppi_per_blocco
        from .quality_models import AnomaliaDescrizione

        details: dict[int, list[dict]] = {}
        for detail in AnomaliaDescrizione.objects.filter(
            segnalazione__anomalia_id__in=[int(a["id"]) for a in anomalie_live if a.get("id")]
        ).select_related("segnalazione").prefetch_related("allegati").order_by("ordine", "id"):
            details.setdefault(detail.segnalazione.anomalia_id, []).append({
                "id": detail.pk,
                "seriali": detail.seriali if isinstance(detail.seriali, list) else [],
                "testo": detail.testo,
                "risposta": detail.risposta_capocommessa,
                "allegati": list(detail.allegati.values("id", "nome", "size")),
            })
        for anomaly in anomalie_live:
            anomaly_id = int(anomaly["id"])
            righe_descrizione = details.get(anomaly_id, [])
            # Le descrizioni multiple esistono solo per le righe della prima versione
            # del form; con una sola descrizione basta il testo dell'anomalia.
            anomaly["descrizioni"] = righe_descrizione if len(righe_descrizione) > 1 else []
            anomaly["nuova"] = anomaly_id in nuove
            try:
                allegati = _list_attachments_for_local(anomaly_id)
            except Exception:
                allegati = []
            anomaly["allegati"] = allegati
            anomaly["immagini"] = [a for a in allegati if a.get("is_image")][:4]
        gruppi = gruppi_per_blocco(anomalie_live)
    except Exception:
        logger.exception("mail_action: raggruppamento anomalie fallito op=%s", token_obj.op_id)
        for anomaly in anomalie_live:
            anomaly.setdefault("testo", anomaly.get("descrizione") or "")
            anomaly["nuova"] = int(anomaly["id"]) in nuove
        gruppi = [
            {"chiave": f"r{a['id']}", "titolo": a.get("seriale") or "", "sottotitolo": "", "righe": [a]}
            for a in anomalie_live
        ]
    _segna_decise_e_azioni(anomalie_live)
    from .segnalato_service import arricchisci_righe, nota_congelata
    arricchisci_righe(anomalie_live)
    for a in anomalie_live:
        a["nota_congelata"] = nota_congelata(a.get(_STATO_FIELD), a.get("note_capocommessa"))
    for gruppo in gruppi:
        gruppo["nuovo"] = any(r.get("nuova") for r in gruppo["righe"])
    gruppi.sort(key=lambda g: 0 if g["nuovo"] else 1)
    if any(g["nuovo"] for g in gruppi):
        primo_altro = next((g for g in gruppi if not g["nuovo"]), None)
        if primo_altro is not None:
            primo_altro["primo_altri"] = True
    return gruppi


def _load_first_images(anomalia_id: int) -> list[dict]:
    """Restituisce i metadati delle immagini della prima anomalia (max 3)."""
    try:
        from anomalie.views import _list_attachments_for_local
        all_att = _list_attachments_for_local(anomalia_id)
        images = [a for a in all_att if a.get("is_image")]
        return images[:3]
    except Exception:
        return []


def _apply_action_to_anomalia(
    *,
    anomalia_id: int,
    op_id: str,
    action: str,
    nuovo_avanzamento: str,
    note: str,
    aprire_rdc: bool | None = None,
    segnalare: bool | None = None,
    chiudere: bool | None = None,
    numero_rdc: str | None = None,
) -> bool:
    """Applica l'azione (update avanzamento / campi / flag) alla riga anomalia legacy."""
    try:
        from django.db import connections
        updates: dict[str, object] = {}
        if nuovo_avanzamento:
            updates["avanzamento"] = nuovo_avanzamento
        # Flag dai toggle del form (regole Power Apps risolte lato client)
        if aprire_rdc is not None:
            updates["aprire_rdc"] = 1 if aprire_rdc else 0
        if segnalare is not None:
            updates["segnalare_cliente"] = 1 if segnalare else 0
        # chiudere: dall'azione "chiudi" oppure dal flag automatico per-riga
        if action == "chiudi" or chiudere:
            updates["chiudere"] = 1
        # note=None: campo non toccato; stringa (anche vuota): risposta del capocommessa.
        if note is not None:
            updates["note_capocommessa"] = note
        if numero_rdc is not None:
            from core.legacy_utils import legacy_table_columns
            if "numero_rdc" in (legacy_table_columns("anomalie") or set()):
                updates["numero_rdc"] = numero_rdc

        if not updates:
            return True

        set_clause = ", ".join([f"{k} = %s" for k in updates])
        values = list(updates.values()) + [anomalia_id]
        with connections["default"].cursor() as cur:
            cur.execute(
                f"UPDATE anomalie SET {set_clause} WHERE id = %s",
                values,
            )
        return True
    except Exception:
        logger.exception(
            "mail_action: impossibile aggiornare anomalia id=%s op=%s action=%s",
            anomalia_id,
            op_id,
            action,
        )
        return False


def _write_action_log(
    *,
    request: HttpRequest,
    token_obj,
    anomalie: list[dict],
    action: str,
    note: str,
    previous_status: str,
    new_status: str,
    source: str,
) -> None:
    from .mail_action_models import AnomaliaActionLog

    # Senza login: usa il nome del destinatario dal token come user_display
    user_display = token_obj.recipient_display or token_obj.recipient_email or "anonimo"

    for anomalia in anomalie:
        anomalia_id = anomalia.get("id")
        if not anomalia_id:
            continue
        AnomaliaActionLog.objects.create(
            anomalia_id=anomalia_id,
            op_id=token_obj.op_id,
            user=request.user if request.user.is_authenticated else None,
            legacy_user_id=token_obj.recipient_legacy_user_id,
            user_display=user_display,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            note=note,
            source=source,
            token=token_obj,
            ip_address=_get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )


def _action_label(action: str) -> str:
    labels = {
        "prendi_in_carico": "Prendi in carico",
        "approva": "Approva",
        "respingi": "Respingi",
        "richiedi_modifica": "Richiedi modifica",
        "chiudi": "Chiudi",
        "visualizza": "Visualizza",
        "aggiorna_avanzamento": "Aggiorna avanzamento",
    }
    return labels.get(action, action.replace("_", " ").title())


def _get_ip(request: HttpRequest) -> str | None:
    from core.audit import _get_client_ip
    return _get_client_ip(request)
