"""«Segnalato» e «Risposta» di cliente e terzista: regole comuni a pagina e link mail.

Flusso della decisione con «Segnalare al cliente» / «Segnala a terzista»:

1. la spunta «Segnalare…» chiede la segnalazione: l'anomalia resta aperta;
2. «Segnalato…» (capocommessa o qualità) registra che il destinatario è stato
   avvisato: senza RDC l'anomalia si chiude (``views.chiusura_automatica``);
3. per aspettare la risposta si sceglie «In attesa risposta cliente» / «In attesa
   risposta terzista»: la nota già scritta resta congelata, la risposta si scrive
   in un campo suo (``AnomaliaEsito``) da chi ha fatto la segnalazione, poi si
   sceglie lo stato definitivo.

Nessuna dipendenza dalle view: le usano ``views`` e ``mail_action_views``.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

AVANZAMENTO_RISPOSTA_CLIENTE = "In attesa risposta cliente"
AVANZAMENTO_RISPOSTA_TERZISTA = "In attesa risposta terzista"
AVANZAMENTO_RISPOSTA = {"cliente": AVANZAMENTO_RISPOSTA_CLIENTE, "terzista": AVANZAMENTO_RISPOSTA_TERZISTA}
STATI_RISPOSTA = {v.lower() for v in AVANZAMENTO_RISPOSTA.values()}
DESTINATARI = ("cliente", "terzista")
_STATI_LIBERI = {"", "in attesa"}


def tipo_risposta(chi: str) -> str:
    from .quality_models import AnomaliaEsito

    return AnomaliaEsito.Tipo.RISPOSTA_CLIENTE if chi == "cliente" else AnomaliaEsito.Tipo.RISPOSTA_TERZISTA


def stato_segnalati(anomalia_id) -> dict:
    """``{"cliente": bool, "terzista": bool, "segnala_terzista": bool}`` dalla scheda qualità."""
    out = {"cliente": False, "terzista": False, "segnala_terzista": False}
    if not anomalia_id:
        return out
    try:
        from .quality_models import AnomaliaSchedaQualita

        riga = AnomaliaSchedaQualita.objects.filter(anomalia_id=int(anomalia_id)).values(
            "segnalato_cliente_il", "segnalato_terzista_il", "segnala_terzista",
        ).first()
    except Exception:
        logger.warning("anomalie: lettura «Segnalato» fallita id=%s", anomalia_id, exc_info=True)
        return out
    if riga:
        out["cliente"] = riga["segnalato_cliente_il"] is not None
        out["terzista"] = riga["segnalato_terzista_il"] is not None
        out["segnala_terzista"] = bool(riga["segnala_terzista"])
    return out


def nota_congelata(avanzamento_salvato: str, nota_salvata: str) -> bool:
    """In attesa di risposta la nota già scritta (quella mandata al destinatario) non si modifica."""
    return str(avanzamento_salvato or "").strip().lower() in STATI_RISPOSTA and bool(str(nota_salvata or "").strip())


def registra_segnalato(anomalia_id: int, chi: str, acceso: bool, chi_utente: str, *, ruolo: str = "cc") -> bool:
    """Scrive «Segnalato al cliente/terzista» sulla scheda. Ritorna True se è cambiato.

    Una spunta già registrata non si riscrive: data, autore e ruolo («cc» o
    «qualita») restano i primi.
    """
    if chi not in DESTINATARI:
        return False
    from .qualita_service import get_or_create_scheda
    from .quality_models import AnomaliaSchedaQualita

    scheda, _ = get_or_create_scheda(int(anomalia_id))
    if scheda is None:
        return False
    campo_il, campo_da = f"segnalato_{chi}_il", f"segnalato_{chi}_da"
    gia = getattr(scheda, campo_il) is not None
    if gia == bool(acceso):
        return False
    valori = {campo_il: timezone.now() if acceso else None, campo_da: (chi_utente or "")[:200] if acceso else "",
              f"segnalato_{chi}_ruolo": (ruolo or "")[:16] if acceso else ""}
    AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(**valori, updated_at=timezone.now())
    return True


def registra_risposta(anomalia_id: int, chi: str, testo: str, *, user=None, utente_display: str = ""):
    """Risposta del cliente o del terzista come esito dell'anomalia (tempi e storico)."""
    testo = str(testo or "").strip()[:4000]
    if chi not in DESTINATARI or not testo:
        return None
    from .qualita_service import get_or_create_scheda
    from .quality_models import AnomaliaEsito, AnomaliaSchedaQualita

    esito = AnomaliaEsito.objects.create(
        anomalia_id=int(anomalia_id), tipo=tipo_risposta(chi), testo=testo,
        utente=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
        utente_display=(utente_display or "")[:200],
    )
    if chi == "cliente":
        scheda, _ = get_or_create_scheda(int(anomalia_id))
        if scheda is not None and scheda.risposta_cliente_il is None:
            AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(risposta_cliente_il=esito.created_at)
    return esito


