"""Sessioni in aula: presenze in un tocco, firma e test dal telefono, chiusura, Da chiudere, efficacia."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_formazione import (
    TrainingCourse, TrainingCourseType, TrainingEfficacia, TrainingEmployeeRecord, TrainingEnrollment,
    TrainingLesson, TrainingLessonAttendance, TrainingPlan, TrainingSession,
)
from .services import formazione_aula as aula
from .services import sessione_online as so

A, B = 5101, 5102
NOMI = {A: "ROSSI MARIO", B: "BIANCHI LAURA"}
MATRICOLE = {A: {"T138"}, B: {"CNO77"}}


def _adesso(ora: time):
    return timezone.make_aware(datetime.combine(timezone.localdate(), ora))


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.aula", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.tipo = TrainingCourseType.objects.create(nome="Tecnico prova", efficacia_mesi=3)
        piano = TrainingPlan.objects.create(codice="PA", nome="Piano aula")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="AU-1", titolo="Corso in aula",
                                                   durata_ore_teorica=Decimal("2"), stato="ATTIVO", tipo=self.tipo)
        oggi = timezone.localdate()
        self.s = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-AU-1", modalita="IN_SEDE",
                                                data_inizio=oggi, data_fine=oggi, docente_nome="Docente Prova",
                                                stato="IN_CORSO")
        self.lz = TrainingLesson.objects.create(sessione=self.s, numero=1, data=oggi, ora_inizio=time(9),
                                                ora_fine=time(11), argomento="Giornata 1")
        self.ea = TrainingEnrollment.objects.create(sessione=self.s, legacy_anagrafica_id=A)
        self.eb = TrainingEnrollment.objects.create(sessione=self.s, legacy_anagrafica_id=B)
        p1 = mock.patch("anagrafica.views._helpers._build_nomi_map", return_value=NOMI)
        p2 = mock.patch("anagrafica.services.elearning_link_aperto.matricole_attive",
                        side_effect=lambda ids: {k: v for k, v in MATRICOLE.items() if k in ids})
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)


class PresenzeTests(_Base):
    def test_tutti_presenti_e_segna_parziale(self):
        r = self.client.post(reverse("anagrafica:formazione_presenze_tutti", args=[self.s.pk, self.lz.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TrainingLessonAttendance.objects.filter(lezione=self.lz, stato_presenza="PRESENTE").count(), 2)
        self.client.post(reverse("anagrafica:formazione_presenza_rapida", args=[self.s.pk, self.lz.pk]),
                         {"legacy_anagrafica_id": B, "stato": "PARZIALE", "ingresso": "10:00", "uscita": "11:00"})
        p = TrainingLessonAttendance.objects.get(lezione=self.lz, legacy_anagrafica_id=B)
        self.assertEqual((p.stato_presenza, p.ore_effettive), ("PARZIALE", Decimal("1.00")))
        self.eb.refresh_from_db()
        self.assertEqual(float(self.eb.percentuale_presenza), 50.0)

    def test_pagina_presenze_mostra_i_pulsanti(self):
        r = self.client.get(reverse("anagrafica:formazione_lezione_presenze", args=[self.s.pk, self.lz.pk]))
        self.assertContains(r, "Tutti presenti")
        self.assertContains(r, "Ritardo / uscita")


class TelefonoTests(_Base):
    def _url(self):
        return reverse("corso_aperto:aula", args=[aula.token(self.s)])

    def test_firma_ingresso_e_uscita(self):
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(8, 50))):
            r = self.client.post(self._url(), {"matricola": "t 138", "cognome": "Rossi"})
        self.assertContains(r, "Ingresso firmato alle 08:50")
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(9, 10))):
            r = self.client.post(self._url(), {})
        self.assertContains(r, "L&#x27;uscita si firma a fine lezione")
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(11, 5))):
            r = self.client.post(self._url(), {})
        self.assertContains(r, "Uscita firmata alle 11:05")
        p = TrainingLessonAttendance.objects.get(lezione=self.lz, legacy_anagrafica_id=A)
        self.assertEqual((p.ora_ingresso, p.ora_uscita, p.signature_method), (time(8, 50), time(11, 5), "DIGITALE"))
        self.assertEqual(p.ore_effettive, Decimal("2.00"))

    def test_fuori_orario_e_persona_sbagliata(self):
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(14, 0))):
            r = self.client.post(self._url(), {"matricola": "T138", "cognome": "Rossi"})
        self.assertContains(r, "non c&#x27;è una lezione aperta")
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(9, 0))):
            r = self.client.post(self._url(), {"matricola": "T138", "cognome": "Bianchi"})
        self.assertContains(r, "non corrispondono")
        self.assertFalse(TrainingLessonAttendance.objects.exists())

    def test_token_sconosciuto(self):
        self.assertEqual(self.client.get(reverse("corso_aperto:aula", args=["x" * 32])).status_code, 404)

    def test_test_in_aula_dal_telefono(self):
        so.salva_domanda(self.s, testo="2+2?", risposte=["4", "5"], giuste={0})
        aula.apri_chiudi_test(self.s, True)
        with mock.patch("django.utils.timezone.now", return_value=_adesso(time(9, 0))):
            self.client.post(self._url(), {"matricola": "T138", "cognome": "Rossi"})
        url = reverse("corso_aperto:aula_test", args=[self.s.token_aula])
        d = so.domande_valide(self.s)[0]
        giusta = d.opzioni.get(corretta=True)
        r = self.client.post(url, {f"q_{d.pk}": giusta.pk})
        self.assertContains(r, "Test superato")
        self.ea.refresh_from_db()
        self.assertTrue(self.ea.verifica_superata)
        self.assertIsNone(self.ea.idoneo)  # in aula l'esito si decide alla chiusura, la presenza viene dal registro


class ChiusuraTests(_Base):
    def test_proposta_e_chiusura_con_efficacia(self):
        aula.tutti_presenti(self.lz, self.admin)
        aula.segna(self.lz, self.eb, "ASSENTE_INGIUST", self.admin)
        righe = {r.enrollment.legacy_anagrafica_id: r for r in aula.proposta(self.s)}
        self.assertEqual((righe[A].proposto, righe[B].proposto), ("COMPLETATO", "ASSENTE"))
        r = self.client.post(reverse("anagrafica:formazione_aula_chiudi", args=[self.s.pk]),
                             {f"esito_{self.ea.pk}": "COMPLETATO", f"esito_{self.eb.pk}": "ASSENTE"})
        self.assertEqual(r.status_code, 302)
        self.s.refresh_from_db()
        self.assertEqual(self.s.stato, "COMPLETATA")
        self.assertIsNotNone(self.s.chiusa_il)
        rec = TrainingEmployeeRecord.objects.get(legacy_anagrafica_id=A)
        eff = TrainingEfficacia.objects.get(record=rec)
        self.assertEqual(eff.attesa_dal.month, (rec.data_completamento.month + 2) % 12 + 1)
        self.assertIn(self.s, list(aula.edizioni_da_approvare()))

    def test_test_su_carta_e_da_decidere(self):
        aula.tutti_presenti(self.lz, self.admin)
        out = aula.chiudi(self.s, self.admin, {self.ea.pk: "COMPLETATO"}, {self.eb.pk: "40"})
        self.assertFalse(out.chiusa)
        self.eb.refresh_from_db()
        self.assertFalse(self.eb.verifica_superata)
        self.assertEqual(aula.proposta(self.s)[1].proposto, "NON_IDONEO")
        self.assertContains(self.client.get(reverse("anagrafica:formazione_aula_chiudi", args=[self.s.pk])), "Chiudi l'edizione")

    def test_da_chiudere_in_blocco(self):
        ieri = timezone.localdate() - timedelta(days=5)
        vuota = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-VUOTA", modalita="IN_SEDE",
                                               data_inizio=ieri, data_fine=ieri)
        self.assertIn(vuota, list(aula.da_chiudere()))
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?da_chiudere=1")
        self.assertContains(r, "S-VUOTA")
        self.assertContains(r, "nessun iscritto")
        self.client.post(reverse("anagrafica:formazione_da_chiudere_azione"), {"sel": [vuota.pk], "azione": "annulla"})
        vuota.refresh_from_db()
        self.assertEqual(vuota.stato, "ANNULLATA")

    def test_fasi_nella_pagina_sessione(self):
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.s.pk]))
        self.assertContains(r, "Presenze di oggi")
        self.assertContains(r, "QR d'aula e test")


class EfficaciaTests(_Base):
    def test_salva_efficacia_e_pagina(self):
        aula.tutti_presenti(self.lz, self.admin)
        aula.chiudi(self.s, self.admin, {self.ea.pk: "COMPLETATO", self.eb.pk: "ASSENTE"})
        eff = TrainingEfficacia.objects.get()
        TrainingEfficacia.objects.filter(pk=eff.pk).update(attesa_dal=timezone.localdate())
        r = self.client.get(reverse("anagrafica:formazione_efficacia"))
        self.assertContains(r, "ROSSI MARIO")
        r = self.client.post(reverse("anagrafica:formazione_efficacia"), {"id": eff.pk, "esito": "PARZIALE"})
        eff.refresh_from_db()
        self.assertIsNone(eff.valutata_il)  # senza azione non si salva
        self.client.post(reverse("anagrafica:formazione_efficacia"),
                         {"id": eff.pk, "esito": "PARZIALE", "metodo": "PRATICA", "azione": "Affiancamento 2 settimane"})
        eff.refresh_from_db()
        self.assertEqual((eff.esito, eff.azione), ("PARZIALE", "Affiancamento 2 settimane"))
        self.assertIn("Prova pratica", eff.note)

    def test_capo_vede_solo_le_sue(self):
        aula.tutti_presenti(self.lz, self.admin)
        aula.chiudi(self.s, self.admin, {self.ea.pk: "COMPLETATO", self.eb.pk: "ASSENTE"})
        TrainingEfficacia.objects.update(attesa_dal=timezone.localdate())
        from .services.capo_team import Capo
        with mock.patch("anagrafica.services.capo_team.mappa_capi", return_value={A: Capo(9999)}):
            self.assertEqual(len(aula.efficacie_da_valutare(9999)), 1)
            self.assertEqual(aula.efficacie_da_valutare(1234), [])

    def test_tipo_senza_efficacia(self):
        self.tipo.efficacia_mesi = 0
        self.tipo.save()
        aula.tutti_presenti(self.lz, self.admin)
        aula.chiudi(self.s, self.admin, {self.ea.pk: "COMPLETATO", self.eb.pk: "ASSENTE"})
        self.assertFalse(TrainingEfficacia.objects.exists())

    def test_tipi_corso_salva_mesi(self):
        self.client.post(reverse("anagrafica:formazione_tipi_corso_azione"),
                         {"azione": "modifica", "tipo_id": self.tipo.pk, "nome": self.tipo.nome, "efficacia_mesi": "6"})
        self.tipo.refresh_from_db()
        self.assertEqual(self.tipo.efficacia_mesi, 6)
