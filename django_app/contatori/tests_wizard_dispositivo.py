"""Wizard «Nuovo dispositivo SNMP»: ogni passo, ogni codice d'errore, bozza e blocchi.

SNMP sempre mockato, solo dati sintetici (IP di documentazione 192.0.2.0/24).
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from puresnmp.exc import ErrorResponse, SnmpError, Timeout
from x690.types import ObjectIdentifier

from .models import (
    ColonnaProfiloSNMP, CommunitySNMP, DispositivoSNMP, ImpostazioniSNMP, ProfiloSNMP, StatoSNMP,
)
from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, descrivi_errore
from .tests import _AuthedClientMixin

LEGGI_OIDS = "contatori.snmp.leggi_oids"
LEGGI_SPEC = "contatori.snmp.leggi_specifiche"


def _ok(*_a, **_k):
    return {SYS_DESCR: b"SYN Printer 4000", SYS_OBJECT_ID: "1.3.6.1.4.1.99999.1.7"}, {}


def _errore(exc):
    def lancia(host, *_a, **_k):
        raise SNMPError(f"{host}: {descrivi_errore(exc)}") from exc
    return lancia


class WizardBase(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.profilo = ProfiloSNMP.objects.create(slug="syn", nome="SYN 4000", produttore="Syn",
                                                  sys_object_id_prefix="1.3.6.1.4.1.99999")
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Totale A4 B/N",
                                          oid="1.3.6.1.4.1.99999.2.1.0", contatore_mfc="a4_bn")
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Toner",
                                          oid="1.3.6.1.4.1.99999.2.9.0")
        r = self.client.get(reverse("contatori:wizard_avvia", args=["dispositivo"]))
        self.url = r["Location"]

    def post(self, azione, **dati):
        return self.client.post(self.url, {"azione": azione, **dati})

    def stato(self):
        return next(iter(self.client.session["contatori_wizard"].values()))

    def fino_a_credenziali(self, host="192.0.2.50", versione="v2c"):
        self.post("avanti", nome="Stampante sintetica", categoria="STAMPANTE", profilo="")
        return self.post("avanti", host=host, porta="161", versione=versione)

    def fino_al_test(self, **kw):
        self.fino_a_credenziali(**kw)
        return self.post("avanti", community="syn-lettura")


class PassiTests(WizardBase):
    def test_avvio_e_primo_passo_obbligatorio(self):
        r = self.client.get(self.url)
        self.assertContains(r, "Passo 1 di 7")
        r = self.post("avanti", nome="", categoria="STAMPANTE")
        self.assertEqual(self.stato()["passo"], 0)
        self.assertContains(r, "Questo campo è obbligatorio")

    def test_indirizzo_non_valido_snmp_001(self):
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo="")
        r = self.post("avanti", host="300.1.1.1", porta="161", versione="v2c")
        self.assertContains(r, "SNMP-001")
        self.assertEqual(self.stato()["passo"], 1)

    def test_nome_non_risolto_snmp_002(self):
        import socket
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo="")
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("no")):
            r = self.post("avanti", host="mfc-inesistente.example", porta="161", versione="v2c")
        self.assertContains(r, "SNMP-002")

    def test_indirizzi_speciali_rifiutati(self):
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo="")
        for host in ("127.0.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.1"):
            r = self.post("avanti", host=host, porta="161", versione="v2c")
            self.assertContains(r, "indirizzo speciale", msg_prefix=host)

    def test_nome_host_risolto_una_volta_sola(self):
        import socket
        risposta = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.44", 161))]
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo="")
        with mock.patch("socket.getaddrinfo", return_value=risposta) as dns:
            self.post("avanti", host="mfc-sintetica.example", porta="161", versione="v2c")
            self.post("avanti", community="syn-lettura")
            with mock.patch(LEGGI_OIDS, side_effect=_ok):
                self.post("test")
            self.post("avanti")
        self.assertEqual(dns.call_count, 1)  # poi si usa l'IP salvato
        self.assertEqual(self.stato()["passo"], 4)

    def test_host_gia_usato(self):
        DispositivoSNMP.objects.create(nome="Esistente", host="192.0.2.50")
        r = self.fino_a_credenziali()
        self.assertContains(r, "già usato dal dispositivo «Esistente»")

    def test_credenziali_obbligatorie_e_segreto_cifrato_in_sessione(self):
        self.fino_a_credenziali()
        r = self.post("avanti")
        self.assertContains(r, "Scegli una credenziale dal catalogo")
        self.post("avanti", community="syn-lettura")
        self.assertEqual(self.stato()["passo"], 3)
        self.assertNotIn("syn-lettura", str(dict(self.client.session)))

    def test_credenziale_catalogo_di_versione_sbagliata(self):
        from .credential_crypto import cifra
        v3 = CommunitySNMP.objects.create(nome="Utente v3", versione="v3", segreto_cifrato=cifra("{}"))
        self.fino_a_credenziali()
        r = self.post("avanti", community_salvata=v3.pk)
        self.assertContains(r, "Questa credenziale è per SNMPv3")

    def test_v3_richiede_utente(self):
        self.fino_a_credenziali(versione="v3")
        r = self.post("avanti", v3_utente="")
        self.assertContains(r, "SNMPv3: inserisci utente")
        self.post("avanti", v3_utente="syn", v3_auth="sha1", v3_auth_key="chiave-sintetica-1")
        self.assertEqual(self.stato()["passo"], 3)

    def test_indietro_non_perde_i_dati(self):
        self.fino_a_credenziali()
        self.post("indietro")
        r = self.client.get(self.url)
        self.assertContains(r, 'value="192.0.2.50"')
        self.post("vai:0")
        self.assertContains(self.client.get(self.url), 'value="Stampante sintetica"')


class TestConnessioneTests(WizardBase):
    def test_avanti_bloccato_senza_test(self):
        self.fino_al_test()
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 3)
        self.assertContains(r, "Esegui il test di connessione")
        # Neanche saltando direttamente alla conferma
        self.post("conferma")
        self.assertFalse(DispositivoSNMP.objects.exists())

    def test_timeout_snmp_003_con_un_retry(self):
        self.fino_al_test()
        with mock.patch(LEGGI_OIDS, side_effect=_errore(Timeout("3 second timeout"))) as leggi:
            r = self.post("test")
        self.assertEqual(leggi.call_count, 2)
        self.assertContains(r, "SNMP-003")
        self.assertContains(r, "192.0.2.50:161 in 3 s")
        self.assertContains(r, "community errata")
        self.assertEqual(leggi.call_args.kwargs["timeout"], 3)

    def test_v3_rifiutato_snmp_004_senza_retry(self):
        self.fino_a_credenziali(versione="v3")
        self.post("avanti", v3_utente="syn", v3_auth="sha1", v3_auth_key="chiave-sintetica-1")
        exc = SnmpError("Error response from remote device: Unknown user-name")
        with mock.patch(LEGGI_OIDS, side_effect=_errore(exc)) as leggi:
            r = self.post("test")
        self.assertEqual(leggi.call_count, 1)
        self.assertContains(r, "SNMP-004")

    def test_permessi_snmp_007(self):
        self.fino_al_test()
        exc = ErrorResponse.construct(16, ObjectIdentifier(SYS_DESCR))
        with mock.patch(LEGGI_OIDS, side_effect=_errore(exc)):
            self.assertContains(self.post("test"), "SNMP-007")

    def test_riuscito_riconosce_il_profilo_e_sblocca(self):
        self.fino_al_test()
        with mock.patch(LEGGI_OIDS, side_effect=_ok):
            r = self.post("test")
        self.assertContains(r, "Connessione riuscita")
        self.assertContains(r, "SYN 4000")
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 4)

    def test_test_invalidato_se_cambia_la_rete(self):
        self.fino_al_test()
        with mock.patch(LEGGI_OIDS, side_effect=_ok):
            self.post("test")
        self.post("vai:1")
        self.post("avanti", host="192.0.2.51", porta="161", versione="v2c")
        self.post("avanti")  # credenziali gia' salvate
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 3)  # il test va rifatto


class MappaturaEConfermaTests(WizardBase):
    def _fino_alla_mappatura(self):
        self.fino_al_test()
        with mock.patch(LEGGI_OIDS, side_effect=_ok):
            self.post("test")
        self.post("avanti")

    def test_mappatura_evidenzia_oid_assenti_e_valori_non_validi(self):
        self._fino_alla_mappatura()
        nosuch = descrivi_errore(ErrorResponse.construct(2, ObjectIdentifier("1.3.6.1.4.1.99999.2.9.0")))
        with mock.patch(LEGGI_SPEC, return_value=({"1.3.6.1.4.1.99999.2.1.0": b"abc"},
                                                   {"1.3.6.1.4.1.99999.2.9.0": nosuch})):
            r = self.post("leggi")
        self.assertContains(r, "SNMP-005")
        self.assertContains(r, "SNMP-006")
        self.assertContains(r, 'class="wiz-ko"', count=2)

    def test_conferma_crea_dispositivo_verificato_con_credenziale_cifrata(self):
        from assets.models import Asset
        self._fino_alla_mappatura()
        with mock.patch(LEGGI_SPEC, return_value=({"1.3.6.1.4.1.99999.2.1.0": 1500}, {})):
            self.post("leggi")
        self.post("avanti")
        r = self.post("avanti", posizione="Officina", note="")
        self.assertContains(r, "Riepilogo")
        self.assertContains(r, "Nuova credenziale, salvata cifrata")
        self.assertNotContains(r, "syn-lettura")
        r = self.post("conferma")
        d = DispositivoSNMP.objects.get()
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[d.pk]), fetch_redirect_response=False)
        self.assertTrue(d.verificato)
        self.assertEqual(d.snmp_stato, StatoSNMP.OK)
        self.assertEqual(d.profilo_snmp, self.profilo)
        self.assertEqual(d.community, "")
        self.assertNotIn("syn-lettura", d.community_salvata.segreto_cifrato)
        self.assertEqual(d.sonde.count(), 2)  # profilo applicato
        self.assertEqual(self.client.session.get("contatori_wizard"), {})
        self.assertFalse(Asset.objects.filter(contatori_macchine__isnull=False).exists())

    def test_credenziale_omonima_nel_catalogo_non_viene_sovrascritta(self):
        from core.models import AuditLog
        from .credential_crypto import cifra, decifra
        esistente = CommunitySNMP.objects.create(nome="Community dispositivo 192.0.2.50", versione="v2c",
                                                 segreto_cifrato=cifra("altra"))
        self._fino_alla_mappatura()
        audit = AuditLog.objects.filter(azione="snmp_wizard_test").last()
        self.assertIn("192.0.2.50", str(audit.dettaglio))
        self.assertNotIn("syn-lettura", str(audit.dettaglio))
        self.post("avanti")
        self.post("avanti", posizione="", note="")
        self.post("conferma")
        esistente.refresh_from_db()
        self.assertEqual(decifra(esistente.segreto_cifrato), "altra")
        d = DispositivoSNMP.objects.get()
        self.assertEqual(d.community_salvata.nome, "Community dispositivo 192.0.2.50 (2)")

    def test_htmx_conferma_usa_hx_redirect(self):
        self._fino_alla_mappatura()
        self.post("avanti")
        self.post("avanti", posizione="", note="")
        r = self.client.post(self.url, {"azione": "conferma"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 204)
        self.assertIn("/contatori/snmp/dispositivi/", r["HX-Redirect"])


class BozzaTests(WizardBase):
    def test_bozza_richiede_tipo_e_rete(self):
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo="")
        r = self.post("bozza", host="", porta="161", versione="v2c")
        self.assertFalse(DispositivoSNMP.objects.exists())
        self.assertEqual(r.status_code, 200)

    def test_bozza_non_verificata_visibile(self):
        self.fino_a_credenziali()
        r = self.post("bozza", community="syn-lettura")
        d = DispositivoSNMP.objects.get()
        self.assertFalse(d.verificato)
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[d.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk])), "Non verificato")
        self.assertContains(self.client.get(reverse("contatori:snmp_centrale")), "non verificato")

    def test_prima_lettura_riuscita_verifica_la_bozza(self):
        from . import services
        from .credential_crypto import cifra
        c = CommunitySNMP.objects.create(nome="syn", versione="v2c", segreto_cifrato=cifra("syn-lettura"))
        d = DispositivoSNMP.objects.create(nome="B", host="192.0.2.60", community_salvata=c, verificato=False)
        with mock.patch("contatori.snmp.leggi_specifiche", return_value=_ok()):
            services.interroga_dispositivo(d)
        d.refresh_from_db()
        self.assertTrue(d.verificato)


class CorrezioniReviewTests(WizardBase):
    def test_scelta_dal_catalogo_sostituisce_la_community_digitata(self):
        from .credential_crypto import cifra
        catalogo = CommunitySNMP.objects.create(nome="Catalogo stampanti", versione="v2c",
                                                segreto_cifrato=cifra("dal-catalogo"))
        self.fino_al_test()                      # community digitata «syn-lettura»
        self.post("vai:2")
        self.post("avanti", community_salvata=catalogo.pk)
        with mock.patch(LEGGI_OIDS, side_effect=_ok) as leggi:
            self.post("test")
        self.assertEqual(leggi.call_args.kwargs["community"], "dal-catalogo")
        self.post("avanti")
        self.post("avanti")
        self.post("avanti", posizione="", note="")
        self.post("conferma")
        self.assertEqual(DispositivoSNMP.objects.get().community_salvata, catalogo)
        self.assertEqual(CommunitySNMP.objects.count(), 1)  # nessuna voce nuova

    def test_host_registrato_nel_frattempo_niente_500(self):
        self.fino_al_test()
        with mock.patch(LEGGI_OIDS, side_effect=_ok):
            self.post("test")
        self.post("avanti")
        self.post("avanti")
        self.post("avanti", posizione="", note="")
        DispositivoSNMP.objects.create(nome="Concorrente", host="192.0.2.50")
        r = self.post("conferma")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DispositivoSNMP.objects.count(), 1)
        self.assertEqual(self.stato()["passo"], 1)

    def test_riconoscimento_da_oid_dedicato_e_avviso_profilo_diverso(self):
        altro = ProfiloSNMP.objects.create(slug="gen", nome="Generico OID", produttore="Gen",
                                           oid_riconoscimento="1.3.6.1.4.1.88888.1.0")
        self.post("avanti", nome="X", categoria="STAMPANTE", profilo=self.profilo.pk)
        self.post("avanti", host="192.0.2.50", porta="161", versione="v2c")
        self.post("avanti", community="syn-lettura")

        def risponde(*_a, **_k):
            return {SYS_DESCR: b"box", SYS_OBJECT_ID: "1.3.6.1.4.1.8072.3", "1.3.6.1.4.1.88888.1.0": 1}, {}
        with mock.patch(LEGGI_OIDS, side_effect=risponde) as leggi:
            r = self.post("test")
        self.assertIn("1.3.6.1.4.1.88888.1.0", leggi.call_args.args[1])
        self.assertContains(r, "Generico OID")
        self.assertContains(r, "Verrà usato quello scelto")
        self.assertEqual(self.stato()["extra"]["test"]["profilo_id"], altro.pk)

    def test_modifiche_non_valide_conservate_tornando_indietro(self):
        self.fino_a_credenziali()
        self.post("vai:1")
        self.post("indietro", host="non valido!", porta="161", versione="v2c")
        self.post("avanti", nome="Stampante sintetica", categoria="STAMPANTE", profilo="")
        self.assertContains(self.client.get(self.url), 'value="non valido!"')

    def test_scheda_mostra_titolo_e_azione_del_catalogo(self):
        d = DispositivoSNMP.objects.create(nome="E", host="192.0.2.63",
                                           snmp_ultimo_errore="[SNMP-007] richiesta rifiutata")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, "SNMP-007 · Richiesta rifiutata per permessi")
        self.assertContains(r, "Cosa fare:")


class PermessiEdErroriTests(WizardBase):
    def test_sola_consultazione_bloccata_anche_in_htmx(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            self.assertRedirects(self.client.get(reverse("contatori:wizard_avvia", args=["dispositivo"])),
                                 reverse("contatori:dashboard"))
            r = self.client.post(self.url, {"azione": "avanti"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["ok"], False)

    def test_wizard_scaduto(self):
        r = self.client.get(reverse("contatori:wizard",
                                    args=["dispositivo", "00000000-0000-0000-0000-000000000000"]))
        self.assertRedirects(r, reverse("contatori:snmp_centrale"), fetch_redirect_response=False)

    def test_precompilazione_da_discovery(self):
        from .credential_crypto import cifra
        c = CommunitySNMP.objects.create(nome="syn", versione="v2c", segreto_cifrato=cifra("x"))
        r = self.client.get(reverse("contatori:wizard_avvia", args=["dispositivo"]),
                            {"host": "192.0.2.77", "nome": "Da discovery", "community_id": c.pk, "versione": "v2c"})
        self.assertContains(self.client.get(r["Location"]), 'value="Da discovery"')

    def test_errore_salvato_dai_job_ha_il_codice(self):
        from . import services
        d = DispositivoSNMP.objects.create(nome="T", host="192.0.2.61")
        ImpostazioniSNMP.objects.update_or_create(pk=1, defaults={"community": "syn-globale"})
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=_errore(Timeout("x"))):
            services.interroga_dispositivo(d)
        d.refresh_from_db()
        self.assertTrue(d.snmp_ultimo_errore.startswith("[SNMP-003] "))

    def test_form_completo_crea_non_verificato(self):
        self.client.post(reverse("contatori:snmp_dispositivo_nuovo"), {
            "nome": "Classico", "categoria": "STAMPANTE", "host": "192.0.2.62", "attivo": "on",
            "community": "syn"})
        self.assertFalse(DispositivoSNMP.objects.get(nome="Classico").verificato)
