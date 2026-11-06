"""L'attività di programmazione e il programma che deve produrre."""
from __future__ import annotations

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import NavigationItem

from .models import ProjectTechRef, Task, TaskCategory, TaskStatus, TechRefKind, TechRefStatus
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


class ProgrammiBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(username="prog-pm", legacy_user_id=631, role_id=2, role_name="tasks")
        self.client.force_login(self.user)
        self.project = make_project(name="Commessa", created_by=self.user, client_name="Cliente Prova", part_number="PN-1")
        self.cam = TaskCategory.objects.get(richiede=TechRefKind.CAM)
        self.cmm = TaskCategory.objects.get(richiede=TechRefKind.CMM)

    def attivita(self, categoria=None, **altri):
        dati = {
            "title": "Programmare fasi", "project": self.project, "created_by": self.user,
            "assigned_to": self.user, "category": categoria or self.cam, "due_date": date(2026, 12, 1),
        }
        return Task.objects.create(**{**dati, **altri})


class RegolaTests(ProgrammiBase):
    def test_tipi_iniziali(self):
        self.assertEqual(TaskCategory.objects.get(richiede=TechRefKind.FAI).name, "Esecuzione FAI")

    def test_attivita_crea_la_sua_riga(self):
        task = self.attivita()
        ref = task.tech_ref
        self.assertEqual((ref.kind, ref.assigned_to, ref.due_date), ("CAM", self.user, date(2026, 12, 1)))
        self.assertEqual(self.attivita(self.cmm, title="Misura").tech_ref.kind, "CMM")

    def test_salvataggi_non_creano_doppioni(self):
        task = self.attivita()
        task.title = "Nuovo titolo"
        task.save()
        self.assertEqual(ProjectTechRef.objects.filter(project=self.project).count(), 1)

    def test_senza_commessa_o_senza_regola_niente_riga(self):
        self.attivita(project=None)
        self.attivita(category=TaskCategory.objects.create(name="Altro", slug="altro"))
        self.assertFalse(ProjectTechRef.objects.exists())

    def test_adotta_la_riga_assegnata_in_riunione(self):
        libera = ProjectTechRef.objects.create(project=self.project, kind="CAM", code="O1", assigned_to=self.user)
        task = self.attivita()
        self.assertEqual(task.tech_ref.pk, libera.pk)

    def test_non_adotta_la_riga_di_un_altro(self):
        altro = _create_user_with_legacy(username="prog-altro", legacy_user_id=632, role_id=2, role_name="tasks")
        libera = ProjectTechRef.objects.create(project=self.project, kind="CAM", assigned_to=altro)
        self.assertNotEqual(self.attivita().tech_ref.pk, libera.pk)

    def test_responsabile_e_data_seguono_l_attivita(self):
        task = self.attivita()
        task.due_date = date(2027, 1, 2)
        task.assigned_to = None
        task.save()
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual((ref.due_date, ref.assigned_to), (date(2027, 1, 2), None))

    def test_chiusa_senza_programma_resta_da_inserire(self):
        task = self.attivita()
        task.status = TaskStatus.DONE
        task.save()
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual(ref.status, TechRefStatus.OPEN)
        self.client.post(reverse("tasks:task_programma", args=[task.pk]), {"code": "O5", "path": ""})
        ref.refresh_from_db()
        self.assertEqual(ref.status, TechRefStatus.DONE)

    def test_chiusa_con_programma_e_riaperta(self):
        task = self.attivita()
        ProjectTechRef.objects.filter(task=task).update(code="O5")
        task.status = TaskStatus.DONE
        task.save()
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual(ref.status, TechRefStatus.DONE)
        task.status = TaskStatus.TODO
        task.save()
        ref.refresh_from_db()
        self.assertEqual(ref.status, TechRefStatus.OPEN)

    def test_cambio_tipo_e_annullamento(self):
        task = self.attivita()
        task.category = self.cmm
        task.save()
        self.assertEqual(ProjectTechRef.objects.get(task=task).kind, "CMM")
        ProjectTechRef.objects.filter(task=task).update(code="M1")
        task.status = TaskStatus.CANCELED
        task.save()
        ref = ProjectTechRef.objects.get(code="M1")
        self.assertIsNone(ref.task_id)

    def test_attivita_eliminata(self):
        vuota, piena = self.attivita(), self.attivita(self.cmm, title="Misura")
        ProjectTechRef.objects.filter(task=piena).update(code="M1")
        vuota.delete()
        piena.delete()
        self.assertEqual(list(ProjectTechRef.objects.values_list("code", flat=True)), ["M1"])


