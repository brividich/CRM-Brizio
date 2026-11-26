"""Link aperto: ripresa dal punto giusto, codice in vista e per email, un corso = un completamento.
Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.core import mail
from django.test import Client

from .models_elearning import TrainingElearningPartecipazioneAperta as P
from .models_formazione import TrainingEmployeeRecord, TrainingEnrollment, TrainingSession
from .services import elearning_link_aperto as servizio
from .tests_elearning_link_aperto import _Base


class RipresaTests(_Base):
    def test_dopo_la_registrazione_pagina_col_codice(self):
        r = self.registra()
        self.assertEqual(r["Location"], self.url("pronto"))
        p = P.objects.get()
        pagina = self.anonimo.get(self.url("pronto"))
        self.assertContains(pagina, p.codice)
        self.assertContains(pagina, "inizia il corso")

    def test_stesso_telefono_sessione_scaduta_riprende_dalla_prima_non_vista(self):
        self.registra()
        self.anonimo.get(self.url())  # slide 1
        # La sessione del browser scade: resta solo il cookie firmato del corso.
        self.anonimo.cookies.pop("sessionid", None)
        r = self.anonimo.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["indice"], 2)
        self.assertEqual(P.objects.count(), 1)

    def test_cookie_manomesso_non_vale(self):
        self.registra()
        self.anonimo.cookies.pop("sessionid", None)
        self.anonimo.cookies[f"pn_corso_{self.link.pk}"] = "1:falso"
        r = self.anonimo.get(self.url())
        self.assertEqual(r.status_code, 302)
        self.assertIn("registrati", r["Location"])

    def test_nuova_registrazione_stessa_matricola_riprende(self):
        self.registra()
        self.anonimo.get(self.url())
        altro = Client()
        r = self.registra(altro, nome="Mario", cognome="Rossi Sintetico", matricola="t 999")
        self.assertEqual(r["Location"], self.url("pronto"))
        self.assertEqual(P.objects.count(), 1)
        self.assertContains(altro.get(self.url("pronto")), "riprendi dalla slide 2")
        self.assertEqual(altro.get(self.url()).context["indice"], 2)

    def test_matricola_diversa_nuova_partecipazione(self):
        self.registra()
        self.registra(Client(), matricola="T111")
        self.assertEqual(P.objects.count(), 2)

    def test_codice_riprende_dalla_slide_giusta(self):
        self.registra()
        self.anonimo.get(self.url())
        p = P.objects.get()
        altro = Client()
        r = altro.post(self.url("registrati"), {"codice": p.codice, "cognome_ripresa": "rossi sintetico"})
        self.assertEqual(r["Location"], self.url("pronto"))
        self.assertEqual(altro.get(self.url()).context["indice"], 2)


class EmailCodiceTests(_Base):
    def test_email_alla_persona_abbinata(self):
        self.dip.email_notifica = "mario.sintetico@example.com"
        self.dip.save()
        with mock.patch.object(servizio, "accoda_email_codice") as accoda:
            self.registra()
        accoda.assert_called_once()
        self.assertContains(self.anonimo.get(self.url("pronto")), "m•••@example.com")
        p = P.objects.get()
        self.assertTrue(servizio.invia_email_codice(p.pk, "https://esempio.invalid/corso-aperto/x/registrati/"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(p.codice, mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mario.sintetico@example.com"])

    def test_senza_email_nessun_invio(self):
        with mock.patch.object(servizio, "accoda_email_codice") as accoda:
            self.registra()
        accoda.assert_not_called()
        self.assertFalse(servizio.invia_email_codice(P.objects.get().pk, "https://esempio.invalid/"))


class CorsoUnicoTests(_Base):
    def _sessione_online(self, **kw):
        s = TrainingSession.objects.create(corso=self.corso, codice_sessione=kw.pop("codice", "S-ON-1"),
                                           modalita=kw.pop("modalita", "ONLINE"), data_inizio=date.today(),
                                           data_fine=date.today() + timedelta(days=30), stato="PIANIFICATA")
        e = TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=self.dip.id, stato="ISCRITTO")
        return s, e

    def test_link_aperto_completa_anche_la_sessione_online(self):
        s, e = self._sessione_online()
        self.segui_corso()
        self.consegna(self.giusta)
        e.refresh_from_db()
        self.assertEqual(e.stato, "COMPLETATO")
        self.assertTrue(e.verifica_superata)
        record = TrainingEmployeeRecord.objects.get(legacy_anagrafica_id=self.dip.id)
        self.assertEqual((record.enrollment_id, record.sessione_id), (e.pk, s.pk))
        self.assertEqual(TrainingEmployeeRecord.objects.count(), 1)

    def test_sessione_in_aula_non_si_tocca(self):
        _s, e = self._sessione_online(modalita="IN_SEDE")
        self.segui_corso()
        self.consegna(self.giusta)
        e.refresh_from_db()
        self.assertEqual(e.stato, "ISCRITTO")

    def test_catalogo_una_riga_per_corso(self):
        from .views_elearning import _sezioni_catalogo
        s, e = self._sessione_online()
        oggi = date.today()
        card = {"corso": self.corso, "stato": "COMPLETATO", "n_slide": 2, "due_date": None, "in_ritardo": False,
                "progress_pct": 100, "best_pct": None, "assegnato_da_fare": False, "da_valutare": False}
        lz = {"sessione": s, "cfg": mock.Mock(scadenza=oggi), "finita": False, "stato": "non_iniziata",
              "stato_label": "Non iniziata", "url": "/x/", "n_slide": 2}
        da_fare, _disp, completati = _sezioni_catalogo([card], [lz], oggi)
        self.assertEqual((len(da_fare), len(completati)), (0, 1))
        card["stato"] = None
        da_fare, disp, completati = _sezioni_catalogo([card], [lz], oggi)
        self.assertEqual((len(da_fare), len(disp), len(completati)), (1, 0, 0))
        self.assertEqual(da_fare[0]["tipo"], "sessione")
