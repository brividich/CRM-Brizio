"""E-learning, fase 2 del prompt 05. Dati sintetici.

Blocco 1: domande tipizzate (singola, multipla, vero/falso) e import da Excel.
"""
from __future__ import annotations

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models_formazione import TrainingQuizAttempt, TrainingQuizOption, TrainingQuizQuestion
from .services import elearning_quiz
from .services.elearning_quiz_import import ImportQuizError, leggi
from .tests_elearning_pro import _Pro

User = get_user_model()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(righe) -> SimpleUploadedFile:
    from openpyxl import Workbook
    wb = Workbook()
    for r in righe:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("domande.xlsx", buf.getvalue(), content_type=XLSX)


class DomandeTipizzateTests(_Pro):
    def _domanda(self, tipo, opzioni):
        q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=9, testo=f"Domanda {tipo}", tipo=tipo)
        for i, (testo, giusta) in enumerate(opzioni, start=1):
            TrainingQuizOption.objects.create(domanda=q, testo=testo, corretta=giusta, ordine=i)
        return q

    def test_validita_per_tipo(self):
        singola_doppia = self._domanda("SINGOLA", [("a", True), ("b", True)])
        multipla = self._domanda("MULTIPLA", [("a", True), ("b", True), ("c", False)])
        senza = self._domanda("MULTIPLA", [("a", False), ("b", False)])
        self.assertIn("una sola", elearning_quiz.problema_domanda(singola_doppia))
        self.assertEqual(elearning_quiz.problema_domanda(multipla), "")
        self.assertIn("Nessuna risposta corretta", elearning_quiz.problema_domanda(senza))
        valide = {d.pk for d in elearning_quiz.domande_valide(self.corso)}
        self.assertIn(multipla.pk, valide)
        self.assertNotIn(singola_doppia.pk, valide)

    def test_multipla_tutte_e_sole_le_giuste(self):
        self.q.delete()
        q = self._domanda("MULTIPLA", [("a", True), ("b", True), ("c", False)])
        a, b, _c = q.opzioni.order_by("ordine")
        self._vedi_tutte()
        url = reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk])
        r = self.client.get(url)
        self.assertContains(r, 'type="checkbox" name="q_%d"' % q.pk)
        self.client.post(url, {"token": r.context["token"], f"q_{q.pk}": [a.pk]})  # incompleta
        self.assertFalse(TrainingQuizAttempt.objects.get(token=r.context["token"]).superato)

    def test_singola_e_vero_falso_con_radio(self):
        vf = self._domanda("VERO_FALSO", [])
        elearning_quiz.imposta_vero_falso(vf, vera=False)
        self.assertEqual([(o.testo, o.corretta) for o in vf.opzioni.order_by("ordine")],
                         [("Vero", False), ("Falso", True)])
        self._vedi_tutte()
        r = self.client.get(reverse("anagrafica:formazione_online_quiz", args=[self.corso.pk]))
        self.assertContains(r, 'type="radio" name="q_%d"' % vf.pk)
        self.assertContains(r, 'type="radio" name="q_%d"' % self.q.pk)
        voce = next(v for v in TrainingQuizAttempt.objects.get(token=r.context["token"]).domande_servite_json
                    if v["id"] == vf.pk)
        self.assertEqual(voce["tipo"], "VERO_FALSO")

    def test_editor_vero_falso_crea_le_opzioni_e_blocca_le_altre(self):
        admin = User.objects.create_superuser("aut.el", "aut@example.invalid", "x")
        self.client.force_login(admin)
        self.client.post(reverse("anagrafica:formazione_question_save", args=[self.corso.pk]),
                         {"testo": "Il casco è un DPI.", "tipo": "VERO_FALSO", "vf_vera": "1", "ordine": 5,
                          "is_active": "on"})
        q = TrainingQuizQuestion.objects.get(testo="Il casco è un DPI.")
        self.assertEqual([(o.testo, o.corretta) for o in q.opzioni.order_by("ordine")],
                         [("Vero", True), ("Falso", False)])
        self.client.post(reverse("anagrafica:formazione_option_save", args=[self.corso.pk, q.pk]),
                         {"testo": "Forse", "ordine": 3})
        self.assertEqual(q.opzioni.count(), 2)
        r = self.client.get(reverse("anagrafica:formazione_corso_elearning", args=[self.corso.pk]))
        self.assertContains(r, "Importa domande da Excel")


