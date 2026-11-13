"""Mail e notifiche della decisione qualità: richiesta di informazioni e risposta.

La richiesta va al capocommessa e/o al controllore (email di notifica
dell'anagrafica) con un link monouso per rispondere senza login
(``/gestione-anomalie/mail-action/<token>/``, azione ``rispondi_info``); la
risposta torna a chi l'ha chiesta. Mai bloccanti.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from .codice import codice_anomalia  # noqa: E402

logger = logging.getLogger(__name__)

AZIONE_RISPONDI = "rispondi_info"
TOKEN_ORE = 24 * 14


def _destinatari_legacy(anomalia_id: int, op_id: str, destinatari: list[str]) -> list[tuple[str, object]]:
    """``[(ruolo, utente_legacy)]`` di capocommessa dell'OP e controllore (autore)."""
    from .automazioni_service import _fetch
    from .mail_action_service import find_legacy_user_by_name
    from .views import _row_capocommessa

    from .incaricati import per_anomalie

    out = []
    incaricati = per_anomalie([anomalia_id]).get(int(anomalia_id)) or {}
    for ruolo in ("cc", "controllore"):
        if ruolo in destinatari and ruolo in incaricati:
            # Ruolo affidato a una persona: la richiesta va a lei, non a chi lo ha di serie.
            try:
                from core.legacy_models import UtenteLegacy

                utente = UtenteLegacy.objects.filter(pk=incaricati[ruolo]["id"]).first()
                if utente is not None and all(u.pk != utente.pk for _r, u in out):
                    out.append((ruolo, utente))
            except Exception:
                logger.warning("richiesta info: incaricato %s non trovato id=%s", ruolo, anomalia_id, exc_info=True)
            destinatari = [d for d in destinatari if d != ruolo]
    if "cc" in destinatari:
        try:
            rows = _fetch("SELECT capocomessa FROM ordini_produzione WHERE title = %s", [op_id])
            capo = str(_row_capocommessa(rows[0]) or "").strip() if rows else ""
            utente = find_legacy_user_by_name(capo) if capo else None
            if utente is not None:
                out.append(("cc", utente))
        except Exception:
            logger.warning("richiesta info: capocommessa non trovato op=%s", op_id, exc_info=True)
    if "controllore" in destinatari:
        try:
            from core.legacy_models import UtenteLegacy

            rows = _fetch("SELECT created_by_user_id FROM anomalie WHERE id = %s", [anomalia_id])
            uid = rows[0].get("created_by_user_id") if rows else None
            utente = UtenteLegacy.objects.filter(pk=int(uid)).first() if uid else None
            if utente is not None and all(u.pk != utente.pk for _r, u in out):
                out.append(("controllore", utente))
        except Exception:
            logger.warning("richiesta info: controllore non trovato id=%s", anomalia_id, exc_info=True)
    return out


