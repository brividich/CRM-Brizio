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
from anagrafica.services import integrita_scadenze, requisiti, scadenze
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
        conta = {"n": 0}
        vero = scadenze.ricalcola_tutto

        def contato(*a, **k):
            conta["n"] += 1
            return vero(*a, **k)

        with patch.object(scadenze, "ricalcola_tutto", side_effect=contato):
            with self.captureOnCommitCallbacks(execute=True):
                v = VisitaMedica.objects.create(legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=fatta)
                VisitaMedica.objects.create(legacy_anagrafica_id=901, tipo=self.annuale, data_svolgimento=fatta)
        self.assertEqual(conta["n"], 1)  # un solo ricalcolo per transazione
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

        sezioni = {s.titolo: s.righe for s in integrita_scadenze.verifica(["visite"])}
        self.assertTrue(any(f"tipo #{sbagliato.pk}" in r for r in sezioni["Tipi con durata diversa dalla cadenza nel nome"]))
        self.assertTrue(any(f"visita #{v.pk}" in r for r in sezioni["Visite correnti con scadenza diversa dal motore"]))
        self.assertTrue(any(f"visita #{rotta.pk}" in r for r in sezioni["Visite che scadono prima di essere fatte"]))
        out = StringIO()
        with self.assertRaises(SystemExit):  # errori → codice di uscita 1
            call_command("verifica_scadenze_visite", stdout=out)
        self.assertIn("Anomalie da correggere", out.getvalue())
        v.refresh_from_db()
        self.assertEqual(v.data_scadenza, _add_months(fatta, 24))  # non scrive

        scadenze.ricalcola_visite()
        VisitaMedica.objects.filter(pk=rotta.pk).update(data_scadenza=_add_months(fatta, 12))
        sbagliato.delete()
        out = StringIO()
        call_command("verifica_scadenze_visite", stdout=out)
        self.assertIn("Nessun errore", out.getvalue())
        anticipate = out.getvalue().split("anticipate dal requisito")[1]
        self.assertIn(f"visita #{v.pk}", anticipate)
        self.assertIn("Ruolo «Saldatore» richiede", anticipate)  # la nota dice da dove viene l'obbligo

    def test_esami_con_piu_cadenze_senza_famiglia(self):
        a = TipoVisitaMedica.objects.create(nome="Spirometria basale annuale", durata_mesi=12)
        b = TipoVisitaMedica.objects.create(nome="Spirometria basale biennale", durata_mesi=24)
        sezioni = {s.titolo: s.righe for s in integrita_scadenze.verifica(["visite"])}
        righe = sezioni["Esami con piu' cadenze senza famiglia (categoria)"]
        self.assertEqual(len(righe), 1)
        self.assertIn(f"#{a.pk}", righe[0])
        self.assertIn(f"#{b.pk}", righe[0])

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

    def test_attestato_con_scadenza_su_corso_una_tantum_scade(self):
        # Caso prod: corso portato a validita' 0 dopo aver emesso attestati quinquennali.
        corso = self.corso("ASR", validita=0)
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=2000),
                                              data_scadenza=OGGI - timedelta(days=170))
        scadenze.ricalcola_formazione()
        self.assertEqual(TrainingDeadline.objects.get().stato_scadenza, "SCADUTO")
        sezioni = {s.titolo: s.righe for s in integrita_scadenze.verifica(["formazione"])}
        self.assertIn("1 gia' scaduti", sezioni["Corsi «una tantum» con attestati che scadono"][0])

    def test_completamento_futuro_non_copre_quello_vero(self):
        corso = self.corso("PART")
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=400),
                                              data_scadenza=OGGI - timedelta(days=35))
        futuro = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                       data_completamento=OGGI + timedelta(days=900))
        scadenze.ricalcola_formazione()
        riga = TrainingDeadline.objects.get()
        self.assertEqual(riga.stato_scadenza, "SCADUTO")
        self.assertEqual(riga.data_ultimo_completamento, OGGI - timedelta(days=400))
        sezioni = {s.titolo: s.righe for s in integrita_scadenze.verifica(["formazione"])}
        self.assertTrue(any(f"#{futuro.pk}" in r for r in sezioni["Completamenti con data nel futuro"]))

    def test_doppioni_e_scadenzario_vecchio(self):
        corso = self.corso("DUP")
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        fatto = OGGI - timedelta(days=100)
        for _ in range(2):
            TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                  data_completamento=fatto, data_scadenza=_add_months(fatto, 12))
        scadenze.ricalcola_formazione()
        TrainingDeadline.objects.update(stato_scadenza="SCADUTO")  # cache rimasta indietro
        sezioni = {s.titolo: s.righe for s in integrita_scadenze.verifica(["formazione"], legacy_ids=[902])}
        self.assertEqual(len(sezioni["Attestati doppi (persona, corso, data)"]), 1)
        self.assertEqual(len(sezioni["Scadenzario formazione non aggiornato"]), 1)


