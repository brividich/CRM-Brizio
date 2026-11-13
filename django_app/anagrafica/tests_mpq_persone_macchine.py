"""MOD.128 — persone qualificate e macchine qualificate (13/11/2026).

Scadenze indipendenti: processo, persona (requisiti per ruolo, una tantum o
ricorrenti) e macchina (verifica con misure, sospensioni da manutenzione).
Dati sintetici.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, WorkOrder
from core.models import UserOnboarding

from .models import TrainingCourse, TrainingDeadline, TrainingPlan
from .models_mpq import (
    AbilitazioneProcesso,
    ClienteQualificante,
    EvidenzaRequisitoPersona,
    ParametroVerificaMacchina,
    ProcessoQualificato,
    QualificaMacchina,
    RequisitoPersona,
    RuoloProcesso,
    VerificaMacchina,
)
from .services import mpq_macchine, mpq_persone

User = get_user_model()


def _admin(username="mpq.pm"):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.test",
                                    is_superuser=True, is_staff=True)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


class _Base(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        cli = ClienteQualificante.objects.create(nome="Cliente sintetico PM")
        self.proc = ProcessoQualificato.objects.create(
            nome="Foratura sintetica", cliente=cli, tipo_validita=ProcessoQualificato.VALIDITA_ILLIMITATA,
            frequenza_macchine_mesi=12)
        self.op = RuoloProcesso.objects.create(processo=self.proc, nome="Operatore macchina")
        self.ing = RuoloProcesso.objects.create(processo=self.proc, nome="Ingegneria")
        self.ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=901, processo=self.proc)
        self.ab.ruoli_processo.add(self.op)
        self.asset = Asset.objects.create(asset_tag="SYN-CN-1", name="Centro sintetico", reparto="CN")


class PersoneTests(_Base):
    def test_requisito_per_ruolo_e_tutti(self):
        solo_ing = RequisitoPersona.objects.create(processo=self.proc, tipo="esame", descrizione="Esame ingegneria")
        solo_ing.ruoli.add(self.ing)
        tutti = RequisitoPersona.objects.create(processo=self.proc, tipo="test_visivo", descrizione="Test visivo")
        reqs = mpq_persone.requisiti_per_abilitazione(self.ab)
        self.assertEqual(reqs, [tutti])

    def test_test_visivo_ricorrente_scade_a_fine_mese_indipendente_dal_processo(self):
        req = RequisitoPersona.objects.create(processo=self.proc, tipo="test_visivo", descrizione="Test visivo",
                                              frequenza_mesi=12, scadenza_fine_mese=True)
        st = mpq_persone.stato_persona(self.ab)
        self.assertEqual(st["esito"], "incompleto")
        self.assertFalse(st["operativa"])
        fatto = self.oggi.replace(day=1)
        EvidenzaRequisitoPersona.objects.create(abilitazione=self.ab, requisito=req, data_esecuzione=fatto)
        st = mpq_persone.stato_persona(self.ab)
        self.assertTrue(st["operativa"])
        attesa = req.scadenza_da(fatto)
        self.assertEqual(attesa.month, fatto.month)
        self.assertEqual(attesa.year, fatto.year + 1)
        self.assertEqual(st["scadenza"], attesa)
        self.assertIsNone(self.proc.scadenza_effettiva)  # il processo non scade

    def test_esito_negativo_non_qualifica(self):
        req = RequisitoPersona.objects.create(processo=self.proc, tipo="esame", descrizione="Esame",
                                              ricorrenza="UNA_TANTUM")
        EvidenzaRequisitoPersona.objects.create(abilitazione=self.ab, requisito=req, data_esecuzione=self.oggi,
                                                esito="NON_SUPERATO")
        self.assertEqual(mpq_persone.stato_persona(self.ab)["esito"], "ko")

    def test_ore_esperienza(self):
        req = RequisitoPersona.objects.create(processo=self.proc, tipo="esperienza", descrizione="Ore",
                                              ricorrenza="UNA_TANTUM", ore_minime=Decimal("40"))
        EvidenzaRequisitoPersona.objects.create(abilitazione=self.ab, requisito=req, data_esecuzione=self.oggi,
                                                ore=Decimal("30"))
        self.assertEqual(mpq_persone.stato_persona(self.ab)["esito"], "incompleto")
        EvidenzaRequisitoPersona.objects.create(abilitazione=self.ab, requisito=req, data_esecuzione=self.oggi,
                                                ore=Decimal("12"))
        self.assertEqual(mpq_persone.stato_persona(self.ab)["esito"], "ok")

    def test_corso_con_frequenza_del_processo(self):
        piano = TrainingPlan.objects.create(codice="PL-PM", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="P11", titolo="Consapevolezza", durata_ore_teorica=1)
        RequisitoPersona.objects.create(processo=self.proc, tipo="corso", corso=corso, frequenza_mesi=12)
        TrainingDeadline.objects.create(corso=corso, legacy_anagrafica_id=901,
                                        data_ultimo_completamento=self.oggi - timedelta(days=400),
                                        stato_scadenza="VALIDO")
        st = mpq_persone.stato_persona(self.ab)
        self.assertEqual(st["esito"], "ko")  # 400 giorni > 12 mesi del processo

    def test_corso_per_ruolo_diventa_obbligo_in_formazione(self):
        from .services.mpq_formazione import coppie_richieste_da_processo, legacy_ids_richiesti_da_processo

        piano = TrainingPlan.objects.create(codice="PL-PM2", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="P12", titolo="Corso ruolo", durata_ore_teorica=1)
        req = RequisitoPersona.objects.create(processo=self.proc, tipo="corso", corso=corso, frequenza_mesi=12)
        req.ruoli.add(self.op)
        altro = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=902, processo=self.proc)
        altro.ruoli_processo.add(self.ing)
        self.assertEqual(legacy_ids_richiesti_da_processo(corso.pk), {901})
        self.assertIn((901, corso), coppie_richieste_da_processo(corso_id=corso.pk))


class MacchineTests(_Base):
    def setUp(self):
        super().setUp()
        self.qm = mpq_macchine.collega(self.proc, self.asset)
        self.giri = ParametroVerificaMacchina.objects.create(processo=self.proc, nome="Giri mandrino",
                                                             tolleranza_pct=Decimal("10"))
        self.refr = ParametroVerificaMacchina.objects.create(processo=self.proc, nome="Blocco refrigerante",
                                                             tipo="PROVA")
        self.press = ParametroVerificaMacchina.objects.create(processo=self.proc, nome="Pressione", tipo="MINIMO",
                                                              valore_minimo=Decimal("4.1"), unita="bar")

    def test_collega_apre_qualifica_da_qualificare(self):
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_DA_QUALIFICARE)
        self.assertEqual(self.qm.frequenza_mesi, 12)
        self.assertTrue(self.asset.processi_qualificati.filter(pk=self.proc.pk).exists())
        self.assertFalse(self.qm.is_operativa())

    def test_valuta_misura(self):
        self.assertTrue(mpq_macchine.valuta_misura(self.giri, nominale="1000", misurato="1090")["conforme"])
        self.assertFalse(mpq_macchine.valuta_misura(self.giri, nominale="1000", misurato="1110")["conforme"])
        self.assertFalse(mpq_macchine.valuta_misura(self.press, misurato="4,0")["conforme"])
        self.assertTrue(mpq_macchine.valuta_misura(self.refr, conforme=True)["conforme"])

    def _righe(self, misurato="1050"):
        return [(self.giri, {"nominale": "1000", "misurato": misurato}),
                (self.refr, {"conforme": True}), (self.press, {"misurato": "5"})]

    def test_verifica_conforme_qualifica_per_12_mesi(self):
        ver = mpq_macchine.registra_verifica(self.qm, tipo="INIZIALE", data=self.oggi, righe=self._righe())
        self.qm.refresh_from_db()
        self.assertEqual(ver.esito, VerificaMacchina.ESITO_OK)
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_QUALIFICATA)
        self.assertEqual(self.qm.scadenza_effettiva.year, self.oggi.year + 1)
        self.assertTrue(self.qm.is_operativa())

    def test_verifica_non_conforme_sospende_e_indica_periodo(self):
        prima = self.oggi - timedelta(days=200)
        mpq_macchine.registra_verifica(self.qm, tipo="INIZIALE", data=prima, righe=self._righe())
        with self.captureOnCommitCallbacks(execute=True):
            ver = mpq_macchine.registra_verifica(self.qm, tipo="PERIODICA", data=self.oggi,
                                                 righe=self._righe("1200"))
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_SOSPESA)
        self.assertIn("Giri mandrino", self.qm.motivo_stato)
        self.assertEqual(mpq_macchine.periodo_da_riesaminare(ver), (prima, self.oggi))

    def test_odl_correttivo_chiuso_chiede_valutazione(self):
        mpq_macchine.registra_verifica(self.qm, tipo="INIZIALE", data=self.oggi, righe=self._righe())
        odl = WorkOrder.objects.create(asset=self.asset, title="Sostituzione cuscinetti mandrino",
                                       kind=WorkOrder.KIND_CORRECTIVE)
        self.assertEqual(mpq_macchine.qualifiche_toccate_da_odl(odl), [self.qm])
        with self.captureOnCommitCallbacks(execute=True):
            odl.status = WorkOrder.STATUS_DONE
            odl.closed_at = timezone.now()
            odl.save()
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_DA_VALUTARE)

    def test_odl_preventivo_non_tocca(self):
        mpq_macchine.registra_verifica(self.qm, tipo="INIZIALE", data=self.oggi, righe=self._righe())
        odl = WorkOrder.objects.create(asset=self.asset, title="Ingrassaggio", kind=WorkOrder.KIND_PREVENTIVE)
        with self.captureOnCommitCallbacks(execute=True):
            odl.status = WorkOrder.STATUS_DONE
            odl.save()
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_QUALIFICATA)

    def test_asset_dismesso_ritira_qualifica(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.asset.status = Asset.STATUS_RETIRED
            self.asset.save()
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_RITIRATA)

    def test_scollega_conserva_storico(self):
        mpq_macchine.scollega(self.proc, self.asset)
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_RITIRATA)
        self.assertFalse(self.asset.processi_qualificati.filter(pk=self.proc.pk).exists())
        mpq_macchine.collega(self.proc, self.asset)
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_DA_QUALIFICARE)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class VisteTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(_admin())
        self.qm = mpq_macchine.collega(self.proc, self.asset)
        ParametroVerificaMacchina.objects.create(processo=self.proc, nome="Giri mandrino",
                                                 tolleranza_pct=Decimal("10"))
        self.req = RequisitoPersona.objects.create(processo=self.proc, tipo="test_visivo",
                                                   descrizione="Test visivo", frequenza_mesi=12)

    def test_dettaglio_processo_mostra_persone_e_macchine(self):
        resp = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.proc.pk]))
        self.assertContains(resp, "Persone qualificate")
        self.assertContains(resp, "Macchine qualificate")
        self.assertContains(resp, "Cosa serve a una persona")
        self.assertContains(resp, "Registra verifica")
        self.assertContains(resp, reverse("anagrafica:mpq_evidenza_add", args=[self.ab.pk, self.req.pk]))

    def test_registra_evidenza(self):
        url = reverse("anagrafica:mpq_evidenza_add", args=[self.ab.pk, self.req.pk])
        resp = self.client.post(url, {"data_esecuzione": self.oggi.isoformat(), "esito": "SUPERATO"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(mpq_persone.stato_persona(self.ab)["operativa"])

    def test_verifica_da_pagina(self):
        par = self.proc.parametri_verifica.get()
        resp = self.client.post(reverse("anagrafica:mpq_verifica_add", args=[self.qm.pk]), {
            "tipo": "INIZIALE", "data": self.oggi.isoformat(),
            f"nom_{par.pk}": "1000", f"mis_{par.pk}": "1020",
        })
        self.assertEqual(resp.status_code, 302)
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_QUALIFICATA)
        scheda = self.client.get(reverse("anagrafica:mpq_qualifica_macchina", args=[self.qm.pk]))
        self.assertContains(scheda, "Conforme")

    def test_verifica_senza_misure_segnala_errore(self):
        resp = self.client.post(reverse("anagrafica:mpq_verifica_add", args=[self.qm.pk]),
                                {"tipo": "INIZIALE", "data": self.oggi.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "servono valore nominale e misurato")

    def test_valuta_non_incide(self):
        self.qm.stato = QualificaMacchina.STATO_DA_VALUTARE
        self.qm.data_qualifica = self.oggi
        self.qm.save()
        self.client.post(reverse("anagrafica:mpq_qualifica_macchina_stato", args=[self.qm.pk]),
                         {"azione": "non_incide"})
        self.qm.refresh_from_db()
        self.assertEqual(self.qm.stato, QualificaMacchina.STATO_QUALIFICATA)

    def test_elenco_e_scheda_asset(self):
        self.assertEqual(self.client.get(reverse("anagrafica:mpq_elenco", args=[self.proc.pk])).status_code, 200)
        scheda = self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))
        self.assertContains(scheda, reverse("anagrafica:mpq_qualifica_macchina", args=[self.qm.pk]))

    def test_ruoli_e_requisito_persona_da_form(self):
        self.client.post(reverse("anagrafica:mpq_ruolo_add", args=[self.proc.pk]), {"nome": "Presetting; CAR"})
        self.assertEqual(self.proc.ruoli.count(), 4)
        resp = self.client.post(reverse("anagrafica:mpq_requisito_persona_add", args=[self.proc.pk]), {
            "tipo": "esame", "descrizione": "Verifica annuale", "ricorrenza": "RICORRENTE",
            "frequenza_mesi": "12", "ruoli": [self.op.pk], "bloccante": "on", "attivo": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(RequisitoPersona.objects.filter(descrizione="Verifica annuale", ruoli=self.op).exists())


class ScadenzarioTests(_Base):
    def test_fonte_qualifiche_porta_persone_e_macchine(self):
        from types import SimpleNamespace

        from scadenzario.fonti_moduli import _persone_macchine_qualificate

        req = RequisitoPersona.objects.create(processo=self.proc, tipo="test_visivo", descrizione="Test visivo",
                                              frequenza_mesi=12)
        EvidenzaRequisitoPersona.objects.create(abilitazione=self.ab, requisito=req,
                                                data_esecuzione=self.oggi - timedelta(days=350))
        qm = mpq_macchine.collega(self.proc, self.asset)
        qm.stato = QualificaMacchina.STATO_SOSPESA
        qm.save()
        ctx = SimpleNamespace(sistema=True, oggi=self.oggi, orizzonte=self.oggi + timedelta(days=90))
        kinds = sorted(i.kind for i in _persone_macchine_qualificate(ctx))
        self.assertEqual(kinds, ["macchina_processo", "persona_processo"])


class MigrazioneDatiTests(TestCase):
    def test_fine_mese(self):
        from .models_mpq import _fine_mese

        self.assertEqual(_fine_mese(date(2027, 2, 3)), date(2027, 2, 28))
