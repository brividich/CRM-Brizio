"""
Tests per il modulo procedure_refresh.

Esecuzione:
    python manage.py test procedure_refresh --settings=config.settings.dev
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import UserExtraInfo

from .models import (
    AssignmentStatus,
    CampaignStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureDocument,
    ProcedureQuiz,
    ProcedureQuizAttempt,
    ProcedureRevision,
    ReadEventType,
    SourceType,
)

User = get_user_model()


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pw", is_superuser=True)

    def _make_doc(self, code="MT-TEST-001"):
        return ProcedureDocument.objects.create(
            code=code,
            title="Test document",
            document_type="MT",
            is_active=True,
        )

    def _make_revision(self, doc, code="Rev.01", is_current=True):
        return ProcedureRevision.objects.create(
            document=doc,
            revision_code=code,
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 15),
            source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/doc.pdf",
            file_name="MT-TEST-001_Rev01.pdf",
            is_current=is_current,
            published_by=self.user,
        )

    def _make_campaign(self, name="Test Campaign"):
        return ProcedureCampaign.objects.create(
            name=name,
            status=CampaignStatus.PUBLISHED,
            start_date=date(2026, 1, 1),
            due_date=date(2026, 3, 31),
            created_by=self.user,
        )

    def test_document_creation(self):
        doc = self._make_doc()
        self.assertEqual(str(doc), "[MT] MT-TEST-001 — Test document")
        self.assertTrue(doc.is_active)

    def test_revision_current_unique(self):
        doc = self._make_doc()
        rev1 = self._make_revision(doc, "Rev.01", is_current=True)
        rev2 = self._make_revision(doc, "Rev.02", is_current=True)
        rev1.refresh_from_db()
        self.assertFalse(rev1.is_current, "Rev.01 should no longer be current after Rev.02 set as current")
        self.assertTrue(rev2.is_current)

    def test_revision_validation_sharepoint_requires_url(self):
        from django.core.exceptions import ValidationError

        doc = self._make_doc("MT-VALID-001")
        rev = ProcedureRevision(
            document=doc,
            revision_code="Rev.01",
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 15),
            source_type=SourceType.SHAREPOINT,
            source_url="",  # missing
            file_name="test.pdf",
        )
        with self.assertRaises(ValidationError):
            rev.clean()

    def test_revision_validation_fileserver_requires_path(self):
        from django.core.exceptions import ValidationError

        doc = self._make_doc("MT-VALID-002")
        rev = ProcedureRevision(
            document=doc,
            revision_code="Rev.01",
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 15),
            source_type=SourceType.FILESERVER,
            source_path="",  # missing
            file_name="test.pdf",
        )
        with self.assertRaises(ValidationError):
            rev.clean()

    def test_assignment_creation(self):
        doc = self._make_doc("MT-ASSIGN-001")
        rev = self._make_revision(doc)
        camp = self._make_campaign()
        assignment = ProcedureAssignment.objects.create(
            campaign=camp,
            revision=rev,
            user=self.user,
            assigned_by=self.user,
            due_date=date(2026, 3, 31),
            status=AssignmentStatus.ASSIGNED,
        )
        self.assertEqual(assignment.status, AssignmentStatus.ASSIGNED)
        self.assertFalse(assignment.read_confirmed_flag)
        self.assertEqual(assignment.open_count, 0)

    def test_document_current_revision_helper(self):
        doc = self._make_doc("MT-HELPER-001")
        rev1 = self._make_revision(doc, "Rev.01", is_current=False)
        rev2 = self._make_revision(doc, "Rev.02", is_current=True)
        self.assertEqual(doc.current_revision().pk, rev2.pk)


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="viewuser", password="pw", email="view@test.com", is_superuser=True
        )
        self.doc = ProcedureDocument.objects.create(
            code="MT-VIEW-001",
            title="View test doc",
            document_type="MT",
            is_active=True,
        )
        self.rev = ProcedureRevision.objects.create(
            document=self.doc,
            revision_code="Rev.01",
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 15),
            source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/doc.pdf",
            file_name="MT-VIEW-001_Rev01.pdf",
            is_current=True,
        )
        self.campaign = ProcedureCampaign.objects.create(
            name="View Campaign",
            status=CampaignStatus.PUBLISHED,
            start_date=date(2026, 1, 1),
            due_date=date(2026, 3, 31),
            created_by=self.user,
        )
        self.campaign_doc = ProcedureCampaignDocument.objects.create(
            campaign=self.campaign,
            revision=self.rev,
            is_mandatory=True,
        )
        self.assignment = ProcedureAssignment.objects.create(
            campaign=self.campaign,
            revision=self.rev,
            user=self.user,
            assigned_by=self.user,
            due_date=date(2026, 3, 31),
            status=AssignmentStatus.ASSIGNED,
        )

    def test_redirect_if_not_authenticated(self):
        resp = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertEqual(resp.status_code, 302)

    def test_my_assignments_authenticated(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "MT-VIEW-001")

    def test_my_assignments_renderizza_workspace_fullpage(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pr-workspace-page")
        self.assertContains(resp, "pr-shell")
        self.assertContains(resp, "pr-workspace")
        self.assertContains(resp, "Da completare")
        self.assertContains(resp, "1 risultati")

    def test_subpages_renderizzano_workspace_fullpage(self):
        self.client.force_login(self.user)
        urls_and_markers = [
            (reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk}), "pr-reading-page"),
            (reverse("procedure_refresh:admin_dashboard"), "pr-admin-dashboard-page"),
            (reverse("procedure_refresh:document_list"), "pr-document-list-page"),
            (reverse("procedure_refresh:document_create"), "pr-document-form-page"),
            (reverse("procedure_refresh:revision_create", kwargs={"doc_pk": self.doc.pk}), "pr-revision-form-page"),
            (reverse("procedure_refresh:revision_quiz", kwargs={"rev_pk": self.rev.pk}), "pr-quiz-form-page"),
            (reverse("procedure_refresh:campaign_list"), "pr-campaign-list-page"),
            (reverse("procedure_refresh:campaign_create"), "pr-campaign-form-page"),
            (reverse("procedure_refresh:campaign_detail", kwargs={"pk": self.campaign.pk}), "pr-campaign-detail-page"),
            (reverse("procedure_refresh:report_user"), "pr-report-user-page"),
            (reverse("procedure_refresh:report_document"), "pr-report-document-page"),
            (reverse("procedure_refresh:report_campaign") + f"?camp_id={self.campaign.pk}", "pr-report-campaign-page"),
            (reverse("procedure_refresh:report_matrix"), "pr-report-matrix-page"),
        ]

        for url, marker in urls_and_markers:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "pr-workspace-page")
                self.assertContains(resp, marker)

    def test_assignment_detail_get_tracks_open(self):
        self.client.force_login(self.user)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.open_count, 1)
        self.assertIsNotNone(self.assignment.first_opened_at)
        self.assertEqual(self.assignment.status, AssignmentStatus.OPENED)

    def test_assignment_detail_confirm_read(self):
        self.client.force_login(self.user)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.post(url, {"user_note": "Ho letto.", "confirm_read": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.read_confirmed_flag)
        self.assertIsNotNone(self.assignment.read_confirmed_at)
        self.assertEqual(self.assignment.status, AssignmentStatus.READ_CONFIRMED)
        self.assertEqual(self.assignment.user_note, "Ho letto.")

    def test_assignment_detail_cannot_access_others(self):
        other = User.objects.create_user(username="other", password="pw", is_superuser=True)
        self.client.force_login(other)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_read_event_created_on_confirm(self):
        self.client.force_login(self.user)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        self.client.post(url, {"user_note": "Ok.", "confirm_read": "1"})
        events = self.assignment.events.filter(event_type=ReadEventType.CONFIRMED)
        self.assertEqual(events.count(), 1)

    def test_note_saved_without_confirmation(self):
        self.client.force_login(self.user)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        self.client.post(url, {"user_note": "Nota senza conferma"})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.user_note, "Nota senza conferma")
        self.assertFalse(self.assignment.read_confirmed_flag)

    def test_report_matrix_by_department_and_csv_export(self):
        UserExtraInfo.objects.create(legacy_user_id=self.user.pk, reparto="Produzione")
        self.assignment.status = AssignmentStatus.READ_CONFIRMED
        self.assignment.read_confirmed_flag = True
        self.assignment.save(update_fields=["status", "read_confirmed_flag", "updated_at"])

        self.client.force_login(self.user)
        url = reverse("procedure_refresh:report_matrix") + f"?camp_id={self.campaign.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Matrice formazione")
        self.assertContains(resp, "Produzione")
        self.assertContains(resp, "1/1")

        csv_url = reverse("procedure_refresh:export_csv") + f"?type=matrix&camp={self.campaign.pk}"
        csv_resp = self.client.get(csv_url)
        self.assertEqual(csv_resp.status_code, 200)
        body = b"".join(csv_resp.streaming_content).decode("utf-8")
        self.assertIn("Completamento %", body)
        self.assertIn("Produzione", body)
        self.assertIn("MT-VIEW-001", body)

    def test_revision_quiz_manager_creates_quiz(self):
        self.client.force_login(self.user)
        url = reverse("procedure_refresh:revision_quiz", kwargs={"rev_pk": self.rev.pk})
        resp = self.client.post(url, {
            "title": "Verifica lettura",
            "is_active": "1",
            "question_1": "Quale documento hai letto?",
            "question_1_option_1": "MT-VIEW-001",
            "question_1_option_2": "Altro",
            "question_1_correct": "1",
        })
        self.assertEqual(resp.status_code, 302)
        quiz = ProcedureQuiz.objects.get(revision=self.rev)
        self.assertEqual(quiz.title, "Verifica lettura")
        self.assertTrue(quiz.is_active)
        self.assertEqual(quiz.question_count, 1)

    def test_quiz_after_read_confirmation_is_tracked_and_non_blocking(self):
        quiz = ProcedureQuiz.objects.create(
            revision=self.rev,
            title="Quiz rapido",
            questions=[{
                "text": "Risposta corretta?",
                "options": ["No", "Si"],
                "correct_index": 1,
            }],
            is_active=True,
            created_by=self.user,
        )
        self.client.force_login(self.user)
        detail_url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})

        confirm_resp = self.client.post(detail_url, {"user_note": "Letto", "confirm_read": "1"})
        self.assertEqual(confirm_resp.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.READ_CONFIRMED)

        get_resp = self.client.get(detail_url)
        self.assertContains(get_resp, "Quiz rapido")

        quiz_resp = self.client.post(detail_url, {"submit_quiz": "1", "quiz_q_0": "1"})
        self.assertEqual(quiz_resp.status_code, 302)
        attempt = ProcedureQuizAttempt.objects.get(quiz=quiz, assignment=self.assignment, user=self.user)
        self.assertEqual(attempt.score, 1)
        self.assertEqual(attempt.total_questions, 1)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.READ_CONFIRMED)
