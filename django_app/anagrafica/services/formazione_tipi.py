"""Tipi di corso, assegnazione in blocco per piano e accorpamento dei piani doppi.

- il **tipo** raggruppa i corsi (Sicurezza, Normativo…) e alimenta i filtri dell'elenco;
- il **piano** resta il programma o cliente di provenienza: si può assegnare un tipo a tutti
  i corsi di un piano con un clic;
- i **piani doppi** (stesso nome a meno di maiuscole e punteggiatura, o un nome tagliato che è
  l'inizio dell'altro) si accorpano solo su conferma: corsi, regole di obbligo e assegnazioni
  passano al piano scelto, quello vecchio si disattiva. Completamenti e attestati sono legati
  al corso, non al piano, quindi lo storico non cambia.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from django.db import transaction
from django.db.models import Count

from ..models_formazione import (
    TrainingAssignment, TrainingCourse, TrainingCourseType, TrainingPlan, TrainingPlanNonDoppio,
    TrainingRequirementRule,
)


class TipiError(Exception):
    pass


def _norm(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def tipi_con_conteggi():
    """Tipi con il numero di corsi e di corsi obbligatori («obbligatorio» = regola unica del
    catalogo, ``formazione_catalogo.q_obbligatori``: spunta per tutti, mansione, ruolo, processo)."""
    from .formazione_catalogo import q_obbligatori

    obbligatori = Counter(
        TrainingCourse.objects.filter(q_obbligatori(), tipo__isnull=False).values_list("tipo_id", flat=True))
    tipi = list(TrainingCourseType.objects.annotate(n_corsi=Count("corsi", distinct=True)).order_by("ordine", "nome"))
    for t in tipi:
        t.n_obbligatori = obbligatori.get(t.pk, 0)
    return tipi


def piani_con_conteggi() -> list[dict]:
    out = []
    piani = TrainingPlan.objects.filter(is_active=True).annotate(n=Count("corsi")).order_by("nome")
    tipi_per_piano: dict[int, Counter] = {}
    for piano_id, tipo_id in TrainingCourse.objects.values_list("piano_id", "tipo_id"):
        tipi_per_piano.setdefault(piano_id, Counter())[tipo_id] += 1
    nomi_tipo = dict(TrainingCourseType.objects.values_list("pk", "nome"))
    for p in piani:
        conta = tipi_per_piano.get(p.pk, Counter())
        senza = conta.get(None, 0)
        con_tipo = [(t, n) for t, n in conta.most_common() if t]
        out.append({"piano": p, "n": p.n, "senza_tipo": senza,
                    "tipi": [(nomi_tipo.get(t, "?"), n) for t, n in con_tipo],
                    "tipo_unico": con_tipo[0][0] if len(con_tipo) == 1 and not senza else None})
    return out


def assegna_tipo_a_piano(piano, tipo, *, solo_senza_tipo: bool = True) -> int:
    qs = TrainingCourse.objects.filter(piano=piano)
    if solo_senza_tipo:
        qs = qs.filter(tipo__isnull=True)
    return qs.update(tipo=tipo)


def doppioni() -> list[dict]:
    """Coppie di piani attivi che sembrano lo stesso piano (escluse quelle già dichiarate non doppie)."""
    piani = list(TrainingPlan.objects.filter(is_active=True).annotate(n=Count("corsi")))
    esclusi = {tuple(sorted(c)) for c in TrainingPlanNonDoppio.objects.values_list("piano_a_id", "piano_b_id")}
    out, visti = [], set()
    for i, a in enumerate(piani):
        na = _norm(a.nome)
        for b in piani[i + 1:]:
            nb = _norm(b.nome)
            if not na or not nb:
                continue
            corto, lungo = sorted((na, nb), key=len)
            simili = na == nb or (len(corto) >= 12 and lungo.startswith(corto))
            if not simili:
                continue
            coppia = tuple(sorted((a.pk, b.pk)))
            if coppia in esclusi or coppia in visti:
                continue
            visti.add(coppia)
            # Proposta: si tiene il piano col nome più lungo (non tagliato), a parità quello con più corsi.
            tieni, togli = (a, b) if (len(a.nome), a.n) >= (len(b.nome), b.n) else (b, a)
            out.append({"togli": togli, "tieni": tieni})
    return out


def piani_di_prova() -> list:
    return [p for p in TrainingPlan.objects.filter(is_active=True).annotate(n=Count("corsi"))
            if _norm(p.nome) in ("prova", "test", "prove")]


def accorpa(togli: TrainingPlan, tieni: TrainingPlan) -> dict:
    if togli.pk == tieni.pk:
        raise TipiError("Scegli due piani diversi.")
    if not tieni.is_active:
        raise TipiError("Il piano di destinazione è disattivato.")
    with transaction.atomic():
        n_corsi = TrainingCourse.objects.filter(piano=togli).update(piano=tieni)
        n_regole = TrainingRequirementRule.objects.filter(piano=togli).update(piano=tieni)
        n_ass = TrainingAssignment.objects.filter(piano=togli).update(piano=tieni)
        togli.is_active = False
        togli.save(update_fields=["is_active"])
    return {"corsi": n_corsi, "regole": n_regole, "assegnazioni": n_ass}


def segna_non_doppi(a: TrainingPlan, b: TrainingPlan, chi: str = "") -> None:
    x, y = sorted((a, b), key=lambda p: p.pk)
    TrainingPlanNonDoppio.objects.get_or_create(piano_a=x, piano_b=y, defaults={"deciso_da": chi[:160]})
