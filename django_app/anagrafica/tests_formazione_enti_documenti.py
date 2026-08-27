"""Scheda ente, report «chi ci ha formato», documenti, argomenti, espansione.

Il secondo giro di migliorie al modulo formazione:
* l'ente di formazione ha una scheda che risponde a «cosa ci ha erogato»,
  con le ore attribuite alla giornata e non alla sessione;
* il report d'insieme mette in fila i fornitori nel periodo;
* accreditamento, contratto, CV e attestato del formatore diventano documenti
  in archivio privato invece che testo;
* la ricerca globale entra nel programma didattico;
* la tabella corsi si apre in riga su edizioni e giornate.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser durante i test.
"""
import tempfile
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingCourseArgomento,
    TrainingInstructor,
    TrainingLesson,
    TrainingPlan,
    TrainingProvider,
    TrainingProviderDocument,
    TrainingSession,
    TrainingSessionArgomento,
)

User = get_user_model()

PDF = b"%PDF-1.4\n%%EOF\n"


def _corso(codice="C-ENTE", titolo="Sicurezza generale"):
    piano, _ = TrainingPlan.objects.get_or_create(
        codice="P-ENTE", defaults={"nome": "Piano enti"},
    )
    return TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=titolo, durata_ore_teorica=4,
    )


def _sessione(corso, codice, data, docente=None, stato="COMPLETATA"):
    return TrainingSession.objects.create(
        corso=corso, codice_sessione=codice, stato=stato,
        data_inizio=data, data_fine=data, docente=docente,
    )


