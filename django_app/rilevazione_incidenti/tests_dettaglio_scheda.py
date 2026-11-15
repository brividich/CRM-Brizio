"""Dettaglio rilevazione con la grafica del Diario del preposto: infografica e storia."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from . import scheda
from .models import RilevazioneIncidente


class DettaglioSchedaTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(username="ri-admin", email="ri@example.com", password="x")
        UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
        self.client.force_login(user)
        fatto = timezone.now() - timedelta(days=40)
        self.r = RilevazioneIncidente.objects.create(
            nominativo="Mario Prova", tipologia_scheda="Near Miss", reparto="Officina",
            data_segnalazione=fatto, descrizione_avvenimento="Pezzo caduto dal banco",
            why_1="Banco ingombro", approvazione_rls="Approvato", data_approvazione_rls=date.today(),
        )
        RilevazioneIncidente.objects.create(
            nominativo="Altro", tipologia_scheda="Unsafe Condition", reparto="Officina",
            data_segnalazione=fatto + timedelta(days=1), descrizione_avvenimento="Olio a terra",
        )

    def test_pagina_mostra_infografica_e_storia(self):
        response = self.client.get(reverse("rilevazione_incidenti:dettaglio", args=[self.r.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Situazione della rilevazione")
        self.assertContains(response, "Storia della rilevazione")
        self.assertContains(response, "Il reparto: Officina")
        self.assertContains(response, "Successiva · n.")
        self.assertContains(response, "Valutata dall&#x27;RLS: Approvato")
        self.assertContains(response, "dp-card-header")

    def test_controlli_chiusura_in_ritardo_e_misure_mancanti(self):
        f = self.r.as_sp_fields()
        storyline = scheda.costruisci_storyline(f, str(self.r.pk), locale=True)
        c = {v["titolo"]: v["stato"] for v in scheda.controlli(f, storyline)["voci"]}
        self.assertEqual(c["Chiusa da RSPP/ASPP"], "avviso")
        self.assertEqual(c["Misure individuate"], "avviso")
        self.assertEqual(c["Analisi 5WHY"], "ok")
        self.assertEqual(c["Valutazione RLS"], "ok")
        titoli = [e.titolo for e in storyline["eventi"]]
        self.assertEqual(titoli[0], "Evento rilevato")
        self.assertTrue(any(t.startswith("Registrata nel portale") for t in titoli))

    def test_sharepoint_senza_storico(self):
        f = {"Nominativo": "X", "Data_e_ora_rilevazione": "2026-11-01T08:00:00Z", "Chiusura_RSPP": True,
             "Data_chiusura_RSPP": "2026-11-05"}
        storyline = scheda.costruisci_storyline(f, "abc", locale=False)
        self.assertFalse(storyline["riepilogo"]["storico"])
        tappe = scheda.percorso(f, storyline, oggi=date(2026, 11, 15))
        self.assertEqual(tappe[-1]["titolo"], "Chiusa")
        self.assertEqual(tappe[-1]["dopo"], "dopo 4 giorni")
