"""Ingressi: recruiting (posizioni, pipeline, offerta) e onboarding a fasi.

Nessun dato reale: nomi, mansioni e date sono fittizi.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import OnboardingPratica, OnboardingTask
from .models_recruiting import Candidato, PosizioneAperta
from .services import onboarding, recruiting as recruiting_service
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()
T = OnboardingTask


class PianoAFasiTests(TestCase):
    """Fasi, ordine e scadenze calcolate dalla data di ingresso."""

    def test_scadenze_dalla_data_di_ingresso(self):
        ingresso = date(2026, 11, 2)
        pratica = onboarding.avvia_onboarding(
            legacy_id=None, dipendente_nome="ROSSI ANNA", mansione="Impiegata",
            data_assunzione=ingresso, fine_prova=date(2027, 2, 1), notifica_dpi=False,
        )
        voci = {t.codice: t for t in pratica.tasks.all()}
        self.assertEqual(voci["amm_unilav"].fase, T.FASE_PRE)
        self.assertEqual(voci["amm_unilav"].scadenza, ingresso - timedelta(days=1))
        self.assertEqual(voci["hr_badge_accessi"].scadenza, ingresso)
        self.assertEqual(voci["responsabile_colloquio_30gg"].scadenza, ingresso + timedelta(days=30))
        self.assertEqual(voci["formazione_corsi_obbligatori"].scadenza, ingresso + timedelta(days=60))
        self.assertEqual(voci["responsabile_valutazione_prova"].scadenza, date(2027, 1, 25))
        self.assertEqual(voci["hr_esito_prova"].scadenza, date(2027, 2, 1))
        # Le voci escono nell'ordine delle fasi.
        fasi = [t.fase for t in pratica.tasks.all()]
        ordine = [onboarding.FASI_ORDINE.index(f) for f in fasi]
        self.assertEqual(ordine, sorted(ordine))

    def test_senza_data_le_scadenze_restano_da_definire_e_si_ricalcolano(self):
        pratica = onboarding.avvia_onboarding(legacy_id=None, dipendente_nome="X", notifica_dpi=False)
        self.assertFalse(pratica.tasks.exclude(scadenza=None).exists())
        pratica.data_assunzione = date(2026, 12, 1)
        pratica.save()
        self.assertGreater(onboarding.ricalcola_scadenze(pratica), 0)
        self.assertEqual(pratica.tasks.get(codice="hr_badge_accessi").scadenza, date(2026, 12, 1))

    def test_riepilogo_ritardo_e_fase_corrente(self):
        pratica = onboarding.avvia_onboarding(
            legacy_id=None, dipendente_nome="Y", data_assunzione=date.today() - timedelta(days=10),
            notifica_dpi=False,
        )
        r = onboarding.riepilogo(pratica)
        self.assertGreater(r["in_ritardo"], 0)
        self.assertEqual(r["fase_corrente"], "Prima dell'ingresso")
        pratica.tasks.filter(fase=T.FASE_PRE).update(stato=T.STATO_COMPLETATO)
        self.assertEqual(onboarding.riepilogo(pratica)["fase_corrente"], "Primo giorno")


class ChiusuraAutomaticaTests(TestCase):
    """Le voci verificabili si chiudono da sole quando il portale registra il dato."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser("hr-ingressi", "hr-ingressi@example.com", "pass12345")
        candidato = Candidato.objects.create(cognome="Bianchi", nome="Prova", mansione_cercata="Magazziniere",
                                             data_assunzione=date.today())
        self.pratica = recruiting_service.assumi_e_avvia_onboarding(candidato, user=self.user)

    def test_account_collegato_chiude_la_voce(self):
        voce = self.pratica.tasks.get(codice="it_account_ad")
        self.assertEqual(voce.stato, T.STATO_DA_FARE)
        with connection.cursor() as cur:
            cur.execute("UPDATE anagrafica_dipendenti SET utente_id = %s WHERE id = %s",
                        [4242, self.pratica.legacy_anagrafica_id])
        esito = onboarding.aggiorna_pratiche()
        voce.refresh_from_db()
        self.assertGreaterEqual(esito["chiusi"], 1)
        self.assertEqual(voce.stato, T.STATO_COMPLETATO)
        self.assertTrue(voce.chiusura_automatica)
        self.assertIn("Account", voce.chiusura_nota)

    def test_voci_manuali_non_si_chiudono_da_sole(self):
        onboarding.aggiorna_pratiche()
        self.assertEqual(self.pratica.tasks.get(codice="amm_unilav").stato, T.STATO_DA_FARE)


class OffertaEPreIngressoTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser("hr-offerta", "hr-offerta@example.com", "pass12345")
        self.posizione = PosizioneAperta.objects.create(
            titolo="Operatore CNC turno A", mansione="Operatore CNC", reparto="Produzione",
            posti=1, data_richiesta=date.today() - timedelta(days=20),
        )
        self.candidato = Candidato.objects.create(
            cognome="Verdi", nome="Lia", mansione_cercata="Operatore CNC", posizione=self.posizione,
            stato=Candidato.STATO_COLLOQUIO_2,
        )

    def test_offerta_accettata_apre_pre_ingresso_e_assunzione_lo_collega(self):
        ingresso = date.today() + timedelta(days=14)
        recruiting_service.invia_offerta(self.candidato, inviata_il=date.today(), data_ingresso=ingresso, user=self.user)
        self.assertEqual(self.candidato.stato, Candidato.STATO_OFFERTA)

        pratica = recruiting_service.registra_esito_offerta(
            self.candidato, Candidato.OFFERTA_ACCETTATA, user=self.user,
        )
        self.assertIsNotNone(pratica)
        self.assertTrue(pratica.in_pre_ingresso)
        self.assertEqual(pratica.data_assunzione, ingresso)
        self.assertEqual(pratica.reparto, "Produzione")

        self.candidato.refresh_from_db()
        collegata = recruiting_service.assumi_e_avvia_onboarding(self.candidato, user=self.user)
        self.assertEqual(collegata.pk, pratica.pk)  # nessuna seconda pratica
        collegata.refresh_from_db()
        self.assertTrue(collegata.legacy_anagrafica_id)
        self.assertEqual(OnboardingPratica.objects.count(), 1)

        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.stato, Candidato.STATO_ASSUNTO)
        self.posizione.refresh_from_db()
        self.assertEqual(self.posizione.stato, PosizioneAperta.STATO_COPERTA)
        self.assertEqual(self.posizione.giorni_copertura, 20)

    def test_offerta_rifiutata_chiude_per_rinuncia(self):
        recruiting_service.invia_offerta(self.candidato, inviata_il=date.today(), user=self.user)
        self.assertIsNone(recruiting_service.registra_esito_offerta(
            self.candidato, Candidato.OFFERTA_RIFIUTATA, user=self.user,
        ))
        self.assertEqual(self.candidato.stato, Candidato.STATO_RINUNCIA)
        self.assertFalse(OnboardingPratica.objects.exists())

    def test_offerta_facoltativa_assunzione_diretta(self):
        pratica = recruiting_service.assumi_e_avvia_onboarding(self.candidato, user=self.user)
        self.assertTrue(pratica.legacy_anagrafica_id)
        self.assertEqual(self.candidato.stato, Candidato.STATO_ASSUNTO)

    def test_sposta_in_fase(self):
        recruiting_service.sposta_in_fase(self.candidato, Candidato.STATO_OFFERTA, user=self.user)
        self.assertEqual(self.candidato.stato, Candidato.STATO_OFFERTA)
        self.assertEqual(self.candidato.offerta_inviata_il, date.today())
        with self.assertRaises(recruiting_service.TransizioneError):
            recruiting_service.sposta_in_fase(self.candidato, Candidato.STATO_ASSUNTO, user=self.user)

    def test_kpi_posizioni(self):
        PosizioneAperta.objects.create(titolo="Ritardo", posti=2, data_richiesta=date.today() - timedelta(days=40),
                                       entro_il=date.today() - timedelta(days=1))
        kpi = recruiting_service.kpi_posizioni()
        self.assertEqual(kpi["aperte"], 2)
        self.assertEqual(kpi["posti_aperti"], 3)
        self.assertEqual(kpi["in_ritardo"], 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class IngressiViewTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser("hr-viste", "hr-viste@example.com", "pass12345")
        self.client.force_login(self.user)
        self.candidato = Candidato.objects.create(cognome="Neri", nome="Ada", mansione_cercata="Saldatore")

    def test_pagine_recruiting(self):
        for nome in ("recruiting_pipeline", "recruiting_posizioni", "recruiting_posizione_create", "recruiting_dashboard"):
            self.assertEqual(self.client.get(reverse(f"anagrafica:{nome}")).status_code, 200, nome)

    def test_crea_posizione(self):
        risposta = self.client.post(reverse("anagrafica:recruiting_posizione_create"), {
            "titolo": "Saldatore TIG", "mansione": "Saldatore", "reparto": "Carpenteria", "posti": 2,
            "motivo": PosizioneAperta.MOTIVO_INCREMENTO, "data_richiesta": "2026-10-01", "stato": "APERTA",
        })
        posizione = PosizioneAperta.objects.get(titolo="Saldatore TIG")
        self.assertRedirects(risposta, reverse("anagrafica:recruiting_posizione_detail", args=[posizione.pk]))
        self.assertEqual(self.client.get(reverse("anagrafica:recruiting_posizione_detail", args=[posizione.pk])).status_code, 200)

    def test_sposta_risponde_json(self):
        url = reverse("anagrafica:recruiting_sposta", args=[self.candidato.pk])
        r = self.client.post(url, {"stato": Candidato.STATO_COLLOQUIO_1}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["stato"], Candidato.STATO_COLLOQUIO_1)
        r = self.client.post(url, {"stato": Candidato.STATO_ASSUNTO}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.status_code, 400)

    def test_onboarding_cruscotto_pratica_e_voce_htmx(self):
        pratica = onboarding.avvia_onboarding(
            legacy_id=None, dipendente_nome="NERI ADA", data_assunzione=date.today(), notifica_dpi=False,
        )
        self.assertContains(self.client.get(reverse("anagrafica:onboarding_list")), "NERI ADA")
        dettaglio = self.client.get(reverse("anagrafica:onboarding_detail", args=[pratica.pk]))
        self.assertContains(dettaglio, "Prima dell&#x27;ingresso")
        self.assertContains(dettaglio, "Pre-ingresso")

        voce = pratica.tasks.get(codice="amm_unilav")
        r = self.client.post(
            reverse("anagrafica:onboarding_task_update", args=[pratica.pk, voce.pk]),
            {"stato": T.STATO_COMPLETATO, "note": ""}, HTTP_HX_REQUEST="true",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'id="obv-{voce.pk}"')
        self.assertContains(r, 'hx-swap-oob="true"')
        voce.refresh_from_db()
        self.assertEqual(voce.stato, T.STATO_COMPLETATO)

    def test_onboarding_date_ricalcola(self):
        pratica = onboarding.avvia_onboarding(legacy_id=None, dipendente_nome="Z", notifica_dpi=False)
        r = self.client.post(reverse("anagrafica:onboarding_date", args=[pratica.pk]),
                             {"data_assunzione": "2026-12-01", "fine_prova": "2027-03-01"})
        self.assertRedirects(r, reverse("anagrafica:onboarding_detail", args=[pratica.pk]))
        self.assertEqual(pratica.tasks.get(codice="hr_esito_prova").scadenza, date(2027, 3, 1))

    def test_offerta_dalla_scheda(self):
        self.candidato.stato = Candidato.STATO_COLLOQUIO_2
        self.candidato.save()
        r = self.client.post(reverse("anagrafica:recruiting_offerta", args=[self.candidato.pk]),
                             {"inviata_il": "2026-10-07", "data_ingresso": "2026-11-02", "note": "Liv. 3"})
        self.assertRedirects(r, reverse("anagrafica:recruiting_detail", args=[self.candidato.pk]))
        r = self.client.post(reverse("anagrafica:recruiting_offerta_esito", args=[self.candidato.pk]),
                             {"esito": "ACCETTATA"})
        self.candidato.refresh_from_db()
        self.assertTrue(self.candidato.onboarding_pratica.in_pre_ingresso)
        self.assertEqual(self.candidato.onboarding_pratica.data_assunzione, date(2026, 11, 2))
