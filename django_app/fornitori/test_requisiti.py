"""Requisiti di sicurezza dei fornitori in sede (art. 26 D.Lgs. 81/2008): stato,
scheda, accessi esterni, avviso a RSPP/ASPP (solo notifica) e scadenzario."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Fornitore, FornitoreDocumento

from . import requisiti
from .guestportal import Accesso


def _doc(fornitore, tipo, scadenza):
    d = FornitoreDocumento(fornitore=fornitore, nome=f"{tipo} esempio", tipo=tipo, data_scadenza=scadenza)
    d.file.save(f"{tipo.lower()}.pdf", ContentFile(b"%PDF-1.4 esempio"), save=False)
    d.save()
    return d


class StatoRequisitiTests(TestCase):
    def setUp(self):
        self.oggi = date(2026, 3, 10)
        self.f = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl", accede_in_sede=True)

    def test_non_richiesto_se_non_lavora_in_sede(self):
        f = Fornitore.objects.create(ragione_sociale="Solo Materiali Spa")
        self.assertEqual(requisiti.stato_fornitore(f, self.oggi).esito, requisiti.ESITO_NON_RICHIESTO)

    def test_mancanti_scaduti_in_scadenza_e_ok(self):
        s = requisiti.stato_fornitore(self.f, self.oggi)
        self.assertEqual(s.esito, requisiti.ESITO_NON_IN_REGOLA)
        self.assertIn("DURC mancante", s.riassunto)
        _doc(self.f, "VISURA", None)
        _doc(self.f, "IDONEITA", None)
        _doc(self.f, "DUVRI", self.oggi + timedelta(days=200))
        _doc(self.f, "DURC", self.oggi - timedelta(days=1))
        s = requisiti.stato_fornitore(self.f, self.oggi)
        self.assertEqual(s.esito, requisiti.ESITO_NON_IN_REGOLA)
        self.assertIn("DURC scaduto il 09/03/2026", s.riassunto)
        # Il DURC rinnovato vale più del vecchio scaduto; scade entro 30 giorni → in scadenza.
        _doc(self.f, "DURC", self.oggi + timedelta(days=20))
        self.assertEqual(requisiti.stato_fornitore(self.f, self.oggi).esito, requisiti.ESITO_IN_SCADENZA)
        _doc(self.f, "DURC", self.oggi + timedelta(days=120))
        s = requisiti.stato_fornitore(self.f, self.oggi)
        # La polizza RCT manca ma è solo consigliata: resta in regola.
        self.assertEqual(s.esito, requisiti.ESITO_OK)
        self.assertEqual([v.stato for v in s.voci if v.tipo == "RCT"], ["mancante"])

    def test_abbinamento_per_ragione_sociale(self):
        a = SimpleNamespace(azienda="DITTA ESEMPIO S.R.L.", ditta_gp_id=None, fornitore_id=None)
        requisiti.abbina_fornitori([a])
        self.assertEqual(a.fornitore_id, self.f.pk)


class PagineTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("forn_req", password="x"))
        self.f = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl", accede_in_sede=True)

    def test_scheda_ed_elenco_mostrano_lo_stato(self):
        r = self.client.get(reverse("fornitori:fornitore_detail", args=[self.f.pk]))
        self.assertContains(r, "Requisiti per lavorare in sede")
        self.assertContains(r, "Documenti non in regola")
        r = self.client.get(reverse("fornitori:fornitori_list"))
        self.assertContains(r, "Documenti non in regola")

    def test_accessi_esterni_mostra_la_ditta_non_in_regola(self):
        accesso = Accesso(visita_id=5, stato="CHECKEDIN", tipo="SUPPLIER", nome="Paolo Verdi", azienda="Ditta Esempio Srl",
                          referente="", motivo="", badge="", ingresso=datetime.now(), uscita=None)
        with patch("fornitori.guestportal.db_configurato", return_value=True), \
             patch("fornitori.guestportal.presenti_ora", return_value=[accesso]), \
             patch("fornitori.guestportal.storico", return_value=([], False)):
            r = self.client.get(reverse("fornitori:accessi_esterni"))
        self.assertContains(r, "Documenti non in regola")
        self.assertContains(r, "DURC mancante")


class AvvisoIngressoTests(TestCase):
    def setUp(self):
        self.f = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl", accede_in_sede=True)
        self.accesso = Accesso(visita_id=9, stato="CHECKEDIN", tipo="SUPPLIER", nome="Paolo Verdi",
                               azienda="Ditta Esempio Srl", referente="", motivo="", badge="",
                               ingresso=datetime.now(), uscita=None)

    def test_notifica_una_volta_e_mai_mail(self):
        from . import tasks
        from .models import AvvisoIngressoNonInRegola

        with patch("fornitori.guestportal.db_configurato", return_value=True), \
             patch("fornitori.guestportal.presenti_ora", side_effect=lambda: [self.accesso]), \
             patch.object(tasks, "_destinatari", return_value=[41, 42]), \
             patch("core.notifiche.invia_notifica") as notifica, \
             patch("core.email_utils.send_hub_mail") as mail:
            e1 = tasks.avvisa_ingressi_non_in_regola()
            e2 = tasks.avvisa_ingressi_non_in_regola()
        self.assertEqual(e1["avvisati"], 1)
        self.assertEqual(e2["gia_avvisati"], 1)
        self.assertEqual(notifica.call_count, 2)  # due destinatari, una sola volta
        self.assertIn("DURC mancante", notifica.call_args.kwargs["messaggio"])
        mail.assert_not_called()
        self.assertEqual(AvvisoIngressoNonInRegola.objects.count(), 1)

    def test_ditta_in_regola_nessun_avviso(self):
        from . import tasks

        for tipo in ("VISURA", "IDONEITA", "DURC", "DUVRI"):
            _doc(self.f, tipo, date.today() + timedelta(days=100))
        with patch("fornitori.guestportal.db_configurato", return_value=True), \
             patch("fornitori.guestportal.presenti_ora", return_value=[self.accesso]), \
             patch("core.notifiche.invia_notifica") as notifica:
            self.assertEqual(tasks.avvisa_ingressi_non_in_regola()["non_in_regola"], 0)
        notifica.assert_not_called()


class ScadenzarioTests(TestCase):
    def test_documento_piu_recente_per_tipo(self):
        from dashboard.scadenze_providers import ScadenzeContext
        from scadenzario import fonti_moduli as fm

        f = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl", accede_in_sede=True)
        oggi = date.today()
        _doc(f, "DURC", oggi - timedelta(days=5))
        _doc(f, "DURC", oggi + timedelta(days=15))
        ctx = ScadenzeContext.build(SimpleNamespace(user=SimpleNamespace(is_authenticated=True, is_superuser=True, id=None),
                                                    method="GET", legacy_user=None, session={}, GET={}), sistema=True)
        voci = fm.collect_fornitori(ctx)
        self.assertEqual([(v.elemento, v.data_scadenza) for v in voci], [("DURC", oggi + timedelta(days=15))])
