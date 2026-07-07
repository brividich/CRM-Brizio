"""
Tests per il modulo procedure_refresh.

Esecuzione:
    python manage.py test procedure_refresh --settings=config.settings.dev
"""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

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

    def test_campaign_remove_document(self):
        """Regressione: la rimozione di un documento da campagna non deve andare in 500
        (bug NameError su `campaign.pk` nel log_action)."""
        self.client.force_login(self.user)
        url = reverse(
            "procedure_refresh:campaign_remove_document",
            kwargs={"pk": self.campaign.pk, "cd_pk": self.campaign_doc.pk},
        )
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ProcedureCampaignDocument.objects.filter(pk=self.campaign_doc.pk).exists()
        )

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


class ImportSgiDaShareTests(TestCase):
    """Importer del corpus SGI da share: parser dei nomi + comando end-to-end."""

    def _parser(self):
        from procedure_refresh.management.commands.import_sgi_da_share import (
            _fallback_parse,
            parse_sgi_filename,
        )

        return parse_sgi_filename, _fallback_parse

    def test_parse_riconosce_codice_mt(self):
        parse, _ = self._parser()
        info = parse("MT CN 06 Rev.21_Risorse Umane.pdf")
        self.assertEqual(info["code"], "MT CN 06")
        self.assertEqual(info["revision"], "21")
        self.assertEqual(info["title"], "Risorse Umane")
        self.assertEqual(info["document_type"], "MT")
        self.assertFalse(info["fallback"])

    def test_parse_distingue_sottonumeri_e_numeri_lunghi(self):
        parse, _ = self._parser()
        # sotto-numero _10 fa parte del codice (documenti distinti, niente fusione)
        self.assertEqual(parse("MT CN 125_10 Gestione Prevenzione Abusi.pdf")["code"], "MT CN 125_10")
        # 2710 e 271 sono codici DISTINTI (4 cifre vs 3)
        self.assertEqual(parse("MT CN 2710_Requisiti legali Rev.0.pdf")["code"], "MT CN 2710")
        self.assertEqual(parse("MT CN 271_Politica di Sicurezza Rev.2.pdf")["code"], "MT CN 271")

    def test_parse_mod_con_punto(self):
        parse, _ = self._parser()
        self.assertEqual(parse("MOD.165 - RAR RiskAssessmentAndRegister Rev.3.pdf")["code"], "MOD.165")
        self.assertEqual(parse("MOD. 093 - TDM Marketing Rev.2.pdf")["code"], "MOD.093")
        self.assertEqual(parse("MOD.165 - RAR Rev.3.pdf")["document_type"], "ALTRO")

    def test_parse_none_per_nomi_non_sgi(self):
        parse, _ = self._parser()
        self.assertIsNone(parse("prEN_9100_E.pdf"))
        self.assertIsNone(parse("Quality Plan generico.pdf"))

    def test_fallback_per_nomi_non_standard(self):
        _, fallback = self._parser()
        info = fallback("PdQ CN_01.2020 Rev.21_firmato.pdf")
        self.assertTrue(info["fallback"])
        self.assertEqual(info["revision"], "21")
        self.assertTrue(info["code"].startswith("PdQ"))
        self.assertEqual(info["document_type"], "ALTRO")

    def _build_share(self, tmp):
        from pathlib import Path

        files = {
            "9100_Qualita/2_MT/MT CN 06 Rev.21_Risorse Umane.pdf",
            "9100_Qualita/_Modelli/MOD.165 - RAR RiskAssessmentAndRegister Rev.3.pdf",
            "_Piani Qualita/PdQ CN_01.2020 Rev.21_firmato.pdf",   # fallback
            "SUPERATO/MT CN 99 Rev.1_Vecchio.pdf",                # escluso
        }
        for rel in files:
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"%PDF-1.4 contenuto finto")
        return tmp

    def test_command_dry_run_non_scrive(self):
        import tempfile

        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as tmp:
            self._build_share(tmp)
            call_command("import_sgi_da_share", "--root", tmp)  # niente --apply
        self.assertEqual(ProcedureDocument.objects.count(), 0)

    def test_command_apply_registra_documenti_correnti_ed_esclude_superato(self):
        import tempfile

        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as tmp:
            self._build_share(tmp)
            call_command("import_sgi_da_share", "--root", tmp, "--apply")

        # 3 documenti (SUPERATO escluso)
        self.assertEqual(ProcedureDocument.objects.count(), 3)
        self.assertFalse(ProcedureDocument.objects.filter(code__icontains="MT CN 99").exists())

        mt = ProcedureDocument.objects.get(code="MT CN 06")
        self.assertEqual(mt.document_type, "MT")
        self.assertEqual(mt.title, "Risorse Umane")
        rev = mt.current_revision()
        self.assertIsNotNone(rev)
        self.assertEqual(rev.source_type, SourceType.FILESERVER)
        self.assertEqual(rev.revision_code, "21")
        self.assertTrue(rev.is_current)
        self.assertTrue(rev.source_path.endswith(".pdf"))
        self.assertTrue(rev.file_hash)  # hash calcolato in apply

        # la modulistica e i fallback ci sono
        self.assertTrue(ProcedureDocument.objects.filter(code="MOD.165").exists())
        self.assertTrue(ProcedureDocument.objects.filter(code__startswith="PdQ").exists())

    def test_command_solo_procedure_esclude_mod(self):
        import tempfile

        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as tmp:
            self._build_share(tmp)
            call_command("import_sgi_da_share", "--root", tmp, "--apply", "--solo-procedure")

        self.assertTrue(ProcedureDocument.objects.filter(code="MT CN 06").exists())
        self.assertFalse(ProcedureDocument.objects.filter(code="MOD.165").exists())  # MOD escluso

    def _dedup(self):
        from procedure_refresh.management.commands.import_sgi_da_share import dedup_candidates

        return dedup_candidates

    def _info(self, code, revision, title, file_name):
        return {
            "code": code,
            "revision": revision,
            "title": title,
            "file_name": file_name,
            "document_type": "MT",
            "fallback": False,
            "category": "",
            "path": f"\\\\srv\\sgi\\{file_name}",
        }

    def test_dedup_stesso_titolo_tiene_revisione_piu_alta(self):
        """Stesso codice + stesso titolo = revisioni: si tiene la più alta, niente perdita di documenti distinti."""
        dedup = self._dedup()
        parsed = [
            self._info("MOD.165", "2", "RAR RiskAssessmentAndRegister", "MOD.165 - RAR RiskAssessmentAndRegister Rev.2.pdf"),
            self._info("MOD.165", "3", "RAR RiskAssessmentAndRegister", "MOD.165 - RAR RiskAssessmentAndRegister Rev.3.pdf"),
        ]
        candidates, conflicts = dedup(parsed)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["code"], "MOD.165")
        self.assertEqual(candidates[0]["revision"], "3")  # vince la revisione più alta
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["motivo"], "revisione superata")

    def test_dedup_titoli_diversi_stesso_codice_disambigua_e_non_perde(self):
        """Documenti DISTINTI che condividono il codice parserizzato vengono tenuti tutti (codice disambiguato)."""
        dedup = self._dedup()
        parsed = [
            self._info("IDOR CN 02", "9", "Manuale di gestione del sistema informatico", "IDOR CN 02_Manuale di gestione del sistema informatico Rev.9.pdf"),
            self._info("IDOR CN 02", "2", "ISMS_Manuale ISMS", "IDOR CN 02 ISMS_Manuale ISMS Rev.2.pdf"),
        ]
        candidates, conflicts = dedup(parsed)
        codes = {c["code"] for c in candidates}
        # nessuna perdita: due documenti distinti, due codici distinti
        self.assertEqual(len(candidates), 2)
        self.assertIn("IDOR CN 02", codes)  # primario (revisione più alta) tiene il codice nudo
        self.assertNotIn("IDOR CN 02", [c["code"] for c in candidates if c.get("disambiguated_from")])
        disamb = [c for c in candidates if c.get("disambiguated_from") == "IDOR CN 02"]
        self.assertEqual(len(disamb), 1)
        self.assertEqual(disamb[0]["revision"], "2")
        self.assertNotEqual(disamb[0]["code"], "IDOR CN 02")
        self.assertFalse(conflicts)  # non è una revisione superata: è un altro documento

    def test_dedup_primario_stabile_su_parita_revisione(self):
        """A parità di revisione il codice nudo va al nome file alfabeticamente primo (idempotenza con import passati)."""
        dedup = self._dedup()
        parsed = [
            self._info("Mod.088", "1", "CIS - B - Certificato Ispezione NC CND", "Mod.088 - CIS - B - Certificato Ispezione NC CND Rev.1.pdf"),
            self._info("Mod.088", "1", "CIS - A - Certificato Ispezione CND", "Mod.088 - CIS - A - Certificato Ispezione CND Rev.1.pdf"),
        ]
        candidates, _ = dedup(parsed)
        primary = [c for c in candidates if not c.get("disambiguated_from")]
        self.assertEqual(len(primary), 1)
        self.assertTrue(primary[0]["file_name"].startswith("Mod.088 - CIS - A"))  # "A" < "B"
        self.assertEqual(primary[0]["code"], "Mod.088")


