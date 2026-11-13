"""Tabelle RENTRI: colonna FIR, filtri ricordati per pagina, cestino (annulla/elimina) e consolida filo."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .models import RegistroRifiuti

User = get_user_model()


def _mov(tipo, giorno, codice="15 01 06", quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=codice,
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "kg"), **extra,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class _Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-tab", email="tab@example.com", password="x")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.ieri = self.oggi - timedelta(days=1)


class ColonnaFirTests(_Base):
    def test_elenco_mostra_fir_e_manca_fir(self):
        c = _mov("C", self.ieri)
        _mov("O", self.ieri, rif_op=c.id_registrazione, arrivo_fir="XYZ 123456/26")
        _mov("O", self.oggi, rif_op=c.id_registrazione)
        html = self.client.get(reverse("rentri_elenco") + "?view=famiglie").content.decode()
        self.assertIn("<th>FIR</th>", html)
        self.assertNotIn("<th>C/S</th>", html)
        self.assertIn("XYZ 123456/26", html)
        self.assertIn("manca FIR", html)

    def test_scadenzario_ha_colonna_fir(self):
        _mov("O", self.ieri, arrivo_fir="")
        html = self.client.get(reverse("rentri_scadenzario")).content.decode()
        self.assertIn("<th>FIR</th>", html)
        csv = self.client.get(reverse("rentri_scadenzario") + "?export=csv").content.decode("utf-8-sig")
        self.assertIn(";FIR;", csv.splitlines()[0])


class FiltriRicordatiTests(_Base):
    def test_elenco_riapplica_e_azzera(self):
        url = reverse("rentri_elenco")
        self.assertEqual(self.client.get(url + "?tipo=C&q=abc").status_code, 200)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("tipo=C", r["Location"])
        self.assertIn("q=abc", r["Location"])
        r = self.client.get(url + "?reset=1")
        self.assertRedirects(r, url, fetch_redirect_response=False)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_ogni_pagina_ha_i_suoi_filtri(self):
        self.client.get(reverse("rentri_elenco") + "?tipo=O")
        self.client.get(reverse("rentri_giacenze") + "?allerta=1")
        r = self.client.get(reverse("rentri_giacenze"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("allerta=1", r["Location"])
        self.assertNotIn("tipo=O", r["Location"])
        r = self.client.get(reverse("rentri_elenco"))
        self.assertIn("tipo=O", r["Location"])

    def test_export_non_sovrascrive(self):
        self.client.get(reverse("rentri_giacenze") + "?q=15")
        self.assertEqual(self.client.get(reverse("rentri_giacenze") + "?export=csv").status_code, 200)
        self.assertIn("q=15", self.client.get(reverse("rentri_giacenze"))["Location"])


class CestinoTests(_Base):
    def test_annulla_dalla_tabella_torna_ai_filtri(self):
        c = _mov("C", self.ieri)
        prossima = reverse("rentri_elenco") + "?tipo=C"
        r = self.client.post(reverse("rentri_rimuovi", args=[c.pk]),
                             {"modo": "annulla", "motivo": "inserita due volte", "next": prossima})
        self.assertRedirects(r, prossima, fetch_redirect_response=False)
        c.refresh_from_db()
        self.assertTrue(c.annullato)
        self.assertEqual(c.motivo_annullamento, "inserita due volte")

    def test_motivo_obbligatorio(self):
        c = _mov("C", self.ieri)
        self.client.post(reverse("rentri_rimuovi", args=[c.pk]), {"modo": "elimina", "motivo": "no"})
        self.assertTrue(RegistroRifiuti.objects.filter(pk=c.pk).exists())
        self.client.post(reverse("rentri_rimuovi", args=[c.pk]), {"modo": "annulla", "motivo": ""})
        c.refresh_from_db()
        self.assertFalse(c.annullato)

    def test_elimina_definitivamente_una_bozza_isolata(self):
        c = _mov("C", self.ieri)
        numero = c.id_registrazione
        r = self.client.post(reverse("rentri_rimuovi", args=[c.pk]),
                             {"modo": "elimina", "motivo": "errore di battitura", "next": f"/rentri/{c.pk}/"})
        self.assertRedirects(r, reverse("rentri_elenco"), fetch_redirect_response=False)
        self.assertFalse(RegistroRifiuti.objects.filter(pk=c.pk).exists())
        voce = AuditLog.objects.filter(azione="rentri_movimento_eliminato").latest("id")
        self.assertIn(numero, str(voce.dettaglio))
        self.assertIn("errore di battitura", str(voce.dettaglio))
        # Il numero non torna disponibile.
        self.assertNotEqual(_mov("C", self.ieri).id_registrazione, numero)

    def test_non_si_elimina_consolidata_trasmessa_o_con_collegati(self):
        cons = _mov("C", self.ieri, salva=True)
        trasm = _mov("C", self.ieri, rentri_si_no=True)
        padre = _mov("C", self.ieri)
        _mov("O", self.oggi, rif_op=padre.id_registrazione)
        for reg in (cons, trasm, padre):
            self.client.post(reverse("rentri_rimuovi", args=[reg.pk]), {"modo": "elimina", "motivo": "prova eliminazione"})
            self.assertTrue(RegistroRifiuti.objects.filter(pk=reg.pk).exists(), reg.id_registrazione)

    def test_sharepoint_non_eliminato_blocca(self):
        c = _mov("C", self.ieri, sharepoint_item_id="42")
        with mock.patch("rentri.sharepoint._graph_configured", return_value=True), \
                mock.patch("rentri.sharepoint._graph_delete", return_value=(False, "boom")):
            self.client.post(reverse("rentri_rimuovi", args=[c.pk]), {"modo": "elimina", "motivo": "prova eliminazione"})
        self.assertTrue(RegistroRifiuti.objects.filter(pk=c.pk).exists())

    def test_cestino_in_tabella_e_popup(self):
        padre = _mov("C", self.ieri)
        _mov("O", self.oggi, rif_op=padre.id_registrazione)
        html = self.client.get(reverse("rentri_elenco") + "?view=lista").content.decode()
        self.assertIn('id="rn-rimuovi"', html)
        self.assertIn(reverse("rentri_rimuovi", args=[padre.pk]), html)
        self.assertIn('data-perche="ha movimenti collegati"', html)

    def test_non_gestore_403(self):
        c = _mov("C", self.ieri)
        utente = User.objects.create_user(username="rentri-lettore", password="x")
        self.client.force_login(utente)
        r = self.client.post(reverse("rentri_rimuovi", args=[c.pk]), {"modo": "elimina", "motivo": "prova eliminazione"})
        self.assertIn(r.status_code, (302, 403))
        self.assertTrue(RegistroRifiuti.objects.filter(pk=c.pk).exists())


class ConsolidaFiloTests(_Base):
    def test_consolida_tutto_il_filo_tranne_incomplete(self):
        c1 = _mov("C", self.ieri)
        c2 = _mov("C", self.ieri)
        o = _mov("O", self.oggi, rif_op=f"{c1.id_registrazione}, {c2.id_registrazione}")
        m = _mov("M", self.oggi, rif_op=o.id_registrazione)
        incompleta = _mov("R", self.oggi, rif_op=o.id_registrazione, quantita=None)
        estraneo = _mov("C", self.ieri, codice="12 01 01")

        anteprima = self.client.get(reverse("rentri_consolida_filo", args=[m.pk]) + "?next=/rentri/elenco/")
        self.assertEqual(anteprima.status_code, 200)
        self.assertContains(anteprima, "Consolida 4 righe")
        self.assertContains(anteprima, "manca la quantità")

        r = self.client.post(reverse("rentri_consolida_filo", args=[m.pk]), {"next": "/rentri/elenco/"})
        self.assertRedirects(r, "/rentri/elenco/", fetch_redirect_response=False)
        for reg in (c1, c2, o, m):
            reg.refresh_from_db()
            self.assertTrue(reg.salva, reg.id_registrazione)
        incompleta.refresh_from_db()
        estraneo.refresh_from_db()
        self.assertFalse(incompleta.salva)
        self.assertFalse(estraneo.salva)

    def test_elenco_mostra_pulsante_filo(self):
        c = _mov("C", self.ieri, salva=True)
        _mov("O", self.oggi, rif_op=c.id_registrazione)
        html = self.client.get(reverse("rentri_elenco") + "?view=famiglie").content.decode()
        self.assertIn("Consolida filo · 1/2", html)

    def test_scheda_e_scadenzario_usano_il_filo(self):
        c = _mov("C", self.ieri)
        self.assertContains(self.client.get(reverse("rentri_dettaglio", args=[c.pk])), "Consolida filo…")
        self.assertContains(self.client.get(reverse("rentri_scadenzario")),
                            reverse("rentri_consolida_filo", args=[c.pk]))

    def test_orfani_stesso_rif(self):
        o1 = _mov("O", self.ieri, rif_op="2020/9999")
        o2 = _mov("M", self.oggi, rif_op="2020/9999")
        self.client.post(reverse("rentri_consolida_filo", args=[o1.pk]))
        o2.refresh_from_db()
        self.assertTrue(o2.salva)
