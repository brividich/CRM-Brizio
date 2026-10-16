"""Analisi modulo HR, seconda parte (16/10/2026). Dati sintetici.

- report di prova mansione → catalogo (sola lettura);
- conservazione dei dati: eliminazione documenti e anonimizzazione candidati con conferma;
- «La mia scheda»: solo i dati del dipendente collegato.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    DipendenteAnagraficaAziendale,
    DocumentoDipendente,
    Mansione,
    SaldoCedolino,
    ImportazioneCedolini,
    TipoVisitaMedica,
    VisitaMedica,
)
from anagrafica.tests import _ensure_anagrafica_table
from core.legacy_models import AnagraficaDipendente

User = get_user_model()


def _utente(username, superuser=False):
    from core.models import UserOnboarding

    if superuser:
        user = User.objects.create_superuser(username, f"{username}@example.invalid", "x")
    else:
        user = User.objects.create_user(username, password="x")
    UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
    return user


class ReportMansioniCatalogoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def test_esiti_e_nessuna_scrittura(self):
        from anagrafica.management.commands.report_mansioni_catalogo import analizza

        Mansione.objects.create(nome="Saldatore")
        Mansione.objects.create(nome="Verniciatore")
        for i, testo in enumerate(("Saldatore", "saldatore ", "Vernicia-tore", "Pittore", "Pittore")):
            AnagraficaDipendente.objects.create(nome=f"N{i}", cognome=f"Prova{i}", mansione=testo)
        esiti = {r["mansione"]: (r["esito"], r["persone"]) for r in analizza()}
        self.assertEqual(esiti["Saldatore"], ("esatta", 1))
        self.assertEqual(esiti["saldatore"], ("per nome", 1))
        self.assertEqual(esiti["Vernicia-tore"], ("simile", 1))
        self.assertEqual(esiti["Pittore"], ("assente", 2))
        prima = Mansione.objects.count()
        out = StringIO()
        call_command("report_mansioni_catalogo", stdout=out)
        self.assertIn("sola lettura", out.getvalue())
        self.assertEqual(Mansione.objects.count(), prima)


class RetentionConfermaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def setUp(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=11, data_cessazione=date(1980, 1, 1))
        self.vecchio = self._doc(11)
        self.attivo = self._doc(12)
        from anagrafica.models_recruiting import Candidato

        self.cand = Candidato.objects.create(cognome="Bianchi", nome="Ugo", email="ugo@example.invalid",
                                             cellulare="333", note="note", stato=Candidato.STATO_SCARTATO)
        Candidato.objects.filter(pk=self.cand.pk).update(updated_at=timezone.now() - timedelta(days=900))
        self.recente = Candidato.objects.create(cognome="Verdi", nome="Ada", stato=Candidato.STATO_SCARTATO)

    def _doc(self, legacy_id):
        doc = DocumentoDipendente.objects.create(legacy_anagrafica_id=legacy_id, tipo="ALTRO", nome_originale="x.pdf")
        DocumentoDipendente.objects.filter(pk=doc.pk).update(retention_until=date(2000, 1, 1))
        return doc

    def test_non_admin_403(self):
        self.client.force_login(_utente("rt_utente"))
        with mock.patch("anagrafica.views._is_anagrafica_admin", return_value=False):
            resp = self.client.get(reverse("anagrafica:retention"))
        self.assertEqual(resp.status_code, 403)

    def test_senza_parola_di_conferma_non_cancella(self):
        self.client.force_login(_utente("rt_admin", superuser=True))
        self.client.post(reverse("anagrafica:retention"), {"azione": "documenti", "ids": [self.vecchio.pk], "conferma": "si"})
        self.assertTrue(DocumentoDipendente.objects.filter(pk=self.vecchio.pk).exists())

    def test_elimina_solo_i_documenti_ancora_oltre_la_conservazione(self):
        from core.models import AuditLog

        self.client.force_login(_utente("rt_admin2", superuser=True))
        resp = self.client.get(reverse("anagrafica:retention"))
        self.assertContains(resp, "x.pdf")
        self.client.post(reverse("anagrafica:retention"), {
            "azione": "documenti", "ids": [self.vecchio.pk, self.attivo.pk], "conferma": "ELIMINA"})
        self.assertFalse(DocumentoDipendente.objects.filter(pk=self.vecchio.pk).exists())
        self.assertTrue(DocumentoDipendente.objects.filter(pk=self.attivo.pk).exists())
        self.assertTrue(AuditLog.objects.filter(dettaglio__oggetto="retention_documento").exists())

    def test_anonimizza_solo_i_candidati_scaduti(self):
        from anagrafica.models_recruiting import Candidato
        from anagrafica.services.retention import COGNOME_ANONIMO, candidati_da_rivalutare

        self.client.force_login(_utente("rt_admin3", superuser=True))
        self.client.post(reverse("anagrafica:retention"), {
            "azione": "candidati", "ids": [self.cand.pk, self.recente.pk], "conferma": "elimina"})
        self.cand.refresh_from_db()
        self.assertEqual((self.cand.cognome, self.cand.nome, self.cand.email, self.cand.note),
                         (COGNOME_ANONIMO, "", "", ""))
        self.assertEqual(self.cand.stato, Candidato.STATO_SCARTATO)
        self.assertEqual(Candidato.objects.get(pk=self.recente.pk).cognome, "Verdi")
        self.assertEqual(candidati_da_rivalutare(), 0)


class MiaSchedaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_anagrafica_table()
        super().setUpClass()

    def setUp(self):
        self.io = AnagraficaDipendente.objects.create(nome="Ivo", cognome="Io", reparto="Officina")
        self.altro = AnagraficaDipendente.objects.create(nome="Ada", cognome="Altra", reparto="Officina")
        imp = ImportazioneCedolini.objects.create(data_competenza=date(2026, 9, 30))
        SaldoCedolino.objects.create(importazione=imp, tax_code="X", legacy_anagrafica_id=self.io.id,
                                     data_competenza=date(2026, 9, 30), ferie_residui=Decimal("42.5"))
        SaldoCedolino.objects.create(importazione=imp, tax_code="Y", legacy_anagrafica_id=self.altro.id,
                                     data_competenza=date(2026, 9, 30), ferie_residui=Decimal("99.75"))
        tipo = TipoVisitaMedica.objects.create(nome="Periodica scheda", durata_mesi=12, obbligatoria=True)
        VisitaMedica.objects.create(legacy_anagrafica_id=self.io.id, tipo=tipo,
                                    data_svolgimento=timezone.localdate() - timedelta(days=30),
                                    prescrizioni="PRESCRIZIONE-RISERVATA")
        self.client.force_login(_utente("ms_utente"))

    def _get(self, lid, url=None):
        with mock.patch("anagrafica.views._current_legacy_anagrafica_id", return_value=lid):
            return self.client.get(url or reverse("anagrafica:mia_scheda"))

    def test_non_collegato(self):
        self.assertContains(self._get(None), "Account non collegato")

    def test_solo_i_miei_dati_e_niente_prescrizioni(self):
        resp = self._get(self.io.id)
        self.assertContains(resp, "42,5")
        self.assertNotContains(resp, "99,75")
        self.assertContains(resp, "Periodica scheda")
        self.assertNotContains(resp, "PRESCRIZIONE-RISERVATA")

    def test_attestato_di_un_altro_404_il_mio_pdf(self):
        from anagrafica.models_formazione import TrainingCourse, TrainingEmployeeRecord, TrainingPlan

        piano = TrainingPlan.objects.create(codice="MS", nome="Piano MS")
        corso = TrainingCourse.objects.create(piano=piano, codice="MS-01", titolo="Corso MS",
                                              durata_ore_teorica=Decimal("8.00"), stato="ATTIVO")
        mio = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=self.io.id,
                                                    data_completamento=timezone.localdate())
        suo = TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=self.altro.id,
                                                    data_completamento=timezone.localdate())
        self.assertContains(self._get(self.io.id), "Corso MS")
        with mock.patch("anagrafica.services.attestato_pdf.build_attestato_pdf_bytes", return_value=b"%PDF-1.4"):
            self.assertEqual(self._get(self.io.id, reverse("anagrafica:mio_attestato", args=[suo.pk])).status_code, 404)
            resp = self._get(self.io.id, reverse("anagrafica:mio_attestato", args=[mio.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
