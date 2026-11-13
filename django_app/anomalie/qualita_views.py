"""API della decisione qualità e delle richieste di informazioni.

- ``POST /api/anomalie/qualita/salva``: numero RDC, avanzamento e note qualità,
  «Segnalato» se il capocommessa non l'ha fatto, risposta del destinatario,
  «Chiudi»; poi la regola unica di chiusura.
- ``POST /api/anomalie/qualita/richiedi-info``: chiarimenti al capocommessa e/o al
  controllore (notifica + mail con link di risposta).
- ``POST /api/anomalie/qualita/rispondi-info``: risposta di capocommessa o controllore.

Decide la qualità chi è nella lista «Referenti RDC / segnalazione cliente» di
Configurazione (o l'amministratore del modulo). Errori sempre in JSON.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connections, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.legacy_utils import get_legacy_user, legacy_table_columns

from . import decisione_qualita as dq
from . import segnalato_service as segn

logger = logging.getLogger(__name__)


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": msg}, status=status)


def puo_decisione_qualita(request) -> bool:
    from core.acl import user_can_modulo_action

    from .views import _is_referente_rdc

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_superuser", False):
        return True
    try:
        if user_can_modulo_action(request, "anomalie", "admin_anomalie"):
            return True
    except Exception:
        pass
    return _is_referente_rdc(request)


def _json(request) -> dict:
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _riga(local_id: int) -> dict | None:
    from .views import _fetch_all_dict

    cols = legacy_table_columns("anomalie") or set()
    voluti = ("id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "aprire_rdc", "numero_rdc",
              "segnalare_cliente", "chiudere", "avanzamento", "created_by_user_id", "pezzo_recuperato")
    sel = ", ".join(c for c in voluti if c in cols)
    rows = _fetch_all_dict(f"SELECT TOP 1 {sel} FROM anomalie WHERE id = %s", [local_id])
    return rows[0] if rows else None


def _chi(request) -> str:
    from .views import _current_user_identity, _safe_text

    identity = _current_user_identity(request)
    return _safe_text(identity.get("name") or request.user.get_full_name() or request.user.username, 200) or ""


def _timeline(request, local_id, op_id, action, *, note="", prev="", new="", modifiche=None):
    try:
        from .mail_action_service import log_anomalia_portal_action
        from .views import _client_ip

        legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        log_anomalia_portal_action(
            anomalia_id=local_id, op_id=op_id, action=action, user=request.user,
            legacy_user_id=int(legacy.id) if legacy else None, user_display=_chi(request),
            previous_status=prev, new_status=new, note=note[:500],
            payload={"modifiche": modifiche} if modifiche else None,
            ip_address=_client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except Exception:
        logger.warning("qualità: cronologia non scritta id=%s", local_id, exc_info=True)


def _aggiorna_legacy(request, local_id: int, valori: dict) -> None:
    cols = legacy_table_columns("anomalie") or set()
    sets, params = [], []
    for k, v in valori.items():
        if k in cols:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return
    if "modified_datetime" in cols:
        sets.append("modified_datetime = SYSUTCDATETIME()")
    legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if "modified_by_user_id" in cols and legacy:
        sets.append("modified_by_user_id = %s")
        params.append(legacy.id)
    with connections["default"].cursor() as cur:
        cur.execute(f"UPDATE anomalie SET {', '.join(sets)} WHERE id = %s", params + [local_id])


@login_required
@require_POST
def api_qualita_salva(request):
    from .qualita_service import get_or_create_scheda, sync_da_anomalia
    from .quality_models import AnomaliaSchedaQualita
    from .views import _notify_anomalia_event, _safe_text, _serve_azione_per_chiudere, chiusura_automatica

    data = _json(request)
    try:
        local_id = int(str(data.get("local_id") or "").split(":")[-1])
    except ValueError:
        return _err("local_id non valido")
    from .incaricati import incaricato_qualita

    if not (puo_decisione_qualita(request) or incaricato_qualita(request, local_id)):
        return _err("Permesso negato: la decisione qualità la prendono i referenti qualità", 403)
    row = _riga(local_id)
    if row is None:
        return _err("Anomalia non trovata", 404)
    if row.get("chiudere"):
        return _err("L'anomalia è chiusa: riaprila per cambiare la decisione qualità")
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    av_qualita = _safe_text(data.get("avanzamento_qualita"), 100) or ""
    if av_qualita and av_qualita.lower() not in {v.lower() for v in dq.avanzamenti_qualita()}:
        return _err("Avanzamento qualità non previsto in Configurazione")
    chiudi = bool(data.get("chiudi"))
    if chiudi and not row.get("aprire_rdc") and _serve_azione_per_chiudere(local_id):
        from .tempi_service import MSG_SERVE_AZIONE
        return _err(MSG_SERVE_AZIONE)

    chi = _chi(request)
    stato = segn.stato_segnalati(local_id)
    prima_q = AnomaliaSchedaQualita.objects.filter(anomalia_id=local_id).values("avanzamento_qualita", "note_qualita").first() or {}
    richiesti = {"cliente": bool(row.get("segnalare_cliente")), "terzista": stato["segnala_terzista"]}
    avanzamento = str(row.get("avanzamento") or "").strip()
    legacy_valori: dict = {}
    numero = str(row.get("numero_rdc") or "")
    if row.get("aprire_rdc") and "numero_rdc" in data:
        numero = _safe_text(data.get("numero_rdc"), 100) or ""
        legacy_valori["numero_rdc"] = numero
    try:
        with transaction.atomic():
            scheda, _ = get_or_create_scheda(local_id, row=row)
            if scheda is None:
                return _err("Scheda dell'anomalia non disponibile", 500)
            AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(
                avanzamento_qualita=av_qualita, note_qualita=(_safe_text(data.get("note_qualita")) or ""),
                qualita_il=timezone.now(), qualita_da=chi, updated_at=timezone.now(),
            )
            for d in segn.DESTINATARI:
                if richiesti[d] and f"segnalato_{d}" in data:
                    acceso = bool(data.get(f"segnalato_{d}"))
                    if acceso != stato[d] and segn.registra_segnalato(local_id, d, acceso, chi, ruolo="qualita"):
                        stato[d] = acceso
                        _timeline(request, local_id, op_id, "segnalato",
                                  note=(f"Segnalato {'al cliente' if d == 'cliente' else 'al terzista'} (qualità)"
                                        if acceso else f"Tolta la spunta «Segnalato» ({d})"))
                testo = _safe_text(data.get(f"risposta_{d}"), 4000) or ""
                if richiesti[d] and testo and segn.registra_risposta(local_id, d, testo, user=request.user,
                                                                     utente_display=chi):
                    _timeline(request, local_id, op_id, f"risposta_{d}", note=testo)
                    # Risposta registrata dalla qualità: l'attesa finisce.
                    if avanzamento.lower() == segn.AVANZAMENTO_RISPOSTA[d].lower():
                        avanzamento = "In attesa"
                        legacy_valori["avanzamento"] = avanzamento
            info = dq.info_per_anomalie([local_id]).get(local_id, {})
            regola = chiusura_automatica(
                bool(row.get("aprire_rdc")), numero, richiesti["cliente"], stato["cliente"], avanzamento,
                richiesti["terzista"], stato["terzista"], cc_chiude=dq.cc_puo_chiudere(),
                chiarimenti=bool(info.get("richiesta_aperta")),
            )
            if regola and not row.get("aprire_rdc") and _serve_azione_per_chiudere(local_id):
                regola = False
            chiusa = chiudi or regola
            if chiusa:
                legacy_valori["chiudere"] = 1
            _aggiorna_legacy(request, local_id, legacy_valori)
    except DatabaseError as exc:
        return _err(f"Salvataggio non riuscito: {exc}", 500)

    modifiche = []
    if (prima_q.get("avanzamento_qualita") or "") != av_qualita:
        modifiche.append(["Avanzamento qualità", prima_q.get("avanzamento_qualita") or "nessuno stato", av_qualita or "nessuno stato"])
    nota_q = (_safe_text(data.get("note_qualita")) or "")
    if (prima_q.get("note_qualita") or "") != nota_q:
        modifiche.append(["Note della qualità", (prima_q.get("note_qualita") or "")[:300], nota_q[:300]])
    if "numero_rdc" in legacy_valori and legacy_valori["numero_rdc"] != str(row.get("numero_rdc") or ""):
        modifiche.append(["N° RDC", str(row.get("numero_rdc") or ""), legacy_valori["numero_rdc"]])
    if chiusa:
        modifiche.append(["Chiusa", "no", "sì"])
    _timeline(request, local_id, op_id, "chiudi" if chiusa else "qualita",
              note=" · ".join(x for x in (av_qualita, (data.get("note_qualita") or "")[:300]) if x),
              prev=avanzamento or "In attesa", new="Chiusa" if chiusa else (av_qualita or "Decisione qualità"),
              modifiche=modifiche)
    try:
        log_action(request, "anomalia_decisione_qualita", "anomalie",
                   {"local_id": local_id, "op_id": op_id, "avanzamento_qualita": av_qualita, "chiusa": chiusa})
    except Exception:
        pass
    try:
        with transaction.atomic():
            sync_da_anomalia(local_id)
    except Exception:
        logger.warning("qualità: scheda/tempi non aggiornati id=%s", local_id, exc_info=True)
    if chiusa:
        _notify_anomalia_event(request, "chiudere", local_id, op_id, str(row.get("seriale") or ""))
    _accoda_riepilogo(request, row, local_id, op_id, chiusa=chiusa, numero=numero, av_qualita=av_qualita,
                      note_qualita=data.get("note_qualita") or "", avanzamento=avanzamento)
    return JsonResponse({"success": True, "chiusa": chiusa, "numero_rdc": numero, "avanzamento": avanzamento})


def _accoda_riepilogo(request, row, local_id, op_id, *, chiusa, numero, av_qualita, note_qualita, avanzamento):
    """La decisione qualità entra nel riepilogo delle modifiche dell'OP."""
    try:
        from .mail_action_service import register_pending_update
        from .views import _extra_decisione_per_mail

        chi = _chi(request)
        legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        register_pending_update(op_id=op_id, op_nominativo=op_id, modified_by=chi, update_row={
            "id": local_id, "seriale": str(row.get("seriale") or ""), "avanzamento": avanzamento,
            "descrizione": str(row.get("descrizione") or ""), "numero_rdc": numero,
            "note": str(row.get("note_capocommessa") or ""), "aprire_rdc": bool(row.get("aprire_rdc")),
            "segnalare": bool(row.get("segnalare_cliente")), "chiudere": bool(chiusa),
            **_extra_decisione_per_mail(local_id, {"segnalare": row.get("segnalare_cliente")}),
            "avanzamento_qualita": av_qualita, "note_qualita": str(note_qualita or "")[:2000], "qualita_da": chi,
            "modified_by": chi, "modified_by_legacy_id": int(legacy.id) if legacy else None,
        })
    except Exception:
        logger.warning("qualità: riepilogo non accodato op=%s", op_id, exc_info=True)


