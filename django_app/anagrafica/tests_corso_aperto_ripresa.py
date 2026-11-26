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


class PercorsoVideoOSlideTests(_Base):
    def setUp(self):
        super().setUp()
        from .models_elearning import TrainingElearningModulo as M
        from .models_formazione import TrainingSlide
        m_slide = M.objects.create(corso=self.corso, ordine=1, titolo="Presentazione", alternativa="SLIDE")
        m_video = M.objects.create(corso=self.corso, ordine=2, titolo="Video", alternativa="VIDEO")
        self.corso.slides.update(modulo=m_slide)
        self.v = TrainingSlide.objects.create(corso=self.corso, ordine=3, titolo="Il video", contenuto="(video)",
                                              modulo=m_video)

    def test_percorsi(self):
        from .services import elearning_fruizione as f
        self.assertTrue(f.percorsi_a_scelta(self.corso))
        self.assertEqual(f.ordini_slide(self.corso, "VIDEO"), [3])
        self.assertEqual(f.ordini_slide(self.corso, "SLIDE"), [1, 2])
        self.assertEqual(f.ordini_slide(self.corso), [1, 2])

    def test_link_aperto_sceglie_video_e_fa_il_quiz(self):
        self.registra()
        self.assertContains(self.anonimo.get(self.url("pronto")), "Guarda il video")
        r = self.anonimo.get(self.url())
        self.assertEqual(r["Location"], self.url("pronto"))
        self.assertEqual(self.anonimo.get(self.url("quiz"))["Location"], self.url("pronto"))
        self.anonimo.post(self.url("pronto"), {"percorso": "VIDEO"})
        r = self.anonimo.get(self.url())
        self.assertEqual((r.context["slide"].pk, r.context["n_slide"]), (self.v.pk, 1))
        q = self.anonimo.get(self.url("quiz"))
        self.assertEqual(q.status_code, 200)
        self.assertEqual(P.objects.get().percorso, "VIDEO")
        r = self.anonimo.post(self.url("quiz"), {f"q_{self.q.pk}": [self.giusta.pk], "consegna": q.context["consegna"]})
        self.assertContains(r, "Corso completato")

    def test_scelta_bloccata_dopo_la_prima_slide(self):
        self.registra()
        self.anonimo.post(self.url("pronto"), {"percorso": "SLIDE"})
        self.anonimo.get(self.url())
        self.anonimo.post(self.url("pronto"), {"percorso": "VIDEO"})
        self.assertEqual(P.objects.get().percorso, "SLIDE")

    def test_un_solo_tipo_nessuna_scelta(self):
        from .services import elearning_fruizione as f
        self.corso.moduli_elearning.filter(alternativa="VIDEO").update(alternativa="")
        self.assertFalse(f.percorsi_a_scelta(self.corso))
        self.assertEqual(f.ordini_slide(self.corso), [1, 2, 3])


class UnaSolaConsegnaTests(_Base):
    """Il quiz del link aperto non si consegna due volte: doppio clic, pagina ricaricata, altra scheda,
    gettone vecchio o assente, nuova registrazione dopo il completamento."""

    def _quiz(self, c=None):
        c = c or self.anonimo
        r = c.get(self.url("quiz"))
        self.assertEqual(r.status_code, 200)
        return r.context["consegna"]

    def _post(self, gettone, opzione=None, c=None):
        c = c or self.anonimo
        return c.post(self.url("quiz"), {f"q_{self.q.pk}": [(opzione or self.giusta).pk], "consegna": gettone})

    def test_stesso_invio_due_volte(self):
        from .models_elearning import TrainingElearningRispostaAperta as R
        self.segui_corso()
        g = self._quiz()
        self.assertContains(self._post(g, self.sbagliata), "Quiz non superato")
        r = self._post(g)  # ripetuto (doppio clic o pagina ricaricata): non vale
        self.assertEqual(r.status_code, 409)
        self.assertEqual(R.objects.count(), 1)
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_senza_gettone_o_gettone_inventato(self):
        from .models_elearning import TrainingElearningRispostaAperta as R
        self.segui_corso()
        self._quiz()
        self.assertEqual(self._post("").status_code, 409)
        self.assertEqual(self._post("inventato").status_code, 409)
        self.assertFalse(R.objects.exists())

    def test_gettone_di_un_quiz_superato_da_un_altra_scheda(self):
        from .models_elearning import TrainingElearningRispostaAperta as R
        self.segui_corso()
        vecchio = self._quiz()
        nuovo = self._quiz()  # seconda scheda: il gettone vecchio non vale più
        self.assertEqual(self._post(vecchio).status_code, 409)
        self.assertContains(self._post(nuovo), "Corso completato")
        self.assertEqual(R.objects.count(), 1)

    def test_gettone_riusato_dopo_aver_ripristinato_la_sessione(self):
        """Chi salva la sessione prima dell'invio e la rimette dopo non consegna di nuovo."""
        from .models_elearning import TrainingElearningRispostaAperta as R
        self.segui_corso()
        g = self._quiz()
        chiave = f"corso_aperto:{self.link.pk}:{self.link.token[:12]}"
        copia = dict(self.anonimo.session[chiave])
        self._post(g, self.sbagliata)
        s = self.anonimo.session
        s[chiave] = copia
        s.save()
        self.assertEqual(self._post(g).status_code, 409)
        self.assertEqual(R.objects.count(), 1)

    def test_nuova_registrazione_dopo_il_completamento(self):
        from .models_elearning import TrainingElearningRispostaAperta as R
        self.segui_corso()
        self._post(self._quiz())
        altro = Client()
        self.registra(altro)  # stessa matricola e cognome: ritrova la partecipazione completata
        self.assertContains(altro.get(self.url("pronto")), "già completato")
        self.assertEqual(altro.get(self.url("quiz")).status_code, 409)
        self.assertEqual(P.objects.count(), 1)
        self.assertEqual(R.objects.count(), 1)

    def test_codice_di_una_partecipazione_completata(self):
        self.segui_corso()
        self._post(self._quiz())
        p = P.objects.get()
        altro = Client()
        altro.post(self.url("registrati"), {"codice": p.codice, "cognome_ripresa": "rossi sintetico"})
        self.assertEqual(altro.get(self.url("quiz")).status_code, 409)
