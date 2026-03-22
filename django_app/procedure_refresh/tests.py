"""
Tests per il modulo procedure_refresh.

Esecuzione:
    python manage.py test procedure_refresh --settings=config.settings.dev
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import (
    AssignmentStatus,
    CampaignStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureDocument,
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
        self.client.login(username="viewuser", password="pw")
        resp = self.client.get(reverse("procedure_refresh:my_assignments"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "MT-VIEW-001")

    def test_assignment_detail_get_tracks_open(self):
        self.client.login(username="viewuser", password="pw")
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.open_count, 1)
        self.assertIsNotNone(self.assignment.first_opened_at)
        self.assertEqual(self.assignment.status, AssignmentStatus.OPENED)

    def test_assignment_detail_confirm_read(self):
        self.client.login(username="viewuser", password="pw")
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
        self.client.login(username="other", password="pw")
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_read_event_created_on_confirm(self):
        self.client.login(username="viewuser", password="pw")
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        self.client.post(url, {"user_note": "Ok.", "confirm_read": "1"})
        events = self.assignment.events.filter(event_type=ReadEventType.CONFIRMED)
        self.assertEqual(events.count(), 1)

    def test_note_saved_without_confirmation(self):
        self.client.login(username="viewuser", password="pw")
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        self.client.post(url, {"user_note": "Nota senza conferma"})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.user_note, "Nota senza conferma")
        self.assertFalse(self.assignment.read_confirmed_flag)
