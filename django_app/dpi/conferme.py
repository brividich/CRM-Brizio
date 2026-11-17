"""Conferma di ricevuta dei DPI consegnati senza badge.

La ricevuta si conferma passando il badge della persona al Banco (oppure con la
firma sul tablet o la ricevuta su carta). Se la consegna e' registrata senza
nessuna delle tre, resta una conferma «Da confermare» che si conferma da sola dopo
``ORE_AUTOCONFERMA`` ore (task ``dpi_avvisi_consegna``, ogni 5 minuti). Nessuna mail.

Fino al 17/11/2026 la conferma arrivava per mail con un link personale sotto
``/approval-actions/dpi/``: i link gia' inviati restano validi finche' la conferma e'
in attesa, quindi «Non li ho ricevuti» avvisa ancora il Magazzino.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from automazioni.managed_flows import event_flow

from . import flusso

logger = logging.getLogger(__name__)

ORE_AUTOCONFERMA = 24
DECISIONI = {"conferma": "CONFERMATA", "contesta": "CONTESTATA"}


def hash_token(raw: str) -> str:
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


def _righe_dpi(consegne) -> list[str]:
    return [f"- {flusso._riga_dpi(c.richiesta)} ({c.richiesta.numero})" for c in consegne]


def richiedi(consegne, *, autore: str = ""):
    """Apre la conferma «Da confermare» per le consegne fatte insieme a una persona senza
    badge, firma o ricevuta su carta. Si conferma da sola dopo ``ORE_AUTOCONFERMA`` ore.

    Ritorna la conferma (None se non c'e' nulla). Fail-soft: un errore non annulla mai la
    consegna registrata."""
    from .models import ConfermaConsegnaDPI

    consegne = [c for c in consegne if c is not None]
    if not consegne:
        return None
    try:
        r = consegne[0].richiesta
        with transaction.atomic():
            conferma = ConfermaConsegnaDPI.objects.create(
                richiedente_legacy_id=r.richiedente_legacy_id, richiedente_nome=r.richiedente_nome,
                destinatario_tipo=ConfermaConsegnaDPI.Destinatario.DIPENDENTE, creata_da_nome=autore[:200],
            )
            for c in consegne:
                c.conferma = conferma
                c.save(update_fields=["conferma"])
        return conferma
    except Exception:
        logger.warning("Conferma di ricevuta DPI non aperta", exc_info=True)
        return None


def autoconferma(adesso=None) -> int:
    """Conferma le ricevute ancora «Da confermare» da almeno ``ORE_AUTOCONFERMA`` ore.
    Ritorna quante. Chi aggiorna per primo decide: browser e task insieme non raddoppiano."""
    from .models import ConfermaConsegnaDPI, RichiestaDPICommento

    adesso = adesso or timezone.now()
    limite = adesso - timedelta(hours=ORE_AUTOCONFERMA)
    fatte = 0
    for conferma in ConfermaConsegnaDPI.objects.filter(stato=ConfermaConsegnaDPI.Stato.IN_ATTESA, created_at__lte=limite):
        nota = f"Confermata automaticamente dopo {ORE_AUTOCONFERMA} ore senza contestazioni."
        if not ConfermaConsegnaDPI.objects.filter(pk=conferma.pk, stato=ConfermaConsegnaDPI.Stato.IN_ATTESA).update(
            stato=ConfermaConsegnaDPI.Stato.CONFERMATA, decisa_il=adesso, nota=nota,
        ):
            continue
        for c in conferma.consegne.select_related("richiesta"):
            RichiestaDPICommento.objects.create(
                richiesta=c.richiesta, autore_nome="Portale", is_interno=False,
                testo=f"Ricevuta confermata automaticamente: {ORE_AUTOCONFERMA} ore dopo la consegna senza badge.",
            )
        fatte += 1
    return fatte


def link_da_token(raw: str):
    from .models import LinkConfermaDPI

    raw = str(raw or "").strip()
    if not raw or len(raw) > 128:
        return None
    return LinkConfermaDPI.objects.select_related("conferma").filter(token_hash=hash_token(raw)).first()


def decidi(link, decisione: str, nota: str = "") -> bool:
    """Link di una mail gia' inviata prima del 17/11/2026: registra la decisione come il
    destinatario del link. False se gia' decisa (anche dall'autoconferma)."""
    from .models import ConfermaConsegnaDPI, RichiestaDPICommento

    stato = DECISIONI[decisione]
    with transaction.atomic():
        aggiornate = ConfermaConsegnaDPI.objects.filter(
            pk=link.conferma_id, stato=ConfermaConsegnaDPI.Stato.IN_ATTESA
        ).update(stato=stato, decisa_il=timezone.now(), decisa_da_email=link.email, nota=(nota or "")[:500])
    if not aggiornate:
        return False
    conferma = ConfermaConsegnaDPI.objects.get(pk=link.conferma_id)
    consegne = list(conferma.consegne.select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi",
                                                     "richiesta__modello_dpi", "richiesta__taglia_dpi"))
    if stato == ConfermaConsegnaDPI.Stato.CONFERMATA:
        testo = f"Ricevuta confermata via mail da {link.email}."
    else:
        testo = f"Ricevuta CONTESTATA via mail da {link.email}: «non li ho ricevuti»." + (f" Nota: {nota}" if nota else "")
    for c in consegne:
        RichiestaDPICommento.objects.create(richiesta=c.richiesta, autore_nome="Portale", testo=testo, is_interno=False)
    if stato == ConfermaConsegnaDPI.Stato.CONTESTATA and consegne:
        _avvisa_contestazione(conferma, consegne)
    return True


@event_flow("dpi_consegna_contestata", skipped_result=None)
def _avvisa_contestazione(conferma, consegne) -> None:
    try:
        r = consegne[0].richiesta
        corpo = "\n".join([
            f"{conferma.decisa_da_email} dice che {conferma.richiedente_nome} NON ha ricevuto questi DPI, "
            "registrati come consegnati:", "", *_righe_dpi(consegne),
            *( ["", f"Nota: {conferma.nota}"] if conferma.nota else [] ),
            "", "Verifica la consegna (DPI > Banco consegne, riquadro «Conferme di ricevuta»).",
        ])
        flusso._mail(f"[DPI] Consegna contestata - {conferma.richiedente_nome}", corpo,
                     flusso.destinatari_consegna(r), title="Consegna DPI contestata")
    except Exception:
        logger.warning("Avviso di consegna DPI contestata non inviato (%s)", conferma.pk, exc_info=True)
