"""Fase 1 — Export SANIFICATO dei dati FORMAZIONE (DEV) per import in PROD via loaddata.

Da lanciare su DEV. Produce un JSON pronto per ``loaddata`` su prod:
  - include il grafo ``Training*`` + i cataloghi prod-vuoti ``CategoriaCorso``/``TipoQualifica``
    (in prod queste tabelle sono vuote → i PK vengono preservati senza collisioni);
  - ESCLUDE: ``TrainingDeadline`` (cache derivata, ricalcolata in prod con
    ``refresh_training_deadlines``), ``TrainingExportLog`` (audit), ``TrainingAttachment``
    (allegati/file) e i singleton di configurazione;
  - ANNULLA le FK verso modelli FUORI dal set: ``auth.User`` (created_by/updated_by/…),
    ``DocumentoDipendente``/``CartellaDocumentoDipendente`` (file — che non servono),
    ``Mansione``/``AreaAziendale``/``RuoloOperativo`` (ID diversi tra ambienti); le M2M
    verso fuori-set vengono svuotate. Ogni FK NON-nullable che andrebbe annullata è
    segnalata come ATTENZIONE (bloccherebbe il loaddata).

Il legame col dipendente è ``legacy_anagrafica_id`` (stabile dev↔prod): NON viene toccato.
Le VISITE mediche sono trattate a parte (Fase 2, merge per nome dei tipi visita).

Uso:
    python manage.py migra_formazione_export --out formazione_export.json --settings=config.settings.dev
Poi, su PROD:
    python manage.py loaddata formazione_export.json --settings=config.settings.prod
    python manage.py refresh_training_deadlines --settings=config.settings.prod
"""
import json

from django.apps import apps
from django.core import serializers
from django.core.management.base import BaseCommand

# Ordine = genitori prima (loaddata rispetta l'ordine del file).
IMPORT_SET = [
    # cataloghi prod-vuoti (PK preservati, nessuna collisione)
    "CategoriaCorso", "TipoQualifica",
    # grafo formazione
    "TrainingPlan", "TrainingCourse", "TrainingCourseVersion", "TrainingCompletionRule",
    "TrainingCourseDependency", "TrainingCourseModule", "TrainingRequirementRule",
    "TrainingInstructor", "TrainingAssignment", "TrainingSession", "TrainingLesson",
    "TrainingEnrollment", "TrainingEnrollmentLesson", "TrainingLessonAttendance",
    "TrainingEmployeeRecord", "TrainingCertificate", "TrainingSlide",
    "TrainingQuizQuestion", "TrainingQuizOption", "TrainingElearningEnrollment",
    "TrainingQuizAttempt",
]


class Command(BaseCommand):
    help = "Fase 1: export sanificato Formazione (DEV) pronto per loaddata in PROD."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="formazione_export.json",
                            help="File JSON di output (default: formazione_export.json).")

    def handle(self, *args, **opts):
        set_names = set(IMPORT_SET)
        models = [apps.get_model("anagrafica", n) for n in IMPORT_SET]

        # Introspezione: FK/M2M che puntano FUORI dal set -> da annullare/svuotare.
        null_fk: dict[str, set] = {}
        empty_m2m: dict[str, set] = {}
        warns: list[str] = []
        for M in models:
            label = M._meta.label_lower
            for f in M._meta.get_fields():
                if not f.is_relation or f.related_model is None:
                    continue
                if f.related_model.__name__ in set_names:
                    continue  # FK dentro il set: PK preservati, si tiene
                if (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)) and f.concrete:
                    null_fk.setdefault(label, set()).add(f.name)
                    if not f.null:
                        warns.append(
                            f"{M.__name__}.{f.name} -> {f.related_model.__name__} NON e' nullable: "
                            "se ci sono righe non nulle il loaddata fallira'"
                        )
                elif getattr(f, "many_to_many", False) and not f.auto_created:
                    empty_m2m.setdefault(label, set()).add(f.name)

        # Serializza tutte le righe nell'ordine IMPORT_SET.
        all_objs = []
        counts: dict[str, int] = {}
        for M in models:
            qs = list(M.objects.all())
            counts[M.__name__] = len(qs)
            all_objs.extend(qs)
        data = json.loads(serializers.serialize(
            "json", all_objs, use_natural_foreign_keys=False, use_natural_primary_keys=False))

        nulled = emptied = 0
        for obj in data:
            label = obj["model"]
            for fn in null_fk.get(label, ()):
                if obj["fields"].get(fn) is not None:
                    obj["fields"][fn] = None
                    nulled += 1
            for fn in empty_m2m.get(label, ()):
                if obj["fields"].get(fn):
                    obj["fields"][fn] = []
                    emptied += 1

        with open(opts["out"], "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)

        self.stdout.write("=== EXPORT FORMAZIONE (Fase 1) — sanificato ===")
        for n, c in counts.items():
            if c:
                self.stdout.write(f"  {n:<28} {c}")
        self.stdout.write(f"Righe serializzate: {len(data)} | FK fuori-set annullate: {nulled} | "
                          f"M2M svuotate: {emptied}")
        if warns:
            for w in warns:
                self.stdout.write(self.style.WARNING("  ATTENZIONE: " + w))
        else:
            self.stdout.write(self.style.SUCCESS("  Nessuna FK non-nullable da annullare (ok)."))
        self.stdout.write(self.style.SUCCESS(f"Scritto: {opts['out']}"))
        self.stdout.write("ESCLUSI: TrainingDeadline (ricalcola in prod), TrainingExportLog, "
                          "TrainingAttachment, singleton config.")
        self.stdout.write("PROD:  loaddata <file>  ->  refresh_training_deadlines")
