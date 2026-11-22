"""Gantt: sovrapposizioni libere, dipendenze esplicite, ordine delle righe, priorità e chi modifica cosa."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import override_settings
from django.urls import reverse

from .models import (
    DependencyType,
    Task,
    TaskAccessLevel,
    TaskDependency,
    TaskPriority,
    TaskRoleAccessRule,
    TaskRoleType,
    TaskStatus,
)
from .services.gantt_piano import inizio_minimo, ordina_piano
from .tests_utils import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
    make_project,
)

D0 = date(2027, 3, 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GanttPianoTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        # Comportamento senza approvazione degli spostamenti (coperto con approvazione in tests_spostamenti).
        from tasks.models import TaskImpostazioni
        TaskImpostazioni.objects.update_or_create(pk=TaskImpostazioni.get_singleton().pk, defaults={"spostamenti_con_approvazione": False})
        _ensure_role(2, "utente")
        _grant_role_actions(2, ["tasks_view", "tasks_edit", "tasks_comment"])
        self._refresh_acl_cache()
        self.owner = _create_user_with_legacy(username="gp_owner", legacy_user_id=6101, role_id=2, role_name="utente")
        self.prog = _create_user_with_legacy(username="gp_prog", legacy_user_id=6102, role_id=2, role_name="utente")
        self.altro = _create_user_with_legacy(username="gp_altro", legacy_user_id=6103, role_id=2, role_name="utente")
        self.project = make_project(name="Piano", created_by=self.owner, programmer=self.prog)
        TaskRoleAccessRule.objects.create(role_type=TaskRoleType.PROGRAMMER, access_level=TaskAccessLevel.EDIT_ASSIGNED)
        self.a = self._task("A", 0, 4, assegnato=self.prog)
        self.b = self._task("B", 5, 9, assegnato=self.prog)
        self.c = self._task("C", 10, 12)

    def _task(self, titolo, da, a, assegnato=None):
        return Task.objects.create(
            title=titolo,
            created_by=self.owner,
            assigned_to=assegnato,
            project=self.project,
            status=TaskStatus.TODO,
            next_step_due=D0 + timedelta(days=da),
            due_date=D0 + timedelta(days=a),
        )

    def _shift(self, task, giorni, utente=None, **extra):
        self.client.force_login(utente or self.owner)
        return self.client.post(
            reverse("tasks:project_gantt_shift_task", args=[self.project.id, task.id]),
            {"shift_days": str(giorni), **extra},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    # ── Sovrapposizioni e dipendenze ──

    def test_attivita_senza_dipendenze_si_sovrappongono(self):
        resp = self._shift(self.b, -4)
        self.assertEqual(resp.status_code, 200)
        self.b.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=1))  # dentro A: ammesso
        self.a.refresh_from_db()
        self.assertEqual(self.a.next_step_due, D0)

    def test_spostare_una_barra_non_trascina_chi_non_dipende(self):
        self._shift(self.a, 8)
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=5))
        self.assertEqual(self.c.next_step_due, D0 + timedelta(days=10))

    def test_dipendenza_fs_trattiene_e_trascina(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b, dependency_type=DependencyType.FS)
        self._shift(self.b, -4)
        self.b.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=5))  # non prima della fine di A + 1
        self._shift(self.a, 3)
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=8))
        self.assertEqual(self.b.due_date, D0 + timedelta(days=12))  # durata invariata
        self.assertEqual(self.c.next_step_due, D0 + timedelta(days=10))

    def test_catena_di_dipendenze_si_propaga(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        TaskDependency.objects.create(predecessor=self.b, successor=self.c)
        self._shift(self.a, 6)
        self.c.refresh_from_db()
        self.assertEqual(self.c.next_step_due, D0 + timedelta(days=16))

    def test_dipendenza_circolare_rifiutata(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        TaskDependency.objects.create(predecessor=self.b, successor=self.c)
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("tasks:project_gantt_add_dependency", args=[self.project.id]),
            {"predecessor_id": self.c.id, "successor_id": self.a.id, "dependency_type": "FS"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(TaskDependency.objects.filter(predecessor=self.c, successor=self.a).exists())

    def test_nuova_dipendenza_sposta_subito_la_successiva(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("tasks:project_gantt_add_dependency", args=[self.project.id]),
            {"predecessor_id": self.b.id, "successor_id": self.a.id, "dependency_type": "FS"},
        )
        self.assertEqual(resp.json()["moved"], 1)
        self.a.refresh_from_db()
        self.assertEqual(self.a.next_step_due, D0 + timedelta(days=10))

    def test_inizio_minimo_ss_e_ff(self):
        per_id = {self.a.id: self.a, self.b.id: self.b}
        ss = TaskDependency(predecessor=self.a, successor=self.b, dependency_type=DependencyType.SS, lag_days=2)
        self.assertEqual(inizio_minimo(self.b, [ss], per_id), D0 + timedelta(days=2))
        ff = TaskDependency(predecessor=self.a, successor=self.b, dependency_type=DependencyType.FF)
        # B dura 4 giorni e deve finire non prima della fine di A (giorno 4): può iniziare dal giorno 0.
        self.assertEqual(inizio_minimo(self.b, [ff], per_id), D0)

    # ── Ordine delle righe ──

    def test_nuova_attivita_va_in_fondo_e_le_frecce_cambiano_ordine(self):
        self.assertEqual([t.title for t in ordina_piano(self.project.tasks.all())], ["A", "B", "C"])
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("tasks:project_gantt_move_task", args=[self.project.id, self.c.id]), {"direzione": "su"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual([t.title for t in ordina_piano(self.project.tasks.all())], ["A", "C", "B"])
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "2. C")

    def test_ordine_lo_cambia_solo_il_responsabile_del_kickoff(self):
        self.client.force_login(self.prog)
        resp = self.client.post(
            reverse("tasks:project_gantt_move_task", args=[self.project.id, self.b.id]), {"direzione": "su"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual([t.title for t in ordina_piano(self.project.tasks.all())], ["A", "B", "C"])

    # ── Priorità e chi modifica cosa ──

    def _update(self, task, utente, **campi):
        self.client.force_login(utente)
        dati = {
            f"task_{task.id}-next_step_due": task.next_step_due.isoformat(),
            f"task_{task.id}-due_date": task.due_date.isoformat(),
            f"task_{task.id}-status": task.status,
        }
        dati.update({f"task_{task.id}-{k}": v for k, v in campi.items()})
        return self.client.post(reverse("tasks:project_gantt_update_task", args=[self.project.id, task.id]), dati)

    def test_priorita_la_cambia_il_responsabile_del_kickoff(self):
        self._update(self.a, self.owner, priority=TaskPriority.HIGH)
        self.a.refresh_from_db()
        self.assertEqual(self.a.priority, TaskPriority.HIGH)

    def test_assegnatario_con_modifica_cambia_stato_ma_non_priorita(self):
        resp = self._update(self.a, self.prog, priority=TaskPriority.HIGH, status=TaskStatus.IN_PROGRESS)
        self.assertEqual(resp.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.a.priority, TaskPriority.MEDIUM)

    def test_pagina_mostra_il_livello_e_i_pulsanti_giusti(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "Chi può modificare cosa")
        self.assertContains(resp, "Tu: Responsabile del kickoff")
        self.assertContains(resp, 'name="direzione"')
        self.assertContains(resp, f'name="task_{self.a.id}-priority"')

        self.client.force_login(self.prog)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "Tu: Ruolo con permesso di modifica")
        self.assertNotContains(resp, 'name="direzione"')
        self.assertNotContains(resp, f'name="task_{self.a.id}-priority"')

    def test_responsabile_senza_permesso_aggiorna_solo_lo_stato(self):
        d = self._task("D", 2, 3, assegnato=self.altro)
        self.client.force_login(self.altro)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "Tu: Responsabile dell")
        self.assertContains(resp, reverse("tasks:mia_voce_stato", args=["attivita", d.id]))
        self.assertNotContains(resp, f'name="task_{d.id}-due_date"')

    def test_sovrapposizione_stessa_persona_segnalata(self):
        self.b.next_step_due = D0 + timedelta(days=2)
        self.b.save()
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "insieme a 2")
        self.assertContains(resp, "insieme a 1")

    def test_riga_mostra_da_chi_dipende(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.c, dependency_type=DependencyType.SS)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        self.assertContains(resp, "dopo 1 SS")

    # ── Spostamento senza ricarica: la risposta JSON porta lo stato del diagramma ──

    def test_spostamento_risponde_con_le_attivita_cambiate(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        dati = self._shift(self.a, 3).json()
        self.assertTrue(dati["ok"])
        self.assertEqual(dati["cascade_count"], 1)
        per_id = {r["id"]: r for r in dati["attivita"]}
        self.assertEqual(set(per_id), {self.a.id, self.b.id})  # la C non dipende: non è fra le cambiate
        self.assertFalse(per_id[self.a.id]["cascata"])
        self.assertTrue(per_id[self.b.id]["cascata"])
        self.assertEqual(
            (per_id[self.b.id]["inizio"], per_id[self.b.id]["fine"]),
            ((D0 + timedelta(days=8)).isoformat(), (D0 + timedelta(days=12)).isoformat()),
        )
        # Posizione nel diagramma: la B parte il giorno dopo la fine della A.
        self.assertEqual(per_id[self.b.id]["start_index"], per_id[self.a.id]["start_index"] + per_id[self.a.id]["span"])
        righe = {r["id"]: r for r in dati["righe"]}
        self.assertEqual(set(righe), {self.a.id, self.b.id, self.c.id})
        self.assertIn(f"{D0 + timedelta(days=8):%d/%m} → {D0 + timedelta(days=12):%d/%m}", righe[self.b.id]["meta_html"])
        self.assertIn("dopo 1", righe[self.b.id]["meta_html"])
        self.assertEqual(set(dati["numeri"]), {"scadute", "in_7_giorni", "da_controllare"})
        self.assertEqual(set(dati["finestra"]), {"inizio", "giorni"})

    def test_senza_cascata_cambia_solo_la_barra_mossa(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        dati = self._shift(self.a, 3, cascade="0").json()
        self.assertEqual([r["id"] for r in dati["attivita"]], [self.a.id])
        self.b.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=5))

    def test_finestra_della_risposta_uguale_a_quella_della_pagina(self):
        self.client.force_login(self.owner)
        url = reverse("tasks:project_gantt_shift_task", args=[self.project.id, self.b.id]) + "?window_days=62"
        dati = self.client.post(url, {"shift_days": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        pagina = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]) + "?window_days=62")
        self.assertEqual(dati["finestra"]["giorni"], len(pagina.context["gantt_days"]))
        self.assertEqual(dati["finestra"]["inizio"], pagina.context["gantt_timeline_start"].isoformat())
        self.assertContains(pagina, f'data-inizio="{dati["finestra"]["inizio"]}" data-giorni="{dati["finestra"]["giorni"]}"')

    def test_pagina_espone_dipendenze_e_parti_aggiornabili(self):
        import html
        import json
        import re

        TaskDependency.objects.create(predecessor=self.a, successor=self.b, dependency_type=DependencyType.SS, lag_days=2)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("tasks:project_gantt", args=[self.project.id]))
        deps = json.loads(html.unescape(re.search(r'data-deps="([^"]*)"', resp.content.decode()).group(1)))
        self.assertEqual(deps, [{"p": self.a.id, "s": self.b.id, "t": "SS", "lag": 2}])
        for regione in ("diagramma", "numeri", "rapida", "dipendenze"):
            self.assertContains(resp, f'data-g-region="{regione}"')
        self.assertContains(resp, f'data-ini="{D0:%Y-%m-%d}"')

    def test_messaggio_della_cascata_arriva_con_la_risposta(self):
        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        resp = self._shift(self.a, 3)
        self.assertIn("Spostate in avanti per rispettare le dipendenze", resp.headers.get("X-Hub-Flash", ""))

    def test_anteprima_cascata_uguale_alla_propagazione(self):
        from .services.gantt_piano import anteprima_cascata, propaga_dipendenze

        TaskDependency.objects.create(predecessor=self.a, successor=self.b)
        TaskDependency.objects.create(predecessor=self.b, successor=self.c)
        righe = anteprima_cascata(self.project, self.a, D0 + timedelta(days=6), D0 + timedelta(days=10))
        self.assertEqual([(r["task"].id, r["giorni"]) for r in righe], [(self.b.id, 6), (self.c.id, 6)])
        self.b.refresh_from_db()
        self.assertEqual(self.b.next_step_due, D0 + timedelta(days=5))  # l'anteprima non salva
        self.a.next_step_due, self.a.due_date = D0 + timedelta(days=6), D0 + timedelta(days=10)
        self.a.save()
        prima = {}
        spostate = propaga_dipendenze(self.project, self.a, prima=prima)
        self.assertEqual(
            [(t.id, t.next_step_due) for t in spostate], [(r["task"].id, r["inizio_nuovo"]) for r in righe]
        )
        self.assertEqual(prima[self.b.id], {"next_step_due": D0 + timedelta(days=5), "due_date": D0 + timedelta(days=9)})
