"""Notifiche del cambio mansione: «c'è un adempimento», mai il contenuto clinico.

Due flussi, entrambi gestiti dal designer automazioni:

- evento ``cambio_mansione_piano`` (``managed_flows.event_flow``): parte **dopo
  il commit** quando il piano di adeguamento di uno spostamento (o un
  riallineamento) crea nuovi adempimenti;
- schedule ``cambio_mansione_digest``: riepilogo mattutino di adempimenti in
  ritardo e persone con stato operativo da segnalare.

Destinatari: ``SiteConfig.cambio_mansione_emails`` (modificabili da Automazioni
→ Task pianificati → «Configura mail» del digest). Senza destinatari
configurati non parte nulla: niente ripiego su admin/superuser, perché la mail
nomina persone e adempimenti di sicurezza.

Privacy: le visite compaiono come «Visita medica» (mai il tipo), nessun esito,
nessuna prescrizione, nessun motivo sanitario.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from automazioni.managed_flows import event_flow

logger = logging.getLogger(__name__)

CONFIG_KEY = "cambio_mansione_emails"
_TIPI = {"VISITA": "Visita medica", "FORMAZIONE": "Formazione", "DPI": "DPI", "SDS": "Schede di sicurezza"}


def destinatari() -> list[str]:
    from core.models import SiteConfig
    from core.reminder_recipients import split_emails
    return sorted(set(split_emails(SiteConfig.get(CONFIG_KEY, "") or "")))


def _nome_persona(legacy_id: int) -> str:
    try:
        from core import naming
        from core.legacy_anagrafica import fetch_anagrafica_rows
        rows = fetch_anagrafica_rows(ids=[legacy_id])
        if rows:
            return naming.nome_completo(rows[0].get("nome"), rows[0].get("cognome")) or f"#{legacy_id}"
    except Exception:
        pass
    return f"#{legacy_id}"


def _voce(adempimento) -> str:
    """Riga di un adempimento senza dettaglio sanitario."""
    if adempimento.tipo == "VISITA":
        return f"Visita medica, entro il {adempimento.entro_il:%d/%m/%Y}"
    return f"{adempimento.descrizione}, entro il {adempimento.entro_il:%d/%m/%Y}"


@event_flow("cambio_mansione_piano", skipped_result=None)
def notifica_piano_cambio_mansione(legacy_id: int, assegnazione_id: int) -> int:
    """Avvisa i destinatari configurati dei nuovi adempimenti aperti di uno spostamento."""
    from core.email_utils import send_hub_mail
    from ..models import AdempimentoCambioMansione as A, DipendenteAssegnazione

    dest = destinatari()
    if not dest:
        return 0
    assegnazione = DipendenteAssegnazione.objects.filter(pk=assegnazione_id).first()
    if assegnazione is None:
        return 0
    aperti = list(assegnazione.adempimenti.filter(stato=A.STATO_APERTO, attivo=True).order_by("entro_il", "tipo"))
    if not aperti:
        return 0
    nome = _nome_persona(legacy_id)
    send_hub_mail(
        subject=f"[Cambio mansione] {nome}: {len(aperti)} adempimenti da completare",
        body_text=(
            f"{nome} → mansione «{assegnazione.mansione}» dal {assegnazione.data_inizio:%d/%m/%Y}.\n\n"
            "Adempimenti da completare entro la decorrenza:\n- " + "\n- ".join(_voce(a) for a in aperti)
            + "\n\nDettaglio: NOVICROM HUB → Anagrafica → Cambi mansione."
        ),
        recipients=dest, title="Piano di adeguamento al cambio mansione",
        email_type="Anagrafica HR", section_label="Cambio mansione", fail_silently=True,
    )
    return len(dest)


def invia_digest() -> dict:
    """Riepilogo: adempimenti in ritardo + persone non idonee a operare / in avviso."""
    from core.email_utils import send_hub_mail
    from ..models import AdempimentoCambioMansione as A
    from . import stato_operativo

    dest = destinatari()
    if not dest:
        return {"inviato": False, "motivo": "nessun destinatario"}
    oggi = timezone.localdate()
    ritardo = list(
        A.objects.filter(stato=A.STATO_APERTO, attivo=True, entro_il__lt=oggi)
        .order_by("entro_il", "legacy_anagrafica_id")[:200]
    )
    stati = [s for s in stato_operativo.calcola().values() if s.codice != stato_operativo.OK]
    if not ritardo and not stati:
        return {"inviato": False, "motivo": "niente da segnalare"}
    righe = []
    if stati:
        righe.append(f"Stato operativo da verificare ({len(stati)}):")
        righe += [f"- {_nome_persona(s.legacy_id)}: {s.etichetta}" for s in stati]
        righe.append("")
    if ritardo:
        righe.append(f"Adempimenti in ritardo ({len(ritardo)}):")
        righe += [f"- {_nome_persona(a.legacy_anagrafica_id)}: {_voce(a)}" for a in ritardo]
    send_hub_mail(
        subject=f"[Cambio mansione] {len(stati)} persone da verificare, {len(ritardo)} adempimenti in ritardo",
        body_text="\n".join(righe) + "\n\nDettaglio: NOVICROM HUB → Anagrafica → Cambi mansione.",
        recipients=dest, title="Cambio mansione — riepilogo", email_type="Anagrafica HR",
        section_label="Cambio mansione", fail_silently=True,
    )
    return {"inviato": True, "stati": len(stati), "ritardo": len(ritardo)}
