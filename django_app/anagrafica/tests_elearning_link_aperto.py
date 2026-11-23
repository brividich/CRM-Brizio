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

    def segui_corso(self, client=None):
        c = client or self.anonimo
        self.assertEqual(c.get(self.url()).status_code, 200)
        self.assertEqual(c.get(self.url() + "?s=2").status_code, 200)
        return c

    def consegna(self, opzione, nome="mario", cognome="ROSSI  sintetico", client=None):
        c = client or self.anonimo
        self.assertEqual(c.get(self.url("quiz")).status_code, 200)
        return c.post(self.url("quiz"), {f"q_{self.q.pk}": [opzione.pk], "nome": nome, "cognome": cognome})


class AccessoPubblicoTests(_Base):
    def test_senza_login_si_apre(self):
        r = self.anonimo.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Slide 1")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", r["Cache-Control"])

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
        r = self.anonimo.get(self.url() + "?s=2")
        self.assertContains(r, "Slide 1")  # la 2 non si salta
        self.assertEqual(self.anonimo.get(self.url("quiz")).status_code, 409)
        self.segui_corso()
        self.assertEqual(self.anonimo.get(self.url("quiz")).status_code, 200)

    def test_secondi_minimi_per_slide(self):
        regola = TrainingCompletionRule.objects.get(corso=self.corso)
        regola.el_secondi_minimi_slide = 60
        regola.save()
        self.anonimo.get(self.url())
        r = self.anonimo.get(self.url() + "?s=2")
        self.assertContains(r, "Slide 1")
        self.assertContains(r, "Puoi andare avanti tra")

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
        self.segui_corso()
        self.consegna(self.giusta, nome="Nessuno", cognome="Sconosciuto")
        AnagraficaDipendente.objects.create(nome="Mario", cognome="Rossi Sintetico")
        self.consegna(self.giusta)
        self.assertEqual(list(R.objects.values_list("stato", flat=True)), [R.DA_ABBINARE, R.DA_ABBINARE])
        self.assertFalse(TrainingEmployeeRecord.objects.exists())

    def test_nome_obbligatorio(self):
        self.segui_corso()
        r = self.consegna(self.giusta, nome="", cognome="")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(R.objects.exists())

    def test_campo_trappola_non_salva(self):
        self.segui_corso()
        self.anonimo.get(self.url("quiz"))
        self.anonimo.post(self.url("quiz"), {f"q_{self.q.pk}": [self.giusta.pk], "nome": "a", "cognome": "b",
                                             "sito_web": "x"})
        self.assertFalse(R.objects.exists())

    def test_secondo_superamento_stessa_versione_riusa_il_record(self):
        self.segui_corso()
        self.consegna(self.giusta)
        self.consegna(self.giusta)
        self.assertEqual(TrainingEmployeeRecord.objects.count(), 1)
        self.assertEqual(R.objects.filter(record__isnull=False).count(), 2)


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
