"""Dispense dei corsi per i dipendenti: visibilità, lettore, «Ho letto», ricerca, Sapere, impostazioni HR.

Dati sintetici.
"""
from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserOnboarding

from .models_formazione import (TrainingAssignment, TrainingAttachment, TrainingCourse, TrainingCourseType,
                                TrainingDispensaApertura, TrainingDispensaLettura, TrainingPlan, TrainingSlide)
from .services import dispense as srv

PID = 9901
LEGACY = "anagrafica.views._helpers._current_legacy_anagrafica_id"


def _pdf(testo: str) -> bytes:
    import fitz
    doc = fitz.open()
    for riga in testo.split("|"):
        pag = doc.new_page()
        pag.insert_text((72, 72), riga)
    dati = doc.tobytes()
    doc.close()
    return dati


class _Base(TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="pn_dispense_")
        self._ovr = override_settings(ANAGRAFICA_PRIVATE_ROOT=self._root)
        self._ovr.enable()
        U = get_user_model()
        self.hr = U.objects.create_superuser("hr.disp", "hr@example.invalid", "pwd12345")
        self.dip = U.objects.create_user("dip.disp", "dip@example.invalid", "pwd12345")
        for u in (self.hr, self.dip):
            UserOnboarding.objects.get_or_create(user=u, defaults={"completed": True})
        piano = TrainingPlan.objects.create(codice="PDS", nome="Piano sintetico dispense")
        tipo = TrainingCourseType.objects.create(nome="Sicurezza prova", colore="#b83a3a", ordine=1)
        self.corso = TrainingCourse.objects.create(piano=piano, tipo=tipo, codice="DSP1", titolo="Corso sintetico dispense",
                                                   durata_ore_teorica=Decimal("2"), is_active=True, stato="ATTIVO")
        self.aperta = self._att("Uso dell'estintore", "Prima pagina|Usa l'estintore sulla base del fuoco")
        self.riservata = self._att("Solo iscritti", "Contenuto riservato", solo_chi_ha_corso=True)
        self.nascosta = self._att("Bozza HR", "Non pubblica", visibile=False)
        self.registro = TrainingAttachment.objects.create(
            corso=self.corso, tipo="REGISTRO_FIRMATO", visibile_dipendenti=True, nome_originale="registro.pdf",
            file=SimpleUploadedFile("registro.pdf", _pdf("Firme"), content_type="application/pdf"))

    def tearDown(self):
        self._ovr.disable()
        shutil.rmtree(self._root, ignore_errors=True)

    def _att(self, titolo, testo, *, visibile=True, solo_chi_ha_corso=False, richiedi_lettura=False):
        a = TrainingAttachment.objects.create(
            corso=self.corso, tipo="MATERIALE", titolo=titolo, visibile_dipendenti=visibile,
            solo_chi_ha_corso=solo_chi_ha_corso, richiedi_lettura=richiedi_lettura,
            nome_originale=f"{titolo}.pdf", tipo_mime="application/pdf",
            file=SimpleUploadedFile(f"{titolo}.pdf", _pdf(testo), content_type="application/pdf"))
        return a

    def come_dipendente(self, lid=PID):
        self.client.force_login(self.dip)
        return mock.patch(LEGACY, return_value=lid)


class VisibilitaTests(_Base):
    def test_dipendente_vede_solo_le_visibili_e_le_riservate_se_ha_il_corso(self):
        ctx = srv.Contesto(PID)
        self.assertEqual(set(srv.visibili(ctx).values_list("pk", flat=True)), {self.aperta.pk})
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=PID)
        ctx = srv.Contesto(PID)
        self.assertEqual(set(srv.visibili(ctx).values_list("pk", flat=True)), {self.aperta.pk, self.riservata.pk})

    def test_mai_registri_ne_nascoste_anche_per_hr(self):
        ids = set(srv.visibili(srv.Contesto(None, tutto=True)).values_list("pk", flat=True))
        self.assertEqual(ids, {self.aperta.pk, self.riservata.pk})

    def test_corso_archiviato_sparisce_per_il_dipendente(self):
        self.corso.stato = "ARCHIVIATO"
        self.corso.save()
        self.assertFalse(srv.visibili(srv.Contesto(PID)).exists())


