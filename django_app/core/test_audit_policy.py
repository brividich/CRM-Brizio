"""Politica dell'audit automatico (BUILD_SPEC R0): classi A/B/C/D, troncamento, check."""
from __future__ import annotations

import hashlib
from unittest import mock

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from core import audit_policy, audit_signals, checks
from core.audit import log_action
from core.models import AuditLog, LegacyRedirect, Notifica, SiteConfig


def _righe(modulo, model, azione=None):
    qs = AuditLog.objects.filter(modulo=modulo, dettaglio__model=model)
    if azione:
        qs = qs.filter(azione=azione)
    return list(qs.order_by("id"))


class ClassificazioneTests(SimpleTestCase):
    def test_classi_dichiarate(self):
        from automazioni.models import AutomationRule, ClusterHeartbeat
        from security.models import SecurityMailboxMessage

        self.assertEqual(audit_policy.classify(ClusterHeartbeat), "excluded")
        self.assertEqual(audit_policy.classify(SecurityMailboxMessage), "metadata_only")
        self.assertEqual(audit_policy.classify(AutomationRule), "full")
        # non elencato = classe A (fail-safe)
        self.assertEqual(audit_policy.classify(SiteConfig), "full")

    def test_ignored_fields_include_auto_now(self):
        from automazioni.models import AutomationRule

        self.assertIn("updated_at", audit_policy.ignored_fields(SiteConfig))
        campi = audit_policy.ignored_fields(AutomationRule)
        self.assertTrue({"last_run_at", "last_test_at", "updated_at"} <= campi)
        self.assertNotIn("name", campi)

    def test_listener_per_modello(self):
        from automazioni.models import ClusterHeartbeat
        from security.models import SecuritySourceFile

        self.assertFalse(audit_signals.is_audited(ClusterHeartbeat))
        self.assertTrue(audit_signals.is_audited(SiteConfig))
        self.assertTrue(audit_signals.is_audited(SecuritySourceFile))
        # nessun receiver globale (sender=None) dell'audit
        for signal in (pre_save, post_save, post_delete):
            globali = [
                ref() for key, ref, *_ in signal.receivers
                if key[1] == id(None) and callable(ref)
            ]
            self.assertFalse(any(getattr(r, "__module__", "") == "core.audit_signals" for r in globali))

    def test_classe_b_senza_listener_post_delete(self):
        from automazioni.models import ClusterHeartbeat

        self.assertFalse(post_delete.has_listeners(ClusterHeartbeat))

    def test_connect_idempotente(self):
        prima = len(post_save.receivers)
        audit_signals.connect_audit_signals()
        self.assertEqual(len(post_save.receivers), prima)


class TroncamentoTests(SimpleTestCase):
    def test_stringa_lunga_troncata_con_lunghezza_e_impronta(self):
        testo = "x" * 10_000
        out = audit_signals._serialize_value(testo)
        impronta = hashlib.sha256(testo.encode()).hexdigest()[:16]
        self.assertTrue(out.startswith("x" * audit_policy.MAX_VALUE_CHARS + "…[troncato"))
        self.assertIn("10000 caratteri", out)
        self.assertIn(f"sha256={impronta}", out)
        self.assertLess(len(out), 600)

    def test_stringa_breve_invariata(self):
        self.assertEqual(audit_signals._serialize_value("breve"), "breve")
        self.assertEqual(audit_signals._serialize_value(5), 5)
        self.assertIsNone(audit_signals._serialize_value(None))

    def test_dict_serializzato_e_troncato(self):
        self.assertEqual(audit_signals._serialize_value({"a": 1}), "{'a': 1}")
        grande = {"k": "v" * 2000}
        self.assertIn("…[troncato", audit_signals._serialize_value(grande))

    def test_binario_mai_serializzato(self):
        self.assertEqual(audit_signals._serialize_value(b"\x00\x01\x02"), "<binario 3 byte>")
        self.assertEqual(audit_signals._serialize_value(memoryview(b"abcd")), "<binario 4 byte>")