def _payload_segnalato(il, da) -> dict | None:
    if not il:
        return None
    return {"il": timezone.localtime(il).strftime("%d/%m/%Y %H:%M"), "da": da or ""}


def arricchisci_righe(righe: list[dict], *, chiave_id: str = "id") -> None:
    """Aggiunge a ogni riga ``segnala_terzista``, ``segnalato_cliente``,
    ``segnalato_terzista`` (``None`` o ``{"il","da"}``) e ``risposte`` (ultime prima)."""
    ids = []
    for r in righe:
        r.setdefault("segnala_terzista", False)
        r.setdefault("segnalato_cliente", None)
        r.setdefault("segnalato_terzista", None)
        r["risposte"] = []
        try:
            ids.append(int(r.get(chiave_id)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return
    try:
        from .quality_models import AnomaliaEsito, AnomaliaSchedaQualita

        schede = {s["anomalia_id"]: s for s in AnomaliaSchedaQualita.objects.filter(anomalia_id__in=ids).values(
            "anomalia_id", "segnala_terzista", "segnalato_cliente_il", "segnalato_cliente_da",
            "segnalato_terzista_il", "segnalato_terzista_da", "segnalato_cliente_ruolo", "segnalato_terzista_ruolo",
        )}
        risposte: dict[int, list[dict]] = {}
        tipi = {AnomaliaEsito.Tipo.RISPOSTA_CLIENTE: "cliente", AnomaliaEsito.Tipo.RISPOSTA_TERZISTA: "terzista"}
        for e in AnomaliaEsito.objects.filter(anomalia_id__in=ids, tipo__in=list(tipi)).order_by("-created_at", "-id"):
            risposte.setdefault(e.anomalia_id, []).append({
                "chi": tipi[e.tipo], "testo": e.testo, "da": e.utente_display,
                "il": timezone.localtime(e.created_at).strftime("%d/%m/%Y %H:%M"),
            })
    except Exception:
        logger.warning("anomalie: «Segnalato»/risposte non letti", exc_info=True)
        return
    for r in righe:
        try:
            aid = int(r.get(chiave_id))
        except (TypeError, ValueError):
            continue
        s = schede.get(aid)
        if s:
            r["segnala_terzista"] = bool(s["segnala_terzista"])
            r["segnalato_cliente"] = _payload_segnalato(s["segnalato_cliente_il"], s["segnalato_cliente_da"])
            r["segnalato_terzista"] = _payload_segnalato(s["segnalato_terzista_il"], s["segnalato_terzista_da"])
            for chi in DESTINATARI:
                if r[f"segnalato_{chi}"]:
                    r[f"segnalato_{chi}"]["ruolo"] = s[f"segnalato_{chi}_ruolo"] or "cc"
        r["risposte"] = risposte.get(aid, [])
