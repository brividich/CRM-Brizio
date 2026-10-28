"""Robustezza del registro: validazione, consolidamento, annullamento, SharePoint, giacenze, verifica."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import RegistroRifiuti, RentriImpostazioni

User = get_user_model()


def _mov(tipo, giorno, codice="15 01 06", quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=codice,
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "kg"), **extra,
    )


class _Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-rob", email="rob@example.com", password="x")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.ieri = self.oggi - timedelta(days=1)

    def post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")


class QuantitaDaTestoTests(TestCase):
    def test_formati_italiani(self):
        from .validazione import quantita_da_testo

        self.assertEqual(quantita_da_testo("1,5"), Decimal("1.500"))
        self.assertEqual(quantita_da_testo("1.234,5"), Decimal("1234.500"))
        self.assertEqual(quantita_da_testo("12.25"), Decimal("12.250"))
        self.assertIsNone(quantita_da_testo(""))
        with self.assertRaises(ValueError):
            quantita_da_testo("abc")

    def test_cer(self):
        from .validazione import cer_pericoloso, normalizza_cer

        self.assertEqual(normalizza_cer("15 01 06 - imballaggi"), "150106")
        self.assertEqual(normalizza_cer("12.01.01"), "120101")
        self.assertTrue(cer_pericoloso("13 02 05* oli"))
        self.assertFalse(cer_pericoloso("150106"))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ValidazioneInserimentoTests(_Base):
    def _carico(self, **override):
        payload = {"data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "10", "unita": "kg"}
        payload.update(override)
        return self.post_json(reverse("rentri_carico"), payload)

    def test_carico_valido_con_virgola(self):
        r = self._carico(quantita="2,5")
        self.assertEqual(r.status_code, 200, r.content)
        reg = RegistroRifiuti.objects.get()
        self.assertEqual(reg.quantita, Decimal("2.500"))
        self.assertEqual(reg.origine, "portale")
        self.assertEqual(reg.carico_scarico, "C")

    def test_regole_di_campo(self):
        casi = [
            ({"codice": "XX"}, "Codice CER non valido"),
            ({"quantita": "0"}, "maggiore di zero"),
            ({"quantita": "-3"}, "maggiore di zero"),
            ({"quantita": ""}, "obbligatoria"),
            ({"unita": ""}, "unità di misura"),
            ({"data": (self.oggi + timedelta(days=3)).isoformat()}, "futuro"),
            ({"codice": "13 02 05*"}, "pericolo"),
        ]
        for override, atteso in casi:
            with self.subTest(override=override):
                r = self._carico(**override)
                self.assertEqual(r.status_code, 400, r.content)
                self.assertIn(atteso, r.json()["error"])
        self.assertEqual(RegistroRifiuti.objects.count(), 0)

    def test_id_registrazione_dal_modulo_ignorato(self):
        r = self._carico(id_registrazione="2020/999")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(RegistroRifiuti.objects.get().id_registrazione, "2020/999")

    def test_scarico_rif_op_verificato(self):
        c = _mov("C", self.ieri - timedelta(days=5), quantita=10)
        altro = _mov("C", self.ieri - timedelta(days=5), codice="20 01 01", quantita=10)
        url = reverse("rentri_scarico_originale")
        base = {"data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "5", "unita": "kg"}

        r = self.post_json(url, {**base, "rif_op": "2099/001"})
        self.assertIn("inesistente", r.json()["error"])
        r = self.post_json(url, {**base, "rif_op": altro.id_registrazione})
        self.assertIn("codice CER diverso", r.json()["error"])
        r = self.post_json(url, {**base, "rif_op": c.id_registrazione, "data": (c.data - timedelta(days=1)).isoformat()})
        self.assertIn("precedere", r.json()["error"])

        r = self.post_json(url, {**base, "rif_op": c.id_registrazione})
        self.assertEqual(r.status_code, 200, r.content)
        # Lo stesso carico non si scarica due volte.
        r = self.post_json(url, {**base, "rif_op": c.id_registrazione})
        self.assertEqual(r.status_code, 400)
        self.assertIn("già uno scarico", r.json()["error"])

    def test_scarico_oltre_giacenza(self):
        c = _mov("C", self.ieri, quantita=10)
        o = _mov("O", self.ieri, quantita=10, rif_op=c.id_registrazione)
        r = self.post_json(reverse("rentri_scarico_effettivo"), {
            "data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "12", "unita": "kg",
            "rif_op": o.id_registrazione,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("oltre la giacenza", r.json()["error"])

    def test_rettifica_negativa_ammessa(self):
        c = _mov("C", self.ieri, quantita=10)
        o = _mov("O", self.ieri, quantita=10, rif_op=c.id_registrazione)
        m = _mov("M", self.ieri, quantita=10, rif_op=o.id_registrazione)
        r = self.post_json(reverse("rentri_rettifica_scarico"), {
            "data": self.oggi.isoformat(), "codice": "15 01 06", "rettifica_scarico": "-1,5", "unita": "kg",
            "rif_op": m.id_registrazione,
        })
        self.assertEqual(r.status_code, 200, r.content)

    def test_candidati_m_escludono_o_gia_scaricato(self):
        c = _mov("C", self.ieri, quantita=10)
        o = _mov("O", self.ieri, quantita=10, rif_op=c.id_registrazione)
        r = self.client.get(reverse("rentri_api_candidati_rif_op"), {"tipo": "M", "codice": "15 01 06"})
        self.assertEqual([x["id_registrazione"] for x in r.json()["candidati"]], [o.id_registrazione])
        _mov("M", self.ieri, quantita=10, rif_op=o.id_registrazione)  # il wizard salva l'id della O
        r = self.client.get(reverse("rentri_api_candidati_rif_op"), {"tipo": "M", "codice": "15 01 06"})
        self.assertEqual(r.json()["candidati"], [])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ConsolidaAnnullaTests(_Base):
    def test_consolidata_non_si_modifica(self):
        c = _mov("C", self.ieri)
        r = self.client.post(reverse("rentri_consolida", args=[c.pk]))
        self.assertEqual(r.status_code, 302)
        c.refresh_from_db()
        self.assertTrue(c.salva)
        self.assertIsNotNone(c.consolidato_il)

        r = self.post_json(reverse("rentri_modifica", args=[c.pk]), {"data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "99"})
        self.assertEqual(r.status_code, 409)
        c.refresh_from_db()
        self.assertEqual(c.quantita, Decimal("10"))
        r = self.client.get(reverse("rentri_modifica", args=[c.pk]))
        self.assertRedirects(r, reverse("rentri_dettaglio", args=[c.pk]), fetch_redirect_response=False)

    def test_consolida_richiede_dati_minimi(self):
        o = RegistroRifiuti.objects.create(tipo="O", data=self.ieri, codice="15 01 06")
        self.client.post(reverse("rentri_consolida", args=[o.pk]))
        o.refresh_from_db()
        self.assertFalse(o.salva)

    def test_trasmesso_dopo_consolidamento(self):
        c = _mov("C", self.ieri, salva=True)
        self.client.post(reverse("rentri_trasmesso", args=[c.pk]), {"trasmesso": "1"})
        c.refresh_from_db()
        self.assertTrue(c.rentri_si_no)

    def test_annulla_con_figli_bloccato_poi_ammesso(self):
        c = _mov("C", self.ieri, quantita=10)
        o = _mov("O", self.ieri, quantita=10, rif_op=c.id_registrazione)
        self.client.post(reverse("rentri_annulla", args=[c.pk]), {"motivo": "carico sbagliato"})
        c.refresh_from_db()
        self.assertFalse(c.annullato)

        self.client.post(reverse("rentri_annulla", args=[o.pk]), {"motivo": "scarico sbagliato"})
        self.client.post(reverse("rentri_annulla", args=[c.pk]), {"motivo": "carico sbagliato"})
        c.refresh_from_db()
        self.assertTrue(c.annullato)
        self.assertEqual(RegistroRifiuti.objects.count(), 2)

        from .giacenze import giacenze_per_cer
        self.assertEqual(giacenze_per_cer(), [])
        r = self.client.get(reverse("rentri_api_candidati_rif_op"), {"tipo": "O", "codice": "15 01 06"})
        self.assertEqual(r.json()["candidati"], [])

    def test_annullati_fuori_dall_elenco_salvo_richiesta(self):
        c = _mov("C", self.ieri, annullato=True, motivo_annullamento="doppio")
        r = self.client.get(reverse("rentri_elenco"), {"view": "lista"})
        self.assertNotContains(r, c.id_registrazione)
        r = self.client.get(reverse("rentri_elenco"), {"view": "lista", "annullati": "1"})
        self.assertContains(r, "ANNULLATO")

    def test_dettaglio_mostra_storico(self):
        r = self.post_json(reverse("rentri_carico"), {"data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "4", "unita": "kg"})
        pk = r.json()["id"]
        r = self.client.get(reverse("rentri_dettaglio", args=[pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "BOZZA")
        self.assertContains(r, "Storico modifiche")

    def test_utente_base_non_annulla(self):
        from core.models import UserOnboarding

        c = _mov("C", self.ieri)
        base = User.objects.create_user(username="rentri-base-rob", password="x")
        UserOnboarding.objects.create(user=base, completed=True, completed_at=timezone.now())
        self.client.force_login(base)
        r = self.client.post(reverse("rentri_annulla", args=[c.pk]), {"motivo": "prova prova"})
        self.assertEqual(r.status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SharePointNonBloccanteTests(_Base):
    def test_errore_sharepoint_non_duplica(self):
        with mock.patch("rentri.sharepoint._graph_configured", return_value=True), \
                mock.patch("rentri.sharepoint._graph_create", side_effect=ConnectionError("rete giù")):
            r = self.post_json(reverse("rentri_carico"), {"data": self.ieri.isoformat(), "codice": "15 01 06", "quantita": "4", "unita": "kg"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("SharePoint", r.json()["avviso_sync"])
        reg = RegistroRifiuti.objects.get()
        self.assertIn("non raggiungibile", reg.sync_errore)

    def test_invio_riuscito_pulisce_errore(self):
        from .sharepoint import sincronizza

        reg = _mov("C", self.ieri, sync_errore="vecchio errore")
        with mock.patch("rentri.sharepoint._graph_configured", return_value=True), \
                mock.patch("rentri.sharepoint._graph_create", return_value=(True, {"id": "77"})):
            self.assertTrue(sincronizza(reg))
        reg.refresh_from_db()
        self.assertEqual(reg.sync_errore, "")
        self.assertEqual(reg.sharepoint_item_id, "77")

    def test_pull_non_tocca_consolidati_e_non_indovina_il_tipo(self):
        from . import sharepoint

        reg = _mov("C", self.ieri, quantita=10, salva=True, sharepoint_item_id="1")
        futuro = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        items = [
            {"id": "1", "fields": {"Data": self.ieri.isoformat(), "Quantit_x00e0_": 999, "Aggiornato": futuro}},
            {"id": "2", "fields": {"Data": self.ieri.isoformat(), "Carico_x002f_Scarico": ""}},
            {"id": "3", "fields": {"Data": self.ieri.isoformat(), "Carico_x002f_Scarico": "M", "Codice": "15 01 06"}},
        ]
        with mock.patch.object(sharepoint, "_graph_get_all", return_value=items):
            esito = sharepoint.pull("prova")
        reg.refresh_from_db()
        self.assertEqual(reg.quantita, Decimal("10"))
        self.assertEqual(esito["created"], 1)
        self.assertEqual(esito["skipped"], 1)
        self.assertEqual(RegistroRifiuti.objects.get(sharepoint_item_id="3").tipo, "M")


class GiacenzeFifoTests(TestCase):
    def test_eta_dal_carico_aperto_non_dal_primo(self):
        from .giacenze import giacenze_per_cer

        oggi = timezone.localdate()
        _mov("C", oggi - timedelta(days=200), quantita=100)
        _mov("C", oggi - timedelta(days=10), quantita=50)
        _mov("M", oggi - timedelta(days=5), quantita=100)
        g = giacenze_per_cer()[0]
        self.assertEqual(g.giacenza, 50.0)
        self.assertEqual(g.giorni_giacenza, 10)
        self.assertEqual(g.primo_carico, oggi - timedelta(days=200))

    def test_criterio_quantitativo(self):
        from .giacenze import criterio_quantitativo, giacenze_per_cer, soglie_deposito

        oggi = timezone.localdate()
        _mov("C", oggi, codice="13 02 05*", quantita=12, unita="m3", pericolosita="HP14")
        _mov("C", oggi, codice="12 01 09", quantita=4000, unita="l")
        _mov("C", oggi, codice="15 01 06", quantita=300, unita="kg")
        crit = criterio_quantitativo(giacenze_per_cer(), soglie_deposito())
        self.assertEqual(crit["m3_totale"], 16.0)
        self.assertEqual(crit["m3_pericolosi"], 12.0)
        self.assertTrue(crit["oltre"])  # 12 m³ pericolosi oltre i 10
        self.assertEqual(crit["non_convertibili"], 1)

    def test_unita_miste_segnalate(self):
        from .giacenze import giacenze_per_cer

        oggi = timezone.localdate()
        _mov("C", oggi, quantita=10, unita="kg")
        _mov("C", oggi, quantita=10, unita="l")
        self.assertEqual(giacenze_per_cer()[0].unita, "misto")


class VerificaTests(TestCase):
    def _sezione(self, key):
        from .verifica import verifica_registro

        return next(s for s in verifica_registro() if s["key"] == key)["righe"]

    def test_controlli(self):
        oggi = timezone.localdate()
        _mov("M", oggi - timedelta(days=3), quantita=5, rif_op="2099/777")  # orfano + saldo negativo
        c = _mov("C", oggi - timedelta(days=150), codice="20 01 01", quantita=10)
        o = _mov("O", oggi - timedelta(days=120), codice="20 01 01", quantita=10, rif_op=c.id_registrazione)
        tardivo = _mov("C", oggi - timedelta(days=40), codice="08 01 11", quantita=1, origine="portale")
        storico = _mov("C", oggi - timedelta(days=40), codice="08 01 11", quantita=1, origine="storico")

        self.assertEqual(len(self._sezione("orfani")), 1)
        self.assertEqual(len(self._sezione("saldo")), 1)
        self.assertEqual([r["pk"] for r in self._sezione("quarta_copia")], [o.pk])
        tardive = [r["pk"] for r in self._sezione("tardive")]
        self.assertIn(tardivo.pk, tardive)
        self.assertNotIn(storico.pk, tardive)

    def test_pagina_e_comando(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("rentri_verifica", "--solo-conteggi", stdout=out)
        self.assertIn("Totale anomalie", out.getvalue())

    @override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_pagina(self):
        admin = User.objects.create_superuser(username="rentri-ver", email="ver@example.com", password="x")
        self.client.force_login(admin)
        r = self.client.get(reverse("rentri_verifica"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Verifica del registro RENTRI")
        r = self.client.get(reverse("rentri_verifica"), {"export": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")


class ImportTuttoONienteTests(TestCase):
    def _riga(self, n, **extra):
        base = {
            "riga": n, "_data_iso": "2026-01-0%d" % n, "tipo": "C", "id_reg": f"2026/90{n}",
            "codice": "15 01 06", "quantita": "1.5", "rettifica": "", "pericolosita": "", "note": "",
            "rentri_si_no": False, "arrivo_fir": "", "inserito_da": "", "rif_op": "", "esiste": False,
        }
        base.update(extra)
        return base

    def test_una_riga_rotta_annulla_tutto(self):
        from .importazione import ImportAnnullato, importa_righe

        with self.assertRaises(ImportAnnullato):
            importa_righe([self._riga(1), self._riga(2, _data_iso="non-una-data")])
        self.assertEqual(RegistroRifiuti.objects.count(), 0)

    def test_import_e_avvisi(self):
        from .importazione import importa_righe

        esito = importa_righe([self._riga(1), self._riga(1), self._riga(2, tipo="O", rif_op="2026/901, 2025/404")])
        self.assertEqual(esito["created"], 2)
        self.assertEqual(esito["skipped"], 1)  # stessa riga due volte nel file
        self.assertEqual(len(esito["avvisi"]), 1)
        self.assertEqual(set(RegistroRifiuti.objects.values_list("origine", flat=True)), {"import"})


class DestinatariAvvisoTests(TestCase):
    def test_referenti_impostazioni(self):
        from .management.commands.check_rentri_scadenze import _destinatari

        cfg = RentriImpostazioni.get_singleton()
        cfg.responsabili = [{"nome": "Referente A", "email": "a@example.com"}, {"nome": "B", "email": "b@example.com"}]
        cfg.save()
        self.assertEqual(_destinatari(None), ["a@example.com", "b@example.com"])
        self.assertEqual(_destinatari("x@example.com"), ["x@example.com"])
