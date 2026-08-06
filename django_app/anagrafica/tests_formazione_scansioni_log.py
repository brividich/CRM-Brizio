"""Formazione HR — riconoscimento del foglio dal QR e registro delle letture.

Due cose che vanno insieme.

La prima: il codice del foglio **non si digita più**, si legge dal QR che il
portale stesso ha stampato. La prova sta nel giro completo — si emette il
foglio, lo si rasterizza come uno scanner, si carica senza dire niente, e il
portale deve capire da solo di quale giornata si tratta.

La seconda: qualunque cosa succeda, **il file resta**. È la lezione del caso in
cui la lettura fallisce: prima restava un messaggio d'errore a schermo e nulla
da guardare. Ora il file è archiviato prima ancora del tentativo, e il registro
dice dove. I test più importanti qui sono quindi quelli che falliscono apposta.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import date, time
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingPlan,
    TrainingScanLog,
    TrainingSession,
)
from .services.foglio_firme import emetti_foglio_firme

User = get_user_model()


def _scenario(codice="SL-01", giorno=date(2026, 5, 12), n_iscritti=3):
    piano, _ = TrainingPlan.objects.get_or_create(codice="SL", defaults={"nome": "Piano SL"})
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
        TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=900 + i)
    return corso, sess, lez


def _scansione_png(pdf: bytes, dpi: int = 200) -> bytes:
    """Il PDF emesso come lo restituirebbe uno scanner: immagine della pagina."""
    import fitz
    from PIL import Image

    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _BaseScansioni(TestCase):
    """Archivio privato dirottato su una cartella temporanea, non su quella vera."""

    @classmethod
    def setUpClass(cls):
        cls._archivio = tempfile.mkdtemp(prefix="pn-scansioni-")
        cls._override = override_settings(ANAGRAFICA_PRIVATE_ROOT=cls._archivio)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._archivio, ignore_errors=True)

    def setUp(self):
        self.utente = User.objects.create_superuser("scan_op", "scan@e.it", "pwd12345")
        self.client.force_login(self.utente)
        self.corso, self.sessione, self.lezione = _scenario()

    def _url_carica(self, lezione=None):
        lezione = lezione or self.lezione
        return reverse("anagrafica:formazione_registro_scansione",
                       args=[lezione.sessione_id, lezione.pk])


class RiconoscimentoDalQrTest(_BaseScansioni):

    def test_il_foglio_si_riconosce_dal_qr_senza_digitare_il_codice(self):
        foglio, pdf = emetti_foglio_firme(self.lezione, user=self.utente)
        scansione = _scansione_png(pdf)

        r = self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("scan.png", scansione, "image/png"),
        })

        self.assertEqual(r.status_code, 200)
        self.assertContains(r, foglio.token)

        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "OK")
        self.assertEqual(riga.token_letto, foglio.token)
        self.assertEqual(riga.token_digitato, "")
        self.assertEqual(riga.foglio_id, foglio.pk)

    def test_il_codice_digitato_resta_una_strada_valida(self):
        """Un QR strappato o macchiato capita: la via a mano non si toglie."""
        foglio, _pdf = emetti_foglio_firme(self.lezione, user=self.utente)
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (1200, 1600), "white").save(buf, format="PNG")

        r = self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("bianco.png", buf.getvalue(), "image/png"),
            "token": foglio.token.lower(),
        }, follow=True)

        # Il foglio è quello giusto: quel che fallisce dopo è la lettura, non il
        # riconoscimento — e infatti il token risulta digitato, non letto.
        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.token_digitato, foglio.token)
        self.assertEqual(riga.token_letto, "")
        self.assertEqual(riga.foglio_id, foglio.pk)
        self.assertEqual(r.status_code, 200)

    def test_il_foglio_di_un_altra_giornata_viene_rifiutato(self):
        """Un token valido ma di un'altra lezione porterebbe presenze sul giorno sbagliato."""
        _corso2, _sess2, lezione2 = _scenario(codice="SL-02", giorno=date(2026, 6, 3))
        foglio_altrui, pdf = emetti_foglio_firme(lezione2, user=self.utente)

        r = self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("scan.png", _scansione_png(pdf), "image/png"),
        }, follow=True)

        self.assertEqual(r.status_code, 200)
        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "RIFIUTATO")
        self.assertEqual(riga.lezione_id, self.lezione.pk)
        self.assertIsNone(riga.foglio_id)
        self.assertIn(foglio_altrui.token, riga.messaggio)

    def test_senza_qr_e_senza_codice_lo_dice_chiaramente(self):
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (900, 1200), "white").save(buf, format="PNG")

        self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("vuoto.png", buf.getvalue(), "image/png"),
        }, follow=True)

        riga = TrainingScanLog.objects.get()
        self.assertEqual(riga.esito, "RIFIUTATO")
        self.assertIn("QR", riga.messaggio)


