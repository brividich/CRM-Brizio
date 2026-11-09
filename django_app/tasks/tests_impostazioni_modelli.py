"""Impostazioni riorganizzate, modelli di commessa, consegna a rischio, chiusura, carico (11/11/2026)."""
from __future__ import annotations

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import ModelloCommessa, ProjectPhase, Task, TaskStatus
from .services.filo import prossimi_passi, stato_consegna
from .services.tappe import carico, percorso
from .tests_programmi import ProgrammiBase


class ImpostazioniModelliTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()

    def test_menu_raggruppato_e_pagine(self):
        url = reverse("tasks:impostazioni")
        pagina = self.client.get(url)
        for voce in ("Commesse", "Persone e permessi", "Modelli di commessa", "Poteri e avvisi", "Registro modifiche"):
            self.assertContains(pagina, voce)
        for tab in ("config", "commesse", "sale", "poteri", "catalogo", "tipi", "record", "log"):
            self.assertEqual(self.client.get(url + f"?tab={tab}").status_code, 200, tab)

    def test_modello_di_commessa(self):
        url = reverse("tasks:impostazioni")
        self.client.post(url, {"tab": "commesse", "nome": "Ripetizione", "tappa_CAM": "on", "giorni_CAM": "10", "tappa_FAI": "on"})
        m = ModelloCommessa.objects.get(nome="Ripetizione")
        self.assertEqual(m.chiavi, ["CAM", "FAI"])
        self.assertEqual(m.giorni_per("CAM"), 10)
        self.assertContains(self.client.get(url + "?tab=commesse"), "Ripetizione")

    def test_kickoff_con_modello_e_consegna_propone_entro(self):
        m = ModelloCommessa.objects.create(nome="Nuovo", tappe=[{"tappa": "CAM", "giorni": 20}])
        self.project.modello = m
        self.project.data_consegna = date(2026, 12, 31)
        self.project.save()
        riga = next(r for r in percorso(self.project)["righe"] if r["key"] == "CAM")
        self.assertEqual(riga["entro_proposto"], date(2026, 12, 11))

    def test_consegna_a_rischio_nei_prossimi_passi(self):
        self.project.data_consegna = timezone.localdate() + timedelta(days=5)
        self.project.save()
        Task.objects.create(title="Fresatura", project=self.project, created_by=self.user, due_date=timezone.localdate() + timedelta(days=9))
        self.assertTrue(stato_consegna(self.project)["a_rischio"])
        self.assertTrue(any("a rischio" in p["titolo"] for p in prossimi_passi(self.project, limite=10)))

    def test_chiusura_e_riapertura(self):
        url = reverse("tasks:project_chiudi", args=[self.project.pk])
        Task.objects.create(title="Aperta", project=self.project, created_by=self.user)
        self.client.post(url, {"nota": "ok"})
        self.project.refresh_from_db()
        self.assertIsNone(self.project.chiuso_il, "con attività aperte serve la conferma")
        self.client.post(url, {"nota": "Tutto pronto", "conferma": "1"})
        self.project.refresh_from_db()
        self.assertEqual((self.project.phase, self.project.chiusura_nota), (ProjectPhase.DONE, "Tutto pronto"))
        self.assertEqual(prossimi_passi(self.project), [])
        self.client.post(url, {"azione": "riapri"})
        self.project.refresh_from_db()
        self.assertIsNone(self.project.chiuso_il)

    def test_carico_nel_periodo(self):
        oggi = timezone.localdate()
        Task.objects.create(title="A", project=self.project, created_by=self.user, assigned_to=self.user, next_step_due=oggi, due_date=oggi + timedelta(days=3))
        Task.objects.create(title="B", project=self.project, created_by=self.user, assigned_to=self.user, status=TaskStatus.DONE, due_date=oggi)
        self.assertEqual(carico([self.user.pk], oggi, oggi + timedelta(days=7)), {self.user.pk: 1})