def _lezione(sessione, numero, ore, docente=None, data=None):
    return TrainingLesson.objects.create(
        sessione=sessione, numero=numero, data=data or sessione.data_inizio,
        ora_inizio=time(9, 0), ora_fine=time(9 + ore, 0),
        argomento=f"Modulo {numero}", docente=docente,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaEnteTests(TestCase):
    """Le ore si attribuiscono alla giornata, non alla sessione."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-ente", "su-ente@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso()
        self.alfa = TrainingProvider.objects.create(nome="Alfa Formazione")
        self.beta = TrainingProvider.objects.create(nome="Beta Academy")
        self.doc_alfa = TrainingInstructor.objects.create(nome="Docente Alfa", azienda=self.alfa)
        self.doc_beta = TrainingInstructor.objects.create(nome="Docente Beta", azienda=self.beta)

        # Un'edizione con due enti: titolare Alfa, una giornata tenuta da Beta.
        self.sess = _sessione(self.corso, "S-ENTE-1", date(2026, 5, 4), docente=self.doc_alfa)
        _lezione(self.sess, 1, 2)                          # senza docente → al titolare
        _lezione(self.sess, 2, 4, docente=self.doc_beta)   # → a Beta

    def _scheda(self, ente, **params):
        resp = self.client.get(
            reverse("anagrafica:formazione_azienda_detail", args=[ente.pk]), params
        )
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_ore_attribuite_al_docente_della_giornata(self):
        alfa = self._scheda(self.alfa)
        beta = self._scheda(self.beta)
        self.assertEqual(alfa.context["ore"], 2.0)
        self.assertEqual(beta.context["ore"], 4.0)
        # L'edizione compare a entrambi: entrambi ci hanno insegnato.
        self.assertEqual(len(alfa.context["sessioni"]), 1)
        self.assertEqual(len(beta.context["sessioni"]), 1)

    def test_periodo_ritaglia_le_erogazioni(self):
        _sessione(self.corso, "S-ENTE-2", date(2024, 3, 1), docente=self.doc_alfa)
        completo = self._scheda(self.alfa)
        self.assertEqual(len(completo.context["sessioni"]), 2)
        parziale = self._scheda(self.alfa, dal="2026-01-01")
        self.assertEqual(len(parziale.context["sessioni"]), 1)
        self.assertTrue(parziale.context["periodo_attivo"])

    def test_scheda_elenca_i_docenti_dell_ente(self):
        resp = self._scheda(self.alfa)
        self.assertEqual([d.pk for d in resp.context["docenti"]], [self.doc_alfa.pk])

    def test_ricerca_porta_alla_scheda_dell_ente(self):
        """Cercare l'ente deve portare a «cosa ci ha erogato», non a un filtro."""
        resp = self.client.get(reverse("anagrafica:formazione_ricerca"), {"q": "Alfa Formazione"})
        self.assertContains(
            resp, reverse("anagrafica:formazione_azienda_detail", args=[self.alfa.pk])
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportEntiTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-rep", "su-rep@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="C-REP")
        self.attivo = TrainingProvider.objects.create(nome="Ente Attivo")
        self.fermo = TrainingProvider.objects.create(nome="Ente Fermo")
        docente = TrainingInstructor.objects.create(nome="Doc Attivo", azienda=self.attivo)
        sess = _sessione(self.corso, "S-REP-1", date(2026, 2, 10), docente=docente)
        _lezione(sess, 1, 8)

    def _report(self, **params):
        resp = self.client.get(reverse("anagrafica:formazione_enti_report"), params)
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_riga_per_ogni_ente_anche_a_zero(self):
        righe = self._report().context["righe"]
        per_nome = {r["ente"].nome: r for r in righe}
        self.assertEqual(per_nome["Ente Attivo"]["n_sessioni"], 1)
        self.assertEqual(per_nome["Ente Attivo"]["ore"], 8.0)
        # Il fornitore che non si usa più resta in elenco: è un'informazione.
        self.assertEqual(per_nome["Ente Fermo"]["n_sessioni"], 0)
        self.assertEqual(per_nome["Ente Fermo"]["ore"], 0.0)

    def test_totali_e_periodo(self):
        resp = self._report()
        self.assertEqual(resp.context["tot_sessioni"], 1)
        self.assertEqual(resp.context["enti_attivi"], 1)
        vuoto = self._report(dal="2027-01-01")
        self.assertEqual(vuoto.context["tot_sessioni"], 0)
        self.assertEqual(vuoto.context["enti_attivi"], 0)

    def test_export_enti_produce_le_righe(self):
        from anagrafica.exports import EXPORT_SPECS

        spec = EXPORT_SPECS["formazione_enti"]
        request = self.client.get(reverse("anagrafica:formazione_enti_report")).wsgi_request
        righe = spec.dataset(request, "full")
        self.assertEqual({r["ente"] for r in righe}, {"Ente Attivo", "Ente Fermo"})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DocumentiEnteTests(TestCase):
    """Accreditamento e qualifica del docente: carte, non testo libero."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-doc", "su-doc@test.local", "x")
        self.client.force_login(self.su)
        self.az = TrainingProvider.objects.create(nome="Ente con carte")
        self.istr = TrainingInstructor.objects.create(nome="Docente con CV", azienda=self.az)

    def _upload(self, url, filename="accreditamento.pdf", contenuto=PDF, **extra):
        dati = {"tipo": "ACCREDITAMENTO", "descrizione": "Accreditamento regionale"}
        dati.update(extra)
        dati["file"] = SimpleUploadedFile(filename, contenuto, content_type="application/pdf")
        return self.client.post(url, dati)

    def test_documento_dell_ente_con_scadenza(self):
        url = reverse("anagrafica:formazione_azienda_documento_add", args=[self.az.pk])
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            resp = self._upload(url, data_scadenza="2027-01-31")
            self.assertEqual(resp.status_code, 302)
            doc = TrainingProviderDocument.objects.get()
            self.assertEqual(doc.azienda_id, self.az.pk)
            self.assertIsNone(doc.docente_id)
            self.assertEqual(doc.data_scadenza, date(2027, 1, 31))
            self.assertEqual(doc.tipo_mime, "application/pdf")

            scarica = self.client.get(
                reverse("anagrafica:formazione_ente_documento_download", args=[doc.pk])
            )
            self.assertEqual(scarica.status_code, 200)

    def test_documento_del_docente(self):
        url = reverse("anagrafica:formazione_istruttore_documento_add", args=[self.istr.pk])
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            self._upload(url, filename="cv.pdf", tipo="CV")
            doc = TrainingProviderDocument.objects.get()
            self.assertEqual(doc.docente_id, self.istr.pk)
            self.assertIsNone(doc.azienda_id)

    def test_formato_non_consentito_rifiutato(self):
        url = reverse("anagrafica:formazione_azienda_documento_add", args=[self.az.pk])
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            resp = self._upload(url, filename="malware.exe", contenuto=b"MZ\x90\x00")
            self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrainingProviderDocument.objects.exists())

    def test_eliminazione(self):
        url = reverse("anagrafica:formazione_azienda_documento_add", args=[self.az.pk])
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            self._upload(url)
            doc = TrainingProviderDocument.objects.get()
            resp = self.client.post(
                reverse("anagrafica:formazione_ente_documento_delete", args=[doc.pk])
            )
            self.assertEqual(resp.status_code, 302)
        self.assertFalse(TrainingProviderDocument.objects.exists())

    def test_stato_scadenza(self):
        doc = TrainingProviderDocument(data_scadenza=date(2020, 1, 1))
        self.assertEqual(doc.stato_scadenza, "SCADUTO")
        self.assertEqual(TrainingProviderDocument().stato_scadenza, "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RicercaArgomentiTests(TestCase):
    """Il contenuto insegnato non sta nel titolo del corso."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-arg", "su-arg@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="C-ARG", titolo="Formazione specifica rischio alto")
        self.sess = _sessione(self.corso, "S-ARG-1", date(2026, 6, 1))
        TrainingCourseArgomento.objects.create(
            corso=self.corso, ordine=1, argomento="Spazi confinati",
            riferimento="DPR 177/2011",
        )
        TrainingSessionArgomento.objects.create(
            sessione=self.sess, ordine=1, argomento="Spazi confinati: procedure di accesso",
        )

    def test_trova_argomento_previsto_ed_erogato(self):
        resp = self.client.get(reverse("anagrafica:formazione_ricerca"), {"q": "spazi confinati"})
        argomenti = resp.context["risultati"]["argomenti"]
        self.assertEqual(len(argomenti), 2)
        # L'erogato (edizione) viene prima del previsto (corso).
        self.assertTrue(argomenti[0]["erogato"])
        self.assertFalse(argomenti[1]["erogato"])
        self.assertContains(resp, "Argomenti del programma")

    def test_trova_per_riferimento_normativo(self):
        resp = self.client.get(reverse("anagrafica:formazione_ricerca"), {"q": "DPR 177"})
        self.assertEqual(len(resp.context["risultati"]["argomenti"]), 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class EspansioneTabellaCorsiTests(TestCase):
    """Corso → edizioni → giornate, dentro la riga."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-esp", "su-esp@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="C-ESP")
        self.sess = _sessione(self.corso, "S-ESP-1", date(2026, 4, 6))
        _lezione(self.sess, 1, 4)
        _lezione(self.sess, 2, 3)

    def test_la_riga_del_corso_ha_il_pulsante_e_la_riga_di_dettaglio(self):
        resp = self.client.get(reverse("anagrafica:formazione_corsi_list"))
        self.assertContains(resp, f'id="fmd-exp-btn-{self.corso.pk}"')
        # La riga di dettaglio deve restare fuori da filtro/sort dell'enhancer.
        self.assertContains(resp, f'id="fmd-exp-row-{self.corso.pk}"')
        self.assertContains(resp, 'data-fm-detail-row="1"')

    def test_frammento_edizioni(self):
        resp = self.client.get(
            reverse("anagrafica:formazione_corso_espansione", args=[self.corso.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "S-ESP-1")
        self.assertContains(resp, "2 giornate")
        self.assertEqual(resp.context["sessioni"][0].n_lezioni, 2)

    def test_frammento_giornate(self):
        resp = self.client.get(
            reverse("anagrafica:formazione_sessione_espansione", args=[self.sess.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["lezioni"]), 2)
        self.assertContains(resp, "Modulo 1")

    def test_corso_senza_edizioni(self):
        vuoto = _corso(codice="C-VUOTO", titolo="Mai erogato")
        resp = self.client.get(
            reverse("anagrafica:formazione_corso_espansione", args=[vuoto.pk])
        )
        self.assertContains(resp, "Nessuna edizione programmata")