class VisteTests(ProgrammiBase):
    def test_scheda_chiede_il_programma_e_non_mostra_attrezzatura(self):
        task = self.attivita()
        pagina = self.client.get(reverse("tasks:detail", args=[task.pk]))
        self.assertContains(pagina, "Programma CAM da inserire")
        self.assertIsNone(pagina.context["attrezzatura_embedded_context"])

    def test_scheda_senza_regola_resta_com_era(self):
        task = self.attivita(category=TaskCategory.objects.create(name="Altro", slug="altro"))
        pagina = self.client.get(reverse("tasks:detail", args=[task.pk]))
        self.assertNotContains(pagina, "programma-attivita")
        self.assertIsNotNone(pagina.context["attrezzatura_embedded_context"])

    def test_salva_dall_attivita(self):
        task = self.attivita()
        self.client.post(reverse("tasks:task_programma", args=[task.pk]), {"code": "O9", "path": r"\\server\cam\pn1"})
        ref = ProjectTechRef.objects.get(task=task)
        self.assertEqual((ref.code, ref.path), ("O9", r"\\server\cam\pn1"))
        self.assertContains(self.client.get(reverse("tasks:detail", args=[task.pk])), "Inserito")

    def test_percorso_non_valido(self):
        task = self.attivita()
        self.client.post(reverse("tasks:task_programma", args=[task.pk]), {"code": "O9", "path": "C:\\locale\\x"})
        self.assertEqual(ProjectTechRef.objects.get(task=task).code, "")

    def test_chiusura_avvisa_se_manca(self):
        task = self.attivita()
        pagina = self.client.post(reverse("tasks:change_status", args=[task.pk]), {"status": TaskStatus.DONE}, follow=True)
        self.assertContains(pagina, "non ancora inserito")

    def test_riga_collegata_si_governa_dall_attivita(self):
        task = self.attivita()
        ref = task.tech_ref
        url = reverse("tasks:tech_ref_action", args=[self.project.pk, ref.pk])
        self.assertEqual(self.client.post(url, {"action": "delete"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"action": "done"}).status_code, 400)
        risposta = self.client.post(reverse("tasks:tech_ref_save", args=[self.project.pk]), {
            "ref_id": ref.pk, "kind": "CMM", "code": "O2", "path": "", "assigned_to": "", "due_date": "2030-01-01",
        })
        self.assertEqual(risposta.status_code, 200)
        ref.refresh_from_db()
        self.assertEqual((ref.kind, ref.code, ref.assigned_to, ref.due_date), ("CAM", "O2", self.user, date(2026, 12, 1)))
        self.assertIn("Attività: Programmare fasi", risposta.json()["html"])

    def test_una_voce_sola_tra_le_mie_attivita(self):
        task = self.attivita()
        pagina = self.client.get(reverse("tasks:mie_azioni"))
        self.assertNotContains(pagina, f'data-tr-ref="{task.tech_ref.pk}"')
        task.status = TaskStatus.DONE
        task.save()
        pagina = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(pagina, "Programma CAM")

    def test_impostazioni_regola_allinea_le_attivita_aperte(self):
        tipo = TaskCategory.objects.create(name="Programmazione", slug="programmazione")
        task = self.attivita(category=tipo)
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "tipi", "cat_action": "category_update", "category_id": tipo.pk, "name": tipo.name,
            "is_active": "1", "richiede": "CMM",
        })
        tipo.refresh_from_db()
        self.assertEqual(tipo.richiede, "CMM")
        self.assertEqual(ProjectTechRef.objects.get(task=task).kind, "CMM")
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "tipi", "cat_action": "category_update", "category_id": tipo.pk, "name": tipo.name,
            "is_active": "1", "richiede": "",
        })
        self.assertFalse(ProjectTechRef.objects.filter(task=task).exists())


class RegistroTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        ieri = timezone.localdate() - timedelta(days=1)
        ProjectTechRef.objects.create(project=self.project, kind="CAM", code="O1", path=r"\\server\cam")
        ProjectTechRef.objects.create(project=self.project, kind="CMM", assigned_to=self.user, due_date=ieri)
        ProjectTechRef.objects.create(project=self.project, kind="FAI", code="PFCN-1")
        self.url = reverse("tasks:programmi_registro")

    def test_tutti_i_programmi_e_non_i_fai(self):
        pagina = self.client.get(self.url)
        self.assertEqual(len(pagina.context["righe"]), 2)
        self.assertNotContains(pagina, "PFCN-1")
        self.assertContains(pagina, "Cliente Prova")

    def test_viste_e_ricerca(self):
        conta = lambda **q: len(self.client.get(self.url, q).context["righe"])  # noqa: E731
        self.assertEqual(conta(vista="cam"), 1)
        self.assertEqual(conta(vista="cmm"), 1)
        self.assertEqual(conta(vista="da_inserire"), 1)
        self.assertEqual(conta(vista="ritardo"), 1)
        self.assertEqual(conta(q="o1"), 1)
        self.assertEqual(conta(q="pn-1"), 2)
        self.assertEqual(conta(q="niente"), 0)

    def test_csv(self):
        risposta = self.client.get(self.url, {"formato": "csv"})
        self.assertEqual(risposta.status_code, 200)
        self.assertIn("O1", risposta.content.decode("utf-8"))

    def test_fuori_ambito_non_vede(self):
        altro = _create_user_with_legacy(username="prog-fuori", legacy_user_id=633, role_id=2, role_name="tasks")
        self.client.force_login(altro)
        self.assertEqual(len(self.client.get(self.url).context["righe"]), 0)

    def test_voce_di_menu(self):
        self.assertEqual(NavigationItem.objects.get(code="tasks-sub-programmi").route_name, "tasks:programmi_registro")
