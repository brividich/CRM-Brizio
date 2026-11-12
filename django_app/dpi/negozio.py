"""Scarpe ordinate al negozio, per le categorie con «Si ordina al negozio».

Due modalita' scelte nella richiesta:

- **Convenzione**: dopo l'approvazione entra nel riepilogo che l'operatore incaricato manda
  al negozio ogni N giorni (Impostazioni). Quando arrivano si ritirano in ufficio
  amministrativo e la consegna si chiude come gli altri DPI (banco o scheda richiesta).
- **Fuori convenzione**: l'operatore avvisa il negozio, il dipendente ritira li'. Si chiude
  caricando la fattura e spuntando gli ordini che copre.

Le scarpe si comprano per la persona: non passano dal magazzino, niente scarico.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from .models import DPIImpostazioni, ModalitaNegozio, OrdineNegozioDPI, RichiestaDPI, StatoRichiesta

logger = logging.getLogger(__name__)

GIORNI_TRA_PROMEMORIA = 3


def da_ordinare(qs):
    return qs.filter(modalita_negozio=ModalitaNegozio.CONVENZIONE, ordine_negozio__isnull=True)


def ordinate(qs):
    return qs.filter(modalita_negozio=ModalitaNegozio.CONVENZIONE, ordine_negozio__isnull=False)


def fuori_convenzione(qs):
    return qs.filter(modalita_negozio=ModalitaNegozio.FUORI)


def dettaglio_ordine(richiesta: RichiestaDPI) -> str:
    """Scarpa, taglia, quantita' e numero della richiesta."""
    parti = [p for p in (
        richiesta.tipo_dpi.nome if richiesta.tipo_dpi_id else "",
        f"{richiesta.modello_dpi.codice} {richiesta.modello_dpi.nome}".strip() if richiesta.modello_dpi_id else "",
    ) if p] or [richiesta.categoria.nome]
    taglia = f"taglia {richiesta.taglia_dpi.valore}" if richiesta.taglia_dpi_id else "taglia da definire"
    return f"{', '.join(parti)}, {taglia}, quantità {richiesta.quantita} ({richiesta.numero})"


def riga_ordine(richiesta: RichiestaDPI) -> str:
    """Una riga del riepilogo per il negozio."""
    return f"{richiesta.richiedente_nome}: {dettaglio_ordine(richiesta)}"


def testo_ordine(richieste, *, note: str = "") -> str:
    righe = "\n".join(f"- {riga_ordine(r)}" for r in richieste)
    paia = sum(r.quantita for r in richieste)
    testo = (
        "Buongiorno,\ndi seguito l'ordine delle scarpe in convenzione, da consegnare presso il nostro ufficio "
        f"amministrativo:\n\n{righe}\n\nTotale: {paia} paia."
    )
    return f"{testo}\n\n{note.strip()}" if note.strip() else testo


def registra_ordine(richieste, *, inviato_a: str, autore: str) -> OrdineNegozioDPI:
    ordine = OrdineNegozioDPI.objects.create(
        negozio_nome=DPIImpostazioni.get_singleton().negozio_nome[:120],
        inviato_a=inviato_a[:400],
        creato_da_nome=autore[:200],
    )
    RichiestaDPI.objects.filter(pk__in=[r.pk for r in richieste]).update(ordine_negozio=ordine, updated_at=timezone.now())
    return ordine


def prossimo_riepilogo(oggi=None):
    """Data entro cui mandare il prossimo riepilogo; None se non c'e' niente da ordinare."""
    coda = da_ordinare(RichiestaDPI.objects.filter(stato=StatoRichiesta.APPROVATA))
    prima = coda.order_by("created_at").values_list("created_at", flat=True).first()
    if prima is None:
        return None
    giorni = DPIImpostazioni.get_singleton().negozio_giorni_riepilogo or 15
    ultimo = OrdineNegozioDPI.objects.order_by("-created_at").values_list("created_at", flat=True).first()
    riferimento = max(prima, ultimo) if ultimo else prima
    return timezone.localtime(riferimento).date() + timedelta(days=giorni)


def promemoria_ordine(oggi=None) -> int:
    """Dal task giornaliero: scaduti i giorni del riepilogo, ricorda l'ordine all'operatore."""
    from . import flusso

    oggi = oggi or timezone.localdate()
    entro = prossimo_riepilogo(oggi)
    if entro is None or oggi < entro:
        return 0
    impost = DPIImpostazioni.get_singleton()
    ultimo = impost.negozio_promemoria_il
    if ultimo and (oggi - ultimo).days < GIORNI_TRA_PROMEMORIA:
        return 0
    coda = da_ordinare(RichiestaDPI.objects.filter(stato=StatoRichiesta.APPROVATA))
    inviate = flusso.notifica_promemoria_ordine(coda.count()) or 0
    if inviate:
        DPIImpostazioni.objects.filter(pk=impost.pk).update(negozio_promemoria_il=oggi)
    return inviate
