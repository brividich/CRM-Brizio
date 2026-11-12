"""Programmi CAM, CMM e FAI: percorsi, permessi, riepilogo personale."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from .models import MeetingStatus, ProjectTechRef, TechRefStatus
from .tech_paths import href_percorso, normalizza_percorso
from .tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)


class PercorsiTests(SimpleTestCase):
    def test_percorso_di_rete(self):
        self.assertEqual(normalizza_percorso(r' "\\srv\cam\pezzo 1.nc" '), r"\\srv\cam\pezzo 1.nc")
        self.assertEqual(normalizza_percorso("//srv/cam"), r"\\srv\cam")
        self.assertEqual(normalizza_percorso("file://srv/cam/pezzo%201.nc"), r"\\srv\cam\pezzo 1.nc")
        self.assertEqual(normalizza_percorso(""), "")

    def test_indirizzo_web(self):
        self.assertEqual(normalizza_percorso("https://esempio.test/a"), "https://esempio.test/a")

    def test_rifiuti(self):
        for valore in ("javascript:alert(1)", "data:text/html,x", "cartella", r"\\srv", r"\\srv\a\..\b", r"\\srv\a<b"):
            with self.subTest(valore=valore), self.assertRaises(ValueError):
                normalizza_percorso(valore)

    def test_lettera_di_unita_spiega_il_motivo(self):
        with self.assertRaisesMessage(ValueError, "cambiano da PC a PC"):
            normalizza_percorso(r"Y:\cam")

    def test_link(self):
        self.assertEqual(href_percorso(r"\\srv\cam\pezzo 1.nc"), "file://srv/cam/pezzo%201.nc")
        self.assertEqual(href_percorso("https://esempio.test/a"), "https://esempio.test/a")
        self.assertEqual(href_percorso(""), "")


class TechRefViewTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.manager, self.programmatore, self.estraneo = (
            _create_user_with_legacy(username=nome, legacy_user_id=id_legacy, role_id=2, role_name="tasks")
            for nome, id_legacy in (("kt-manager", 611), ("kt-prg", 612), ("kt-altro", 613))
        )
        self.project = make_project(name="Commessa esempio", created_by=self.manager, programmer=self.programmatore)
        self.save_url = reverse("tasks:tech_ref_save", args=[self.project.pk])

    def _salva(self, **dati):
        return self.client.post(self.save_url, {"kind": "CAM", **dati}, HTTP_ACCEPT="application/json")

    def test_piu_codici_con_lo_stesso_tipo(self):
        self.client.force_login(self.manager)
        for codice in ("O1001", "O1002"):
            self.assertEqual(self._salva(code=codice).status_code, 200)
        self.assertEqual(self.project.tech_refs.filter(kind="CAM").count(), 2)

    def test_tutto_facoltativo_ma_la_riga_deve_dire_qualcosa(self):
        self.client.force_login(self.manager)
        self.assertEqual(self._salva().status_code, 400)
        self.assertEqual(self._salva(assigned_to=self.programmatore.pk).status_code, 200)
        self.assertEqual(self.project.tech_refs.get().code, "")

    def test_percorso_non_valido_non_si_salva(self):
        self.client.force_login(self.manager)
        risposta = self._salva(code="O1", path="javascript:alert(1)")
        self.assertEqual(risposta.status_code, 400)
        self.assertFalse(self.project.tech_refs.exists())

    def test_responsabile_compila_ma_non_passa_la_riga_ad_altri(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind="CMM", assigned_to=self.programmatore)
        self.client.force_login(self.programmatore)
        risposta = self._salva(ref_id=ref.pk, kind="CMM", code="C-7", assigned_to=self.estraneo.pk)
        self.assertEqual(risposta.status_code, 200)
        ref.refresh_from_db()
        self.assertEqual(ref.code, "C-7")
        self.assertEqual(ref.assigned_to, self.programmatore)

    def test_estraneo_non_aggiunge_ne_modifica(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind="FAI", code="P1")
        self.client.force_login(self.estraneo)
        for dati in ({"code": "X"}, {"ref_id": ref.pk, "code": "X"}):
            risposta = self._salva(**dati)
            self.assertIn(risposta.status_code, (403, 404), dati)
        ref.refresh_from_db()
        self.assertEqual(ref.code, "P1")

    def test_elimina_solo_chi_gestisce(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind="FAI", assigned_to=self.programmatore)
        url = reverse("tasks:tech_ref_action", args=[self.project.pk, ref.pk])
        self.client.force_login(self.programmatore)
        self.assertEqual(self.client.post(url, {"action": "delete"}).status_code, 403)
        self.assertEqual(self.client.post(url, {"action": "done"}).status_code, 200)
        ref.refresh_from_db()
        self.assertEqual(ref.status, TechRefStatus.DONE)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(url, {"action": "delete"}).status_code, 200)
        self.assertFalse(ProjectTechRef.objects.filter(pk=ref.pk).exists())

    def test_riga_inserita_in_incontro_si_vede_in_commessa(self):
        meeting = self.project.meetings.create(numero=1, data=timezone.localdate(), stato=MeetingStatus.PIANIFICATO)
        self.client.force_login(self.manager)
        self.assertEqual(self._salva(code="O9", meeting_id=meeting.pk).status_code, 200)
        self.assertEqual(self.project.tech_refs.get().source_meeting, meeting)
        pagina = self.client.get(reverse("tasks:project_tech_refs", args=[self.project.pk]))
        self.assertContains(pagina, "O9")
        self.assertContains(pagina, "Incontro 1")
        incontro = self.client.get(reverse("tasks:project_meeting_detail", args=[self.project.pk, meeting.pk]))
        self.assertContains(incontro, "O9")

    def test_le_mie_azioni_e_le_mie_attivita(self):
        ieri = timezone.localdate() - timedelta(days=1)
        ProjectTechRef.objects.create(
            project=self.project, kind="CAM", code="O-SCADUTO", path=r"\\srv\cam", assigned_to=self.programmatore, due_date=ieri,
        )
        ProjectTechRef.objects.create(project=self.project, kind="CMM", code="DI-ALTRI", assigned_to=self.manager)
        self.client.force_login(self.programmatore)
        mie = self.client.get(reverse("tasks:mie_azioni"))
        self.assertContains(mie, "O-SCADUTO")
        self.assertContains(mie, "file://srv/cam")
        self.assertNotContains(mie, "DI-ALTRI")
        attivita = self.client.get(reverse("mie_attivita"))
        self.assertContains(attivita, "O-SCADUTO")
        self.assertContains(attivita, "Scaduta")

    def test_mia_voce_stato_chiude_il_programma(self):
        ref = ProjectTechRef.objects.create(project=self.project, kind="CAM", assigned_to=self.programmatore)
        self.client.force_login(self.programmatore)
        self.client.post(reverse("tasks:mia_voce_stato", args=["programma", ref.pk]), {"action": "done"})
        ref.refresh_from_db()
        self.assertEqual(ref.status, TechRefStatus.DONE)

    def test_notifica_al_responsabile(self):
        self.client.force_login(self.manager)
        # La riga assegnata diventa un'attività: l'avviso è quello dell'attività (portale + mail).
        with patch("tasks.services.meeting_tasks.notify_user") as notify,                 patch("tasks.services.meeting_tasks._mail_assegnazione") as mail:
            self.assertEqual(self._salva(code="O1", assigned_to=self.programmatore.pk).status_code, 200)
            self.assertEqual(self._salva(code="O2", assigned_to=self.manager.pk).status_code, 200)
        notify.assert_called_once()
        mail.assert_called_once()
        self.assertIn("O1", notify.call_args.args[1])

    def test_notifica_riga_senza_tipo_attivita(self):
        """Nessun tipo «richiede» CAM: resta la riga semplice con l'avviso di prima."""
        from .models import TaskCategory

        TaskCategory.objects.filter(richiede="CAM").update(richiede="")
        self.client.force_login(self.manager)
        with patch("tasks.views.tech_refs.notify_user") as notify:
            self.assertEqual(self._salva(code="O1", assigned_to=self.programmatore.pk).status_code, 200)
        notify.assert_called_once()
        self.assertIsNone(self.project.tech_refs.get().task_id)

    def test_rotte_con_binding_canonico(self):
        """Con ACL_STRICT_CANONICAL una rotta senza binding viene negata in produzione."""
        from core.models import RoutePermissionBinding

        from .acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)
        for nome in ("tasks:project_tech_refs", "tasks:tech_ref_save", "tasks:tech_ref_action"):
            self.assertTrue(RoutePermissionBinding.objects.filter(route_name=nome).exists(), nome)

    def test_riepilogo_conta_e_chiude_dalla_riga(self):
        ieri = timezone.localdate() - timedelta(days=1)
        ref = ProjectTechRef.objects.create(
            project=self.project, kind="CAM", code="O-RIGA", assigned_to=self.programmatore, due_date=ieri,
        )
        self.client.force_login(self.programmatore)
        pagina = self.client.get(reverse("mie_attivita"))
        self.assertEqual(pagina.context["total_overdue"], 1)
        self.assertEqual(pagina.context["total_open"], 1)
        self.assertContains(pagina, reverse("tasks:mia_voce_stato", args=["programma", ref.pk]))
        risposta = self.client.post(
            reverse("tasks:mia_voce_stato", args=["programma", ref.pk]), {"action": "done"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(risposta.json()["ok"], True)
        self.assertEqual(self.client.get(reverse("mie_attivita")).context["total_open"], 0)

    def test_azione_non_contata_due_volte(self):
        from django.core.cache import cache

        from .models import MeetingActionItem

        cache.clear()
        MeetingActionItem.objects.create(
            project=self.project, title="Azione unica", assigned_to=self.programmatore,
            due_date=timezone.localdate() + timedelta(days=1),
        )
        self.client.force_login(self.programmatore)
        pagina = self.client.get(reverse("mie_attivita"))
        self.assertEqual(pagina.context["total_open"], 1)
        self.assertEqual(pagina.context["total_soon"], 1)