class PagineDipendenteTests(_Base):
    def test_libreria_scaffale_corso_e_lettore(self):
        with self.come_dipendente():
            r = self.client.get(reverse("anagrafica:dispense_libreria"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Sicurezza prova")
            self.assertEqual(self.client.get(reverse("anagrafica:dispense_scaffale", args=[self.corso.tipo_id])).status_code, 200)
            r = self.client.get(reverse("anagrafica:dispense_corso", args=[self.corso.pk]))
            self.assertContains(r, "Uso dell&#x27;estintore")
            self.assertNotContains(r, "Bozza HR")
            r = self.client.get(reverse("anagrafica:dispensa_file", args=[self.aperta.pk]))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r["Content-Disposition"].startswith("inline"))
            self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))
            self.assertEqual(TrainingDispensaApertura.objects.filter(allegato=self.aperta, legacy_anagrafica_id=PID).count(), 1)
            for a in (self.nascosta, self.riservata, self.registro):
                self.assertEqual(self.client.get(reverse("anagrafica:dispensa_file", args=[a.pk])).status_code, 404)

    def test_ho_letto_va_nel_libretto(self):
        self.aperta.richiedi_lettura = True
        self.aperta.save()
        with self.come_dipendente():
            r = self.client.get(reverse("anagrafica:dispense_corso", args=[self.corso.pk]))
            self.assertContains(r, "Ho letto la dispensa")
            self.client.post(reverse("anagrafica:dispensa_letta", args=[self.aperta.pk]))
            self.client.post(reverse("anagrafica:dispensa_letta", args=[self.aperta.pk]))
        self.assertEqual(TrainingDispensaLettura.objects.filter(allegato=self.aperta, legacy_anagrafica_id=PID).count(), 1)
        self.assertEqual(srv.letture_di(PID, [self.aperta.pk]).keys(), {self.aperta.pk})

    def test_ricerca_dentro_il_pdf_con_pagina(self):
        with self.come_dipendente():
            r = self.client.get(reverse("anagrafica:dispense_libreria"), {"q": "estintori base"})
        risultati = r.context["risultati"]
        self.assertEqual([x["a"].pk for x in risultati], [self.aperta.pk])
        self.assertEqual(risultati[0]["estratti"][0]["pagina"], 2)
        with self.come_dipendente():
            r = self.client.get(reverse("anagrafica:dispense_libreria"), {"q": "riservato"})
        self.assertEqual(r.context["risultati"], [])

    def test_riquadro_nel_corso_online_e_carta_in_sapere(self):
        self.corso.is_elearning = True
        self.corso.save()
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="Ciao")
        self.client.force_login(self.hr)
        r = self.client.get(reverse("anagrafica:formazione_online_materiale", args=[self.corso.pk]))
        self.assertContains(r, "Dispense del corso")
        r = self.client.get(reverse("sapere_cataloghi"))
        self.assertContains(r, "Corsi e dispense")


class GestioneHrTests(_Base):
    def test_impostazioni_dalla_scheda_corso(self):
        self.client.force_login(self.hr)
        url = reverse("anagrafica:formazione_allegato_dispensa", args=[self.nascosta.pk])
        self.client.post(url, {"titolo": "Dispensa pubblicata", "visibile": "1", "richiedi_lettura": "1"})
        self.nascosta.refresh_from_db()
        self.assertTrue(self.nascosta.visibile_dipendenti and self.nascosta.richiedi_lettura)
        self.assertEqual(self.nascosta.titolo, "Dispensa pubblicata")
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertContains(r, "Impostazioni per i dipendenti")

    def test_registro_firme_mai_visibile(self):
        self.client.force_login(self.hr)
        self.registro.visibile_dipendenti = False
        self.registro.save()
        self.client.post(reverse("anagrafica:formazione_allegato_dispensa", args=[self.registro.pk]), {"visibile": "1"})
        self.registro.refresh_from_db()
        self.assertFalse(self.registro.visibile_dipendenti)

    def test_upload_visibile_ed_estrae_il_testo(self):
        self.client.force_login(self.hr)
        f = SimpleUploadedFile("nuova.pdf", _pdf("Carrello elevatore e baricentro"), content_type="application/pdf")
        self.client.post(reverse("anagrafica:formazione_corso_allegato_upload", args=[self.corso.pk]),
                         {"file": f, "tipo": "MATERIALE", "titolo": "Carrelli", "visibile": "1"})
        a = TrainingAttachment.objects.get(titolo="Carrelli")
        self.assertTrue(a.visibile_dipendenti)
        self.assertIn("baricentro", a.testo)
        self.assertEqual(a.n_pagine, 1)

    def test_dipendente_non_cambia_le_impostazioni(self):
        with self.come_dipendente():
            self.client.post(reverse("anagrafica:formazione_allegato_dispensa", args=[self.aperta.pk]), {})
        self.aperta.refresh_from_db()
        self.assertTrue(self.aperta.visibile_dipendenti)
