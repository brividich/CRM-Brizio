"""Percorso del kickoff: tappe base come attività (09/11/2026)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.urls import reverse

from .models import Project, Task, TaskCategory, TaskExtraRef, TaskStatus, TappaKickoff
from .services import tappe as svc
from .tests_programmi import ProgrammiBase
from .tests_utils import _create_user_with_legacy


class _TappeBase(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.altro = _create_user_with_legacy(username="tp-dest", legacy_user_id=661, role_id=2, role_name="tasks")
        self.url = reverse("tasks:tappa_azione", args=[self.project.pk])
        patcher = patch("tasks.services.meeting_tasks._mail_assegnazione")
        self.mail = patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, **dati):
        return self.client.post(self.url, dati, HTTP_ACCEPT="application/json")


class TappeTests(_TappeBase):

    def test_tipi_seminati_per_ogni_tappa(self):
        tipi = svc.tipi_per_tappa()
        self.assertEqual(set(tipi), set(TappaKickoff.values))
        self.assertTrue(tipi[TappaKickoff.MACCHINA].is_machine_work)
        self.assertTrue(tipi[TappaKickoff.MACCHINA].fields.filter(code="macchina", field_type="asset").exists())

    def test_percorso_vuoto(self):
        dati = svc.percorso(self.project)
        self.assertEqual(dati["totale"], 9)
        self.assertEqual(dati["a_posto"], 0)
        self.assertTrue(all(r["stato"] == "vuota" for r in dati["righe"]))

    def test_assegna_materiali_crea_attivita_e_avvisa(self):
        risposta = self._post(tappa="MATERIALI", action="assegna", assigned_to=self.altro.pk, due_date="2026-12-10")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        task = Task.objects.get(project=self.project)
        self.assertEqual(task.category.tappa, "MATERIALI")
        self.assertEqual((task.assigned_to, task.due_date), (self.altro, date(2026, 12, 10)))
        self.mail.assert_called_once()
        self.assertIn("Arrivo materiali", risposta.json()["html"])
        # Una sola attività per i materiali.
        self.assertEqual(self._post(tappa="MATERIALI", action="assegna").status_code, 400)

    def test_cam_dal_percorso_crea_anche_la_riga_programmi(self):
        self._post(tappa="CAM", action="assegna", assigned_to=self.altro.pk)
        task = Task.objects.get(project=self.project)
        self.assertEqual(task.tech_refs.get().kind, "CAM")

    def test_terzista_ammette_piu_righe_e_il_fornitore_e_facoltativo(self):
        for nome in ("Ditta Uno", "Ditta Due"):
            self.assertEqual(self._post(tappa="TERZISTA", action="assegna", testo=nome).status_code, 200)
        titoli = sorted(Task.objects.filter(project=self.project).values_list("title", flat=True))
        self.assertEqual(titoli, ["Lavorazione terzista - Ditta Due", "Lavorazione terzista - Ditta Uno"])
        self.assertEqual(Task.objects.filter(project=self.project).order_by("id").first().extra_data["fornitore"], "Ditta Uno")
        # Il Percorso non ha campi propri: «+ Altra» crea l'attività anche senza fornitore, che si scrive sull'attività.
        self.assertEqual(self._post(tappa="TERZISTA", action="assegna").status_code, 200)
        self.assertEqual(Task.objects.filter(project=self.project, title="Lavorazione terzista").count(), 1)

    def test_macchina_salva_asset_e_mostra_disponibilita(self):
        from assets.models import Asset

        asset = Asset.objects.create(asset_tag="CNC-T1", name="Tornio prova", asset_type="CNC")
        risposta = self._post(tappa="MACCHINA", action="assegna", asset=asset.pk, due_date="2026-12-10")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        task = Task.objects.get(project=self.project)
        self.assertEqual(task.extra_data["macchina"], asset.pk)
        self.assertTrue(TaskExtraRef.objects.filter(task=task, asset=asset, field_code="macchina").exists())
        self.assertIn("CNC-T1", task.title)
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "MACCHINA")
        # La macchina è un collegamento dell'attività: sotto la tappa si legge il codice, la disponibilità sta nella scheda.
        self.assertEqual([(c["tipo"], c["codice"]) for c in riga["collegamenti"]], [("macchina", "CNC-T1")])
        self.assertEqual(riga["manca"], [])
        self.assertIn("CNC-T1", risposta.json()["html"])
        dettaglio = svc.dettaglio_macchina(task, con_nomi=False)
        self.assertEqual((dettaglio["asset"], dettaglio["abilitati"]), (asset, 0))

    def test_macchina_non_di_produzione_rifiutata(self):
        from assets.models import Asset

        pc = Asset.objects.create(asset_tag="PC-1", name="PC ufficio", asset_type="PC")
        # Non è una macchina di produzione: l'attività nasce senza macchina, e la tappa dice che manca.
        self.assertEqual(self._post(tappa="MACCHINA", action="assegna", asset=pc.pk).status_code, 200)
        self.assertFalse(TaskExtraRef.objects.filter(asset=pc).exists())
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "MACCHINA")
        self.assertEqual((riga["stato"], riga["stato_label"]), ("manca", "Manca: macchina"))

    def test_non_serve_e_ripristina(self):
        self.assertEqual(self._post(tappa="TERZISTA", action="escludi").status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tappe_escluse, ["TERZISTA"])
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "TERZISTA")
        self.assertEqual(riga["stato"], "esclusa")
        self.assertEqual(svc.percorso(self.project)["a_posto"], 1)
        self._post(tappa="TERZISTA", action="ripristina")
        self.project.refresh_from_db()
        self.assertEqual(self.project.tappe_escluse, [])

    def test_non_serve_rifiutato_se_c_e_attivita(self):
        self._post(tappa="MATERIALI", action="assegna")
        self.assertEqual(self._post(tappa="MATERIALI", action="escludi").status_code, 400)

    def test_stato_fatto_quando_attivita_completata(self):
        self._post(tappa="MATERIALI", action="assegna", assigned_to=self.altro.pk)
        Task.objects.filter(project=self.project).update(status=TaskStatus.DONE)
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "MATERIALI")
        self.assertEqual(riga["stato"], "fatta")

    def test_estraneo_non_assegna(self):
        estraneo = _create_user_with_legacy(username="tp-out", legacy_user_id=662, role_id=2, role_name="tasks")
        self.client.force_login(estraneo)
        risposta = self._post(tappa="MATERIALI", action="assegna")
        self.assertIn(risposta.status_code, (403, 404))
        self.assertFalse(Task.objects.exists())

    def test_tappa_disattivata_sparisce(self):
        TaskCategory.objects.filter(tappa="PROCESSI").update(is_active=False)
        chiavi = [r["key"] for r in svc.percorso(self.project)["righe"]]
        self.assertNotIn("PROCESSI", chiavi)

    def test_pagine_mostrano_il_percorso(self):
        risposta = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        self.assertContains(risposta, "Percorso del kickoff")
        self.assertContains(risposta, "tappe.js")

    def test_rotta_con_binding_canonico(self):
        from core.models import RoutePermissionBinding

        from .acl_bootstrap import bootstrap_tasks_acl_endpoints

        bootstrap_tasks_acl_endpoints(force=True)
        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="tasks:tappa_azione").exists())

    def test_progetto_campo_default(self):
        self.assertEqual(Project.objects.get(pk=self.project.pk).tappe_escluse, [])


class TappeDateFlussiTests(_TappeBase):
    """Inizio, anteprima e flussi spenti di default (09/11/2026)."""

    def test_inizio_e_fine_dal_calendario(self):
        self._post(tappa="MATERIALI", action="assegna", start_date="2026-12-01", due_date="2026-12-10")
        task = Task.objects.get(project=self.project)
        self.assertEqual((task.next_step_due, task.due_date), (date(2026, 12, 1), date(2026, 12, 10)))

    def test_fine_prima_dell_inizio_rifiutata(self):
        risposta = self._post(tappa="MATERIALI", action="assegna", start_date="2026-12-10", due_date="2026-12-01")
        self.assertEqual(risposta.status_code, 400)
        self.assertFalse(Task.objects.exists())

    def test_anteprima_responsabile_e_macchina(self):
        from assets.models import Asset

        asset = Asset.objects.create(asset_tag="CNC-A1", name="Fresa prova", asset_type="CNC")
        url = reverse("tasks:tappa_anteprima", args=[self.project.pk])
        risposta = self.client.get(url, {
            "tappa": "MACCHINA", "asset": asset.pk, "assigned_to": self.altro.pk,
            "start_date": "2026-12-01", "due_date": "2026-12-10",
        }, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 200)
        html = risposta.json()["html"]
        self.assertIn("disponibile dal 01/12 al 10/12", html)
        self.assertIn("Nessun abilitato operativo", html)

    def test_promemoria_spento_di_default(self):
        from .models import TaskReminder

        with self.captureOnCommitCallbacks(execute=True):
            self._post(tappa="MATERIALI", action="assegna", assigned_to=self.altro.pk, due_date="2026-12-10")
        self.assertFalse(TaskReminder.objects.exists())

    def test_promemoria_acceso_dal_designer(self):
        from automazioni.managed_flows import install_flows
        from automazioni.models import ManagedFlow

        from .models import TaskImpostazioni, TaskReminder

        install_flows()
        binding = ManagedFlow.objects.select_related("rule").get(code="kickoff_promemoria_scadenza")
        self.assertFalse(binding.rule.is_active)
        self.assertFalse(ManagedFlow.objects.get(code="kickoff_evento_outlook").rule.is_active)
        binding.rule.is_active = True
        binding.rule.save(update_fields=["is_active"])
        cfg = TaskImpostazioni.get_singleton()
        cfg.notifiche_scadenza_attive = True
        cfg.save()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(tappa="MATERIALI", action="assegna", assigned_to=self.altro.pk, due_date="2026-12-10")
        self.assertTrue(TaskReminder.objects.filter(task__project=self.project).exists())

    def test_percorso_senza_campi_propri(self):
        pagina = self.client.get(reverse("tasks:project_overview", args=[self.project.pk]))
        self.assertNotContains(pagina, "Anche in Outlook")
        for campo in ('data-tp="start"', 'data-tp="due"', 'data-tp="owner"', "data-tp-form", "data-tp-ut-add", 'data-tp="asset"'):
            self.assertNotContains(pagina, campo)
        self.assertContains(pagina, 'data-tp-action="assegna"', count=9)



class AttrezzaturaUtensiliTests(_TappeBase):
    def test_attrezzatura_si_collega_all_attivita_della_tappa(self):
        from attrezzature.models import Attrezzatura, AttrezzaturaKickoffLink, AttrezzaturaTask

        from .services import collegamenti

        self.project.part_number = "PN-ATT-1"
        self.project.save()
        att = Attrezzatura.objects.create(codice="ATT-9", descrizione="Maschera di prova", part_number="PN-ATT-1")
        # «Assegna» non chiede quale attrezzatura: crea l'attività, il codice si collega da lei.
        risposta = self._post(tappa="ATTREZZATURA", action="assegna")
        self.assertEqual(risposta.status_code, 200, risposta.content)
        task = Task.objects.get(project=self.project)
        self.assertEqual(task.title, "Attrezzatura")
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "ATTREZZATURA")
        self.assertEqual((riga["stato"], riga["stato_label"]), ("manca", "Manca: attrezzatura"))
        collegamenti.collega(task, "attrezzatura", att.pk, self.user)
        self.assertTrue(AttrezzaturaKickoffLink.objects.filter(attrezzatura=att, project=self.project, task=task).exists())
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "ATTREZZATURA")
        self.assertEqual(riga["stato"], "fare")
        self.assertEqual([c["codice"] for c in riga["collegamenti"]], ["ATT-9"])
        self.assertFalse(AttrezzaturaTask.objects.exists(), "nessuna richiesta o verifica: è solo un codice")

    def test_il_percorso_non_chiede_piu_attrezzature_nuove(self):
        from attrezzature.models import Attrezzatura

        self.project.part_number = "PN-ATT-2"
        self.project.save()
        # I vecchi parametri, se arrivano, non creano richieste.
        self._post(tappa="ATTREZZATURA", action="assegna", attrezzatura="nuova", testo="Staffaggio fresatura")
        self.assertFalse(Attrezzatura.objects.exists())

    def test_utensili_stati_e_quantita_non_contano_piu(self):
        from .models import ProjectUtensile, Utensile
        from .services import collegamenti

        # Il vecchio indirizzo resta per compatibilità e salva ancora la riga della commessa...
        url = reverse("tasks:utensili_azione", args=[self.project.pk])
        risposta = self.client.post(url, {"action": "aggiungi", "utensile": "FR12 Fresa D12", "quantita": "2"}, HTTP_ACCEPT="application/json")
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual((Utensile.objects.count(), ProjectUtensile.objects.filter(project=self.project).count()), (1, 1))
        # ...ma il Percorso non la legge: niente stati, niente quantità, la tappa aspetta la sua attività.
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "UTENSILI")
        self.assertEqual((riga["stato"], riga["stato_label"]), ("vuota", "Da assegnare"))
        html = risposta.json()["html"]
        for vietato in ("da ordinare", "Da ordinare", " pz", "Disponibile a magazzino", "data-tp-ut"):
            self.assertNotIn(vietato, html)
        self._post(tappa="UTENSILI", action="assegna")
        task = Task.objects.get(project=self.project)
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "UTENSILI")
        self.assertEqual(riga["stato_label"], "Manca: utensile")
        collegamenti.aggiungi(task, "utensile", "fr12", self.user)
        vecchia = ProjectUtensile.objects.get(project=self.project)
        self.assertEqual((vecchia.task, vecchia.quantita), (task, 2), "la riga già registrata passa all'attività con i suoi dati")
        riga = next(r for r in svc.percorso(self.project)["righe"] if r["key"] == "UTENSILI")
        self.assertEqual((riga["stato"], [c["codice"] for c in riga["collegamenti"]]), ("fare", ["FR12"]))
