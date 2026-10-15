"""Mansionario fase 6: il vecchio catalogo MansioneRischio confluisce in Mansione senza perdere dati.

Migra indietro a 0173, popola il vecchio catalogo con dati sintetici, migra a
0176 e controlla dove sono finiti. Gira anche su SQL Server.
"""
from __future__ import annotations

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

PRIMA = [("anagrafica", "0173_mansionario_competenze_dati")]
DOPO = [("anagrafica", "0176_mansioni_rischio_unificate_pulizia")]


class UnificazioneMansioniRischioTests(TransactionTestCase):

    def _migra(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        self._migra(DOPO)

    def test_nulla_va_perso(self):
        apps = self._migra(PRIMA)
        Mansione = apps.get_model("anagrafica", "Mansione")
        MansioneRischio = apps.get_model("anagrafica", "MansioneRischio")
        Link = apps.get_model("anagrafica", "MansioneLavorativaRischio")
        Override = apps.get_model("anagrafica", "DipendenteMansioneRischioOverride")
        Regola = apps.get_model("anagrafica", "TrainingRequirementRule")
        TipoVisita = apps.get_model("anagrafica", "TipoVisitaMedica")
        Fattore = apps.get_model("anagrafica", "FattoreRischio")

        audiometria = TipoVisita.objects.create(nome="Audiometria (sintetica)")
        spirometria = TipoVisita.objects.create(nome="Spirometria (sintetica)")
        rumore = Fattore.objects.create(codice="RUM-SINT", nome="Rumore sintetico")
        lavorativa = Mansione.objects.create(nome="TORNITORE SINTETICO")
        gia = Mansione.objects.create(nome="ADDETTO VERNICIATURA SINT")

        # Nuova voce del catalogo
        mr_rumore = MansioneRischio.objects.create(codice="MR-RUM", nome="ESPOSTO RUMORE SINT",
                                                   livello_rischio_dvr="A", dvr_revisione="7")
        mr_rumore.visite.add(audiometria)
        mr_rumore.fattori.add(rumore)
        # Stesso nome di una voce che c'è già: si fonde lì
        mr_vern = MansioneRischio.objects.create(codice="MR-VER", nome="addetto verniciatura sint",
                                                 dvr_revisione="3")
        mr_vern.visite.add(spirometria)

        Link.objects.create(mansione=lavorativa, mansione_rischio=mr_rumore)
        Regola.objects.create(mansione_rischio=mr_rumore, is_active=True, note="regola sintetica")
        Regola.objects.create(mansione=lavorativa, mansione_rischio=mr_vern, is_active=True, note="doppio bersaglio")
        Override.objects.create(legacy_anagrafica_id=901, mansione_rischio=mr_rumore, azione="ADD",
                                motivo="Addetto antincendio sintetico", data_inizio=date(2026, 1, 1))
        Override.objects.create(legacy_anagrafica_id=902, mansione_rischio=mr_vern, azione="EXCLUDE",
                                motivo="Su indicazione del medico (sintetico)", data_inizio=date(2026, 1, 1))

        apps = self._migra(DOPO)
        Mansione = apps.get_model("anagrafica", "Mansione")
        Override = apps.get_model("anagrafica", "DipendenteMansioneRischioOverride")
        Regola = apps.get_model("anagrafica", "TrainingRequirementRule")
        Esposizione = apps.get_model("anagrafica", "EsposizioneRischio")

        nuova = Mansione.objects.get(nome="ESPOSTO RUMORE SINT")
        self.assertEqual(nuova.livello_rischio, "A")
        self.assertEqual(nuova.dvr_revisione, "7")
        self.assertEqual(list(nuova.visite_richieste.values_list("nome", flat=True)), ["Audiometria (sintetica)"])
        self.assertTrue(Esposizione.objects.filter(mansione=nuova, fattore__codice="RUM-SINT").exists())

        fusa = Mansione.objects.get(nome="ADDETTO VERNICIATURA SINT")
        self.assertEqual(fusa.dvr_revisione, "3")
        self.assertIn("Spirometria (sintetica)", fusa.visite_richieste.values_list("nome", flat=True))
        self.assertEqual(Mansione.objects.filter(nome__iexact="addetto verniciatura sint").count(), 1)

        # Chi aveva la mansione collegata resta tenuto agli stessi obblighi
        lavorativa = Mansione.objects.get(nome="TORNITORE SINTETICO")
        self.assertIn("Audiometria (sintetica)", lavorativa.visite_richieste.values_list("nome", flat=True))
        self.assertTrue(Esposizione.objects.filter(mansione=lavorativa, fattore__codice="RUM-SINT").exists())

        self.assertTrue(Regola.objects.filter(mansione=nuova, note="regola sintetica").exists())
        self.assertTrue(Regola.objects.filter(mansione=lavorativa, note="doppio bersaglio").exists())
        self.assertTrue(Regola.objects.filter(mansione=fusa, note="doppio bersaglio").exists())

        self.assertEqual(Override.objects.get(legacy_anagrafica_id=901).mansione_rischio_id, nuova.pk)
        self.assertEqual(Override.objects.get(legacy_anagrafica_id=902).mansione_rischio_id, fusa.pk)
