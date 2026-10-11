"""Versioni formali dei corsi online (prompt 05, fase 2).

Ogni versione (``TrainingCourseVersion``) porta l'**impronta** dei contenuti
(slide, moduli, domande e risposte) e la loro fotografia. Regola:

- un corso in **bozza** si modifica liberamente: niente versioni;
- alla **pubblicazione** si fissa la versione corrente (la prima, o
  l'aggiornamento di quella senza completamenti);
- una modifica a un corso **pubblicato** che cambia l'impronta:
  - se qualcuno ha già completato la versione corrente → **nuova versione**
    (1.0 → 1.1), e il registro di chi ha completato resta legato alla vecchia;
  - altrimenti si aggiorna la versione corrente (nessuna raffica di versioni
    mentre l'autore sistema il corso prima che qualcuno lo completi).

Chi ha completato una versione precedente: lo decide la regola FAD del corso
(``el_nuova_versione``): restano validi, oppure si apre un nuovo ciclo con
scadenza (``giorni_entro_default``) e notifica.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def contenuti(corso) -> dict:
    """Fotografia dei contenuti che il discente vede (ordine deterministico)."""
    moduli = {m.pk: m.titolo for m in corso.moduli_elearning.all()}
    slide = [{
        "id": s.pk, "ordine": s.ordine, "titolo": s.titolo, "tipo": s.tipo, "contenuto": s.contenuto,
        "immagine": s.immagine.name if s.immagine else "", "video": s.video.name if s.video else "",
        "durata_minima": s.durata_minima_secondi, "modulo": moduli.get(s.modulo_id, ""),
    } for s in corso.slides.filter(is_active=True).order_by("ordine", "pk")]
    domande = [{
        "id": d.pk, "testo": d.testo, "tipo": d.tipo,
        "opzioni": [[o.testo, o.corretta] for o in d.opzioni.all().order_by("ordine", "pk")],
    } for d in corso.quiz_domande.filter(is_active=True).prefetch_related("opzioni").order_by("ordine", "pk")]
    return {"slide": slide, "domande": domande}


def impronta(foto: dict) -> str:
    return hashlib.sha256(json.dumps(foto, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prossima_etichetta(etichetta: str) -> str:
    """«1.0» → «1.1»; «2» → «2.1»; etichette non numeriche → «<etichetta>.1»."""
    pezzi = (etichetta or "1.0").strip().split(".")
    if len(pezzi) >= 2 and pezzi[-1].isdigit():
        return ".".join(pezzi[:-1] + [str(int(pezzi[-1]) + 1)])
    return f"{etichetta or '1'}.1"


def versione_corrente(corso):
    from ..models_formazione import TrainingCourseVersion
    return TrainingCourseVersion.objects.filter(corso=corso, version_label=corso.versione).first()


def completamenti_della_versione(corso, etichetta: str) -> int:
    from ..models_formazione import TrainingEmployeeRecord
    return TrainingEmployeeRecord.objects.filter(
        corso=corso, course_version_snapshot=etichetta, completamento_elearning__isnull=False).count()


@dataclass
class Esito:
    nuova: bool = False
    etichetta: str = ""
    riassegnati: int = 0


def registra(corso, *, user=None, motivo: str = "", alla_pubblicazione: bool = False) -> Esito:
    """Allinea la versione del corso ai contenuti attuali (vedi docstring del modulo)."""
    from ..models_formazione import TrainingCourse, TrainingCourseVersion
    from .elearning_fruizione import corso_pubblicato

    if not corso.is_elearning or not (alla_pubblicazione or corso_pubblicato(corso)):
        return Esito()
    with transaction.atomic():
        corso = TrainingCourse.objects.select_for_update().get(pk=corso.pk)
        foto = contenuti(corso)
        firma = impronta(foto)
        attuale = versione_corrente(corso)
        if attuale is not None and attuale.impronta == firma:
            return Esito(etichetta=attuale.version_label)
        dati = {"titolo_snapshot": corso.titolo[:300], "durata_ore_snapshot": corso.durata_ore_teorica,
                "validita_mesi_snapshot": corso.validita_mesi, "impronta": firma, "contenuti_json": foto,
                "revised_by": user if getattr(user, "is_authenticated", False) else None}
        if attuale is None or not attuale.impronta or not completamenti_della_versione(corso, attuale.version_label):
            # Prima versione, o versione ancora senza completamenti: si aggiorna lì.
            if attuale is None:
                TrainingCourseVersion.objects.create(
                    corso=corso, version_label=corso.versione, data_inizio_validita=timezone.localdate(),
                    note=(motivo or "Prima pubblicazione")[:2000], **dati)
            else:
                for campo, valore in dati.items():
                    setattr(attuale, campo, valore)
                attuale.save()
            return Esito(etichetta=corso.versione)
        etichetta = prossima_etichetta(corso.versione)
        # L'etichetta sta in 10 caratteri: si controlla quella vera, mai una troncata.
        while len(etichetta) <= 10 and TrainingCourseVersion.objects.filter(
                corso=corso, version_label=etichetta).exists():
            etichetta = prossima_etichetta(etichetta)
        if len(etichetta) > 10:
            raise RuntimeError(f"Etichetta di versione oltre 10 caratteri per il corso {corso.pk}: "
                               "rinomina la versione del corso.")
        oggi = timezone.localdate()
        attuale.data_fine_validita = oggi
        attuale.save(update_fields=["data_fine_validita"])
        TrainingCourseVersion.objects.create(
            corso=corso, version_label=etichetta[:10], data_inizio_validita=oggi,
            note=(motivo or "Contenuti modificati dopo la pubblicazione")[:2000], **dati)
        corso.versione = etichetta[:10]
        corso.save(update_fields=["versione", "updated_at"])
    # La riassegnazione (regola RIASSEGNA) la fa il job notturno: l'autore ha il
    # giorno per finire le modifiche, che intanto aggiornano questa versione.
    return Esito(nuova=True, etichetta=etichetta, riassegnati=0)


def fissa_e_riassegna() -> dict:
    """Job notturno: versione di base per i corsi pubblicati che non l'hanno (deploy)
    e nuovo ciclo per chi ha completato una versione precedente (regola RIASSEGNA)."""
    from .elearning_fruizione import corsi_pubblicati

    esito = {"fissate": 0, "riassegnati": 0}
    for corso in corsi_pubblicati():
        try:
            if versione_corrente(corso) is None:
                registra(corso, motivo="Versione registrata all'attivazione del versionamento",
                         alla_pubblicazione=True)
                esito["fissate"] += 1
            elif _regola_riassegna(corso):
                with transaction.atomic():
                    esito["riassegnati"] += _riassegna(corso)
        except Exception:
            logger.exception("Versioni e-learning: corso %s non allineato", corso.pk)
    return esito


def _regola_riassegna(corso) -> bool:
    from .elearning_regole import regola_corso
    return regola_corso(corso).nuova_versione == "RIASSEGNA"


def _riassegna(corso) -> int:
    """Nuovo ciclo per chi ha completato (ultimo ciclo) una versione precedente."""
    from ..models_formazione import ElearningConfig, TrainingAssignment, TrainingElearningEnrollment
    from .elearning_assegnazioni import _notifica
    from .elearning_fruizione import ciclo_corrente
    from .organigramma_albero import cessati_legacy_ids

    entro = timezone.localdate() + timedelta(days=int(ElearningConfig.get_instance().giorni_entro_default or 30))
    cessati = cessati_legacy_ids()
    ultimi = {}
    for e in (TrainingElearningEnrollment.objects.filter(corso=corso, stato="COMPLETATO")
              .select_related("record_completamento").order_by("ciclo")):
        ultimi[e.legacy_anagrafica_id] = e
    n = 0
    for lid, e in ultimi.items():
        if lid in cessati or e.record_completamento is None:
            continue
        if e.record_completamento.course_version_snapshot == corso.versione:
            continue
        if ciclo_corrente(corso, lid) > e.ciclo:
            continue  # c'è già un ciclo successivo aperto
        try:
            with transaction.atomic():
                _a, creata = TrainingAssignment.objects.get_or_create(
                    corso=corso, legacy_anagrafica_id=lid, ciclo=e.ciclo + 1,
                    defaults={"due_date": entro, "note": f"Nuova versione {corso.versione} del corso"})
        except IntegrityError:
            creata = False
        if creata:
            n += 1
            transaction.on_commit(lambda lid=lid: _notifica(corso.pk, lid))
    return n
