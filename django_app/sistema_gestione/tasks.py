"""Job pianificati del sistema di gestione (django-q)."""
from __future__ import annotations

import logging
import os

from django.utils import timezone

logger = logging.getLogger(__name__)

CHIAVE_ESCALATION_GIORNI = "sistema_gestione.car_escalation_giorni"
CHIAVE_EMAIL_RSGI = "sistema_gestione.audit_email_rsgi"


def _legacy_id(user) -> int | None:
    profile = getattr(user, "profile", None) if user else None
    return int(profile.legacy_user_id) if profile is not None and profile.legacy_user_id else None


def _nome(user) -> str:
    return ((user.get_full_name() or user.get_username()).strip() if user else "") or "responsabile non assegnato"


def _responsabili_funzione(car) -> set[str]:
    """Email dei responsabili dei processi dei rilievi collegati alla CAR (escalation di funzione)."""
    from .models import AuditEsito

    return {
        (e.processo.responsabile.email or "").strip()
        for e in AuditEsito.objects.filter(ofi_id=car.registro_id, processo__responsabile__isnull=False).select_related("processo__responsabile")
        if (e.processo.responsabile.email or "").strip()
    }


def _giorni_escalation() -> int:
    from core.models import SiteConfig

    try:
        return max(1, int(SiteConfig.get(CHIAVE_ESCALATION_GIORNI, "15") or 15))
    except (TypeError, ValueError):
        return 15


def _email_rsgi() -> list[str]:
    from core.models import SiteConfig

    valori = (SiteConfig.get(CHIAVE_EMAIL_RSGI, "") or os.environ.get("SISTEMA_GESTIONE_AUDIT_EMAIL_MSM", "")).replace(";", ",")
    return sorted({v.strip() for v in valori.split(",") if v.strip()})


def ritardi_car(oggi=None) -> list[dict]:
    """CAR aperte in ritardo: analisi oltre 1 mese, chiusura oltre scadenza o proroga,
    verifica di efficacia programmata e non eseguita."""
    from .models import AuditVerificaEfficacia, AzioneCorrettivaAudit

    oggi = oggi or timezone.localdate()
    out = []
    for car in AzioneCorrettivaAudit.objects.filter(chiusa_il__isnull=True).select_related("registro", "responsabile__profile"):
        motivi = []
        if not car.analizzata_il and oggi > car.scadenza_analisi:
            motivi.append(("analisi", car.scadenza_analisi))
        if oggi > car.scadenza_chiusura:
            motivi.append(("chiusura", car.scadenza_chiusura))
        if motivi:
            out.append({"car": car, "motivi": motivi, "giorni": (oggi - min(d for _m, d in motivi)).days})
    ultime = {}
    for verifica in AuditVerificaEfficacia.objects.filter(prossima_verifica__isnull=False).select_related("esito__ofi").order_by("esito_id", "-registrato_il"):
        ultime.setdefault(verifica.esito_id, verifica)
    for verifica in ultime.values():
        if verifica.risultato != "EFFICACE" and verifica.prossima_verifica < oggi and verifica.esito.ofi_id:
            car = getattr(verifica.esito.ofi, "car_procedurale", None)
            if car is not None and car.chiusa_il is None:
                riga = next((r for r in out if r["car"].pk == car.pk), None)
                if riga is None:
                    riga = {"car": car, "motivi": [], "giorni": 0}
                    out.append(riga)
                riga["motivi"].append(("efficacia", verifica.prossima_verifica))
                riga["giorni"] = max(riga["giorni"], (oggi - verifica.prossima_verifica).days)
    return out


_TESTO = {"analisi": "analisi delle cause scaduta il {d}", "chiusura": "chiusura scaduta il {d}",
          "efficacia": "verifica di efficacia prevista il {d}"}


