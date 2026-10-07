"""Scadenze HR dal motore unico: cache formazione, scadenza effettiva delle visite.

Persone sintetiche come in ``tests_reportistica_dati_corretti`` (si sostituisce
``carica_dipendenti``).
"""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from anagrafica.models import (
    DipendenteRuoloOperativo, Mansione, RuoloOperativo, TipoVisitaMedica, TrainingCourse, TrainingDeadline,
    TrainingEmployeeRecord, TrainingPlan, TrainingRequirementRule, VisitaMedica,
)
from anagrafica.models import _add_months
from anagrafica.services import requisiti, scadenze
from anagrafica.services.training_deadline_service import refresh_deadlines
from anagrafica.tests_reportistica_dati_corretti import _persone

OGGI = timezone.localdate()


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        p = patch("anagrafica.reportistica.dati.carica_dipendenti", side_effect=_persone)
        p.start()
        self.addCleanup(p.stop)

    def corso(self, codice: str, validita: int = 12) -> TrainingCourse:
        piano, _ = TrainingPlan.objects.get_or_create(codice="PT", defaults={"nome": "Piano test", "stato": "ATTIVO"})
        return TrainingCourse.objects.create(piano=piano, codice=codice, titolo=f"Corso {codice}",
                                             durata_ore_teorica=4, validita_mesi=validita)


class ScadenzaPrudenteTest(TestCase):
    def test_periodicita_piu_stretta_anticipa(self):
        fatta = date(2025, 1, 10)
        self.assertEqual(requisiti.scadenza_prudente(fatta, 24, 12), date(2026, 1, 10))

    def test_periodicita_piu_lunga_non_allunga(self):
        self.assertEqual(requisiti.scadenza_prudente(date(2025, 1, 10), 12, 24), date(2026, 1, 10))

    def test_senza_requisito_vale_il_tipo(self):
        self.assertEqual(requisiti.scadenza_prudente(date(2025, 1, 10), 24, None), date(2027, 1, 10))
        self.assertIsNone(requisiti.scadenza_prudente(date(2025, 1, 10), 0, None))
        self.assertEqual(requisiti.scadenza_prudente(date(2025, 1, 10), 0, 12), date(2026, 1, 10))


