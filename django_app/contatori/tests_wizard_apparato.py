"""Wizard unico «Nuovo apparato» (MFC a contratto e dispositivi SNMP): passi, codici d'errore, bozza.

SNMP sempre mockato, solo dati sintetici (IP di documentazione 192.0.2.0/24).
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from puresnmp.exc import ErrorResponse, SnmpError, Timeout
from x690.types import ObjectIdentifier

from .models import (
    ColonnaProfiloSNMP, CommunitySNMP, DispositivoSNMP, ImpostazioniSNMP, Macchina, ProfiloSNMP, StatoSNMP,
)
from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, descrivi_errore
from .tests import _AuthedClientMixin

LEGGI_OIDS = "contatori.snmp.leggi_oids"
LEGGI_SPEC = "contatori.snmp.leggi_specifiche"
LEGGI_MFC = "contatori.snmp.leggi_macchina"
OID = "1.3.6.1.4.1.99999.3.1.0"


def _ok(*_a, **_k):
    return {SYS_DESCR: b"SYN Printer 4000", SYS_OBJECT_ID: "1.3.6.1.4.1.99999.1.7"}, {}


def _sconosciuto(*_a, **_k):
    return {SYS_DESCR: b"x", SYS_OBJECT_ID: "1.3.6.1.4.1.99998"}, {}


def _errore(exc):
    def lancia(host, *_a, **_k):
        raise SNMPError(f"{host}: {descrivi_errore(exc)}") from exc
    return lancia


class WizardBase(_AuthedClientMixin, TestCase):
    avvio = "apparato"
    query = {}

    def setUp(self):
        super().setUp()
        self.profilo = ProfiloSNMP.objects.create(slug="syn", nome="SYN 4000", produttore="Syn",
                                                  sys_object_id_prefix="1.3.6.1.4.1.99999")
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Totale A4 B/N",
                                          oid="1.3.6.1.4.1.99999.2.1.0", contatore_mfc="a4_bn")
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Toner",
                                          oid="1.3.6.1.4.1.99999.2.9.0")
        r = self.client.get(reverse("contatori:wizard_avvia", args=[self.avvio]), self.query)
        self.url = r["Location"]

    def post(self, azione, **dati):
        return self.client.post(self.url, {"azione": azione, **dati})

    def stato(self):
        return next(iter(self.client.session["contatori_wizard"].values()))

    def apparato(self, **kw):
        dati = {"tipo_apparato": "RETE", "nome": "Switch sintetico", "asset": ""}
        dati.update(kw)
        return self.post("avanti", **dati)

    def connessione(self, host="192.0.2.50", versione="v2c", **kw):
        dati = {"host": host, "porta": "161", "versione": versione}
        dati.update(kw if kw else {"community": "syn-lettura"})
        return self.post("avanti", **dati)

    def fino_alla_verifica(self, **kw):
        self.apparato(**kw)
        return self.connessione()

    def verifica(self, sistema=_ok, valori=None, **dati):
        with mock.patch(LEGGI_OIDS, side_effect=sistema), \
                mock.patch(LEGGI_SPEC, return_value=(valori or {}, {})):
            return self.post("verifica", **dati)


class PassiTests(WizardBase):
    def test_quattro_passi(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Passo 1 di 4")
        self.assertContains(r, "Nuovo apparato")
        r = self.post("avanti", tipo_apparato="RETE", nome="", asset="")
        self.assertEqual(self.stato()["passo"], 0)
        self.assertContains(r, "Inserisci il nome")

    def test_indirizzo_non_valido_snmp_001(self):
        self.apparato()
        r = self.connessione(host="300.1.1.1")
        self.assertContains(r, "SNMP-001")
        self.assertEqual(self.stato()["passo"], 1)

    def test_nome_non_risolto_snmp_002(self):
        import socket
        self.apparato()
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("no")):
            r = self.connessione(host="mfc-inesistente.example")
        self.assertContains(r, "SNMP-002")

    def test_indirizzi_speciali_rifiutati(self):
        self.apparato()
        for host in ("127.0.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.1"):
            r = self.connessione(host=host)
            self.assertContains(r, "indirizzo speciale", msg_prefix=host)

    def test_nome_host_risolto_una_volta_sola(self):
        import socket
        risposta = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.44", 161))]
        self.apparato()
        with mock.patch("socket.getaddrinfo", return_value=risposta) as dns:
            self.connessione(host="mfc-sintetica.example")
            self.verifica()
            self.post("avanti")
        self.assertEqual(dns.call_count, 1)  # poi si usa l'IP salvato
        self.assertEqual(self.stato()["passo"], 3)

    def test_host_gia_usato(self):
        DispositivoSNMP.objects.create(nome="Esistente", host="192.0.2.50")
        r = self.fino_alla_verifica()
        self.assertContains(r, "già usato dal dispositivo «Esistente»")

    def test_credenziali_obbligatorie_e_segreto_cifrato_in_sessione(self):
        self.apparato()
        r = self.connessione(community="")
        self.assertContains(r, "Scegli una credenziale dal catalogo")
        self.connessione()
        self.assertEqual(self.stato()["passo"], 2)
        self.assertNotIn("syn-lettura", str(dict(self.client.session)))

    def test_credenziale_catalogo_di_versione_sbagliata(self):
        from .credential_crypto import cifra
        v3 = CommunitySNMP.objects.create(nome="Utente v3", versione="v3", segreto_cifrato=cifra("{}"))
        self.apparato()
        r = self.connessione(community_salvata=v3.pk)
        self.assertContains(r, "Questa credenziale è per SNMPv3")

    def test_v3_non_chiede_la_community(self):
        self.apparato()
        r = self.connessione(versione="v3", v3_utente="")
        self.assertContains(r, "SNMPv3: inserisci utente")
        self.assertNotContains(r, "inserisci la community")
        self.connessione(versione="v3", v3_utente="syn", v3_auth="sha1", v3_auth_key="chiave-sintetica-1")
        self.assertEqual(self.stato()["passo"], 2)

    def test_connessione_in_una_pagina_con_v3_nascosto_dal_js(self):
        self.apparato()
        r = self.client.get(self.url)
        self.assertContains(r, 'data-snmp-versione')
        self.assertContains(r, 'data-snmp-v3-gruppo')
        self.assertContains(r, 'name="community"')
        self.assertContains(r, 'data-snmp-non-v3')

    def test_indietro_non_perde_i_dati(self):
        self.fino_alla_verifica()
        self.post("indietro")
        r = self.client.get(self.url)
        self.assertContains(r, 'value="192.0.2.50"')
        self.post("vai:0")
        self.assertContains(self.client.get(self.url), 'value="Switch sintetico"')

    def test_modifiche_non_valide_conservate_tornando_indietro(self):
        self.apparato()
        self.post("indietro", host="non valido!", porta="161", versione="v2c")
        self.apparato()
        self.assertContains(self.client.get(self.url), 'value="non valido!"')


class AssetTests(WizardBase):
    def _asset(self, **kw):
        from assets.models import Asset, AssetEndpoint
        dati = {"asset_tag": "SYN-001", "name": "Stampante sintetica ufficio", "serial_number": "SYN-SER-9",
                "model": "iR-ADV C5535i", "reparto": "Ufficio tecnico"}
        dati.update(kw)
        asset = Asset.objects.create(**dati)
        AssetEndpoint.objects.create(asset=asset, ip="192.0.2.70")
        return asset

    def test_dati_mancanti_presi_dall_asset_anche_l_ip(self):
        asset = self._asset()
        self.post("avanti", tipo_apparato="MFC", nome="", matricola="", modello="", asset=asset.pk,
                  fornitore="BASE")
        self.assertEqual(self.stato()["passo"], 1)
        self.assertContains(self.client.get(self.url), 'value="192.0.2.70"')
        self.connessione(host="192.0.2.70")
        with mock.patch(LEGGI_OIDS, side_effect=_sconosciuto), \
                mock.patch(LEGGI_MFC, return_value={"a4_bn": 1, "a3_bn": 2, "a4_col": 3, "a3_col": 4}):
            self.post("verifica")
        self.post("avanti")
        r = self.post("conferma")
        m = Macchina.objects.get()
        self.assertRedirects(r, reverse("contatori:macchina", args=[m.pk]), fetch_redirect_response=False)
        self.assertEqual((m.reparto, m.matricola, m.modello, m.asset), (asset.name, "SYN-SER-9", "iR-ADV C5535i", asset))

    def test_campi_compilati_vincono_sull_asset(self):
        asset = self._asset()
        self.apparato(nome="Switch piano 1", asset=asset.pk)
        self.connessione(host="192.0.2.71")
        self.verifica()
        self.post("avanti")
        self.post("conferma")
        d = DispositivoSNMP.objects.get()
        self.assertEqual((d.nome, d.matricola, d.posizione, d.asset), ("Switch piano 1", "SYN-SER-9",
                                                                        "Ufficio tecnico", asset))

    def test_asset_proposto_al_riepilogo_e_collegabile(self):
        asset = self._asset(serial_number="SYN-PROP-1")
        self.apparato(matricola="SYN-PROP-1")
        self.connessione(host="192.0.2.72")
        self.verifica()
        r = self.post("avanti")
        self.assertContains(r, "Collega questo asset")
        self.assertContains(r, "SYN-001")
        r = self.post("collega")
        self.assertContains(r, "SYN-001 · Stampante sintetica ufficio")
        self.post("conferma")
        self.assertEqual(DispositivoSNMP.objects.get().asset, asset)


class VerificaTests(WizardBase):
    def test_avanti_bloccato_senza_verifica(self):
        self.fino_alla_verifica()
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 2)
        self.assertContains(r, "Esegui la verifica")
        self.post("conferma")
        self.assertFalse(DispositivoSNMP.objects.exists())

    def test_timeout_snmp_003_con_un_retry(self):
        self.fino_alla_verifica()
        with mock.patch(LEGGI_OIDS, side_effect=_errore(Timeout("3 second timeout"))) as leggi:
            r = self.post("verifica")
        self.assertEqual(leggi.call_count, 2)
        self.assertContains(r, "SNMP-003")
        self.assertContains(r, "192.0.2.50:161 in 3 s")
        self.assertContains(r, "community errata")
        self.assertEqual(leggi.call_args.kwargs["timeout"], 3)

    def _timeout_v3(self, engine):
        self.apparato()
        self.connessione(versione="v3", v3_utente="syn", v3_auth="sha1", v3_auth_key="chiave-sintetica-1",
                         v3_priv="aes", v3_priv_key="chiave-sintetica-2")
        with mock.patch(LEGGI_OIDS, side_effect=_errore(Timeout("3 second timeout"))) as leggi, \
                mock.patch("contatori.snmp.sonda_engine_v3", return_value=engine) as sonda:
            r = self.post("verifica")
        self.assertEqual(leggi.call_count, 2)
        sonda.assert_called_once_with("192.0.2.50", 161, timeout=3)
        self.assertNotContains(r, "community errata")
        return r

    def test_v3_timeout_apparato_raggiungibile_snmp_009(self):
        r = self._timeout_v3("80001f8880aabbccdd")
        self.assertContains(r, "SNMP-009")
        self.assertContains(r, "engine ID 80001f8880aabbccdd")
        self.assertContains(r, "AES-128")

    def test_v3_timeout_apparato_muto_snmp_010(self):
        r = self._timeout_v3("")
        self.assertContains(r, "SNMP-010")
        self.assertContains(r, "SNMPv3 non attivo")

    def test_v3_rifiutato_snmp_004_senza_retry(self):
        self.apparato()
        self.connessione(versione="v3", v3_utente="syn", v3_auth="sha1", v3_auth_key="chiave-sintetica-1")
        exc = SnmpError("Error response from remote device: Unknown user-name")
        with mock.patch(LEGGI_OIDS, side_effect=_errore(exc)) as leggi:
            r = self.post("verifica")
        self.assertEqual(leggi.call_count, 1)
        self.assertContains(r, "SNMP-004")

    def test_permessi_snmp_007(self):
        self.fino_alla_verifica()
        exc = ErrorResponse.construct(16, ObjectIdentifier(SYS_DESCR))
        with mock.patch(LEGGI_OIDS, side_effect=_errore(exc)):
            self.assertContains(self.post("verifica"), "SNMP-007")

    def test_verifica_riconosce_il_modello_e_legge_i_valori_insieme(self):
        self.fino_alla_verifica()
        r = self.verifica(valori={"1.3.6.1.4.1.99999.2.1.0": 1500, "1.3.6.1.4.1.99999.2.9.0": 80})
        self.assertContains(r, "Apparato raggiungibile")
        self.assertContains(r, "SYN 4000")
        self.assertContains(r, "1500")
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 3)

    def test_valori_assenti_e_non_validi_evidenziati(self):
        self.fino_alla_verifica()
        nosuch = descrivi_errore(ErrorResponse.construct(2, ObjectIdentifier("1.3.6.1.4.1.99999.2.9.0")))
        with mock.patch(LEGGI_OIDS, side_effect=_ok), \
                mock.patch(LEGGI_SPEC, return_value=({"1.3.6.1.4.1.99999.2.1.0": b"abc"},
                                                     {"1.3.6.1.4.1.99999.2.9.0": nosuch})):
            r = self.post("verifica")
        self.assertContains(r, "SNMP-005")
        self.assertContains(r, "SNMP-006")
        self.assertContains(r, 'class="wiz-ko"', count=2)
        self.post("avanti")  # per un dispositivo i valori non bloccano
        self.assertEqual(self.stato()["passo"], 3)

    def test_verifica_invalidata_se_cambia_la_rete(self):
        self.fino_alla_verifica()
        self.verifica()
        self.post("vai:1")
        self.connessione(host="192.0.2.51")
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 2)  # la verifica va rifatta

    def test_modello_scelto_diverso_dal_riconosciuto(self):
        altro = ProfiloSNMP.objects.create(slug="gen", nome="Generico OID", produttore="Gen",
                                           oid_riconoscimento="1.3.6.1.4.1.88888.1.0")
        self.fino_alla_verifica()

        def risponde(*_a, **_k):
            return {SYS_DESCR: b"box", SYS_OBJECT_ID: "1.3.6.1.4.1.8072.3", "1.3.6.1.4.1.88888.1.0": 1}, {}
        with mock.patch(LEGGI_OIDS, side_effect=risponde) as leggi, mock.patch(LEGGI_SPEC, return_value=({}, {})):
            r = self.post("verifica", profilo=self.profilo.pk)
        self.assertIn("1.3.6.1.4.1.88888.1.0", leggi.call_args.args[1])
        self.assertContains(r, "Generico OID")
        self.assertContains(r, "Verrà usato quello scelto")
        self.assertEqual(self.stato()["extra"]["test"]["profilo_id"], altro.pk)


class ConfermaTests(WizardBase):
    def _fino_al_riepilogo(self):
        self.fino_alla_verifica(posizione="Officina")
        self.verifica(valori={"1.3.6.1.4.1.99999.2.1.0": 1500})
        return self.post("avanti")

    def test_conferma_crea_dispositivo_verificato_con_credenziale_cifrata(self):
        r = self._fino_al_riepilogo()
        self.assertContains(r, "Riepilogo")
        self.assertContains(r, "Nuova credenziale, salvata cifrata")
        self.assertNotContains(r, "syn-lettura")
        r = self.post("conferma")
        d = DispositivoSNMP.objects.get()
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[d.pk]), fetch_redirect_response=False)
        self.assertTrue(d.verificato)
        self.assertEqual(d.snmp_stato, StatoSNMP.OK)
        self.assertEqual(d.posizione, "Officina")
        self.assertEqual(d.profilo_snmp, self.profilo)
        self.assertEqual(d.community, "")
        self.assertNotIn("syn-lettura", d.community_salvata.segreto_cifrato)
        self.assertEqual(d.sonde.count(), 2)  # profilo applicato
        self.assertEqual(self.client.session.get("contatori_wizard"), {})
        self.assertFalse(Macchina.objects.exists())

    def test_credenziale_omonima_nel_catalogo_non_viene_sovrascritta(self):
        from core.models import AuditLog
        from .credential_crypto import cifra, decifra
        esistente = CommunitySNMP.objects.create(nome="Community dispositivo 192.0.2.50", versione="v2c",
                                                 segreto_cifrato=cifra("altra"))
        self._fino_al_riepilogo()
        audit = AuditLog.objects.filter(azione="snmp_wizard_test").last()
        self.assertIn("192.0.2.50", str(audit.dettaglio))
        self.assertNotIn("syn-lettura", str(audit.dettaglio))
        self.post("conferma")
        esistente.refresh_from_db()
        self.assertEqual(decifra(esistente.segreto_cifrato), "altra")
        self.assertEqual(DispositivoSNMP.objects.get().community_salvata.nome, "Community dispositivo 192.0.2.50 (2)")

    def test_htmx_conferma_usa_hx_redirect(self):
        self._fino_al_riepilogo()
        r = self.client.post(self.url, {"azione": "conferma"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 204)
        self.assertIn("/contatori/snmp/dispositivi/", r["HX-Redirect"])

    def test_scelta_dal_catalogo_sostituisce_la_community_digitata(self):
        from .credential_crypto import cifra
        catalogo = CommunitySNMP.objects.create(nome="Catalogo stampanti", versione="v2c",
                                                segreto_cifrato=cifra("dal-catalogo"))
        self.fino_alla_verifica()                # community digitata «syn-lettura»
        self.post("vai:1")
        self.connessione(community_salvata=catalogo.pk)
        with mock.patch(LEGGI_OIDS, side_effect=_ok) as leggi, mock.patch(LEGGI_SPEC, return_value=({}, {})):
            self.post("verifica")
        self.assertEqual(leggi.call_args.kwargs["community"], "dal-catalogo")
        self.post("avanti")
        self.post("conferma")
        self.assertEqual(DispositivoSNMP.objects.get().community_salvata, catalogo)
        self.assertEqual(CommunitySNMP.objects.count(), 1)  # nessuna voce nuova

    def test_host_registrato_nel_frattempo_niente_500(self):
        self._fino_al_riepilogo()
        DispositivoSNMP.objects.create(nome="Concorrente", host="192.0.2.50")
        r = self.post("conferma")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DispositivoSNMP.objects.count(), 1)
        self.assertEqual(self.stato()["passo"], 1)


class BozzaTests(WizardBase):
    def test_bozza_richiede_apparato_e_connessione(self):
        self.apparato()
        r = self.post("bozza", host="", porta="161", versione="v2c")
        self.assertFalse(DispositivoSNMP.objects.exists())
        self.assertContains(r, "Per salvare una bozza")

    def test_bozza_non_verificata_visibile(self):
        self.apparato()
        r = self.post("bozza", host="192.0.2.50", porta="161", versione="v2c", community="syn-lettura")
        d = DispositivoSNMP.objects.get()
        self.assertFalse(d.verificato)
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[d.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk])), "Non verificato")
        self.assertContains(self.client.get(reverse("contatori:snmp_centrale")), "non verificato")

    def test_mfc_mai_in_bozza(self):
        self.apparato(tipo_apparato="MFC", nome="Officina", matricola="SYN-MFC-1", fornitore="BASE")
        r = self.post("bozza", host="192.0.2.50", porta="161", versione="v2c", community="syn-lettura")
        self.assertNotContains(r, 'value="bozza"')
        self.assertContains(r, "non si salva in bozza")
        self.assertFalse(Macchina.objects.exists())

    def test_prima_lettura_riuscita_verifica_la_bozza(self):
        from . import services
        from .credential_crypto import cifra
        c = CommunitySNMP.objects.create(nome="syn", versione="v2c", segreto_cifrato=cifra("syn-lettura"))
        d = DispositivoSNMP.objects.create(nome="B", host="192.0.2.60", community_salvata=c, verificato=False)
        with mock.patch("contatori.snmp.leggi_specifiche", return_value=_ok()):
            services.interroga_dispositivo(d)
        d.refresh_from_db()
        self.assertTrue(d.verificato)


class MfcTests(WizardBase):
    def _anagrafica(self, **kw):
        dati = {"tipo_apparato": "MFC", "nome": "Officina", "matricola": "SYN-MFC-1", "modello": "iR-ADV C5535i",
                "contratto": "K-9", "fornitore": "BASE", "asset": ""}
        dati.update(kw)
        return self.post("avanti", **dati)

    def _fino_alla_verifica(self, **kw):
        self._anagrafica(**kw)
        return self.connessione(host="192.0.2.90", community="syn-mfc")

    def _verifica_canon(self, sistema=_sconosciuto, profilo="", contatori=None):
        with mock.patch(LEGGI_OIDS, side_effect=sistema), \
                mock.patch(LEGGI_MFC, return_value=contatori or {"a4_bn": 123456, "a3_bn": 2, "a4_col": 30,
                                                                 "a3_col": 4}), \
                mock.patch(LEGGI_SPEC, side_effect=AssertionError("nessuna lettura di profilo attesa")):
            return self.post("verifica", profilo=profilo)

    def test_canon_noto_senza_profilo_crea_mfc_verificata(self):
        self._fino_alla_verifica()
        r = self._verifica_canon()
        self.assertContains(r, "123456")
        self.assertContains(r, "tabella Canon standard")
        self.post("avanti")
        r = self.post("conferma")
        m = Macchina.objects.get(matricola="SYN-MFC-1")
        self.assertRedirects(r, reverse("contatori:macchina", args=[m.pk]), fetch_redirect_response=False)
        self.assertEqual((m.reparto, m.host, m.contratto), ("Officina", "192.0.2.90", "K-9"))
        self.assertEqual(m.snmp_community, "")
        self.assertIsNotNone(m.community_salvata)
        self.assertNotIn("syn-mfc", m.community_salvata.segreto_cifrato)
        self.assertFalse(DispositivoSNMP.objects.exists())

    def test_alias_storico_macchina_apre_il_wizard_unico_su_mfc(self):
        r = self.client.get(reverse("contatori:wizard_avvia", args=["macchina"]))
        self.assertIn("/snmp/wizard/apparato/", r["Location"])
        self.assertContains(self.client.get(r["Location"]), '<option value="MFC" selected>')

    def test_modello_sconosciuto_senza_profilo_bloccato(self):
        self._fino_alla_verifica(modello="Syn Generica 9")
        self._verifica_canon()
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 2)
        self.assertContains(r, "Nessun profilo con i contatori")

    def test_profilo_senza_quattro_contatori_bloccato(self):
        p = ProfiloSNMP.objects.create(slug="mfc-mezzo", nome="MFC parziale", produttore="Syn",
                                       categoria=ProfiloSNMP.Categoria.STAMPANTE)
        ColonnaProfiloSNMP.objects.create(profilo=p, nome="A4", oid=OID, contatore_mfc="a4_bn")
        self._fino_alla_verifica(modello="Syn 2")
        self.verifica(sistema=_sconosciuto, valori={OID: 5}, profilo=p.pk)
        r = self.post("avanti", profilo=p.pk)
        self.assertContains(r, "non mappa i contatori a3_bn, a4_col, a3_col")

    def test_cambio_modello_dopo_la_verifica_la_fa_ripetere(self):
        p = self._profilo_completo()
        self._fino_alla_verifica()
        self._verifica_canon()
        r = self.post("avanti", profilo=p.pk)
        self.assertEqual(self.stato()["passo"], 2)
        self.assertContains(r, "Ripeti la verifica")

    def test_canon_con_profilo_generico_rilevato_usa_la_tabella_canon(self):
        generico = ProfiloSNMP.objects.create(slug="stampante-gen", nome="Stampante generica", produttore="Syn",
                                              categoria=ProfiloSNMP.Categoria.STAMPANTE,
                                              sys_object_id_prefix="1.3.6.1.4.1.99997")
        self._fino_alla_verifica()
        self._verifica_canon(sistema=lambda *a, **k: ({SYS_DESCR: b"x", SYS_OBJECT_ID: "1.3.6.1.4.1.99997.1"}, {}),
                             contatori={"a4_bn": 5, "a3_bn": 6, "a4_col": 7, "a3_col": 8})
        self.assertEqual(self.stato()["extra"]["test"]["profilo_id"], generico.pk)
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 3)
        self.post("conferma")
        self.assertIsNone(Macchina.objects.get(matricola="SYN-MFC-1").profilo_snmp)

    def test_ip_gia_usato_da_un_dispositivo(self):
        DispositivoSNMP.objects.create(nome="Occupa IP", host="192.0.2.90")
        r = self._fino_alla_verifica()
        self.assertContains(r, "già usato dal dispositivo «Occupa IP»")

    def test_matricola_duplicata_e_obbligatoria(self):
        Macchina.objects.create(reparto="Altro", matricola="SYN-MFC-1")
        r = self._anagrafica()
        self.assertEqual(self.stato()["passo"], 0)
        self.assertContains(r, "Esiste già una stampante con matricola SYN-MFC-1")
        r = self._anagrafica(matricola="")
        self.assertContains(r, "la matricola è obbligatoria")

    def _profilo_completo(self):
        p = ProfiloSNMP.objects.create(slug="mfc-ok", nome="MFC completa", produttore="Syn",
                                       categoria=ProfiloSNMP.Categoria.STAMPANTE)
        for i, campo in enumerate(("a4_bn", "a3_bn", "a4_col", "a3_col")):
            ColonnaProfiloSNMP.objects.create(profilo=p, nome=campo, oid=f"1.3.6.1.4.1.99999.4.{i}.0",
                                              contatore_mfc=campo)
        return p

    def test_contatore_non_numerico_evidenziato(self):
        p = self._profilo_completo()
        self._fino_alla_verifica(modello="Syn 3")
        valori = {f"1.3.6.1.4.1.99999.4.{i}.0": 10 for i in range(4)}
        valori["1.3.6.1.4.1.99999.4.1.0"] = b"n/d"
        r = self.verifica(sistema=_sconosciuto, valori=valori, profilo=p.pk)
        self.assertContains(r, "SNMP-006")
        r = self.post("avanti", profilo=p.pk)  # un contatore non numerico blocca la MFC
        self.assertEqual(self.stato()["passo"], 2)
        self.assertContains(r, "non leggibile")

    def test_modelli_proposti_solo_stampanti(self):
        ProfiloSNMP.objects.create(slug="ups", nome="UPS sintetico", produttore="Syn",
                                   categoria=ProfiloSNMP.Categoria.UPS)
        self._fino_alla_verifica()
        r = self.client.get(self.url)
        self.assertNotContains(r, "UPS sintetico")


class PermessiEdErroriTests(WizardBase):
    def test_sola_consultazione_bloccata_anche_in_htmx(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            self.assertRedirects(self.client.get(reverse("contatori:wizard_avvia", args=["apparato"])),
                                 reverse("contatori:dashboard"))
            r = self.client.post(self.url, {"azione": "avanti"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["ok"], False)

    def test_wizard_scaduto(self):
        r = self.client.get(reverse("contatori:wizard",
                                    args=["apparato", "00000000-0000-0000-0000-000000000000"]))
        self.assertRedirects(r, reverse("contatori:snmp_centrale"), fetch_redirect_response=False)

    def test_precompilazione_da_discovery(self):
        from .credential_crypto import cifra
        c = CommunitySNMP.objects.create(nome="syn", versione="v2c", segreto_cifrato=cifra("x"))
        r = self.client.get(reverse("contatori:wizard_avvia", args=["dispositivo"]),
                            {"host": "192.0.2.77", "nome": "Da discovery", "community_id": c.pk, "versione": "v2c"})
        self.url = r["Location"]
        self.assertContains(self.client.get(self.url), 'value="Da discovery"')
        self.apparato(nome="Da discovery")
        r = self.client.get(self.url)
        self.assertContains(r, 'value="192.0.2.77"')
        self.assertContains(r, f'<option value="{c.pk}" selected>')

    def test_errore_salvato_dai_job_ha_il_codice(self):
        from . import services
        d = DispositivoSNMP.objects.create(nome="T", host="192.0.2.61")
        ImpostazioniSNMP.objects.update_or_create(pk=1, defaults={"community": "syn-globale"})
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=_errore(Timeout("x"))):
            services.interroga_dispositivo(d)
        d.refresh_from_db()
        self.assertTrue(d.snmp_ultimo_errore.startswith("[SNMP-003] "))

    def test_scheda_mostra_titolo_e_azione_del_catalogo(self):
        d = DispositivoSNMP.objects.create(nome="E", host="192.0.2.63",
                                           snmp_ultimo_errore="[SNMP-007] richiesta rifiutata")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, "SNMP-007 · Richiesta rifiutata per permessi")
        self.assertContains(r, "Cosa fare:")

    def test_form_completo_crea_non_verificato(self):
        self.client.post(reverse("contatori:snmp_dispositivo_nuovo"), {
            "nome": "Classico", "categoria": "STAMPANTE", "host": "192.0.2.62", "attivo": "on",
            "community": "syn"})
        self.assertFalse(DispositivoSNMP.objects.get(nome="Classico").verificato)
