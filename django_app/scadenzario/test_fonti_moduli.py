"""Fonti dello scadenzario dagli altri moduli (Fase 2)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from dashboard.scadenze_providers import PROVIDERS, SOURCE_LABELS, ScadenzeContext, collect_sistema
from scadenzario import catalogo
from scadenzario import fonti_moduli as fm


def _ctx(user=None, sistema=False):
    user = user or SimpleNamespace(is_authenticated=True, is_superuser=False, id=None)
    return ScadenzeContext.build(SimpleNamespace(user=user, method="GET", legacy_user=None, session={}, GET={}),
                                 sistema=sistema)


class RegistroTests(TestCase):
    def test_fonti_registrate_prima_delle_generiche(self):
        codici = list(PROVIDERS)
        for code in fm.PROVIDERS:
            self.assertIn(code, codici)
            self.assertIn(code, SOURCE_LABELS)
        self.assertEqual(codici[-1], "generiche")

    def test_tutte_le_query_girano_senza_errori(self):
        with self.assertNoLogs("scadenzario.fonti_moduli", level="ERROR"):
            for provider in fm.PROVIDERS.values():
                provider(_ctx(sistema=True))
        self.assertIsInstance(collect_sistema(sources=set(fm.PROVIDERS)), list)

    def test_catalogo_conosce_i_tipi(self):
        radici = catalogo.costruisci(voci=[])
        self.assertIsNotNone(catalogo.trova(radici, "sgi|sorveglianza"))
        self.assertIsNotNone(catalogo.trova(radici, "procedure|assegnazione"))


class SistemaGestioneTests(TestCase):
    def test_certificazione_sorveglianza_e_scadenza(self):
        from sistema_gestione.models import Certificazione

        oggi = timezone.localdate()
        Certificazione.objects.create(norma="ISO9001", ente="Ente Esempio", prossima_sorveglianza=oggi + timedelta(days=20),
                                      scade_il=oggi + timedelta(days=400), attiva=True)
        Certificazione.objects.create(norma="ISO45001", ente="Ente", prossima_sorveglianza=oggi,
                                      scade_il=oggi + timedelta(days=400), attiva=False)
        voci = fm.collect_sgi(_ctx(sistema=True))
        self.assertEqual([(v.kind, v.elemento) for v in voci], [("sorveglianza", "ISO9001")])

    def test_senza_permesso_della_pagina_niente(self):
        from sistema_gestione.models import Certificazione

        Certificazione.objects.create(norma="ISO9001", ente="E", prossima_sorveglianza=timezone.localdate(),
                                      scade_il=timezone.localdate() + timedelta(days=400), attiva=True)
        with patch("core.middleware.acl_allows_path", return_value=False):
            self.assertEqual(fm.collect_sgi(_ctx()), [])
        with patch("core.middleware.acl_allows_path", return_value=True):
            self.assertEqual(len(fm.collect_sgi(_ctx())), 1)

    def test_auditor_in_scadenza(self):
        from sistema_gestione.models import Auditor

        Auditor.objects.create(nome_esterno="Auditor Esempio", interno=False, attivo=True,
                               qualifica_scadenza=timezone.localdate() + timedelta(days=5))
        voci = [v for v in fm.collect_sgi(_ctx(sistema=True)) if v.kind == "auditor"]
        self.assertEqual(voci[0].soggetto, "Auditor Esempio")


class VociGiaEvaseTests(TestCase):
    """Le voci che il modulo considera chiuse non restano aperte nello scadenzario."""

    def test_risposta_ente_con_piano_inviato_sparisce(self):
        from sistema_gestione.models import AuditEsterno

        oggi = timezone.localdate()
        dati = dict(tipo=AuditEsterno._meta.get_field("tipo").choices[0][0], ente="Ente Esempio",
                    stato=AuditEsterno.STATO_SVOLTO, data_inizio=oggi, risposta_entro=oggi + timedelta(days=5))
        AuditEsterno.objects.create(**dati)
        self.assertEqual([v.kind for v in fm.collect_sgi(_ctx(sistema=True)) if v.kind == "risposta_ente"], ["risposta_ente"])
        AuditEsterno.objects.update(piano_inviato_il=oggi)
        self.assertEqual([v.kind for v in fm.collect_sgi(_ctx(sistema=True)) if v.kind == "risposta_ente"], [])

    def test_gestore_va_alla_campagna_non_alla_presa_visione_altrui(self):
        from unittest.mock import patch

        righe = [SimpleNamespace(pk=5, campaign_id=9, user_id=1, due_date=timezone.localdate(), revision_id=None,
                                 campaign=SimpleNamespace(name="Campagna sintetica"), user=None)]

        class Qs(list):
            def filter(self, **k):
                return self

            def select_related(self, *a):
                return self

            def exclude(self, *a, **k):
                return self

        with patch("procedure_refresh.models.ProcedureAssignment.objects", Qs(righe)), \
                patch("procedure_refresh.models.ProcedureCampaign.objects", Qs()), \
                patch.object(fm, "_utente_id", return_value=2), patch.object(fm, "_apre", return_value=True):
            voci = fm.collect_procedure(_ctx(sistema=True))
        self.assertIn("/9", [v.url for v in voci][0])


class AltreFontiTests(TestCase):
    def test_amministratore_di_sistema(self):
        from registro_log.models import AmministratoreSistema

        AmministratoreSistema.objects.create(nome="Admin Esempio", account="adm", tipo="esterno",
                                             prossima_revisione=timezone.localdate() - timedelta(days=2))
        AmministratoreSistema.objects.create(nome="Revocato", account="rev", tipo="interno",
                                             prossima_revisione=timezone.localdate(), revocato_il=timezone.localdate())
        voci = fm.collect_gdpr(_ctx(sistema=True))
        self.assertEqual([v.elemento for v in voci], ["Admin Esempio"])
        self.assertTrue(voci[0].scaduta)

    def test_documento_ente_formazione(self):
        from anagrafica.models_formazione import TrainingProvider, TrainingProviderDocument

        ente = TrainingProvider.objects.create(nome="Ente Formazione Esempio")
        TrainingProviderDocument.objects.create(azienda=ente, tipo="ACCREDITAMENTO", file="x.pdf", nome_originale="x.pdf",
                                                data_scadenza=timezone.localdate() + timedelta(days=30))
        voci = fm.collect_formazione(_ctx(sistema=True))
        self.assertEqual((voci[0].kind, voci[0].soggetto, voci[0].elemento), ("documento_ente", "Ente Formazione Esempio", "ACCREDITAMENTO"))

    def test_regola_del_pannello_su_una_fonte_nuova(self):
        """Una persona senza accesso al registro AdS li vede con una regola del pannello."""
        from dashboard.scadenze_providers import collect_all
        from registro_log.models import AmministratoreSistema
        from scadenzario import visibilita as vis
        from scadenzario.models import RegolaVisibilita

        AmministratoreSistema.objects.create(nome="Admin Esempio", account="adm", tipo="esterno",
                                             prossima_revisione=timezone.localdate())
        user = get_user_model().objects.create_user("fm.dpo", "fm.dpo@example.com", "pwd12345")
        request = SimpleNamespace(user=user, method="GET", legacy_user=None, session={}, GET={})
        ident = vis.Identita(legacy_user_id=77)
        with patch("core.middleware.acl_allows_path", return_value=False), \
                patch("scadenzario.visibilita.identita_di", return_value=ident):
            self.assertEqual(collect_all(request, sources={"gdpr"}), [])
            RegolaVisibilita.objects.create(chiave="gdpr|ads_revisione", persona_legacy_id=77)
            request.user = get_user_model().objects.get(pk=user.pk)
            voci = collect_all(request, sources={"gdpr"})
        self.assertEqual([v.elemento for v in voci], ["Admin Esempio"])
