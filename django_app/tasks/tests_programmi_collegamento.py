"""I casi in cui attività e programma potrebbero separarsi."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from django.urls import reverse
from django.utils import timezone

from .models import FaiFase, FaiGruppo, FaiOpzione, FaiRecord, Project, ProjectTechRef, Task, TaskCategory, TaskStatus, TechRefKind
from .services.da_fare import voci_kickoff
from .tests_programmi import ProgrammiBase
from .tests_utils import _create_user_with_legacy, make_project


class CollegamentoTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.fai = TaskCategory.objects.get(richiede=TechRefKind.FAI)
        self.altro = _create_user_with_legacy(username="prog-resp", legacy_user_id=641, role_id=2, role_name="tasks")

    def _dati_fai(self, ref, **altri):
        def primo(gruppo, **filtro):
            return FaiOpzione.objects.filter(gruppo=gruppo, **filtro).first().pk

        return {
            "project": self.project.pk, "ref": ref.pk, "part_number": "PN-1", "client_name": "Cliente Prova",
            "causale": primo(FaiGruppo.CAUSALE, etichetta="Articolo nuovo"), "tipo": "COMPLETO",
            "piano": primo(FaiGruppo.PIANO, etichetta="Interno"),
            "stato": primo(FaiGruppo.STATO, fase=FaiFase.DA_FARE), "responsabile": self.user.pk, **altri,
        }

    # --- Programma svuotato o chiuso a mano
    def test_programma_svuotato_su_attivita_chiusa_torna_da_inserire(self):
        task = self.attivita()
        url = reverse("tasks:task_programma", args=[task.pk])
        self.client.post(url, {"code": "O1", "path": ""})
        task.status = TaskStatus.DONE
        task.save()
        self.assertFalse(ProjectTechRef.objects.get(task=task).is_open)
        self.client.post(url, {"code": "", "path": ""})
        self.assertTrue(ProjectTechRef.objects.get(task=task).is_open)

    def test_da_le_mie_azioni_non_si_chiude_con_attivita_aperta(self):
        ref = self.attivita().tech_ref
        self.client.post(reverse("tasks:mia_voce_stato", args=["programma", ref.pk]), {"action": "done"})
        ref.refresh_from_db()
        self.assertTrue(ref.is_open)

    def test_riga_collegata_si_puo_svuotare_anche_senza_responsabile(self):
        ref = self.attivita(assigned_to=None).tech_ref
        ProjectTechRef.objects.filter(pk=ref.pk).update(code="O1")
        risposta = self.client.post(reverse("tasks:tech_ref_save", args=[self.project.pk]), {
            "ref_id": ref.pk, "kind": "CAM", "code": "", "path": "", "assigned_to": "", "due_date": "",
        })
        self.assertEqual(risposta.status_code, 200)

    # --- Cambi di tipo, commessa, eliminazioni
    def test_tipo_eliminato_stacca_la_riga(self):
        tipo = TaskCategory.objects.create(name="Temporaneo", slug="temporaneo", richiede="CAM")
        task = self.attivita(category=tipo)
        self._diventa_admin()
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "tipi", "cat_action": "category_delete", "category_id": tipo.pk,
        })
        self.assertFalse(TaskCategory.objects.filter(pk=tipo.pk).exists())
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())

    def test_regola_tolta_stacca_anche_le_attivita_chiuse(self):
        tipo = TaskCategory.objects.create(name="Temporaneo", slug="temporaneo", richiede="CAM")
        task = self.attivita(category=tipo, status=TaskStatus.DONE)
        self.assertTrue(ProjectTechRef.objects.filter(task=task).exists())
        self._diventa_admin()
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "tipi", "cat_action": "category_update", "category_id": tipo.pk, "name": tipo.name,
            "is_active": "1", "richiede": "",
        })
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())

    def test_regola_nuova_non_riapre_il_passato(self):
        tipo = TaskCategory.objects.create(name="Temporaneo", slug="temporaneo")
        task = self.attivita(category=tipo, status=TaskStatus.DONE)
        self._diventa_admin()
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "tipi", "cat_action": "category_update", "category_id": tipo.pk, "name": tipo.name,
            "is_active": "1", "richiede": "CAM",
        })
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())

    def test_attivita_spostata_porta_con_se_il_programma(self):
        task = self.attivita()
        ProjectTechRef.objects.filter(task=task).update(code="O1")
        altra = make_project(name="Altra", created_by=self.user, client_name="Cliente Prova", part_number="PN-2")
        task.project = altra
        task.save()
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual((ref.project_id, ref.code), (altra.pk, "O1"))

    def test_attivita_spostata_senza_doppioni_e_senza_incontro_vecchio(self):
        task = self.attivita()
        altra = make_project(name="Altra", created_by=self.user, client_name="Cliente Prova", part_number="PN-2")
        task.project = altra
        task.save()
        self.assertEqual(ProjectTechRef.objects.filter(kind="CAM").count(), 1)
        self.assertFalse(self.project.tech_refs.exists())

    def test_riga_della_riunione_sopravvive_all_attivita(self):
        from .models import KickoffMeeting

        incontro = KickoffMeeting.objects.create(project=self.project, data=date(2026, 11, 1), created_by=self.user)
        riga = ProjectTechRef.objects.create(
            project=self.project, kind="CAM", assigned_to=self.user, source_meeting=incontro, due_date=date(2026, 12, 9),
        )
        task = self.attivita(due_date=None)
        riga.refresh_from_db()
        self.assertEqual(riga.task_id, task.pk)
        self.assertEqual(riga.due_date, date(2026, 12, 9))
        task.delete()
        riga.refresh_from_db()
        self.assertIsNone(riga.task_id)

    def test_attivita_fai_spostata_lascia_la_scheda_e_apre_una_richiesta_nuova(self):
        task = self.attivita(self.fai)
        ref = task.tech_ref
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(ref, piano_numero="P1"))
        altra = make_project(name="Altra", created_by=self.user, client_name="Cliente Prova", part_number="PN-2")
        task.project = altra
        task.save()
        self.assertEqual(FaiRecord.objects.get().project_id, self.project.pk)
        self.assertEqual(self.project.tech_refs.get().code, "P1")
        self.assertIsNone(self.project.tech_refs.get().task_id)
        self.assertEqual(ProjectTechRef.objects.get(task=task).project_id, altra.pk)

    # --- FAI
    def test_fai_il_responsabile_dell_attivita_puo_compilare_la_scheda(self):
        task = self.attivita(self.fai, assigned_to=self.altro)
        self.client.force_login(self.altro)
        ref = task.tech_ref
        url = reverse("tasks:fai_nuovo") + f"?project={self.project.pk}&ref={ref.pk}"
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_fai_resta_una_persona_sola_responsabile(self):
        task = self.attivita(self.fai, assigned_to=self.user)
        ref = task.tech_ref
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(ref, responsabile=self.altro.pk))
        record = FaiRecord.objects.get()
        ref.refresh_from_db()
        self.assertEqual(record.tech_ref_id, ref.pk)
        self.assertEqual(ref.assigned_to, self.user)
        self.assertEqual(record.responsabile, self.user)

    def test_scheda_fai_dall_attivita_parte_dalla_proposta_della_procedura(self):
        task = self.attivita(self.fai)
        pagina = self.client.get(reverse("tasks:detail", args=[task.pk]))
        self.assertContains(pagina, "causale=a")

    def test_fai_eliminato_lascia_la_richiesta_dell_attivita(self):
        task = self.attivita(self.fai)
        ref = task.tech_ref
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(ref, piano_numero="P1"))
        record = FaiRecord.objects.get()
        self.client.post(reverse("tasks:fai_scheda", args=[record.pk]), {"azione": "elimina"})
        riga = ProjectTechRef.objects.get(task=task)
        self.assertEqual(riga.code, "")
        self.assertTrue(riga.is_open)
        self.assertContains(self.client.get(reverse("tasks:detail", args=[task.pk])), "Compila la scheda FAI")

    def test_fai_salvataggi_dell_attivita_non_toccano_lo_stato_scheda(self):
        task = self.attivita(self.fai)
        ref = task.tech_ref
        completo = FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO).exclude(fase=FaiFase.DA_FARE).first()
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(ref, stato=completo.pk))
        record = FaiRecord.objects.get()
        task.title = "Altro titolo"
        task.save()
        record.refresh_from_db()
        self.assertEqual(record.stato_id, completo.pk)

    def test_fai_in_corso_non_viene_chiuso_da_una_modifica_riga(self):
        task = self.attivita(self.fai)
        ref = task.tech_ref
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(ref, piano_numero="P1"))
        task.status = TaskStatus.DONE
        task.save()
        self.client.post(reverse("tasks:tech_ref_save", args=[self.project.pk]), {
            "ref_id": ref.pk, "kind": "FAI", "code": "P2", "path": "", "assigned_to": "", "due_date": "",
        })
        ref.refresh_from_db()
        self.assertTrue(ref.is_open)

    def test_fai_con_scheda_aperta_non_dice_che_manca(self):
        task = self.attivita(self.fai)
        self.client.post(reverse("tasks:fai_nuovo"), self._dati_fai(task.tech_ref, piano_numero="P1"))
        pagina = self.client.post(reverse("tasks:change_status", args=[task.pk]), {"status": TaskStatus.DONE}, follow=True)
        self.assertNotContains(pagina, "non ancora inserito")

    # --- Una voce sola
    def test_home_una_voce_sola(self):
        task = self.attivita()
        richiesta = SimpleNamespace(user=self.user)
        self._voci(richiesta, attese=1)
        task.status = TaskStatus.DONE
        task.save()
        self._voci(richiesta, attese=1)

    def _voci(self, richiesta, attese):
        pagina = self.client.get(reverse("tasks:mie_azioni"))
        voci = voci_kickoff(pagina.wsgi_request)
        self.assertEqual(voci["total"], attese)

    def _diventa_admin(self):
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()


class CopertureTests(ProgrammiBase):
    def test_gantt_e_data_arrivano_alla_riga(self):
        task = self.attivita()
        task.due_date = timezone.localdate() + timedelta(days=30)
        task.save(update_fields=["due_date", "updated_at"])
        self.assertEqual(ProjectTechRef.objects.get(task=task).due_date, task.due_date)

    def test_commessa_eliminata(self):
        task = self.attivita()
        Project.objects.filter(pk=self.project.pk).delete()
        task.refresh_from_db()
        self.assertIsNone(task.project_id)
        self.assertFalse(ProjectTechRef.objects.exists())
        task.save()
        self.assertFalse(ProjectTechRef.objects.exists())

    def test_attivita_senza_tipo_resta_senza_riga(self):
        task = Task.objects.create(title="Generica", project=self.project, created_by=self.user)
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())
