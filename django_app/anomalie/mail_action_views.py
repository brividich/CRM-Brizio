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
from core.public_headers import risposta_pubblica

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


@risposta_pubblica
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
    results = []
    if is_dispositive:
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
            if toccata:
                riga_note = str(per_riga.get("note") or "").strip()[:2000]
                if not riga_note and note and action in _NOTE_GLOBALE_ACTIONS:
                    riga_note = note
                riga_aprire_rdc = bool(per_riga.get("aprire_rdc"))
                riga_segnalare = bool(per_riga.get("segnalare"))
                riga_chiudere = bool(per_riga.get("chiudere"))
                riga_numero_rdc = str(per_riga.get("numero_rdc") or "").strip()[:100]
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
        token_obj.mark_used(
            ip_address=_get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
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
                send_anomalie_update_confirmation(
                    op_id=token_obj.op_id,
                    op_nominativo=token_obj.op_nominativo or "",
                    anomalie_rows=anomalie_live,
                    updates_summary=updates_summary,
                    source_label=f"Risposta da mail ({token_obj.recipient_display})",
                )
        except Exception:
            logger.warning("mail_action: invio conferma aggiornamento fallito op=%s", token_obj.op_id, exc_info=True)
    else:
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