class ArchiviazioneTest(_BaseScansioni):

    def test_il_file_viene_archiviato_anche_quando_la_lettura_fallisce(self):
        """Il caso per cui esiste il registro: dell'errore deve restare la prova."""
        rotto = b"non sono un'immagine, sono spazzatura"

        self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("rotto.png", rotto, "image/png"),
        }, follow=True)

        riga = TrainingScanLog.objects.get()
        self.assertNotEqual(riga.esito, "OK")
        self.assertTrue(riga.percorso, "il percorso di archiviazione deve essere registrato")
        self.assertEqual(riga.dimensione, len(rotto))
        self.assertEqual(riga.nome_file, "rotto.png")

        from .services.archivio_scansioni import apri_archiviata

        f = apri_archiviata(riga.percorso)
        self.assertIsNotNone(f, "il file archiviato deve essere riapribile")
        try:
            self.assertEqual(f.read(), rotto)
        finally:
            f.close()

    def test_il_percorso_e_ordinato_per_anno_e_mese(self):
        self.client.post(self._url_carica(), {
            "scansione": SimpleUploadedFile("x.png", b"qualcosa", "image/png"),
        }, follow=True)
        riga = TrainingScanLog.objects.get()
        self.assertTrue(riga.percorso.startswith("formazione/scansioni/"), riga.percorso)

    def test_il_nome_del_file_viene_ripulito(self):
        """Uno scanner di rete produce nomi con spazi, accenti e percorsi interi."""
        from .services.archivio_scansioni import _nome_sicuro

        self.assertEqual(_nome_sicuro(r"C:\scanner\Foglio Firme (1).pdf"), "Foglio-Firme-1.pdf")
        self.assertEqual(_nome_sicuro("../../etc/passwd"), "passwd")
        self.assertEqual(_nome_sicuro(""), "scansione")

    def test_senza_file_non_nasce_nessuna_riga(self):
        self.client.post(self._url_carica(), {"token": "ABCDEF"}, follow=True)
        self.assertEqual(TrainingScanLog.objects.count(), 0)


class RegistroLettureTest(_BaseScansioni):

    def _riga(self, esito="ERRORE", nome="scan.png", messaggio="qualcosa è andato storto"):
        return TrainingScanLog.objects.create(
            lezione=self.lezione, nome_file=nome, esito=esito, messaggio=messaggio,
            percorso=f"formazione/scansioni/2026/05/{nome}", dimensione=2048,
        )

    def test_la_pagina_elenca_le_letture_e_mostra_dove_e_finito_il_file(self):
        riga = self._riga()
        r = self.client.get(reverse("anagrafica:formazione_scansioni_log"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, riga.nome_file)
        self.assertContains(r, riga.percorso)
        self.assertContains(r, "qualcosa è andato storto")

    def test_il_filtro_per_esito_isola_gli_errori(self):
        self._riga(esito="ERRORE", nome="fallita.png")
        self._riga(esito="OK", nome="riuscita.png", messaggio="")

        r = self.client.get(reverse("anagrafica:formazione_scansioni_log"), {"esito": "ERRORE"})
        self.assertContains(r, "fallita.png")
        self.assertNotContains(r, "riuscita.png")

    def test_la_ricerca_trova_per_nome_file(self):
        self._riga(nome="alfa.png")
        self._riga(nome="beta.png")
        r = self.client.get(reverse("anagrafica:formazione_scansioni_log"), {"q": "beta"})
        self.assertContains(r, "beta.png")
        self.assertNotContains(r, "alfa.png")

    def test_il_file_archiviato_si_riscarica_dalla_pagina(self):
        from .services.archivio_scansioni import archivia_scansione

        percorso, dimensione = archivia_scansione(b"contenuto vero", "vero.png")
        riga = TrainingScanLog.objects.create(
            lezione=self.lezione, nome_file="vero.png", esito="ERRORE",
            percorso=percorso, dimensione=dimensione,
        )

        r = self.client.get(reverse("anagrafica:formazione_scansione_scarica", args=[riga.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"contenuto vero")

    def test_un_file_sparito_non_rompe_la_pagina(self):
        riga = self._riga()  # percorso inventato, nessun file dietro
        r = self.client.get(reverse("anagrafica:formazione_scansione_scarica", args=[riga.pk]),
                            follow=True)
        self.assertEqual(r.status_code, 200)

    def test_il_registro_e_raggiungibile_dalla_home_del_modulo(self):
        """Una pagina che si apre solo conoscendone l'indirizzo non esiste."""
        r = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("anagrafica:formazione_scansioni_log"))

    def test_il_collegamento_non_compare_a_chi_non_puo_entrare(self):
        """Offrire una porta che poi rimbalza è peggio che non offrirla."""
        self.client.logout()
        semplice = User.objects.create_user("solo_lettura", "sl@e.it", "pwd12345")
        self.client.force_login(semplice)

        r = self.client.get(reverse("anagrafica:formazione_dashboard"))
        if r.status_code == 200:
            self.assertNotContains(r, reverse("anagrafica:formazione_scansioni_log"))

    def test_senza_permessi_il_registro_non_si_apre(self):
        self.client.logout()
        semplice = User.objects.create_user("nessuno", "n@e.it", "pwd12345")
        self.client.force_login(semplice)

        r = self.client.get(reverse("anagrafica:formazione_scansioni_log"), follow=True)
        self.assertNotContains(r, "Registro letture scansioni")
