"""Verifica di autenticità degli attestati di formazione (prompt 05, fase 2).

Ogni attestato porta un **codice di verifica** casuale (12 caratteri, alfabeto
senza simboli ambigui, ~59 bit: non si indovina e non si ricava dal protocollo)
stampato in chiaro e come QR. La pagina di verifica mostra solo il minimo:
nome, corso, data, scadenza, protocollo ed esito (valido, scaduto, non valido).
Nessun altro dato personale.

Per i completamenti e-learning la verifica ricalcola anche l'impronta SHA-256
dei requisiti registrati: se la riga del registro è stata alterata, l'attestato
risulta **non verificabile**.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LUNGHEZZA = 12

VALIDO, SCADUTO, NON_VALIDO, SCONOSCIUTO, ALTERATO = "VALIDO", "SCADUTO", "NON_VALIDO", "SCONOSCIUTO", "ALTERATO"


def _nuovo_codice() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(LUNGHEZZA))


def normalizza(codice: str) -> str:
    """Maiuscole, senza trattini né spazi (l'alfabeto non ha 0/O, 1/I/L da confondere)."""
    return "".join(c for c in str(codice or "").upper() if c.isalnum())[:40]


def formatta(codice: str) -> str:
    return "-".join(codice[i:i + 4] for i in range(0, len(codice), 4)) if codice else ""


def firma(record) -> str:
    """HMAC dei dati che la pagina di verifica mostra (chiave derivata da SECRET_KEY)."""
    chiave = hashlib.sha256(("attestato-verifica:" + settings.SECRET_KEY).encode()).digest()
    dati = "|".join(str(x) for x in (
        record.pk, record.codice_verifica, record.legacy_anagrafica_id, record.corso_id,
        record.data_completamento, record.data_scadenza, record.idoneo, record.course_title_snapshot))
    return hmac.new(chiave, dati.encode(), hashlib.sha256).hexdigest()


def assegna_codice_verifica(record) -> str:
    """Codice del record, assegnato se manca (idempotente, sicuro in concorrenza)."""
    from ..models_formazione import TrainingEmployeeRecord

    if record.codice_verifica:
        return record.codice_verifica
    for _ in range(8):
        codice = _nuovo_codice()
        record.codice_verifica = codice
        try:
            with transaction.atomic():
                aggiornate = (TrainingEmployeeRecord.objects.filter(pk=record.pk, codice_verifica="")
                              .update(codice_verifica=codice, firma_verifica=firma(record)))
        except IntegrityError:
            record.codice_verifica = ""
            continue  # collisione (improbabilissima): si ritenta
        if not aggiornate:  # assegnato nel frattempo da un'altra richiesta
            record.codice_verifica, record.firma_verifica = (TrainingEmployeeRecord.objects
                                                             .values_list("codice_verifica", "firma_verifica")
                                                             .get(pk=record.pk))
            return record.codice_verifica
        record.firma_verifica = firma(record)
        return codice
    raise RuntimeError("Impossibile assegnare un codice di verifica univoco.")


def url_verifica(codice: str, request=None) -> str:
    """URL assoluto della pagina di verifica (vuoto se non determinabile)."""
    percorso = reverse("anagrafica:formazione_verifica_attestato_codice", args=[formatta(codice)])
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if base:
        return base + percorso
    if request is not None:
        return request.build_absolute_uri(percorso)
    return ""


@dataclass
class Esito:
    stato: str
    codice: str = ""
    nome: str = ""
    corso: str = ""
    data_completamento: date | None = None
    data_scadenza: date | None = None
    protocollo: str = ""

    @property
    def valido(self) -> bool:
        return self.stato == VALIDO


def _impronta_integra(record) -> bool | None:
    """True/False per un completamento e-learning; None se non è e-learning."""
    from ..models_elearning import TrainingElearningCompletamento

    comp = TrainingElearningCompletamento.objects.filter(record=record).only("verifica_json", "sha256").first()
    if comp is None:
        return None
    canonico = json.dumps(comp.verifica_json, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonico.encode()).hexdigest() == comp.sha256


def _nome(legacy_id: int) -> str:
    from core import naming
    from core.legacy_models import AnagraficaDipendente

    dip = AnagraficaDipendente.objects.filter(pk=legacy_id).values("nome", "cognome").first()
    return naming.nome_completo(dip["nome"], dip["cognome"]) if dip else ""


def verifica(codice: str, *, oggi: date | None = None) -> Esito:
    from ..models_formazione import TrainingEmployeeRecord

    codice = normalizza(codice)
    if len(codice) != LUNGHEZZA:
        return Esito(SCONOSCIUTO, codice)
    record = (TrainingEmployeeRecord.objects.select_related("corso")
              .filter(codice_verifica=codice).first())
    if record is None:
        return Esito(SCONOSCIUTO, codice)
    oggi = oggi or timezone.localdate()
    if not hmac.compare_digest(record.firma_verifica or "", firma(record)) or _impronta_integra(record) is False:
        stato = ALTERATO
    elif not record.idoneo:
        stato = NON_VALIDO
    elif record.data_scadenza and record.data_scadenza < oggi:
        stato = SCADUTO
    else:
        stato = VALIDO
    return Esito(
        stato=stato, codice=codice, nome=_nome(record.legacy_anagrafica_id),
        corso=record.course_title_snapshot or (record.corso.titolo if record.corso_id else ""),
        data_completamento=record.data_completamento, data_scadenza=record.data_scadenza,
        protocollo=record.numero_protocollo,
    )