def invia_richiesta_info(*, richiesta, op_id: str, seriale: str, descrizione: str) -> dict:
    """Notifica nel portale e mail con il link per rispondere a ogni destinatario."""
    from core.models import Notifica

    from .automazioni_service import _render_mail, _send, contatto_operatore, op_portal_link, op_url
    from .mail_action_models import AnomaliaMailActionToken

    esito = {"inviate": 0, "notificati": 0, "senza_email": []}
    chi = richiesta.richiesta_da_display or "La qualità"
    codice = codice_anomalia(richiesta.anomalia_id)
    for ruolo, utente in _destinatari_legacy(richiesta.anomalia_id, op_id, richiesta.destinatari or []):
        try:
            Notifica.objects.create(
                legacy_user_id=utente.pk, tipo="anomalia_da_gestire",
                messaggio=f"OP {op_id}, {codice} (S/N {seriale or '—'}): {chi} chiede informazioni sulla segnalazione."[:500],
                url_azione=op_url(op_id),
            )
            esito["notificati"] += 1
        except Exception:
            logger.warning("richiesta info: notifica fallita uid=%s", utente.pk, exc_info=True)
        email, nome = contatto_operatore(utente.pk)
        if not email:
            esito["senza_email"].append(getattr(utente, "nome", "") or str(utente.pk))
            continue
        link = ""
        try:
            from core.accounts.portal_links import portal_link

            token = AnomaliaMailActionToken.objects.create(
                recipient_legacy_user_id=utente.pk, recipient_email=email, recipient_display=nome or email,
                op_id=op_id, op_nominativo=op_id, anomalie_ids=[richiesta.anomalia_id], anomalie_snapshot=[],
                action=AZIONE_RISPONDI, expires_at=timezone.now() + timedelta(hours=TOKEN_ORE),
            )
            link = portal_link(f"/gestione-anomalie/mail-action/{token.token}/")
        except Exception:
            logger.warning("richiesta info: link di risposta non creato", exc_info=True)
        portale = op_portal_link(op_id)
        ruolo_txt = "capocommessa" if ruolo == "cc" else "controllore"
        subject = f"[Novicrom Hub] OP {op_id} — la qualità chiede informazioni su {codice} (S/N {seriale or '—'})"
        lines = [f"{chi} chiede informazioni aggiuntive sulla segnalazione (sei il {ruolo_txt}).", "",
                 f"  • {codice} · OP {op_id} · S/N {seriale or '—'}", f"      {(descrizione or '—')[:200]}", "",
                 "Richiesta:", f"  {richiesta.messaggio}", ""]
        if link:
            lines.append(f"Rispondi qui (senza accesso): {link}")
        if portale:
            lines.append(f"Oppure in Gestione anomalie: {portale}")
        html = _render_mail(
            badge="Richiesta informazioni", eyebrow=f"OP {op_id}",
            title="La qualità chiede informazioni sulla segnalazione",
            intro=f"{'Buongiorno ' + nome + ', ' if nome else ''}{chi} chiede informazioni aggiuntive: "
                  f"«{richiesta.messaggio[:500]}»",
            columns=["ID", "S/N", "Anomalia"], rows=[[codice, seriale or "—", (descrizione or "—")[:200]]],
            cta_url=link or portale, cta_label="Rispondi",
        )
        if _send(kind="richiesta_info", subject=subject, lines=lines, html=html, to=[email], op_id=op_id,
                 context={"anomalia_id": richiesta.anomalia_id, "richiesta": richiesta.pk, "ruolo": ruolo}):
            esito["inviate"] += 1
    return esito


def invia_risposta_info(*, richiesta, op_id: str, seriale: str) -> None:
    """Avvisa chi ha chiesto le informazioni che è arrivata la risposta."""
    from core.models import Notifica

    from .automazioni_service import _render_mail, _send, contatto_operatore, op_portal_link, op_url

    utente_dj = richiesta.richiesta_da
    if utente_dj is None:
        return
    try:
        from core.legacy_utils import get_legacy_user

        legacy = get_legacy_user(utente_dj)
    except Exception:
        legacy = None
    if legacy is None:
        return
    chi = richiesta.risposta_da_display or "Il capocommessa"
    codice = codice_anomalia(richiesta.anomalia_id)
    try:
        Notifica.objects.create(
            legacy_user_id=legacy.pk, tipo="anomalia_da_gestire",
            messaggio=f"OP {op_id}, {codice} (S/N {seriale or '—'}): {chi} ha risposto alla tua richiesta di informazioni."[:500],
            url_azione=op_url(op_id),
        )
    except Exception:
        logger.warning("risposta info: notifica fallita", exc_info=True)
    email, nome = contatto_operatore(legacy.pk)
    if not email:
        return
    portale = op_portal_link(op_id)
    lines = [f"{chi} ha risposto alla tua richiesta di informazioni.", "",
             f"  • {codice} · OP {op_id} · S/N {seriale or '—'}", "", "Richiesta:", f"  {richiesta.messaggio}", "",
             "Risposta:", f"  {richiesta.risposta}", ""]
    if portale:
        lines.append(f"Gestione anomalie: {portale}")
    html = _render_mail(
        badge="Risposta ricevuta", eyebrow=f"OP {op_id}", title="Risposta alla richiesta di informazioni",
        intro=f"{'Buongiorno ' + nome + ', ' if nome else ''}{chi} ha risposto: «{richiesta.risposta[:800]}»",
        columns=["ID", "S/N", "Richiesta"], rows=[[codice, seriale or "—", richiesta.messaggio[:300]]],
        cta_url=portale, cta_label="Apri in Gestione anomalie",
    )
    _send(kind="risposta_info", subject=f"[Novicrom Hub] OP {op_id} — risposta su {codice}",
          lines=lines, html=html, to=[email], op_id=op_id,
          context={"anomalia_id": richiesta.anomalia_id, "richiesta": richiesta.pk})
