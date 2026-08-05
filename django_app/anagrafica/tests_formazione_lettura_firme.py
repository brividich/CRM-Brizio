"""Formazione HR — lettura della scansione del foglio firme.

Il banco di prova è un **giro completo**: si emette il foglio, lo si rasterizza
come farebbe uno scanner, ci si «firma» sopra disegnando dentro alcune celle, e
si rilegge. Se il procedimento regge, tornano indietro esattamente le righe su
cui si è scritto — nessuna in più, nessuna in meno.

È il modo giusto di provarlo perché esercita la catena vera: geometria salvata
alla generazione → marcatori d'angolo → corrispondenza millimetri-pixel →
misura dell'inchiostro. Un test sulle sole soglie non direbbe nulla.

Le prove includono i casi che rompono davvero uno scanner: foglio ruotato,
scansione a risoluzione diversa, foglio storto oltre il tollerabile, marcatori
tagliati fuori.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from io import BytesIO

from django.test import TestCase

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
)
from .services.foglio_firme import emetti_foglio_firme
from .services.lettura_foglio_firme import (
    ErroreLettura,
    analizza_scansione,
    apri_scansione,
    trova_marcatori,
)


def _scenario(n_iscritti=4):
    corso = TrainingCourse.objects.create(
        piano=TrainingPlan.objects.create(codice="LF", nome="Piano LF"),
        codice="LF-01", titolo="Corso lettura firme",
        durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
    )
    sess = TrainingSession.objects.create(
        corso=corso, codice_sessione="LF-01-E1",
        data_inizio=date(2026, 4, 14), data_fine=date(2026, 4, 14),
    )
    lez = TrainingLesson.objects.create(
        sessione=sess, numero=1, data=date(2026, 4, 14),
        ora_inizio=time(8, 0), ora_fine=time(17, 0), argomento="Teoria",
    )
    for i in range(n_iscritti):
        TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=500 + i)
    return corso, sess, lez


def _rasterizza(pdf: bytes, dpi: int = 200):
    """La scansione come la produrrebbe uno scanner: pagina rasterizzata."""
    import fitz
    from PIL import Image

    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    finally:
        doc.close()


def _firma(img, geometria, righe: list[int], campo: str = "ingresso"):
    """Disegna uno scarabocchio dentro le celle indicate: è la firma in aula."""
    from PIL import ImageDraw

    larghezza_px, altezza_px = img.size
    larghezza_mm, altezza_mm = geometria["pagina_mm"]
    kx, ky = larghezza_px / larghezza_mm, altezza_px / altezza_mm
    disegna = ImageDraw.Draw(img)
    for cella in geometria["celle"]:
        if cella["riga"] not in righe or cella["campo"] != campo:
            continue
        x0 = (cella["x_mm"] + 4) * kx
        y0 = (cella["y_mm"] + 3) * ky
        x1 = (cella["x_mm"] + cella["w_mm"] - 4) * kx
        y1 = (cella["y_mm"] + cella["h_mm"] - 3) * ky
        # Tratto spesso e spezzato: assomiglia a una firma più di una linea retta.
        disegna.line([(x0, y1), ((x0 + x1) / 2, y0), (x1, y1)], fill=0, width=4)
        disegna.line([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)], fill=0, width=3)
    return img


def _png(img) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class GiroCompletoTests(TestCase):
    """Emetti → stampa → firma → rileggi. È la prova che conta."""

    def setUp(self):
        self.corso, self.sess, self.lez = _scenario(n_iscritti=4)
        self.foglio, self.pdf = emetti_foglio_firme(self.lez)

    def test_tornano_esattamente_le_righe_firmate(self):
        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [1, 3])
        esito = analizza_scansione(self.foglio, _png(img), "scan.png")

        firmate = {r["riga"] for r in esito["righe"] if r["ingresso"]}
        self.assertEqual(firmate, {1, 3})
        non_firmate = {r["riga"] for r in esito["righe"] if not r["ingresso"]}
        self.assertEqual(non_firmate, {2, 4})

    def test_foglio_intonso_non_produce_falsi_positivi(self):
        """Il caso peggiore: dare per presente chi non c'era."""
        esito = analizza_scansione(self.foglio, _png(_rasterizza(self.pdf)), "scan.png")
        self.assertEqual(esito["n_firmati"], 0)
        self.assertFalse(any(r["ingresso"] or r["uscita"] for r in esito["righe"]))

    def test_ingresso_e_uscita_sono_indipendenti(self):
        img = _rasterizza(self.pdf)
        _firma(img, self.foglio.geometria, [2], campo="ingresso")
        _firma(img, self.foglio.geometria, [4], campo="uscita")
        esito = analizza_scansione(self.foglio, _png(img), "scan.png")

        per_riga = {r["riga"]: r for r in esito["righe"]}
        self.assertTrue(per_riga[2]["ingresso"])
        self.assertFalse(per_riga[2]["uscita"])
        self.assertFalse(per_riga[4]["ingresso"])
        self.assertTrue(per_riga[4]["uscita"])

    def test_la_riga_riporta_la_persona_congelata(self):
        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [1])
        esito = analizza_scansione(self.foglio, _png(img), "scan.png")

        prima = next(r for r in esito["righe"] if r["riga"] == 1)
        attesa = self.foglio.righe[0]
        self.assertEqual(prima["legacy_id"], attesa["legacy_id"])
        self.assertEqual(prima["nome"], attesa["nome"])

    def test_tutti_firmati(self):
        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [1, 2, 3, 4])
        esito = analizza_scansione(self.foglio, _png(img), "scan.png")
        self.assertEqual(esito["n_firmati"], 4)


