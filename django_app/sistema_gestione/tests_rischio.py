"""Analisi del rischio del MOD.165 (registro minacce, monitoraggio controlli, piano OT). Solo dati sintetici."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from .acl_bootstrap import _ROUTE_BINDINGS, PERM_SOA_EDIT, PERM_SOA_VIEW
from .models import ControlloIso27002, RischioMinaccia, ScenarioRischioOT, SoaRevisione
from .services import soa as soa_service
from .services.mod165_rischi_import import AnalisiRischioImportata, MinacciaImportata, ScenarioOTImportato
from .services.rischio import analizza, fascia, residuo
from .tests_audit import AuditBase, _request


class RischioBase(AuditBase):
    def setUp(self):
        super().setUp()
        soa_service.assicura_catalogo()
        self.rev = soa_service.nuova_revisione(numero=1, motivo="Sintetica")
        self.rev.voci.update(vulnerabilita=1, livello=4)
        self.rev.voci.filter(controllo__codice="5.15").update(vulnerabilita=3, livello=2)
        self.c = {c.codice: c for c in ControlloIso27002.objects.filter(codice__in=["5.1", "5.15", "8.7"])}

    def minaccia(self, nome="Minaccia sintetica", inerente=36, codici=("5.1", "5.15"), **kw):
        m = RischioMinaccia.objects.create(revisione=self.rev, minaccia=nome, rischio_inerente=inerente, **kw)
        m.controlli.set([self.c[k] for k in codici])
        return m


class CalcoloTest(RischioBase):
    def test_formula_e_fasce_del_mod165(self):
        self.assertEqual(residuo(36, 3), 27)
        self.assertEqual(residuo(48, 2), 24)
        self.assertEqual(residuo(12, 3), 9)
        self.assertIsNone(residuo(None, 2))
        self.assertEqual([fascia(v) for v in (0, 10, 11, 30, 31, 48)], ["zero", "f1", "f2", "f3", "f4", "f5"])

    def test_residuo_dalla_vulnerabilita_massima_della_soa(self):
        self.minaccia()
        self.minaccia("Sotto soglia", inerente=16, codici=("5.1",))
        analisi = analizza(self.rev)
        alta, bassa = analisi.minacce
        self.assertEqual((alta.vulnerabilita, alta.residuo, alta.accettabile), (3, 27, True))
        self.assertEqual([c.codice for c in alta.critici], ["5.15"])
        self.assertEqual((bassa.residuo, bassa.accettabile), (4, True))
        self.rev.soglia_rischio = 20
        self.rev.save()
        self.assertEqual(len(analizza(self.rev).non_accettabili), 1)

    def test_il_residuo_segue_la_soa_e_segnala_la_differenza_dal_modulo(self):
        self.minaccia(residuo_registrato=27)
        self.assertFalse(analizza(self.rev).differenze_registrate)
        self.rev.voci.filter(controllo__codice="5.15").update(vulnerabilita=1)
        analisi = analizza(self.rev)
        self.assertEqual(analisi.minacce[0].residuo, 9)
        self.assertEqual(len(analisi.differenze_registrate), 1)

    def test_monitoraggio_controlli_e_residuo_futuro(self):
        self.minaccia()
        self.minaccia("Altra", inerente=48, codici=("5.15",))
        self.rev.voci.filter(controllo__codice="5.15").update(vulnerabilita_attesa=1)
        riga = next(r for r in analizza(self.rev).controlli if r.voce.controllo.codice == "5.15")
        self.assertEqual((riga.minacce, riga.inerente_max, riga.residuo, riga.accettabile), (2, 48, 36, False))
        self.assertEqual((riga.futuro, riga.futuro_accettabile), (12, True))

    def test_scenario_ot_residuo_attuale_e_atteso(self):
        s = ScenarioRischioOT.objects.create(revisione=self.rev, codice="OT-01", scenario="Scenario sintetico",
                                             rischio_inerente=48, vulnerabilita_attesa=1)
        s.controlli.set([self.c["5.15"], self.c["8.7"]])
        riga = analizza(self.rev).scenari[0]
        self.assertEqual((riga.vulnerabilita, riga.residuo, riga.atteso), (3, 36, 12))
        self.assertFalse(riga.accettabile)

    def test_nuova_revisione_soa_copia_l_analisi(self):
        self.minaccia()
        s = ScenarioRischioOT.objects.create(revisione=self.rev, codice="OT-01", scenario="Scenario sintetico")
        s.controlli.set([self.c["8.7"]])
        self.rev.soglia_rischio = 25
        self.rev.voci.filter(controllo__codice="5.1").update(vulnerabilita_attesa=0)
        self.rev.stato = SoaRevisione.STATO_APPROVATA
        self.rev.save()
        nuova = soa_service.nuova_revisione(utente=self.user, motivo="Copia")
        self.assertEqual(nuova.soglia_rischio, 25)
        self.assertEqual(nuova.minacce.get().controlli.count(), 2)
        self.assertEqual(nuova.scenari_ot.get().controlli.get().codice, "8.7")
        self.assertEqual(nuova.voci.get(controllo__codice="5.1").vulnerabilita_attesa, 0)
        self.assertEqual(self.rev.minacce.count(), 1)


def _analisi_sintetica():
    return AnalisiRischioImportata(
        minacce=[MinacciaImportata(gruppo="G", agente="A", minaccia="Minaccia sintetica", rischio_inerente=36,
                                   vulnerabilita=3, residuo=27, controlli=["5.1", "5.15"]),
                 MinacciaImportata(gruppo="G", agente="A", minaccia="Seconda", rischio_inerente=16,
                                   vulnerabilita=1, residuo=4, controlli=["5.1"])],
        vulnerabilita_attese={"5.15": 2},
        scenari_ot=[ScenarioOTImportato(codice="OT-01", scenario="Scenario sintetico", controlli="8.7 5.1",
                                        rischio_inerente=12, vulnerabilita_attesa=1, scadenza="30/06/2027")],
        soglia=30,
    )


@patch("sistema_gestione.management.commands.importa_rischi_mod165.leggi_analisi_rischio",
       side_effect=lambda *_a, **_k: _analisi_sintetica())
class ComandoImportTest(RischioBase):
    def test_dry_run_non_scrive_e_confronta_con_la_soa(self, _mock):
        out = StringIO()
        call_command("importa_rischi_mod165", "file.pdf", "--numero", "1", stdout=out)
        self.assertIn("2 uguali, 0 diversi", out.getvalue())
        self.assertFalse(RischioMinaccia.objects.exists())

    def test_apply_e_sostituzione_solo_in_bozza(self, _mock):
        call_command("importa_rischi_mod165", "file.pdf", "--numero", "1", "--apply", stdout=StringIO())
        self.assertEqual(self.rev.minacce.count(), 2)
        self.assertEqual(self.rev.minacce.get(minaccia="Minaccia sintetica").controlli.count(), 2)
        ot = self.rev.scenari_ot.get()
        self.assertEqual((ot.scadenza.isoformat(), ot.controlli.count()), ("2027-06-30", 2))
        self.assertEqual(self.rev.voci.get(controllo__codice="5.15").vulnerabilita_attesa, 2)
        with self.assertRaises(CommandError):
            call_command("importa_rischi_mod165", "file.pdf", "--numero", "1", "--apply", stdout=StringIO())
        call_command("importa_rischi_mod165", "file.pdf", "--numero", "1", "--apply", "--sostituisci", stdout=StringIO())
        self.assertEqual(self.rev.minacce.count(), 2)
        SoaRevisione.objects.filter(pk=self.rev.pk).update(stato=SoaRevisione.STATO_APPROVATA)
        with self.assertRaises(CommandError):
            call_command("importa_rischi_mod165", "file.pdf", "--numero", "1", "--apply", "--sostituisci", stdout=StringIO())

    def test_revisione_inesistente(self, _mock):
        with self.assertRaises(CommandError):
            call_command("importa_rischi_mod165", "file.pdf", "--numero", "9", stdout=StringIO())


class VisteRischioTest(RischioBase):
    def test_binding_delle_route(self):
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:soa_rischi"], PERM_SOA_VIEW)
        for nome in ("soa_rischio_soglia", "soa_rischio_minaccia", "soa_rischio_minaccia_nuova", "soa_rischio_ot",
                     "soa_rischio_ot_nuovo"):
            self.assertEqual(_ROUTE_BINDINGS[f"sistema_gestione:{nome}"], PERM_SOA_EDIT)

    @patch("sistema_gestione.rischio_views._has_perm", return_value=True)
    def test_pagina_ed_export(self, _perm):
        from .rischio_views import soa_rischi

        self.minaccia()
        html = soa_rischi(_request(self.user, method="get"), 1).content.decode()
        self.assertIn("Rischio per minaccia", html)
        self.assertIn("Minaccia sintetica", html)
        self.assertNotIn("{#", html)
        risposta = soa_rischi(_request(self.user, method="get", data={"formato": "xlsx"}), 1)
        self.assertIn("Rischi_MOD165_Rev1.xlsx", risposta["Content-Disposition"])

    @patch("sistema_gestione.rischio_views._has_perm", return_value=True)
    def test_modifica_solo_in_bozza(self, _perm):
        from .rischio_views import soa_rischio_minaccia

        m = self.minaccia()
        dati = {"gruppo": "G", "agente": "A", "minaccia": "Rinominata", "rischio_inerente": "24",
                "controlli": [self.c["5.1"].pk], "note": "", "ordine": "10"}
        soa_rischio_minaccia(_request(self.user, data=dati), 1, m.pk)
        m.refresh_from_db()
        self.assertEqual((m.minaccia, m.rischio_inerente, m.controlli.count()), ("Rinominata", 24, 1))
        SoaRevisione.objects.filter(pk=self.rev.pk).update(stato=SoaRevisione.STATO_APPROVATA)
        soa_rischio_minaccia(_request(self.user, data={**dati, "minaccia": "Bloccata"}), 1, m.pk)
        m.refresh_from_db()
        self.assertEqual(m.minaccia, "Rinominata")

    @patch("sistema_gestione.rischio_views._has_perm", return_value=True)
    def test_inerente_oltre_64_rifiutato(self, _perm):
        from .rischio_views import soa_rischio_minaccia

        soa_rischio_minaccia(_request(self.user, data={"minaccia": "Troppo", "rischio_inerente": "90", "ordine": "10"}), 1)
        self.assertFalse(RischioMinaccia.objects.filter(minaccia="Troppo").exists())