class SystemCheckTests(SimpleTestCase):
    def test_configurazione_attuale_senza_warning(self):
        self.assertEqual(checks.check_audit_policy_keys(None), [])

    def test_chiave_errata_warning(self):
        with mock.patch.object(audit_policy, "METADATA_ONLY_MODELS", frozenset({"security.refuso"})):
            warns = checks.check_audit_policy_keys(None)
        self.assertEqual([w.id for w in warns], ["core.W002"])
        self.assertIn("security.refuso", warns[0].msg)

    def test_campo_ignorato_inesistente_warning(self):
        with mock.patch.dict(audit_policy.IGNORED_FIELDS, {"core.notifica": frozenset({"letta", "inesistente"})}):
            warns = checks.check_audit_policy_keys(None)
        self.assertEqual([w.id for w in warns], ["core.W003"])


class ClasseATests(TestCase):
    """Modelli di business: insert/update reale/delete come prima."""

    def test_insert_update_delete(self):
        r = LegacyRedirect.objects.create(legacy_path="/vecchio", target_url_path="/nuovo", note="n")
        ins = _righe("core", "LegacyRedirect", "auto_insert")
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0].dettaglio["pk"], str(r.pk))
        self.assertEqual(ins[0].dettaglio["oggetto"], "LegacyRedirect</vecchio>")
        valori = ins[0].dettaglio["valori"]
        self.assertEqual(valori["legacy_path"], "/vecchio")
        self.assertEqual(valori["target_url_path"], "/nuovo")
        self.assertEqual(valori["is_enabled"], True)
        self.assertIn("updated_at", valori)  # gli insert restano completi

        r.note = "cambiata"
        r.save()
        upd = _righe("core", "LegacyRedirect", "auto_update")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0].dettaglio["modifiche"], {"note": {"old": "n", "new": "cambiata"}})
        self.assertEqual(upd[0].dettaglio["campi_tecnici_cambiati"], ["updated_at"])

        pk = r.pk
        r.delete()
        dele = _righe("core", "LegacyRedirect", "auto_delete")
        self.assertEqual(len(dele), 1)
        self.assertEqual(dele[0].dettaglio["pk"], str(pk))
        self.assertEqual(dele[0].dettaglio["valori"]["note"], "cambiata")

    def test_update_senza_modifiche_con_auto_now_nessuna_riga(self):
        c = SiteConfig.objects.create(chiave="k_audit", valore="v")
        c.save()
        c.save(update_fields=["valore"])
        self.assertEqual(_righe("core", "SiteConfig", "auto_update"), [])

    def test_valore_lungo_troncato_nell_audit(self):
        SiteConfig.objects.create(chiave="k_lungo", valore="y" * 5000)
        riga = _righe("core", "SiteConfig", "auto_insert")[0]
        self.assertIn("…[troncato, 5000 caratteri", riga.dettaglio["valori"]["valore"])


class ChiaviTecnicheTests(TestCase):
    """v3: battiti e cursori dei task salvati fra le impostazioni non scrivono righe."""

    def test_battito_non_scrive_le_altre_chiavi_si(self):
        battito = SiteConfig.objects.create(chiave="assets.collector_cnc.battito", valore="1")
        normale = SiteConfig.objects.create(chiave="login_titolo", valore="Ciao")
        battito.valore = "2"
        battito.save()
        normale.valore = "Benvenuti"
        normale.save()
        oggetti = [r.dettaglio["oggetto"] for r in _righe("core", "SiteConfig", "auto_update")]
        self.assertEqual(oggetti, ["SiteConfig<login_titolo>"])

    def test_modelli_delle_chiavi(self):
        from security.models import SecurityCenterSetting

        for chiave in ("defender.cursore", "entra.cursore_audit", "veeam.ultimo_giro", "entra.ultimo_controllo_account"):
            self.assertTrue(audit_policy.chiave_tecnica(SecurityCenterSetting, SecurityCenterSetting(key=chiave)), chiave)
        for chiave in ("watchguard.api.credenziali", "defender.severita_minima"):
            self.assertFalse(audit_policy.chiave_tecnica(SecurityCenterSetting, SecurityCenterSetting(key=chiave)), chiave)

    def test_campi_v3_ignorati_ma_configurazione_tracciata(self):
        from assets.models import IndirizzoRete

        campi = audit_policy.ignored_fields(IndirizzoRete)
        self.assertIn("ultima_vista", campi)
        self.assertEqual(audit_policy.classify(IndirizzoRete), "full")


