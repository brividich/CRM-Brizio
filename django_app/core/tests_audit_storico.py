"""Audit trail per record: l'aggancio all'oggetto e lo storico che ne deriva.

Fino all'introduzione di ``oggetto_tipo``/``oggetto_id``, ``AuditLog`` sapeva
rispondere solo a «chi ha fatto cosa, in quale modulo». Questi test coprono la
domanda che si fa davanti a una scheda — «cosa è successo a QUESTO record» — e
soprattutto la retrocompatibilità: le ~300 chiamate storiche di ``log_action``
non passano l'oggetto e devono continuare a funzionare identiche.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.audit import log_action, storico_leggibile, storico_oggetto
from core.models import AuditLog, SiteConfig

User = get_user_model()


def _esplicite(voci) -> list[str]:
    """Le azioni di ``log_action``: le ``auto_*`` dei segnali ora sono agganciate anche loro."""
    return [v.azione for v in voci if not v.azione.startswith("auto_")]


class AuditOggettoTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="audit-op", password="x")

    def _request(self):
        request = self.factory.post("/qualsiasi/")
        request.user = self.user
        return request

    # -- retrocompatibilità ---------------------------------------------------

    def test_chiamata_storica_senza_oggetto_resta_valida(self):
        log_action(self._request(), "azione_storica", "modulo_x", {"dettaglio": "qualcosa"})

        voce = AuditLog.objects.get(azione="azione_storica")
        self.assertEqual(voce.modulo, "modulo_x")
        self.assertEqual(voce.oggetto_tipo, "")
        self.assertEqual(voce.oggetto_id, "")

    def test_dettaglio_stringa_ancora_incapsulato(self):
        log_action(self._request(), "azione_stringa", "modulo_x", "testo libero")
        self.assertEqual(
            AuditLog.objects.get(azione="azione_stringa").dettaglio, {"dettaglio": "testo libero"},
        )

    # -- aggancio -------------------------------------------------------------

    def test_oggetto_istanza_deriva_etichetta_e_id(self):
        config = SiteConfig.objects.create(chiave="chiave-audit", valore="v")
        log_action(self._request(), "modifica", "core", {}, oggetto=config)

        voce = AuditLog.objects.get(azione="modifica")
        self.assertEqual(voce.oggetto_tipo, "core.siteconfig")
        self.assertEqual(voce.oggetto_id, str(config.pk))

    def test_riferimento_esplicito_per_tabelle_legacy(self):
        """Le tabelle legacy non hanno un modello Django da cui dedurre l'etichetta."""
        log_action(
            self._request(), "modifica_legacy", "anagrafica", {},
            oggetto_tipo="legacy.anagrafica_dipendenti", oggetto_id=4242,
        )

        voce = AuditLog.objects.get(azione="modifica_legacy")
        self.assertEqual(voce.oggetto_tipo, "legacy.anagrafica_dipendenti")
        self.assertEqual(voce.oggetto_id, "4242")

    # -- storico --------------------------------------------------------------

    def test_storico_isola_il_singolo_record(self):
        primo = SiteConfig.objects.create(chiave="primo", valore="1")
        secondo = SiteConfig.objects.create(chiave="secondo", valore="2")
        log_action(self._request(), "tocca_primo", "core", {}, oggetto=primo)
        log_action(self._request(), "tocca_primo_ancora", "core", {}, oggetto=primo)
        log_action(self._request(), "tocca_secondo", "core", {}, oggetto=secondo)
        log_action(self._request(), "senza_oggetto", "core", {})

        azioni = _esplicite(storico_oggetto(primo))
        self.assertEqual(sorted(azioni), ["tocca_primo", "tocca_primo_ancora"])
        self.assertEqual(_esplicite(storico_oggetto(secondo)), ["tocca_secondo"])

    def test_storico_ordinato_dal_piu_recente(self):
        config = SiteConfig.objects.create(chiave="ordine", valore="1")
        for i in range(3):
            log_action(self._request(), f"azione_{i}", "core", {}, oggetto=config)

        self.assertEqual(_esplicite(storico_oggetto(config)), ["azione_2", "azione_1", "azione_0"])

    def test_storico_rispetta_il_limite(self):
        config = SiteConfig.objects.create(chiave="limite", valore="1")
        for i in range(8):
            log_action(self._request(), f"a{i}", "core", {}, oggetto=config)

        self.assertEqual(len(list(storico_oggetto(config, limit=3))), 3)

    def test_storico_senza_riferimento_e_vuoto_non_none(self):
        """Il chiamante non deve difendersi dal None: sempre un queryset."""
        self.assertEqual(list(storico_oggetto()), [])
        self.assertEqual(list(storico_oggetto(oggetto_tipo="solo.tipo")), [])
        self.assertEqual(list(storico_oggetto(oggetto_id="123")), [])

    def test_audit_automatico_agganciato_al_record(self):
        """I segnali scrivono la voce con l'aggancio: prima restava fuori dallo storico."""
        config = SiteConfig.objects.create(chiave="auto-aggancio", valore="1")
        config.valore = "2"
        config.save()
        azioni = [v.azione for v in storico_oggetto(config)]
        self.assertEqual(azioni[:2], ["auto_update", "auto_insert"])

    def test_storico_leggibile_righe_prima_dopo(self):
        config = SiteConfig.objects.create(chiave="leggibile", valore="vecchio")
        config.valore = "nuovo"
        config.save()
        voce = next(v for v in storico_leggibile(storico_oggetto(config)) if v.azione == "auto_update")
        self.assertEqual(voce.azione_label, "Modifica")
        self.assertIn(("vecchio", "nuovo"), [(r["prima"], r["dopo"]) for r in voce.righe])
        self.assertEqual(voce.dettaglio, {})

    def test_id_lungo_troncato_senza_errore(self):
        log_action(
            self._request(), "id_lungo", "core", {},
            oggetto_tipo="legacy.tabella", oggetto_id="X" * 200,
        )
        self.assertEqual(len(AuditLog.objects.get(azione="id_lungo").oggetto_id), 64)
