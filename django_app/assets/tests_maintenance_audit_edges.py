"""Edge-case audit for the maintenance-domain refactor.

These tests intentionally live outside the implementation test modules written by
the refactor session.  They describe the required boundary behaviour without
patching models, services, views, or templates.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import UserExtraInfo

from assets.models import (
    Asset,
    AssetCategory,
    AssetGroup,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import maintenance_domain as domain
from assets.services.recurrence import add_recurrence, validate_recurrence_fields


User = get_user_model()


class CalendarEdgeAuditTests(SimpleTestCase):
    def spec(self, **overrides):
        data = {
            "frequency": "DAYS",
            "interval": 1,
            "weekday": None,
            "week_of_month": None,
            "day_of_month": None,
            "month_of_year": None,
        }
        data.update(overrides)
        return data

    def test_31_january_plus_one_month_clamps_to_february(self):
        self.assertEqual(
            add_recurrence(self.spec(frequency="MONTHS", day_of_month=31), date(2027, 1, 31)),
            date(2027, 2, 28),
        )

    def test_leap_day_plus_one_year_clamps_to_february_28(self):
        self.assertEqual(
            add_recurrence(self.spec(frequency="YEARS", month_of_year=2, day_of_month=29), date(2024, 2, 29)),
            date(2025, 2, 28),
        )

    def test_february_to_march_daily_transition(self):
        self.assertEqual(add_recurrence(self.spec(), date(2027, 2, 28)), date(2027, 3, 1))

    def test_quarterly_recurrence_crosses_december(self):
        self.assertEqual(
            add_recurrence(self.spec(frequency="MONTHS", interval=3, day_of_month=31), date(2026, 10, 31)),
            date(2027, 1, 31),
        )

    def test_first_monday_is_resolved_in_target_month(self):
        self.assertEqual(
            add_recurrence(
                self.spec(frequency="MONTHS", interval=1, weekday=0, week_of_month=1),
                date(2026, 9, 7),
            ),
            date(2026, 10, 5),
        )

    def test_fifth_monday_configuration_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_recurrence_fields(
                self.spec(frequency="MONTHS", interval=1, weekday=0, week_of_month=5)
            )

    def test_annual_february_29_recovers_in_next_leap_year(self):
        spec = self.spec(frequency="YEARS", month_of_year=2, day_of_month=29)
        due = date(2024, 2, 29)
        for expected in (date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)):
            due = add_recurrence(spec, due)
            self.assertEqual(due, expected)

    def test_daily_recurrence_crosses_year_end(self):
        self.assertEqual(add_recurrence(self.spec(), date(2026, 12, 31)), date(2027, 1, 1))


class MaintenanceAuditFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="audit-maintainer", password="x")
        UserExtraInfo.objects.create(
            legacy_user_id=cls.user.pk,
            reparto="TORNI",
            caporeparto="audit-maintainer",
        )
        cls.category = AssetCategory.objects.create(code="audit-machines", label="Audit machines")
        cls.assets = [
            Asset.objects.create(
                asset_tag=f"AUDIT-{number:02d}",
                name=f"Audit machine {number}",
                asset_category=cls.category,
                reparto="TORNI" if number != 3 else "FRESE",
                status=Asset.STATUS_IN_USE,
            )
            for number in range(1, 4)
        ]
        cls.group = AssetGroup.objects.create(code="audit-torni", label="Audit torni")
        for asset in cls.assets:
            AssetGroupMembership.objects.create(group=cls.group, asset=asset)

    def make_plan(self, suffix="base"):
        return MaintenanceInterventionTemplate.objects.create(
            code=f"audit-plan-{suffix}",
            label=f"Audit plan {suffix}",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ROUTINE,
        )

    def make_assignment(self, plan, **overrides):
        values = {
            "plan": plan,
            "target_type": MaintenancePlanAssignment.TARGET_GROUP,
            "asset_group": self.group,
            "frequency": MaintenancePlanAssignment.FREQ_DAYS,
            "interval": 30,
            "warning_days": 30,
            "first_due_date": date(2026, 9, 20),
        }
        values.update(overrides)
        return MaintenancePlanAssignment.objects.create(**values)

    def make_occurrences(self, suffix="flow", count=3):
        plan = self.make_plan(suffix)
        assignment = self.make_assignment(plan)
        occurrences = [
            MaintenanceOccurrence.objects.create(
                plan=plan,
                assignment=assignment,
                asset=asset,
                due_date=date(2026, 9, 20),
                warning_days=30,
            )
            for asset in self.assets[:count]
        ]
        return plan, assignment, occurrences


class OccurrenceEdgeAuditTests(MaintenanceAuditFixture):
    def test_repeated_scheduler_is_idempotent(self):
        plan = self.make_plan("repeat")
        self.make_assignment(plan)
        domain.generate_occurrences(today=date(2026, 9, 20))
        domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertEqual(MaintenanceOccurrence.objects.filter(plan=plan).count(), 3)

    def test_disabled_assignment_does_not_generate(self):
        plan = self.make_plan("disabled")
        self.make_assignment(plan, is_active=False)
        domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertFalse(MaintenanceOccurrence.objects.filter(plan=plan).exists())

    def test_asset_assignment_precedes_group_assignment(self):
        plan = self.make_plan("specific")
        self.make_assignment(plan, interval=90)
        specific = self.make_assignment(
            plan,
            target_type=MaintenancePlanAssignment.TARGET_ASSET,
            asset_group=None,
            asset=self.assets[0],
            interval=45,
        )
        resolution = domain.resolve_plan_for_asset(plan_id=plan.pk, asset=self.assets[0])
        self.assertEqual(resolution.assignment, specific)

    def test_conflicting_groups_do_not_generate(self):
        plan = self.make_plan("conflict")
        second_group = AssetGroup.objects.create(code="audit-second-group", label="Second group")
        AssetGroupMembership.objects.create(group=second_group, asset=self.assets[0])
        self.make_assignment(plan, interval=90)
        self.make_assignment(plan, asset_group=second_group, interval=60)
        result = domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertGreaterEqual(result["conflicts"], 1)
        self.assertFalse(MaintenanceOccurrence.objects.filter(plan=plan, asset=self.assets[0]).exists())

    def test_done_occurrence_is_preserved_and_next_one_is_generated(self):
        plan = self.make_plan("done")
        assignment = self.make_assignment(plan)
        completed = MaintenanceOccurrence.objects.create(
            plan=plan,
            assignment=assignment,
            asset=self.assets[0],
            due_date=date(2026, 8, 21),
            completed_on=date(2026, 8, 21),
            status=MaintenanceOccurrence.STATUS_DONE,
        )
        domain.generate_occurrences(today=date(2026, 9, 20))
        completed.refresh_from_db()
        self.assertEqual(completed.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertEqual(
            MaintenanceOccurrence.objects.filter(plan=plan, asset=self.assets[0], status=MaintenanceOccurrence.STATUS_OPEN).count(),
            1,
        )

    def test_occurrence_already_in_workorder_is_not_regenerated(self):
        plan, _assignment, occurrences = self.make_occurrences("planned", count=1)
        domain.create_workorder_from_occurrences(occurrences, user=self.user)
        domain.generate_occurrences(today=date(2026, 9, 20))
        self.assertEqual(MaintenanceOccurrence.objects.filter(plan=plan, asset=self.assets[0]).count(), 1)


class MassiveWorkOrderEdgeAuditTests(MaintenanceAuditFixture):
    def test_partial_completion_keeps_other_occurrences_open(self):
        _plan, _assignment, occurrences = self.make_occurrences("partial")
        work_order = domain.create_workorder_from_occurrences(occurrences, user=self.user)
        domain.complete_occurrence(occurrences[0], completed_on=date(2026, 9, 21), create_next=False)
        progress = domain.workorder_progress(work_order)
        self.assertEqual((progress["done"], progress["todo"]), (1, 2))
        self.assertTrue(progress["is_partial"])

    def test_removal_returns_occurrence_to_unplanned(self):
        _plan, _assignment, occurrences = self.make_occurrences("remove")
        work_order = domain.create_workorder_from_occurrences(occurrences, user=self.user)
        domain.remove_occurrence_from_workorder(occurrences[1], user=self.user)
        occurrences[1].refresh_from_db()
        self.assertIsNone(occurrences[1].work_order_id)
        self.assertEqual(occurrences[1].status, MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(work_order.occurrences.count(), 2)

    def test_redistribution_only_moves_occurrences_of_that_workorder(self):
        _plan, _assignment, occurrences = self.make_occurrences("days")
        work_order = domain.create_workorder_from_occurrences(occurrences[:2], user=self.user)
        day = domain.assign_occurrences_to_day(
            work_order,
            [occurrences[0], occurrences[2]],
            execution_date=date(2026, 9, 23),
            user=self.user,
        )
        self.assertEqual(list(day.occurrences.values_list("pk", flat=True)), [occurrences[0].pk])

    def test_followup_can_target_only_one_asset(self):
        _plan, _assignment, occurrences = self.make_occurrences("followup")
        work_order = domain.create_workorder_from_occurrences(occurrences, user=self.user)
        follow_up = WorkOrder.objects.create(
            asset=occurrences[1].asset,
            title="Single-asset follow-up",
            follow_up_of=work_order,
            follow_up_occurrence=occurrences[1],
        )
        self.assertEqual(follow_up.asset_id, occurrences[1].asset_id)
        self.assertNotEqual(follow_up.asset_id, work_order.asset_id)

    def test_single_asset_workorder_is_not_massive(self):
        _plan, _assignment, occurrences = self.make_occurrences("single", count=1)
        work_order = domain.create_workorder_from_occurrences(occurrences, user=self.user)
        self.assertFalse(work_order.is_massive)
        self.assertEqual(work_order.occurrences.count(), 1)

    def test_many_asset_workorder_keeps_every_occurrence(self):
        plan = self.make_plan("many")
        assignment = self.make_assignment(plan)
        many_assets = [
            Asset.objects.create(
                asset_tag=f"MANY-{number:02d}",
                name=f"Many machine {number}",
                asset_category=self.category,
                status=Asset.STATUS_IN_USE,
            )
            for number in range(20)
        ]
        occurrences = [
            MaintenanceOccurrence.objects.create(
                plan=plan,
                assignment=assignment,
                asset=asset,
                due_date=date(2026, 10, 1),
            )
            for asset in many_assets
        ]
        work_order = domain.create_workorder_from_occurrences(occurrences, user=self.user)
        self.assertTrue(work_order.is_massive)
        self.assertEqual(work_order.occurrences.count(), 20)


@override_settings(LEGACY_AUTH_ENABLED=False)
class MaintenanceACLEdgeAuditTests(MaintenanceAuditFixture):
    def setUp(self):
        self.client.force_login(self.user)

    def test_maintainer_cannot_open_plan_configuration_directly(self):
        response = self.client.get(reverse("assets:maintenance_plan_create"))
        self.assertEqual(response.status_code, 302)

    def test_unauthorized_direct_post_does_not_create_workorder(self):
        _plan, _assignment, occurrences = self.make_occurrences("unauthorized", count=1)
        response = self.client.post(
            reverse("assets:occurrence_create_workorder"),
            {"occurrence_ids": [occurrences[0].pk]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(WorkOrder.objects.exists())

    def test_department_manager_cannot_plan_asset_outside_department(self):
        """Expected boundary: an allowed planner must still be scoped by department.

        The patch grants only the action capability; the selected occurrence belongs
        to FRESE while the simulated manager is responsible for TORNI.  A successful
        write is an IDOR/reparto-scope defect, not a test-fixture shortcut.
        """
        _plan, _assignment, occurrences = self.make_occurrences("department")
        outside = occurrences[2]
        with patch("assets.views_maintenance.can_plan_maintenance", return_value=True):
            response = self.client.post(
                reverse("assets:occurrence_create_workorder"),
                {"occurrence_ids": [outside.pk]},
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(WorkOrder.objects.exists())
