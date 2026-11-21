"""Elenco unico delle attività: filtri a pulsanti, raggruppamento, pagine, nota e collegamenti dalla riga."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import override_settings
from django.urls import reverse

from tasks.models import Task, TaskDependency, TaskStatus
from tasks.services import elenco
from tasks.tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ElencoAttivitaTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.pm = _create_user_with_legacy(username="el-pm", legacy_user_id=571, role_id=2, role_name="tasks")
        self.resp = _create_user_with_legacy(username="el-resp", legacy_user_id=572, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa elenco", created_by=self.pm, project_manager=self.pm)
        self.project.add_team_member("programmers", self.resp)
        self.url = reverse("tasks:project_actions", args=[self.project.pk])
        oggi = date.today()
        self.mia = Task.objects.create(
            title="Programma CAM", project=self.project, created_by=self.pm, assigned_to=self.resp,
            due_date=oggi + timedelta(days=5), description="Dall'incontro #1 (01/11/2026)\nGrezzo nuovo",
        )
        self.ritardo = Task.objects.create(
            title="Ordine materiale", project=self.project, created_by=self.pm, assigned_to=self.pm,
            due_date=oggi - timedelta(days=2),
        )
        self.libera = Task.objects.create(title="Collaudo", project=self.project, created_by=self.pm)
        self.attesa = Task.objects.create(
            title="Verifica disegno", project=self.project, created_by=self.pm, assigned_to=self.resp,
            extra_data={"avviso_con_minuta": 9},
        )

    def _titoli(self, pagina):
        return [r["titolo"] for g in pagina.context["elenco_gruppi"] for r in g["righe"]]

    def test_filtri_a_pulsanti(self):
        self.client.force_login(self.resp)
        casi = {
            "mie": {"Programma CAM", "Verifica disegno"},
            "ritardo": {"Ordine materiale"},
            "da_confermare": {"Verifica disegno"},
            "senza_responsabile": {"Collaudo"},
        }
        for vista, attese in casi.items():
            pagina = self.client.get(self.url, {"vista": vista})
            self.assertEqual(set(self._titoli(pagina)), attese, vista)
        pagina = self.client.get(self.url)
        for etichetta in ("Tutte", "Le mie", "In ritardo", "Da confermare", "Senza responsabile"):
            self.assertContains(pagina, f">{etichetta}</a>")

    def test_raggruppa_per_stato_e_per_responsabile(self):
        self.client.force_login(self.pm)
        gruppi = self.client.get(self.url, {"raggruppa": "stato"}).context["elenco_gruppi"]
        self.assertEqual([g["etichetta"] for g in gruppi], ["In ritardo", "Da fare"])
        gruppi = self.client.get(self.url, {"raggruppa": "responsabile"}).context["elenco_gruppi"]
        self.assertEqual(gruppi[-1]["etichetta"], "Senza responsabile")
        self.assertEqual(sum(len(g["righe"]) for g in gruppi), 4)

    def test_paginazione(self):
        for i in range(elenco.PER_PAGINA + 3):
            Task.objects.create(title=f"Voce {i:02d}", project=self.project, created_by=self.pm)
        self.client.force_login(self.pm)
        prima = self.client.get(self.url)
        self.assertEqual(len(self._titoli(prima)), elenco.PER_PAGINA)
        self.assertContains(prima, "Pagina 1 di 2")
        seconda = self.client.get(self.url, {"pagina": 2})
        self.assertEqual(len(self._titoli(seconda)), 7)

    def test_nota_e_collegamento_dalla_riga(self):
        TaskDependency.objects.create(predecessor=self.ritardo, successor=self.mia)
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url)
        riga = next(r for g in pagina.context["elenco_gruppi"] for r in g["righe"] if r["titolo"] == "Programma CAM")
        self.assertEqual(riga["nota"], "Grezzo nuovo")
        self.assertEqual([d["titolo"] for d in riga["dopo"]], ["Ordine materiale"])
        self.assertContains(pagina, "data-ka-nota-apri")
        self.assertContains(pagina, "data-ka-colleg-riga")
        self.assertContains(pagina, "data-ka-scollega-riga")
        risposta = self.client.post(
            reverse("tasks:task_nota", args=[self.mia.pk]), {"nota": "Grezzo del lotto B"}, HTTP_ACCEPT="application/json",
        )
        self.assertEqual(risposta.json()["ok"], True)
        self.mia.refresh_from_db()
        self.assertEqual(self.mia.description, "Dall'incontro #1 (01/11/2026)\nGrezzo del lotto B")

    def test_l_incaricato_non_collega_e_non_cambia_la_nota_dalla_riga(self):
        self.client.force_login(self.resp)
        pagina = self.client.get(self.url)
        self.assertNotContains(pagina, "data-ka-colleg-riga")
        self.assertNotContains(pagina, "data-ka-nota-apri")
        risposta = self.client.post(
            reverse("tasks:task_nota", args=[self.mia.pk]), {"nota": "x"}, HTTP_ACCEPT="application/json",
        )
        self.assertIn(risposta.status_code, (403, 302))

    def test_stesso_elenco_in_le_mie_attivita_e_nella_dashboard(self):
        self.client.force_login(self.resp)
        mie = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(mie, f'data-ka-riga="{self.mia.pk}"')
        self.assertContains(mie, "data-ka-stato")
        self.assertContains(mie, "Raggruppa")
        dashboard = self.client.get(reverse("tasks:list"))
        self.assertContains(dashboard, f'data-ka-riga="{self.mia.pk}"')
        self.assertContains(dashboard, "Commessa elenco")
        self.assertContains(dashboard, "Raggruppa")

    def test_in_le_mie_attivita_il_motivo_compare_solo_per_chi_chiede(self):
        self.client.force_login(self.resp)
        mie = self.client.get(reverse("tasks:mie_azioni"))
        riga = next(r for g in mie.context["elenco_gruppi"] for r in g["righe"] if r["titolo"] == "Programma CAM")
        self.assertTrue(riga["chiede"])
        self.assertContains(mie, "data-motivo")

    def test_le_annullate_non_si_modificano_dalla_riga(self):
        self.mia.status = TaskStatus.CANCELED
        self.mia.save()
        self.client.force_login(self.pm)
        pagina = self.client.get(self.url, {"closed": "1"})
        riga = next(r for g in pagina.context["elenco_gruppi"] for r in g["righe"] if r["titolo"] == "Programma CAM")
        self.assertFalse(riga["puo"])
