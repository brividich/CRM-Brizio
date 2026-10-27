"""Registro OFI: responsabile, cronologia, avanzamento PDCA guidato, allegati, cruscotto.

Nessun dato reale: utenti e voci sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from gestione_specifiche import registro_ofi as R
from gestione_specifiche.models import RegistroOFI, RegistroOFIAllegato, RegistroOFIEvento


def _voce(**kw):
    dati = {"numero": R.prossimo_numero(), "data_apertura": timezone.localdate(), "processo": "Produzione"}
    dati.update(kw)
    return RegistroOFI.objects.create(**dati)


class AvanzamentoTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("resp_ofi", password="x", email="resp@example.com")

    def test_serve_il_testo_della_fase_per_avanzare(self):
        v = _voce()
        with self.assertRaises(R.AvanzamentoNonValido):
            R.avanza_fase(v, utente=self.u)
        self.assertEqual(R.avanza_fase(v, utente=self.u, testo="Piano"), RegistroOFI.FASE_DO)
        v.refresh_from_db()
        self.assertEqual(v.plan, "Piano")
        ev = v.eventi.get()
        self.assertEqual((ev.tipo, ev.utente, ev.a), (RegistroOFIEvento.TIPO_FASE, self.u, "Do (attua)"))

    def test_testo_gia_compilato_basta(self):
        v = _voce(fase=RegistroOFI.FASE_DO, do="Fatto")
        self.assertEqual(R.avanza_fase(v, utente=self.u), RegistroOFI.FASE_CHECK)

    def test_act_chiude_con_data(self):
        oggi = timezone.localdate()
        v = _voce(fase=RegistroOFI.FASE_ACT, verifica="ok", act="Consolidato")
        R.avanza_fase(v, utente=self.u, oggi=oggi)
        v.refresh_from_db()
        self.assertTrue(v.is_chiuso)
        self.assertEqual(v.data_chiusura, oggi)
        with self.assertRaises(R.AvanzamentoNonValido):
            R.avanza_fase(v, utente=self.u, testo="ancora")

    def test_car_aperta_impedisce_la_chiusura(self):
        v = _voce(fase=RegistroOFI.FASE_ACT, act="x")
        with patch.object(R, "car_aperta", return_value=object()):
            with self.assertRaises(R.AvanzamentoNonValido):
                R.avanza_fase(v, utente=self.u)
        v.refresh_from_db()
        self.assertEqual(v.fase, RegistroOFI.FASE_ACT)

    def test_riapri_richiede_motivo_e_torna_in_plan(self):
        v = _voce(fase=RegistroOFI.FASE_CHIUSO, data_chiusura=timezone.localdate(), verifica="x")
        with self.assertRaises(R.AvanzamentoNonValido):
            R.riapri_non_efficace(v, utente=self.u, motivo=" ")
        R.riapri_non_efficace(v, utente=self.u, motivo="Il problema si è ripresentato")
        v.refresh_from_db()
        self.assertEqual(v.fase, RegistroOFI.FASE_PLAN)
        self.assertIsNone(v.data_chiusura)
        self.assertEqual(v.eventi.get().tipo, RegistroOFIEvento.TIPO_RIAPERTA)

    def test_riapri_non_ammesso_in_plan(self):
        with self.assertRaises(R.AvanzamentoNonValido):
            R.riapri_non_efficace(_voce(), utente=self.u, motivo="x")


class CronologiaModificheTests(TestCase):
    def test_cambi_di_fase_scadenza_e_responsabile(self):
        u = get_user_model().objects.create_user("mod_ofi", password="x")
        v = _voce()
        prima = R.fotografia(v)
        v.fase = RegistroOFI.FASE_DO
        v.data_richiesta = timezone.localdate()
        v.responsabile = u
        v.save()
        R.registra_modifiche(prima, v, u)
        self.assertEqual(sorted(v.eventi.values_list("tipo", flat=True)),
                         sorted([RegistroOFIEvento.TIPO_FASE, RegistroOFIEvento.TIPO_SCADENZA,
                                 RegistroOFIEvento.TIPO_RESPONSABILE]))

    def test_modifica_generica(self):
        v = _voce()
        R.registra_modifiche(R.fotografia(v), v, None)
        self.assertEqual(v.eventi.get().tipo, RegistroOFIEvento.TIPO_MODIFICA)


@override_settings(GESTIONE_SPECIFICHE={"OFI_REMINDER_EMAILS": "qualita@example.com"})
class SollecitoTests(TestCase):
    def test_sollecito_al_responsabile_e_alla_qualita(self):
        u = get_user_model().objects.create_user("sol_ofi", password="x", email="resp@example.com")
        v = _voce(responsabile=u, data_richiesta=timezone.localdate() - timedelta(days=1))
        with patch("core.email_utils.send_hub_mail") as invia:
            esito = R.invia_reminder_ofi()
        self.assertEqual(esito["inviati"], 1)
        self.assertEqual(invia.call_args.kwargs["to"], ["resp@example.com", "qualita@example.com"])
        self.assertTrue(v.eventi.filter(tipo=RegistroOFIEvento.TIPO_SOLLECITO).exists())


class CruscottoTests(TestCase):
    def test_numeri_principali(self):
        oggi = timezone.localdate()
        u = get_user_model().objects.create_user("cr_ofi", password="x")
        _voce(tipo=RegistroOFI.TIPO_NC, data_richiesta=oggi - timedelta(days=3), responsabile=u)
        _voce(data_apertura=oggi - timedelta(days=200), norma_en9100=True)
        _voce(data_apertura=oggi - timedelta(days=20), fase=RegistroOFI.FASE_CHIUSO,
              data_chiusura=oggi - timedelta(days=10), data_richiesta=oggi - timedelta(days=5))
        c = R.cruscotto(oggi=oggi)
        self.assertEqual((c["totale"], c["aperte"], c["nc_aperte"], c["scadute"]), (3, 2, 1, 1))
        self.assertEqual(c["senza_responsabile"], 1)
        self.assertEqual(c["giorni_medi_chiusura"], 10)
        self.assertEqual(c["pct_in_tempo"], 100)
        self.assertEqual({r["etichetta"]: r["n"] for r in c["anzianita"]}["Oltre 180 giorni"], 1)
        self.assertEqual(c["per_norma"], [{"nome": "9100", "n": 1}])
        self.assertEqual(len(c["andamento"]), 12)
        self.assertEqual(c["ricorrenti"], [{"nome": "Produzione", "n": 3}])


class VisteTests(TestCase):
    """Permessi delle viste: il responsabile agisce sulla propria voce, gli altri no."""

    def setUp(self):
        User = get_user_model()
        self.resp = User.objects.create_user("vista_resp", password="x")
        self.altro = User.objects.create_user("vista_altro", password="x")
        for u in (self.resp, self.altro):
            UserOnboarding.objects.create(user=u, completed=True)
        self.voce = _voce(responsabile=self.resp)
        # Tutti leggono il registro (rotta consentita dal middleware); nessuno ha «registroofi.add»:
        # il controllo che interessa qui è quello della view sul responsabile.
        lettura = patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
        lettura.start()
        self.addCleanup(lettura.stop)

    def _post(self, user, nome, dati=None, **kw):
        self.client.force_login(user)
        with patch("registro_ofi.views.request_has_permission_code", return_value=False):
            return self.client.post(reverse(f"registro_ofi:{nome}", args=[self.voce.pk]), dati or {}, **kw)

    def test_altro_utente_non_avanza(self):
        r = self._post(self.altro, "avanza", {"testo": "x"})
        self.assertEqual(r.status_code, 403)
        self.voce.refresh_from_db()
        self.assertEqual(self.voce.fase, RegistroOFI.FASE_PLAN)

    def test_responsabile_avanza(self):
        r = self._post(self.resp, "avanza", {"testo": "Piano fatto"})
        self.assertEqual(r.status_code, 302)
        self.voce.refresh_from_db()
        self.assertEqual(self.voce.fase, RegistroOFI.FASE_DO)

    def test_allegato_caricato_e_scaricato(self):
        f = SimpleUploadedFile("evidenza.pdf", b"%PDF-1.4 sintetico", content_type="application/pdf")
        with patch("core.upload_mime.sniff_upload_mime", return_value="application/pdf"):
            r = self._post(self.resp, "allegato_carica", {"file": f, "descrizione": "Verbale"})
        self.assertEqual(r.status_code, 302)
        al = RegistroOFIAllegato.objects.get(voce=self.voce)
        self.assertEqual((al.nome, al.descrizione, len(al.sha256)), ("evidenza.pdf", "Verbale", 64))
        self.assertTrue(self.voce.eventi.filter(tipo=RegistroOFIEvento.TIPO_ALLEGATO).exists())
        r = self.client.get(reverse("registro_ofi:allegato_scarica", args=[self.voce.pk, al.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 sintetico")
        al.file.delete(save=False)

    def test_altro_utente_non_carica_allegati(self):
        f = SimpleUploadedFile("evidenza.pdf", b"%PDF-1.4", content_type="application/pdf")
        r = self._post(self.altro, "allegato_carica", {"file": f})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(RegistroOFIAllegato.objects.exists())

    def test_dettaglio_e_cruscotto_si_aprono(self):
        R.registra_evento(self.voce, RegistroOFIEvento.TIPO_CREATA, utente=self.resp, a="Plan")
        self.client.force_login(self.resp)
        with patch("registro_ofi.views.request_has_permission_code", return_value=False):
            r = self.client.get(reverse("registro_ofi:dettaglio", args=[self.voce.pk]))
            self.assertContains(r, "Passa a «Do (attua)»")
            self.assertContains(r, "Cronologia")
            # Il vecchio cruscotto porta alla dashboard; chi non consulta il registro vede il suo lavoro.
            r = self.client.get(reverse("registro_ofi:cruscotto"), follow=True)
            self.assertContains(r, "Il mio lavoro")
            self.assertContains(r, f"{self.voce.tipo} {self.voce.numero}")
            self.assertNotContains(r, "Da dove arrivano le voci")
            r = self.client.get(reverse("registro_ofi:mie"))
            self.assertContains(r, reverse("registro_ofi:dettaglio", args=[self.voce.pk]))
            r = self.client.get(reverse("registro_ofi:lista") + "?mie=1")
            self.assertContains(r, "Le mie voci")

    def test_allegato_tipo_non_ammesso(self):
        f = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")
        self._post(self.resp, "allegato_carica", {"file": f})
        self.assertFalse(RegistroOFIAllegato.objects.exists())
