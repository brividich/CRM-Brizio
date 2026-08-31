"""Docenti con azienda formativa, ricerca estesa ai docenti, libretto per periodo.

Tre migliorie che si tengono: l'ente di formazione diventa un'entità (prima era
testo libero ripetuto su ogni docente), la ricerca globale sa rispondere anche
alla domanda «chi ha insegnato cosa», e il libretto formativo si può ritagliare
su un intervallo di date.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser durante i test (vedi tests_formazione_form_cerca).
"""
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import TrainingLessonForm, TrainingSessionForm
from .models_formazione import (
    TrainingCourse,
    TrainingPlan,
    TrainingEmployeeRecord,
    TrainingInstructor,
    TrainingLesson,
    TrainingProvider,
    TrainingSession,
)

User = get_user_model()

FAKE_DIP = [{
    "legacy_anagrafica_id": 4242,
    "cognome": "Rossi",
    "nome": "Mario",
    "matricola": "M-42",
    "reparto": "Produzione",
    "mansione": "Operatore",
}]


def _corso(codice="C-DOC", titolo="Sicurezza generale"):
    piano, _ = TrainingPlan.objects.get_or_create(
        codice="P-DOC", defaults={"nome": "Piano docenti"},
    )
    return TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=titolo, durata_ore_teorica=4,
    )


