"""Formazione HR — acquisizione dei fogli firme da cartella di rete.

Il banco di prova è il giro che farà davvero la fotocopiatrice: si emette il
foglio, lo si rasterizza come uno scanner, ci si «firma» sopra, **lo si scrive
in una cartella** e si lascia lavorare il portale. Nessun nome di file
concordato, nessuna giornata indicata a mano: il QR dice tutto.

Le prove che contano di più sono quelle sulla **prudenza**, perché è lì che un
automatismo fa danni: un file ancora in scrittura non va toccato, un foglio non
riconosciuto non deve sparire, e soprattutto le presenze **non si registrano da
sole** finché qualcuno non lo decide esplicitamente — e nemmeno allora, se il
foglio ha celle troppo incerte per essere lette.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import date, time
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingScanIntakeConfig,
    TrainingScanLog,
    TrainingSession,
)
from .services.foglio_firme import emetti_foglio_firme
from .services.intake_scansioni import elabora_cartella

User = get_user_model()


def _scenario(codice="IN-01", giorno=date(2026, 6, 9), n_iscritti=4):
    piano, _ = TrainingPlan.objects.get_or_create(codice="IN", defaults={"nome": "Piano IN"})
    corso = TrainingCourse.objects.create(
        piano=piano, codice=codice, titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
    )
    sess = TrainingSession.objects.create(
        corso=corso, codice_sessione=f"{codice}-E1",
        data_inizio=giorno, data_fine=giorno,
    )
    lez = TrainingLesson.objects.create(
        sessione=sess, numero=1, data=giorno,
        ora_inizio=time(9, 0), ora_fine=time(17, 0), argomento="Teoria",
    )
    for i in range(n_iscritti):
        TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=700 + i)
    return corso, sess, lez


def _scansione_firmata(pdf: bytes, geometria: dict, righe: list[int]) -> bytes:
    """Il foglio rasterizzato con uno scarabocchio nelle celle indicate."""
    import fitz
    from PIL import Image, ImageDraw

    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    larghezza_px, altezza_px = img.size
    larghezza_mm, altezza_mm = geometria["pagina_mm"]
    kx, ky = larghezza_px / larghezza_mm, altezza_px / altezza_mm
    disegna = ImageDraw.Draw(img)

    for cella in geometria["celle"]:
        if cella["riga"] not in righe:
            continue
        x = cella["x_mm"] * kx
        y = cella["y_mm"] * ky
        w = cella["w_mm"] * kx
        h = cella["h_mm"] * ky
        for k in range(7):
            disegna.line(
                [x + w * 0.15, y + h * (0.3 + 0.05 * k),
                 x + w * 0.85, y + h * (0.7 - 0.04 * k)],
                fill=(10, 10, 60), width=4,
            )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _BaseIntake(TestCase):
    """Cartella di ingresso e archivio privato entrambi su cartelle temporanee."""

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
        self.intake = Path(tempfile.mkdtemp(prefix="pn-intake-"))
        self.addCleanup(shutil.rmtree, self.intake, True)

        self.utente = User.objects.create_superuser("intake_op", "i@e.it", "pwd12345")
        self.corso, self.sessione, self.lezione = _scenario()
        self.config = TrainingScanIntakeConfig.load()
        self.config.attiva = True
        self.config.cartella = str(self.intake)
        self.config.save()

    def _deposita(self, nome="scan_001.png", righe=(1, 2)) -> tuple:
        """Emette un foglio, lo firma e lo scrive nella cartella come la fotocopiatrice."""
        foglio, pdf = emetti_foglio_firme(self.lezione, user=self.utente)
        contenuto = _scansione_firmata(pdf, foglio.geometria, list(righe))
        (self.intake / nome).write_bytes(contenuto)
        return foglio, contenuto

    def _elabora(self):
        # Le prove non devono aspettare la stabilizzazione del file: la
        # fotocopiatrice scrive a pezzi, un test no.
        from .services import intake_scansioni

        originale = intake_scansioni.ATTESA_STABILITA_SECONDI
        intake_scansioni.ATTESA_STABILITA_SECONDI = 0
        try:
            return elabora_cartella(TrainingScanIntakeConfig.load())
        finally:
            intake_scansioni.ATTESA_STABILITA_SECONDI = originale


class AcquisizioneTest(_BaseIntake):

    def test_il_foglio_si_riconosce_senza_convenzioni_sul_nome(self):
        """Nessuna regola sul nome file: la prima cosa che nessuno rispetta."""
        foglio, _ = self._deposita(nome="SKM_C224e19061410250.png")

        esito = self._elabora()

        self.assertEqual(esito["letti"], 1)
        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "OK")
        self.assertEqual(riga.origine, "CARTELLA")
        self.assertEqual(riga.token_letto, foglio.token)
        self.assertEqual(riga.lezione_id, self.lezione.pk)
        self.assertEqual(riga.n_firmati, 2)

    def test_il_file_letto_viene_spostato_in_elaborati(self):
        self._deposita(nome="scan_a.png")
        self._elabora()

        self.assertFalse((self.intake / "scan_a.png").exists())
        self.assertTrue((self.intake / "elaborati" / "scan_a.png").exists())

    def test_un_foglio_non_riconosciuto_finisce_in_errori_ma_non_si_perde(self):
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (900, 1200), "white").save(buf, format="PNG")
        (self.intake / "estraneo.png").write_bytes(buf.getvalue())

        esito = self._elabora()

        self.assertEqual(esito["rifiutati"], 1)
        self.assertTrue((self.intake / "errori" / "estraneo.png").exists())

        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "RIFIUTATO")
        self.assertTrue(riga.percorso, "il file va archiviato anche se non riconosciuto")

    def test_niente_viene_letto_due_volte(self):
        self._deposita(nome="scan_b.png")
        self._elabora()
        secondo = self._elabora()

        self.assertEqual(secondo["esaminati"], 0)
        self.assertEqual(TrainingScanLog.objects.count(), 1)

    def test_i_file_estranei_vengono_ignorati(self):
        (self.intake / "istruzioni.txt").write_text("non sono una scansione", encoding="utf-8")
        esito = self._elabora()
        self.assertEqual(esito["esaminati"], 0)
        self.assertTrue((self.intake / "istruzioni.txt").exists())

    def test_il_limite_per_giro_viene_rispettato(self):
        for i in range(3):
            self._deposita(nome=f"multi_{i}.png")
        self.config.max_file_per_giro = 2
        self.config.save()

        esito = self._elabora()
        self.assertEqual(esito["esaminati"], 2)

    def test_spenta_non_guarda_nemmeno_la_cartella(self):
        self._deposita(nome="ignorato.png")
        self.config.attiva = False
        self.config.save()

        esito = self._elabora()
        self.assertEqual(esito["esaminati"], 0)
        self.assertTrue((self.intake / "ignorato.png").exists())
        self.assertEqual(TrainingScanLog.objects.count(), 0)

    def test_cartella_irraggiungibile_non_e_un_guasto(self):
        """Una share che non risponde è un contrattempo, non un errore del portale."""
        self.config.cartella = r"\\server-inesistente\condivisione\mai"
        self.config.save()

        esito = self._elabora()
        self.assertIn("non raggiungibile", esito["riepilogo"])
        self.assertEqual(esito["esaminati"], 0)

    def test_l_ultimo_passaggio_resta_annotato(self):
        self._deposita(nome="scan_c.png")
        self._elabora()

        config = TrainingScanIntakeConfig.load()
        self.assertIsNotNone(config.ultima_esecuzione)
        self.assertIn("letti", config.ultimo_esito)


class ConfermaAutomaticaTest(_BaseIntake):

    def test_per_default_non_registra_nessuna_presenza(self):
        """Il punto fermo: una misura di pixel non è una firma."""
        self._deposita(righe=(1, 2, 3, 4))
        esito = self._elabora()

        self.assertEqual(esito["presenze_scritte"], 0)
        self.assertEqual(TrainingLessonAttendance.objects.count(), 0)
        self.assertEqual(TrainingScanLog.objects.get().presenze_scritte, 0)

    def test_accesa_registra_le_presenze_lette(self):
        self.config.conferma_automatica = True
        self.config.save()
        self._deposita(righe=(1, 2))

        esito = self._elabora()

        self.assertEqual(esito["presenze_scritte"], 2)
        presenze = TrainingLessonAttendance.objects.filter(lezione=self.lezione)
        self.assertEqual(presenze.count(), 2)
        for p in presenze:
            self.assertEqual(p.stato_presenza, "PRESENTE")
            self.assertEqual(p.signature_status, "FIRMATO")
            self.assertEqual(p.signature_method, "UPLOAD")
        self.assertEqual(TrainingScanLog.objects.get().presenze_scritte, 2)

    def test_chi_non_ha_firmato_non_viene_toccato(self):
        """L'assenza di una firma non è la prova di un'assenza."""
        self.config.conferma_automatica = True
        self.config.save()
        self._deposita(righe=(1,))

        self._elabora()

        self.assertEqual(TrainingLessonAttendance.objects.filter(lezione=self.lezione).count(), 1)

    def test_si_ferma_se_non_tutti_risultano_firmati(self):
        self.config.conferma_automatica = True
        self.config.auto_solo_se_tutti_firmati = True
        self.config.save()
        self._deposita(righe=(1, 2))  # 2 su 4

        esito = self._elabora()

        self.assertEqual(esito["presenze_scritte"], 0)
        self.assertEqual(TrainingLessonAttendance.objects.count(), 0)
        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "OK")
        self.assertIn("conferma manuale", riga.messaggio)

    def test_registra_tutti_quando_tutti_hanno_firmato(self):
        self.config.conferma_automatica = True
        self.config.auto_solo_se_tutti_firmati = True
        self.config.save()
        self._deposita(righe=(1, 2, 3, 4))

        esito = self._elabora()
        self.assertEqual(esito["presenze_scritte"], 4)


class ImpostazioniPaginaTest(_BaseIntake):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.utente)

    def test_la_pagina_mostra_lo_stato_della_cartella(self):
        r = self.client.get(reverse("anagrafica:formazione_scansioni_impostazioni"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cartella raggiungibile")

    def test_una_lettera_di_unita_viene_accettata_ma_segnalata(self):
        """Può essere un disco locale del server: non si rifiuta, si avvisa.

        Se invece è un'unità mappata, il servizio non la vede e la cartella
        resterebbe eternamente vuota senza che nessuno capisca perché.
        """
        r = self.client.post(reverse("anagrafica:formazione_scansioni_impostazioni"), {
            "azione": "salva", "attiva": "on", "cartella": r"Y:\scansioni\formazione",
            "max_file_per_giro": "25", "auto_solo_senza_dubbie": "on",
        }, follow=True)

        self.assertEqual(TrainingScanIntakeConfig.load().cartella, r"Y:\scansioni\formazione")
        self.assertContains(r, "lettera di unità")

    def test_non_si_attiva_senza_cartella(self):
        r = self.client.post(reverse("anagrafica:formazione_scansioni_impostazioni"), {
            "azione": "salva", "attiva": "on", "cartella": "",
            "max_file_per_giro": "25",
        })
        self.assertContains(r, "Serve una cartella")

    def test_salva_le_impostazioni(self):
        r = self.client.post(reverse("anagrafica:formazione_scansioni_impostazioni"), {
            "azione": "salva", "attiva": "on", "cartella": str(self.intake),
            "max_file_per_giro": "10", "conferma_automatica": "on",
            "auto_solo_senza_dubbie": "on",
        }, follow=True)
        self.assertEqual(r.status_code, 200)

        config = TrainingScanIntakeConfig.load()
        self.assertTrue(config.conferma_automatica)
        self.assertEqual(config.max_file_per_giro, 10)

    def test_prova_adesso_esegue_un_passaggio(self):
        self._deposita(nome="prova.png")
        from .services import intake_scansioni

        originale = intake_scansioni.ATTESA_STABILITA_SECONDI
        intake_scansioni.ATTESA_STABILITA_SECONDI = 0
        try:
            r = self.client.post(reverse("anagrafica:formazione_scansioni_impostazioni"),
                                 {"azione": "prova"}, follow=True)
        finally:
            intake_scansioni.ATTESA_STABILITA_SECONDI = originale

        self.assertEqual(r.status_code, 200)
        self.assertEqual(TrainingScanLog.objects.count(), 1)

    def test_senza_permessi_la_pagina_non_si_apre(self):
        self.client.logout()
        semplice = User.objects.create_user("nessuno_intake", "n@e.it", "pwd12345")
        self.client.force_login(semplice)

        r = self.client.get(reverse("anagrafica:formazione_scansioni_impostazioni"), follow=True)
        self.assertNotContains(r, "Acquisizione scansioni da cartella")
