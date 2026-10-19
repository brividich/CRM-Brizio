"""Sistema unico dei permessi (core.permessi): registro, motore, team, matrice, sync.

Dati sintetici. Le verifiche sui singoli moduli (ticket, diario, incidenti,
assenze, assistente AI, ricerca) stanno in ``core.tests_permessi_moduli``.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings

from core.legacy_models import UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    RuoloPermessoModulo,
    SiteConfig,
)
from core.permessi.motore import (
    SITECONFIG_SISTEMA_ATTIVO,
    decisione,
    invalida_contesto,
    puo_fare,
    utenti_visibili,
)
from core.permessi.preset import PRESETS, applica_preset
from core.permessi.registro import AZIONI_STANDARD, moduli_registrati
from core.permessi.cache import invalida_permessi

User = get_user_model()

# App del progetto che non dichiarano un modulo proprio, con il perche'.
APP_SENZA_MODULO = {
    "twofa": "Doppio fattore: pagine di autenticazione, fuori dai permessi (esenti nel middleware).",
    "setup_wizard": "Wizard di installazione: permessi nel modulo «piattaforma» di core.",
    "monitoring": "Monitoring tecnico: permessi nel modulo «piattaforma» di core.",
    "hub_tools": "BrizioHUB: permessi nel modulo «piattaforma» di core.",
    "dati_bi": "Viste SQL e API /api/v1/ per applicazioni: nessuna pagina per utenti, accesso con token e ambiti "
               "(dati_bi.ApiClient) e permessi SQL concessi dal DBA.",
}


def ensure_anagrafica_table():
    with connection.cursor() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS anagrafica_dipendenti (id INTEGER PRIMARY KEY, aliasusername TEXT, "
            "nome TEXT, cognome TEXT, mansione TEXT, reparto TEXT, email TEXT, email_notifica TEXT, utente_id INTEGER)"
        )


class PersoneMixin:
    """Crea persone sintetiche: utente legacy + utente Django + profilo."""

    _seq = 0

    def persona(self, nome: str, *, ruoli=(), superuser=False):
        PersoneMixin._seq += 1
        n = PersoneMixin._seq
        legacy = UtenteLegacy.objects.create(
            nome=nome, email=f"persona{n}@example.test", password="!", attivo=True,
            deve_cambiare_password=False, ruolo="utente",
        )
        user = User.objects.create_user(username=f"persona{n}@example.test", password="x", is_superuser=superuser)
        Profile.objects.create(user=user, legacy_user_id=legacy.id)
        for codice in ruoli:
            AccessGroupMembership.objects.create(group=AccessGroup.objects.get(code=codice), legacy_user_id=legacy.id)
        invalida_permessi()
        return user, legacy

    def ricarica(self, user):
        invalida_contesto(user)
        return User.objects.get(pk=user.pk)

    def attiva_sistema(self, attivo=True):
        SiteConfig.set(SITECONFIG_SISTEMA_ATTIVO, "1" if attivo else "0")
        invalida_permessi()


class RegistroModuliTests(TestCase):
    def test_ogni_app_del_progetto_dichiara_un_modulo(self):
        """Fallisce se un'app nuova non si registra nel sistema dei permessi."""
        from django.apps import apps

        base = Path(settings.BASE_DIR).resolve()
        dichiaranti = {spec.app for spec in moduli_registrati().values()}
        mancanti = []
        for config in apps.get_app_configs():
            percorso = Path(config.path).resolve()
            if base not in percorso.parents:
                continue  # app di terze parti
            if config.label in dichiaranti or config.label in APP_SENZA_MODULO:
                continue
            mancanti.append(config.label)
        self.assertEqual(
            mancanti,
            [],
            "App senza modulo nel sistema dei permessi: aggiungi <app>/registro_permessi.py "
            "(vedi docs/ai/PERMESSI_RUOLI.md) o motiva l'esclusione in APP_SENZA_MODULO.",
        )

    def test_i_preset_usano_solo_moduli_e_azioni_registrati(self):
        moduli = moduli_registrati()
        for preset in PRESETS:
            for chiave, azioni in preset.celle.items():
                self.assertIn(chiave, moduli, f"preset {preset.chiave}: modulo {chiave}")
                for azione, ambito in azioni.items():
                    self.assertIn(azione, moduli[chiave].azioni, f"{preset.chiave}.{chiave}.{azione}")
                    self.assertIn(ambito, ("propri", "team", "tutti"))

    def test_ordini_dei_preset_distinti(self):
        ordini = [p.ordine for p in PRESETS]
        self.assertEqual(len(ordini), len(set(ordini)))

    def test_ogni_tool_dell_assistente_e_mappato(self):
        from ai_assistant.tools import RUNTIME_TOOLS, TOOL_MODULI, TOOL_SENZA_DATI_DI_MODULO

        moduli = moduli_registrati()
        for tool in RUNTIME_TOOLS:
            self.assertTrue(
                tool in TOOL_MODULI or tool in TOOL_SENZA_DATI_DI_MODULO,
                f"Tool {tool.__name__} senza modulo: aggiungilo a TOOL_MODULI.",
            )
        for chiavi in TOOL_MODULI.values():
            for chiave in chiavi:
                self.assertIn(chiave, moduli)

    def test_modulo_non_registrato_e_negato(self):
        user = User.objects.create_user(username="x@example.test", is_superuser=True)
        self.assertFalse(decisione(user, "modulo_inesistente", "vedere").consentito)


class MotoreTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()

    def test_senza_ruoli_vale_solo_il_dipendente(self):
        user, _ = self.persona("Base")
        esito = decisione(user, "assenze", "vedere")
        self.assertTrue(esito.consentito)
        self.assertEqual(esito.ambito, "propri")
        self.assertFalse(decisione(user, "assenze", "approvare").consentito)
        self.assertFalse(decisione(user, "anagrafica", "vedere").consentito)

    def test_comanda_il_ruolo_con_ordine_piu_alto(self):
        user, _ = self.persona("Preposto e responsabile", ruoli=("ruolo-preposto", "ruolo-responsabile"))
        # Caporeparto (400) > Preposto (300) sulla visibilita' del diario: team.
        esito = decisione(user, "diario_preposto", "vedere")
        self.assertEqual((esito.consentito, esito.ambito), (True, "team"))
        self.assertIn("Caporeparto", esito.ruolo)
        # Il responsabile non si esprime su «creare» nel diario: decide il preposto.
        self.assertEqual(decisione(user, "diario_preposto", "creare").ambito, "propri")

    def test_ruolo_che_tace_lascia_decidere_il_successivo(self):
        user, _ = self.persona("HR", ruoli=("ruolo-hr",))
        # Gestione personale non si esprime sui ticket di manutenzione: vale l'Operatore.
        esito = decisione(user, "ticket_manutenzione", "vedere")
        self.assertEqual((esito.consentito, esito.ambito), (True, "propri"))

    def test_no_esplicito_batte_un_ruolo_piu_basso(self):
        user, _ = self.persona("Limitato", ruoli=("ruolo-preposto",))
        preposto = AccessGroup.objects.get(code="ruolo-preposto")
        RuoloPermessoModulo.objects.create(ruolo=preposto, modulo="ticket_it", azione="creare", consentito=False)
        user = self.ricarica(user)
        self.assertFalse(decisione(user, "ticket_it", "creare").consentito)

    def test_a_parita_di_ordine_vince_il_no(self):
        a = AccessGroup.objects.create(code="pari-a", label="Pari A", priority=450)
        b = AccessGroup.objects.create(code="pari-b", label="Pari B", priority=450)
        RuoloPermessoModulo.objects.create(ruolo=a, modulo="kickoff", azione="vedere", ambito="tutti")
        RuoloPermessoModulo.objects.create(ruolo=b, modulo="kickoff", azione="vedere", consentito=False)
        user, _ = self.persona("Pari", ruoli=("pari-a", "pari-b"))
        self.assertFalse(decisione(user, "kickoff", "vedere").consentito)

    def test_a_parita_di_ordine_vale_la_visibilita_piu_ampia(self):
        a = AccessGroup.objects.create(code="pari-c", label="Pari C", priority=460)
        b = AccessGroup.objects.create(code="pari-d", label="Pari D", priority=460)
        RuoloPermessoModulo.objects.create(ruolo=a, modulo="kickoff", azione="vedere", ambito="propri")
        RuoloPermessoModulo.objects.create(ruolo=b, modulo="kickoff", azione="vedere", ambito="tutti")
        user, _ = self.persona("Pari 2", ruoli=("pari-c", "pari-d"))
        self.assertEqual(decisione(user, "kickoff", "vedere").ambito, "tutti")

    def test_direzione_vede_ed_esporta_tutto_ma_non_modifica(self):
        user, _ = self.persona("Direttore", ruoli=("ruolo-direzione",))
        for spec in moduli_registrati().values():
            self.assertTrue(decisione(user, spec.chiave, "vedere").consentito, spec.chiave)
            self.assertEqual(decisione(user, spec.chiave, "vedere").ambito, "tutti")
            self.assertTrue(decisione(user, spec.chiave, "esportare").consentito, spec.chiave)
        self.assertFalse(decisione(user, "anagrafica", "modificare").consentito)
        self.assertFalse(decisione(user, "assenze", "approvare").consentito)

    def test_amministratore_fa_tutto_e_vale_come_admin_ovunque(self):
        from core.legacy_utils import is_legacy_admin

        user, legacy = self.persona("Admin", ruoli=("ruolo-amministratore",))
        for spec in moduli_registrati().values():
            for azione in AZIONI_STANDARD:
                self.assertTrue(decisione(user, spec.chiave, azione).consentito, f"{spec.chiave}.{azione}")
        self.assertTrue(is_legacy_admin(legacy))

    def test_ruolo_disattivo_non_conta(self):
        user, _ = self.persona("Sicurezza", ruoli=("ruolo-sicurezza",))
        AccessGroup.objects.filter(code="ruolo-sicurezza").update(is_active=False)
        user = self.ricarica(user)
        self.assertFalse(decisione(user, "rilevazione_incidenti", "gestire").consentito)

    def test_anonimo_negato(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(puo_fare(AnonymousUser(), "assenze", "vedere"))


class MatricePerRuoloTests(PersoneMixin, TestCase):
    """Per ogni preset e ogni modulo: concesso cio' che il preset dice, vietato il resto.

    Una persona con il solo ruolo in prova (piu' il Dipendente di base): dove il
    preset tace, deve valere il Dipendente o il divieto.
    """

    def setUp(self):
        cache.clear()
        applica_preset()

    def test_ogni_ruolo_ogni_modulo_ogni_azione(self):
        base = next(p for p in PRESETS if p.chiave == "dipendente")
        for preset in PRESETS:
            ruoli = () if preset.chiave == "dipendente" else (preset.codice,)
            user, _ = self.persona(f"Prova {preset.chiave}", ruoli=ruoli)
            for spec in moduli_registrati().values():
                for azione in AZIONI_STANDARD:
                    esito = decisione(user, spec.chiave, azione)
                    atteso = preset.celle.get(spec.chiave, {}).get(azione)
                    if preset.amministratore:
                        atteso = "tutti"
                    elif atteso is None and preset.vede_tutto and azione in ("vedere", "esportare"):
                        atteso = "tutti"
                    elif atteso is None:
                        atteso = base.celle.get(spec.chiave, {}).get(azione)
                    with self.subTest(ruolo=preset.chiave, modulo=spec.chiave, azione=azione):
                        if atteso is None:
                            self.assertFalse(esito.consentito)
                        else:
                            self.assertTrue(esito.consentito)
                            self.assertEqual(esito.ambito, atteso)


class TeamOrganigrammaTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        ensure_anagrafica_table()
        applica_preset()
        from anagrafica.models import RuoloOperativo

        self.r_resp = RuoloOperativo.objects.create(nome="Responsabile produzione TEST")
        self.r_capo = RuoloOperativo.objects.create(nome="Capo reparto TEST", riporta_a=self.r_resp)
        self.r_op = RuoloOperativo.objects.create(nome="Operatore TEST", riporta_a=self.r_capo)
        self.resp, self.resp_l = self.persona("Resp", ruoli=("ruolo-responsabile",))
        self.capo, self.capo_l = self.persona("Capo", ruoli=("ruolo-preposto",))
        self.op, self.op_l = self.persona("Operatore")
        self.collega, self.collega_l = self.persona("Collega capo")
        self.estraneo, self.estraneo_l = self.persona("Estraneo")
        for legacy, ruolo in (
            (self.resp_l, self.r_resp), (self.capo_l, self.r_capo), (self.op_l, self.r_op),
            (self.collega_l, self.r_capo),
        ):
            self.assegna(legacy, ruolo)

    def assegna(self, legacy, ruolo, *, data_fine=None):
        from anagrafica.models import DipendenteRuoloOperativo

        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, utente_id) VALUES (%s, %s, %s)",
                [9000 + legacy.id, legacy.nome, legacy.id],
            )
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=9000 + legacy.id, ruolo=ruolo, data_fine=data_fine
        )

    def test_team_scende_la_gerarchia_dei_ruoli(self):
        from core.permessi.team import team_di

        self.assertEqual(team_di(self.resp_l.id), {self.capo_l.id, self.op_l.id, self.collega_l.id})
        self.assertEqual(team_di(self.capo_l.id), {self.op_l.id})
        self.assertEqual(team_di(self.op_l.id), frozenset())

    def test_assegnazione_conclusa_non_conta(self):
        from anagrafica.models import DipendenteRuoloOperativo
        from core.permessi.team import invalida_cache_team, team_di

        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=9000 + self.op_l.id).update(
            data_fine=date.today() - timedelta(days=1)
        )
        invalida_cache_team()
        self.assertEqual(team_di(self.capo_l.id), frozenset())

    def test_visibilita_team_sul_singolo_record(self):
        from core.permessi.registro import ModuloPermessi, registra_modulo

        registra_modulo(ModuloPermessi(
            chiave="test_record", nome="Test record", app="core", proprietario=lambda o: o["autore"]
        ))
        preposto = AccessGroup.objects.get(code="ruolo-preposto")
        RuoloPermessoModulo.objects.create(ruolo=preposto, modulo="test_record", azione="vedere", ambito="team")
        capo = self.ricarica(self.capo)
        self.assertTrue(puo_fare(capo, "test_record", "vedere", {"autore": self.op_l.id}))
        self.assertTrue(puo_fare(capo, "test_record", "vedere", {"autore": self.capo_l.id}))
        self.assertFalse(puo_fare(capo, "test_record", "vedere", {"autore": self.estraneo_l.id}))
        self.assertFalse(puo_fare(capo, "test_record", "vedere", {"autore": None}))
        self.assertEqual(utenti_visibili(capo, "test_record"), {self.capo_l.id, self.op_l.id})


