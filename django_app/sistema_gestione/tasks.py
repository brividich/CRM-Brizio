"""Job pianificati del sistema di gestione (django-q)."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

CHIAVE_ESCALATION_GIORNI = "sistema_gestione.car_escalation_giorni"
CHIAVE_EMAIL_RSGI = "sistema_gestione.audit_email_rsgi"


def _legacy_id(user) -> int | None:
    profile = getattr(user, "profile", None) if user else None
    return int(profile.legacy_user_id) if profile is not None and profile.legacy_user_id else None


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

    from core.notifiche import invia_notifica

    oggi = timezone.localdate()
    soglia = _giorni_escalation()
    solleciti = escalation = 0
    da_escalare = []
    for riga in ritardi_car(oggi):
        car = riga["car"]
        url = reverse("sistema_gestione:procedura_car", args=[car.registro_id])
        testo = "; ".join(_TESTO[m].format(d=d.strftime("%d/%m/%Y")) for m, d in riga["motivi"])
        if car.sollecitata_il != oggi:
            invia_notifica(_legacy_id(car.responsabile), "sistema_gestione",
                           f"CAR MOD.174 n. {car.registro.numero}: {testo}.", url)
            car.sollecitata_il = oggi
            car.save(update_fields=["sollecitata_il"])
            solleciti += 1
        if riga["giorni"] >= soglia and car.escalation_il is None:
            da_escalare.append((car, testo, url))
    destinatari = _email_rsgi()
    if da_escalare and destinatari:
        from core.email_utils import send_hub_mail

        corpo = "\n".join(f"- MOD.174 n. {c.registro.numero} ({c.responsabile}): {t}" for c, t, _u in da_escalare)
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