class RobustezzaScansioneTests(TestCase):
    def setUp(self):
        self.corso, self.sess, self.lez = _scenario(n_iscritti=4)
        self.foglio, self.pdf = emetti_foglio_firme(self.lez)

    def test_scansione_ruotata_viene_raddrizzata(self):
        """Un foglio messo storto nello scanner è la norma, non l'eccezione."""
        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [2, 4])
        storta = img.rotate(-1.2, resample=2, fillcolor=255, expand=False)

        esito = analizza_scansione(self.foglio, _png(storta), "scan.png")

        self.assertEqual({r["riga"] for r in esito["righe"] if r["ingresso"]}, {2, 4})
        self.assertGreater(abs(esito["inclinazione"]), 0.25, "l'inclinazione va rilevata")
        self.assertLess(abs(esito["inclinazione_residua"]), 0.4, "e corretta")

    def test_risoluzione_diversa_non_cambia_l_esito(self):
        """Chi scansiona non guarda mai i dpi."""
        for dpi in (150, 300):
            with self.subTest(dpi=dpi):
                img = _firma(_rasterizza(self.pdf, dpi=dpi), self.foglio.geometria, [1, 4])
                esito = analizza_scansione(self.foglio, _png(img), "scan.png")
                self.assertEqual({r["riga"] for r in esito["righe"] if r["ingresso"]}, {1, 4})

    def test_pdf_accettato_come_immagine(self):
        """Molti scanner consegnano un PDF, non un JPEG."""
        esito = analizza_scansione(self.foglio, self.pdf, "scansione.pdf")
        self.assertEqual(len(esito["righe"]), 4)

    def test_marcatori_tagliati_danno_errore_comprensibile(self):
        img = _rasterizza(self.pdf)
        larghezza, altezza = img.size
        ritagliata = img.crop((int(larghezza * 0.2), 0, larghezza, altezza))

        with self.assertRaises(ErroreLettura) as ctx:
            analizza_scansione(self.foglio, _png(ritagliata), "scan.png")
        self.assertIn("riferimento d'angolo", str(ctx.exception))

    def test_file_non_leggibile_non_esplode(self):
        with self.assertRaises(ErroreLettura):
            analizza_scansione(self.foglio, b"non sono un'immagine", "scan.png")

    def test_immagine_minuscola_rifiutata(self):
        from PIL import Image

        with self.assertRaises(ErroreLettura):
            analizza_scansione(self.foglio, _png(Image.new("L", (50, 50), 255)), "x.png")

    def test_foglio_senza_geometria_lo_dice(self):
        self.foglio.geometria = {}
        self.foglio.save()
        with self.assertRaises(ErroreLettura) as ctx:
            analizza_scansione(self.foglio, self.pdf, "scan.pdf")
        self.assertIn("geometria", str(ctx.exception))


