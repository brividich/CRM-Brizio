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
