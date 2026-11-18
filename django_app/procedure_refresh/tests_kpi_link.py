"""Tessere KPI di Presa visione: portano all'elenco filtrato che conta lo stesso numero. Dati sintetici."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import (
    AssignmentStatus,
    CampaignStatus,
    ChangeRequestStatus,
    ProcedureAssignment,
    ProcedureCampaign,
    ProcedureCampaignDocument,
    ProcedureChangeRequest,
    ProcedureDocument,
    ProcedureRevision,
    SourceType,
)


class KpiLinkTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kpi-pr", password="x", is_superuser=True)
        self.client.force_login(self.user)
        self.oggi = timezone.localdate()
        self.doc = ProcedureDocument.objects.create(code="MT-KPI-9", title="Doc", document_type="MT", is_active=True)
        ProcedureDocument.objects.create(code="MT-KPI-OFF", title="Vecchio", document_type="MT", is_active=False)
        self.rev = ProcedureRevision.objects.create(
            document=self.doc, revision_code="Rev.01", revision_date=date(2026, 1, 1), effective_date=date(2026, 1, 2),
            source_type=SourceType.SHAREPOINT, source_url="https://example.invalid/doc.pdf", file_name="d.pdf",
            is_current=True, published_by=self.user,
        )
        self.camp = ProcedureCampaign.objects.create(
            name="Sessione KPI", status=CampaignStatus.PUBLISHED, start_date=self.oggi - timedelta(days=30),
            due_date=self.oggi + timedelta(days=30), created_by=self.user,
        )
        ProcedureCampaignDocument.objects.create(campaign=self.camp, revision=self.rev)
        ProcedureCampaign.objects.create(name="Bozza KPI", status=CampaignStatus.DRAFT, start_date=self.oggi,
                                         due_date=self.oggi, created_by=self.user)
        utenti = [get_user_model().objects.create_user(username=f"kpi-u{i}", password="x", is_superuser=True) for i in range(5)]
        for u in utenti:
            UserOnboarding.objects.create(user=u, completed=True)
        stati = [
            (AssignmentStatus.READ_CONFIRMED, self.oggi + timedelta(days=5)),
            (AssignmentStatus.ASSIGNED, self.oggi + timedelta(days=3)),   # in attesa, in scadenza 7g
            (AssignmentStatus.ASSIGNED, self.oggi - timedelta(days=1)),   # scaduta dal vivo
            (AssignmentStatus.OVERDUE, self.oggi - timedelta(days=9)),    # scaduta marcata
            (AssignmentStatus.CANCELLED, self.oggi + timedelta(days=5)),
        ]
        for u, (stato, scadenza) in zip(utenti, stati, strict=True):
            ProcedureAssignment.objects.create(campaign=self.camp, revision=self.rev, user=u, assigned_by=self.user,
                                               due_date=scadenza, status=stato)
        ProcedureChangeRequest.objects.create(document=self.doc, created_by=self.user, status=ChangeRequestStatus.APERTA,
                                              testo="x")
        ProcedureChangeRequest.objects.create(document=self.doc, created_by=self.user,
                                              status=ChangeRequestStatus.IN_CARICO, testo="y")
        ProcedureChangeRequest.objects.create(document=self.doc, created_by=self.user,
                                              status=ChangeRequestStatus.RESPINTA, testo="z")

    def _report(self, query):
        return self.client.get(reverse("procedure_refresh:report_campaign") + query).context

    def test_impostazioni_portano_al_report_di_tutte_le_sessioni(self):
        r = self.client.get(reverse("procedure_refresh:admin_dashboard"))
        report = reverse("procedure_refresh:report_campaign")
        self.assertContains(r, f'href="{report}?camp_id=tutte&amp;stato=scadute"')
        tutte = self._report("?camp_id=tutte")
        self.assertEqual(len(tutte["assignments"]), r.context["n_assignments"])
        for stato, chiave in (("confermate", "n_confirmed"), ("in_attesa", "n_pending"), ("scadute", "n_overdue")):
            with self.subTest(stato=stato):
                self.assertEqual(len(self._report(f"?camp_id=tutte&stato={stato}")["assignments"]), r.context[chiave])
        self.assertEqual((r.context["n_confirmed"], r.context["n_pending"], r.context["n_overdue"]), (1, 1, 2))

    def test_impostazioni_documenti_sessioni_segnalazioni(self):
        r = self.client.get(reverse("procedure_refresh:admin_dashboard"))
        docs = self.client.get(reverse("procedure_refresh:document_list") + "?filtro=attivi").context["documents"]
        self.assertEqual(len(docs), r.context["n_documents"])
        pubblicate = self.client.get(reverse("procedure_refresh:campaign_list") + "?stato=published").context["campaigns"]
        self.assertEqual(len(pubblicate), r.context["n_published"])
        aperte = self.client.get(reverse("procedure_refresh:change_request_list") + "?stato=aperte").context
        self.assertEqual(len(aperte["change_requests"]), r.context["n_change_requests_open"])
        self.assertEqual(aperte["n_open"], 2)

    def test_sessione_in_attesa_esclude_le_scadute_come_il_report(self):
        r = self.client.get(reverse("procedure_refresh:campaign_detail", args=[self.camp.pk]))
        self.assertEqual(r.context["n_pending"], 1)
        self.assertContains(r, f'?camp_id={self.camp.pk}&amp;stato=in_attesa')
        stats = self._report(f"?camp_id={self.camp.pk}")["report_stats"]
        self.assertEqual(stats["pending"], r.context["n_pending"])

    def test_matrice_porta_al_report_con_lo_stesso_numero(self):
        m = self.client.get(reverse("procedure_refresh:report_matrix") + f"?camp_id={self.camp.pk}").context["matrix"]
        richieste = self._report(f"?camp_id={self.camp.pk}&stato=richieste")["assignments"]
        da_confermare = self._report(f"?camp_id={self.camp.pk}&stato=da_confermare")["assignments"]
        confermate = self._report(f"?camp_id={self.camp.pk}&stato=richieste_confermate")["assignments"]
        self.assertEqual((len(richieste), len(confermate), len(da_confermare)), (m["total"], m["confirmed"], m["pending"]))
        self.assertEqual(m["total"], 4)

    def test_le_mie_letture_filtri_delle_tessere(self):
        for u in get_user_model().objects.filter(username__startswith="kpi-u"):
            self.client.force_login(u)
            r = self.client.get(reverse("procedure_refresh:my_assignments"))
            for stato, chiave in (("pending", "pending"), ("due_soon", "due_soon"), ("overdue", "overdue"),
                                  ("read_confirmed", "confirmed")):
                with self.subTest(utente=u.username, stato=stato):
                    filtrato = self.client.get(reverse("procedure_refresh:my_assignments") + f"?status={stato}")
                    self.assertEqual(filtrato.context["pr_stats"]["filtered"], r.context["pr_stats"][chiave])

    def test_report_mostra_scaduta_anche_se_non_ancora_marcata(self):
        righe = self._report(f"?camp_id={self.camp.pk}&stato=scadute")["assignments"]
        self.assertTrue(all(a.scaduta_ora for a in righe))