class VisiteTest(_Base):
    def setUp(self):
        super().setUp()
        self.annuale = TipoVisitaMedica.objects.create(nome="Visita medica annuale", durata_mesi=12,
                                                       categoria="Visita medica")
        self.biennale = TipoVisitaMedica.objects.create(nome="Visita medica biennale", durata_mesi=24,
                                                        categoria="Visita medica")
        self.ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.annuale.ruoli_operativi.add(self.ruolo)

    def test_biennale_fatta_ma_richiesta_annuale(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        fatta = OGGI - timedelta(days=420)
        v = VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=fatta)
        self.assertEqual(v.data_scadenza, _add_months(fatta, 24))

        esito = scadenze.ricalcola_visite()
        v.refresh_from_db()
        self.assertEqual(esito["aggiornate"], 1)
        self.assertEqual(v.data_scadenza, _add_months(fatta, 12))
        self.assertLess(v.data_scadenza, OGGI)  # con la periodicita' richiesta e' gia' scaduta
        self.assertIn("Visita medica annuale", v.scadenza_nota)

        # Requisito tolto (ruolo concluso): torna la scadenza del tipo.
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=902).update(data_fine=OGGI - timedelta(days=1))
        scadenze.ricalcola_visite()
        v.refresh_from_db()
        self.assertEqual(v.data_scadenza, _add_months(fatta, 24))
        self.assertEqual(v.scadenza_nota, "")

    def test_salvataggio_della_visita_ricalcola_dopo_il_commit(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        fatta = OGGI - timedelta(days=30)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            v = VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=fatta)
            VisitaMedica.objects.create(legacy_anagrafica_id=901, tipo=self.annuale, data_svolgimento=fatta)
        self.assertEqual(len(callbacks), 1)  # un solo ricalcolo per transazione
        v.refresh_from_db()
        self.assertEqual(v.data_scadenza, _add_months(fatta, 12))

    def test_verifica_integrita_sola_lettura(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        fatta = OGGI - timedelta(days=30)
        sbagliato = TipoVisitaMedica.objects.create(nome="Visita medica quinquennale", durata_mesi=12)
        v = VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=fatta)
        # Scadenza del tipo rimasta senza ricalcolo (anticipo atteso a 12 mesi).
        VisitaMedica.objects.filter(pk=v.pk).update(data_scadenza=_add_months(fatta, 24), scadenza_nota="")
        rotta = VisitaMedica.objects.create(legacy_anagrafica_id=901, tipo=self.annuale, data_svolgimento=fatta)
        VisitaMedica.objects.filter(pk=rotta.pk).update(data_scadenza=fatta - timedelta(days=1))

        out = StringIO()
        call_command("verifica_scadenze_visite", stdout=out)
        testo = out.getvalue()
        self.assertIn(f"tipo #{sbagliato.pk}", testo)
        self.assertIn(f"visita #{v.pk}", testo.split("2a.")[1].split("2b.")[0])
        self.assertIn(f"visita #{rotta.pk}", testo.split("3b.")[1].split("3c.")[0])
        v.refresh_from_db()
        self.assertEqual(v.data_scadenza, _add_months(fatta, 24))  # non scrive

        scadenze.ricalcola_visite()
        VisitaMedica.objects.filter(pk=rotta.pk).update(data_scadenza=_add_months(fatta, 12))
        sbagliato.delete()
        out = StringIO()
        call_command("verifica_scadenze_visite", stdout=out)
        self.assertIn("Nessuna anomalia", out.getvalue())
        self.assertIn(f"visita #{v.pk}", out.getvalue().split("2b.")[1])

    def test_scheda_visita_spiega_scadenza_anticipata(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        fatta = OGGI - timedelta(days=30)
        v = VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=fatta)
        scadenze.ricalcola_visite()
        admin = get_user_model().objects.create_superuser("vm_admin", "vm@example.test", "x")
        self.client.force_login(admin)
        with patch("anagrafica.views._can_view_visite_mediche", return_value=True):
            resp = self.client.get(reverse("anagrafica:visita_medica_dettaglio", args=[v.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scadenza anticipata")
        self.assertContains(resp, f"{_add_months(fatta, 24):%d/%m/%Y} previsto dal tipo")

    def test_dettaglio_visite_dal_motore(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=self.ruolo)
        VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale,
                                    data_svolgimento=OGGI - timedelta(days=30))
        ctx = requisiti.ambito()
        voce = requisiti.visite(ctx, {p.id: p for p in ctx.dipendenti()})[0]
        self.assertTrue(voce.richiesta)
        self.assertLess(voce.scadenza, voce.scadenza_propria)
        self.assertIn("anticipata", voce.nota)


class FormazioneTest(_Base):
    def test_cache_ricostruita_dal_motore(self):
        corso = self.corso("SALD")
        mansione = Mansione.objects.create(nome="Saldatore")
        TrainingRequirementRule.objects.create(corso=corso, mansione=mansione)
        # Completamento sul doppione 951 di ROSSI ANNA (901), scaduto dopo l'ultimo ricalcolo.
        TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=951, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=400),
                                              data_scadenza=OGGI - timedelta(days=35))
        vecchia = TrainingDeadline.objects.create(corso=corso, legacy_anagrafica_id=951, stato_scadenza="VALIDO",
                                                  is_required=True)
        cessato = TrainingDeadline.objects.create(corso=corso, legacy_anagrafica_id=903, stato_scadenza="SCADUTO",
                                                  is_required=True)
        orfana = TrainingDeadline.objects.create(corso=self.corso("X"), legacy_anagrafica_id=7777,
                                                 stato_scadenza="MAI_FREQUENTATO", is_required=True)

        esito = scadenze.ricalcola_formazione()

        righe = {(d.legacy_anagrafica_id, d.corso.codice): d for d in TrainingDeadline.objects.select_related("corso")}
        self.assertEqual(set(righe), {(901, "SALD")})
        riga = righe[(901, "SALD")]
        self.assertEqual(riga.stato_scadenza, "SCADUTO")
        self.assertTrue(riga.is_required)
        self.assertIn("Saldatore", " ".join(riga.reason_snapshot["origini"]))
        self.assertEqual(esito["cancellate"], 3)
        for r in (vecchia, cessato, orfana):
            self.assertFalse(TrainingDeadline.objects.filter(pk=r.pk).exists())

    def test_ricalcolo_idempotente_e_per_persona(self):
        corso = self.corso("ANT")
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        scadenze.ricalcola_formazione()
        secondo = scadenze.ricalcola_formazione()
        self.assertEqual((secondo["create"], secondo["aggiornate"], secondo["cancellate"]), (0, 0, 0))
        self.assertEqual(refresh_deadlines(legacy_id=902), 1)
        self.assertEqual(TrainingDeadline.objects.get().stato_scadenza, "MAI_FREQUENTATO")

    def test_comando_anteprima_non_scrive(self):
        TrainingRequirementRule.objects.create(corso=self.corso("ANT"), legacy_anagrafica_id=902)
        out = StringIO()
        call_command("ricalcola_scadenze_hr", "--anteprima", stdout=out)
        self.assertIn("Anteprima", out.getvalue())
        self.assertFalse(TrainingDeadline.objects.exists())
        call_command("ricalcola_scadenze_hr", stdout=StringIO())
        self.assertTrue(TrainingDeadline.objects.exists())


class PianificazioneTest(TestCase):
    def test_ricalcolo_notturno_prima_dei_promemoria(self):
        from automazioni.schedules import SCHEDULES

        per_nome = {s["name"]: s for s in SCHEDULES}
        self.assertEqual(per_nome["anagrafica_ricalcolo_scadenze"]["func"], "anagrafica.tasks.run_ricalcolo_scadenze")
        self.assertEqual(per_nome["anagrafica_ricalcolo_scadenze"]["cron"], "20 0 * * *")
