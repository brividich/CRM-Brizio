"""Mail dei moduli in Automazioni: flussi su evento nuovi e impostazioni del modulo modificabili da entrambe le parti."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from automazioni.event_notifications import EVENT_NOTIFICATIONS
from automazioni.mail_modulo import _impostazioni, campi
from automazioni.managed_flows import catalog
from core.models import SiteConfig

User = get_user_model()

NUOVI = (
    "assenze_sollecito_manuale", "reception_invito", "reception_conferma_richiesta", "reception_nuova_richiesta",
    "reception_rifiuto", "sgi_audit_comunicazione", "sgi_audit_rapporto", "kickoff_assegnazione_attivita",
    "kickoff_convocazione", "kickoff_minuta", "kickoff_annullamento", "anagrafica_avviso_it_ingresso",
    "suggestion_corner_comunicazione_cliente",
)


class CatalogoTests(TestCase):
    def test_flussi_nuovi_nel_catalogo(self):
        codici = {e["code"] for e in EVENT_NOTIFICATIONS}
        for codice in NUOVI:
            self.assertIn(codice, codici)

    def test_funzioni_decorate_con_il_loro_flusso(self):
        import importlib

        for e in EVENT_NOTIFICATIONS:
            if e["code"] not in NUOVI:
                continue
            modulo = importlib.import_module(e["source"].removesuffix(".py").replace("/", "."))
            funzione = getattr(modulo, e["func"])
            self.assertTrue(hasattr(funzione, "__wrapped__"), e["code"])

    def test_impostazioni_solo_per_flussi_censiti(self):
        self.assertFalse(set(_impostazioni()) - set(catalog()))


class FlussoSpentoTests(TestCase):
    def setUp(self):
        from automazioni.managed_flows import install_flows

        install_flows()

    def _spegni(self, codice):
        from automazioni.models import ManagedFlow

        rule = ManagedFlow.objects.get(code=codice).rule
        rule.is_active = False
        rule.save(update_fields=["is_active"])

    def test_suggestion_corner_cliente_non_parte_se_spento(self):
        from types import SimpleNamespace

        from suggestion_corner.notifications import notifica_cliente_sms

        seg = SimpleNamespace(pk=3, cliente_email="cli@x.local", cliente_nome="Cliente",
                              reparto_provenienza_id=None, opportunity="Testo")
        self.assertEqual(notifica_cliente_sms(seg), 1)
        self.assertEqual(len(mail.outbox), 1)
        self._spegni("suggestion_corner_comunicazione_cliente")
        self.assertEqual(notifica_cliente_sms(seg), 0)
        self.assertEqual(len(mail.outbox), 1)


class ImpostazioniBidirezionaliTests(TestCase):
    def setUp(self):
        from automazioni.managed_flows import install_flows

        install_flows()
        self.admin = User.objects.create_superuser("mm_admin", "mm@x.local", "x")
        self.client.force_login(self.admin)

    def _salva(self, codice, dati):
        return self.client.post(reverse("admin_portale:automazioni_pianificati_mail_save", kwargs={"name": codice}),
                                {"mail_step": "1", "invia_mail": "1", **dati})

    def test_pannello_mostra_il_valore_del_modulo(self):
        SiteConfig.set("cambio_mansione_emails", "hr@x.local")
        r = self.client.get(reverse("admin_portale:automazioni_pianificati_mail", kwargs={"name": "cambio_mansione_piano"}),
                            HTTP_HX_REQUEST="true")
        self.assertContains(r, "Impostazioni del modulo")
        self.assertContains(r, 'name="mod__sc:cambio_mansione_emails"')
        self.assertContains(r, "hr@x.local")

    def test_salvare_dal_flusso_scrive_nel_modulo(self):
        self._salva("cambio_mansione_piano", {"mod__sc:cambio_mansione_emails": "a@x.local; b@x.local"})
        self.assertEqual(SiteConfig.get("cambio_mansione_emails"), "a@x.local, b@x.local")

    def test_indirizzo_non_valido_rifiutato(self):
        SiteConfig.set("cambio_mansione_emails", "hr@x.local")
        self._salva("cambio_mansione_piano", {"mod__sc:cambio_mansione_emails": "non-valido"})
        self.assertEqual(SiteConfig.get("cambio_mansione_emails"), "hr@x.local")

    def test_testo_reception_condiviso(self):
        from reception import personalizza

        self._salva("reception_rifiuto", {"mod__rc:rifiuto_oggetto": "Visita non accolta per il {data}"})
        self.assertEqual(personalizza.leggi("rifiuto_oggetto"), "Visita non accolta per il {data}")
        personalizza.salva("rifiuto_oggetto", "Dal modulo")
        valori = {c["nome"]: c["valore"] for c in campi("reception_rifiuto")["campi"]}
        self.assertEqual(valori["mod__rc:rifiuto_oggetto"], "Dal modulo")

    def test_avviso_it_mantiene_utenti_e_ticket(self):
        from anagrafica.services.avviso_it_ingresso import configurazione, salva_configurazione

        salva_configurazione(emails_raw="it@x.local", utenti_ids=[5], ticket=True)
        self._salva("anagrafica_avviso_it_ingresso", {"mod__it:emails": "it@x.local, help@x.local"})
        conf = configurazione()
        self.assertEqual(conf["emails"], ["it@x.local", "help@x.local"])
        self.assertEqual((conf["utenti_ids"], conf["ticket"]), ([5], True))

    def test_dpi_magazzino_condiviso_uno_per_riga(self):
        from dpi.models import DPIImpostazioni

        self._salva("dpi_avviso_consegna", {"mod__m:dpi.DPIImpostazioni.magazzino_emails": "mag@x.local, mag2@x.local"})
        self.assertEqual(DPIImpostazioni.get_singleton().magazzino_emails, "mag@x.local\nmag2@x.local")

    def test_mpq_lista_senza_pagina_modulo(self):
        self._salva("part145_scadenze", {"mod__sc:mpq_msm_reminder_emails": "qualita@x.local"})
        self.assertEqual(SiteConfig.get("mpq_msm_reminder_emails"), "qualita@x.local")

    def test_tutti_i_campi_si_leggono(self):
        for codice in _impostazioni():
            self.assertTrue(campi(codice)["campi"], codice)