class ImportDomandeExcelTests(_Pro):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("imp.el", "imp@example.invalid", "x")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:formazione_question_import", args=[self.corso.pk])

    def test_import_dei_tre_tipi(self):
        f = _xlsx([["Tipo", "Domanda", "Risposta 1", "Risposta 2", "Risposta 3", "Corrette"],
                   ["", "Singola implicita?", "sì", "no", None, 1],
                   ["multipla", "Quali?", "a", "b", "c", "1,3"],
                   ["VF", "Vero?", None, None, None, "F"]])
        self.client.post(self.url, {"file": f})
        nuove = list(self.corso.quiz_domande.exclude(pk=self.q.pk).order_by("ordine"))
        self.assertEqual([d.tipo for d in nuove], ["SINGOLA", "MULTIPLA", "VERO_FALSO"])
        self.assertTrue(all(not elearning_quiz.problema_domanda(d) for d in nuove))
        self.assertEqual(nuove[0].ordine, self.q.ordine + 1)

    def test_tutto_o_niente_con_numero_di_riga(self):
        f = _xlsx([["Domanda", "Risposta 1", "Risposta 2", "Corrette"],
                   ["Buona?", "a", "b", "1"],
                   ["Rotta?", "a", "b", "5"]])
        with self.assertRaises(ImportQuizError) as ctx:
            leggi(f)
        self.assertIn("Riga 3", ctx.exception.errori[0])
        f.seek(0)
        r = self.client.post(self.url, {"file": f}, follow=True)
        self.assertContains(r, "nessuna domanda salvata")
        self.assertEqual(self.corso.quiz_domande.count(), 1)

    def test_file_non_excel_rifiutato_e_modello_scaricabile(self):
        finto = SimpleUploadedFile("domande.xlsx", b"<html>no</html>", content_type=XLSX)
        r = self.client.post(self.url, {"file": finto}, follow=True)
        self.assertContains(r, "File rifiutato")
        self.assertEqual(self.corso.quiz_domande.count(), 1)
        modello = self.client.get(self.url)
        self.assertEqual(modello.status_code, 200)
        self.assertEqual(len(leggi(SimpleUploadedFile("m.xlsx", modello.content))), 3)

    def test_discente_non_importa(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"file": _xlsx([["Domanda", "Risposta 1", "Risposta 2", "Corrette"],
                                                   ["X?", "a", "b", "1"]])})
        self.assertEqual(self.corso.quiz_domande.count(), 1)


class VerificaAttestatoTests(_Pro):
    def setUp(self):
        super().setUp()
        self._vedi_tutte()
        with self.captureOnCommitCallbacks(execute=True):
            self._quiz(self.giusta)
        from .models_formazione import TrainingEmployeeRecord
        self.record = TrainingEmployeeRecord.objects.get(legacy_anagrafica_id=self.lid)

    def _codice(self):
        from .services.attestato_verifica import assegna_codice_verifica
        return assegna_codice_verifica(self.record)

    def test_codice_stabile_e_casuale(self):
        from .services import attestato_verifica as av
        codice = self._codice()
        self.assertEqual(len(codice), av.LUNGHEZZA)
        self.assertTrue(set(codice) <= set(av.ALFABETO))
        self.record.refresh_from_db()
        self.assertEqual(av.assegna_codice_verifica(self.record), codice)

    def test_esiti(self):
        from datetime import date
        from .models_elearning import TrainingElearningCompletamento
        from .services import attestato_verifica as av
        codice = self._codice()
        esito = av.verifica(av.formatta(codice).lower())
        self.assertEqual(esito.stato, av.VALIDO)
        self.assertEqual(esito.nome, "DISCENTE.EL NOME")
        self.assertEqual(av.verifica("ZZZZ-ZZZZ-ZZZZ").stato, av.SCONOSCIUTO)
        self.assertEqual(av.verifica(codice, oggi=date(2999, 1, 1)).stato, av.VALIDO)  # nessuna scadenza
        type(self.record).objects.filter(pk=self.record.pk).update(data_scadenza=date(2020, 1, 1))
        self.assertEqual(av.verifica(codice).stato, av.SCADUTO)
        comp = TrainingElearningCompletamento.objects.get(record=self.record)
        TrainingElearningCompletamento.objects.filter(pk=comp.pk).update(verifica_json={"falso": True})
        self.assertEqual(av.verifica(codice).stato, av.ALTERATO)

    def test_pagina_minima_e_solo_autenticati(self):
        from .services.attestato_verifica import formatta
        url = reverse("anagrafica:formazione_verifica_attestato_codice", args=[formatta(self._codice())])
        r = self.client.get(url)
        self.assertContains(r, "Attestato autentico e valido")
        self.assertContains(r, "Sicurezza online")
        self.assertNotContains(r, "discente.el@example.invalid")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_limite_di_verifiche(self):
        from django.core.cache import cache
        from .views_elearning import VERIFICHE_MAX
        cache.set(f"elearning:verifica:{self.user.pk}", VERIFICHE_MAX, 60)
        r = self.client.get(reverse("anagrafica:formazione_verifica_attestato_codice", args=["AAAA-BBBB-CCCC"]))
        self.assertEqual(r.status_code, 429)
        cache.delete(f"elearning:verifica:{self.user.pk}")

    def test_pdf_e_html_portano_il_codice(self):
        from django.test import override_settings
        from .services.attestato_pdf import build_attestato_context, build_attestato_pdf_bytes
        with override_settings(SITE_URL="https://hub.example.invalid"):
            ctx = build_attestato_context(self.record)
            self.assertTrue(ctx["verifica_url"].startswith("https://hub.example.invalid/anagrafica/"))
            self.assertIn("<svg", ctx["verifica_qr_svg"])
            self.assertTrue(build_attestato_pdf_bytes(self.record).startswith(b"%PDF"))
        admin = User.objects.create_superuser("att.el", "att@example.invalid", "x")
        self.client.force_login(admin)
        r = self.client.get(reverse("anagrafica:attestato_formazione", args=[self.record.pk]))
        self.assertContains(r, ctx["codice_verifica"])