@login_required
@require_POST
def api_qualita_richiedi_info(request):
    from .qualita_mail import invia_richiesta_info
    from .qualita_service import get_or_create_scheda
    from .quality_models import AnomaliaRichiestaInfo, AnomaliaSchedaQualita
    from .views import _safe_text

    if not puo_decisione_qualita(request):
        return _err("Permesso negato: le informazioni le chiede la qualità", 403)
    data = _json(request)
    try:
        local_id = int(str(data.get("local_id") or "").split(":")[-1])
    except ValueError:
        return _err("local_id non valido")
    destinatari = [d for d in ("cc", "controllore") if d in (data.get("destinatari") or [])]
    messaggio = _safe_text(data.get("messaggio"), 4000) or ""
    if not destinatari:
        return _err("Scegli a chi chiedere: capocommessa e/o controllore")
    if not messaggio:
        return _err("Scrivi cosa ti serve sapere")
    row = _riga(local_id)
    if row is None:
        return _err("Anomalia non trovata", 404)
    if row.get("chiudere"):
        return _err("L'anomalia è chiusa")
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    chi = _chi(request)
    with transaction.atomic():
        richiesta = AnomaliaRichiestaInfo.objects.create(
            anomalia_id=local_id, destinatari=destinatari, messaggio=messaggio,
            richiesta_da=request.user, richiesta_da_display=chi,
        )
        scheda, _ = get_or_create_scheda(local_id, row=row)
        if scheda is not None:
            AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(
                avanzamento_qualita=dq.AVANZAMENTO_CHIARIMENTI, qualita_il=timezone.now(), qualita_da=chi,
                updated_at=timezone.now())
    a_chi = " e ".join("capocommessa" if d == "cc" else "controllore" for d in destinatari)
    _timeline(request, local_id, op_id, "richiesta_info", note=f"A {a_chi}: {messaggio}",
              new=dq.AVANZAMENTO_CHIARIMENTI)
    try:
        log_action(request, "anomalia_richiesta_info", "anomalie",
                   {"local_id": local_id, "op_id": op_id, "destinatari": destinatari})
    except Exception:
        pass
    esito = {}
    try:
        esito = invia_richiesta_info(richiesta=richiesta, op_id=op_id, seriale=str(row.get("seriale") or ""),
                                     descrizione=str(row.get("descrizione") or ""))
    except Exception:
        logger.warning("richiesta info: invio fallito id=%s", local_id, exc_info=True)
    return JsonResponse({"success": True, "richieste": dq.richieste_payload(local_id), "invio": esito,
                         "avanzamento_qualita": dq.AVANZAMENTO_CHIARIMENTI})


