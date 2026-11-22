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


class CascataApprovazioneTests(SpostamentiBase):
    """Approvando uno spostamento le successive collegate seguono (solo in avanti) e chi decide lo vede prima."""

    def setUp(self):
        super().setUp()
        from .models import TaskDependency

        self.dopo = Task.objects.create(
            title="Collaudo fresatura", project=self.project, created_by=self.cc, assigned_to=self.altro,
            next_step_due=date(2026, 12, 6), due_date=date(2026, 12, 10),
        )
        self.poi = Task.objects.create(
            title="Imballo", project=self.project, created_by=self.cc,
            next_step_due=date(2026, 12, 11), due_date=date(2026, 12, 12),
        )
        TaskDependency.objects.create(predecessor=self.task, successor=self.dopo)
        TaskDependency.objects.create(predecessor=self.dopo, successor=self.poi)

    def _chiedi(self, fine: str):
        self.client.force_login(self.inc)
        self.client.post(reverse("tasks:update_due_date", args=[self.task.pk]), {"due_date": fine})
        return TaskSpostamento.objects.get(stato=SpostamentoStato.IN_ATTESA)

    def _date(self, task):
        task.refresh_from_db()
        return task.next_step_due, task.due_date

    def test_anteprima_calcola_senza_salvare(self):
        from .services.spostamenti import anteprima

        sp = self._chiedi("2026-12-08")
        righe = anteprima(sp)
        self.assertEqual([(r["task"].pk, r["giorni"]) for r in righe], [(self.dopo.pk, 3), (self.poi.pk, 3)])
        self.assertEqual((righe[0]["inizio_prima"], righe[0]["inizio_nuovo"]), (date(2026, 12, 6), date(2026, 12, 9)))
        self.assertEqual((righe[0]["fine_prima"], righe[0]["fine_nuovo"]), (date(2026, 12, 10), date(2026, 12, 13)))
        # Solo calcolo: nel database non cambia niente.
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))
        self.assertEqual(self._date(self.poi), (date(2026, 12, 11), date(2026, 12, 12)))
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 5)))

    def test_approvazione_sposta_le_successive_e_avvisa(self):
        sp = self._chiedi("2026-12-08")
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))  # finché non si approva, ferme
        self.notify.reset_mock()
        self.client.force_login(self.cc)
        risposta = self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"}, follow=True)
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 8)))
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 9), date(2026, 12, 13)))  # durata invariata
        self.assertEqual(self._date(self.poi), (date(2026, 12, 14), date(2026, 12, 15)))
        # Storico e avviso anche sull'attività spostata a cascata.
        evento = TaskEvent.objects.get(task=self.dopo, type=TaskEventType.EDIT)
        self.assertEqual(evento.actor, self.cc)
        self.assertEqual(evento.payload["changes"]["due_date"], {"from": "2026-12-10", "to": "2026-12-13"})
        self.assertIn(self.altro, [c.args[0] for c in self.notify.call_args_list])
        self.assertContains(risposta, "Spostate in avanti per rispettare le dipendenze: «Collaudo fresatura», «Imballo».")

    def test_approvazione_con_date_diverse_usa_quelle_per_la_cascata(self):
        sp = self._chiedi("2026-12-08")
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva", "fine": "2026-12-06"})
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 6)))
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 7), date(2026, 12, 11)))

    def test_anticipo_non_tira_indietro_le_successive(self):
        from .services.spostamenti import anteprima

        sp = self._chiedi("2026-12-03")
        self.assertEqual(anteprima(sp), [])
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"})
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 3)))
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))
        self.assertFalse(TaskEvent.objects.filter(task=self.dopo, type=TaskEventType.EDIT).exists())

    def test_rifiuto_non_sposta_niente(self):
        sp = self._chiedi("2026-12-08")
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "rifiuta"})
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 5)))
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))

    def test_successiva_chiusa_resta_ferma(self):
        Task.objects.filter(pk=self.dopo.pk).update(status=TaskStatus.DONE)
        sp = self._chiedi("2026-12-08")
        self.client.force_login(self.cc)
        self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"})
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))

    def test_errore_nella_cascata_annulla_tutta_l_approvazione(self):
        sp = self._chiedi("2026-12-08")
        self.client.force_login(self.cc)
        with patch("tasks.services.spostamenti.propaga_dipendenze", side_effect=RuntimeError("test/boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("tasks:spostamento_decidi", args=[sp.pk]), {"decisione": "approva"})
        sp.refresh_from_db()
        self.assertTrue(sp.in_attesa)
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 5)))

    def test_chi_decide_vede_l_anteprima_dove_approva(self):
        self._chiedi("2026-12-08")
        # Il richiedente non decide: niente anteprima.
        self.assertNotContains(self.client.get(reverse("tasks:detail", args=[self.task.pk])), "Approvando si spostano in avanti anche")
        self.client.force_login(self.cc)
        for nome, args in (("tasks:detail", [self.task.pk]), ("tasks:mie_azioni", [])):
            pagina = self.client.get(reverse(nome, args=args))
            self.assertContains(pagina, "Approvando si spostano in avanti anche")
            self.assertContains(pagina, "Collaudo fresatura")
            self.assertContains(pagina, "+3 giorni")
            self.assertContains(pagina, "09/12–13/12")

    def test_senza_successive_niente_riquadro(self):
        from .models import TaskDependency

        TaskDependency.objects.all().delete()
        self._chiedi("2026-12-08")
        self.client.force_login(self.cc)
        self.assertNotContains(self.client.get(reverse("tasks:detail", args=[self.task.pk])), "Approvando si spostano in avanti anche")

    def test_gantt_dell_incaricato_richiesta_in_json_e_successive_ferme(self):
        self.client.force_login(self.inc)
        risposta = self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.pk, self.task.pk]),
            {"mode": "shift", "shift_days": "3"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        dati = risposta.json()
        self.assertTrue(dati["ok"] and dati["richiesta"])
        self.assertIn("inviato al capocommessa", dati["messaggio"])
        # Il messaggio a comparsa parte con la risposta (niente ricarica della pagina).
        self.assertIn("inviato al capocommessa", risposta.headers.get("X-Hub-Flash", ""))
        self.assertNotIn("attivita", dati)
        self.assertEqual(self._date(self.task), (date(2026, 12, 1), date(2026, 12, 5)))
        self.assertEqual(self._date(self.dopo), (date(2026, 12, 6), date(2026, 12, 10)))

    def test_incaricato_senza_permesso_di_modifica_puo_trascinare_la_sua_barra(self):
        _ensure_role(3, "tasks-lettura")
        _grant_role_actions(3, ["tasks_view"])
        self._refresh_acl_cache()
        lettore = _create_user_with_legacy(username="sp-lettore", legacy_user_id=1015, role_id=3, role_name="tasks-lettura")
        mia = Task.objects.create(
            title="Attività del lettore", project=self.project, created_by=self.cc, assigned_to=lettore,
            next_step_due=date(2026, 12, 1), due_date=date(2026, 12, 2),
        )
        self.client.force_login(lettore)
        pagina = self.client.get(reverse("tasks:project_gantt", args=[self.project.pk])).content.decode()
        url_mia = reverse("tasks:project_gantt_shift_task", args=[self.project.pk, mia.pk])
        url_altrui = reverse("tasks:project_gantt_shift_task", args=[self.project.pk, self.dopo.pk])
        self.assertIn(f'data-shift-url="{url_mia}"', pagina)
        self.assertNotIn(f'data-shift-url="{url_altrui}"', pagina)
        # Il server decide: sull'attività di un altro risponde 403 in JSON.
        negata = self.client.post(url_altrui, {"shift_days": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(negata.status_code, 403)
        self.assertEqual(negata.json()["ok"], False)
