"""Catalogo delle voci ricorrenti (10/11/2026)."""
from __future__ import annotations

from datetime import date

from django.urls import reverse

from .models import CatalogoVoce, KickoffMeeting, MeetingActionItem, Task
from .services.catalogo import chiave, registra_uso, unisci
from .tests_programmi import ProgrammiBase


class CatalogoTests(ProgrammiBase):
    def test_chiave_ignora_maiuscole_spazi_punto(self):
        self.assertEqual(chiave("  Stato   avanzamento. "), chiave("stato avanzamento"))

    def test_registra_e_conta_gli_usi(self):
        registra_uso("ODG", "Stato avanzamento", nota="Gantt", durata=15)
        registra_uso("ODG", "stato avanzamento.")
        voce = CatalogoVoce.objects.get(tipo="ODG")
        self.assertEqual((voce.usi, voce.nota, voce.durata_minuti), (2, "Gantt", 15))

    def test_si_riempie_scrivendo(self):
        m = KickoffMeeting.objects.create(project=self.project, data=date(2026, 12, 1), created_by=self.user)
        m.agenda_items = [{"id": "a1", "titolo": "Verifica attrezzature", "durata_minuti": 10}]
        m.save()
        m.save()  # risalvare non conta un secondo uso
        MeetingActionItem.objects.create(project=self.project, title="Ordinare la barra tonda")
        Task.objects.create(title="Preparare il grezzo", project=self.project, created_by=self.user)
        self.assertEqual(CatalogoVoce.objects.get(tipo="ODG").usi, 1)
        self.assertTrue(CatalogoVoce.objects.filter(tipo="AZIONE", testo="Ordinare la barra tonda").exists())
        self.assertTrue(CatalogoVoce.objects.filter(tipo="ATTIVITA", testo="Preparare il grezzo").exists())

    def test_tappe_e_punti_generati_esclusi(self):
        m = KickoffMeeting.objects.create(project=self.project, data=date(2026, 12, 1), created_by=self.user)
        m.agenda_items = [{"id": "t", "titolo": "Macchina: da assegnare", "source": "tappa:MACCHINA"}]
        m.save()
        self.assertFalse(CatalogoVoce.objects.filter(tipo="ODG").exists())

    def test_unisci(self):
        registra_uso("AZIONE", "Ordinare materiale")
        registra_uso("AZIONE", "Ordine materiale")
        a, b = CatalogoVoce.objects.order_by("id")
        unisci(b, a)
        a.refresh_from_db()
        self.assertEqual((CatalogoVoce.objects.count(), a.usi), (1, 2))

    def test_suggerimenti_odg_dal_catalogo(self):
        registra_uso("ODG", "Rischi aperti", durata=20)
        pagina = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.pk]))
        titoli = [s["titolo"] for s in pagina.context["agenda_suggestions_json"]]
        self.assertIn("Rischi aperti", titoli)

    def test_datalist_nei_campi(self):
        registra_uso("ATTIVITA", "Preparare il grezzo")
        m = KickoffMeeting.objects.create(project=self.project, data=date(2026, 12, 1), created_by=self.user)
        pagina = self.client.get(reverse("tasks:project_meeting_run", args=[self.project.pk, m.pk]))
        self.assertContains(pagina, 'id="cat-attivita"')
        self.assertContains(pagina, "Preparare il grezzo")

    def test_impostazioni_rinomina_nascondi_unisci(self):
        self.user.is_superuser = True
        self.user.save()
        registra_uso("ODG", "Stato avanz")
        registra_uso("ODG", "Stato avanzamento")
        a, b = CatalogoVoce.objects.order_by("id")
        url = reverse("tasks:impostazioni")
        self.assertContains(self.client.get(url + "?tab=catalogo"), "Catalogo delle voci ricorrenti")
        self.client.post(url, {"tab": "catalogo", "voce_id": a.pk, "testo": "Stato avanzamento"})
        self.assertEqual(CatalogoVoce.objects.filter(tipo="ODG").count(), 1, "rinominare in un doppione unisce")
        voce = CatalogoVoce.objects.get(tipo="ODG")
        self.client.post(url, {"tab": "catalogo", "voce_id": voce.pk, "azione": "nascondi"})
        voce.refresh_from_db()
        self.assertFalse(voce.attiva)
