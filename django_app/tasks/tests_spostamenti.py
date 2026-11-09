"""Pieni poteri, spostamenti di date con approvazione, storico e avvisi sui cambiamenti (10/11/2026)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from .models import SpostamentoStato, Task, TaskEvent, TaskEventType, TaskImpostazioni, TaskPriority, TaskSpostamento, TaskStatus
from .tests_utils import TasksBaseTestCase, _create_user_with_legacy, _ensure_role, _grant_role_actions, make_project


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SpostamentiBase(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "tasks")
        _grant_role_actions(2, ["tasks_view", "tasks_create", "tasks_edit"])
        self._refresh_acl_cache()
        self.cc = _create_user_with_legacy(username="sp-cc", legacy_user_id=1011, role_id=2, role_name="tasks")
        self.inc = _create_user_with_legacy(username="sp-inc", legacy_user_id=1012, role_id=2, role_name="tasks")
        self.altro = _create_user_with_legacy(username="sp-altro", legacy_user_id=1013, role_id=2, role_name="tasks")
        self.project = make_project(name="Commessa spostamenti", created_by=self.altro)
        self.project.add_team_member("CC", self.cc)
        self.task = Task.objects.create(
            title="Programmare fresatura", project=self.project, created_by=self.cc, assigned_to=self.inc,
            next_step_due=date(2026, 12, 1), due_date=date(2026, 12, 5), priority=TaskPriority.MEDIUM,
        )
        notify = patch("tasks.services.avvisi.notify_user")
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        mail = patch("tasks.services.avvisi.mail_cambiamento")
        self.mail = mail.start()
        self.addCleanup(mail.stop)
        notify_sp = patch("tasks.services.spostamenti.notify_user")
        self.notify_sp = notify_sp.start()
        self.addCleanup(notify_sp.stop)


class PieniPoteriTests(SpostamentiBase):
    def test_capocommessa_modifica_tutto(self):
        from django.test import RequestFactory

        from .access import can_manage_project, ha_pieni_poteri

        req = RequestFactory().get("/")
        req.user = self.cc
        self.assertTrue(ha_pieni_poteri(req, self.project))
        self.assertTrue(can_manage_project(req, self.project))
        req2 = RequestFactory().get("/")
        req2.user = self.inc
        self.assertFalse(ha_pieni_poteri(req2, self.project))

    def test_persona_scelta_in_impostazioni(self):
        from django.test import RequestFactory

        from .access import ha_pieni_poteri

        TaskImpostazioni.get_singleton().poteri_utenti.add(self.inc)
        req = RequestFactory().get("/")
        req.user = self.inc
        self.assertTrue(ha_pieni_poteri(req, self.project))

    def test_capocommessa_sposta_subito(self):
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-10"})
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 10))
        self.assertFalse(TaskSpostamento.objects.exists())
        # L'incaricato è avvisato del cambiamento.
        self.assertIn(self.inc, [c.args[0] for c in self.notify.call_args_list])


class RichiestaSpostamentoTests(SpostamentiBase):
    def test_incaricato_chiede_e_le_date_non_cambiano(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12", "motivo": "Materiale in ritardo"})
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 5))
        sp = TaskSpostamento.objects.get()
        self.assertEqual((sp.fine_prima, sp.fine_nuovo, sp.motivo), (date(2026, 12, 5), date(2026, 12, 12), "Materiale in ritardo"))
        self.assertTrue(TaskEvent.objects.filter(task=self.task, type=TaskEventType.DATE_REQUEST).exists())
        self.assertIn(self.cc, [c.args[0] for c in self.notify_sp.call_args_list])

    def test_gantt_dell_incaricato_diventa_richiesta(self):
        self.client.force_login(self.inc)
        risposta = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.pk, self.task.pk]), {"mode": "shift", "shift_days": "3"},
        )
        self.assertTrue(risposta.json()["richiesta"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.next_step_due, date(2026, 12, 1))
        self.assertEqual(TaskSpostamento.objects.get().inizio_nuovo, date(2026, 12, 4))

    def test_capocommessa_approva_con_date_diverse(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12"})
        sp = TaskSpostamento.objects.get()
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva", "fine": "2026-12-09", "nota": "Fino al 9"})
        self.task.refresh_from_db()
        sp.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 9))
        self.assertEqual((sp.stato, sp.deciso_da, sp.nota_decisione), (SpostamentoStato.APPROVATA, self.cc, "Fino al 9"))
        self.assertIn(self.inc, [c.args[0] for c in self.notify_sp.call_args_list])
        self.assertTrue(TaskEvent.objects.filter(task=self.task, type=TaskEventType.EDIT).exists())

    def test_rifiuto_e_secondo_capocommessa_vede_gia_deciso(self):
        secondo = _create_user_with_legacy(username="sp-cc2", legacy_user_id=1014, role_id=2, role_name="tasks")
        self.project.add_team_member("CC", secondo)
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12"})
        sp = TaskSpostamento.objects.get()
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "rifiuta"})
        self.client.force_login(secondo)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"})
        sp.refresh_from_db()
        self.assertEqual((sp.stato, sp.deciso_da), (SpostamentoStato.RIFIUTATA, self.cc))
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 5))

    def test_incaricato_non_puo_decidere(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12"})
        sp = TaskSpostamento.objects.get()
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"})
        sp.refresh_from_db()
        self.assertTrue(sp.in_attesa)

    def test_ritiro_e_sostituzione(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12"})
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-14"})
        self.assertEqual(TaskSpostamento.objects.filter(stato=SpostamentoStato.IN_ATTESA).count(), 1)
        sp = TaskSpostamento.objects.get(stato=SpostamentoStato.IN_ATTESA)
        self.client.post(reverse("tasks:spostamento_annulla", args=[sp.pk]))
        sp.refresh_from_db()
        self.assertEqual(sp.stato, SpostamentoStato.ANNULLATA)

    def test_scheda_e_le_mie_azioni(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": "2026-12-12"})
        self.assertContains(self.client.get(reverse("tasks:detail", args=[self.task.pk])), "Ritira la richiesta")
        self.client.force_login(self.cc)
        self.assertContains(self.client.get(reverse("tasks:detail", args=[self.task.pk])), "Approva")
        self.assertContains(self.client.get(reverse("tasks:mie_azioni")), "Spostamenti da decidere")

    def test_incaricato_non_cambia_responsabile_ne_annulla(self):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:change_status", args=[self.task.pk]), {"status": TaskStatus.CANCELED})
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, TaskStatus.CANCELED)


class AvvisiTests(SpostamentiBase):
    def test_destinatari_configurabili(self):
        from .services.avvisi import destinatari

        self.assertEqual({u.pk for u in destinatari(self.task)}, {self.inc.pk, self.cc.pk})
        cfg = TaskImpostazioni.get_singleton()
        cfg.avvisi_destinatari = "INCARICATO"
        cfg.save()
        self.assertEqual({u.pk for u in destinatari(self.task)}, {self.inc.pk})

    def test_cambio_responsabile_avvisa_chi_lo_perde(self):
        from .services.avvisi import notifica_cambiamenti
        from .views._shared import _task_snapshot

        before = _task_snapshot(self.task)
        self.task.assigned_to = self.altro
        self.task.save()
        notifica_cambiamenti(self.task, self.cc, before)
        testi = {c.args[0].pk: c.args[1] for c in self.notify.call_args_list}
        self.assertIn("Non sei più responsabile", testi[self.inc.pk])

    def test_chi_modifica_non_si_avvisa(self):
        from .services.avvisi import notifica_cambiamenti
        from .views._shared import _task_snapshot

        before = _task_snapshot(self.task)
        self.task.priority = TaskPriority.HIGH
        notifica_cambiamenti(self.task, self.cc, before)
        destinatari = [c.args[0].pk for c in self.notify.call_args_list]
        self.assertEqual(destinatari, [self.inc.pk])
        self.assertIn("Priorità: Media → Alta", self.notify.call_args.args[1])

    def test_impostazioni_salvano_poteri_e_avvisi(self):
        self.cc.is_superuser = True
        self.cc.save()
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:impostazioni"), {
            "tab": "poteri", "poteri_ruoli": ["CC"], "avvisi_destinatari": ["INCARICATO", "PM"],
            "poteri_utenti": [str(self.altro.pk)],
        })
        cfg = TaskImpostazioni.get_singleton()
        cfg.refresh_from_db()
        self.assertEqual((cfg.poteri_ruoli, cfg.avvisi_destinatari, cfg.spostamenti_con_approvazione), ("CC", "INCARICATO,PM", False))
        self.assertEqual(list(cfg.poteri_utenti.values_list("pk", flat=True)), [self.altro.pk])
        self.assertContains(self.client.get(reverse("tasks:impostazioni") + "?tab=config"), "Poteri e avvisi")