class SgiShareDriftTests(TestCase):
    """Watchdog: rileva documenti SGI nuovi/aggiornati sulla share vs DB e NOTIFICA
    (Issue), senza importare nulla (--apply resta un'azione umana)."""

    def _build_share(self, tmp):
        from pathlib import Path

        files = {
            "9100_Qualita/2_MT/MT CN 06 Rev.21_Risorse Umane.pdf",   # allineato al DB
            "9100_Qualita/_Modelli/MOD.165 - RAR Rev.3.pdf",          # share Rev.3 > DB Rev.2
            "_Piani Qualita/PdQ CN_01.2020 Rev.21_firmato.pdf",       # fallback, non nel DB = nuovo
        }
        for rel in files:
            p = Path(tmp) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"%PDF-1.4 contenuto finto")
        return tmp

    def _seed_doc(self, code, rev, title="t"):
        doc = ProcedureDocument.objects.create(code=code, title=title, is_active=True)
        ProcedureRevision.objects.create(
            document=doc, revision_code=rev, revision_date=date.today(),
            effective_date=date.today(), source_type=SourceType.FILESERVER,
            source_path="x.pdf", file_name="x.pdf", is_current=True,
        )
        return doc

    def test_detect_share_drift(self):
        import tempfile
        from pathlib import Path

        from procedure_refresh.management.commands.import_sgi_da_share import detect_share_drift

        self._seed_doc("MT CN 06", "21")  # = share -> non drift
        self._seed_doc("MOD.165", "2")    # share ha Rev.3 -> aggiornato
        with tempfile.TemporaryDirectory() as tmp:
            self._build_share(tmp)
            drift = detect_share_drift(Path(tmp))

        self.assertEqual(len(drift["new"]), 1)
        self.assertTrue(drift["new"][0]["code"].startswith("PdQ"))
        self.assertEqual(len(drift["updated"]), 1)
        self.assertEqual(drift["updated"][0]["code"], "MOD.165")
        self.assertEqual(drift["updated"][0]["revision_share"], "3")
        self.assertEqual(drift["updated"][0]["revision_db"], "2")

    def test_watchdog_apre_e_risolve_issue(self):
        import tempfile

        from django.core.management import call_command
        from django.test import override_settings

        from monitoring.models import Issue
        from procedure_refresh.tasks import run_sgi_share_check

        self._seed_doc("MT CN 06", "21")
        self._seed_doc("MOD.165", "2")
        with tempfile.TemporaryDirectory() as tmp:
            self._build_share(tmp)
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                res = run_sgi_share_check()
                self.assertTrue(res["ok"])
                self.assertEqual(res["new"], 1)
                self.assertEqual(res["updated"], 1)
                issue = Issue.objects.filter(current_url="check:sgi_share_drift").first()
                self.assertIsNotNone(issue)
                self.assertNotEqual(issue.status, Issue.Status.RESOLVED)

                # Allinea il DB alla share -> niente drift -> Issue risolta automaticamente
                call_command("import_sgi_da_share", "--root", tmp, "--apply")
                res2 = run_sgi_share_check()
                self.assertEqual(res2["new"], 0)
                self.assertEqual(res2["updated"], 0)
                issue.refresh_from_db()
                self.assertEqual(issue.status, Issue.Status.RESOLVED)

    def test_skip_se_root_non_configurata(self):
        from django.test import override_settings

        from procedure_refresh.tasks import run_sgi_share_check

        with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=""):
            res = run_sgi_share_check()
        self.assertTrue(res["skipped"])


