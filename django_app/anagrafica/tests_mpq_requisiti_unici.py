"""MOD.128: un solo elenco dei requisiti per persona e un solo calcolo.

- i corsi/visite/DPI «uguali per tutti» del processo diventano requisiti persona (0225);
- qualifica del catalogo e DPI si leggono dai loro moduli;
- la frequenza del processo arriva nello scadenzario della Formazione (stessa data);
- «Sposta» porta un requisito per persona fuori dai requisiti del processo;
- collegamenti di ritorno su corso e qualifica.
Solo dati sintetici.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AbilitazioneProcesso,
    ClienteQualificante,
    DipendenteQualifica,
    ProcessoQualificato,
    RequisitoQualifica,
    TipoQualifica,
    TipoVisitaMedica,
    TrainingCourse,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingPlan,
)
from .models_mpq import RequisitoPersona, RuoloProcesso
from .services.mpq_persone import processi_che_richiedono, stato_persona


def _proc(nome="Processo U"):
    cli = ClienteQualificante.objects.create(nome=f"Cli {nome}")
    return ProcessoQualificato.objects.create(nome=nome, cliente=cli)


def _corso(codice="U1", validita=24):
    plan = TrainingPlan.objects.create(codice=f"PL-{codice}", nome="Piano")
    return TrainingCourse.objects.create(piano=plan, codice=codice, titolo=f"Corso {codice}",
                                         durata_ore_teorica=1, validita_mesi=validita)


class MigrazioneTests(TestCase):
    def test_m2m_diventano_requisiti_persona(self):
        from dpi.models import CategoriaDPI

        mig = importlib.import_module("anagrafica.migrations.0225_mpq_requisiti_persona_unici")
        p = _proc()
        c = _corso()
        t = TipoVisitaMedica.objects.create(nome="Visita U", durata_mesi=12)
        cat = CategoriaDPI.objects.create(nome="Guanti U")
        p.corsi_richiesti.add(c)
        p.visite_richieste.add(t)
        p.dpi_richiesti.add(cat)
        mig._avanti(apps, None)
        mig._avanti(apps, None)  # rilanciata non duplica
        reqs = RequisitoPersona.objects.filter(processo=p)
        self.assertEqual(reqs.count(), 3)
        self.assertEqual({r.tipo for r in reqs}, {"corso", "visita", "dpi"})
        self.assertTrue(all(r.bloccante and not r.frequenza_mesi for r in reqs))
        self.assertEqual(p.corsi_richiesti.count() + p.visite_richieste.count() + p.dpi_richiesti.count(), 0)
        mig._indietro(apps, None)
        self.assertEqual(RequisitoPersona.objects.filter(processo=p).count(), 0)
        self.assertEqual(p.corsi_richiesti.count(), 1)


class FonteUnicaTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.p = _proc()
        self.ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4101, processo=self.p,
                                                      stato=AbilitazioneProcesso.STATO_ATTIVA)

    def test_qualifica_del_catalogo_letta_dalla_scheda(self):
        tq = TipoQualifica.objects.create(nome="Livello 2 sintetico", durata_mesi=60)
        RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_QUALIFICA, tipo_qualifica=tq)
        self.assertEqual(stato_persona(self.ab)["esito"], "incompleto")
        # Vale quella conseguita per ultima: la vecchia scaduta non conta.
        DipendenteQualifica.objects.create(legacy_anagrafica_id=4101, tipo=tq, data_conseguimento=date(2015, 1, 1),
                                           data_scadenza=date(2020, 1, 1))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=4101, tipo=tq,
                                           data_conseguimento=self.oggi - timedelta(days=10),
                                           data_scadenza=self.oggi + timedelta(days=400))
        st = stato_persona(self.ab)
        self.assertEqual(st["esito"], "ok")
        self.assertEqual(st["scadenza"], self.oggi + timedelta(days=400))
        self.assertEqual(processi_che_richiedono(tipo_qualifica=tq)[0]["processo"], self.p)

    def test_dpi_consegnato(self):
        from dpi.models import CategoriaDPI

        cat = CategoriaDPI.objects.create(nome="Occhiali U")
        RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_DPI, categoria_dpi=cat)
        st = stato_persona(self.ab)
        self.assertEqual(st["esito"], "incompleto")
        self.assertEqual(st["voci"][0]["nome"], "Occhiali U")

    def test_requisito_per_ruolo_non_vale_per_gli_altri(self):
        ruolo = RuoloProcesso.objects.create(processo=self.p, nome="Ispettore")
        r = RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_TEST_VISIVO,
                                            descrizione="Test visivo", ricorrenza="RICORRENTE", frequenza_mesi=12)
        r.ruoli.add(ruolo)
        self.assertEqual(stato_persona(self.ab)["esito"], "nessuno")
        self.ab.ruoli_processo.add(ruolo)
        self.assertEqual(stato_persona(self.ab)["esito"], "incompleto")


class FrequenzaInFormazioneTests(TestCase):
    """Processo «ogni 12 mesi» su un corso da 24: Formazione e processo dicono la stessa scadenza."""

    def test_stessa_scadenza_nei_due_posti(self):
        from core.legacy_models import AnagraficaDipendente

        from .models import _add_months
        from .services.training_deadline_service import refresh_deadlines

        oggi = timezone.localdate()
        dip = AnagraficaDipendente.objects.create(nome="Prova", cognome="Freq", aliasusername="prova.freq.mpq")
        c = _corso("UF", validita=24)
        p = _proc("Processo F")
        RequisitoPersona.objects.create(processo=p, tipo=RequisitoPersona.TIPO_CORSO, corso=c,
                                        ricorrenza="RICORRENTE", frequenza_mesi=12)
        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=dip.id, processo=p,
                                                 stato=AbilitazioneProcesso.STATO_ATTIVA)
        fatto = oggi - timedelta(days=400)
        TrainingEmployeeRecord.objects.create(legacy_anagrafica_id=dip.id, corso=c, data_completamento=fatto,
                                              data_scadenza=_add_months(fatto, 24), idoneo=True)
        refresh_deadlines(legacy_id=dip.id)
        d = TrainingDeadline.objects.get(legacy_anagrafica_id=dip.id, corso=c)
        self.assertEqual(d.data_scadenza, _add_months(fatto, 12))
        self.assertEqual(d.stato_scadenza, "SCADUTO")
        st = stato_persona(ab)
        self.assertEqual(st["scadenza"], d.data_scadenza)
        self.assertEqual(st["esito"], "ko")


class PagineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("mpq.unici", "mpq.unici@example.com", "x")
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.p = _proc("Processo P")

    def test_sposta_requisito_per_persona(self):
        req = RequisitoQualifica.objects.create(processo=self.p, tipo=RequisitoQualifica.TIPO_VISIONE,
                                                descrizione="Test visivo annuale", periodicita_mesi=12)
        r = self.client.post(reverse("anagrafica:mpq_requisito_sposta", args=[req.pk]))
        nuovo = RequisitoPersona.objects.get(processo=self.p)
        self.assertRedirects(r, reverse("anagrafica:mpq_requisito_persona_edit", args=[nuovo.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(nuovo.tipo, RequisitoPersona.TIPO_TEST_VISIVO)
        self.assertEqual(nuovo.frequenza_mesi, 12)
        self.assertFalse(RequisitoQualifica.objects.filter(pk=req.pk).exists())

    def test_contratto_non_si_sposta(self):
        req = RequisitoQualifica.objects.create(processo=self.p, tipo=RequisitoQualifica.TIPO_CONTRATTO,
                                                descrizione="Contratto quadro")
        self.client.post(reverse("anagrafica:mpq_requisito_sposta", args=[req.pk]))
        self.assertTrue(RequisitoQualifica.objects.filter(pk=req.pk).exists())

    def test_form_requisito_processo_senza_tipi_per_persona(self):
        from .forms_mpq import RequisitoQualificaForm

        tipi = {k for k, _v in RequisitoQualificaForm().fields["tipo"].choices}
        self.assertNotIn(RequisitoQualifica.TIPO_ESAME, tipi)
        self.assertIn(RequisitoQualifica.TIPO_CONTRATTO, tipi)

    def test_dettaglio_e_schede_collegate(self):
        c = _corso("UP")
        RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_CORSO, corso=c)
        r = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.p.pk]))
        self.assertContains(r, "Requisiti del processo")
        self.assertContains(r, "Segue la sua scadenza")
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[c.pk]))
        self.assertContains(r, "Richiesto dai processi qualificati")
        self.assertContains(r, "Processo P")


class AlternativeTests(TestCase):
    """«Livello 2 UT» oppure «Livello 3 UT»: basta una delle righe con lo stesso gruppo."""

    def setUp(self):
        self.oggi = timezone.localdate()
        self.p = _proc("Processo A")
        self.ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4201, processo=self.p,
                                                      stato=AbilitazioneProcesso.STATO_ATTIVA)
        self.l2 = TipoQualifica.objects.create(nome="L2 sintetico", durata_mesi=60)
        self.l3 = TipoQualifica.objects.create(nome="L3 sintetico", durata_mesi=60)
        for tq in (self.l2, self.l3):
            RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_QUALIFICA,
                                            tipo_qualifica=tq, gruppo_alternativo="UT")

    def test_nessuna_alternativa_incompleta(self):
        st = stato_persona(self.ab)
        self.assertEqual(st["esito"], "incompleto")
        self.assertEqual(st["n_mancanti"], 1)  # il gruppo conta una volta

    def test_basta_una(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=4201, tipo=self.l3,
                                           data_conseguimento=self.oggi - timedelta(days=5),
                                           data_scadenza=self.oggi + timedelta(days=500))
        st = stato_persona(self.ab)
        self.assertEqual(st["esito"], "ok")
        self.assertEqual(st["scadenza"], self.oggi + timedelta(days=500))
        scartate = [v for v in st["voci"] if v.get("alternativa_scartata")]
        self.assertEqual([v["nome"] for v in scartate], ["L2 sintetico"])

    def test_alternative_non_diventano_obblighi(self):
        from .services.mpq_formazione import legacy_ids_richiesti_da_processo
        from .services.mpq_persone import obblighi_richiesti

        c = _corso("UA")
        RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_CORSO, corso=c,
                                        gruppo_alternativo="Base")
        self.assertEqual(obblighi_richiesti(self.ab)["corsi"], [])
        self.assertEqual(legacy_ids_richiesti_da_processo(c.pk), set())


class RuoliUniciTests(TestCase):
    """Qualificato/Addetto/Controllore/Part 145 sono ruoli del processo; i booleani ne sono la copia."""

    def setUp(self):
        self.p = _proc("Processo R")

    def test_imposta_ruoli_scrive_la_copia(self):
        from .services.mpq_ruoli import imposta_ruoli, nomi_ruoli, ruolo_standard

        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4301, processo=self.p)
        op = RuoloProcesso.objects.create(processo=self.p, nome="Operatore macchina")
        imposta_ruoli(ab, [ruolo_standard(self.p, "CONTROLLORE"), op])
        ab.refresh_from_db()
        self.assertTrue(ab.is_controllore)
        self.assertFalse(ab.is_qualificato)
        self.assertEqual(nomi_ruoli(ab), ["Controllore", "Operatore macchina"])

    def test_requisito_per_ruolo_standard(self):
        from .services.mpq_ruoli import imposta_ruoli, ruolo_standard

        ctrl = ruolo_standard(self.p, "CONTROLLORE")
        r = RequisitoPersona.objects.create(processo=self.p, tipo=RequisitoPersona.TIPO_ESAME,
                                            descrizione="Esame controllore")
        r.ruoli.add(ctrl)
        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4302, processo=self.p)
        imposta_ruoli(ab, [ruolo_standard(self.p, "QUALIFICATO")])
        self.assertEqual(stato_persona(ab)["esito"], "nessuno")
        imposta_ruoli(ab, [ctrl])
        self.assertEqual(stato_persona(ab)["esito"], "incompleto")

    def test_migrazione_crea_ruoli_dai_booleani(self):
        mig = importlib.import_module("anagrafica.migrations.0227_mpq_ruoli_unici")
        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4303, processo=self.p,
                                                 is_qualificato=True, is_part145=True)
        mig._avanti(apps, None)
        mig._avanti(apps, None)
        self.assertEqual(sorted(r.codice_modulo for r in ab.ruoli_processo.all()), ["PART145", "QUALIFICATO"])
        self.assertEqual(self.p.ruoli.count(), 2)

    def test_form_abilitazione_salva_ruoli(self):
        from core.models import UserOnboarding

        u = get_user_model().objects.create_superuser("mpq.ruoli", "mpq.ruoli@example.com", "x")
        UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True})
        self.client.force_login(u)
        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4304, processo=self.p)
        r = self.client.post(reverse("anagrafica:mpq_abilitazione_edit", args=[ab.pk]), {
            "tipo_persona": "interno", "dipendente": "4304", "stato": "ATTIVA",
            "ruoli_standard": ["ADDETTO", "PART145"],
        })
        self.assertEqual(r.status_code, 302)
        ab.refresh_from_db()
        self.assertTrue(ab.is_addetto and ab.is_part145)
        self.assertFalse(ab.is_qualificato)


class IscriviTuttiTests(TestCase):
    def test_pulsante_con_tutti_i_mancanti(self):
        from core.models import UserOnboarding

        u = get_user_model().objects.create_superuser("mpq.iscrivi", "mpq.iscrivi@example.com", "x")
        UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True})
        self.client.force_login(u)
        p = _proc("Processo I")
        c = _corso("UI")
        RequisitoPersona.objects.create(processo=p, tipo=RequisitoPersona.TIPO_CORSO, corso=c)
        for lid in (4401, 4402):
            AbilitazioneProcesso.objects.create(legacy_anagrafica_id=lid, processo=p,
                                                stato=AbilitazioneProcesso.STATO_ATTIVA)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4403, processo=p,
                                            stato=AbilitazioneProcesso.STATO_SOSPESA)
        r = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[p.pk]))
        self.assertContains(r, "Iscrivi tutti (2)")
        html = r.content.decode("utf-8")
        fine = html.index("Iscrivi tutti (2)")
        modulo = html[html.rindex("<form", 0, fine):fine]
        self.assertIn('value="4401"', modulo)
        self.assertIn('value="4402"', modulo)
        self.assertNotIn('value="4403"', modulo)


class MatriceTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        u = get_user_model().objects.create_superuser("mpq.matrice", "mpq.matrice@example.com", "x")
        UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True})
        self.client.force_login(u)
        self.p1 = _proc("Processo M1")
        self.p2 = _proc("Processo M2")
        RequisitoPersona.objects.create(processo=self.p2, tipo=RequisitoPersona.TIPO_ESAME, descrizione="Esame M2")
        for p in (self.p1, self.p2):
            AbilitazioneProcesso.objects.create(legacy_anagrafica_id=4501, processo=p,
                                                stato=AbilitazioneProcesso.STATO_ATTIVA)

    def test_pagina_e_stesso_calcolo(self):
        from .services.mpq_persone import matrice

        dati = matrice()
        riga = [r for r in dati["righe"] if r["legacy_id"] == 4501][0]
        self.assertTrue(riga["celle"][self.p1.pk]["operativa"])
        self.assertFalse(riga["celle"][self.p2.pk]["operativa"])
        r = self.client.get(reverse("anagrafica:mpq_matrice"))
        self.assertContains(r, "Processo M1")
        self.assertContains(r, "1 da sistemare")
        r = self.client.get(reverse("anagrafica:mpq_matrice") + "?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Processo M2", r.content.decode("utf-8"))

    def test_voce_di_menu(self):
        from .models import SubnavLinkAnagrafica

        mig = importlib.import_module("anagrafica.migrations.0228_subnav_mpq_matrice")
        mig.avanti(apps, None)
        sorella = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:mpq_cruscotto").first()
        if sorella is not None:
            self.assertTrue(SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:mpq_matrice").exists())
