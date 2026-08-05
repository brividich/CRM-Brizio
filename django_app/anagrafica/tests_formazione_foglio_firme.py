"""Formazione HR — foglio firme tracciato: elenco congelato, QR, geometria.

Il registro cartaceo resta l'unico documento che un ispettore accetta senza
discutere: l'obiettivo è farlo diventare anche il modo di compilare il portale.
Tre scelte lo rendono possibile **senza riconoscimento del testo**, e sono
quelle che questi test presidiano.

- **L'elenco viene congelato alla stampa.** Se dopo si aggiunge un iscritto,
  l'ordine delle righe cambierebbe e la riga 7 della scansione non sarebbe più
  la stessa persona. Il foglio emesso è un fatto storico, non una vista.
- **Il QR porta il token**: al caricamento non c'è nulla da scegliere.
- **La geometria delle celle è registrata**, quindi rileggere la scansione sarà
  misurare se un rettangolo di posizione nota contiene inchiostro — non
  interpretare una firma.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
    TrainingSignatureSheet,
)
from .services.foglio_firme import (
    build_foglio_firme_pdf,
    emetti_foglio_firme,
    genera_token,
)

User = get_user_model()


def _scenario(n_iscritti=3):
    corso = TrainingCourse.objects.create(
        piano=TrainingPlan.objects.create(codice="FF", nome="Piano FF"),
        codice="FF-01", titolo="Corso foglio firme",
        durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
    )
    sess = TrainingSession.objects.create(
        corso=corso, codice_sessione="FF-01-E1",
        data_inizio=date(2026, 4, 14), data_fine=date(2026, 4, 14),
        docente_nome="Ente accreditato",
    )
    lez = TrainingLesson.objects.create(
        sessione=sess, numero=1, data=date(2026, 4, 14),
        ora_inizio=time(8, 0), ora_fine=time(17, 0), argomento="Parte teorica",
    )
    for i in range(n_iscritti):
        TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=900 + i)
    return corso, sess, lez


class TokenTests(TestCase):
    def test_lunghezza_e_alfabeto_senza_caratteri_ambigui(self):
        """Se il QR si rovina qualcuno ribatte il token a mano: «0/O» e «1/I»
        sarebbero una trappola."""
        token = genera_token()
        self.assertEqual(len(token), 10)
        for vietato in "01OI":
            self.assertNotIn(vietato, token)

    def test_token_diversi(self):
        self.assertNotEqual(genera_token(), genera_token())


class EmissioneTests(TestCase):
    def setUp(self):
        self.corso, self.sess, self.lez = _scenario()

    def test_emissione_congela_l_elenco(self):
        foglio, pdf = emetti_foglio_firme(self.lez)

        self.assertEqual(foglio.n_righe, 3)
        self.assertEqual([r["n"] for r in foglio.righe], [1, 2, 3])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(foglio.stato, "EMESSO")

    def test_iscritto_aggiunto_dopo_non_altera_il_foglio_emesso(self):
        """È il motivo per cui il foglio è un record e non una ristampa al volo."""
        foglio, _ = emetti_foglio_firme(self.lez)
        prima = list(foglio.righe)

        TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=1)

        foglio.refresh_from_db()
        self.assertEqual(foglio.righe, prima, "la riga 7 deve restare la persona di allora")

    def test_ristampa_emette_un_foglio_nuovo(self):
        """Due fogli con lo stesso token porterebbero elenchi diversi."""
        primo, _ = emetti_foglio_firme(self.lez)
        TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=1)
        secondo, _ = emetti_foglio_firme(self.lez)

        self.assertNotEqual(primo.token, secondo.token)
        self.assertEqual(primo.n_righe, 3)
        self.assertEqual(secondo.n_righe, 4)
        self.assertEqual(TrainingSignatureSheet.objects.count(), 2)

    def test_lezione_senza_iscritti_produce_comunque_il_foglio(self):
        vuota = TrainingLesson.objects.create(
            sessione=self.sess, numero=2, data=date(2026, 4, 15),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="Seconda",
        )
        TrainingEnrollment.objects.all().delete()
        foglio, pdf = emetti_foglio_firme(vuota)
        self.assertEqual(foglio.n_righe, 0)
        self.assertTrue(pdf.startswith(b"%PDF"))


class GeometriaTests(TestCase):
    def setUp(self):
        self.corso, self.sess, self.lez = _scenario(n_iscritti=2)

    def test_una_cella_per_firma_per_ogni_iscritto(self):
        foglio, _ = emetti_foglio_firme(self.lez)
        celle = foglio.geometria["celle"]

        self.assertEqual(len(celle), 4, "due iscritti × ingresso e uscita")
        self.assertEqual({c["campo"] for c in celle}, {"ingresso", "uscita"})
        self.assertEqual({c["legacy_id"] for c in celle}, {900, 901})

    def test_le_celle_portano_la_persona_non_solo_la_riga(self):
        """Legare la cella al legacy_id evita che una rinumerazione
        futura riassegni le firme alla persona sbagliata."""
        foglio, _ = emetti_foglio_firme(self.lez)
        for cella in foglio.geometria["celle"]:
            self.assertIn("legacy_id", cella)
            self.assertIn("riga", cella)

    def test_coordinate_dentro_la_pagina_e_dall_alto(self):
        foglio, _ = emetti_foglio_firme(self.lez)
        larghezza, altezza = foglio.geometria["pagina_mm"]
        self.assertAlmostEqual(larghezza, 210, delta=1)
        self.assertAlmostEqual(altezza, 297, delta=1)
        for c in foglio.geometria["celle"]:
            self.assertGreater(c["x_mm"], 0)
            self.assertLess(c["x_mm"] + c["w_mm"], larghezza)
            self.assertGreater(c["y_mm"], 0, "le y sono misurate dall'alto")
            self.assertLess(c["y_mm"] + c["h_mm"], altezza)

    def test_righe_successive_scendono(self):
        foglio, _ = emetti_foglio_firme(self.lez)
        ing = sorted(
            (c for c in foglio.geometria["celle"] if c["campo"] == "ingresso"),
            key=lambda c: c["riga"],
        )
        self.assertLess(ing[0]["y_mm"], ing[1]["y_mm"], "la riga 2 sta sotto la riga 1")

    def test_ingresso_e_uscita_non_si_sovrappongono(self):
        foglio, _ = emetti_foglio_firme(self.lez)
        per_riga: dict = {}
        for c in foglio.geometria["celle"]:
            per_riga.setdefault(c["riga"], {})[c["campo"]] = c
        for celle in per_riga.values():
            a, b = celle["ingresso"], celle["uscita"]
            self.assertGreaterEqual(b["x_mm"], a["x_mm"] + a["w_mm"] - 0.01)

    def test_geometria_versionata(self):
        """Il lettore della scansione dovrà sapere con quale schema è stata scritta."""
        foglio, _ = emetti_foglio_firme(self.lez)
        self.assertEqual(foglio.geometria["versione"], 1)
        self.assertIn("marcatore_mm", foglio.geometria)


class ContenutoPdfTests(TestCase):
    def _testo(self, pdf: bytes) -> str:
        import fitz

        doc = fitz.open(stream=pdf, filetype="pdf")
        try:
            return " ".join(" ".join(p.get_text().split()) for p in doc)
        finally:
            doc.close()

    def test_il_foglio_riporta_token_corso_e_giornata(self):
        corso, sess, lez = _scenario(n_iscritti=1)
        foglio, pdf = emetti_foglio_firme(lez)
        testo = self._testo(pdf)

        self.assertIn(foglio.token, testo, "il token va leggibile anche se il QR si rovina")
        self.assertIn("Registro presenze", testo)
        self.assertIn("FF-01-E1", testo)
        self.assertIn("14-04-2026", testo)
        self.assertIn("Ente accreditato", testo)

    def test_marcatori_disegnati_ai_quattro_angoli(self):
        import fitz

        corso, sess, lez = _scenario(n_iscritti=1)
        pdf, _geometria = build_foglio_firme_pdf(lez, [], "TESTTOKEN1")
        doc = fitz.open(stream=pdf, filetype="pdf")
        try:
            quadrati = [d for d in doc[0].get_drawings()
                        if d.get("fill") and d["rect"].width < 20 and d["rect"].height < 20]
            self.assertGreaterEqual(len(quadrati), 4, "servono i quattro riferimenti d'angolo")
        finally:
            doc.close()


@override_settings(LEGACY_AUTH_ENABLED=False)
class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("ff", "f@b.c", "pwd12345")
        self.client.force_login(self.user)
        self.corso, self.sess, self.lez = _scenario(n_iscritti=2)

    def test_endpoint_emette_e_restituisce_il_pdf(self):
        r = self.client.get(reverse(
            "anagrafica:formazione_lezione_registro_qr", args=[self.sess.pk, self.lez.pk]))

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        foglio = TrainingSignatureSheet.objects.get()
        self.assertIn(foglio.token, r["Content-Disposition"])
        self.assertEqual(foglio.emesso_da, self.user)

    def test_non_editor_non_emette(self):
        self.client.force_login(User.objects.create_user("tizio", "t@b.c", "pwd12345"))
        self.client.get(reverse(
            "anagrafica:formazione_lezione_registro_qr", args=[self.sess.pk, self.lez.pk]))
        self.assertEqual(TrainingSignatureSheet.objects.count(), 0)

    def test_lezione_di_un_altra_sessione_non_passa(self):
        altra = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="FF-01-E2",
            data_inizio=date(2026, 5, 1), data_fine=date(2026, 5, 1),
        )
        r = self.client.get(reverse(
            "anagrafica:formazione_lezione_registro_qr", args=[altra.pk, self.lez.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(TrainingSignatureSheet.objects.count(), 0)

    def test_emissione_tracciata_nel_registro_export(self):
        from .models_formazione import TrainingExportLog

        self.client.get(reverse(
            "anagrafica:formazione_lezione_registro_qr", args=[self.sess.pk, self.lez.pk]))
        voce = TrainingExportLog.objects.filter(tipo="REPORT_FIRMA").first()
        self.assertIsNotNone(voce)
        self.assertEqual(voce.filtri_json.get("formato"), "foglio_firme_qr")
        self.assertEqual(voce.righe_esportate, 2)
