"""Back-fill dei legami qualifica ↔ corso ↔ completamento (competency management).

Collega i record creati "in parallelo" (es. da ``import_asr``) secondo il modello
in cui la **qualifica è l'àncora**:

1. ``TrainingCourse.qualifica`` → ``TipoQualifica`` quando il titolo del corso
   coincide (normalizzato) con il nome della qualifica (match 1:1, conservativo).
2. ``DipendenteQualifica.record_formazione`` → ``TrainingEmployeeRecord`` per lo
   stesso dipendente, sui corsi collegati alla qualifica e con stessa data di
   conseguimento/completamento.

DRY-RUN di default: nessuna scrittura senza ``--commit``. Idempotente. Output
anonimo (solo conteggi; con ``--verbose`` i titoli corso ambigui/non legati).
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction


def _norm(value) -> str:
    return " ".join(str(value or "").strip().casefold().split())


class Command(BaseCommand):
    help = "Collega corsi↔qualifiche e completamenti↔qualifiche dipendente (back-fill)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Scrive su DB (default dry-run).")

    def handle(self, *args, **opt):
        from anagrafica.models import TipoQualifica, DipendenteQualifica
        from anagrafica.models_formazione import TrainingCourse, TrainingEmployeeRecord

        commit = bool(opt["commit"])
        verbose = opt["verbosity"] >= 2

        # Indice qualifiche per nome normalizzato.
        by_nome: dict[str, list] = defaultdict(list)
        for t in TipoQualifica.objects.all():
            by_nome[_norm(t.nome)].append(t)

        # ---- Pass 1: TrainingCourse.qualifica ------------------------------
        course_to_tipo: dict[int, int] = {}
        linked_courses = ambiguous = nomatch = 0
        ambigui_titoli: list[str] = []
        nolink_titoli: list[str] = []

        for c in TrainingCourse.objects.filter(qualifica__isnull=False).values_list("id", "qualifica_id"):
            course_to_tipo[c[0]] = c[1]  # già collegati

        for c in TrainingCourse.objects.filter(qualifica__isnull=True):
            cand = by_nome.get(_norm(c.titolo), [])
            if len(cand) == 1:
                course_to_tipo[c.id] = cand[0].id
                linked_courses += 1
                if commit:
                    c.qualifica = cand[0]
                    c.save(update_fields=["qualifica"])
            elif len(cand) > 1:
                ambiguous += 1
                ambigui_titoli.append(c.titolo)
            else:
                nomatch += 1
                nolink_titoli.append(c.titolo)

        # corsi per qualifica (incl. proposti, così il pass 2 vale anche in dry-run)
        courses_per_tipo: dict[int, list[int]] = defaultdict(list)
        for cid, tid in course_to_tipo.items():
            courses_per_tipo[tid].append(cid)

        # ---- Pass 2: DipendenteQualifica.record_formazione -----------------
        linked_records = rec_nomatch = 0
        for dq in DipendenteQualifica.objects.filter(record_formazione__isnull=True):
            cids = courses_per_tipo.get(dq.tipo_id)
            if not cids:
                continue
            rec_qs = TrainingEmployeeRecord.objects.filter(
                legacy_anagrafica_id=dq.legacy_anagrafica_id, corso_id__in=cids
            )
            if dq.data_conseguimento:
                rec_qs = rec_qs.filter(data_completamento=dq.data_conseguimento)
            rec = rec_qs.order_by("-data_completamento", "-id").first()
            if rec is None:
                rec_nomatch += 1
                continue
            linked_records += 1
            if commit:
                dq.record_formazione = rec
                dq.save(update_fields=["record_formazione"])

        mode = "COMMIT" if commit else "DRY-RUN (nessuna scrittura)"
        self.stdout.write(self.style.WARNING(f"== Link qualifiche/corsi - {mode} =="))
        self.stdout.write(self.style.MIGRATE_HEADING("  -- Corso -> Qualifica --"))
        self.stdout.write(f"    Collegati: {linked_courses} | ambigui: {ambiguous} | senza match: {nomatch}")
        self.stdout.write(self.style.MIGRATE_HEADING("  -- Qualifica dipendente -> Completamento --"))
        self.stdout.write(f"    Collegati: {linked_records} | senza completamento corrispondente: {rec_nomatch}")
        if verbose and ambigui_titoli:
            self.stdout.write("  Titoli corso ambigui (più qualifiche con stesso nome): " + "; ".join(sorted(set(ambigui_titoli))))
        if verbose and nolink_titoli:
            self.stdout.write("  Titoli corso senza qualifica corrispondente: " + "; ".join(sorted(set(nolink_titoli))))
        if not commit:
            self.stdout.write(self.style.NOTICE("  Rilancia con --commit per scrivere i collegamenti."))
