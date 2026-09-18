"""Libretto sanitario aziendale: catena mansione → requisiti → conforme/non conforme.

Copre il service (stato per riga, origine del requisito, verdetto) e la pagina
stampabile, inclusa la regola di privacy sulla sorveglianza sanitaria.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dpi.models import CategoriaDPI

from .models import Mansione, TipoVisitaMedica, VisitaMedica
from .models_rischi import EsposizioneRischio, FattoreRischio
from .services import libretto_sanitario as libretto_service
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LibrettoSanitarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="lsadmin", email="lsadmin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s)",
                ["l.sani", "Lino", "Sani", "Cromatore-LS", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername=%s", ["l.sani"])
            self.legacy_id = int(cur.fetchone()[0])
        self.mansione = Mansione.objects.create(nome="Cromatore-LS")

    # ── service ──────────────────────────────────────────────────────────

    def test_requisito_mai_registrato_e_da_acquisire_non_scaduto(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita chimica LS")
        self.mansione.visite_richieste.add(tipo)
        dati = libretto_service.libretto(
            self.legacy_id, mansione_nome="Cromatore-LS", include_visite_dettaglio=True
        )
        righe = dati["sezioni"][0]["righe"]
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0].stato, libretto_service.STATO_MANCANTE)
        self.assertEqual(dati["verdetto"], libretto_service.STATO_MANCANTE)
        self.assertEqual(dati["conteggi"]["mancante"], 1)

    def test_visita_scaduta_rende_non_conforme(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita audiometrica LS")
        self.mansione.visite_richieste.add(tipo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=self.legacy_id, tipo=tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
            data_scadenza=self.oggi - timedelta(days=35),
        )
        dati = libretto_service.libretto(
            self.legacy_id, mansione_nome="Cromatore-LS", include_visite_dettaglio=True
        )
        riga = dati["sezioni"][0]["righe"][0]
        self.assertEqual(riga.stato, libretto_service.STATO_KO)
        self.assertEqual(dati["verdetto"], libretto_service.STATO_KO)
        self.assertIn("NON conforme", dati["verdetto_label"])
        self.assertEqual([r.nome for r in dati["criticita"]], ["Visita audiometrica LS"])

    def test_visita_valida_in_scadenza_resta_conforme(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita periodica LS")
        self.mansione.visite_richieste.add(tipo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=self.legacy_id, tipo=tipo,
            data_svolgimento=self.oggi - timedelta(days=330),
            data_scadenza=self.oggi + timedelta(days=20),
        )
        dati = libretto_service.libretto(
            self.legacy_id, mansione_nome="Cromatore-LS", include_visite_dettaglio=True
        )
        self.assertEqual(dati["sezioni"][0]["righe"][0].stato, libretto_service.STATO_WARN)
        self.assertEqual(dati["verdetto"], libretto_service.STATO_WARN)

    def test_origine_requisito_da_fattore_di_rischio(self):
        """Un DPI ereditato da un fattore esposto alla mansione deve dire da dove viene."""
        guanti = CategoriaDPI.objects.create(nome="Guanti cromo LS")
        fattore = FattoreRischio.objects.create(codice="CRLS", nome="Cromo esavalente LS")
        fattore.categorie_dpi.add(guanti)
        EsposizioneRischio.objects.create(fattore=fattore, mansione=self.mansione)
        dati = libretto_service.libretto(self.legacy_id, mansione_nome="Cromatore-LS")
        riga = [r for r in dati["righe"] if r.nome == "Guanti cromo LS"][0]
        self.assertEqual(riga.origini, ["Mansione «Cromatore-LS»"])
        self.assertIn(fattore, dati["fattori"])

    def test_origine_esposizione_diretta(self):
        occhiali = CategoriaDPI.objects.create(nome="Occhiali LS")
        fattore = FattoreRischio.objects.create(codice="SPLS", nome="Spruzzi LS")
        fattore.categorie_dpi.add(occhiali)
        EsposizioneRischio.objects.create(
            fattore=fattore, legacy_anagrafica_id=self.legacy_id
        )
        dati = libretto_service.libretto(self.legacy_id, mansione_nome="Cromatore-LS")
        riga = [r for r in dati["righe"] if r.nome == "Occhiali LS"][0]
        self.assertEqual(riga.origini, ["Esposizione diretta"])

    def test_senza_requisiti_verdetto_na(self):
        dati = libretto_service.libretto(self.legacy_id, mansione_nome="Cromatore-LS")
        self.assertEqual(dati["verdetto"], "na")
        self.assertEqual(dati["conteggi"]["totale"], 0)

    # ── pagina ───────────────────────────────────────────────────────────

    def test_pagina_mostra_requisiti_e_verdetto(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita chimica pagina LS")
        self.mansione.visite_richieste.add(tipo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=self.legacy_id, tipo=tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
            data_scadenza=self.oggi - timedelta(days=10),
        )
        resp = self.client.get(
            reverse("anagrafica:dipendente_libretto_sanitario", args=[self.legacy_id])
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Libretto sanitario aziendale", body)
        self.assertIn("NON conforme", body)
        self.assertIn("Visita chimica pagina LS", body)
        self.assertIn("Da sistemare", body)

    def test_pagina_senza_gate_sorveglianza_nasconde_la_tipologia_di_visita(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita riservata LS")
        self.mansione.visite_richieste.add(tipo)
        dati = libretto_service.libretto(
            self.legacy_id, mansione_nome="Cromatore-LS", include_visite_dettaglio=False
        )
        nomi = [r.nome for r in dati["sezioni"][0]["righe"]]
        self.assertEqual(nomi, ["Visita medica richiesta"])
        self.assertNotIn("Visita riservata LS", nomi)

    # ── quadro generale ──────────────────────────────────────────────────

    def test_generale_kpi_e_vista_adempimenti(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita generale LS")
        self.mansione.visite_richieste.add(tipo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=self.legacy_id, tipo=tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
            data_scadenza=self.oggi - timedelta(days=5),
        )
        guanti = CategoriaDPI.objects.create(nome="Guanti generale LS")
        self.mansione.dpi_richiesti.add(guanti)

        url = reverse("anagrafica:libretto_sanitario_generale")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Libretto sanitario aziendale", body)
        self.assertIn("Sani", body)

        ctx = resp.context
        self.assertEqual(ctx["conta_stato"]["ko"], 1)        # visita scaduta
        self.assertEqual(ctx["conta_stato"]["mancante"], 1)  # DPI mai consegnato
        self.assertEqual(ctx["n_persone_ko"], 1)
        self.assertEqual(ctx["n_obblighi"], 2)

        resp2 = self.client.get(url, {"vista": "adempimenti"})
        self.assertEqual(resp2.status_code, 200)
        righe = list(resp2.context["page_obj"].object_list)
        self.assertEqual([r["riga"].nome for r in righe],
                         ["Visita generale LS", "Guanti generale LS"])  # peggiori in testa

    def test_generale_filtro_stato_e_dominio(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita filtro LS")
        self.mansione.visite_richieste.add(tipo)
        guanti = CategoriaDPI.objects.create(nome="Guanti filtro LS")
        self.mansione.dpi_richiesti.add(guanti)
        url = reverse("anagrafica:libretto_sanitario_generale")
        resp = self.client.get(url, {"vista": "adempimenti", "dominio": "dpi"})
        nomi = [r["riga"].nome for r in resp.context["page_obj"].object_list]
        self.assertEqual(nomi, ["Guanti filtro LS"])
        resp2 = self.client.get(url, {"vista": "adempimenti", "stato": "ko"})
        self.assertEqual(list(resp2.context["page_obj"].object_list), [])

    def test_generale_export_csv_adempimenti(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita csv LS")
        self.mansione.visite_richieste.add(tipo)
        resp = self.client.get(
            reverse("anagrafica:libretto_sanitario_generale"),
            {"vista": "adempimenti", "format": "csv"},
        )
        self.assertEqual(resp.status_code, 200)
        testo = resp.content.decode("utf-8-sig")
        self.assertIn("Perch", testo)          # intestazione "Perché è dovuto"
        self.assertIn("Visita csv LS", testo)
        self.assertIn("Cromatore-LS", testo)

    def test_dipendente_inesistente_redirige(self):
        resp = self.client.get(
            reverse("anagrafica:dipendente_libretto_sanitario", args=[999999])
        )
        self.assertEqual(resp.status_code, 302)