class ClasseBTests(TestCase):
    def test_nessuna_riga(self):
        from automazioni.models import ClusterHeartbeat

        hb = ClusterHeartbeat.objects.create(instance="i1", cluster="c", seen_at=timezone.now(), status="ok")
        hb.status = "ko"
        hb.save()
        hb.delete()
        self.assertEqual(AuditLog.objects.filter(dettaglio__model="ClusterHeartbeat").count(), 0)


class ClasseCTests(TestCase):
    def test_solo_metadati(self):
        from security.models import SecurityMailboxMessage, SecuritySource

        src = SecuritySource.objects.create(name="src-audit", source_type="email")
        msg = SecurityMailboxMessage.objects.create(
            source=src, subject="Oggetto sintetico", body="CORPO-SEGRETO " * 50, sender="a@example.com",
        )
        ins = _righe("security", "SecurityMailboxMessage", "auto_insert")[0]
        self.assertNotIn("valori", ins.dettaglio)
        self.assertIn("body", ins.dettaglio["campi_valorizzati"])
        self.assertNotIn("CORPO-SEGRETO", str(ins.dettaglio))

        msg.body = "ALTRO-CORPO"
        msg.save()
        upd = _righe("security", "SecurityMailboxMessage", "auto_update")[0]
        self.assertEqual(upd.dettaglio["campi"], ["body"])
        self.assertNotIn("ALTRO-CORPO", str(upd.dettaglio))

        msg.save()  # nessuna modifica
        self.assertEqual(len(_righe("security", "SecurityMailboxMessage", "auto_update")), 1)

        msg.delete()
        dele = _righe("security", "SecurityMailboxMessage", "auto_delete")[0]
        self.assertNotIn("valori", dele.dettaglio)
        self.assertNotIn("CORPO", str(dele.dettaglio))
        self.assertEqual(dele.dettaglio["oggetto"], "Oggetto sintetico")


class ClasseDTests(TestCase):
    def setUp(self):
        self.n = Notifica.objects.create(legacy_user_id=1, messaggio="ciao")
        AuditLog.objects.all().delete()

    def test_solo_campi_ignorati_nessuna_riga(self):
        self.n.letta = True
        self.n.letta_il = timezone.now()
        self.n.popup_shown = True
        self.n.save()
        self.assertEqual(_righe("core", "Notifica"), [])

    def test_campo_reale_piu_ignorato(self):
        self.n.letta = True
        self.n.messaggio = "aggiornato"
        self.n.save()
        righe = _righe("core", "Notifica", "auto_update")
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0].dettaglio["modifiche"], {"messaggio": {"old": "ciao", "new": "aggiornato"}})
        self.assertEqual(righe[0].dettaglio["campi_tecnici_cambiati"], ["letta"])


class InvariantiTests(TestCase):
    def test_log_action_invariato(self):
        req = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5")
        log_action(req, "azione_test", "modulo_test", {"x": "y" * 2000})
        riga = AuditLog.objects.get(azione="azione_test")
        # log_action esplicito: nessun troncamento né filtro della politica
        self.assertEqual(riga.dettaglio, {"x": "y" * 2000})
        self.assertEqual(riga.ip_address, "10.0.0.5")

    def test_login_fallito_invariato(self):
        req = RequestFactory().post("/login/", REMOTE_ADDR="10.0.0.9")
        user_login_failed.send(sender=self.__class__, credentials={"username": "mario"}, request=req)
        riga = AuditLog.objects.get(azione="login_fallito")
        self.assertEqual(riga.modulo, "core")
        self.assertEqual(riga.dettaglio["username"], "mario")
        self.assertEqual(riga.dettaglio["origine"], "locale")
