"""Interventi dall'analisi formazione del 26/11/2026: efficacia senza tipo, tipo e validità in blocco,
qualifiche dai completamenti, un solo punto di uscita del completamento, completamenti con data futura,
«completato» = completamento valido, Copertura sul motore dei requisiti, schede di copertura. Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models_formazione import (
    TrainingAssignment, TrainingCourse, TrainingCourseType, TrainingEmployeeRecord, TrainingEnrollment,
    TrainingPlan, TrainingSession,
)

PID = 7101


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.interventi", "hr@example.com", "pwd12345")
        UserOnboarding.objects.get_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PIN", nome="Piano interventi")
        self.corso = TrainingCourse.objects.create(piano=self.piano, codice="AGG-1", titolo="Aggiornamento antincendio",
                                                   durata_ore_teorica=Decimal("4"), stato="ATTIVO")
        oggi = timezone.localdate()
        self.s = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-IN-1", modalita="IN_SEDE",
                                                data_inizio=oggi - timedelta(days=2), data_fine=oggi - timedelta(days=1))

    def _record_aula(self, pid=PID, giorni_fa=1):
        from .views import _crea_employee_record
        e = TrainingEnrollment.objects.create(sessione=self.s, legacy_anagrafica_id=pid, ore_frequentate=4, idoneo=True,
                                              stato="COMPLETATO",
                                              data_completamento=timezone.localdate() - timedelta(days=giorni_fa))
        return _crea_employee_record(e, self.admin)


class EfficaciaSenzaTipoTests(_Base):
    def test_predefinito_tre_mesi_e_tipo_che_vince(self):
        from .services.formazione_efficacia import mesi_efficacia_richiesti
        rec = self._record_aula()
        self.assertEqual(mesi_efficacia_richiesti(self.corso, rec), 3)
        self.corso.tipo = TrainingCourseType.objects.create(nome="Sicurezza prova", efficacia_mesi=6)
        self.corso.save()
        self.assertEqual(mesi_efficacia_richiesti(self.corso, rec), 6)

    def test_valore_modificabile_dai_tipi_di_corso(self):
        from .models_formazione import AttestatoFormazioneConfig
        self.client.post(reverse("anagrafica:formazione_tipi_corso_azione"),
                         {"azione": "efficacia_senza_tipo", "efficacia_mesi": "0"})
        self.assertEqual(AttestatoFormazioneConfig.get_instance().efficacia_mesi_senza_tipo, 0)


class CorsiInBloccoTests(_Base):
    def test_tipo_e_validita_con_scadenze_mancanti(self):
        rec = self._record_aula(giorni_fa=10)
        self.assertIsNone(rec.data_scadenza)
        tipo = TrainingCourseType.objects.create(nome="Antincendio prova")
        url = reverse("anagrafica:formazione_corsi_azione")
        self.client.post(url, {"azione": "tipo", "tipo_id": tipo.pk, "corso_id": [self.corso.pk]})
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.tipo_id, tipo.pk)
        self.client.post(url, {"azione": "validita", "validita_mesi": "60", "riempi": "1", "corso_id": [self.corso.pk]})
        self.corso.refresh_from_db()
        rec.refresh_from_db()
        self.assertEqual(self.corso.validita_mesi, 60)
        self.assertIsNotNone(rec.data_scadenza)
        self.assertGreater(rec.data_scadenza, rec.data_completamento + timedelta(days=1700))

    def test_scadenze_scritte_non_cambiano(self):
        rec = self._record_aula()
        TrainingEmployeeRecord.objects.filter(pk=rec.pk).update(data_scadenza=date(2030, 1, 1))
        self.client.post(reverse("anagrafica:formazione_corsi_azione"),
                         {"azione": "validita", "validita_mesi": "12", "riempi": "1", "corso_id": [self.corso.pk]})
        rec.refresh_from_db()
        self.assertEqual(rec.data_scadenza, date(2030, 1, 1))

    def test_una_tantum_da_rivedere(self):
        from .services.formazione_catalogo import ids_una_tantum_da_rivedere
        altro = TrainingCourse.objects.create(piano=self.piano, codice="X-1", titolo="Benvenuto in azienda", durata_ore_teorica=Decimal("1"),
                                              stato="ATTIVO")
        ids = ids_una_tantum_da_rivedere()
        self.assertIn(self.corso.pk, ids)
        self.assertNotIn(altro.pk, ids)
        r = self.client.get(reverse("anagrafica:formazione_corsi_list") + "?rinnovo=1")
        self.assertContains(r, "Aggiornamento antincendio")
        self.assertNotContains(r, "Benvenuto in azienda")


class QualificheDaiCorsiTests(_Base):
    def test_allinea(self):
        from .models import DipendenteQualifica, TipoQualifica
        from .services.formazione_qualifiche import da_allineare
        rec = self._record_aula()
        q = TipoQualifica.objects.create(nome="Addetto antincendio prova")
        self.corso.qualifica = q
        self.corso.save()
        self.assertEqual([r.pk for r in da_allineare()], [rec.pk])
        self.client.post(reverse("anagrafica:qualifiche_allinea"))
        dq = DipendenteQualifica.objects.get(legacy_anagrafica_id=PID, tipo=q)
        self.assertEqual((dq.data_conseguimento, dq.record_formazione_id), (rec.data_completamento, rec.pk))
        self.assertEqual(da_allineare(), [])


class UnCorsoUnCompletamentoTests(_Base):
    def test_aula_chiude_assegnazioni_e_sessione_online_dello_stesso_corso(self):
        a = TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, stato="ASSEGNATO")
        on = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-ON-X", modalita="ONLINE",
                                            data_inizio=timezone.localdate(),
                                            data_fine=timezone.localdate() + timedelta(days=20))
        e_on = TrainingEnrollment.objects.create(sessione=on, legacy_anagrafica_id=PID, stato="ISCRITTO")
        self._record_aula()
        a.refresh_from_db()
        e_on.refresh_from_db()
        self.assertEqual((a.stato, e_on.stato), ("COMPLETATO", "COMPLETATO"))
        self.assertEqual(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=PID).count(), 1)

    def test_link_aperto_riusa_il_completamento_di_aula_e_non_lo_annulla(self):
        from core.legacy_models import AnagraficaDipendente

        from .models_elearning import TrainingElearningRispostaAperta as R
        from .services import elearning_link_aperto as la
        dip = AnagraficaDipendente.objects.create(nome="Anna", cognome="Prova Sintetica")
        rec = self._record_aula(pid=dip.id)
        self.corso.is_elearning = True
        self.corso.save()
        esito = {"punteggio_pct": Decimal("100"), "n_corrette": 1, "n_totali": 1, "superato": True, "risposte": []}
        risposta = la.registra(self.corso, nome="Anna", cognome="Prova Sintetica", esito=esito, avviato_il=None,
                               ip="", user_agent="")
        self.assertEqual(risposta.record_id, rec.pk)
        self.assertEqual(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=dip.id).count(), 1)
        altro = AnagraficaDipendente.objects.create(nome="Bruno", cognome="Altro Sintetico")
        la.abbina(risposta, altro.id, user=self.admin)  # correzione HR
        rec.refresh_from_db()
        self.assertFalse(rec.is_annullato)
        self.assertEqual(R.objects.get(pk=risposta.pk).legacy_anagrafica_id, altro.id)

    def test_assegnabili_vede_chi_ha_fatto_il_corso_in_aula(self):
        from .services import elearning_corso_gestione as g
        from .services.formazione_completamento import ids_con_completamento_valido
        self._record_aula()
        self.assertEqual(ids_con_completamento_valido(self.corso, [PID, PID + 1]), {PID})
        self.assertTrue(hasattr(g, "persone_assegnabili"))


class CompletamentiFuturiTests(_Base):
    def _futuro(self, sessione=None, giorni=40):
        return TrainingEmployeeRecord.objects.create(
            corso=self.corso, sessione=sessione, legacy_anagrafica_id=PID,
            data_completamento=timezone.localdate() + timedelta(days=giorni), validity_months_snapshot=12,
            course_code_snapshot="AGG-1")

    def test_porta_alla_data_reale(self):
        r = self._futuro(sessione=self.s)
        self.client.post(reverse("anagrafica:formazione_integrita"), {"azione": "futuri_data", "record_id": [r.pk]})
        r.refresh_from_db()
        self.assertEqual(r.data_completamento, self.s.data_fine)
        self.assertIsNotNone(r.data_scadenza)
        self.assertIn("era nel futuro", r.note)

    def test_senza_edizione_si_annulla_con_motivo(self):
        r = self._futuro()
        self.client.post(reverse("anagrafica:formazione_integrita"), {"azione": "futuri_data", "record_id": [r.pk]})
        r.refresh_from_db()
        self.assertGreater(r.data_completamento, timezone.localdate())
        self.client.post(reverse("anagrafica:formazione_integrita"),
                         {"azione": "futuri_annulla", "record_id": [r.pk], "motivo": "Data dell'import sbagliata"})
        self.assertTrue(TrainingEmployeeRecord.tutti.get(pk=r.pk).is_annullato)

    def test_pagina_elenca_i_futuri(self):
        self._futuro(sessione=self.s)
        r = self.client.get(reverse("anagrafica:formazione_integrita"))
        self.assertContains(r, "Completamenti con data futura")
        self.assertContains(r, "Porta alla data reale")


class SoglieESchedeTests(_Base):
    def test_soglie_uniche(self):
        from .scadenze_soglie import GIORNI_PREAVVISO, GIORNI_URGENTE
        from .services.training_deadline_service import _compute_stato
        oggi = timezone.localdate()
        self.assertEqual(_compute_stato(oggi + timedelta(days=GIORNI_URGENTE), 0, oggi)[0], "IN_SCADENZA_30")
        self.assertEqual(_compute_stato(oggi + timedelta(days=GIORNI_PREAVVISO), 0, oggi)[0], "IN_SCADENZA_90")

    def test_schede_copertura_sulle_pagine(self):
        r = self.client.get(reverse("anagrafica:formazione_copertura"))
        self.assertContains(r, "Copertura e lacune")
        self.assertContains(r, reverse("anagrafica:mansionario_lacune"))
