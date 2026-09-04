"""Test del nuovo dominio manutenzione (Piano -> Applicazione -> Occorrenza -> OdL).

Coprono i casi elencati nella specifica di refactoring: i due ancoraggi della
periodicita', le ricorrenze di calendario, il preavviso, l'idempotenza dello
scheduler, gli OdL massivi (rimozione asset, completamento parziale, giornate),
l'allegato obbligatorio, la precedenza asset/gruppo e i conflitti.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetGroup,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import maintenance_domain as domain
from assets.services.recurrence import (
    ANCHOR_FIXED_CALENDAR,
    ANCHOR_FROM_COMPLETION,
    add_recurrence,
    compute_next_due,
    describe_recurrence,
)

User = get_user_model()


class RecurrenceEngineTests(TestCase):
    """Il motore di periodicita' e' solo temporale: niente ore, km o cicli."""

    def _spec(self, **kwargs):
        base = {"frequency": "DAYS", "interval": 1, "weekday": None, "week_of_month": None, "day_of_month": None, "month_of_year": None}
        base.update(kwargs)
        return base

    def test_ordinaria_riparte_dalla_data_di_esecuzione(self):
        # due 10/09, eseguita 20/09, mensile => prossima 20/10
        spec = self._spec(frequency="MONTHS", interval=1)
        self.assertEqual(
            compute_next_due(
                spec,
                anchor=ANCHOR_FROM_COMPLETION,
                previous_due=date(2026, 9, 10),
                completion_date=date(2026, 9, 20),
            ),
            date(2026, 10, 20),
        )

    def test_amministrativa_resta_ancorata_alla_scadenza_teorica(self):
        # due 10/09, eseguita 20/09, mensile => prossima 10/10 (il ritardo non sposta il calendario)
        spec = self._spec(frequency="MONTHS", interval=1)
        self.assertEqual(
            compute_next_due(
                spec,
                anchor=ANCHOR_FIXED_CALENDAR,
                previous_due=date(2026, 9, 10),
                completion_date=date(2026, 9, 20),
            ),
            date(2026, 10, 10),
        )

    def test_primo_lunedi_del_mese_su_mesi_che_iniziano_diversamente(self):
        spec = self._spec(frequency="MONTHS", interval=1, weekday=0, week_of_month=1)
        # 01/10/2026 e' un giovedi -> primo lunedi 05/10; novembre inizia di domenica -> 02/11
        self.assertEqual(add_recurrence(spec, date(2026, 9, 7)), date(2026, 10, 5))
        self.assertEqual(add_recurrence(spec, date(2026, 10, 5)), date(2026, 11, 2))

    def test_ultimo_giorno_del_mese_gestisce_i_mesi_corti(self):
        spec = self._spec(frequency="MONTHS", interval=1, day_of_month=-1)
        self.assertEqual(add_recurrence(spec, date(2027, 1, 31)), date(2027, 2, 28))

    def test_giorno_31_scivola_all_ultimo_giorno_disponibile(self):
        spec = self._spec(frequency="MONTHS", interval=1, day_of_month=31)
        self.assertEqual(add_recurrence(spec, date(2026, 1, 31)), date(2026, 2, 28))

    def test_trimestrale_attraversa_il_cambio_anno(self):
        spec = self._spec(frequency="MONTHS", interval=3)
        self.assertEqual(add_recurrence(spec, date(2026, 11, 15)), date(2027, 2, 15))

    def test_annuale_a_data_fissa(self):
        spec = self._spec(frequency="YEARS", interval=1, month_of_year=12, day_of_month=31)
        self.assertEqual(add_recurrence(spec, date(2026, 12, 31)), date(2027, 12, 31))

    def test_descrizione_leggibile_senza_termini_tecnici(self):
        self.assertEqual(describe_recurrence(self._spec(frequency="DAYS", interval=30)), "Ogni 30 giorni")
        self.assertEqual(describe_recurrence(self._spec(frequency="MONTHS", interval=3)), "Ogni trimestre")
        self.assertEqual(
            describe_recurrence(self._spec(frequency="MONTHS", interval=1, weekday=0, week_of_month=1)),
            "Ogni mese, il primo lunedi",
        )


class MaintenanceDomainTestCase(TestCase):
    """Base con una categoria, un gruppo TORNI e tre asset."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="manutentore", password="x")
        cls.category = AssetCategory.objects.create(code="macchine", label="Macchine")
        cls.assets = [
            Asset.objects.create(
                asset_tag=f"TORNIO0{i}",
                name=f"Tornio {i}",
                asset_category=cls.category,
                status=Asset.STATUS_IN_USE,
            )
            for i in (1, 2, 3)
        ]
        cls.group = AssetGroup.objects.create(code="torni", label="TORNI")
        for asset in cls.assets:
            AssetGroupMembership.objects.create(group=cls.group, asset=asset)

    def make_plan(self, label="Cambio olio", **kwargs):
        defaults = {
            "code": label.lower().replace(" ", "-"),
            "label": label,
            "maintenance_type": MaintenanceInterventionTemplate.TYPE_ROUTINE,
        }
        defaults.update(kwargs)
        return MaintenanceInterventionTemplate.objects.create(**defaults)

    def make_assignment(self, plan, **kwargs):
        defaults = {
            "plan": plan,
            "target_type": MaintenancePlanAssignment.TARGET_GROUP,
            "asset_group": self.group,
            "frequency": MaintenancePlanAssignment.FREQ_DAYS,
            "interval": 30,
            "warning_days": 10,
        }
        defaults.update(kwargs)
        return MaintenancePlanAssignment.objects.create(**defaults)


