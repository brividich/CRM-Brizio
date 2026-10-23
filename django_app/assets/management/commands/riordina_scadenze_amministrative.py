"""Riordina il registro delle scadenze amministrative.

Nel registro (``AssetAdministrativeDeadline``) sono finite voci che amministrative
non sono: manutenzioni programmate a calendario (controllo batterie, tagliandi
trimestrali...) inserite come «Scadenza tecnica», spesso come serie di righe una
per data, perche' il registro non aveva una periodicita'. Altre voci copiano un
piano di manutenzione gia' attivo sullo stesso asset (es. «Verifica VTS» accanto
al piano «Verifica Termocoppia Sicurezza - VTS»): la stessa scadenza compare due
volte nello Scadenzario.

Due passi, entrambi senza cancellare nulla:

1. **Manutenzioni → piani.** Le voci di tipo «Scadenza tecnica» (e le voci con lo
   stesso titolo di una di esse) diventano un'applicazione di piano sull'asset:
   piano con la stessa etichetta (riusato se esiste, altrimenti creato), ogni N
   mesi, prima scadenza = la data piu' vicina della serie. La periodicita' si
   ricava dalla distanza fra le date della serie; per i titoli senza serie si
   indica con ``--mesi "Titolo=12"``, altrimenti la voce resta dov'e' e viene
   elencata. Le righe del registro si disattivano con una nota.
2. **Doppioni dei piani.** Le scadenze amministrative attive che hanno la stessa
   sigla (3+ maiuscole, es. VTS, VAP, SAT, TUS) di un piano attivo sullo stesso
   asset si disattivano con una nota: fa fede il piano, che e' quello eseguito.

Le vere scadenze amministrative (revisioni, verifiche periodiche di legge,
certificati) restano nel registro. Di default e' una prova a vuoto; scrive solo
con ``--apply``. Ripetibile: le voci gia' riordinate non sono piu' attive.
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from assets.models import (
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenancePlanAssignment,
)

AUDIT_ACTION = "ASSET_SCADENZA_AMMINISTRATIVA_RIORDINATA"
ACRONYM_RE = re.compile(r"\b[A-Z]{3,}\b")


def _acronyms(text: str) -> set[str]:
    return set(ACRONYM_RE.findall(text or ""))


def _month_gap(a, b) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def _parse_months(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for raw in values or []:
        title, sep, months = (raw or "").rpartition("=")
        if not sep or not title.strip():
            raise CommandError(f"--mesi non valido: {raw!r} (atteso \"Titolo=12\").")
        try:
            value = int(months)
        except ValueError as exc:
            raise CommandError(f"--mesi non valido: {raw!r} (mesi non numerici).") from exc
        if value <= 0:
            raise CommandError(f"--mesi non valido: {raw!r} (mesi > 0).")
        out[title.strip().lower()] = value
    return out


def _series_key(d: AssetAdministrativeDeadline) -> tuple:
    return (d.title.strip().lower(), d.asset_id, d.component_id)


class Command(BaseCommand):
    help = "Sposta nei piani le manutenzioni finite fra le scadenze amministrative e spegne i doppioni (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: solo elenco).")
        parser.add_argument(
            "--mesi",
            action="append",
            default=[],
            metavar="TITOLO=MESI",
            help="Periodicita' per i titoli senza serie, es. --mesi \"Verifica VFC_MOP=12\". Ripetibile.",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        months_override = _parse_months(options.get("mesi") or [])
        today = timezone.localdate()
        mode = "APPLICA" if apply else "PROVA A VUOTO"

        active = list(
            AssetAdministrativeDeadline.objects.filter(is_active=True)
            .select_related("asset")
            .order_by("due_date", "id")
        )

        # --- 1. Manutenzioni -> piani ---------------------------------------
        technical_titles = {
            d.title.strip().lower() for d in active if d.deadline_type == AssetAdministrativeDeadline.TYPE_TECHNICAL
        }
        series: dict[tuple, list[AssetAdministrativeDeadline]] = defaultdict(list)
        for d in active:
            if d.title.strip().lower() in technical_titles:
                series[_series_key(d)].append(d)

        title_gap: dict[str, int] = {}
        for (title, _asset, _comp), rows in series.items():
            dates = sorted({r.due_date for r in rows})
            gaps = [g for g in (_month_gap(a, b) for a, b in zip(dates, dates[1:], strict=False)) if g > 0]
            if gaps:
                title_gap[title] = min(min(gaps), title_gap.get(title, 10**6))

        moves = []
        unknown = []
        for key, rows in sorted(series.items(), key=lambda kv: (kv[0][0], kv[1][0].asset.asset_tag)):
            title = key[0]
            dates = sorted({r.due_date for r in rows})
            gaps = [g for g in (_month_gap(a, b) for a, b in zip(dates, dates[1:], strict=False)) if g > 0]
            months = months_override.get(title) or (min(gaps) if gaps else title_gap.get(title))
            if not months:
                unknown.append(rows)
                continue
            moves.append({"rows": rows, "months": months, "first_due": dates[0]})

        self.stdout.write(f"[{mode}] 1. Manutenzioni da spostare nei piani: {len(moves)} (righe {sum(len(m['rows']) for m in moves)})")
        for m in moves:
            lead = m["rows"][0]
            self.stdout.write(
                f"  {lead.asset.asset_tag} — {lead.title} — ogni {m['months']} mesi dal {m['first_due']:%d/%m/%Y}"
                f" ({len(m['rows'])} righe)"
            )
        if unknown:
            self.stdout.write(self.style.WARNING(
                f"  Senza periodicita' ricavabile (restano nel registro, indicarla con --mesi): {len(unknown)}"
            ))
            for title in sorted({rows[0].title for rows in unknown}):
                n = sum(1 for rows in unknown if rows[0].title == title)
                self.stdout.write(f"    «{title}» su {n} asset")

        # --- 2. Doppioni dei piani -------------------------------------------
        moving_ids = {r.id for m in moves for r in m["rows"]}
        assignments_by_asset: dict[int, list[MaintenancePlanAssignment]] = defaultdict(list)
        for a in (
            MaintenancePlanAssignment.objects.filter(
                is_active=True,
                is_excluded=False,
                plan__is_active=True,
                target_type=MaintenancePlanAssignment.TARGET_ASSET,
            )
            .exclude(plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)
            .select_related("plan")
        ):
            assignments_by_asset[a.asset_id].append(a)
        duplicates = []
        for d in active:
            if d.id in moving_ids:
                continue
            tokens = _acronyms(d.title)
            if not tokens:
                continue
            for a in assignments_by_asset.get(d.asset_id, []):
                if tokens & _acronyms(a.plan.label):
                    duplicates.append((d, a))
                    break
        self.stdout.write(f"[{mode}] 2. Scadenze doppione di un piano attivo: {len(duplicates)}")
        for d, a in duplicates:
            self.stdout.write(
                f"  #{d.id} {d.asset.asset_tag} — {d.title} ({d.due_date:%d/%m/%Y}) = piano «{a.plan.label}»"
            )

        if not apply:
            if moves or duplicates:
                self.stdout.write("Nessuna modifica. Rilanciare con --apply.")
            return

        from core.audit import log_action
        from assets.services.maintenance_domain import generate_occurrences

        def audit(operazione: str, oggetto, **dettagli):
            log_action(
                None,
                AUDIT_ACTION,
                "assets",
                {"operazione": operazione, "comando": "riordina_scadenze_amministrative", **dettagli},
                oggetto=oggetto,
            )

        plans_by_label: dict[str, MaintenanceInterventionTemplate] = {}
        touched_plan_ids: set[int] = set()
        stamp = f"{today:%d/%m/%Y}"
        with transaction.atomic():
            for m in moves:
                lead = m["rows"][0]
                plan = self._plan_for(lead.title, plans_by_label, audit)
                touched_plan_ids.add(plan.id)
                assignment, created = MaintenancePlanAssignment.objects.get_or_create(
                    plan=plan,
                    asset=lead.asset,
                    target_type=MaintenancePlanAssignment.TARGET_ASSET,
                    defaults={
                        "frequency": MaintenancePlanAssignment.FREQ_MONTHS,
                        "interval": m["months"],
                        "first_due_date": m["first_due"],
                        "warning_days": lead.warning_days,
                        "auto_generate": True,
                        "is_active": True,
                    },
                )
                if not created and not assignment.is_active:
                    assignment.frequency = MaintenancePlanAssignment.FREQ_MONTHS
                    assignment.interval = m["months"]
                    assignment.first_due_date = m["first_due"]
                    assignment.warning_days = lead.warning_days
                    assignment.is_excluded = False
                    assignment.auto_generate = True
                    assignment.is_active = True
                    assignment.save()
                ids = ", ".join(f"#{r.id}" for r in m["rows"])
                assignment.notes = (
                    f"{assignment.notes}\n[{stamp}] Dalle scadenze amministrative {ids}.".strip()
                )
                assignment.save(update_fields=["notes", "updated_at"])
                audit(
                    "applicazione_da_scadenza", assignment,
                    assignment_id=assignment.id, plan_id=plan.id, asset_id=lead.asset_id,
                    deadline_ids=[r.id for r in m["rows"]], mesi=m["months"], creata=created,
                )
                for r in m["rows"]:
                    r.is_active = False
                    r.notes = f"{r.notes}\n[{stamp}] Spostata nel piano di manutenzione «{plan.label}».".strip()
                    r.save(update_fields=["is_active", "notes", "updated_at"])
            for d, a in duplicates:
                d.is_active = False
                d.notes = f"{d.notes}\n[{stamp}] Doppione del piano «{a.plan.label}»: fa fede il piano.".strip()
                d.save(update_fields=["is_active", "notes", "updated_at"])
                audit("doppione_spento", d, deadline_id=d.id, asset_id=d.asset_id, plan_id=a.plan_id)

        generated = {"created": 0}
        if touched_plan_ids:
            generated = generate_occurrences(plan_ids=touched_plan_ids)
        self.stdout.write(self.style.SUCCESS(
            f"Fatto: {len(moves)} applicazioni di piano, {sum(len(m['rows']) for m in moves)} righe spostate, "
            f"{len(duplicates)} doppioni spenti, {generated.get('created', 0)} manutenzioni generate."
        ))

    def _plan_for(self, title: str, cache: dict, audit) -> MaintenanceInterventionTemplate:
        key = title.strip().lower()
        if key in cache:
            return cache[key]
        # I vecchi piani amministrativi «copia» non si riusano: le loro occorrenze
        # annullate occupano (piano, asset, scadenza), vincolo unico, e la nuova
        # occorrenza non nascerebbe.
        candidates = [
            p
            for p in MaintenanceInterventionTemplate.objects.exclude(
                maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
            ).order_by("-is_active", "id")
            if (p.label or "").strip().lower() == key
        ]
        plan = candidates[0] if candidates else None
        if plan is None:
            base = f"man-{slugify(title)}"[:70]
            code, n = base, 2
            while MaintenanceInterventionTemplate.objects.filter(code=code).exists():
                code, n = f"{base}-{n}", n + 1
            plan = MaintenanceInterventionTemplate.objects.create(
                code=code,
                label=title.strip()[:120],
                maintenance_type=MaintenanceInterventionTemplate.TYPE_ROUTINE,
                is_active=True,
            )
            audit("piano_creato", plan, plan_id=plan.id)
        elif not plan.is_active:
            plan.is_active = True
            plan.save(update_fields=["is_active", "updated_at"])
            audit("piano_riattivato", plan, plan_id=plan.id)
        cache[key] = plan
        return plan
