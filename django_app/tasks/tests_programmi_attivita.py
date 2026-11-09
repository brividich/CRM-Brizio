"""Riga assegnata in «Programmi e FAI» = attività del kickoff (09/11/2026)."""
from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from .models import KickoffMeeting, ProjectTechRef, Task, TaskStatus, TechRefKind
from .tests_programmi import ProgrammiBase
from .tests_utils import _create_user_with_legacy


class RigaDiventaAttivitaTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.altro = _create_user_with_legacy(username="prog-dest", legacy_user_id=651, role_id=2, role_name="tasks")
        self.url = reverse("tasks:tech_ref_save", args=[self.project.pk])

    def _salva(self, **dati):
        return self.client.post(self.url, {"kind": "CAM", **dati}, HTTP_ACCEPT="application/json")

    def test_riga_assegnata_crea_attivita_collegata(self):
        with patch("tasks.services.meeting_tasks._mail_assegnazione") as mail:
            risposta = self._salva(code="O1", assigned_to=self.altro.pk, due_date="2026-12-01")
        self.assertEqual(risposta.status_code, 200)
        ref = self.project.tech_refs.get()
        task = ref.task
        self.assertIsNotNone(task)
        self.assertEqual((task.category, task.assigned_to, task.due_date), (self.cam, self.altro, date(2026, 12, 1)))
        self.assertEqual(task.title, f"{self.cam.name} O1")
        self.assertEqual(task.status, TaskStatus.TODO)
        mail.assert_called_once()
        # Una riga sola: l'attività non se ne crea un'altra.
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project).count(), 1)

    def test_senza_responsabile_resta_riga_semplice(self):
        self._salva(code="O1")
        self.assertIsNone(self.project.tech_refs.get().task_id)
        self.assertFalse(Task.objects.exists())

    def test_assegnata_dopo_crea_attivita(self):
        self._salva(code="O1")
        ref = self.project.tech_refs.get()
        self._salva(ref_id=ref.pk, code="O1", assigned_to=self.altro.pk)
        ref.refresh_from_db()
        self.assertEqual(ref.task.assigned_to, self.altro)
        self.assertEqual(Task.objects.count(), 1)

    def test_riga_libera_piu_vecchia_non_viene_presa(self):
        """L'attività si aggancia alla riga che l'ha chiesta, non alla prima libera."""
        vecchia = ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.CAM, code="VECCHIA")
        self._salva(code="NUOVA", assigned_to=self.altro.pk)
        nuova = self.project.tech_refs.get(code="NUOVA")
        vecchia.refresh_from_db()
        self.assertIsNotNone(nuova.task_id)
        self.assertIsNone(vecchia.task_id)

    def test_fai_dall_incontro_entra_nelle_attivita_dell_incontro(self):
        meeting = KickoffMeeting.objects.create(project=self.project, numero=1, data=timezone.now())
        self.client.post(self.url, {
            "kind": "FAI", "assigned_to": self.altro.pk, "meeting_id": meeting.pk,
        }, HTTP_ACCEPT="application/json")
        task = self.project.tech_refs.get().task
        self.assertEqual(task.category.richiede, TechRefKind.FAI)
        self.assertTrue(task.description.startswith("Dall'incontro #1 ("))

    def test_attivita_completata_chiude_la_riga(self):
        self._salva(code="O1", assigned_to=self.altro.pk)
        ref = self.project.tech_refs.get()
        task = ref.task
        task.status = TaskStatus.DONE
        task.save()
        ref.refresh_from_db()
        self.assertFalse(ref.is_open)

    def test_comando_aggancia_le_righe_esistenti(self):
        ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.CMM, assigned_to=self.altro)
        ProjectTechRef.objects.create(project=self.project, kind=TechRefKind.CAM)  # senza responsabile
        out = StringIO()
        call_command("aggancia_attivita_programmi", "--dry-run", stdout=out)
        self.assertFalse(Task.objects.exists())
        with patch("tasks.services.meeting_tasks._mail_assegnazione") as mail:
            call_command("aggancia_attivita_programmi", stdout=out)
        mail.assert_not_called()
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(Task.objects.get().category, self.cmm)
