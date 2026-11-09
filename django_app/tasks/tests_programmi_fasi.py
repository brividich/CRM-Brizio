"""Programmi CAM/CMM: fasi, revisione, macchina, storico (10/11/2026)."""
from __future__ import annotations

from django.urls import reverse

from .models import ProgrammaFase, ProgrammaStorico, ProjectTechRef, TaskStatus
from .services.programmi_fasi import revisione_successiva
from .tests_programmi import ProgrammiBase


class FasiTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.task = self.attivita()
        self.ref = ProjectTechRef.objects.get(task=self.task)
        self.url = reverse("tasks:programma_fase", args=[self.ref.pk])

    def passo(self, azione, **altri):
        return self.client.post(self.url, {"azione": azione, **altri})

    def test_percorso_completo_chiude_e_riapre_l_attivita(self):
        self.passo("inizia")
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.fase, ProgrammaFase.IN_SCRITTURA)
        self.passo("da_provare")
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.fase, ProgrammaFase.IN_SCRITTURA, "senza codice non si va in prova")
        self.passo("da_provare", code="O1234")
        self.ref.refresh_from_db()
        self.assertEqual((self.ref.fase, self.ref.revisione), (ProgrammaFase.DA_PROVARE, "A"))
        self.passo("valida")
        self.ref.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.ref.fase, ProgrammaFase.VALIDATO)
        self.assertFalse(self.ref.is_open)
        self.assertEqual(self.task.status, TaskStatus.DONE)
        self.passo("revisione")
        self.ref.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual((self.ref.fase, self.ref.revisione), (ProgrammaFase.IN_SCRITTURA, "B"))
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(ProgrammaStorico.objects.filter(ref=self.ref).count(), 4)

    def test_passo_non_ammesso(self):
        self.passo("valida")
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.fase, ProgrammaFase.DA_SCRIVERE)

    def test_revisione_successiva(self):
        self.assertEqual([revisione_successiva(r) for r in ("", "A", "B", "3", "Z")], ["A", "B", "C", "4", "Z1"])

    def test_registro_mostra_fasi_e_pulsanti(self):
        pagina = self.client.get(reverse("tasks:programmi_registro"))
        self.assertContains(pagina, "Da scrivere")
        self.assertContains(pagina, "Inizia a scrivere")

    def test_passo_dalla_tabella_della_commessa(self):
        risposta = self.client.post(
            reverse("tasks:tech_ref_action", args=[self.project.pk, self.ref.pk]), {"action": "fase_inizia"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(risposta.status_code, 200)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.fase, ProgrammaFase.IN_SCRITTURA)