@override_settings(LEGACY_AUTH_ENABLED=True)
class SincronizzazioneEInterruttoreTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        from core.test_acl_v2 import _ensure_legacy_acl_tables

        _ensure_legacy_acl_tables()
        applica_preset()
        for code, module in (
            ("tickets.dashboard.view", "tickets"),
            ("tickets.nuovo.view", "tickets"),
            ("tickets.impostazioni.manage", "tickets"),
            ("dpi.approva.view", "dpi"),
            ("dpi.detail.view", "dpi"),
        ):
            PermissionDefinition.objects.create(code=code, label=code, module=module)

    def test_matrice_diventa_permessi_di_pagina(self):
        from core.permessi.sync import NOTA_MATRICE, sincronizza_tutti

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        accesi = set(GroupPermissionGrant.objects.filter(group=base, enabled=True).values_list("permission_id", flat=True))
        self.assertIn("tickets.dashboard.view", accesi)
        self.assertIn("dpi.detail.view", accesi)
        # «dpi.approva.view» finisce in .view ma approva: il Dipendente non lo riceve.
        self.assertNotIn("dpi.approva.view", accesi)
        self.assertNotIn("tickets.impostazioni.manage", accesi)
        self.assertTrue(GroupPermissionGrant.objects.filter(group=base, note=NOTA_MATRICE).exists())

    def test_sincronizzazione_non_tocca_i_grant_messi_a_mano(self):
        from core.permessi.sync import sincronizza_tutti

        base = AccessGroup.objects.get(code="ruolo-dipendente")
        GroupPermissionGrant.objects.create(group=base, permission_id="dpi.approva.view", enabled=True, note="a mano")
        sincronizza_tutti()
        self.assertTrue(GroupPermissionGrant.objects.filter(group=base, permission_id="dpi.approva.view").exists())

    def test_cella_tolta_spegne_la_pagina(self):
        from core.permessi.sync import sincronizza_tutti

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        RuoloPermessoModulo.objects.filter(ruolo=base, modulo="dpi").delete()
        sincronizza_tutti()
        self.assertFalse(GroupPermissionGrant.objects.filter(group=base, permission_id="dpi.detail.view").exists())

    def test_stato_pagine_riflette_la_matrice(self):
        from core.permessi.sync import STATO_PIENO, STATO_VUOTO, sincronizza_tutti, stato_pagine_ruolo

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        stato = stato_pagine_ruolo(base)
        vedere = stato[("dpi", "vedere")]
        self.assertEqual(vedere.stato, STATO_PIENO)
        self.assertFalse(vedere.eccezione)
        self.assertIn("dpi.detail.view", vedere.concesse)
        self.assertEqual(stato[("dpi", "approvare")].stato, STATO_VUOTO)

    def test_stato_pagine_segna_le_modifiche_fatte_a_mano(self):
        from core.permessi.sync import STATO_PIENO, STATO_VUOTO, sincronizza_tutti, stato_pagine_ruolo

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        # Da Accessi: tolta una pagina che la matrice concede, aggiunta una che non concede.
        GroupPermissionGrant.objects.filter(group=base, permission_id="dpi.detail.view").delete()
        GroupPermissionGrant.objects.create(group=base, permission_id="dpi.approva.view", enabled=True)
        stato = stato_pagine_ruolo(base)
        vedere, approvare = stato[("dpi", "vedere")], stato[("dpi", "approvare")]
        self.assertEqual(vedere.stato, STATO_VUOTO)
        self.assertEqual(vedere.tolte_a_mano, ["dpi.detail.view"])
        self.assertEqual(approvare.stato, STATO_PIENO)
        self.assertEqual(approvare.a_mano, ["dpi.approva.view"])
        self.assertTrue(vedere.eccezione and approvare.eccezione)
        self.assertIn("a mano", approvare.dettaglio)

    def test_anteprima_prevede_il_risultato_del_salvataggio(self):
        """Lo stesso calcolo che fa la pagina (JS) coincide con la sincronizzazione vera."""
        from core.permessi.sync import (
            dati_anteprima_ruolo,
            sincronizza_ruolo,
            sincronizza_tutti,
            stato_pagine_ruolo,
        )

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        # Eccezioni manuali che la sincronizzazione non tocca.
        GroupPermissionGrant.objects.create(group=base, permission_id="tickets.impostazioni.manage", enabled=True)
        GroupPermissionGrant.objects.update_or_create(
            group=base, permission_id="dpi.detail.view", defaults={"enabled": False, "note": "negato a mano"}
        )
        dati = dati_anteprima_ruolo(base)
        # Chiave del modulo che possiede le pagine ticket (dal registro, non scritta a mano).
        tk = next(k for k, m in dati["moduli"].items() if any(p[0] == "tickets.impostazioni.manage" for p in m["pagine"]))
        nuove = {("dpi", "approvare"): "tutti", ("dpi", "vedere"): "tutti", (tk, "vedere"): ""}

        def previsto(modulo, azione):
            celle = {
                (c.modulo, c.azione): (c.ambito if c.consentito else "no")
                for c in RuoloPermessoModulo.objects.filter(ruolo=base, modulo=modulo)
            }
            celle.update({k: v for k, v in nuove.items() if k[0] == modulo})
            voluti = {
                cap for (m, a), v in celle.items() if v in ("propri", "team", "tutti") for cap in dati["azioni"].get(a, [])
            }
            info = dati["moduli"][modulo]
            caps = dati["azioni"][azione]
            return sum(
                1
                for _code, cap, a_mano, negata in info["pagine"]
                if cap in caps
                and (a_mano or (not negata and (cap in voluti or (dati["vede_tutto"] and not info["solo_admin"] and cap == dati["lettura"]))))
            )

        attesi = {k: previsto(*k) for k in [("dpi", "vedere"), ("dpi", "approvare"), (tk, "vedere"), (tk, "gestire")]}
        for (modulo, azione), valore in nuove.items():
            if valore:
                RuoloPermessoModulo.objects.update_or_create(
                    ruolo=base, modulo=modulo, azione=azione, defaults={"consentito": True, "ambito": valore}
                )
            else:
                RuoloPermessoModulo.objects.filter(ruolo=base, modulo=modulo, azione=azione).delete()
        sincronizza_ruolo(base)
        stato = stato_pagine_ruolo(base)
        for chiave, atteso in attesi.items():
            with self.subTest(cella=chiave):
                self.assertEqual(len(stato[chiave].concesse), atteso)
        # Il diniego manuale resta e l'acceso a mano pure.
        self.assertEqual(attesi[("dpi", "vedere")], 0)
        self.assertEqual(attesi[("dpi", "approvare")], 1)
        self.assertEqual(attesi[(tk, "gestire")], 1)

    def test_stato_pagine_non_scrive_nulla(self):
        from core.permessi.sync import sincronizza_tutti, stato_pagine_ruolo

        sincronizza_tutti()
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        prima = list(GroupPermissionGrant.objects.order_by("id").values_list("id", "permission_id", "enabled", "note"))
        stato_pagine_ruolo(base)
        dopo = list(GroupPermissionGrant.objects.order_by("id").values_list("id", "permission_id", "enabled", "note"))
        self.assertEqual(prima, dopo)

    def test_sistema_attivo_ignora_il_ruolo_legacy(self):
        from core.acl_resolver import resolve_permission_decision
        from core.legacy_models import Ruolo

        Ruolo.objects.create(id=55, nome="caporeparto")
        _user, legacy = self.persona("Legacy")
        UtenteLegacy.objects.filter(id=legacy.id).update(ruolo_id=55)
        legacy.refresh_from_db()
        RolePermissionGrant.objects.create(legacy_role_id=55, permission_id="tickets.impostazioni.manage", enabled=True)
        self.assertTrue(resolve_permission_decision(permission_code="tickets.impostazioni.manage", legacy_user=legacy).allowed)
        self.attiva_sistema()
        self.assertFalse(resolve_permission_decision(permission_code="tickets.impostazioni.manage", legacy_user=legacy).allowed)

    def test_sistema_attivo_da_il_ruolo_base_a_tutti(self):
        from core.acl_resolver import resolve_permission_decision
        from core.permessi.sync import sincronizza_tutti

        sincronizza_tutti()
        _user, legacy = self.persona("Nuovo arrivato")
        self.assertFalse(resolve_permission_decision(permission_code="tickets.dashboard.view", legacy_user=legacy).allowed)
        self.attiva_sistema()
        self.assertTrue(resolve_permission_decision(permission_code="tickets.dashboard.view", legacy_user=legacy).allowed)

    def test_sistema_attivo_nega_le_pagine_senza_permesso_collegato(self):
        from core.acl_v2 import resolve_acl_access

        _user, legacy = self.persona("Chiunque")
        self.attiva_sistema()
        esito = resolve_acl_access(path="/pagina-senza-binding-di-prova/", legacy_user=legacy)
        self.assertFalse(esito["allowed"])
        self.assertEqual(esito["decision_source"], "deny_unbound_route")

    def test_binding_resta_autorita_della_pagina(self):
        from core.acl_v2 import resolve_acl_access
        from core.permessi.sync import sincronizza_tutti

        RoutePermissionBinding.objects.create(
            path_pattern="/prova-ticket/", match_strategy="prefix", permission_id="tickets.dashboard.view"
        )
        sincronizza_tutti()
        _user, legacy = self.persona("Utente")
        self.attiva_sistema()
        self.assertTrue(resolve_acl_access(path="/prova-ticket/", legacy_user=legacy)["allowed"])