def ruoli_risposta(request, row: dict) -> list[str]:
    """Ruoli con cui chi guarda può rispondere: capocommessa (modifica l'OP) e/o controllore (autore)."""
    from .views import _can_edit_anomalie_for_op, _request_legacy_user_id

    ruoli = []
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    if _can_edit_anomalie_for_op(request, op_id):
        ruoli.append("cc")
    me = _request_legacy_user_id(request)
    try:
        if me is not None and int(row.get("created_by_user_id") or 0) == int(me):
            ruoli.append("controllore")
    except (TypeError, ValueError):
        pass
    # Incaricato del ruolo su questa anomalia (incaricati.py).
    if me is not None and row.get("id") is not None:
        from .incaricati import per_anomalie

        for ruolo, v in (per_anomalie([row["id"]]).get(int(row["id"])) or {}).items():
            if ruolo in ("cc", "controllore") and v["id"] == int(me) and ruolo not in ruoli:
                ruoli.append(ruolo)
    return ruoli


@login_required
@require_POST
def api_qualita_rispondi_info(request):
    from .qualita_mail import invia_risposta_info
    from .views import _safe_text

    data = _json(request)
    try:
        local_id = int(str(data.get("local_id") or "").split(":")[-1])
    except ValueError:
        return _err("local_id non valido")
    testo = _safe_text(data.get("testo"), 4000) or ""
    if not testo:
        return _err("Scrivi la risposta")
    row = _riga(local_id)
    if row is None:
        return _err("Anomalia non trovata", 404)
    ruoli = ruoli_risposta(request, row)
    if not ruoli:
        return _err("Permesso negato: rispondono il capocommessa o il controllore", 403)
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    chi = _chi(request)
    chiuse = []
    for ruolo in ruoli:
        chiuse += dq.registra_risposta_info(local_id, testo, ruolo=ruolo, chi=chi)
    if not chiuse:
        return _err("Nessuna richiesta aperta per te su questa anomalia")
    _timeline(request, local_id, op_id, "risposta_info", note=testo, new="Torna alla qualità")
    for r in {r.pk: r for r in chiuse}.values():
        try:
            invia_risposta_info(richiesta=r, op_id=op_id, seriale=str(row.get("seriale") or ""))
        except Exception:
            logger.warning("risposta info: avviso fallito id=%s", local_id, exc_info=True)
    return JsonResponse({"success": True, "richieste": dq.richieste_payload(local_id)})
