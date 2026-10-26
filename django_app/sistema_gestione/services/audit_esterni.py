"""Audit esterni (enti, clienti, autorità) e certificazioni del sistema di gestione.

I rilievi di un audit esterno diventano voci del Registro OFI (MOD.174) con origine
l'audit e fonte l'ente, così azioni, CAR, solleciti e cruscotto restano quelli del
registro unico.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import AuditEsterno, Certificazione

CLASSIFICAZIONI = [
    ("NC_MAGGIORE", "Non conformità maggiore"),
    ("NC_MINORE", "Non conformità minore"),
    ("OSSERVAZIONE", "Osservazione"),
    ("OFI", "Opportunità di miglioramento"),
]
_ETICHETTE = dict(CLASSIFICAZIONI)
# Campo norma dell'audit esterno -> campo norma del registro OFI.
_NORME = {"en9100": "norma_en9100", "iso45001": "norma_iso45001", "iso14001": "norma_iso14001",
          "iso27001": "norma_iso27001", "pdr125": "norma_pdr125"}


def rilievi(audit: AuditEsterno):
    from gestione_specifiche.models import RegistroOFI
    ct = ContentType.objects.get_for_model(AuditEsterno)
    return (RegistroOFI.objects.filter(content_type=ct, object_id=audit.pk)
            .select_related("responsabile").order_by("numero"))


def crea_rilievo(audit: AuditEsterno, *, classificazione: str, descrizione: str, utente, rif_norma: str = "",
                 processo: str = "", data_richiesta=None, responsabile=None):
    """Registra un rilievo dell'audit esterno come voce del Registro OFI."""
    from gestione_specifiche import registro_ofi as reg
    from gestione_specifiche.models import RegistroOFI

    if classificazione not in _ETICHETTE:
        raise ValueError("Classificazione non valida.")
    nc = classificazione.startswith("NC_")
    testo = descrizione.strip()
    if classificazione != "OFI":
        testo = f"[{_ETICHETTE[classificazione]}] {testo}"
    dati = {
        "data_apertura": audit.data_fine or audit.data_inizio,
        "tipo": RegistroOFI.TIPO_NC if nc else RegistroOFI.TIPO_OFI,
        "fonte": audit.ente[:100],
        "ref": f"{audit.get_tipo_display()} {audit.data_inizio:%d/%m/%Y}"[:100],
        "rif_norma": rif_norma[:200],
        "processo": processo[:200],
        "opportunita": testo[:5000],
        "priorita": RegistroOFI.PRIORITA_ALTA if classificazione == "NC_MAGGIORE" else RegistroOFI.PRIORITA_MEDIA,
        "data_richiesta": data_richiesta or audit.risposta_entro,
        "responsabile": responsabile,
        "modulo_origine": "sistema_gestione",
        "content_type": ContentType.objects.get_for_model(AuditEsterno),
        "object_id": audit.pk,
        **{campo_ofi: getattr(audit, campo) for campo, campo_ofi in _NORME.items()},
    }
    voce = None
    for tentativo in range(2):
        try:
            with transaction.atomic():
                voce = RegistroOFI.objects.create(numero=reg.prossimo_numero(), **dati)
            break
        except IntegrityError:
            if tentativo:
                raise
    reg.registra_evento(voce, "CREATA", utente=utente, a=voce.get_fase_display(),
                        nota=f"Rilievo dell'audit esterno: {audit}")
    if audit.stato == AuditEsterno.STATO_PIANIFICATO:
        audit.stato = AuditEsterno.STATO_SVOLTO
        audit.save(update_fields=["stato", "aggiornato_il"])
    return voce


def nc_aperte(audit: AuditEsterno) -> int:
    from gestione_specifiche.models import RegistroOFI
    return sum(1 for v in rilievi(audit) if v.tipo == RegistroOFI.TIPO_NC and not v.is_chiuso)


def problemi_chiusura(audit: AuditEsterno) -> list[str]:
    """Cosa manca per chiudere l'audit esterno."""
    problemi = []
    if not audit.esito:
        problemi.append("Registra l'esito comunicato dall'ente.")
    if not audit.rapporto:
        problemi.append("Carica il rapporto dell'ente.")
    aperte = nc_aperte(audit)
    if aperte:
        problemi.append(f"Ci sono {aperte} non conformità ancora aperte nel Registro OFI.")
    return problemi


def scadenze(oggi=None, *, giorni_risposta: int = 7, giorni_sorveglianza: int = 30) -> dict:
    """Certificati scaduti o in scadenza, sorveglianze vicine, risposte all'ente da inviare."""
    oggi = oggi or timezone.localdate()
    certificati = [c for c in Certificazione.objects.filter(attiva=True) if c.stato in ("scaduta", "in_scadenza")]
    sorveglianze = list(Certificazione.objects.filter(
        attiva=True, prossima_sorveglianza__isnull=False,
        prossima_sorveglianza__lte=oggi + timedelta(days=giorni_sorveglianza)).order_by("prossima_sorveglianza"))
    risposte = list(AuditEsterno.objects.exclude(stato=AuditEsterno.STATO_CHIUSO).filter(
        risposta_entro__isnull=False, risposta_entro__lte=oggi + timedelta(days=giorni_risposta))
        .order_by("risposta_entro"))
    return {"certificati": certificati, "sorveglianze": sorveglianze, "risposte": risposte}
