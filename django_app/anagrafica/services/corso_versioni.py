"""Versioni automatiche dei corsi d'aula.

Stessa regola delle versioni e-learning (``elearning_versioni``), applicata a
ciò che definisce un corso in aula: titolo, durata, validità, qualifica
rilasciata, categoria di rischio e programma didattico.

- alla creazione si fissa la prima versione (``corso.versione``, di norma 1.0);
- a ogni salvataggio che cambia uno di quei dati:
  - se qualcuno ha già un completamento registrato sulla versione corrente →
    **nuova versione** (1.0 → 1.1): la vecchia si chiude con la data di oggi e
    i completamenti restano legati a quella che hanno frequentato;
  - altrimenti si aggiorna la versione corrente (chi sta ancora sistemando il
    corso non genera una raffica di versioni);
- la nota della versione elenca cosa è cambiato, in italiano.

I corsi e-learning hanno il loro versionamento sui contenuti (slide e quiz):
qui si saltano.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Etichette leggibili per la nota della versione.
_ETICHETTE = {
    "titolo": "titolo",
    "durata_ore": "durata",
    "validita_mesi": "validità",
    "qualifica": "qualifica rilasciata",
    "categoria": "categoria di rischio",
    "programma": "programma didattico",
}


def fotografia(corso) -> dict:
    """Ciò che definisce il corso, in forma confrontabile (ordine deterministico)."""
    programma = [
        {"argomento": a.argomento, "ore": str(a.ore_previste or ""), "riferimento": a.riferimento or ""}
        for a in corso.programma.all().order_by("ordine", "pk")
    ]
    return {
        "titolo": corso.titolo or "",
        "durata_ore": str(corso.durata_ore_teorica or ""),
        "validita_mesi": corso.validita_mesi or 0,
        "qualifica": corso.qualifica.nome if corso.qualifica_id else "",
        "categoria": corso.categoria.nome if corso.categoria_id else "",
        "programma": programma,
    }


def impronta(foto: dict) -> str:
    return hashlib.sha256(json.dumps(foto, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _descrivi(prima: dict, dopo: dict) -> str:
    """«Durata 8 → 12 h; validità 60 → 36 mesi; programma didattico» (vuoto se nulla)."""
    parti = []
    for chiave, etichetta in _ETICHETTE.items():
        a, b = prima.get(chiave), dopo.get(chiave)
        if a == b:
            continue
        if chiave == "programma":
            parti.append(f"{etichetta} ({len(a or [])} → {len(b or [])} argomenti)")
        elif chiave == "durata_ore":
            parti.append(f"{etichetta} {a or '—'} → {b or '—'} h")
        elif chiave == "validita_mesi":
            parti.append(f"{etichetta} {a or 'una tantum'} → {b or 'una tantum'}" + (" mesi" if b else ""))
        else:
            parti.append(f"{etichetta} «{a or '—'}» → «{b or '—'}»")
    testo = "; ".join(parti)
    return testo[:1].upper() + testo[1:] if testo else ""


def _completamenti(corso, etichetta: str) -> int:
    from ..models_formazione import TrainingEmployeeRecord

    return TrainingEmployeeRecord.objects.filter(corso=corso, course_version_snapshot=etichetta).count()


def _prossima(etichetta: str) -> str:
    from .elearning_versioni import prossima_etichetta

    return prossima_etichetta(etichetta)


@dataclass
class Esito:
    nuova: bool = False
    aggiornata: bool = False
    etichetta: str = ""
    nota: str = ""


def registra(corso, *, user=None) -> Esito:
    """Allinea la versione del corso ai suoi dati attuali (vedi docstring del modulo)."""
    from ..models_formazione import TrainingCourse, TrainingCourseVersion

    if corso.is_elearning:
        return Esito()
    with transaction.atomic():
        corso = (
            TrainingCourse.objects.select_for_update()
            .select_related("qualifica", "categoria")
            .get(pk=corso.pk)
        )
        foto = fotografia(corso)
        firma = impronta(foto)
        autore = user if getattr(user, "is_authenticated", False) else None
        attuale = TrainingCourseVersion.objects.filter(corso=corso, version_label=corso.versione).first()
        if attuale is not None and attuale.impronta == firma:
            return Esito(etichetta=attuale.version_label)
        dati = {
            "titolo_snapshot": (corso.titolo or "")[:300],
            "durata_ore_snapshot": corso.durata_ore_teorica,
            "validita_mesi_snapshot": corso.validita_mesi,
            "impronta": firma,
            "contenuti_json": foto,
            "revised_by": autore,
        }
        oggi = timezone.localdate()
        if attuale is None:
            TrainingCourseVersion.objects.create(
                corso=corso, version_label=corso.versione, data_inizio_validita=oggi,
                note="Prima versione del corso", **dati,
            )
            return Esito(nuova=True, etichetta=corso.versione, nota="Prima versione del corso")
        nota = _descrivi(attuale.contenuti_json or {}, foto) if attuale.impronta else "Dati del corso fissati"
        if not attuale.impronta or not _completamenti(corso, attuale.version_label):
            # Nessuno l'ha ancora frequentata: si corregge la versione corrente.
            for campo, valore in dati.items():
                setattr(attuale, campo, valore)
            if nota:
                attuale.note = (f"{attuale.note}\n{oggi:%d-%m-%Y}: {nota}" if attuale.note else nota)[:2000]
            attuale.save()
            return Esito(aggiornata=True, etichetta=attuale.version_label, nota=nota)
        etichetta = _prossima(corso.versione)
        while len(etichetta) <= 10 and TrainingCourseVersion.objects.filter(corso=corso, version_label=etichetta).exists():
            etichetta = _prossima(etichetta)
        if len(etichetta) > 10:
            logger.warning("Versione oltre 10 caratteri per il corso %s: versione non registrata", corso.pk)
            return Esito(etichetta=corso.versione)
        attuale.data_fine_validita = oggi
        attuale.save(update_fields=["data_fine_validita"])
        TrainingCourseVersion.objects.create(
            corso=corso, version_label=etichetta, data_inizio_validita=oggi, note=nota[:2000], **dati,
        )
        corso.versione = etichetta
        corso.save(update_fields=["versione", "updated_at"])
    return Esito(nuova=True, etichetta=etichetta, nota=nota)


def registra_con_messaggio(request, corso) -> None:
    """``registra`` + messaggio in pagina quando nasce una versione nuova. Mai bloccante."""
    from django.contrib import messages

    try:
        esito = registra(corso, user=request.user)
    except Exception:
        logger.exception("Versione automatica non registrata per il corso %s", getattr(corso, "pk", None))
        return
    if esito.nuova and esito.nota and esito.nota != "Prima versione del corso":
        messages.info(
            request,
            f"Nuova versione {esito.etichetta} del corso: {esito.nota}. "
            "Chi ha già completato resta registrato sulla versione che ha frequentato.",
        )