class OccurrenceGenerationTests(MaintenanceDomainTestCase):
    def test_occurrence_generata_solo_dentro_la_finestra_di_preavviso(self):
        plan = self.make_plan()
        self.make_assignment(plan, warning_days=30, first_due_date=date(2026, 10, 20))

        result = domain.generate_occurrences(today=date(2026, 9, 1))
        self.assertEqual(result["created"], 0, "fuori preavviso non si genera nulla")

        result = domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertEqual(result["created"], 3)
        self.assertEqual(
            set(MaintenanceOccurrence.objects.values_list("due_date", flat=True)),
            {date(2026, 10, 20)},
        )

    def test_generazione_idempotente(self):
        plan = self.make_plan()
        self.make_assignment(plan, first_due_date=date(2026, 9, 25), warning_days=30)

        domain.generate_occurrences(today=date(2026, 9, 20))
        second = domain.generate_occurrences(today=date(2026, 9, 20))

        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped_open"], 3)
        self.assertEqual(MaintenanceOccurrence.objects.count(), 3)

    def test_dry_run_non_scrive(self):
        plan = self.make_plan()
        self.make_assignment(plan, first_due_date=date(2026, 9, 25), warning_days=30)

        result = domain.generate_occurrences(today=date(2026, 9, 20), dry_run=True)

        self.assertEqual(result["created"], 3)
        self.assertEqual(MaintenanceOccurrence.objects.count(), 0)

    def test_comando_scheduler(self):
        plan = self.make_plan()
        self.make_assignment(plan, first_due_date=date(2020, 1, 1), warning_days=30)
        call_command("generate_maintenance_occurrences", verbosity=0)
        self.assertEqual(MaintenanceOccurrence.objects.count(), 3)

    def test_asset_fermo_continua_a_generare_se_incluso_esplicitamente(self):
        plan = self.make_plan()
        self.make_assignment(plan, first_due_date=date(2020, 1, 1))
        self.assets[0].status = Asset.STATUS_IN_REPAIR
        self.assets[0].save(update_fields=["status"])

        result = domain.generate_occurrences(today=date(2026, 9, 20), asset_queryset=Asset.objects.all())
        self.assertEqual(result["created"], 3)


