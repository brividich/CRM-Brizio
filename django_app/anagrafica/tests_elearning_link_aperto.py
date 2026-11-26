"""Link aperto dei corsi e-learning (``/corso-aperto/<token>/``): fruizione senza login,
nome e cognome alla consegna, abbinamento automatico all'anagrafica e controllo HR.
Dati sintetici.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente
from core.models import UserOnboarding

from .models_elearning import TrainingElearningLinkAperto, TrainingElearningRispostaAperta as R
from .models_formazione import (
    TrainingAssignment, TrainingCompletionRule, TrainingCourse, TrainingEmployeeRecord, TrainingPlan,
    TrainingQuizOption, TrainingQuizQuestion, TrainingSlide,
)
from .services import elearning_link_aperto as servizio

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["*"])
class _Base(TestCase):
    def setUp(self):
        cache.clear()
        piano = TrainingPlan.objects.create(codice="PLA", nome="Piano link aperto")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="LA1", titolo="Corso officina", durata_ore_teorica=1,
            is_elearning=True, is_active=True, stato="ATTIVO", quiz_punteggio_minimo=100,
        )
        TrainingCompletionRule.objects.create(corso=self.corso, confermata_rspp_il=timezone.now())
        for i in (1, 2):
            TrainingSlide.objects.create(corso=self.corso, ordine=i, titolo=f"Slide {i}", contenuto=f"Testo {i}")
        self.q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="Domanda?")
        self.giusta = TrainingQuizOption.objects.create(domanda=self.q, testo="Giusta", corretta=True, ordine=1)
        self.sbagliata = TrainingQuizOption.objects.create(domanda=self.q, testo="Sbagliata", corretta=False, ordine=2)
        self.dip = AnagraficaDipendente.objects.create(nome="Màrio", cognome="Rossi Sintetico")
        self.link = TrainingElearningLinkAperto.objects.create(corso=self.corso, token="tok-" + "x" * 30)
        self.anonimo = Client()

    def url(self, nome="corso", *args):
        return reverse(f"corso_aperto:{nome}", args=[self.link.token, *args])

    def registra(self, client=None, nome="mario", cognome="ROSSI  sintetico", matricola="T999"):
        c = client or self.anonimo
        return c.post(self.url("registrati"), {"nome": nome, "cognome": cognome, "matricola": matricola})

    def segui_corso(self, client=None, **chi):
        c = client or self.anonimo
        self.registra(c, **chi)
        self.assertEqual(c.get(self.url()).status_code, 200)
        self.assertEqual(c.get(self.url() + "?s=2").status_code, 200)
        return c

    def consegna(self, opzione, nome=None, cognome=None, client=None, matricola="T999"):
        c = client or self.anonimo
        if nome is not None or cognome is not None:
            # Un'altra persona sullo stesso browser: nuova registrazione e nuovo percorso.
            self.segui_corso(c, nome=nome or "", cognome=cognome or "", matricola=matricola)
        r = c.get(self.url("quiz"))
        if r.status_code != 200:
            return r  # es. corso già completato: il quiz non si riapre
        return c.post(self.url("quiz"), {f"q_{self.q.pk}": [opzione.pk], "consegna": r.context["consegna"]})


class AccessoPubblicoTests(_Base):
    def test_senza_login_si_apre(self):
        r = self.anonimo.get(self.url())
        self.assertRedirects(r, self.url("registrati"), fetch_redirect_response=False)
        r = self.anonimo.get(self.url("registrati"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Matricola")
        self.assertIn("no-store", r["Cache-Control"])
        self.registra()
        r = self.anonimo.get(self.url())
        self.assertContains(r, "Slide 1")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")

    def test_token_errato_spento_scaduto_o_bozza_404(self):
        self.assertEqual(self.anonimo.get(reverse("corso_aperto:corso", args=["sbagliato"])).status_code, 404)
        self.link.attivo = False
        self.link.save()
        self.assertEqual(self.anonimo.get(self.url()).status_code, 404)
        self.link.attivo = True
        self.link.scade_il = timezone.localdate() - timezone.timedelta(days=1)
        self.link.save()
        self.assertEqual(self.anonimo.get(self.url()).status_code, 404)
        self.link.scade_il = None
        self.link.save()
        self.corso.stato = "BOZZA"
        self.corso.save()
        self.assertEqual(self.anonimo.get(self.url()).status_code, 404)

    def test_slide_in_ordine_e_quiz_solo_dopo_tutte(self):
        self.registra()
        r = self.anonimo.get(self.url() + "?s=2")
        self.assertContains(r, "Slide 1")  # la 2 non si salta
        self.assertEqual(self.anonimo.get(self.url("quiz")).status_code, 409)
        self.segui_corso()
        self.assertEqual(self.anonimo.get(self.url("quiz")).status_code, 200)

    def test_nessun_tempo_minimo_per_slide(self):
        """Dal 26/11/2026 la permanenza minima per slide non si applica: si passa subito alla successiva."""
        regola = TrainingCompletionRule.objects.get(corso=self.corso)
        regola.el_secondi_minimi_slide = 60
        regola.save()
        self.registra()
        self.anonimo.get(self.url())
        r = self.anonimo.get(self.url() + "?s=2")
        self.assertContains(r, "Slide 2")
        self.assertNotContains(r, "Puoi andare avanti tra")

    def test_media_solo_di_slide_aperte(self):
        s2 = self.corso.slides.get(ordine=2)
        self.assertEqual(self.anonimo.get(self.url("immagine", s2.pk)).status_code, 404)


class ConsegnaTests(_Base):
    def test_abbinamento_automatico_e_completamento(self):
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=self.dip.id, stato="ASSEGNATO")
        self.segui_corso()
        r = self.consegna(self.giusta)
        self.assertContains(r, "Corso completato")
        risposta = R.objects.get()
        self.assertEqual((risposta.stato, risposta.legacy_anagrafica_id, risposta.superato), (R.AUTO, self.dip.id, True))
        record = TrainingEmployeeRecord.objects.get(legacy_anagrafica_id=self.dip.id)
        self.assertEqual(risposta.record_id, record.pk)
        self.assertIn("link aperto", record.note)
        self.assertEqual(TrainingAssignment.objects.get().stato, "COMPLETATO")

    def test_non_superato_nessun_record(self):
        self.segui_corso()
        r = self.consegna(self.sbagliata)
        self.assertContains(r, "Quiz non superato")
        self.assertEqual(R.objects.get().stato, R.AUTO)
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_nome_sconosciuto_o_omonimi_da_abbinare(self):
        AnagraficaDipendente.objects.create(nome="Mario", cognome="Rossi Sintetico")  # omonimo
        self.segui_corso()
        self.consegna(self.giusta, nome="Nessuno", cognome="Sconosciuto")
        # Torna Mario (stessa matricola e cognome): riprende la sua partecipazione non finita.
        self.consegna(self.giusta, nome="Mario", cognome="Rossi Sintetico")
        self.assertEqual(list(R.objects.values_list("stato", flat=True)), [R.DA_ABBINARE, R.DA_ABBINARE])
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_nome_e_matricola_obbligatori_prima_di_iniziare(self):
        r = self.registra(nome="", cognome="", matricola="")
        self.assertEqual(r.status_code, 400)
        r = self.registra(matricola="")
        self.assertEqual(r.status_code, 400)
        self.assertRedirects(self.anonimo.get(self.url("quiz")), self.url("registrati"), fetch_redirect_response=False)
        self.assertFalse(R.objects.exists())

    def test_consultazione_libera_dopo_la_registrazione(self):
        self.registra()
        r = self.anonimo.get(self.url("materiale"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Materiale del corso")
        r = self.anonimo.get(self.url() + "?c=2")
        self.assertContains(r, "Consultazione")
        # La consultazione non sblocca il quiz: serve il percorso guidato.
        self.assertEqual(self.anonimo.get(self.url("quiz")).status_code, 409)

    def test_matricola_di_un_altra_persona_non_abbina(self):
        from unittest import mock
        from .services import elearning_link_aperto as la
        altro = AnagraficaDipendente.objects.create(nome="Luigi", cognome="Verdi Sintetico")
        with mock.patch.object(la, "matricole_attive", return_value={altro.id: {"T138"}}):
            self.segui_corso(matricola="000000t138")
            self.consegna(self.giusta)
        r = R.objects.get()
        self.assertEqual(r.stato, R.DA_ABBINARE)
        self.assertIn("altra persona", r.nota)
        # Matricola corretta (diversa da quella sbagliata di prima): nuova partecipazione, abbinata.
        with mock.patch.object(la, "matricole_attive", return_value={self.dip.id: {"T139"}}):
            self.consegna(self.giusta, nome="Mario", cognome="rossi sintetico", matricola="t 139")
        self.assertEqual(R.objects.order_by("-pk").first().stato, R.AUTO)

    def test_campo_trappola_non_salva(self):
        self.segui_corso()
        r = self.anonimo.get(self.url("quiz"))
        self.anonimo.post(self.url("quiz"), {f"q_{self.q.pk}": [self.giusta.pk], "nome": "a", "cognome": "b",
                                             "sito_web": "x", "consegna": r.context["consegna"]})
        self.assertFalse(R.objects.exists())

    def test_dopo_il_superamento_il_quiz_non_si_ripete(self):
        self.segui_corso()
        self.consegna(self.giusta)
        r = self.consegna(self.giusta)
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "Corso già completato", status_code=409)
        self.assertEqual(TrainingEmployeeRecord.objects.count(), 1)
        self.assertEqual(R.objects.count(), 1)


class ControlloHrTests(_Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("hr.link", "hr@example.invalid", "x")
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True, "completed_at": timezone.now()})
        self.hr = Client()
        self.hr.force_login(self.admin)

    def test_attiva_rigenera_spegni(self):
        self.link.delete()
        url = reverse("anagrafica:elearning_link_aperto", args=[self.corso.pk])
        self.hr.post(url, {"azione": "attiva"})
        link = TrainingElearningLinkAperto.objects.get(corso=self.corso)
        vecchio = link.token
        self.hr.post(url, {"azione": "rigenera"})
        link.refresh_from_db()
        self.assertNotEqual(link.token, vecchio)
        self.assertEqual(self.anonimo.get(reverse("corso_aperto:corso", args=[vecchio])).status_code, 404)
        self.hr.post(url, {"azione": "spegni"})
        link.refresh_from_db()
        self.assertFalse(link.attivo)

    def test_gestione_mostra_link_e_risposte(self):
        self.segui_corso()
        self.consegna(self.giusta, nome="Nessuno", cognome="Sconosciuto")
        r = self.hr.get(reverse("anagrafica:formazione_elearning_manage", args=[self.corso.pk]))
        self.assertContains(r, self.link.token)
        self.assertContains(r, "1 da abbinare")
        self.assertContains(r, "Sconosciuto Nessuno")
        self.assertEqual(self.hr.get(reverse("anagrafica:elearning_link_aperto_qr", args=[self.corso.pk]))["Content-Type"],
                         "image/png")

    def test_abbina_a_mano_e_correggi_annulla_il_record_precedente(self):
        altro = AnagraficaDipendente.objects.create(nome="Luigi", cognome="Verdi Sintetico")
        self.segui_corso()
        self.consegna(self.giusta, nome="Mario", cognome="Rossi Sintetico")
        risposta = R.objects.get()
        url = reverse("anagrafica:elearning_risposta_aperta", args=[self.corso.pk, risposta.pk])
        self.hr.post(url, {"azione": "abbina", "legacy_anagrafica_id": altro.id})
        risposta.refresh_from_db()
        self.assertEqual((risposta.stato, risposta.legacy_anagrafica_id), (R.MANUALE, altro.id))
        vecchio = TrainingEmployeeRecord.tutti.get(legacy_anagrafica_id=self.dip.id)
        self.assertTrue(vecchio.is_annullato)
        self.assertTrue(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=altro.id).exists())

    def test_scarta_annulla_il_record(self):
        self.segui_corso()
        self.consegna(self.giusta)
        risposta = R.objects.get()
        self.hr.post(reverse("anagrafica:elearning_risposta_aperta", args=[self.corso.pk, risposta.pk]), {"azione": "scarta"})
        risposta.refresh_from_db()
        self.assertEqual(risposta.stato, R.SCARTATA)
        self.assertFalse(TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=self.dip.id).exists())

    def test_senza_permesso_niente(self):
        anonimo_loggato = User.objects.create_user("nessuno.link", "n@example.invalid", "x")
        UserOnboarding.objects.update_or_create(user=anonimo_loggato,
                                                defaults={"completed": True, "completed_at": timezone.now()})
        c = Client()
        c.force_login(anonimo_loggato)
        c.post(reverse("anagrafica:elearning_link_aperto", args=[self.corso.pk]), {"azione": "spegni"})
        self.link.refresh_from_db()
        self.assertTrue(self.link.attivo)


class ServizioTests(_Base):
    def test_candidati_ignorano_ordine_accenti_maiuscole(self):
        self.assertEqual(servizio.candidati("ROSSI SINTETICO", "mario"), [self.dip.id])
        self.assertEqual(servizio.candidati("Mario", "Rossi"), [])


class PartecipazioneApertaTests(_Base):
    """Fase A: la partecipazione nasce alla registrazione e tiene avanzamento e tempo sul server."""

    def test_registrazione_crea_partecipazione_abbinata(self):
        from .models_elearning import TrainingElearningPartecipazioneAperta as P
        self.segui_corso()
        p = P.objects.get()
        self.assertEqual(p.legacy_anagrafica_id, self.dip.id)
        self.assertEqual(len(p.slide_viste), 2)
        self.consegna(self.giusta)
        p.refresh_from_db()
        self.assertIsNotNone(p.completata_il)
        self.assertEqual(R.objects.get().partecipazione_id, p.pk)

    def test_tempo_accreditato_dal_server(self):
        from datetime import timedelta
        from .models_elearning import TrainingElearningPartecipazioneAperta as P
        self.registra()
        self.anonimo.get(self.url())
        P.objects.update(ultimo_accesso_il=timezone.now() - timedelta(seconds=40))
        self.anonimo.get(self.url() + "?s=2")
        self.assertGreaterEqual(P.objects.get().secondi, 39)
        P.objects.update(ultimo_accesso_il=timezone.now() - timedelta(hours=3))
        self.anonimo.get(self.url())
        self.assertLess(P.objects.get().secondi, 40 + 125)  # la pagina dimenticata aperta non conta ore

    def test_ripresa_da_altro_telefono_con_codice(self):
        from .models_elearning import TrainingElearningPartecipazioneAperta as P
        self.segui_corso()
        p = P.objects.get()
        altro = Client()
        r = altro.post(self.url("registrati"), {"codice": p.codice.lower(), "cognome_ripresa": "Sbagliato"})
        self.assertEqual(r.status_code, 400)
        altro.post(self.url("registrati"), {"codice": p.codice, "cognome_ripresa": "rossi sintetico"})
        self.assertEqual(altro.get(self.url("quiz")).status_code, 200)  # slide già viste: il quiz si apre
        self.assertEqual(P.objects.count(), 1)

    def test_qr_reparto_passa_alla_registrazione(self):
        r = self.anonimo.get(self.url() + "?rep=Officina")
        self.assertIn("rep=Officina", r["Location"])
        self.assertContains(self.anonimo.get(r["Location"]), "Officina")