class EndpointScansioneTests(TestCase):
    """La lettura propone; a scrivere resta la strada già collaudata."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_superuser("scan", "s@b.c", "pwd12345")
        self.client.force_login(self.user)
        self.corso, self.sess, self.lez = _scenario(n_iscritti=3)
        self.foglio, self.pdf = emetti_foglio_firme(self.lez)

    def _url(self):
        from django.urls import reverse

        return reverse("anagrafica:formazione_registro_scansione",
                       args=[self.sess.pk, self.lez.pk])

    def _file(self, contenuto: bytes, nome="scan.png"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(nome, contenuto, content_type="image/png")

    def test_proposta_senza_scrivere_nulla(self):
        from .models_formazione import TrainingLessonAttendance

        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [1, 2])
        r = self.client.post(self._url(), {
            "token": self.foglio.token, "scansione": self._file(_png(img)),
        })

        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conferma le presenze")
        self.assertEqual(
            TrainingLessonAttendance.objects.count(), 0,
            "la lettura propone soltanto: nessuna presenza va scritta qui",
        )

    def test_token_in_minuscolo_accettato(self):
        img = _rasterizza(self.pdf)
        r = self.client.post(self._url(), {
            "token": self.foglio.token.lower(), "scansione": self._file(_png(img)),
        })
        self.assertEqual(r.status_code, 200)

    def test_token_di_un_altra_giornata_rifiutato(self):
        """Un token valido ma di un'altra lezione porterebbe presenze sul giorno sbagliato."""
        altra = TrainingLesson.objects.create(
            sessione=self.sess, numero=2, data=date(2026, 4, 15),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="Seconda",
        )
        foglio_altro, _ = emetti_foglio_firme(altra)

        from django.contrib.messages import get_messages

        r = self.client.post(self._url(), {
            "token": foglio_altro.token, "scansione": self._file(_png(_rasterizza(self.pdf))),
        }, follow=True)

        testi = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("Nessun foglio con codice" in t for t in testi), testi)
        self.assertNotContains(r, "Conferma le presenze")

    def test_scansione_illeggibile_riporta_l_errore_all_utente(self):
        r = self.client.post(self._url(), {
            "token": self.foglio.token, "scansione": self._file(b"spazzatura"),
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Conferma le presenze")

    def test_campi_mancanti(self):
        """Il codice del foglio è facoltativo — si legge dal QR. Il file no."""
        from django.contrib.messages import get_messages

        r = self.client.post(self._url(), {"token": self.foglio.token}, follow=True)
        testi = [str(m) for m in get_messages(r.wsgi_request)]
        self.assertTrue(any("Serve il file della scansione" in t for t in testi), testi)
        self.assertNotContains(r, "Conferma le presenze")

    def test_non_editor_non_legge(self):
        from django.contrib.auth import get_user_model

        self.client.force_login(get_user_model().objects.create_user("tale", "t@b.c", "pwd12345"))
        r = self.client.post(self._url(), {
            "token": self.foglio.token, "scansione": self._file(_png(_rasterizza(self.pdf))),
        }, follow=True)
        self.assertNotContains(r, "Conferma le presenze")

    def test_lettura_tracciata_nel_registro_audit(self):
        from core.models import AuditLog

        img = _firma(_rasterizza(self.pdf), self.foglio.geometria, [3])
        self.client.post(self._url(), {
            "token": self.foglio.token, "scansione": self._file(_png(img)),
        })

        voce = AuditLog.objects.filter(azione="scansione_registro_letta").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.dettaglio.get("token"), self.foglio.token)
        self.assertEqual(voce.dettaglio.get("firmati"), 1)


class MarcatoriTests(TestCase):
    def setUp(self):
        self.corso, self.sess, self.lez = _scenario(n_iscritti=2)
        self.foglio, self.pdf = emetti_foglio_firme(self.lez)

    def test_quattro_marcatori_agli_angoli_giusti(self):
        img = _rasterizza(self.pdf)
        marcatori = trova_marcatori(img)
        larghezza, altezza = img.size

        self.assertEqual(set(marcatori), {"alto_sx", "alto_dx", "basso_sx", "basso_dx"})
        self.assertLess(marcatori["alto_sx"][0], larghezza / 2)
        self.assertGreater(marcatori["alto_dx"][0], larghezza / 2)
        self.assertLess(marcatori["alto_sx"][1], altezza / 2)
        self.assertGreater(marcatori["basso_sx"][1], altezza / 2)

    def test_i_marcatori_stanno_dove_li_abbiamo_stampati(self):
        """A 11 mm dai bordi: margine 8 più metà del lato 6."""
        img = _rasterizza(self.pdf)
        marcatori = trova_marcatori(img)
        larghezza, altezza = img.size
        atteso_x = larghezza * 11.0 / 210.0
        atteso_y = altezza * 11.0 / 297.0

        self.assertAlmostEqual(marcatori["alto_sx"][0], atteso_x, delta=larghezza * 0.01)
        self.assertAlmostEqual(marcatori["alto_sx"][1], atteso_y, delta=altezza * 0.01)

    def test_apri_scansione_restituisce_scala_di_grigi(self):
        self.assertEqual(apri_scansione(self.pdf, "x.pdf").mode, "L")