class PuliziaTest(_Base):
    def test_doppioni_anteprima_poi_applica(self):
        from core.models import AuditLog

        corso = self.corso("DUP")
        fatto = OGGI - timedelta(days=100)
        tenuto = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                       data_completamento=fatto, numero_protocollo="ATT-1")
        copia = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                      data_completamento=fatto)
        out = StringIO()
        call_command("pulisci_scadenze_hr", "--doppioni", stdout=out)
        self.assertIn(f"elimina persona 902 corso DUP", out.getvalue())
        self.assertEqual(TrainingEmployeeRecord.objects.count(), 2)  # anteprima

        call_command("pulisci_scadenze_hr", "--doppioni", "--applica", stdout=StringIO())
        self.assertEqual(list(TrainingEmployeeRecord.objects.values_list("pk", flat=True)), [tenuto.pk])
        self.assertTrue(AuditLog.objects.filter(azione="formazione_attestato_doppio_eliminato",
                                                oggetto_id=str(copia.pk)).exists())

    def test_doppione_collegato_resta_a_mano(self):
        corso = self.corso("DUP2")
        fatto = OGGI - timedelta(days=100)
        for protocollo in ("ATT-1", "ATT-2"):
            TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                  data_completamento=fatto, numero_protocollo=protocollo)
        out = StringIO()
        call_command("pulisci_scadenze_hr", "--doppioni", "--applica", stdout=out)
        self.assertIn("da vedere a mano", out.getvalue())
        self.assertEqual(TrainingEmployeeRecord.objects.count(), 2)

    def test_scadenze_mancanti_completate(self):
        corso = self.corso("ASR2", validita=60)
        fatto = OGGI - timedelta(days=200)
        r = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                                  data_completamento=fatto)  # emesso quando era una tantum
        call_command("pulisci_scadenze_hr", "--scadenze-mancanti", stdout=StringIO())
        r.refresh_from_db()
        self.assertIsNone(r.data_scadenza)  # anteprima
        call_command("pulisci_scadenze_hr", "--scadenze-mancanti", "--applica", stdout=StringIO())
        r.refresh_from_db()
        self.assertEqual(r.data_scadenza, _add_months(fatto, 60))

    def test_validita_corso_allineata(self):
        corso = self.corso("ASR", validita=0)
        TrainingRequirementRule.objects.create(corso=corso, legacy_anagrafica_id=902)
        fatto = OGGI - timedelta(days=2000)
        TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=902, idoneo=True,
                                              data_completamento=fatto, data_scadenza=_add_months(fatto, 60))
        call_command("pulisci_scadenze_hr", "--validita-corsi", stdout=StringIO())
        corso.refresh_from_db()
        self.assertEqual(corso.validita_mesi, 0)  # anteprima
        call_command("pulisci_scadenze_hr", "--validita-corsi", "--applica", stdout=StringIO())
        corso.refresh_from_db()
        self.assertEqual(corso.validita_mesi, 60)
        self.assertEqual(TrainingDeadline.objects.get().stato_scadenza, "SCADUTO")


class IntegritaDpiQualificheTest(_Base):
    def test_dpi_e_qualifiche(self):
        from anagrafica.models import DipendenteQualifica, TipoQualifica
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI

        cat = CategoriaDPI.objects.create(nome="Guanti", vita_utile_giorni=180)
        r = RichiestaDPI.objects.create(categoria=cat, richiedente_legacy_id=902, richiedente_nome="X",
                                        stato="CONSEGNATA")
        c = ConsegnaDPI.objects.create(richiesta=r, data_consegna=OGGI,
                                       data_scadenza_stimata=OGGI - timedelta(days=1))
        tipo = TipoQualifica.objects.create(nome="Patentino", durata_mesi=60)
        q = DipendenteQualifica.objects.create(legacy_anagrafica_id=902, tipo=tipo,
                                               data_conseguimento=OGGI - timedelta(days=10))
        sezioni = {(s.area, s.titolo): s.righe for s in integrita_scadenze.verifica(["dpi", "qualifiche"])}
        self.assertTrue(any(f"#{c.pk}" in x for x in sezioni[("dpi", "Consegne che scadono prima della consegna")]))
        self.assertTrue(any(f"#{q.pk}" in x for x in
                            sezioni[("qualifiche", "Qualifiche senza scadenza con tipo a durata")]))


class PianificazioneTest(TestCase):
    def test_ricalcolo_notturno_prima_dei_promemoria(self):
        from automazioni.schedules import SCHEDULES

        per_nome = {s["name"]: s for s in SCHEDULES}
        self.assertEqual(per_nome["anagrafica_ricalcolo_scadenze"]["func"], "anagrafica.tasks.run_ricalcolo_scadenze")
        self.assertEqual(per_nome["anagrafica_ricalcolo_scadenze"]["cron"], "20 0 * * *")
