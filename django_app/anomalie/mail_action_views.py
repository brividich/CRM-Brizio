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

logger = logging.getLogger(__name__)

# Azioni che modificano lo stato: monouso.
_DISPOSITIVE_ACTIONS = {"prendi_in_carico", "approva", "respingi", "richiedi_modifica", "chiudi", "aggiorna_avanzamento"}
_STATO_FIELD = "avanzamento"

# Mapping azione → valore da scrivere nel campo avanzamento (tabella legacy)
# aggiorna_avanzamento non ha default: il valore arriva sempre per-riga dal form.
_ACTION_TO_AVANZAMENTO = {
    "prendi_in_carico": "In attesa",
    "approva": "Accetto lo stato",
    "chiudi": "Finito trattato",
}


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

    first_images = []
    if anomalie_live:
        first_images = _load_first_images(anomalie_live[0]["id"])

    if request.method == "POST":
        return _handle_post(request, token_obj, anomalie_live)

    return render(
        request,
        "anomalie/pages/mail_action_form.html",
        {
            "token": token_obj,
            "anomalie": anomalie_live,
            "first_images": first_images,
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
            # Per-riga: usa il valore salvato individualmente se presente, altrimenti il default
            per_riga = aggiornamenti_per_id.get(str(anomalia_id), {})
            riga_avanzamento = (per_riga.get("avanzamento") or "").strip() or default_avanzamento
            riga_note = (per_riga.get("note") or "").strip() or note
            prev = anomalia.get(_STATO_FIELD) or ""
            ok = _apply_action_to_anomalia(
                anomalia_id=anomalia_id,
                op_id=token_obj.op_id,
                action=action,
                nuovo_avanzamento=riga_avanzamento,
                note=riga_note,
            )
            results.append({
                "id": anomalia_id,
                "ok": ok,
                "prev": prev,
                "new": riga_avanzamento if ok else prev,
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


def _load_anomalie_live(anomalie_ids: list, op_id: str) -> list[dict]:
    """Carica le righe anomalie live dalla tabella legacy SQL."""
    if not anomalie_ids:
        return []
    try:
        from django.db import connections
        with connections["default"].cursor() as cur:
            placeholders = ",".join(["%s"] * len(anomalie_ids))
            cur.execute(
                f"SELECT id, ex_op_nominativo, seriale, descrizione, note_capocommessa,"
                f" avanzamento, pezzo_recuperato, aprire_rdc, segnalare_cliente, chiudere"
                f" FROM anomalie WHERE id IN ({placeholders}) ORDER BY id",
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
        with connections["default"].cursor() as cur:
            if _conn.vendor == "sqlite":
                cur.execute(
                    "SELECT id, ex_op_nominativo, seriale, descrizione, note_capocommessa,"
                    " avanzamento, pezzo_recuperato, aprire_rdc, segnalare_cliente, chiudere"
                    " FROM anomalie WHERE LOWER(ex_op_nominativo) = LOWER(%s)"
                    " AND (chiudere IS NULL OR chiudere = 0) ORDER BY id",
                    [op_id],
                )
            else:
                cur.execute(
                    "SELECT id, ex_op_nominativo, seriale, descrizione, note_capocommessa,"
                    " avanzamento, pezzo_recuperato, aprire_rdc, segnalare_cliente, chiudere"
                    " FROM anomalie WHERE LOWER(CAST(ex_op_nominativo AS NVARCHAR(MAX))) = LOWER(%s)"
                    " AND (chiudere IS NULL OR chiudere = 0) ORDER BY id",
                    [op_id],
                )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        logger.exception("mail_action: impossibile caricare anomalie per op_id=%s", op_id)
        return []


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
) -> bool:
    """Applica l'azione (update avanzamento / campi) alla riga anomalia legacy."""
    try:
        from django.db import connections
        updates: dict[str, object] = {}
        if nuovo_avanzamento:
            updates["avanzamento"] = nuovo_avanzamento
        if action == "chiudi":
            updates["chiudere"] = True
        if action in ("approva", "respingi", "richiedi_modifica") and note:
            updates["note_capocommessa"] = note

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
