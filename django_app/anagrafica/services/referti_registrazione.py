"""Dal referto letto alla visita registrata e ai requisiti del dipendente.

UN CERTIFICATO DI IDONEITÀ È UNA VISITA SOLA

Il «PROTOCOLLO SANITARIO» stampato sul certificato **non** elenca esami svolti in
quella data: è il protocollo a cui il lavoratore è soggetto, deciso dal medico
competente in base a mansione, rischi ed età (D.Lgs 81/08 art. 41). La visita
svolta alla data del giudizio è una: la riga «Visita Medica», con la sua cadenza.
Le altre righe — oculistica, spirometria, antitetanica, esami ematici… — sono
**requisiti**: visite che il dipendente deve fare, non visite fatte.

Una prima versione creava una ``VisitaMedica`` per ogni riga del protocollo: dati
sanitari falsi (un'antitetanica «fatta» con scadenza a dieci anni), annullati in
produzione il 15/09/2026. Da qui la regola, che non va riaperta.

I REQUISITI SEGUONO L'ULTIMO CERTIFICATO

Tutte le righe del protocollo, «Visita Medica» compresa, diventano
``RequisitoVisitaDipendente``. Il certificato più recente sostituisce i requisiti
del precedente, che restano come storico: se il medico cambia il protocollo
(nuova mansione, età), lo scadenzario lo segue. Un esame dei requisiti non a
catalogo **non blocca** la registrazione della visita: resta con ``tipo`` vuoto e
viene segnalato, finché non lo si mappa.

LA PERIODICITÀ VIENE DAL CATALOGO

La scadenza la calcola ``VisitaMedica.save()`` da ``TipoVisitaMedica.durata_mesi``,
come per ogni altra visita. Se il medico dichiara una cadenza diversa da quella a
catalogo la divergenza viene registrata e mostrata, non sovrascritta in silenzio.

IL CERTIFICATO OCULISTICO

Modulo prestampato con data, nome, valori e giudizio **scritti a mano**. L'OCR non
li legge in modo affidabile e la frase «non si rilevano controindicazioni» è
stampata su ogni modulo: data ed esito li inserisce chi revisiona guardando la
scansione. Il tipo di visita si propone dal requisito oculistico del dipendente
(il certificato non riporta la cadenza).

QUELLO CHE NON SI INVENTA

Una visita senza la riga «Visita Medica» riconosciuta, un giudizio che non si
riconosce, una data che manca: si va in revisione. Inventare un tipo significa
inventare una scadenza.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from django.db import transaction

from .referti_parsing import PERIODICITA_NOTE, normalizza

logger = logging.getLogger(__name__)

__all__ = [
    "PianoRegistrazione",
    "prepara_registrazione",
    "registra",
    "ErroreRegistrazione",
    "aggiorna_requisiti",
    "collega_referto_a_visita",
    "tipo_oculistico_da_requisiti",
    "tipo_visita_per_riga",
    "tipi_famiglia",
    "e_riga_visita_medica",
]


class ErroreRegistrazione(Exception):
    """Non si può registrare, con un motivo dicibile a una persona."""


@dataclass
class PianoRegistrazione:
    """Cosa verrebbe registrato, prima di registrarlo.

    ``visita_tipo`` è la visita svolta (la riga «Visita Medica»); ``requisiti`` sono
    tutte le righe del protocollo, con il tipo a catalogo se riconosciuto.
    ``ostacoli`` bloccano la registrazione; ``esami_ignoti`` (requisiti non a
    catalogo) no.
    """

    visita_tipo: object = None
    visita_voce: dict | None = None
    requisiti: list = field(default_factory=list)      # [(TipoVisitaMedica | None, voce)]
    esito: str = ""
    divergenze: list[dict] = field(default_factory=list)
    esami_ignoti: list[str] = field(default_factory=list)
    ostacoli: list[str] = field(default_factory=list)

    @property
    def completo(self) -> bool:
        return not self.ostacoli

    @property
    def tipi(self) -> list:
        """Righe del protocollo riconosciute a catalogo: [(tipo, voce)]."""
        return [(t, v) for t, v in self.requisiti if t is not None]


def _mappa_esami() -> dict[tuple[str, str], int]:
    """(testo normalizzato dell'esame, periodicità) → id del tipo di visita.

    La periodicità vuota è il ripiego: vale quando non esiste una riga per la
    cadenza esatta scritta sul certificato.
    """
    from ..models_sorveglianza import AliasEsameProtocollo

    mappa = {}
    for testo, periodicita, tipo_id in (
        AliasEsameProtocollo.objects.filter(attivo=True)
        .values_list("testo", "periodicita", "tipo_id")
    ):
        mappa[(normalizza(testo), (periodicita or "").lower())] = tipo_id
    return mappa


def _mappa_esiti() -> dict[str, str]:
    """Testo normalizzato del giudizio → valore di esito."""
    from ..models_sorveglianza import AliasEsitoIdoneita

    return {
        normalizza(testo): esito
        for testo, esito in
        AliasEsitoIdoneita.objects.filter(attivo=True).values_list("testo", "esito")
    }


# Solo gli strascichi osservati davvero: numeri (settimane) e i pochi caratteri del
# riquadro letti come lettere. Non «qualsiasi lettera»: «Epatite B» deve restare tale.
_SPORCO_FINALE_ESAME = re.compile(r"^(.*\S)\s+(?:\d{1,3}|F\d?|FI|I)$")

# La riga della visita svolta: «Visita Medica», «Vis. medica», «Visita medica periodica».
_RIGA_VISITA_MEDICA = re.compile(r"^VIS(?:ITA)?\s+MEDICA\b")


def ripulisci_esame(testo: str) -> str:
    """Il nome dell'esame senza gli strascichi che l'OCR gli attacca in coda.

    Alcuni certificati hanno una colonna in più con la periodicità **in settimane**
    («Visita Medica 52 annuale»): il numero finisce incollato al nome. Si aggiungono
    lettere isolate lette dai bordi della tabella («F1», «i») e virgolette spurie.
    Serve solo come **secondo tentativo** dopo il testo esatto: un alias già
    registrato col numero continua a valere.
    """
    pulito = normalizza(testo)
    while True:
        m = _SPORCO_FINALE_ESAME.match(pulito)
        if not m:
            return pulito
        pulito = m.group(1)


def ripulisci_giudizio(testo: str) -> str:
    """Il giudizio senza ripetizioni e lettere spurie in coda.

    «IDONEO CON PRESCRIZIONI PRESCRIZIONI» è lo stesso giudizio letto due volte;
    «IDONEO MANSIONE SPECIFICA C» ha un carattere del riquadro in fondo. Un giudizio
    **troncato** o con parole mancanti non si ricostruisce: resta non riconosciuto.
    """
    parole = normalizza(testo).split()
    compatte = [p for i, p in enumerate(parole) if i == 0 or p != parole[i - 1]]
    while len(compatte) > 1 and len(compatte[-1]) == 1:
        compatte.pop()
    return " ".join(compatte)


def e_riga_visita_medica(voce: dict) -> bool:
    """La riga del protocollo che corrisponde alla visita svolta alla data del giudizio."""
    return bool(_RIGA_VISITA_MEDICA.match(ripulisci_esame(voce.get("esame", ""))))


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
    """Traduce quello che si è letto: visita svolta, requisiti, esito.

    Non tocca il database in scrittura e non solleva: descrive.
    """
    from ..models import TipoVisitaMedica

    piano = PianoRegistrazione()

    alias_esami = _mappa_esami()
    per_nome = _tipi_per_nome()
    tipi_cache = {t.id: t for t in TipoVisitaMedica.objects.filter(is_active=True)}

    righe_visita = []
    for voce in (campi.protocollo or []):
        cadenza = (voce.get("periodicita") or "").lower()
        # Prima la riga per la cadenza esatta, poi quella generica, infine il
        # nome a catalogo: la cadenza è ciò che distingue «Visita Medica
        # Annuale» da «Quinquennale», e sbagliarla sposta una scadenza di anni.
        # Tutta la sequenza col testo esatto, poi di nuovo col nome ripulito.
        tipo_id = None
        for chiave in dict.fromkeys((normalizza(voce.get("esame", "")), ripulisci_esame(voce.get("esame", "")))):
            tipo_id = (
                alias_esami.get((chiave, cadenza))
                or alias_esami.get((chiave, ""))
                or per_nome.get(chiave)
            )
            if tipo_id:
                break
        tipo = tipi_cache.get(tipo_id) if tipo_id else None
        piano.requisiti.append((tipo, voce))
        if e_riga_visita_medica(voce):
            righe_visita.append((tipo, voce))
        elif tipo is None:
            piano.esami_ignoti.append(voce.get("esame", ""))

    cadenze_visita = {(v.get("periodicita") or "").lower() for _t, v in righe_visita}
    if not righe_visita:
        piano.ostacoli.append(
            "Nel protocollo sanitario non c'è la riga «Visita Medica»: non si sa quale "
            "visita sia stata svolta."
        )
    elif len(cadenze_visita) > 1:
        piano.ostacoli.append(
            "Più righe «Visita Medica» con cadenze diverse: va scelta a mano."
        )
    else:
        tipo, voce = righe_visita[0]
        piano.visita_voce = voce
        if tipo is None:
            piano.ostacoli.append(
                f"«{voce.get('esame', '')} {voce.get('periodicita', '')}» non è a catalogo: "
                "va mappata negli alias prima di registrare."
            )
        else:
            piano.visita_tipo = tipo
            mesi_certificato = PERIODICITA_NOTE.get((voce.get("periodicita") or "").lower())
            if mesi_certificato and tipo.durata_mesi and mesi_certificato != tipo.durata_mesi:
                piano.divergenze.append({
                    "esame": voce.get("esame", ""),
                    "tipo": tipo.nome,
                    "certificato_mesi": mesi_certificato,
                    "catalogo_mesi": tipo.durata_mesi,
                })

    alias_esiti = _mappa_esiti()
    piano.esito = (
        alias_esiti.get(normalizza(campi.esito_testo or ""), "")
        or alias_esiti.get(ripulisci_giudizio(campi.esito_testo or ""), "")
    )
    if not piano.esito:
        piano.ostacoli.append(f"Giudizio «{campi.esito_testo or '—'}» non riconosciuto.")

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


def _trova_visita_da_associare(*, legacy_id: int, tipo_id: int, data_giudizio, tolleranza: int):
    """La visita già registrata più vicina alla data del certificato, se c'è.

    Candidata solo una ``VisitaMedica`` con **almeno uno slot referto libero**
    (primario o secondario). Una che li ha già entrambi occupati è stata
    prodotta da altri due certificati, non va toccata. Fra più candidate nella
    finestra vince la più vicina alla data letta: è quella con più probabilità
    di essere lo stesso evento.
    """
    from datetime import timedelta

    from django.db.models import Q

    from ..models import VisitaMedica

    if tolleranza <= 0:
        return None

    candidate = list(
        VisitaMedica.objects.filter(
            Q(referto_documento__isnull=True) | Q(referto_documento_secondario__isnull=True),
            legacy_anagrafica_id=legacy_id,
            tipo_id=tipo_id,
            data_svolgimento__gte=data_giudizio - timedelta(days=tolleranza),
            data_svolgimento__lte=data_giudizio + timedelta(days=tolleranza),
        )
    )
    if not candidate:
        return None
    return min(candidate, key=lambda v: abs((v.data_svolgimento - data_giudizio).days))


def _aggancia_documento(visita, documento, utente, nota: str = "") -> bool:
    """Mette ``documento`` nel primo slot referto libero di ``visita``.

    Ritorna ``True`` se agganciato (slot trovato), ``False`` se entrambi gli
    slot (primario e secondario) sono già occupati: due certificati per la
    stessa visita capitano (es. oculistico su 2 fogli), un terzo no.
    """
    campo = None
    if visita.referto_documento_id is None:
        campo = "referto_documento"
    elif visita.referto_documento_secondario_id is None:
        campo = "referto_documento_secondario"
    else:
        return False

    setattr(visita, campo, documento)
    aggiornati = [campo, "updated_by", "updated_at"]
    if nota:
        visita.note = (visita.note + " " + nota).strip() if visita.note else nota
        aggiornati.append("note")
    visita.updated_by = utente
    visita.save(update_fields=aggiornati)
    return True


def _registra_visita(*, legacy_id, tipo, data, esito, documento, note, utente):
    """Una visita: nuova, agganciata a una già presente, o già presente.

    Ritorna ``(stato, visita)`` con stato «creata» / «agganciata» / «presente».
    Stesso dipendente, tipo e data = la stessa visita (magari registrata a mano):
    non se ne crea una seconda, al più le si aggancia il referto (fino a due:
    referto primario e secondario, per i certificati arrivati su più fogli).
    Entro la tolleranza, una visita con uno slot libero è lo stesso evento con
    la data scritta un giorno prima o dopo: la data registrata non si tocca.
    """
    from ..models import VisitaMedica
    from ..models_sorveglianza import RefertoIntakeConfig

    presente = (
        VisitaMedica.objects
        .filter(legacy_anagrafica_id=legacy_id, tipo=tipo, data_svolgimento=data)
        .order_by("pk").first()
    )
    if presente is not None:
        if documento is not None and _aggancia_documento(presente, documento, utente):
            return "agganciata", presente
        return "presente", presente

    tolleranza = RefertoIntakeConfig.load().giorni_tolleranza_associazione
    candidata = _trova_visita_da_associare(
        legacy_id=legacy_id, tipo_id=tipo.id, data_giudizio=data, tolleranza=tolleranza,
    )
    if candidata is not None:
        scarto_giorni = abs((candidata.data_svolgimento - data).days)
        nota = (
            f"Referto agganciato: giudizio del {data:%d/%m/%Y}"
            + (f", {scarto_giorni} giorni dopo la data registrata" if scarto_giorni else "")
            + "."
        )
        if _aggancia_documento(candidata, documento, utente, nota=nota):
            return "agganciata", candidata

    visita = VisitaMedica(
        legacy_anagrafica_id=legacy_id,
        tipo=tipo,
        data_svolgimento=data,
        esito=esito,
        medico_competente="",
        note=note,
        referto_documento=documento,
        created_by=utente,
        updated_by=utente,
    )
    visita.save()  # la scadenza la calcola save() dal catalogo
    return "creata", visita


def aggiorna_requisiti(legacy_id: int, data_certificato, requisiti, riga=None) -> bool:
    """Registra il protocollo del certificato come requisiti del dipendente.

    Ritorna ``True`` se è diventato il protocollo in vigore (certificato non più
    vecchio dell'ultimo registrato), ``False`` se è finito solo nello storico.
    """
    from django.db.models import Max

    from ..models_sorveglianza import RequisitoVisitaDipendente

    ultimo = (
        RequisitoVisitaDipendente.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .aggregate(m=Max("data_certificato"))["m"]
    )
    in_vigore = ultimo is None or data_certificato >= ultimo
    if in_vigore:
        RequisitoVisitaDipendente.objects.filter(
            legacy_anagrafica_id=legacy_id, attivo=True,
        ).update(attivo=False)
    RequisitoVisitaDipendente.objects.bulk_create([
        RequisitoVisitaDipendente(
            legacy_anagrafica_id=legacy_id,
            tipo=tipo,
            esame=(voce.get("esame") or "")[:200],
            periodicita=(voce.get("periodicita") or "")[:20],
            data_certificato=data_certificato,
            riga=riga,
            attivo=in_vigore,
        )
        for tipo, voce in requisiti
    ])
    return in_vigore


def tipo_oculistico_da_requisiti(legacy_id: int, data=None):
    """Il tipo di visita oculistica richiesto al dipendente, dai suoi requisiti.

    Con una data: il requisito del certificato in vigore a quella data (l'ultimo
    non successivo); senza, o se nessuno la precede, il più recente.
    """
    from ..models_sorveglianza import RequisitoVisitaDipendente

    candidati = [
        r for r in (
            RequisitoVisitaDipendente.objects
            .filter(legacy_anagrafica_id=legacy_id, tipo__isnull=False, tipo__is_active=True)
            .select_related("tipo")
        )
        if "OCULIST" in normalizza(r.esame) or "OCULIST" in normalizza(r.tipo.nome)
    ]
    if not candidati:
        return None
    if data is not None:
        precedenti = [r for r in candidati if r.data_certificato <= data]
        if precedenti:
            return max(precedenti, key=lambda r: (r.data_certificato, r.pk)).tipo
    return max(candidati, key=lambda r: (r.data_certificato, r.pk)).tipo


def tipi_famiglia(tipo) -> set[int]:
    """Tipi di visita intercambiabili con ``tipo`` nell'unione manuale di un referto.

    Con ``categoria`` valorizzata, la famiglia è ogni tipo attivo della stessa
    categoria (es. «oculistica annuale» e «biennale» sotto «Oculistica»): il
    dipendente può passare da una periodicità all'altra per cambio mansione, e il
    referto va unito comunque. Senza categoria non c'è gruppo da allargare: la
    famiglia resta il solo tipo, cioè il confronto stretto di prima.
    """
    from ..models import TipoVisitaMedica

    if tipo is None:
        return set()
    if not tipo.categoria:
        return {tipo.pk}
    return set(
        TipoVisitaMedica.objects
        .filter(is_active=True, categoria=tipo.categoria)
        .values_list("id", flat=True)
    )


def tipo_visita_per_riga(riga, *, legacy_id: int | None = None, tipo_visita=None):
    """Tipo visita riconosciuto per una riga, senza registrare nulla.

    Serve anche al flusso manuale «Unisci con altra visita»: il target deve
    appartenere allo stesso dipendente e avere esattamente questo tipo.
    """
    from ..models_sorveglianza import RefertoIntakeRiga
    from .referti_parsing import CampiReferto

    if riga.tipo_referto == RefertoIntakeRiga.TIPO_OCULISTICA:
        return (
            tipo_visita
            or riga.tipo_visita_scelto
            or tipo_oculistico_da_requisiti(
                legacy_id or riga.legacy_anagrafica_id_proposto,
                riga.letto_data_giudizio,
            )
        )
    piano = prepara_registrazione(CampiReferto(
        esito_testo=riga.letto_esito_testo,
        protocollo=list(riga.letto_protocollo or []),
    ))
    return piano.visita_tipo


@transaction.atomic
def collega_referto_a_visita(riga, visita, *, utente=None):
    """Allega il documento della riga a una visita esistente, senza crearne una.

    Il primo referto resta la FK primaria di ``VisitaMedica``; le pagine o i
    documenti successivi sono ``DocumentoDipendente`` riferiti alla stessa
    visita tramite ``oggetto_riferimento_*``. In questo modo nessun originale
    viene sostituito o cancellato e la UI può mostrarli tutti.
    """
    from django.utils import timezone

    from ..models_sorveglianza import RefertoIntakeRiga

    if riga.esito != RefertoIntakeRiga.ESITO_DA_RIVEDERE:
        raise ErroreRegistrazione("Questo referto non è più nella coda di revisione.")
    if visita.legacy_anagrafica_id != riga.legacy_anagrafica_id_proposto:
        raise ErroreRegistrazione("La visita scelta appartiene a un altro dipendente.")

    tipo = tipo_visita_per_riga(riga, legacy_id=visita.legacy_anagrafica_id)
    if tipo is None:
        raise ErroreRegistrazione(
            "Il tipo della pagina non è riconoscibile: non si può unirla in sicurezza."
        )
    if visita.tipo_id not in tipi_famiglia(tipo):
        raise ErroreRegistrazione(
            "La visita scelta non è dello stesso tipo (né della stessa categoria) del referto."
        )

    documento = _archivia_nel_fascicolo(riga, visita.legacy_anagrafica_id, utente)
    if documento is None:
        raise ErroreRegistrazione("Il file del referto non è più disponibile nell'archivio.")
    if documento.legacy_anagrafica_id != visita.legacy_anagrafica_id:
        raise ErroreRegistrazione("Il documento archiviato appartiene a un altro dipendente.")

    documento.oggetto_riferimento_tipo = "anagrafica.visitamedica"
    documento.oggetto_riferimento_id = visita.pk
    documento.descrizione = (
        f"Pagina/referto aggiuntivo per {visita.tipo.nome} "
        f"del {visita.data_svolgimento:%d-%m-%Y}"
    )
    documento.save(update_fields=[
        "oggetto_riferimento_tipo", "oggetto_riferimento_id", "descrizione",
    ])

    if visita.referto_documento_id is None:
        visita.referto_documento = documento
        visita.updated_by = utente
        visita.save(update_fields=["referto_documento", "updated_by", "updated_at"])

    riga.esito = RefertoIntakeRiga.ESITO_OK
    riga.visite_create = 0
    riga.visite_associate = 1
    riga.documento = documento
    riga.confermato_da = utente
    riga.confermato_il = timezone.now()
    riga.messaggio = (
        f"Allegato aggiuntivo unito a {visita.tipo.nome} "
        f"del {visita.data_svolgimento:%d/%m/%Y}; nessuna nuova visita creata."
    )
    riga.save()
    return documento


_MESSAGGI_STATO = {
    "creata": "Visita registrata",
    "agganciata": "Referto agganciato alla visita già presente",
    "presente": "Visita già presente",
}


@transaction.atomic
def registra(riga, *, utente=None, legacy_id: int | None = None,
             data_visita=None, tipo_visita=None, esito_visita: str = ""):
    """Registra la visita del referto (e, per l'idoneità, i requisiti).

    Ritorna la lista delle visite nuove o agganciate (al più una). Atomica: un
    referto registrato a metà — visita senza requisiti o viceversa — è peggio di
    un referto che torna in coda.
    """
    from django.utils import timezone

    from ..models_sorveglianza import RefertoIntakeRiga
    from .referti_parsing import CampiReferto

    legacy_id = legacy_id or riga.legacy_anagrafica_id_proposto
    if not legacy_id:
        raise ErroreRegistrazione("Nessun dipendente scelto per questo referto.")

    if riga.tipo_referto == RefertoIntakeRiga.TIPO_OCULISTICA:
        return _registra_oculistica(
            riga, utente=utente, legacy_id=legacy_id,
            data_visita=data_visita, tipo_visita=tipo_visita, esito_visita=esito_visita,
        )

    data = riga.letto_data_giudizio
    if data is None:
        raise ErroreRegistrazione(
            "Manca la data del giudizio: senza quella la scadenza sarebbe inventata."
        )

    campi = CampiReferto(
        esito_testo=riga.letto_esito_testo,
        protocollo=list(riga.letto_protocollo or []),
    )
    piano = prepara_registrazione(campi)
    if piano.ostacoli:
        raise ErroreRegistrazione(" ".join(piano.ostacoli))

    documento = _archivia_nel_fascicolo(riga, legacy_id, utente)
    stato, visita = _registra_visita(
        legacy_id=legacy_id, tipo=piano.visita_tipo, data=data, esito=piano.esito,
        documento=documento, note=_descrizione_divergenze(piano.divergenze), utente=utente,
    )
    in_vigore = aggiorna_requisiti(legacy_id, data, piano.requisiti, riga)

    riga.legacy_anagrafica_id_proposto = legacy_id
    riga.esito = RefertoIntakeRiga.ESITO_OK
    riga.visite_create = 1 if stato == "creata" else 0
    riga.visite_associate = 1 if stato == "agganciata" else 0
    riga.documento = documento
    riga.divergenze = piano.divergenze
    riga.confermato_da = utente
    riga.confermato_il = timezone.now()
    pezzi = [
        f"{_MESSAGGI_STATO[stato]}: {piano.visita_tipo.nome} del {data:%d/%m/%Y}",
        f"{len(piano.requisiti)} requisiti "
        + ("in vigore" if in_vigore else "nello storico (esiste un certificato più recente)"),
    ]
    if piano.esami_ignoti:
        pezzi.append("requisiti non a catalogo: " + ", ".join(piano.esami_ignoti))
    if piano.divergenze:
        pezzi.append(_descrizione_divergenze(piano.divergenze))
    riga.messaggio = "; ".join(pezzi) + "."
    riga.save()

    return [visita] if stato in ("creata", "agganciata") else []


def _registra_oculistica(riga, *, utente, legacy_id, data_visita, tipo_visita, esito_visita):
    """Certificato oculistico: data, tipo ed esito confermati da chi revisiona."""
    from django.utils import timezone

    from ..models import VisitaMedica
    from ..models_sorveglianza import RefertoIntakeRiga

    data = data_visita or riga.letto_data_giudizio
    if data is None:
        raise ErroreRegistrazione(
            "Certificato oculistico: inserire la data della visita scritta sul certificato."
        )
    if data > timezone.localdate():
        raise ErroreRegistrazione("La data della visita oculistica è nel futuro.")

    tipo = tipo_visita or riga.tipo_visita_scelto or tipo_oculistico_da_requisiti(legacy_id, data)
    if tipo is None:
        raise ErroreRegistrazione(
            "Nessun requisito oculistico per questo dipendente: scegliere il tipo di visita."
        )

    esiti_validi = dict(VisitaMedica.Esito.choices)
    if esito_visita not in esiti_validi:
        raise ErroreRegistrazione("Certificato oculistico: scegliere l'esito della visita.")

    documento = _archivia_nel_fascicolo(riga, legacy_id, utente)
    stato, _visita = _registra_visita(
        legacy_id=legacy_id, tipo=tipo, data=data, esito=esito_visita,
        documento=documento, note="", utente=utente,
    )

    riga.legacy_anagrafica_id_proposto = legacy_id
    riga.letto_data_giudizio = data
    riga.tipo_visita_scelto = tipo
    riga.esito = RefertoIntakeRiga.ESITO_OK
    riga.visite_create = 1 if stato == "creata" else 0
    riga.visite_associate = 1 if stato == "agganciata" else 0
    riga.documento = documento
    riga.confermato_da = utente
    riga.confermato_il = timezone.now()
    riga.messaggio = (
        f"{_MESSAGGI_STATO[stato]}: {tipo.nome} del {data:%d/%m/%Y}, "
        f"esito {esiti_validi[esito_visita]}."
    )
    riga.save()
    return [_visita] if stato in ("creata", "agganciata") else []


def _archivia_nel_fascicolo(riga, legacy_id: int, utente):
    """Il referto nel fascicolo del dipendente, una sola copia.

    Se la riga punta già a un documento (es. referto importato dall'archivio) si
    usa quello. Altrimenti si legge dall'archivio delle scansioni e si crea.
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
    oculistico = getattr(riga, "tipo_referto", "") == "OCULISTICA"
    etichetta = "Certificato visita oculistica" if oculistico else "Certificato di idoneità"
    doc = DocumentoDipendente(
        legacy_anagrafica_id=legacy_id,
        tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        nome_originale=nome,
        tipo_mime="application/pdf",
        dimensione_bytes=len(contenuto),
        descrizione=(
            f"{etichetta} del {riga.letto_data_giudizio:%d-%m-%Y}"
            if riga.letto_data_giudizio else etichetta
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
