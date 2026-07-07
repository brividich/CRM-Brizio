"""MOD.128 MPQ — F2 UI (cruscotto processi qualificati + dettaglio processo).

Test di rendering delle pagine di sola lettura: cruscotto (KPI + elenco processi
+ scadenze urgenti) e dettaglio processo (clienti/reparti/riferimenti +
abilitazioni persona×processo + certificazioni individuali), più il seeding
della voce di subnav sotto Competenze → Qualifiche.

Nessun dato reale: tutti gli esempi sono fittizi (no PII del MOD.128 reale).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    ProcessoQualificato,
)
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqCruscottoUITests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="mpq-cru", email="mpq-cru@example.com", password="pass12345",
        )
        self.client.force_login(self.user)
        self.cli = ClienteQualificante.objects.create(nome="Cliente Aerospace A")
        self.p_attivo = ProcessoQualificato.objects.create(
            nome="Trattamento termico", cliente=self.cli,
            stato=ProcessoQualificato.STATO_ATTIVO,
        )
        self.p_sospeso = ProcessoQualificato.objects.create(
            nome="Saldatura speciale", cliente=self.cli,
            stato=ProcessoQualificato.STATO_SOSPESO,
        )

    def test_cruscotto_richiede_login(self):
        self.client.logout()
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertNotEqual(resp.status_code, 200)

    def test_cruscotto_ok_con_subnav(self):
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hrnav")   # subnav di modulo
        self.assertContains(resp, "MOD.128")

    def test_cruscotto_conteggi_stato(self):
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertEqual(resp.context["n_processi"], 2)
        self.assertEqual(resp.context["n_attivi"], 1)

    def test_cruscotto_elenca_processi(self):
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertContains(resp, "Trattamento termico")
        self.assertContains(resp, "Saldatura speciale")

    def test_scadenza_urgente_in_evidenza(self):
        oggi = timezone.localdate()
        p = ProcessoQualificato.objects.create(
            nome="Processo in scadenza", cliente=self.cli,
            tipo_validita=ProcessoQualificato.VALIDITA_DATA,
            data_scadenza=oggi + timedelta(days=10),
        )
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        urgenti_ids = [r["obj"].id for r in resp.context["scadenze_urgenti"]]
        self.assertIn(p.id, urgenti_ids)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqProcessoDetailUITests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="mpq-det", email="mpq-det@example.com", password="pass12345",
        )
        self.client.force_login(self.user)
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")
        self.proc = ProcessoQualificato.objects.create(nome="Controllo PT", cliente=self.cli)
        self.ab = AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=42, processo=self.proc, is_controllore=True,
        )

    def test_detail_ok(self):
        resp = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.proc.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Controllo PT")

    def test_detail_mostra_abilitazione_fallback_id(self):
        # Anagrafica vuota → il nome persona non è risolto e resta il fallback #<id>.
        resp = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.proc.id]))
        self.assertContains(resp, "#42")

    def test_detail_mostra_certificazione(self):
        CertificazioneIndividuale.objects.create(
            abilitazione=self.ab, schema="ITA", numero="AAA-123",
            data_scadenza=timezone.localdate() + timedelta(days=200),
        )
        resp = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.proc.id]))
        self.assertContains(resp, "AAA-123")

    def test_detail_404_su_id_inesistente(self):
        resp = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[999999]))
        self.assertEqual(resp.status_code, 404)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqSubnavSeedTests(TestCase):
    def test_link_mpq_sotto_competenze_qualifiche(self):
        from .models import SubnavLinkAnagrafica
        link = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:mpq_cruscotto").first()
        self.assertIsNotNone(link)
        self.assertEqual(link.categoria.nome, "Competenze")
        self.assertEqual(link.gruppo, "Qualifiche")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqVistaUITests(TestCase):
    """Vista "MOD.128" (F3): tabella 8-col raggruppata per cliente + export .docx."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="mpq-vista", email="mpq-vista@example.com", password="pass12345",
        )
        self.client.force_login(self.user)
        self.cli = ClienteQualificante.objects.create(nome="Cliente Aerospace A")
        # Processo nominale con abilitazioni per ruolo.
        self.p_nom = ProcessoQualificato.objects.create(
            nome="Controllo liquidi penetranti", cliente=self.cli,
            stato=ProcessoQualificato.STATO_ATTIVO,
        )
        self.ab = AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=42, processo=self.p_nom,
            is_qualificato=True, is_controllore=True,
        )
        CertificazioneIndividuale.objects.create(
            abilitazione=self.ab, schema="ITA", numero="CN-777",
            data_scadenza=timezone.localdate() + timedelta(days=300),
        )
        # Processo organizzativo (rimando a dichiarazione, niente nominativi).
        self.p_org = ProcessoQualificato.objects.create(
            nome="Trattamento termico", cliente=self.cli,
            stato=ProcessoQualificato.STATO_ATTIVO,
            personale_modalita=ProcessoQualificato.MODALITA_ORGANIZZATIVO,
            riferimento_dichiarazione="Dich. organizzativa rev. 3",
        )

    def test_vista_ok_con_subnav(self):
        resp = self.client.get(reverse("anagrafica:mpq_vista"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hrnav")
        self.assertContains(resp, "MOD.128")
        self.assertContains(resp, "Controllo liquidi penetranti")

    def test_vista_raggruppa_per_cliente(self):
        resp = self.client.get(reverse("anagrafica:mpq_vista"))
        gruppi = resp.context["gruppi"]
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(gruppi[0]["cliente"], "Cliente Aerospace A")
        self.assertEqual(len(gruppi[0]["righe"]), 2)

    def test_vista_personale_per_ruolo(self):
        resp = self.client.get(reverse("anagrafica:mpq_vista"))
        riga = next(r for g in resp.context["gruppi"] for r in g["righe"]
                    if r["processo"] == "Controllo liquidi penetranti")
        self.assertIn("#42", riga["controllore"])
        self.assertIn("#42", riga["qualificato"])
        self.assertEqual(riga["addetto"], [])

    def test_vista_organizzativo_mostra_riferimento(self):
        resp = self.client.get(reverse("anagrafica:mpq_vista"))
        riga = next(r for g in resp.context["gruppi"] for r in g["righe"]
                    if r["processo"] == "Trattamento termico")
        self.assertTrue(riga["organizzativo"])
        self.assertIn("Dich. organizzativa rev. 3", riga["organizzativo_rif"])
        self.assertEqual(riga["qualificato"], [])

    def test_export_docx_download(self):
        resp = self.client.get(reverse("anagrafica:mpq_vista"), {"format": "docx"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("wordprocessingml", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn(".docx", resp["Content-Disposition"])
        self.assertEqual(bytes(resp.content[:2]), b"PK")  # zip/docx signature


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqAclTests(TestCase):
    """F4 — ACL v2 canonica: permessi + binding route + gate in-view."""

    def test_bootstrap_registra_permessi_e_binding(self):
        from core.models import PermissionDefinition, RoutePermissionBinding
        from .acl_bootstrap import (
            PERM_MPQ_VIEW, PERM_MPQ_MANAGE, bootstrap_anagrafica_acl_endpoints,
        )
        bootstrap_anagrafica_acl_endpoints(force=True)
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_MPQ_VIEW).exists())
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_MPQ_MANAGE).exists())
        for route in ("anagrafica:mpq_cruscotto", "anagrafica:mpq_vista",
                      "anagrafica:mpq_processo_detail"):
            self.assertTrue(
                RoutePermissionBinding.objects.filter(
                    route_name=route, permission_id=PERM_MPQ_VIEW, is_active=True,
                ).exists(),
                f"binding mancante per {route}",
            )

    def test_utente_senza_permesso_negato(self):
        # Utente autenticato ma senza grant → il gate in-view reindirizza (302).
        user = User.objects.create_user(
            username="mpq-nogrant", email="mpq-nogrant@example.com", password="pass12345",
        )
        self.client.force_login(user)
        for route in ("anagrafica:mpq_cruscotto", "anagrafica:mpq_vista"):
            resp = self.client.get(reverse(route))
            self.assertEqual(resp.status_code, 302, f"{route} doveva negare")

    def test_superuser_ammesso(self):
        su = User.objects.create_superuser(
            username="mpq-su", email="mpq-su@example.com", password="pass12345",
        )
        self.client.force_login(su)
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertEqual(resp.status_code, 200)


class Mod128DocxBuilderTests(TestCase):
    """Builder .docx puro (senza DB): la tabella replica contiene i dati."""

    def test_build_docx_contiene_processo_e_persona(self):
        from io import BytesIO
        from datetime import date
        from docx import Document
        from .mpq_export import build_mod128_docx_bytes

        gruppi = [{
            "cliente": "Cliente X",
            "righe": [{
                "processo": "Proc Y", "livello": "LVL2", "regime": "NADCAP",
                "riferimenti": ["COP001"], "qualificato": ["Rossi Mario"],
                "addetto": [], "controllore": ["Rossi Mario"], "part145": [],
                "scadenze": ["Processo: 06-04-2029"], "reparti": ["CND PT"],
                "stato": "Attivo", "organizzativo": False, "organizzativo_rif": "",
            }],
        }]
        data = build_mod128_docx_bytes(gruppi, date(2026, 7, 7))
        self.assertTrue(data.startswith(b"PK"))
        doc = Document(BytesIO(data))
        testi = [c.text for t in doc.tables for row in t.rows for c in row.cells]
        self.assertTrue(any("Proc Y" in x for x in testi))
        self.assertTrue(any("Rossi Mario" in x for x in testi))
