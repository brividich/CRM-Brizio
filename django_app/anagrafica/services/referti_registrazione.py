"""Dal referto letto alle visite registrate.

UN CERTIFICATO NON È UNA VISITA

È la cosa che sorprende di più di questo documento: il certificato di idoneità
porta un intero **protocollo sanitario**, cioè più esami, ciascuno con la propria
cadenza — visita medica annuale, oculistica biennale, antitetanica decennale. Da
un solo PDF nascono quindi più ``VisitaMedica``, tutte con la stessa data di
svolgimento e scadenze diverse. Trattarlo come «una visita» significherebbe
perdere le altre e lasciare scoperte le scadenze che nessuno vede.

LA PERIODICITÀ VIENE DAL CATALOGO

La scadenza la calcola ``VisitaMedica.save()`` da ``TipoVisitaMedica.durata_mesi``,
come per ogni altra visita registrata a mano. Una sola regola in tutto il sistema,
nessun percorso privilegiato per i referti automatici.

Il che **non** vuol dire ignorare quello che c'è scritto sul certificato: se il
medico dichiara una cadenza diversa da quella a catalogo, la visita si crea
comunque col valore del catalogo, ma la divergenza viene registrata e mostrata.
Una divergenza significa che il protocollo è cambiato, ed è un'informazione che
deve raggiungere una persona invece di essere sovrascritta in silenzio.

QUELLO CHE NON SI INVENTA

Un esame che non trova corrispondenza a catalogo non diventa un tipo nuovo, e un
giudizio che non si riconosce non diventa l'esito più somigliante. In entrambi i
casi si va in revisione: inventare un tipo significa inventare una scadenza, e
scegliere «il più simile» fra «idoneo con prescrizioni» e «idoneo con
limitazioni» significa cambiare cosa può fare una persona al lavoro.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction

from .referti_parsing import PERIODICITA_NOTE, normalizza

logger = logging.getLogger(__name__)

__all__ = [
    "PianoRegistrazione",
    "prepara_registrazione",
    "registra",
    "ErroreRegistrazione",
]


class ErroreRegistrazione(Exception):
    """Non si può registrare, con un motivo dicibile a una persona."""


@dataclass
class PianoRegistrazione:
    """Cosa verrebbe creato, prima di crearlo.

    Esiste separato dall'esecuzione perché la coda di revisione deve poter
    *mostrare* l'effetto di una conferma senza produrlo: chi revisiona vede le
    visite che nascerebbero, con le loro scadenze, e poi decide.
    """

    tipi: list = field(default_factory=list)          # [(TipoVisitaMedica, dict esame)]
    esito: str = ""
    divergenze: list[dict] = field(default_factory=list)
    esami_ignoti: list[str] = field(default_factory=list)

    @property
    def completo(self) -> bool:
        return bool(self.tipi) and bool(self.esito) and not self.esami_ignoti


def _mappa_esami() -> dict[str, int]:
    """Testo normalizzato dell'esame → id del tipo di visita."""
    from ..models_sorveglianza import AliasEsameProtocollo

    mappa = {}
    for testo, tipo_id in (
        AliasEsameProtocollo.objects.filter(attivo=True).values_list("testo", "tipo_id")
    ):
        mappa[normalizza(testo)] = tipo_id
    return mappa


def _mappa_esiti() -> dict[str, str]:
    """Testo normalizzato del giudizio → valore di esito."""
    from ..models_sorveglianza import AliasEsitoIdoneita

    return {
        normalizza(testo): esito
        for testo, esito in
        AliasEsitoIdoneita.objects.filter(attivo=True).values_list("testo", "esito")
    }


def _tipi_per_nome() -> dict[str, int]:
    """Il catalogo stesso vale come alias: se il medico scrive esattamente il nome
    che abbiamo a catalogo, non c'è ragione di pretendere una riga di mappatura."""
    from ..models import TipoVisitaMedica

    return {
        normalizza(nome): tipo_id
        for tipo_id, nome in TipoVisitaMedica.objects.filter(is_active=True)
        .values_list("id", "nome")
    }


def prepara_registrazione(campi) -> PianoRegistrazione:
    """Traduce quello che si è letto in tipi a catalogo ed esito in codice.

    Non tocca il database in scrittura e non solleva: descrive.
    """
    from ..models import TipoVisitaMedica

    piano = PianoRegistrazione()

    alias_esami = _mappa_esami()
    per_nome = _tipi_per_nome()
    tipi_cache = {t.id: t for t in TipoVisitaMedica.objects.filter(is_active=True)}

    for voce in (campi.protocollo or []):
        chiave = normalizza(voce.get("esame", ""))
        tipo_id = alias_esami.get(chiave) or per_nome.get(chiave)
        tipo = tipi_cache.get(tipo_id) if tipo_id else None
        if tipo is None:
            piano.esami_ignoti.append(voce.get("esame", ""))
            continue

        piano.tipi.append((tipo, voce))

        # Confronto fra la cadenza dichiarata dal medico e quella a catalogo.
        mesi_certificato = PERIODICITA_NOTE.get((voce.get("periodicita") or "").lower())
        if mesi_certificato and tipo.durata_mesi and mesi_certificato != tipo.durata_mesi:
            piano.divergenze.append({
                "esame": voce.get("esame", ""),
                "tipo": tipo.nome,
                "certificato_mesi": mesi_certificato,
                "catalogo_mesi": tipo.durata_mesi,
            })

    alias_esiti = _mappa_esiti()
    piano.esito = alias_esiti.get(normalizza(campi.esito_testo or ""), "")

    return piano


