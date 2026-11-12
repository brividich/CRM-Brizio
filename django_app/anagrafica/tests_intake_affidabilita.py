"""Affidabilità delle acquisizioni da cartella (fogli firme e referti).

Le prove simulano i guasti veri di un lavoro periodico su una share: il worker
ucciso fra l'archiviazione e lo spostamento, la cache svuotata, due passaggi in
parallelo (pulsante «Prova adesso» e giro automatico), un arretrato più lungo del
budget. Dati sintetici: nessun nome, nessun file reale.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import TrainingScanIntakeConfig, TrainingScanLog
from .models_sorveglianza import RefertoIntakeConfig, RefertoIntakeRiga
from .services import intake_scansioni, referti_intake
from .tests_formazione_intake_scansioni import _scansione_firmata, _scenario

User = get_user_model()


class _Cartelle(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._archivio = tempfile.mkdtemp(prefix="pn-archivio-")
        cls._override = override_settings(ANAGRAFICA_PRIVATE_ROOT=cls._archivio)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._archivio, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.cartella = Path(tempfile.mkdtemp(prefix="pn-intake-"))
        self.addCleanup(shutil.rmtree, self.cartella, True)
        attesa = mock.patch.object(intake_scansioni, "ATTESA_STABILITA_SECONDI", 0)
        attesa.start()
        self.addCleanup(attesa.stop)
        attesa_r = mock.patch.object(referti_intake, "ATTESA_STABILITA_SECONDI", 0)
        attesa_r.start()
        self.addCleanup(attesa_r.stop)


class FogliFirmeRipresaTest(_Cartelle):
    def setUp(self):
        super().setUp()
        from .services.foglio_firme import emetti_foglio_firme

        self.utente = User.objects.create_superuser("aff_op", "a@example.invalid", "pwd12345")
        _corso, _sess, self.lezione = _scenario(codice="AFF-01")
        self.config = TrainingScanIntakeConfig.load()
        self.config.attiva = True
        self.config.cartella = str(self.cartella)
        self.config.conferma_automatica = True
        self.config.save()
        foglio, pdf = emetti_foglio_firme(self.lezione, user=self.utente)
        (self.cartella / "scan_aff.png").write_bytes(_scansione_firmata(pdf, foglio.geometria, [1, 2]))

    def test_passaggio_interrotto_prima_dello_spostamento_non_riarchivia(self):
        """Worker ucciso dopo archivio e presenze: il giro dopo sposta e basta."""
        from .services import formazione_presenze

        with mock.patch.object(intake_scansioni, "_sposta", return_value=""):
            primo = intake_scansioni.elabora_cartella()
        self.assertEqual(primo["letti"], 1)
        self.assertTrue((self.cartella / "scan_aff.png").exists(), "simula lo spostamento mai avvenuto")

        with mock.patch.object(formazione_presenze, "applica_firme_lezione") as applica:
            secondo = intake_scansioni.elabora_cartella()

        applica.assert_not_called()
        self.assertEqual(secondo["esaminati"], 0)
        self.assertEqual(secondo["gia_elaborati"], 1)
        self.assertEqual(TrainingScanLog.objects.count(), 1, "nessuna seconda riga né seconda copia")
        self.assertTrue((self.cartella / "elaborati" / "scan_aff.png").exists())
        self.assertIn("già elaborati", secondo["riepilogo"])

    def test_la_dedup_regge_anche_a_cache_svuotata(self):
        with mock.patch.object(intake_scansioni, "_sposta", return_value=""):
            intake_scansioni.elabora_cartella()
        cache.clear()

        secondo = intake_scansioni.elabora_cartella()
        self.assertEqual(secondo["gia_elaborati"], 1)
        self.assertEqual(TrainingScanLog.objects.count(), 1)

    def test_senza_spostamento_il_file_non_si_rilegge_a_ogni_giro(self):
        self.config.sposta_elaborati = False
        self.config.save()
        intake_scansioni.elabora_cartella()
        secondo = intake_scansioni.elabora_cartella()
        self.assertEqual(secondo["esaminati"], 0)
        self.assertEqual(TrainingScanLog.objects.count(), 1)

    def test_due_passaggi_sulla_stessa_cartella_non_si_sovrappongono(self):
        self.config.ultimo_esito = "precedente"
        self.config.save()
        with intake_scansioni.lock_cartella("scansioni_formazione", str(self.cartella)) as preso:
            self.assertTrue(preso)
            esito = intake_scansioni.elabora_cartella()
        self.assertTrue(esito.get("in_corso"))
        self.assertEqual(TrainingScanLog.objects.count(), 0)
        self.assertEqual(TrainingScanIntakeConfig.load().ultimo_esito, "precedente")
        # Rilasciato il lock, il passaggio successivo lavora.
        self.assertEqual(intake_scansioni.elabora_cartella()["letti"], 1)

    def test_budget_esaurito_rimanda_al_giro_dopo(self):
        with mock.patch.object(intake_scansioni, "BUDGET_SECONDI", -1):
            esito = intake_scansioni.elabora_cartella()
        self.assertEqual(esito["rimandati"], 1)
        self.assertEqual(esito["esaminati"], 0)
        self.assertTrue((self.cartella / "scan_aff.png").exists())
        self.assertIn("rimandati al prossimo giro", esito["riepilogo"])

    def test_una_sola_attesa_di_stabilita_per_lotto(self):
        for i in range(3):
            (self.cartella / f"estraneo_{i}.png").write_bytes(b"x" * (10 + i))
        with mock.patch.object(intake_scansioni, "ATTESA_STABILITA_SECONDI", 2.0), \
                mock.patch.object(intake_scansioni.time, "sleep") as dorme, \
                mock.patch.object(intake_scansioni, "_elabora_file"):
            intake_scansioni.elabora_cartella()
        dorme.assert_called_once_with(2.0)

    def test_file_che_cambia_durante_l_attesa_resta_li(self):
        percorso = self.cartella / "scan_aff.png"

        def cresce(_secondi):
            with percorso.open("ab") as fh:
                fh.write(b"altro")

        with mock.patch.object(intake_scansioni, "ATTESA_STABILITA_SECONDI", 1.0), \
                mock.patch.object(intake_scansioni.time, "sleep", side_effect=cresce):
            esito = intake_scansioni.elabora_cartella()
        self.assertEqual(esito["esaminati"], 0)
        self.assertTrue(percorso.exists())


class RefertiPerPaginaTest(_Cartelle):
    """Dedup per pagina: un PDF letto a metà non perde le pagine mancanti."""

    def _finto_ocr(self, pagine: int):
        """OCR e analisi sostituiti: ogni pagina è un certificato a sé."""
        def elabora_testo(testo, nome_file, pagina, *, config, origine, utente=None,
                          percorso="", dimensione=0, sha=""):
            return RefertoIntakeRiga.objects.create(
                nome_file=nome_file, percorso=percorso, dimensione=dimensione, sha256=sha,
                pagina=pagina + 1, origine=origine, esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE,
            )

        return [
            mock.patch("anagrafica.services.referti_ocr.conta_pagine", return_value=pagine),
            mock.patch("anagrafica.services.referti_ocr.testo_pagina",
                       side_effect=lambda c, p, cfg: f"pagina {p}"),
            mock.patch.object(referti_intake, "_raggruppa_pagine", side_effect=lambda testi: testi),
            mock.patch.object(referti_intake, "_elabora_testo", side_effect=elabora_testo),
        ]

    def _con(self, patches, fn):
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def test_pdf_interrotto_si_completa_senza_doppioni(self):
        contenuto = b"%PDF-sintetico-tre-pagine"
        sha = referti_intake._impronta(contenuto)
        # Passaggio precedente morto dopo la prima pagina.
        RefertoIntakeRiga.objects.create(nome_file="r.pdf", percorso="sorveglianza/x.pdf",
                                         sha256=sha, pagina=1, origine="CARTELLA")

        righe = self._con(self._finto_ocr(3), lambda: referti_intake.elabora_contenuto(
            contenuto, "r.pdf", origine="CARTELLA"))

        self.assertEqual(sorted(r.pagina for r in righe), [2, 3])
        self.assertEqual(RefertoIntakeRiga.objects.filter(sha256=sha).count(), 3)
        self.assertTrue(all(r.percorso == "sorveglianza/x.pdf" for r in righe), "non si riarchivia")
        self.assertTrue(referti_intake._file_completo(sha))

        # Una terza lettura non aggiunge niente.
        again = self._con(self._finto_ocr(3), lambda: referti_intake.elabora_contenuto(
            contenuto, "r.pdf", origine="CARTELLA"))
        self.assertEqual(again, [])
        self.assertEqual(RefertoIntakeRiga.objects.filter(sha256=sha).count(), 3)

    def test_la_cache_da_sola_non_basta_per_dire_completo(self):
        sha = referti_intake._impronta(b"qualcosa")
        referti_intake._segna_completo(sha)
        self.assertFalse(referti_intake._file_completo(sha), "senza righe in coda non è completo")

    def _config_cartella(self):
        config = RefertoIntakeConfig.load()
        config.attiva = True
        config.cartella = str(self.cartella)
        config.save()
        return config

    def test_file_letto_a_meta_resta_nella_cartella(self):
        self._config_cartella()
        (self.cartella / "pila.pdf").write_bytes(b"%PDF-pila")
        # La lettura si interrompe: righe parziali, file non marcato completo.
        with mock.patch.object(referti_intake, "elabora_contenuto", return_value=[]):
            esito = referti_intake.elabora_cartella()
        self.assertTrue((self.cartella / "pila.pdf").exists())
        self.assertTrue(any("lettura incompleta" in d for d in esito["dettagli"]))

    def test_file_completo_va_in_elaborati(self):
        self._config_cartella()
        (self.cartella / "uno.pdf").write_bytes(b"%PDF-uno")
        esito = self._con(self._finto_ocr(2), referti_intake.elabora_cartella)
        self.assertEqual(esito["in_coda"], 2)
        self.assertFalse((self.cartella / "uno.pdf").exists())
        self.assertTrue((self.cartella / "elaborati" / "uno.pdf").exists())

    def test_lock_condiviso_col_giro_automatico(self):
        config = self._config_cartella()
        (self.cartella / "uno.pdf").write_bytes(b"%PDF-uno")
        with intake_scansioni.lock_cartella("referti_sanitari", config.cartella):
            esito = referti_intake.elabora_cartella()
        self.assertTrue(esito.get("in_corso"))
        self.assertTrue((self.cartella / "uno.pdf").exists())

    def test_budget_esaurito_lascia_i_file_al_giro_dopo(self):
        self._config_cartella()
        (self.cartella / "a.pdf").write_bytes(b"%PDF-a")
        (self.cartella / "b.pdf").write_bytes(b"%PDF-b")
        with mock.patch.object(referti_intake, "BUDGET_SECONDI", -1):
            esito = referti_intake.elabora_cartella()
        self.assertEqual(esito["rimandati"], 2)
        self.assertTrue((self.cartella / "a.pdf").exists())

    def test_nei_log_niente_nome_o_percorso_del_file(self):
        """Dati sanitari: nei log solo impronta abbreviata e pagina."""
        nome = "Cognome Nome visita.pdf"
        with mock.patch("anagrafica.services.referti_intake.shutil.move",
                        side_effect=OSError(2, "non trovato", str(self.cartella / nome))), \
                self.assertLogs("anagrafica.services.referti_intake", level="WARNING") as registro:
            referti_intake._sposta(self.cartella / nome, self.cartella, "elaborati", "ab" * 32)
        testo = "\n".join(registro.output)
        self.assertNotIn("Cognome", testo)
        self.assertIn("abababababab", testo)

        with mock.patch("anagrafica.services.referti_ocr.conta_pagine", return_value=1), \
                mock.patch("anagrafica.services.referti_ocr.testo_pagina", side_effect=RuntimeError(nome)), \
                self.assertLogs("anagrafica.services.referti_intake", level="ERROR") as registro:
            referti_intake.elabora_contenuto(b"%PDF-log", nome, origine="CARTELLA")
        self.assertNotIn("Cognome", "\n".join(registro.output))


class PulsantiProvaTest(_Cartelle):
    def setUp(self):
        super().setUp()
        self.utente = User.objects.create_superuser("aff_admin", "b@example.invalid", "pwd12345")
        self.client.force_login(self.utente)

    def test_prova_referti_accoda_e_mostra_l_ultimo_esito(self):
        config = RefertoIntakeConfig.load()
        config.attiva = True
        config.cartella = str(self.cartella)
        config.ultimo_esito = "Nessun file da elaborare."
        from django.utils import timezone

        config.ultima_esecuzione = timezone.now()
        config.save()
        (self.cartella / "uno.pdf").write_bytes(b"%PDF-uno")

        with mock.patch("django_q.tasks.async_task") as accoda:
            r = self.client.post(reverse("anagrafica:referti_impostazioni"), {"azione": "prova"}, follow=True)

        accoda.assert_called_once()
        self.assertEqual(accoda.call_args[0][0], "anagrafica.tasks.run_intake_referti_sanitari")
        self.assertContains(r, "Lettura avviata")
        self.assertContains(r, "Ultimo passaggio")
        self.assertEqual(RefertoIntakeRiga.objects.count(), 0, "niente OCR nella richiesta web")
        self.assertTrue((self.cartella / "uno.pdf").exists())

    def test_prova_referti_spenta_non_accoda(self):
        with mock.patch("django_q.tasks.async_task") as accoda:
            r = self.client.post(reverse("anagrafica:referti_impostazioni"), {"azione": "prova"}, follow=True)
        accoda.assert_not_called()
        self.assertContains(r, "Attiva l")

    def test_accodamento_fallito_lo_dice(self):
        config = TrainingScanIntakeConfig.load()
        config.attiva = True
        config.cartella = str(self.cartella)
        config.save()
        with mock.patch("django_q.tasks.async_task", side_effect=RuntimeError("broker giù")):
            r = self.client.post(reverse("anagrafica:formazione_scansioni_impostazioni"),
                                 {"azione": "prova"}, follow=True)
        self.assertContains(r, "Non è stato possibile avviare la lettura")
