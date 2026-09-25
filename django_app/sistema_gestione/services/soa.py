"""Ciclo di vita della Dichiarazione di applicabilità: bozza -> proposta -> approvata -> superata."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..catalogo_27002 import CONTROLLI, ordine_di, tema_di
from ..models import ControlloIso27002, SoaRevisione, SoaVoce

_CAMPI_VOCE = (
    "livello", "vulnerabilita", "riferimenti", "giustificazione",
    "obbligo_legislativo", "obbligo_normativo", "obbligo_regolatorio", "obbligo_cliente", "buona_pratica",
    "azione", "responsabile", "scadenza", "livello_atteso", "ofi_id",
)


class TransizioneNonAmmessa(Exception):
    pass


def assicura_catalogo() -> int:
    """Crea i controlli mancanti (idempotente). Ritorna quanti ne ha creati."""
    esistenti = set(ControlloIso27002.objects.values_list("codice", flat=True))
    nuovi = [
        ControlloIso27002(codice=codice, titolo=titolo, tema=tema_di(codice), ordine=ordine_di(codice))
        for codice, titolo in CONTROLLI if codice not in esistenti
    ]
    ControlloIso27002.objects.bulk_create(nuovi)
    return len(nuovi)


def revisione_in_vigore() -> SoaRevisione | None:
    return SoaRevisione.objects.filter(stato=SoaRevisione.STATO_APPROVATA).order_by("-numero").first()


def revisione_di_lavoro() -> SoaRevisione | None:
    """La revisione non ancora approvata (bozza o proposta), se esiste."""
    return (
        SoaRevisione.objects.filter(stato__in=(SoaRevisione.STATO_BOZZA, SoaRevisione.STATO_PROPOSTA))
        .order_by("-numero").first()
    )


def prossimo_numero() -> int:
    massimo = SoaRevisione.objects.aggregate(m=Max("numero"))["m"]
    return 0 if massimo is None else massimo + 1


@transaction.atomic
def nuova_revisione(*, utente=None, motivo: str = "", numero: int | None = None, origine: str = "") -> SoaRevisione:
    """Nuova bozza: copia della revisione più recente, o vuota sul catalogo completo."""
    if revisione_di_lavoro() is not None:
        raise TransizioneNonAmmessa("Esiste già una revisione in bozza o proposta: completala prima di aprirne un'altra.")
    assicura_catalogo()
    base = SoaRevisione.objects.order_by("-numero").first()
    revisione = SoaRevisione.objects.create(
        numero=prossimo_numero() if numero is None else numero,
        motivo=motivo, origine=origine, preparata_da=utente,
    )
    voci_base = {v.controllo_id: v for v in base.voci.all()} if base else {}
    nuove = []
    for controllo in ControlloIso27002.objects.all():
        voce = SoaVoce(revisione=revisione, controllo=controllo, aggiornata_da=utente)
        precedente = voci_base.get(controllo.id)
        if precedente is not None:
            for campo in _CAMPI_VOCE:
                setattr(voce, campo, getattr(precedente, campo))
        nuove.append(voce)
    SoaVoce.objects.bulk_create(nuove)
    return revisione


def proponi(revisione: SoaRevisione, *, utente=None) -> SoaRevisione:
    if revisione.stato != SoaRevisione.STATO_BOZZA:
        raise TransizioneNonAmmessa("Si può proporre solo una revisione in bozza.")
    revisione.stato = SoaRevisione.STATO_PROPOSTA
    revisione.proposta_il = timezone.now()
    if revisione.preparata_da_id is None and utente is not None:
        revisione.preparata_da = utente
    revisione.save(update_fields=["stato", "proposta_il", "preparata_da", "updated_at"])
    return revisione


def riporta_in_bozza(revisione: SoaRevisione) -> SoaRevisione:
    if revisione.stato != SoaRevisione.STATO_PROPOSTA:
        raise TransizioneNonAmmessa("Solo una revisione proposta può tornare in bozza.")
    revisione.stato = SoaRevisione.STATO_BOZZA
    revisione.proposta_il = None
    revisione.save(update_fields=["stato", "proposta_il", "updated_at"])
    return revisione


@transaction.atomic
def approva(revisione: SoaRevisione, *, utente) -> SoaRevisione:
    if revisione.stato != SoaRevisione.STATO_PROPOSTA:
        raise TransizioneNonAmmessa("Si può approvare solo una revisione proposta alla Direzione.")
    SoaRevisione.objects.filter(stato=SoaRevisione.STATO_APPROVATA).update(
        stato=SoaRevisione.STATO_SUPERATA, updated_at=timezone.now(),
    )
    revisione.stato = SoaRevisione.STATO_APPROVATA
    revisione.approvata_da = utente
    revisione.approvata_il = timezone.now()
    revisione.save(update_fields=["stato", "approvata_da", "approvata_il", "updated_at"])
    return revisione


@dataclass
class StatisticheSoa:
    totale: int = 0
    pieni: int = 0
    parziali: int = 0
    esclusi: int = 0
    senza_giustificazione: int = 0
    azioni_aperte: int = 0
    azioni_scadute: int = 0

    @property
    def applicabili(self) -> int:
        return self.totale - self.esclusi

    @property
    def percentuale_piena(self) -> int | None:
        return round(self.pieni * 100 / self.applicabili) if self.applicabili else None


def statistiche(revisione: SoaRevisione | None, oggi=None) -> StatisticheSoa:
    stats = StatisticheSoa()
    if revisione is None:
        return stats
    oggi = oggi or timezone.localdate()
    for voce in revisione.voci.all():
        stats.totale += 1
        if voce.livello == 0:
            stats.esclusi += 1
        elif voce.livello == 4:
            stats.pieni += 1
        else:
            stats.parziali += 1
        if not (voce.giustificazione or "").strip():
            stats.senza_giustificazione += 1
        if voce.ha_azione_aperta:
            stats.azioni_aperte += 1
            if voce.azione_scaduta(oggi):
                stats.azioni_scadute += 1
    return stats


def differenze(revisione: SoaRevisione, precedente: SoaRevisione | None) -> dict[int, list[str]]:
    """Per ogni controllo, i campi cambiati rispetto alla revisione precedente."""
    if precedente is None:
        return {}
    prima = {v.controllo_id: v for v in precedente.voci.all()}
    etichette = {
        "livello": "livello", "vulnerabilita": "vulnerabilità", "riferimenti": "riferimenti",
        "giustificazione": "giustificazione", "azione": "azione", "responsabile": "responsabile",
        "scadenza": "scadenza", "livello_atteso": "livello atteso",
    }
    out: dict[int, list[str]] = {}
    for voce in revisione.voci.all():
        vecchia = prima.get(voce.controllo_id)
        if vecchia is None:
            out[voce.controllo_id] = ["nuovo controllo"]
            continue
        cambiati = [label for campo, label in etichette.items() if getattr(voce, campo) != getattr(vecchia, campo)]
        if cambiati:
            out[voce.controllo_id] = cambiati
    return out