def _sessione(corso, codice, data, docente=None):
    return TrainingSession.objects.create(
        corso=corso, codice_sessione=codice,
        data_inizio=data, data_fine=data, docente=docente,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AziendaFormativaTests(TestCase):
    """CRUD dell'ente e legame con i docenti."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-az", "su-az@test.local", "x")
        self.client.force_login(self.su)

    def test_creazione_azienda_e_associazione_docente(self):
        resp = self.client.post(reverse("anagrafica:formazione_azienda_create"), {
            "nome": "  Formazione Sicura   S.r.l. ",
            "partita_iva": "01234567890",
            "is_active": "True",
        })
        self.assertEqual(resp.status_code, 302)
        az = TrainingProvider.objects.get()
        # clean_nome collassa gli spazi: due grafie non devono convivere.
        self.assertEqual(az.nome, "Formazione Sicura S.r.l.")

        resp = self.client.post(reverse("anagrafica:formazione_istruttore_create"), {
            "tipo": "ESTERNO", "nome": "Bianchi Luca", "azienda": str(az.pk), "is_active": "True",
        })
        self.assertEqual(resp.status_code, 302)
        istr = TrainingInstructor.objects.get()
        self.assertEqual(istr.azienda_id, az.pk)
        self.assertEqual(istr.ente, "Formazione Sicura S.r.l.")

    def test_ente_ripiega_sul_testo_libero_quando_non_c_e_azienda(self):
        istr = TrainingInstructor.objects.create(nome="Verdi", ragione_sociale="Studio Verdi")
        self.assertEqual(istr.ente, "Studio Verdi")

    def test_eliminazione_con_docenti_disattiva_invece_di_cancellare(self):
        az = TrainingProvider.objects.create(nome="Ente con docenti")
        TrainingInstructor.objects.create(nome="Neri", azienda=az)
        resp = self.client.post(reverse("anagrafica:formazione_azienda_delete", args=[az.pk]))
        self.assertEqual(resp.status_code, 302)
        az.refresh_from_db()
        self.assertFalse(az.is_active)

    def test_eliminazione_senza_docenti_cancella(self):
        az = TrainingProvider.objects.create(nome="Ente vuoto")
        resp = self.client.post(reverse("anagrafica:formazione_azienda_delete", args=[az.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrainingProvider.objects.filter(pk=az.pk).exists())

    def test_modifica_azienda(self):
        az = TrainingProvider.objects.create(nome="Vecchio nome")
        resp = self.client.post(reverse("anagrafica:formazione_azienda_edit", args=[az.pk]), {
            "nome": "Nuovo nome", "accreditamento": "REG-2026/17", "is_active": "True",
        })
        self.assertEqual(resp.status_code, 302)
        az.refresh_from_db()
        self.assertEqual(az.nome, "Nuovo nome")
        self.assertEqual(az.accreditamento, "REG-2026/17")

    def _docenti_table_section(self, body):
        # La tabella "Aziende formative" elenca sempre tutti i docenti di ogni
        # ente (righe di dettaglio espandibili), a prescindere dal filtro: le
        # asserzioni sul filtro riguardano solo la tabella docenti sotto.
        marker = 'data-table-id="formazione.istruttori.list"'
        idx = body.index(marker)
        return body[idx:]

    def test_elenco_docenti_filtra_per_azienda(self):
        az = TrainingProvider.objects.create(nome="Alfa Formazione")
        dentro = TrainingInstructor.objects.create(nome="Docente Alfa", azienda=az)
        fuori = TrainingInstructor.objects.create(nome="Docente Solo")

        url = reverse("anagrafica:formazione_istruttori_list")
        section = self._docenti_table_section(self.client.get(url, {"azienda": str(az.pk)}).content.decode())
        self.assertIn(dentro.nome, section)
        self.assertNotIn(fuori.nome, section)

        section = self._docenti_table_section(self.client.get(url, {"azienda": "NESSUNA"}).content.decode())
        self.assertIn(fuori.nome, section)
        self.assertNotIn(dentro.nome, section)

    def test_elenco_docenti_trova_per_nome_azienda(self):
        az = TrainingProvider.objects.create(nome="Beta Academy")
        TrainingInstructor.objects.create(nome="Docente Beta", azienda=az)
        body = self.client.get(
            reverse("anagrafica:formazione_istruttori_list"), {"q": "Beta Acad"},
        ).content.decode()
        self.assertIn("Docente Beta", body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaDocenteTests(TestCase):
    """La scheda risponde a «cosa ha svolto questo docente»."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-sd", "su-sd@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso()
        self.istr = TrainingInstructor.objects.create(nome="Docente Titolare")
        self.altro = TrainingInstructor.objects.create(nome="Docente Ospite")

    def test_conta_sessioni_da_titolare_e_da_lezione_senza_duplicare(self):
        titolare = _sessione(self.corso, "S-1", date(2026, 3, 2), docente=self.istr)
        # Sessione di un altro docente in cui però tiene una lezione: conta.
        ospitata = _sessione(self.corso, "S-2", date(2026, 4, 2), docente=self.altro)
        TrainingLesson.objects.create(
            sessione=ospitata, numero=1, data=date(2026, 4, 2),
            ora_inizio=time(9, 0), ora_fine=time(13, 0),
            argomento="Modulo pratico", docente=self.istr,
        )
        # Due lezioni nella propria sessione non devono farla contare due volte.
        for n in (1, 2):
            TrainingLesson.objects.create(
                sessione=titolare, numero=n, data=date(2026, 3, 2),
                ora_inizio=time(9, 0), ora_fine=time(11, 0),
                argomento=f"Modulo {n}", docente=self.istr,
            )

        resp = self.client.get(
            reverse("anagrafica:formazione_istruttore_detail", args=[self.istr.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["sessioni"]), 2)
        self.assertEqual(resp.context["corsi_distinti"], 1)
        # 2 lezioni da 2h nella propria sessione + 4h nella sessione ospitata.
        self.assertEqual(resp.context["ore_erogate"], 8.0)

    def test_scheda_senza_sessioni_resta_leggibile(self):
        resp = self.client.get(
            reverse("anagrafica:formazione_istruttore_detail", args=[self.altro.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nessun corso svolto")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RicercaDocentiTests(TestCase):
    """La ricerca globale include docenti, aziende e i corsi che hanno svolto."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-rd", "su-rd@test.local", "x")
        self.client.force_login(self.su)
        self.az = TrainingProvider.objects.create(nome="Gamma Formazione", partita_iva="99887766554")
        self.istr = TrainingInstructor.objects.create(nome="Zanetti Paolo", azienda=self.az)
        self.corso = _corso(codice="C-RIC", titolo="Antincendio")
        self.sess = _sessione(self.corso, "S-RIC-1", date(2026, 5, 5), docente=self.istr)

    def _cerca(self, q):
        resp = self.client.get(reverse("anagrafica:formazione_ricerca"), {"q": q})
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_docente_trovato_per_nome_con_i_corsi_svolti(self):
        resp = self._cerca("Zanetti")
        trovati = resp.context["risultati"]["istruttori"]
        self.assertEqual([i.pk for i in trovati], [self.istr.pk])
        self.assertEqual([s.pk for s in trovati[0].sessioni.all()], [self.sess.pk])
        self.assertContains(resp, "S-RIC-1")

    def test_docente_trovato_per_nome_azienda(self):
        resp = self._cerca("Gamma")
        self.assertIn(self.istr.pk, [i.pk for i in resp.context["risultati"]["istruttori"]])
        self.assertIn(self.az.pk, [a.pk for a in resp.context["risultati"]["aziende"]])

    def test_sessione_trovata_per_nome_docente(self):
        resp = self._cerca("Zanetti")
        self.assertIn(self.sess.pk, [s.pk for s in resp.context["risultati"]["sessioni"]])

    def test_tendina_suggerimenti_mostra_i_docenti(self):
        resp = self.client.get(
            reverse("anagrafica:formazione_ricerca"),
            {"q": "Zanetti", "suggest": "1"},
            headers={"hx-request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Docenti")
        self.assertContains(resp, "Zanetti Paolo")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LibrettoPeriodoTests(TestCase):
    """Lo storico del libretto si ritaglia su un intervallo di date."""

    LEGACY_ID = 4242

    def setUp(self):
        self.su = User.objects.create_superuser("su-lb", "su-lb@test.local", "x")
        self.client.force_login(self.su)
        corso = _corso(codice="C-LIB", titolo="Primo soccorso")
        for anno, ore in ((2024, 4), (2025, 8), (2026, 12)):
            TrainingEmployeeRecord.objects.create(
                legacy_anagrafica_id=self.LEGACY_ID,
                corso=corso,
                course_title_snapshot=f"Primo soccorso {anno}",
                course_code_snapshot="C-LIB",
                data_completamento=date(anno, 6, 15),
                ore_frequentate=ore,
                idoneo=True,
            )

    def _get(self, **params):
        with patch("anagrafica.views.ensure_anagrafica_schema"), \
             patch("anagrafica.views.fetch_anagrafica_rows", return_value=FAKE_DIP):
            resp = self.client.get(
                reverse("anagrafica:dipendente_libretto_formativo", args=[self.LEGACY_ID]),
                params,
            )
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_senza_periodo_lo_storico_e_completo(self):
        resp = self._get()
        self.assertEqual(len(resp.context["record_storici"]), 3)
        self.assertFalse(resp.context["periodo_attivo"])
        self.assertEqual(resp.context["totale_record"], 3)

    def test_intervallo_restringe_lo_storico_e_ricalcola_le_ore(self):
        resp = self._get(dal="2025-01-01", al="2025-12-31")
        self.assertEqual(len(resp.context["record_storici"]), 1)
        self.assertEqual(resp.context["ore_totali"], 8)
        self.assertTrue(resp.context["periodo_attivo"])
        # Il totale complessivo resta visibile: dice che l'estratto è parziale.
        self.assertEqual(resp.context["totale_record"], 3)

    def test_solo_dal_o_solo_al(self):
        self.assertEqual(len(self._get(dal="2025-01-01").context["record_storici"]), 2)
        self.assertEqual(len(self._get(al="2024-12-31").context["record_storici"]), 1)

    def test_intervallo_invertito_viene_raddrizzato(self):
        resp = self._get(dal="2025-12-31", al="2025-01-01")
        self.assertEqual(resp.context["dal"], date(2025, 1, 1))
        self.assertEqual(resp.context["al"], date(2025, 12, 31))
        self.assertEqual(len(resp.context["record_storici"]), 1)

    def test_data_illeggibile_vale_come_assente(self):
        resp = self._get(dal="non-una-data")
        self.assertIsNone(resp.context["dal"])
        self.assertEqual(len(resp.context["record_storici"]), 3)

    def test_gli_obblighi_non_sono_filtrati_dal_periodo(self):
        """Sono lo stato di oggi: un intervallo non li rende parziali."""
        resp = self._get(dal="2025-01-01", al="2025-12-31")
        self.assertContains(resp, "stato di oggi, non filtrato")

    def test_il_link_pdf_porta_con_se_il_periodo(self):
        resp = self._get(dal="2025-01-01", al="2025-12-31")
        self.assertContains(resp, "formato=pdf&amp;dal=2025-01-01&amp;al=2025-12-31")

    def test_pdf_filtrato_per_periodo(self):
        from .services.attestato_pdf import build_libretto_pdf_bytes

        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=FAKE_DIP), \
             patch("core.legacy_anagrafica.ensure_anagrafica_schema"):
            completo = build_libretto_pdf_bytes(self.LEGACY_ID)
            parziale = build_libretto_pdf_bytes(
                self.LEGACY_ID, dal=date(2025, 1, 1), al=date(2025, 12, 31),
            )
        self.assertTrue(completo.startswith(b"%PDF"))
        self.assertTrue(parziale.startswith(b"%PDF"))
        # L'estratto parziale ha meno righe da stampare del libretto completo.
        self.assertLess(len(parziale), len(completo))


class EnteComeDocenteTests(TestCase):
    """Sessioni/lezioni la cui competenza formativa è dell'ente, senza un
    docente nominativo noto (tipicamente webinar erogati dal provider)."""

    def setUp(self):
        self.corso = _corso(codice="C-ENTE")
        self.az = TrainingProvider.objects.create(nome="Webinar Academy")

    def test_form_sessione_accetta_ente_come_docente(self):
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "REMOTO",
            "data_inizio": "2026-09-01", "data_fine": "2026-09-01",
            "docente_ente": self.az.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        sessione = form.save()
        self.assertIsNone(sessione.docente_id)
        self.assertEqual(sessione.docente_ente_id, self.az.pk)
        # Lo snapshot testuale usato da PDF/export prende il nome dell'ente.
        self.assertEqual(sessione.docente_nome, "Webinar Academy")

    def test_form_sessione_rifiuta_docente_e_ente_insieme(self):
        istr = TrainingInstructor.objects.create(nome="Rossi")
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "REMOTO",
            "data_inizio": "2026-09-01", "data_fine": "2026-09-01",
            "docente": istr.pk, "docente_ente": self.az.pk,
        })
        self.assertFalse(form.is_valid())

    def test_form_lezione_accetta_ente_come_docente(self):
        sessione = _sessione(self.corso, "S-ENTE", date(2026, 9, 1))
        form = TrainingLessonForm(data={
            "numero": 1, "data": "2026-09-01",
            "ora_inizio": "09:00", "ora_fine": "13:00", "pausa_minuti": 0,
            "argomento": "Introduzione", "docente_ente": self.az.pk,
        }, sessione=sessione)
        self.assertTrue(form.is_valid(), form.errors)
        lezione = form.save(commit=False)
        lezione.sessione = sessione
        lezione.save()
        self.assertIsNone(lezione.docente_id)
        self.assertEqual(lezione.docente_ente_id, self.az.pk)
        self.assertEqual(lezione.docente_nome, "Webinar Academy")

    def test_vincolo_db_non_ammette_docente_e_ente_insieme(self):
        sessione = _sessione(self.corso, "S-VINC", date(2026, 9, 1))
        istr = TrainingInstructor.objects.create(nome="Verdi")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingLesson.objects.create(
                sessione=sessione, numero=1, data=date(2026, 9, 1),
                ora_inizio=time(9, 0), ora_fine=time(13, 0),
                argomento="X", docente=istr, docente_ente=self.az,
            )