def _descrizione_divergenze(divergenze: list[dict]) -> str:
    if not divergenze:
        return ""
    pezzi = [
        f"{d['tipo']}: il certificato dice {d['certificato_mesi']} mesi, "
        f"il catalogo {d['catalogo_mesi']}"
        for d in divergenze
    ]
    return "Periodicità diverse dal catalogo (vale il catalogo) — " + "; ".join(pezzi)


@transaction.atomic
def registra(riga, *, utente=None, legacy_id: int | None = None):
    """Crea le visite del protocollo e archivia il referto nel fascicolo.

    Atomica per necessità, non per prudenza: un protocollo registrato a metà
    lascerebbe scadenze scoperte che nessuno sa mancanti, ed è peggio di un
    referto che torna in coda.
    """
    from django.utils import timezone

    from ..models import VisitaMedica
    from ..models_sorveglianza import RefertoIntakeRiga
    from .referti_parsing import CampiReferto

    legacy_id = legacy_id or riga.legacy_anagrafica_id_proposto
    if not legacy_id:
        raise ErroreRegistrazione("Nessun dipendente scelto per questo referto.")
    if riga.letto_data_giudizio is None:
        raise ErroreRegistrazione(
            "Manca la data del giudizio: senza quella la scadenza sarebbe inventata."
        )

    campi = CampiReferto(
        esito_testo=riga.letto_esito_testo,
        protocollo=list(riga.letto_protocollo or []),
    )
    piano = prepara_registrazione(campi)

    if piano.esami_ignoti:
        raise ErroreRegistrazione(
            "Esami non presenti a catalogo: "
            + ", ".join(piano.esami_ignoti)
            + ". Vanno mappati dalle impostazioni prima di registrare."
        )
    if not piano.tipi:
        raise ErroreRegistrazione("Nessun esame riconosciuto nel protocollo sanitario.")
    if not piano.esito:
        raise ErroreRegistrazione(
            f"Giudizio «{riga.letto_esito_testo or '—'}» non riconosciuto: "
            "va mappato dalle impostazioni prima di registrare."
        )

    # Doppione logico: stesso dipendente, stesso tipo, stessa data. Non è un
    # errore del lettore, è un referto già registrato — magari a mano.
    gia_presenti = set(
        VisitaMedica.objects
        .filter(
            legacy_anagrafica_id=legacy_id,
            data_svolgimento=riga.letto_data_giudizio,
            tipo_id__in=[t.id for t, _ in piano.tipi],
        )
        .values_list("tipo_id", flat=True)
    )
    da_creare = [(t, v) for t, v in piano.tipi if t.id not in gia_presenti]
    if not da_creare:
        raise ErroreRegistrazione(
            "Queste visite risultano già registrate per il dipendente in questa data."
        )

    documento = _archivia_nel_fascicolo(riga, legacy_id, utente)

    create = []
    for tipo, _voce in da_creare:
        visita = VisitaMedica(
            legacy_anagrafica_id=legacy_id,
            tipo=tipo,
            data_svolgimento=riga.letto_data_giudizio,
            esito=piano.esito,
            medico_competente="",
            note=_descrizione_divergenze(piano.divergenze),
            referto_documento=documento,
            created_by=utente,
            updated_by=utente,
        )
        visita.save()  # la scadenza la calcola save() dal catalogo
        create.append(visita)

    riga.legacy_anagrafica_id_proposto = legacy_id
    riga.esito = RefertoIntakeRiga.ESITO_OK
    riga.visite_create = len(create)
    riga.documento = documento
    riga.divergenze = piano.divergenze
    riga.confermato_da = utente
    riga.confermato_il = timezone.now()
    saltate = len(piano.tipi) - len(da_creare)
    riga.messaggio = (
        f"{len(create)} visite registrate"
        + (f", {saltate} già presenti" if saltate else "")
        + ("; " + _descrizione_divergenze(piano.divergenze) if piano.divergenze else "")
    )
    riga.save()

    return create


def _archivia_nel_fascicolo(riga, legacy_id: int, utente):
    """Il referto nel fascicolo del dipendente, uno solo per tutte le visite.

    Il PDF è uno: duplicarlo per ogni esame del protocollo gonfierebbe l'archivio
    e moltiplicherebbe le copie di un dato sanitario, che è il contrario di quello
    che si vuole.
    """
    from django.core.files.base import ContentFile

    from ..models import DocumentoDipendente
    from .archivio_scansioni import apri_archiviata

    if riga.documento_id:
        return riga.documento

    contenuto = b""
    handle = apri_archiviata(riga.percorso)
    if handle is not None:
        try:
            contenuto = handle.read()
        except Exception:
            logger.exception("Referto: rilettura dall'archivio fallita (%s)", riga.percorso)
        finally:
            try:
                handle.close()
            except Exception:
                pass

    if not contenuto:
        logger.warning("Referto: nessun contenuto da archiviare nel fascicolo (riga %s)", riga.pk)
        return None

    nome = riga.nome_file or "referto.pdf"
    doc = DocumentoDipendente(
        legacy_anagrafica_id=legacy_id,
        tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        nome_originale=nome,
        tipo_mime="application/pdf",
        dimensione_bytes=len(contenuto),
        descrizione=(
            f"Certificato di idoneità del {riga.letto_data_giudizio:%d-%m-%Y}"
            if riga.letto_data_giudizio else "Certificato di idoneità"
        ),
        oggetto_riferimento_tipo="anagrafica.refertointakeriga",
        oggetto_riferimento_id=riga.pk,
        created_by=utente,
        created_by_display=(
            (utente.get_full_name() or utente.username) if utente else "Acquisizione automatica"
        ),
    )
    doc.file.save(nome, ContentFile(contenuto), save=True)
    return doc