class AssignmentPrecedenceTests(MaintenanceDomainTestCase):
    def test_asset_specifico_vince_sul_gruppo(self):
        plan = self.make_plan()
        group_assignment = self.make_assignment(plan, interval=90)
        self.make_assignment(
            plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset_group=None,
            asset=self.assets[2],
            interval=60,
        )

        resolutions = domain.build_plan_resolutions()
        self.assertEqual(resolutions[(plan.id, self.assets[0].id)].assignment.interval, 90)
        self.assertEqual(resolutions[(plan.id, self.assets[1].id)].assignment.interval, 90)

        custom = resolutions[(plan.id, self.assets[2].id)]
        self.assertEqual(custom.assignment.interval, 60)
        self.assertEqual(custom.source, domain.SOURCE_ASSET)
        self.assertEqual(custom.inherited_from, group_assignment)
        self.assertEqual(custom.inherited_recurrence_label, "Ogni 90 giorni")

    def test_due_gruppi_con_tempi_diversi_generano_conflitto_non_una_scelta_arbitraria(self):
        plan = self.make_plan()
        other_group = AssetGroup.objects.create(code="reparto-1", label="REPARTO 1")
        AssetGroupMembership.objects.create(group=other_group, asset=self.assets[0])

        self.make_assignment(plan, interval=90)
        self.make_assignment(plan, asset_group=other_group, interval=60)

        resolution = domain.build_plan_resolutions()[(plan.id, self.assets[0].id)]
        self.assertTrue(resolution.is_conflict)
        self.assertIsNone(resolution.assignment)
        self.assertEqual(len(resolution.conflict_description()), 2)

        # Il conflitto blocca la generazione: nessuna periodicita' scelta d'ufficio.
        result = domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertEqual(result["conflicts"], 1)
        self.assertFalse(MaintenanceOccurrence.objects.filter(asset=self.assets[0]).exists())

    def test_personalizzare_l_asset_risolve_il_conflitto(self):
        plan = self.make_plan()
        other_group = AssetGroup.objects.create(code="reparto-1", label="REPARTO 1")
        AssetGroupMembership.objects.create(group=other_group, asset=self.assets[0])
        self.make_assignment(plan, interval=90)
        self.make_assignment(plan, asset_group=other_group, interval=60)

        self.make_assignment(
            plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset_group=None,
            asset=self.assets[0],
            interval=45,
        )

        resolution = domain.build_plan_resolutions()[(plan.id, self.assets[0].id)]
        self.assertTrue(resolution.is_applied)
        self.assertEqual(resolution.assignment.interval, 45)

    def test_esclusione_di_un_asset_dal_piano_ereditato(self):
        plan = self.make_plan()
        self.make_assignment(plan, first_due_date=date(2020, 1, 1))
        self.make_assignment(
            plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset_group=None,
            asset=self.assets[1],
            is_excluded=True,
        )

        result = domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["excluded"], 1)
        self.assertFalse(MaintenanceOccurrence.objects.filter(asset=self.assets[1]).exists())

    def test_stessa_periodicita_da_due_gruppi_non_e_un_conflitto(self):
        plan = self.make_plan()
        other_group = AssetGroup.objects.create(code="reparto-1", label="REPARTO 1")
        AssetGroupMembership.objects.create(group=other_group, asset=self.assets[0])
        self.make_assignment(plan, interval=90, warning_days=10)
        self.make_assignment(plan, asset_group=other_group, interval=90, warning_days=10)

        resolution = domain.build_plan_resolutions()[(plan.id, self.assets[0].id)]
        self.assertTrue(resolution.is_applied)


