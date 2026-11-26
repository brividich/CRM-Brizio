"""Sessioni formative ↔ «Corso richiesto» della competenza della mansione (24/11/2026).

- all'apertura l'edizione già completata del corso richiesto entra nella riga;
- senza requisito formale la riga non va oltre «I – in formazione» (stessa regola della matrice);
- corso completato dopo: l'edizione entra da sola nelle righe aperte;
- mansione senza competenze richieste: avviso prima di aprire la sessione;
- scheda della mansione: sessioni formative e richieste in corso per persona, attese del corso.

Dati sintetici.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from .models import VoceMacchinaCatalogo
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingEnrollment, TrainingPlan, TrainingSession
from .models_sessioni import SessioneEvento, SessioneRiga as Riga
from .services import sessioni as svc
from .tests_sessioni import _Scenario as _ScenarioSessioni


class _Scenario(_ScenarioSessioni):
    def setUp(self):
        super().setUp()
        piano = TrainingPlan.objects.create(codice="P-SF", nome="Piano sintetico SF")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-MIS", titolo="Strumenti di misura",
                                                   durata_ore_teorica=8, is_active=True)
        self.v_misure.corso = self.corso
        self.v_misure.save()
        self.edizione = TrainingSession.objects.create(corso=self.corso, codice_sessione="ED-MIS-1",
                                                       data_inizio=date(2026, 10, 5), data_fine=date(2026, 10, 6))

    def _completa(self, **extra):
        dati = dict(sessione=self.edizione, legacy_anagrafica_id=self.rossi, stato="COMPLETATO", idoneo=True,
                    data_completamento=date(2026, 10, 6))
        dati.update(extra)
        iscrizione = TrainingEnrollment.objects.create(**dati)
        # «Corso completato» = completamento a libretto valido (regola unica completamento_valido).
        from .models_formazione import TrainingEmployeeRecord
        TrainingEmployeeRecord.objects.create(
            corso=self.corso, sessione=self.edizione, enrollment=iscrizione, legacy_anagrafica_id=self.rossi,
            data_completamento=dati["data_completamento"], idoneo=dati["idoneo"] is not False)
        return iscrizione

    def _valido(self):
        TrainingDeadline.objects.update_or_create(
            legacy_anagrafica_id=self.rossi, corso=self.corso,
            defaults={"is_required": True, "stato_scadenza": "UNA_TANTUM",
                      "data_scadenza": timezone.localdate() + timedelta(days=3650)})


class CorsoRichiestoAperturaTests(_Scenario):
    def test_edizione_completata_entra_all_apertura(self):
        self._completa()
        s = self._aperta()
        riga = self._riga(s, self.v_misure)
        self.assertEqual((riga.edizione_id, riga.corso_id, riga.data_corso), (self.edizione.pk, self.corso.pk, date(2026, 10, 6)))
        self.assertEqual(riga.verifica, Riga.VERIFICA_ATTESTATO)
        # Modalità e livello restano a chi valuta.
        self.assertEqual((riga.modalita, riga.stato), ("", Riga.STATO_DA_ASSEGNARE))
        self.assertTrue(SessioneEvento.objects.filter(sessione=s, riga=riga, azione="Edizione collegata").exists())

    def test_senza_iscrizione_la_riga_resta_vuota(self):
        s = self._aperta()
        riga = self._riga(s, self.v_misure)
        self.assertIsNone(riga.edizione_id)
        self.assertEqual(svc.corso_richiesto(riga), self.corso)

    def test_non_idoneo_non_entra(self):
        self._completa(idoneo=False)
        self.assertIsNone(self._riga(self._aperta(), self.v_misure).edizione_id)


class RequisitoFormaleTests(_Scenario):
    def test_senza_corso_valido_non_si_va_oltre_i(self):
        s = self._aperta()
        riga = self._riga(s, self.v_misure)
        with self.assertRaisesMessage(svc.SessioneNonValida, "manca il requisito formale (corso «Strumenti di misura»)"):
            svc.valuta(self.capo, riga, modalita="C", livello="U", docente_ente="Ente di prova", verifica="test")
        riga = svc.valuta(self.capo, riga, modalita="C", livello="I", docente_ente="Ente di prova", verifica="test")
        self.assertEqual(riga.stato, Riga.STATO_IN_ACQUISIZIONE)
        self._valido()
        riga = svc.valuta(self.capo, riga, modalita="C", livello="U", docente_ente="Ente di prova", verifica="test")
        self.assertEqual(riga.stato, Riga.STATO_POSITIVA)

    def test_vale_anche_per_pregressa_e_affiancamento(self):
        s = self._aperta()
        with self.assertRaisesMessage(svc.SessioneNonValida, "requisito formale"):
            svc.valuta(self.capo, self._riga(s, self.v_misure), modalita="P", livello="U",
                       descrizione="Prova pratica", data_verifica=timezone.localdate())

    def test_requisito_scaduto_dopo_la_valutazione_blocca_firma_e_chiusura(self):
        self._valido()
        s = self._aperta()
        self._valuta_tutto(s)
        TrainingDeadline.objects.filter(legacy_anagrafica_id=self.rossi, corso=self.corso).update(stato_scadenza="SCADUTO")
        self.assertIn("«Misure»: manca il requisito formale", svc.motivo_non_firma_approvatore(self.rdd, s))
        self.assertIn("«Misure»: manca il requisito formale", svc.motivo_non_chiude(self.hr, s))
        self.assertEqual([r.voce for r, _ in svc.righe_senza_requisito(s)], [self.v_misure])


class EdizioneCollegataDaSolaTests(_Scenario):
    def test_corso_completato_dopo_entra_nella_riga_aperta(self):
        s = self._aperta()
        isc = TrainingEnrollment.objects.create(sessione=self.edizione, legacy_anagrafica_id=self.rossi, stato="ISCRITTO")
        with self.captureOnCommitCallbacks(execute=True):
            isc.stato, isc.idoneo, isc.data_completamento = "COMPLETATO", True, date(2026, 10, 6)
            isc.save()
        riga = self._riga(s, self.v_misure)
        self.assertEqual(riga.edizione_id, self.edizione.pk)
        self.assertEqual(svc.collega_edizioni_completate(isc), 0)  # già collegata: niente doppioni

    def test_riga_gia_valutata_o_sessione_firmata_non_cambia(self):
        self._valido()
        s = self._aperta()
        self._valuta_tutto(s)
        svc.firma_approvatore(self.rdd, s, visto_mod040=True)
        self.assertEqual(svc.collega_edizioni_completate(self._completa()), 0)


class SenzaCompetenzeTests(_Scenario):
    def test_avviso_prima_di_aprire(self):
        vuota = self._crea_mansione("Mansione vuota", self.in1, self.op)
        richiesta = self._approvata(mansione_id=vuota.pk)
        self.assertIn("non ha competenze richieste", svc.avviso_apertura(richiesta))
        self.assertTrue([x for x in svc.da_fare(self.hr)["da_aprire"] if x["senza_competenze"]])
        self.assertEqual(svc.avviso_apertura(self._approvata()), "")


class PagineTests(_Scenario):
    def _come(self, attore):
        self.client.force_login(attore.user)
        return mock.patch("anagrafica.services.richieste.attore", return_value=attore)

    def test_dettaglio_mostra_corso_richiesto_e_iscrivi(self):
        s = self._aperta()
        with self._come(self.hr), mock.patch("anagrafica.views._helpers._can_edit_formazione", return_value=True):
            pagina = self.client.get(reverse("anagrafica:sessione", args=[s.pk]))
        self.assertContains(pagina, "Corso richiesto: «Strumenti di misura» · mancante")
        self.assertContains(pagina, "Iscrivi a un'edizione")
        self.assertContains(pagina, f'data-corso-richiesto="{self.corso.pk}"')
        self.assertNotContains(pagina, "{#")

    def test_scheda_mansione_mostra_sessione_e_attesa_del_corso(self):
        s = self._aperta()
        self.client.force_login(self.hr.user)
        with mock.patch("anagrafica.views_mansionario._puo_vedere", return_value=True):
            pagina = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.torno.pk]))
        self.assertContains(pagina, f"Sessione formativa {s.codice}: aperta")
        self.assertContains(pagina, "1 in sessione formativa, in attesa del corso")
