"""HR gestionale: cambio mansione con piano di adeguamento, libretto e conformità sul
motore unico, cruscotto HR, scadenzario qualifiche.

Anagrafiche legacy vere nel DB di test (sintetiche): gli spostamenti leggono e
scrivono la tabella ``anagrafica_dipendenti``.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    AdempimentoCambioMansione, DipendenteAnagraficaAziendale, DipendenteQualifica,
    EsposizioneRischio, FattoreRischio, Mansione, TipoQualifica, TipoVisitaMedica, TrainingCourse,
    TrainingEmployeeRecord, TrainingPlan, TrainingRequirementRule, VisitaMedica,
)
from anagrafica.services import cambio_mansione, conformita, libretto_sanitario
from anagrafica.services.assegnazioni import crea_assegnazione
from anagrafica.services.visite import stato_visite
from core.legacy_models import AnagraficaDipendente

User = get_user_model()
OGGI = timezone.localdate()


class _Scenario(TestCase):
    """Operaio che passa a saldatore: nuovo rischio (fumi) con visita annuale e un corso."""

    def setUp(self):
        super().setUp()
        self.dip = AnagraficaDipendente.objects.create(nome="Luca", cognome="Bianchi", mansione="Operaio",
                                                       reparto="Produzione", aliasusername="lbianchi.test")
        self.lid = self.dip.id
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.lid,
                                                     data_assunzione_ultima=OGGI - timedelta(days=900))
        self.operaio = Mansione.objects.create(nome="Operaio")
        self.saldatore = Mansione.objects.create(nome="Saldatore")
        self.annuale = TipoVisitaMedica.objects.create(nome="Visita medica annuale", durata_mesi=12,
                                                       categoria="Visita medica")
        self.biennale = TipoVisitaMedica.objects.create(nome="Visita medica biennale", durata_mesi=24,
                                                        categoria="Visita medica")
        self.operaio.visite_richieste.add(self.biennale)
        self.fumi = FattoreRischio.objects.create(codice="FUMI", nome="Fumi di saldatura",
                                                  richiede_visita_medica=True)
        self.fumi.tipi_visita.add(self.annuale)
        EsposizioneRischio.objects.create(fattore=self.fumi, mansione=self.saldatore)
        piano, _ = TrainingPlan.objects.get_or_create(codice="PT", defaults={"nome": "Piano", "stato": "ATTIVO"})
        self.corso = TrainingCourse.objects.create(piano=piano, codice="SALD", titolo="Sicurezza in saldatura",
                                                   durata_ore_teorica=8, validita_mesi=60)
        TrainingRequirementRule.objects.create(corso=self.corso, mansione=self.saldatore)
        # Visita biennale fatta 14 mesi fa: valida da operaio, scaduta con la periodicita' annuale.
        self.visita = VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.biennale,
                                                  data_svolgimento=OGGI - timedelta(days=430))
        self.admin = User.objects.create_superuser("hr_admin_test", "hr@example.invalid", "x")


class ConfrontoEPianoTest(_Scenario):
    def test_confronto_rischi_e_obblighi(self):
        c = cambio_mansione.confronta(self.lid, "Saldatore")
        self.assertEqual([f.nome for f in c.rischi_acquisiti], ["Fumi di saldatura"])
        self.assertEqual([v.corso.codice for v in c.corsi_nuovi], ["SALD"])
        # Stessa famiglia «Visita medica», periodicita' piu' stretta: la visita fatta scade prima.
        self.assertEqual([v.tipo_da_mostrare.nome for v in c.visite_nuove], ["Visita medica annuale"])
        self.assertEqual(c.visite_nuove[0].tipo.nome, "Visita medica biennale")  # la visita fatta
        self.assertLess(c.visite_nuove[0].scadenza, OGGI)
        dati = c.as_dict(include_visite_dettaglio=False)
        self.assertTrue(dati["cambia_qualcosa"])
        self.assertNotIn("annuale", " ".join(dati["visite_nuove"]))  # niente nomi visita senza permesso

    def test_piano_generato_e_chiuso_da_solo(self):
        assegnazione = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=10), mansione="Saldatore",
                                         user=self.admin)
        piano = {(a.tipo, a.descrizione) for a in assegnazione.adempimenti.all()}
        self.assertEqual(piano, {("VISITA", "Visita: Visita medica annuale"), ("FORMAZIONE", "Corso: Sicurezza in saldatura")})
        self.assertTrue(all(a.entro_il == assegnazione.data_inizio for a in assegnazione.adempimenti.all()))

        VisitaMedica.objects.create(legacy_anagrafica_id=self.lid, tipo=self.annuale, data_svolgimento=OGGI)
        TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=self.lid, idoneo=True,
                                              data_completamento=OGGI, data_scadenza=OGGI + timedelta(days=1800))
        esito = cambio_mansione.aggiorna_piani([self.lid])
        self.assertEqual(esito["chiusi"], 2)
        self.assertFalse(assegnazione.adempimenti.filter(stato=AdempimentoCambioMansione.STATO_APERTO).exists())
        self.assertTrue(all(a.chiusura_automatica for a in assegnazione.adempimenti.all()))

    def test_correggere_la_mansione_rigenera_il_piano(self):
        from anagrafica.services.assegnazioni import modifica_assegnazione

        assegnazione = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=10), mansione="Saldatore",
                                         user=self.admin)
        modifica_assegnazione(assegnazione, data_inizio=assegnazione.data_inizio, mansione="Operaio", user=self.admin)
        self.assertFalse(assegnazione.adempimenti.filter(stato=AdempimentoCambioMansione.STATO_APERTO).exists())

    def test_attivazione_ricalcola_le_scadenze(self):
        from django.db import connection

        # Nel TestCase la transazione non si chiude mai: il callback registrato dal
        # setUp (visita creata) resta pendente e raccoglierebbe anche questa persona.
        # In produzione la lista on_commit si svuota a ogni commit.
        connection._scadenze_ricalcolo = None
        with self.captureOnCommitCallbacks(execute=True):
            crea_assegnazione(self.lid, data_inizio=OGGI, mansione="Saldatore", user=self.admin)
        self.visita.refresh_from_db()
        self.assertLess(self.visita.data_scadenza, OGGI)  # biennale ora vale come annuale
        self.assertIn("annuale", self.visita.scadenza_nota)


class VisteCambioMansioneTest(_Scenario):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.assegnazione = crea_assegnazione(self.lid, data_inizio=OGGI + timedelta(days=5),
                                              mansione="Saldatore", user=self.admin)

    def test_anteprima_json_con_confronto(self):
        risposta = self.client.get(reverse("anagrafica:dipendente_assegnazione_verifica", args=[self.lid]),
                                   {"mansione": "Saldatore"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        dati = risposta.json()
        self.assertEqual(dati["confronto"]["rischi_acquisiti"], ["Fumi di saldatura"])
        self.assertIn("Sicurezza in saldatura: mai frequentato", dati["confronto"]["corsi_nuovi"])

    def test_non_necessario_riapri_e_audit(self):
        from core.models import AuditLog

        ad = self.assegnazione.adempimenti.get(tipo="VISITA")
        url = reverse("anagrafica:adempimento_cambio_mansione_stato", args=[self.lid, ad.pk])
        self.client.post(url, {"azione": "non_necessario", "motivo": ""})
        ad.refresh_from_db()
        self.assertTrue(ad.aperto)  # il motivo e' obbligatorio
        self.client.post(url, {"azione": "non_necessario", "motivo": "Valutato dal medico competente"})
        ad.refresh_from_db()
        self.assertEqual(ad.stato, AdempimentoCambioMansione.STATO_NON_NECESSARIO)
        self.assertEqual(ad.chiuso_da, self.admin)
        self.client.post(url, {"azione": "riapri"})
        ad.refresh_from_db()
        self.assertTrue(ad.aperto)
        self.assertEqual(AuditLog.objects.filter(azione="cambio_mansione_adempimento").count(), 2)

    def test_pagine_scheda_quadro_e_dashboard(self):
        scheda = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.lid]))
        self.assertContains(scheda, "Piano di adeguamento al cambio mansione")
        self.assertContains(scheda, "Corso: Sicurezza in saldatura")
        quadro = self.client.get(reverse("anagrafica:cambi_mansione"))
        self.assertContains(quadro, "BIANCHI LUCA")
        self.assertContains(quadro, "Sicurezza in saldatura")
        dashboard = self.client.get(reverse("anagrafica:index"))
        self.assertContains(dashboard, "Stato di conformità")
        self.assertContains(dashboard, "Cambi mansione")
        self.assertContains(dashboard, "BIANCHI LUCA")
        for pagina in (scheda, quadro, dashboard):
            self.assertNotContains(pagina, "{#")

    def test_senza_permessi(self):
        utente = User.objects.create_user("hr_nessuno_test", password="x")
        self.client.force_login(utente)
        ad = self.assegnazione.adempimenti.first()
        self.client.post(reverse("anagrafica:adempimento_cambio_mansione_stato", args=[self.lid, ad.pk]),
                         {"azione": "non_necessario", "motivo": "x"})
        ad.refresh_from_db()
        self.assertTrue(ad.aperto)
        self.assertNotEqual(self.client.get(reverse("anagrafica:cambi_mansione")).status_code, 200)


class MotoreUnicoTest(_Scenario):
    def test_conformita_e_libretto_per_famiglia(self):
        # Da operaio la biennale di 14 mesi fa e' valida.
        stato = conformita.stato_conformita(self.lid)
        self.assertEqual(stato["visite"]["esito"], "ok")
        libretto = libretto_sanitario.libretto(self.lid, include_visite_dettaglio=True)
        visite = [r for r in libretto["righe_obbligo"] if r.dominio == "visite"]
        self.assertEqual([(r.nome, r.stato) for r in visite], [("Visita medica biennale", "ok")])
        # Ipotesi saldatore (idoneita'): la periodicita' annuale la rende scaduta, il corso manca.
        idn = conformita.stato_conformita(self.lid, mansione="Saldatore", include_visite_dettaglio=True)["idoneita"]
        self.assertIn("Visita: Visita medica annuale", idn["scaduti"])
        self.assertIn("Corso: Sicurezza in saldatura", idn["mancanti"])

    def test_stato_visite_della_scheda(self):
        voci = stato_visite(self.lid)
        self.assertEqual([(v["tipo"].nome, v["stato"]) for v in voci], [("Visita medica biennale", "valida")])
        self.assertEqual(voci[0]["ultima"], self.visita)


class ScadenzarioQualificheTest(TestCase):
    def test_rinnovo_non_lascia_la_vecchia_scaduta(self):
        dip = AnagraficaDipendente.objects.create(nome="Anna", cognome="Verdi", aliasusername="averdi.test")
        tipo = TipoQualifica.objects.create(nome="Carrellista")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=dip.id, tipo=tipo,
                                           data_conseguimento=date(2020, 1, 1), data_scadenza=OGGI - timedelta(days=30))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=dip.id, tipo=tipo,
                                           data_conseguimento=OGGI - timedelta(days=20),
                                           data_scadenza=OGGI + timedelta(days=20))
        self.client.force_login(User.objects.create_superuser("hr_sq_test", "sq@example.invalid", "x"))
        pagina = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "qualifica"})
        self.assertEqual(pagina.context["n_scadute"], 0)  # la vecchia registrazione e' stata rinnovata
        self.assertEqual(pagina.context["n_30gg"], 1)


class MigrazioneAclTest(TestCase):
    def test_binding_copiato_dalla_rotta_sorella(self):
        import importlib

        from django.apps import apps

        from core.models import PermissionDefinition, RoutePermissionBinding

        PermissionDefinition.objects.get_or_create(code="anagrafica.test.spostamenti",
                                                   defaults={"module": "anagrafica", "label": "x"})
        RoutePermissionBinding.objects.filter(route_name__in=[
            "anagrafica:dipendente_assegnazione_create", "anagrafica:cambi_mansione"]).delete()
        RoutePermissionBinding.objects.create(route_name="anagrafica:dipendente_assegnazione_create", path_pattern="",
                                              match_strategy="exact", permission_id="anagrafica.test.spostamenti",
                                              priority=70, is_active=True)
        modulo = importlib.import_module("anagrafica.migrations.0135_cambio_mansione_acl")
        modulo.avanti(apps, None)
        modulo.avanti(apps, None)  # idempotente
        nuovo = RoutePermissionBinding.objects.get(route_name="anagrafica:cambi_mansione")
        self.assertEqual(nuovo.permission_id, "anagrafica.test.spostamenti")
        self.assertEqual(nuovo.priority, 70)
