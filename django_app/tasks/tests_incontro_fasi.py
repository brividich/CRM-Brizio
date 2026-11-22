"""Incontro a pagina unica: tre fasi (prima, durante, dopo), una sola intestazione, il pulsante segue la fase."""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .models import KickoffMeeting, MeetingStatus
from .services.filo_incontro import fasi_incontro
from .tests_filo import FiloBase
from .tests_utils import make_project

PRIMARIA = 'class="ts-hero-action primary"'


class IncontroTreFasiTests(FiloBase):
    def setUp(self):
        super().setUp()
        self.project = make_project(name="Commessa fasi", created_by=self.user, project_manager=self.user)
        self.oggi = timezone.localdate()
        self.m = KickoffMeeting.objects.create(
            project=self.project, data=self.oggi, created_by=self.user, titolo="Avanzamento",
        )
        self.ids = [self.project.pk, self.m.pk]

    def pagina(self, nome):
        return self.client.get(reverse(nome, args=self.ids))

    # ── la barra ────────────────────────────────────────────────────────────
    def test_tre_fasi_e_i_nomi_di_prima_restano_validi(self):
        fasi = fasi_incontro(self.m, attiva="convocazione", can_manage=True)
        self.assertEqual([f["key"] for f in fasi], ["prima", "durante", "dopo"])
        self.assertEqual([f["label"] for f in fasi], ["Prima", "Durante", "Dopo"])
        self.assertEqual([f["attiva"] for f in fasi], [True, False, False])
        for vecchio, nuovo in (("conduzione", "durante"), ("esito", "dopo"), ("minuta", "dopo")):
            attive = [f["key"] for f in fasi_incontro(self.m, attiva=vecchio, can_manage=True) if f["attiva"]]
            self.assertEqual(attive, [nuovo])

    def test_dopo_porta_all_esito_poi_alla_scheda(self):
        dopo = fasi_incontro(self.m, attiva="prima", can_manage=True)[2]
        self.assertEqual(dopo["url"], reverse("tasks:project_meeting_minutes", args=self.ids))
        self.m.stato = MeetingStatus.SVOLTO
        fasi = fasi_incontro(self.m, attiva="dopo", can_manage=True)
        self.assertEqual(fasi[2]["url"], reverse("tasks:project_meeting_detail", args=self.ids))
        self.assertEqual(fasi[2]["nota"], "Minuta da approvare")
        # A incontro svolto «Prima» e «Durante» restano come traccia, senza collegamento.
        self.assertIsNone(fasi[0]["url"])
        self.assertIsNone(fasi[1]["url"])

    def test_chi_non_gestisce_non_ha_collegamenti_operativi(self):
        fasi = fasi_incontro(self.m, attiva="prima", can_manage=False)
        self.assertIsNone(fasi[1]["url"])
        self.assertIsNone(fasi[2]["url"])

    def test_incontro_annullato_nessuna_barra(self):
        self.m.stato = MeetingStatus.ANNULLATO
        self.assertEqual(fasi_incontro(self.m, attiva="prima", can_manage=True), [])

    # ── le quattro pagine: stessa testata, stessa intestazione ───────────────
    def test_stessa_testata_e_stessa_intestazione_sulle_quattro_pagine(self):
        for nome in (
            "tasks:project_meeting_detail", "tasks:project_meeting_edit",
            "tasks:project_meeting_run", "tasks:project_meeting_minutes",
        ):
            with self.subTest(pagina=nome):
                r = self.pagina(nome)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, f"<h1>{self.project.name}</h1>", html=True)
                self.assertContains(r, 'class="mfasi"')
                self.assertContains(r, 'class="md-hero-num"')
                self.assertContains(r, "<strong>Prima</strong>")
                self.assertContains(r, "<strong>Dopo</strong>")
                # Dentro l'incontro le viste «Incontri / Decisioni» non compaiono.
                self.assertNotContains(r, 'aria-label="Viste degli incontri"')

    def test_il_pulsante_segue_la_fase(self):
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, "Inizia l&#x27;incontro")
        self.assertContains(scheda, reverse("tasks:project_meeting_run", args=self.ids))
        self.assertEqual(scheda.content.decode().count(PRIMARIA), 1)

        conduzione = self.pagina("tasks:project_meeting_run")
        self.assertContains(conduzione, "Termina l&#x27;incontro")

        # La pagina dell'esito ha già il suo «Registra esito»: niente secondo pulsante in testata.
        esito = self.pagina("tasks:project_meeting_minutes")
        self.assertEqual(esito.content.decode().count(PRIMARIA), 0)

    def test_incontro_passato_non_svolto_chiede_l_esito(self):
        KickoffMeeting.objects.filter(pk=self.m.pk).update(data=self.oggi - timedelta(days=2))
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, "Registra l&#x27;esito")
        self.assertNotContains(scheda, "Inizia l&#x27;incontro")

    def test_dopo_approva_poi_invia_poi_pianifica_il_prossimo(self):
        KickoffMeeting.objects.filter(pk=self.m.pk).update(stato=MeetingStatus.SVOLTO)
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, "Approva la minuta")
        self.assertContains(scheda, f'action="{reverse("tasks:project_meeting_minute_close", args=self.ids)}" class="tk-primaria-form"')

        KickoffMeeting.objects.filter(pk=self.m.pk).update(minuta_chiusa_at=timezone.now())
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, "Invia la minuta")
        self.assertContains(scheda, f'action="{reverse("tasks:project_meeting_send_minute", args=self.ids)}" class="tk-primaria-form"')

        KickoffMeeting.objects.filter(pk=self.m.pk).update(minuta_inviata_at=timezone.now())
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, "Pianifica il prossimo incontro")

    # ── la scheda: prima solo la convocazione, dopo solo la minuta ────────────
    def test_scheda_prima_dell_incontro(self):
        scheda = self.pagina("tasks:project_meeting_detail")
        # La convocazione è un riquadro della fase «Prima», non più una riga di pulsanti.
        self.assertContains(scheda, 'id="prima-convocazione"')
        self.assertContains(scheda, "Invia convocazione per mail")
        self.assertNotContains(scheda, "md-docbar")
        for assente in ("Scarica minuta PDF", "Invia minuta", ">Conduci incontro<", ">Registra esito<", "Tutti gli incontri"):
            self.assertNotContains(scheda, assente)

    def test_scheda_dopo_l_incontro(self):
        KickoffMeeting.objects.filter(pk=self.m.pk).update(stato=MeetingStatus.SVOLTO)
        scheda = self.pagina("tasks:project_meeting_detail")
        self.assertContains(scheda, '<span class="md-docbar-label">Minuta</span>', html=True)
        self.assertContains(scheda, "Scarica minuta PDF")
        self.assertContains(scheda, "Aggiorna esito")

    def test_incontro_nuovo_senza_pulsante_in_testata(self):
        r = self.client.get(reverse("tasks:project_meeting_create", args=[self.project.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<h2>Nuovo incontro</h2>", html=True)
        self.assertEqual(r.content.decode().count(PRIMARIA), 0)
