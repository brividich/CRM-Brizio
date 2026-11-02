"""«Scadute» si contano subito, non solo dopo il job delle 06:45."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import (
    AssignmentStatus,
    CampaignStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureDocument,
    ProcedureRevision,
    SourceType,
    q_in_attesa,
    q_scadute,
    scaduta_ora,
)


class ScaduteDalVivoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kpi-proc", password="x")
        doc = ProcedureDocument.objects.create(code="MT-KPI-1", title="Doc", document_type="MT", is_active=True)
        self.rev = ProcedureRevision.objects.create(
            document=doc, revision_code="Rev.01", revision_date=date(2026, 1, 1), effective_date=date(2026, 1, 2),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/doc.pdf", file_name="d.pdf",
            is_current=True, published_by=self.user,
        )
        self.oggi = timezone.localdate()

    def _assegna(self, *, scadenza, stato=AssignmentStatus.ASSIGNED, campagna=CampaignStatus.PUBLISHED):
        camp = ProcedureCampaign.objects.create(
            name=f"C {ProcedureCampaign.objects.count()}", status=campagna,
            start_date=self.oggi - timedelta(days=30), due_date=scadenza, created_by=self.user,
        )
        return ProcedureAssignment.objects.create(
            campaign=camp, revision=self.rev, user=self.user, assigned_by=self.user, due_date=scadenza, status=stato,
        )

    def test_scadenza_passata_conta_come_scaduta_anche_senza_job(self):
        ieri = self._assegna(scadenza=self.oggi - timedelta(days=1))
        domani = self._assegna(scadenza=self.oggi + timedelta(days=1))
        marcata = self._assegna(scadenza=self.oggi - timedelta(days=5), stato=AssignmentStatus.OVERDUE)
        bozza = self._assegna(scadenza=self.oggi - timedelta(days=1), campagna=CampaignStatus.DRAFT)

        scadute = set(ProcedureAssignment.objects.filter(q_scadute(self.oggi)).values_list("pk", flat=True))
        in_attesa = set(ProcedureAssignment.objects.filter(q_in_attesa(self.oggi)).values_list("pk", flat=True))
        self.assertEqual(scadute, {ieri.pk, marcata.pk})
        self.assertEqual(in_attesa, {domani.pk, bozza.pk})
        # Stessa regola per le righe già caricate (contatori di «Le mie procedure»).
        for a in (ieri, domani, marcata, bozza):
            self.assertEqual(scaduta_ora(a, self.oggi), a.pk in scadute)
