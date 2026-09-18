from __future__ import annotations

from django.test import TestCase, override_settings

from anagrafica.models import Mansione, Reparto
from core.legacy_models import AnagraficaDipendente, UtenteLegacy

from .services import enrich_payload_for_source
from .source_registry import get_source_definition


class AnagraficaDipendentiSourceTests(TestCase):
    """Regola AU56: cambio mansione -> email SDS da leggere."""

    def test_sorgente_registrata_con_i_campi_virtuali_attesi(self):
        source = get_source_definition("anagrafica_dipendenti")
        self.assertIsNotNone(source)
        campi = {f["name"] for f in source["fields"]}
        for atteso in (
            "id",
            "mansione",
            "old_mansione",
            "dipendente_nome",
            "dipendente_email",
            "sds_da_leggere_count",
            "sds_url",
            "sds_conferma_tutte_url",
        ):
            self.assertIn(atteso, campi)

    @override_settings(SITE_URL="https://hub.example.local")
    def test_enrich_calcola_nome_email_e_link(self):
        reparto = Reparto.objects.create(nome="Produzione")
        mansione = Mansione.objects.create(nome="Verniciatore")
        utente = UtenteLegacy.objects.create(nome="dip", email="dip@example.local", password="x")
        anagrafica = AnagraficaDipendente.objects.create(
            nome="Mario",
            cognome="Rossi",
            reparto=reparto.nome,
            mansione=mansione.nome,
            email_notifica="mario.rossi@example.local",
            utente=utente,
        )

        payload = {
            "id": anagrafica.pk,
            "mansione": mansione.nome,
            "old_mansione": "Addetto montaggio",
            "nome": "Mario",
            "cognome": "Rossi",
            "email_notifica": "mario.rossi@example.local",
        }
        enriched = enrich_payload_for_source("anagrafica_dipendenti", payload)

        self.assertEqual(enriched["dipendente_nome"], "Rossi Mario")
        self.assertEqual(enriched["dipendente_email"], "mario.rossi@example.local")
        self.assertEqual(enriched["sds_url"], "https://hub.example.local/schede-sicurezza/da-leggere/")
        self.assertEqual(
            enriched["sds_conferma_tutte_url"],
            "https://hub.example.local/schede-sicurezza/da-leggere/conferma-tutte/",
        )
        # Nessuna SDS assegnata alla mansione in questo test: conteggio a zero, non un crash.
        self.assertEqual(enriched["sds_da_leggere_count"], 0)

    def test_enrich_su_payload_non_dict_e_no_op(self):
        self.assertEqual(enrich_payload_for_source("anagrafica_dipendenti", None), None)