class OccurrenceCompletionTests(MaintenanceDomainTestCase):
    def _occurrence(self, plan, assignment, asset, due_date, **kwargs):
        return MaintenanceOccurrence.objects.create(
            plan=plan,
            assignment=assignment,
            asset=asset,
            due_date=due_date,
            warning_days=assignment.warning_days,
            schedule_anchor=assignment.effective_schedule_anchor,
            **kwargs,
        )

    def test_chiusura_ordinaria_avanza_dalla_data_di_esecuzione(self):
        plan = self.make_plan()
        assignment = self.make_assignment(plan, frequency=MaintenancePlanAssignment.FREQ_MONTHS, interval=1)
        occurrence = self._occurrence(plan, assignment, self.assets[0], date(2026, 9, 10))

        following = domain.complete_occurrence(occurrence, completed_on=date(2026, 9, 20), user=self.user)

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertEqual(following.due_date, date(2026, 10, 20))

    def test_chiusura_amministrativa_avanza_dalla_scadenza_teorica(self):
        plan = self.make_plan(
            "Rinnovo assicurazione",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
            attachment_required=True,
        )
        assignment = self.make_assignment(plan, frequency=MaintenancePlanAssignment.FREQ_MONTHS, interval=1)
        occurrence = self._occurrence(plan, assignment, self.assets[0], date(2026, 9, 10))
        MaintenanceOccurrenceAttachment.objects.create(
            occurrence=occurrence, file=SimpleUploadedFile("polizza.pdf", b"x")
        )

        following = domain.complete_occurrence(occurrence, completed_on=date(2026, 9, 20))

        self.assertEqual(following.due_date, date(2026, 10, 10))

    def test_amministrativa_senza_allegato_non_si_chiude(self):
        plan = self.make_plan(
            "Rinnovo assicurazione",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
        )
        plan.full_clean()
        plan.save()
        assignment = self.make_assignment(plan, frequency=MaintenancePlanAssignment.FREQ_YEARS, interval=1)
        occurrence = self._occurrence(plan, assignment, self.assets[0], date(2026, 12, 31))

        with self.assertRaises(domain.OccurrenceCompletionError):
            domain.complete_occurrence(occurrence)

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_OPEN)

    def test_piano_amministrativo_forza_allegato_obbligatorio(self):
        plan = self.make_plan(
            "Revisione",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
            attachment_required=False,
        )
        plan.full_clean()
        plan.save()
        plan.refresh_from_db()
        self.assertTrue(plan.attachment_required)
        self.assertEqual(plan.default_schedule_anchor, ANCHOR_FIXED_CALENDAR)

    def test_amministrativa_molto_in_ritardo_non_genera_una_scadenza_gia_passata(self):
        plan = self.make_plan(
            "Revisione", maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE
        )
        assignment = self.make_assignment(plan, frequency=MaintenancePlanAssignment.FREQ_MONTHS, interval=1)
        occurrence = self._occurrence(plan, assignment, self.assets[0], date(2026, 1, 10))
        MaintenanceOccurrenceAttachment.objects.create(
            occurrence=occurrence, file=SimpleUploadedFile("doc.pdf", b"x")
        )

        following = domain.complete_occurrence(occurrence, completed_on=date(2026, 6, 20))

        self.assertGreaterEqual(following.due_date, date(2026, 6, 20))
        self.assertEqual(following.due_date.day, 10)

    def test_esterna_eseguita_senza_rapporto_resta_rapporto_mancante(self):
        plan = self.make_plan("Taratura", execution_mode=MaintenanceInterventionTemplate.MODE_EXTERNAL)
        assignment = self.make_assignment(plan, frequency=MaintenancePlanAssignment.FREQ_YEARS, interval=1)
        occurrence = self._occurrence(plan, assignment, self.assets[0], date(2026, 9, 10))

        domain.complete_occurrence(occurrence, completed_on=date(2026, 9, 10))
        occurrence.refresh_from_db()
        self.assertEqual(
            domain.occurrence_view_state(occurrence, today=date(2026, 9, 11)),
            MaintenanceOccurrence.VIEW_REPORT_MISSING,
        )

        occurrence.report_received_at = date(2026, 9, 15)
        occurrence.save(update_fields=["report_received_at"])
        self.assertEqual(
            domain.occurrence_view_state(occurrence, today=date(2026, 9, 16)),
            MaintenanceOccurrence.VIEW_COMPLETED,
        )