def run_car_solleciti() -> dict:
    """Un sollecito al giorno al responsabile; oltre la soglia, una sola escalation a RSGI."""
    from django.urls import reverse

    from core.notifiche import invia_notifica, invia_notifica_email

    oggi = timezone.localdate()
    soglia = _giorni_escalation()
    solleciti = escalation = 0
    da_escalare = []
    responsabili_funzione: set[str] = set()
    for riga in ritardi_car(oggi):
        car = riga["car"]
        url = reverse("sistema_gestione:procedura_car", args=[car.registro_id])
        testo = "; ".join(_TESTO[m].format(d=d.strftime("%d/%m/%Y")) for m, d in riga["motivi"])
        if car.sollecitata_il != oggi:
            messaggio = f"CAR MOD.174 n. {car.registro.numero}: {testo}."
            legacy_id = _legacy_id(car.responsabile)
            consegnato = False
            if legacy_id:
                invia_notifica(legacy_id, "sistema_gestione", messaggio, url)
                consegnato = True
            elif getattr(car.responsabile, "email", ""):
                # Senza profilo legacy la notifica in-app non arriva: ripiego sull'email.
                consegnato = bool(invia_notifica_email(car.responsabile.email, "sistema_gestione", messaggio, url))
            if consegnato:
                car.sollecitata_il = oggi
                car.save(update_fields=["sollecitata_il"])
                solleciti += 1
            else:
                logger.warning("Sollecito CAR %s non consegnato: responsabile senza profilo né email", car.registro.numero)
        if riga["giorni"] >= soglia and car.escalation_il is None:
            da_escalare.append((car, testo, url))
            responsabili_funzione |= _responsabili_funzione(car)
    destinatari = sorted(set(_email_rsgi()) | responsabili_funzione)
    if da_escalare and destinatari:
        from core.email_utils import send_hub_mail

        corpo = "\n".join(f"- MOD.174 n. {c.registro.numero} ({_nome(c.responsabile)}): {t}" for c, t, _u in da_escalare)
        try:
            send_hub_mail(
                subject=f"CAR in ritardo oltre {soglia} giorni: {len(da_escalare)}",
                body_text=f"Azioni correttive da audit in ritardo oltre la soglia di escalation:\n{corpo}",
                recipients=destinatari, title="Escalation azioni correttive", email_type="Sistema di gestione",
            )
        except Exception:
            logger.exception("Escalation CAR non inviata")
        else:
            for car, _t, _u in da_escalare:
                car.escalation_il = oggi
                car.save(update_fields=["escalation_il"])
                escalation += 1
    elif da_escalare:
        logger.warning("Escalation CAR senza destinatari: configura %s", CHIAVE_EMAIL_RSGI)
    return {"solleciti": solleciti, "escalation": escalation}


def run_scadenze_audit_esterni() -> dict:
    """Ogni settimana a RSGI: certificati scaduti o in scadenza, sorveglianze entro 30 giorni,
    piani azioni da inviare all'ente entro 7 giorni (o già in ritardo)."""
    from .services.audit_esterni import scadenze

    dati = scadenze()
    righe = []
    for c in dati["certificati"]:
        stato = "SCADUTO" if c.stato == "scaduta" else "in scadenza"
        righe.append(f"- Certificato {c} {stato} il {c.scade_il:%d/%m/%Y}")
    for c in dati["sorveglianze"]:
        righe.append(f"- Audit di sorveglianza {c} previsto il {c.prossima_sorveglianza:%d/%m/%Y}")
    for a in dati["risposte"]:
        righe.append(f"- Piano azioni per {a} da inviare entro il {a.risposta_entro:%d/%m/%Y}")
    destinatari = _email_rsgi()
    if not righe:
        return {"voci": 0, "inviata": False}
    if not destinatari:
        logger.warning("Scadenze audit esterni senza destinatari: configura %s", CHIAVE_EMAIL_RSGI)
        return {"voci": len(righe), "inviata": False}
    from core.email_utils import send_hub_mail
    try:
        send_hub_mail(
            subject=f"Certificazioni e audit esterni: {len(righe)} scadenze",
            body_text="Scadenze delle certificazioni e degli audit esterni:\n" + "\n".join(righe),
            recipients=destinatari, title="Certificazioni e audit esterni", email_type="Sistema di gestione",
        )
    except Exception:
        logger.exception("Avviso scadenze audit esterni non inviato")
        return {"voci": len(righe), "inviata": False}
    return {"voci": len(righe), "inviata": True}
