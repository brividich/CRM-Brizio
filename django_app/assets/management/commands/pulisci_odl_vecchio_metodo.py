"""Annulla gli OdL periodici rimasti aperti dal vecchio metodo.

Prima del motore a scadenze (occorrenze) gli OdL periodici nascevano dalle regole
(``maintenance_rule``) o dalle vecchie verifiche periodiche. Dopo la pulizia dei
piani molti restano aperti senza piu' nessuna scadenza aperta dietro: in
«Interventi» sembrano lavoro da fare e non lo sono.

Un OdL e' candidato se e' APERTO, di origine periodica e non raccoglie nessuna
scadenza aperta. Fra i candidati:

- *da annullare*: nessun lavoro registrato sopra;
- *da guardare a mano*: iniziato, con giornate, allegati, passi di checklist
  fatti, scadenze gia' eseguite o costi. Non vengono toccati.

Di default e' un DRY-RUN. Scrive solo con ``--applica``, in un'unica transazione.

    python manage.py pulisci_odl_vecchio_metodo --report odl_vecchi.xlsx
    python manage.py pulisci_odl_vecchio_metodo --escludi 389,390 --applica
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from assets.models import MaintenanceOccurrence, WorkOrder, WorkOrderLog

CLOSURE_NOTE = (
    "Annullato dalla pulizia degli OdL del vecchio metodo: nessuna scadenza aperta "
    "collegata, nessun lavoro registrato."
)


@dataclass
class Candidate:
    workorder: WorkOrder
    reason: str
    activity: list[str] = field(default_factory=list)

    @property
    def to_cancel(self) -> bool:
        return not self.activity


def _reason(wo: WorkOrder, occurrence_statuses: set[str]) -> str:
    if wo.maintenance_rule_id:
        return "Generato da una regola del vecchio motore"
    if wo.periodic_verification_id:
        return "Generato da una vecchia verifica periodica"
    if occurrence_statuses:
        return "Le sue scadenze sono state annullate"
    return "Periodico senza scadenze collegate"


def _activity(wo: WorkOrder, occurrence_statuses: set[str]) -> list[str]:
    found = []
    if wo.started_at:
        found.append("iniziato")
    if wo.execution_days.exists():
        found.append("giornate di esecuzione")
    if wo.attachments.exists():
        found.append("allegati")
    if wo.checklist_items.filter(is_done=True).exists():
        found.append("checklist compilata")
    if MaintenanceOccurrence.STATUS_DONE in occurrence_statuses:
        found.append("scadenze gia' eseguite")
    if any(v for v in (wo.cost_eur, wo.labor_cost_eur, wo.materials_cost_eur)) or wo.intervention_duration_minutes:
        found.append("costi o durata")
    return found


def find_candidates(exclude_ids: set[int] | None = None) -> list[Candidate]:
    open_occurrence = MaintenanceOccurrence.objects.filter(
        work_order=OuterRef("pk"), status=MaintenanceOccurrence.STATUS_OPEN
    )
    qs = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, origin=WorkOrder.ORIGIN_PERIODIC)
        .exclude(Exists(open_occurrence))
        .exclude(pk__in=exclude_ids or ())
        .select_related("asset", "assigned_to")
        .order_by("opened_at", "id")
    )
    candidates = []
    for wo in qs:
        statuses = set(wo.occurrences.values_list("status", flat=True))
        candidates.append(Candidate(wo, _reason(wo, statuses), _activity(wo, statuses)))
    return candidates


def cancel(candidates: list[Candidate]) -> int:
    done = 0
    with transaction.atomic():
        for c in candidates:
            if not c.to_cancel:
                continue
            wo = WorkOrder.objects.select_for_update().get(pk=c.workorder.pk)
            if wo.status != WorkOrder.STATUS_OPEN:
                continue
            # update() e non close(): close() fa full_clean e un OdL vecchio con un dato
            # non piu' valido bloccherebbe l'intera pulizia per un annullamento.
            WorkOrder.objects.filter(pk=wo.pk).update(
                status=WorkOrder.STATUS_CANCELED,
                closed_at=timezone.now(),
                resolution=wo.resolution or CLOSURE_NOTE,
            )
            WorkOrderLog.objects.create(work_order=wo, note=f"Intervento annullato. {CLOSURE_NOTE} ({c.reason}.)")
            done += 1
    return done


def write_report(candidates: list[Candidate], path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    ws = book.active
    ws.title = "OdL vecchio metodo"
    ws.append(["OdL", "Asset", "Nome asset", "Titolo", "Aperto il", "Assegnato a", "Motivo", "Esito", "Lavoro registrato"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for c in candidates:
        wo = c.workorder
        ws.append([
            wo.id, wo.asset.asset_tag, wo.asset.name, wo.title,
            timezone.localtime(wo.opened_at).strftime("%d/%m/%Y") if wo.opened_at else "",
            (wo.assigned_to.get_full_name() or wo.assigned_to.get_username()) if wo.assigned_to_id else "",
            c.reason, "da annullare" if c.to_cancel else "da guardare a mano", ", ".join(c.activity),
        ])
    ws.freeze_panes = "A2"
    book.save(path)
    return path


class Command(BaseCommand):
    help = "Annulla gli OdL periodici aperti del vecchio metodo senza scadenze aperte (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--report", help="Scrive l'elenco in un file Excel")
        parser.add_argument("--escludi", default="", help="Numeri di OdL da non toccare, separati da virgola")
        parser.add_argument("--applica", action="store_true", help="Esegue davvero l'annullamento (senza: dry-run)")

    def handle(self, *args, **options):
        try:
            exclude = {int(x) for x in options["escludi"].replace(";", ",").split(",") if x.strip()}
        except ValueError as exc:
            raise CommandError("--escludi vuole numeri di OdL separati da virgola") from exc

        candidates = find_candidates(exclude)
        to_cancel = [c for c in candidates if c.to_cancel]
        manual = [c for c in candidates if not c.to_cancel]
        mode = "APPLICAZIONE" if options["applica"] else "DRY-RUN (nessuna modifica)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Pulizia OdL del vecchio metodo — {mode}"))
        self.stdout.write(f"  OdL periodici aperti senza scadenze aperte: {len(candidates)}")
        self.stdout.write(f"  da annullare: {len(to_cancel)}")
        self.stdout.write(f"  da guardare a mano (lavoro registrato): {len(manual)}")
        if exclude:
            self.stdout.write(f"  esclusi a richiesta: {', '.join(str(i) for i in sorted(exclude))}")

        for title, group in (("Da annullare", to_cancel), ("Da guardare a mano", manual)):
            if not group:
                continue
            self.stdout.write(self.style.WARNING(f"\n{title} ({len(group)}):"))
            for c in group:
                wo = c.workorder
                extra = f" [{', '.join(c.activity)}]" if c.activity else ""
                self.stdout.write(
                    f"  #{wo.id} {timezone.localtime(wo.opened_at):%d/%m/%Y} {wo.asset.asset_tag} — {wo.title} · {c.reason}{extra}"
                )

        if options.get("report"):
            path = write_report(candidates, options["report"])
            self.stdout.write(self.style.SUCCESS(f"\nReport: {path}"))

        if not options["applica"]:
            self.stdout.write(self.style.NOTICE("\nDry-run: nessuna modifica. Rilancia con --applica per annullare."))
            return
        done = cancel(candidates)
        self.stdout.write(self.style.SUCCESS(f"\nAnnullati: {done}"))