class MassiveWorkOrderTests(MaintenanceDomainTestCase):
    def setUp(self):
        self.plan = self.make_plan()
        self.assignment = self.make_assignment(self.plan, first_due_date=date(2026, 10, 10), warning_days=30)
        domain.generate_occurrences(today=date(2026, 9, 20))
        self.occurrences = list(MaintenanceOccurrence.objects.order_by("asset__asset_tag"))

    def test_tre_occorrenze_in_un_solo_odl(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)

        self.assertTrue(work_order.is_massive)
        self.assertEqual(work_order.occurrences.count(), 3)
        self.assertEqual(work_order.asset, self.occurrences[0].asset)

    def test_rimuovere_un_asset_lo_riporta_da_pianificare_non_lo_chiude(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        removed = self.occurrences[1]

        domain.remove_occurrence_from_workorder(removed, user=self.user, reason="macchina in produzione")

        removed.refresh_from_db()
        self.assertIsNone(removed.work_order_id)
        self.assertEqual(removed.status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(
            domain.occurrence_view_state(removed, today=date(2026, 10, 1)),
            MaintenanceOccurrence.VIEW_DUE_SOON,
        )
        self.assertEqual(work_order.occurrences.count(), 2)

    def test_rimuovere_il_capofila_sposta_l_asset_dell_odl(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        lead = self.occurrences[0]

        domain.remove_occurrence_from_workorder(lead, user=self.user)

        work_order.refresh_from_db()
        self.assertNotEqual(work_order.asset_id, lead.asset_id)
        self.assertIn(work_order.asset_id, {occ.asset_id for occ in self.occurrences[1:]})

    def test_completamento_parziale(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        domain.complete_occurrence(self.occurrences[0], completed_on=date(2026, 10, 10))
        domain.complete_occurrence(self.occurrences[1], completed_on=date(2026, 10, 10))

        progress = domain.workorder_progress(work_order)
        self.assertEqual(progress["done"], 2)
        self.assertEqual(progress["todo"], 1)
        self.assertTrue(progress["is_partial"])

    def test_chiudere_un_asset_non_chiude_gli_altri(self):
        domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        domain.complete_occurrence(self.occurrences[0], completed_on=date(2026, 10, 10))

        self.occurrences[1].refresh_from_db()
        self.assertEqual(self.occurrences[1].status, MaintenanceOccurrence.STATUS_OPEN)

    def test_distribuzione_su_piu_giorni(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)

        day_one = domain.assign_occurrences_to_day(
            work_order, self.occurrences[:2], execution_date=date(2026, 10, 20), user=self.user
        )
        day_two = domain.assign_occurrences_to_day(
            work_order, self.occurrences[2:], execution_date=date(2026, 10, 21), user=self.user
        )

        self.assertEqual(day_one.occurrences.count(), 2)
        self.assertEqual(day_two.occurrences.count(), 1)

    def test_nuova_occorrenza_non_entra_da_sola_in_un_odl_gia_organizzato(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences[:2], user=self.user)
        orphan = self.occurrences[2]

        domain.generate_occurrences(today=date(2026, 9, 21))

        orphan.refresh_from_db()
        self.assertIsNone(orphan.work_order_id)
        self.assertEqual(work_order.occurrences.count(), 2)

        added = domain.add_occurrences_to_workorder(work_order, [orphan], user=self.user)
        self.assertEqual(added, 1)
        self.assertEqual(work_order.occurrences.count(), 3)

    def test_occorrenza_gia_pianificata_non_si_infila_in_un_secondo_odl(self):
        domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        with self.assertRaises(ValueError):
            domain.create_workorder_from_occurrences(self.occurrences[:1], user=self.user)

    def test_follow_up_collegato_all_asset_non_al_lotto(self):
        work_order = domain.create_workorder_from_occurrences(self.occurrences, user=self.user)
        target = self.occurrences[2]

        follow_up = WorkOrder.objects.create(
            asset=target.asset,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="Perdita olio",
            follow_up_of=work_order,
            follow_up_occurrence=target,
            follow_up_reason="perdita olio rilevata durante il cambio",
        )

        self.assertEqual(follow_up.follow_up_occurrence.asset, target.asset)
        self.assertEqual(list(target.follow_ups.all()), [follow_up])
        # La manutenzione ordinaria resta comunque eseguibile/eseguita.
        domain.complete_occurrence(target, completed_on=date(2026, 10, 10))
        target.refresh_from_db()
        self.assertEqual(target.status, MaintenanceOccurrence.STATUS_DONE)


class OccurrenceViewStateTests(MaintenanceDomainTestCase):
    def setUp(self):
        self.plan = self.make_plan()
        self.assignment = self.make_assignment(self.plan, warning_days=10)
        self.occurrence = MaintenanceOccurrence.objects.create(
            plan=self.plan,
            assignment=self.assignment,
            asset=self.assets[0],
            due_date=date(2026, 10, 20),
            warning_days=10,
        )

    def test_stati_derivati(self):
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 1)),
            MaintenanceOccurrence.VIEW_TO_PLAN,
        )
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 15)),
            MaintenanceOccurrence.VIEW_DUE_SOON,
        )
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 21)),
            MaintenanceOccurrence.VIEW_OVERDUE,
        )

    def test_stato_pianificata_e_in_corso(self):
        work_order = domain.create_workorder_from_occurrences([self.occurrence], user=self.user)
        self.occurrence.refresh_from_db()
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 21)),
            MaintenanceOccurrence.VIEW_PLANNED,
        )

        work_order.started_at = timezone.now()
        work_order.save(update_fields=["started_at"])
        self.occurrence.refresh_from_db()
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 21)),
            MaintenanceOccurrence.VIEW_IN_PROGRESS,
        )

        work_order.is_waiting = True
        work_order.save(update_fields=["is_waiting"])
        self.occurrence.refresh_from_db()
        self.assertEqual(
            domain.occurrence_view_state(self.occurrence, today=date(2026, 10, 21)),
            MaintenanceOccurrence.VIEW_WAITING,
        )