class AutoSyncSafeSubsetTests(TestCase):
    """Sync SGI automatica: perimetro sicuro (filter_auto_safe) + task."""

    def _candidate(self, code, title="Titolo", revision="1", fallback=False, disamb=None):
        info = {
            "code": code, "title": title, "revision": revision,
            "document_type": "MT", "category": "9100", "fallback": fallback,
            "file_name": f"{code}.pdf", "path": f"C:/share/{code}.pdf",
        }
        if disamb:
            info["disambiguated_from"] = disamb
        return info

    def _seed(self, code, *, source_type=SourceType.FILESERVER, requires_ack=False, with_assignment=False):
        doc = ProcedureDocument.objects.create(
            code=code, title="t", is_active=True, requires_acknowledgement=requires_ack
        )
        rev = ProcedureRevision.objects.create(
            document=doc, revision_code="1", revision_date=date.today(),
            effective_date=date.today(), source_type=source_type,
            source_path="C:/share/x.pdf", source_url="https://x/y.pdf" if source_type == SourceType.SHAREPOINT else "",
            file_name="x.pdf", is_current=True,
        )
        if with_assignment:
            camp = ProcedureCampaign.objects.create(
                name="c", status=CampaignStatus.PUBLISHED,
                start_date=date.today(), due_date=date.today(),
            )
            u = User.objects.create_user(username=f"u_{code}", password="pw")
            ProcedureAssignment.objects.create(
                campaign=camp, revision=rev, user=u, status=AssignmentStatus.ASSIGNED
            )
        return doc

    def test_filter_auto_safe(self):
        from procedure_refresh.management.commands.import_sgi_da_share import filter_auto_safe

        self._seed("MT-EXIST-CHILD")                                  # figlio import -> safe
        self._seed("MT-EXIST-SP", source_type=SourceType.SHAREPOINT)  # sharepoint -> escluso
        self._seed("MT-EXIST-ACK", requires_ack=True)                 # presa visione -> escluso
        self._seed("MT-EXIST-ASSIGNED", with_assignment=True)         # assegnato -> escluso

        candidates = [
            self._candidate("MT-NEW-001"),                 # nuovo -> safe
            self._candidate("MT-EXIST-CHILD"),             # safe
            self._candidate("MT-EXIST-SP"),                # escluso
            self._candidate("MT-EXIST-ACK"),               # escluso
            self._candidate("MT-EXIST-ASSIGNED"),          # escluso
            self._candidate("MT-FALLBACK", fallback=True), # escluso (nome non riconosciuto)
            self._candidate("MT-DISAMB", disamb="MT-BASE"),# escluso (disambiguato)
        ]
        safe, excluded = filter_auto_safe(candidates)
        safe_codes = {c["code"] for c in safe}
        self.assertEqual(safe_codes, {"MT-NEW-001", "MT-EXIST-CHILD"})
        self.assertEqual(len(excluded), 5)

    def test_run_auto_sync_flag_off_skips(self):
        from procedure_refresh.tasks import run_sgi_auto_sync

        res = run_sgi_auto_sync()  # flag non impostato
        self.assertTrue(res["skipped"])
        self.assertEqual(res["created"], 0)

    def test_run_auto_sync_applies_safe_only(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        from core.models import SiteConfig
        from procedure_refresh.tasks import run_sgi_auto_sync

        SiteConfig.set("pr_sgi_auto_sync_attivo", "1", "test")
        # Documento in presa visione già esistente: l'auto-sync NON deve toccarlo.
        doc_ack = ProcedureDocument.objects.create(
            code="MT CN 06", title="Manuale", is_active=True, requires_acknowledgement=True
        )
        ProcedureRevision.objects.create(
            document=doc_ack, revision_code="20", revision_date=date.today(),
            effective_date=date.today(), source_type=SourceType.FILESERVER,
            source_path="C:/old.pdf", file_name="old.pdf", is_current=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ["9100/MT CN 07 Rev.3_Nuovo.pdf", "9100/MT CN 06 Rev.21_Manuale.pdf"]:
                p = Path(tmp) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"%PDF-1.4 x")
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                res = run_sgi_auto_sync(reindex=False)
        self.assertTrue(res["ok"])
        self.assertFalse(res["skipped"])
        self.assertEqual(res["created"], 1)  # solo MT CN 07 (nuovo, safe)
        self.assertTrue(ProcedureDocument.objects.filter(code="MT CN 07").exists())
        # Il doc in presa visione resta alla sua revisione (non scavalcato)
        doc_ack.refresh_from_db()
        self.assertEqual(doc_ack.current_revision().revision_code, "20")
        # Esito persistito
        self.assertTrue(SiteConfig.get("pr_sgi_last_sync", ""))

    def test_detect_missing_documents(self):
        import tempfile
        from pathlib import Path

        from procedure_refresh.management.commands.import_sgi_da_share import detect_share_drift

        with tempfile.TemporaryDirectory() as tmp:
            # Documento con path che NON esiste sulla share -> "missing"
            doc = ProcedureDocument.objects.create(code="MT-GONE", title="Sparito", is_active=True)
            ProcedureRevision.objects.create(
                document=doc, revision_code="1", revision_date=date.today(),
                effective_date=date.today(), source_type=SourceType.FILESERVER,
                source_path=str(Path(tmp) / "non_esiste.pdf"), file_name="non_esiste.pdf",
                is_current=True,
            )
            drift = detect_share_drift(Path(tmp))
        codes = {m["code"] for m in drift["missing"]}
        self.assertIn("MT-GONE", codes)


class SgiSyncNowViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="syncmgr", password="pw", is_superuser=True
        )
        self.client.force_login(self.manager)

    def test_pulsante_accoda_task(self):
        with mock.patch("procedure_refresh.views.async_task") as m:
            resp = self.client.post(reverse("procedure_refresh:sgi_sync_now"))
        self.assertEqual(resp.status_code, 302)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], "procedure_refresh.tasks.run_sgi_auto_sync")
        self.assertTrue(kwargs.get("force"))

    def test_toggle_auto_sync(self):
        from core.models import SiteConfig

        resp = self.client.post(reverse("procedure_refresh:admin_dashboard"), {
            "save_sgi_auto_sync": "1",
            "sgi_auto_sync_attivo": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SiteConfig.get("pr_sgi_auto_sync_attivo", ""), "1")


class AssignUsersNotificaTests(TestCase):
    """All'assegnazione parte la notifica in-app (niente mail: la manda l'IT)."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username="assignmgr", password="pw", is_superuser=True
        )
        self.reader = User.objects.create_user(
            username="assignreader", password="pw", first_name="Anna", last_name="Bianchi"
        )
        self.doc = ProcedureDocument.objects.create(
            code="MT-ASSIGN-001", title="Assign doc", document_type="MT", is_active=True
        )
        self.rev = ProcedureRevision.objects.create(
            document=self.doc,
            revision_code="Rev.01",
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1),
            source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/assign.pdf",
            file_name="assign.pdf",
            is_current=True,
        )
        self.campaign = ProcedureCampaign.objects.create(
            name="Assign Campaign",
            status=CampaignStatus.PUBLISHED,
            start_date=date(2026, 1, 1),
            due_date=date(2026, 12, 31),
            created_by=self.manager,
        )

    def test_assign_crea_notifica_in_app(self):
        from core.models import Notifica

        self.client.force_login(self.manager)
        url = reverse("procedure_refresh:assign_users", kwargs={"pk": self.campaign.pk})
        resp = self.client.post(url, {
            "user_ids": [str(self.reader.pk)],
            "revision_id": str(self.rev.pk),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            ProcedureAssignment.objects.filter(campaign=self.campaign, user=self.reader).count(), 1
        )
        notifiche = Notifica.objects.filter(messaggio__contains="MT-ASSIGN-001")
        self.assertEqual(notifiche.count(), 1)
        self.assertEqual(len(mail.outbox), 0)  # nessuna mail automatica all'assegnazione

        # Ri-assegnazione stessa revisione: nessuna nuova notifica
        self.client.post(url, {
            "user_ids": [str(self.reader.pk)],
            "revision_id": str(self.rev.pk),
        })
        self.assertEqual(Notifica.objects.filter(messaggio__contains="MT-ASSIGN-001").count(), 1)

    def test_campaign_detail_espone_elenco_destinatari(self):
        ProcedureAssignment.objects.create(
            campaign=self.campaign, revision=self.rev, user=self.reader,
            assigned_by=self.manager, due_date=date(2026, 12, 31),
            status=AssignmentStatus.ASSIGNED,
        )
        self.client.force_login(self.manager)
        with mock.patch(
            "procedure_refresh.tasks._notification_email_map",
            return_value={self.reader.pk: "bianchi@test.local"},
        ):
            resp = self.client.get(
                reverse("procedure_refresh:campaign_detail", kwargs={"pk": self.campaign.pk})
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["recipients_count"], 1)
        self.assertIn("Anna Bianchi <bianchi@test.local>", resp.context["recipients_clipboard"])
        self.assertContains(resp, "Copia elenco destinatari")

    def test_campaign_detail_evidenzia_senza_email(self):
        ProcedureAssignment.objects.create(
            campaign=self.campaign, revision=self.rev, user=self.reader,
            assigned_by=self.manager, due_date=date(2026, 12, 31),
            status=AssignmentStatus.ASSIGNED,
        )
        self.client.force_login(self.manager)
        with mock.patch(
            "procedure_refresh.tasks._notification_email_map",
            return_value={self.reader.pk: ""},
        ):
            resp = self.client.get(
                reverse("procedure_refresh:campaign_detail", kwargs={"pk": self.campaign.pk})
            )
        self.assertEqual(resp.context["recipients_count"], 0)
        self.assertIn("Anna Bianchi", resp.context["recipients_senza_email"])


class AdminDashboardReminderCardTests(TestCase):
    """Card impostazioni solleciti nella dashboard admin del modulo."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username="cardmgr", password="pw", is_superuser=True
        )
        self.client.force_login(self.manager)

    def test_get_mostra_card(self):
        resp = self.client.get(reverse("procedure_refresh:admin_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Solleciti presa visione")
        self.assertContains(resp, "reminder_pre_giorni")

    def test_post_salva_config(self):
        from procedure_refresh.reminder_config import get_reminder_config

        resp = self.client.post(reverse("procedure_refresh:admin_dashboard"), {
            "save_reminder_config": "1",
            "reminder_attivo": "1",
            "reminder_pre_giorni": "10,3",
            "reminder_post_cadenza": "5",
            "reminder_digest_giorno": "ven",
            "reminder_digest_destinatari": "qualita@test.local",
        })
        self.assertEqual(resp.status_code, 302)
        cfg = get_reminder_config()
        self.assertTrue(cfg["attivo"])
        self.assertEqual(cfg["pre_giorni"], [10, 3])
        self.assertEqual(cfg["post_cadenza_giorni"], 5)
        self.assertEqual(cfg["digest_giorno"], "ven")
        self.assertEqual(cfg["digest_destinatari"], ["qualita@test.local"])


class ChangeRequestTests(TestCase):
    """Segnalazioni di modifica: proposta dal lettore + gestione con stati."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username="crmgr", password="pw", is_superuser=True
        )
        # Proprietario dell'assegnazione: superuser come da convenzione dei test del
        # portale (bypassa il middleware ACL; i test con utente-employee richiedono
        # setup legacy non previsto qui). Testa il branch di view submit_change_request.
        self.reader = User.objects.create_user(
            username="crreader", password="pw", is_superuser=True
        )
        self.doc = ProcedureDocument.objects.create(
            code="MT-CR-001", title="CR doc", document_type="MT", is_active=True
        )
        self.rev = ProcedureRevision.objects.create(
            document=self.doc, revision_code="Rev.01", revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1), source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/cr.pdf", file_name="cr.pdf",
            is_current=True,
        )
        self.campaign = ProcedureCampaign.objects.create(
            name="CR Campaign", status=CampaignStatus.PUBLISHED,
            start_date=date(2026, 1, 1), due_date=date(2026, 12, 31), created_by=self.manager,
        )
        self.assignment = ProcedureAssignment.objects.create(
            campaign=self.campaign, revision=self.rev, user=self.reader,
            assigned_by=self.manager, due_date=date(2026, 12, 31),
            status=AssignmentStatus.ASSIGNED,
        )

    def test_reader_submits_change_request(self):
        from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest

        self.client.force_login(self.reader)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        resp = self.client.post(url, {
            "submit_change_request": "1",
            "change_text": "La tabella 3 va aggiornata con i nuovi limiti.",
        })
        self.assertEqual(resp.status_code, 302)
        cr = ProcedureChangeRequest.objects.get(document=self.doc, created_by=self.reader)
        self.assertEqual(cr.status, ChangeRequestStatus.APERTA)
        self.assertIn("tabella 3", cr.testo)

    def test_empty_change_request_rejected(self):
        from procedure_refresh.models import ProcedureChangeRequest

        self.client.force_login(self.reader)
        url = reverse("procedure_refresh:assignment_detail", kwargs={"pk": self.assignment.pk})
        self.client.post(url, {"submit_change_request": "1", "change_text": "   "})
        self.assertEqual(ProcedureChangeRequest.objects.count(), 0)

    def test_manager_sets_status_recepita(self):
        from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest

        cr = ProcedureChangeRequest.objects.create(
            document=self.doc, revision=self.rev, assignment=self.assignment,
            created_by=self.reader, testo="Proposta X",
        )
        self.client.force_login(self.manager)
        url = reverse("procedure_refresh:change_request_set_status", kwargs={"pk": cr.pk})
        resp = self.client.post(url, {
            "status": ChangeRequestStatus.RECEPITA,
            "risposta_gestore": "Recepita nella nuova revisione.",
            "recepita_in_revisione": str(self.rev.pk),
        })
        self.assertEqual(resp.status_code, 302)
        cr.refresh_from_db()
        self.assertEqual(cr.status, ChangeRequestStatus.RECEPITA)
        self.assertEqual(cr.gestita_da, self.manager)
        self.assertIsNotNone(cr.gestita_il)
        self.assertEqual(cr.recepita_in_revisione_id, self.rev.pk)

    def test_change_request_list_requires_manager(self):
        plain = User.objects.create_user(username="crplain", password="pw")
        self.client.force_login(plain)
        resp = self.client.get(reverse("procedure_refresh:change_request_list"))
        # Negato: 302 dal check _is_manager della view o 403 dal middleware ACL.
        self.assertIn(resp.status_code, (302, 403))

    def test_kpi_open_count(self):
        from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest

        ProcedureChangeRequest.objects.create(document=self.doc, created_by=self.reader, testo="a")
        ProcedureChangeRequest.objects.create(
            document=self.doc, created_by=self.reader, testo="b",
            status=ChangeRequestStatus.RESPINTA,
        )
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("procedure_refresh:admin_dashboard"))
        self.assertEqual(resp.context["n_change_requests_open"], 1)


class AclAndUxTests(TestCase):
    """Fase D: gate ACL v2 canonico + separazione presa visione / corpus AI."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username="daclmgr", password="pw", is_superuser=True
        )
        self.doc_pv = ProcedureDocument.objects.create(
            code="MT-PV-001", title="Documento presa visione", document_type="MT",
            is_active=True, requires_acknowledgement=True,
        )
        self.rev_pv = ProcedureRevision.objects.create(
            document=self.doc_pv, revision_code="Rev.01", revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1), source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/pv.pdf", file_name="pv.pdf",
            is_current=True,
        )
        self.doc_rag = ProcedureDocument.objects.create(
            code="MT-RAG-001", title="Documento solo AI", document_type="MT",
            is_active=True, requires_acknowledgement=False,
        )
        ProcedureRevision.objects.create(
            document=self.doc_rag, revision_code="Rev.01", revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1), source_type=SourceType.FILESERVER,
            source_path="C:/share/rag.pdf", file_name="rag.pdf", is_current=True,
        )

    def test_can_manage_via_acl_v2(self):
        """Un utente non-admin ma con permesso canonico ACL v2 accede alla gestione."""
        from core.models import UserOnboarding

        plain = User.objects.create_user(username="daclplain", password="pw")
        UserOnboarding.objects.create(user=plain, skipped=True)  # bypassa il wizard primo accesso
        self.client.force_login(plain)
        with mock.patch("core.acl_v2.check_acl_access_v2", return_value=True), \
             mock.patch("core.middleware.resolve_acl_access", return_value={"allowed": True}):
            resp = self.client.get(reverse("procedure_refresh:document_list"))
        self.assertEqual(resp.status_code, 200)

    def test_lista_unica_mostra_tutti_con_badge(self):
        """Lista unica: presa visione e corpus AI coesistono nella stessa lista."""
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("procedure_refresh:document_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["filtro"], "tutti")
        codes = {d.code for d in resp.context["documents"]}
        self.assertIn("MT-PV-001", codes)
        self.assertIn("MT-RAG-001", codes)  # non più partizionati in tab esclusivi

    def test_lista_filtro_solo_presa_visione(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("procedure_refresh:document_list") + "?filtro=pv")
        codes = {d.code for d in resp.context["documents"]}
        self.assertIn("MT-PV-001", codes)
        self.assertNotIn("MT-RAG-001", codes)

    def test_document_list_search(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("procedure_refresh:document_list") + "?q=PV-001")
        codes = {d.code for d in resp.context["documents"]}
        self.assertEqual(codes, {"MT-PV-001"})

    def test_campaign_picker_include_tutti_i_documenti(self):
        """Il picker mostra TUTTE le revisioni correnti dei documenti attivi:
        la scelta di cosa mettere in campagna si fa al momento della campagna."""
        campaign = ProcedureCampaign.objects.create(
            name="Picker", status=CampaignStatus.DRAFT,
            start_date=date(2026, 1, 1), due_date=date(2026, 12, 31), created_by=self.manager,
        )
        self.client.force_login(self.manager)
        resp = self.client.get(
            reverse("procedure_refresh:campaign_detail", kwargs={"pk": campaign.pk})
        )
        rev_docs = {r.document.code for r in resp.context["available_revisions"]}
        self.assertIn("MT-PV-001", rev_docs)
        self.assertIn("MT-RAG-001", rev_docs)  # ora incluso: si sceglie in campagna

    def test_toggle_marca_badge_presa_visione(self):
        """Il toggle marca/smarca il badge presa-visione (non gatta più il picker)."""
        self.client.force_login(self.manager)
        resp = self.client.post(
            reverse("procedure_refresh:document_toggle_ack", kwargs={"pk": self.doc_rag.pk}),
        )
        self.assertEqual(resp.status_code, 302)
        self.doc_rag.refresh_from_db()
        self.assertTrue(self.doc_rag.requires_acknowledgement)

    def test_toggle_smarca_presa_visione(self):
        """Il toggle è reversibile."""
        self.client.force_login(self.manager)
        self.client.post(
            reverse("procedure_refresh:document_toggle_ack", kwargs={"pk": self.doc_pv.pk}),
        )
        self.doc_pv.refresh_from_db()
        self.assertFalse(self.doc_pv.requires_acknowledgement)

    def test_toggle_richiede_permesso_gestione(self):
        from core.models import UserOnboarding

        plain = User.objects.create_user(username="daclnope", password="pw")
        UserOnboarding.objects.create(user=plain, skipped=True)
        self.client.force_login(plain)
        resp = self.client.post(
            reverse("procedure_refresh:document_toggle_ack", kwargs={"pk": self.doc_rag.pk})
        )
        self.assertIn(resp.status_code, (302, 403))
        self.doc_rag.refresh_from_db()
        self.assertFalse(self.doc_rag.requires_acknowledgement)  # invariato


class ReminderConfigTests(TestCase):
    """Config solleciti presa visione (SiteConfig, pattern tickets_escalation)."""

    def test_defaults(self):
        from procedure_refresh.reminder_config import get_reminder_config

        cfg = get_reminder_config()
        self.assertFalse(cfg["attivo"])
        self.assertEqual(cfg["pre_giorni"], [7, 2])
        self.assertEqual(cfg["post_cadenza_giorni"], 7)
        self.assertEqual(cfg["digest_giorno"], "lun")
        self.assertEqual(cfg["digest_destinatari"], [])

    def test_save_and_parse(self):
        from procedure_refresh.reminder_config import (
            get_reminder_config,
            save_reminder_config,
        )

        save_reminder_config(
            attivo=True,
            pre_giorni="10, 3, abc, 3, 999",
            post_cadenza_giorni="200",
            digest_giorno="VEN",
            digest_destinatari="A@B.it,, a@b.it , c@d.it, nonvalida",
        )
        cfg = get_reminder_config()
        self.assertTrue(cfg["attivo"])
        self.assertEqual(cfg["pre_giorni"], [60, 10, 3])  # 999 clampato a 60
        self.assertEqual(cfg["post_cadenza_giorni"], 60)  # clamp
        self.assertEqual(cfg["digest_giorno"], "ven")
        self.assertEqual(cfg["digest_destinatari"], ["a@b.it", "c@d.it"])

    def test_digest_giorno_invalido_spegne_digest(self):
        from procedure_refresh.reminder_config import (
            get_reminder_config,
            save_reminder_config,
        )

        save_reminder_config(
            attivo=False, pre_giorni="7,2", post_cadenza_giorni=7,
            digest_giorno="xyz", digest_destinatari="",
        )
        self.assertEqual(get_reminder_config()["digest_giorno"], "")


class AssignmentLifecycleTests(TestCase):
    """Motore scadenze: marcatura OVERDUE (sempre) + solleciti (se attivi)."""

    def setUp(self):
        self.manager = User.objects.create_user(
            username="lifemgr", password="pw", is_superuser=True
        )
        self.reader = User.objects.create_user(
            username="lifereader", password="pw", first_name="Mario", last_name="Rossi"
        )
        self.doc = ProcedureDocument.objects.create(
            code="MT-LIFE-001", title="Life doc", document_type="MT", is_active=True
        )
        self.rev = ProcedureRevision.objects.create(
            document=self.doc,
            revision_code="Rev.01",
            revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1),
            source_type=SourceType.SHAREPOINT,
            source_url="https://example.sharepoint.com/life.pdf",
            file_name="life.pdf",
            is_current=True,
        )

    def _campaign(self, due_date):
        return ProcedureCampaign.objects.create(
            name=f"Life {due_date}",
            status=CampaignStatus.PUBLISHED,
            start_date=date(2026, 1, 1),
            due_date=due_date,
            created_by=self.manager,
        )

    def _assignment(self, due_date, status=AssignmentStatus.ASSIGNED):
        campaign = self._campaign(due_date)
        return ProcedureAssignment.objects.create(
            campaign=campaign,
            revision=self.rev,
            user=self.reader,
            assigned_by=self.manager,
            due_date=due_date,
            status=status,
        )

    def _enable_reminders(self, **overrides):
        from procedure_refresh.reminder_config import save_reminder_config

        params = {
            "attivo": True,
            "pre_giorni": "7,2",
            "post_cadenza_giorni": 7,
            "digest_giorno": "",
            "digest_destinatari": "",
        }
        params.update(overrides)
        save_reminder_config(**params)

    def test_overdue_marcato_anche_con_solleciti_spenti(self):
        from procedure_refresh.tasks import run_assignment_lifecycle

        assignment = self._assignment(timezone.localdate() - timedelta(days=3))
        res = run_assignment_lifecycle()
        self.assertTrue(res["ok"])
        self.assertEqual(res["overdue_marked"], 1)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.OVERDUE)
        self.assertTrue(
            assignment.events.filter(event_type=ReadEventType.OVERDUE_MARKED).exists()
        )
        self.assertEqual(len(mail.outbox), 0)  # solleciti spenti: nessuna mail

        # Secondo run: idempotente, nessuna doppia marcatura
        res2 = run_assignment_lifecycle()
        self.assertEqual(res2["overdue_marked"], 0)
        self.assertEqual(
            assignment.events.filter(event_type=ReadEventType.OVERDUE_MARKED).count(), 1
        )

    def test_pre_scadenza_inviata_una_sola_volta(self):
        from procedure_refresh.tasks import run_assignment_lifecycle

        assignment = self._assignment(timezone.localdate() + timedelta(days=7))
        self._enable_reminders()
        with mock.patch(
            "procedure_refresh.tasks._notification_email_map",
            return_value={self.reader.pk: "rossi@test.local"},
        ):
            res = run_assignment_lifecycle()
            self.assertEqual(res["pre_sent"], 1)
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("rossi@test.local", mail.outbox[0].to)
            self.assertIn("MT-LIFE-001", mail.outbox[0].body)

            # Dedup: secondo run stesso giorno, nessun nuovo invio
            res2 = run_assignment_lifecycle()
            self.assertEqual(res2["pre_sent"], 0)
            self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            assignment.events.filter(
                event_type=ReadEventType.REMINDER_SENT,
                meta_json__contains='"kind": "pre7"',
            ).exists()
        )

    def test_post_scadenza_rispetta_cadenza(self):
        from procedure_refresh.tasks import run_assignment_lifecycle

        assignment = self._assignment(
            timezone.localdate() - timedelta(days=2), status=AssignmentStatus.OVERDUE
        )
        self._enable_reminders()
        with mock.patch(
            "procedure_refresh.tasks._notification_email_map",
            return_value={self.reader.pk: "rossi@test.local"},
        ):
            res = run_assignment_lifecycle()
            self.assertEqual(res["post_sent"], 1)
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("SCADUTA", mail.outbox[0].subject)

            res2 = run_assignment_lifecycle()
            self.assertEqual(res2["post_sent"], 0)
            self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            assignment.events.filter(
                event_type=ReadEventType.REMINDER_SENT,
                meta_json__contains='"kind": "post"',
            ).exists()
        )

    def test_digest_gestore_solo_nel_giorno_configurato_e_una_volta(self):
        from procedure_refresh.tasks import _WEEKDAYS, run_assignment_lifecycle

        self._assignment(
            timezone.localdate() - timedelta(days=2), status=AssignmentStatus.OVERDUE
        )
        oggi = _WEEKDAYS[timezone.localdate().weekday()]
        self._enable_reminders(
            post_cadenza_giorni=60,
            digest_giorno=oggi,
            digest_destinatari="qualita@test.local",
        )
        with mock.patch(
            "procedure_refresh.tasks._notification_email_map",
            return_value={self.reader.pk: ""},  # nessuna mail diretta al lettore
        ):
            res = run_assignment_lifecycle()
            self.assertTrue(res["digest_sent"])
            digest = [m for m in mail.outbox if "qualita@test.local" in m.to]
            self.assertEqual(len(digest), 1)
            self.assertIn("MT-LIFE-001", digest[0].body)

            # Stesso giorno: non re-invia
            res2 = run_assignment_lifecycle()
            self.assertFalse(res2["digest_sent"])
            self.assertEqual(
                len([m for m in mail.outbox if "qualita@test.local" in m.to]), 1
            )
