"""Wizard MFC, profilo, colonna di profilo e lettore OID. SNMP sempre mockato, dati sintetici."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from .models import ColonnaProfiloSNMP, DispositivoSNMP, Macchina, ProfiloSNMP, SondaSNMP
from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID
from .tests import _AuthedClientMixin

LEGGI_OIDS = "contatori.snmp.leggi_oids"
LEGGI_SPEC = "contatori.snmp.leggi_specifiche"
LEGGI_MFC = "contatori.snmp.leggi_macchina"
OID = "1.3.6.1.4.1.99999.3.1.0"


def _ok(*_a, **_k):
    return {SYS_DESCR: b"Canon iR-ADV C5535i", SYS_OBJECT_ID: "1.3.6.1.4.1.1602.4.7"}, {}


class _Base(_AuthedClientMixin, TestCase):
    tipo = ""
    query = {}

    def setUp(self):
        super().setUp()
        r = self.client.get(reverse("contatori:wizard_avvia", args=[self.tipo]), self.query)
        self.url = r["Location"]

    def post(self, azione, **dati):
        return self.client.post(self.url, {"azione": azione, **dati})

    def stato(self):
        return next(iter(self.client.session["contatori_wizard"].values()))


class WizardMacchinaTests(_Base):
    tipo = "macchina"

    def _anagrafica(self, **kw):
        dati = {"reparto": "Officina", "matricola": "SYN-MFC-1", "modello": "iR-ADV C5535i",
                "contratto": "K-9", "fornitore": "BASE", "profilo": ""}
        dati.update(kw)
        return self.post("avanti", **dati)

    def _fino_alla_mappatura(self, sistema=_ok, **kw):
        self._anagrafica(**kw)
        self.post("avanti", host="192.0.2.90", porta="161", versione="v2c")
        self.post("avanti", community="syn-mfc")
        with mock.patch(LEGGI_OIDS, side_effect=sistema):
            self.post("test")
        return self.post("avanti")

    def test_canon_noto_senza_profilo_crea_mfc_verificata(self):
        # sysObjectID che nessun preset riconosce: si usa la tabella Canon standard
        self._fino_alla_mappatura(sistema=lambda *a, **k: ({SYS_DESCR: b"x", SYS_OBJECT_ID: "1.3.6.1.4.1.99998"}, {}))
        with mock.patch(LEGGI_MFC, return_value={"a4_bn": 123456, "a3_bn": 2, "a4_col": 30, "a3_col": 4}), \
                mock.patch(LEGGI_SPEC, side_effect=AssertionError("nessuna lettura di profilo attesa")):
            r = self.post("leggi")
        self.assertContains(r, "123456")
        self.post("avanti")
        self.post("avanti", attiva="on")
        r = self.post("conferma")
        m = Macchina.objects.get(matricola="SYN-MFC-1")
        self.assertRedirects(r, reverse("contatori:macchina", args=[m.pk]), fetch_redirect_response=False)
        self.assertEqual(m.host, "192.0.2.90")
        self.assertEqual(m.snmp_community, "")
        self.assertIsNotNone(m.community_salvata)
        self.assertNotIn("syn-mfc", m.community_salvata.segreto_cifrato)

    def test_modello_sconosciuto_senza_profilo_bloccato(self):
        # Apparato che nessun profilo riconosce
        self._fino_alla_mappatura(modello="Syn Generica 9",
                                  sistema=lambda *a, **k: ({SYS_DESCR: b"syn", SYS_OBJECT_ID: "1.3.6.1.4.1.99998"}, {}))
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 4)
        self.assertContains(r, "Nessun profilo con i contatori")

    def test_profilo_senza_quattro_contatori_bloccato(self):
        p = ProfiloSNMP.objects.create(slug="mfc-mezzo", nome="MFC parziale", produttore="Syn",
                                       categoria=ProfiloSNMP.Categoria.STAMPANTE)
        ColonnaProfiloSNMP.objects.create(profilo=p, nome="A4", oid=OID, contatore_mfc="a4_bn")
        self._fino_alla_mappatura(modello="Syn 2", profilo=p.pk)
        r = self.post("avanti")
        self.assertContains(r, "non mappa i contatori a3_bn, a4_col, a3_col")

    def test_lettura_contatori_obbligatoria(self):
        self._fino_alla_mappatura(sistema=lambda *a, **k: ({SYS_DESCR: b"x", SYS_OBJECT_ID: "1.3.6.1.4.1.99998"}, {}))
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 4)
        self.assertContains(r, "Leggi i contatori")

    def test_canon_con_profilo_generico_rilevato_usa_la_tabella_canon(self):
        generico = ProfiloSNMP.objects.create(slug="stampante-gen", nome="Stampante generica", produttore="Syn",
                                              categoria=ProfiloSNMP.Categoria.STAMPANTE,
                                              sys_object_id_prefix="1.3.6.1.4.1.99997")
        self._fino_alla_mappatura(sistema=lambda *a, **k: ({SYS_DESCR: b"x", SYS_OBJECT_ID: "1.3.6.1.4.1.99997.1"}, {}))
        self.assertEqual(self.stato()["extra"]["test"]["profilo_id"], generico.pk)
        with mock.patch(LEGGI_MFC, return_value={"a4_bn": 5, "a3_bn": 6, "a4_col": 7, "a3_col": 8}):
            self.post("leggi")
        self.post("avanti")
        self.assertEqual(self.stato()["passo"], 5)
        self.post("avanti", attiva="on")
        self.post("conferma")
        self.assertIsNone(Macchina.objects.get(matricola="SYN-MFC-1").profilo_snmp)

    def test_ip_gia_usato_da_un_dispositivo(self):
        DispositivoSNMP.objects.create(nome="Occupa IP", host="192.0.2.90")
        self._anagrafica()
        r = self.post("avanti", host="192.0.2.90", porta="161", versione="v2c")
        self.assertContains(r, "già usato dal dispositivo «Occupa IP»")

    def test_matricola_duplicata(self):
        Macchina.objects.create(reparto="Altro", matricola="SYN-MFC-1")
        r = self._anagrafica()
        self.assertEqual(self.stato()["passo"], 0)
        self.assertContains(r, "già")

    def test_contatore_non_numerico_evidenziato(self):
        p = ProfiloSNMP.objects.create(slug="mfc-ok", nome="MFC completa", produttore="Syn",
                                       categoria=ProfiloSNMP.Categoria.STAMPANTE)
        for i, campo in enumerate(("a4_bn", "a3_bn", "a4_col", "a3_col")):
            ColonnaProfiloSNMP.objects.create(profilo=p, nome=campo, oid=f"1.3.6.1.4.1.99999.4.{i}.0",
                                              contatore_mfc=campo)
        self._fino_alla_mappatura(modello="Syn 3", profilo=p.pk)
        valori = {f"1.3.6.1.4.1.99999.4.{i}.0": 10 for i in range(4)}
        valori["1.3.6.1.4.1.99999.4.1.0"] = b"n/d"
        with mock.patch(LEGGI_SPEC, return_value=(valori, {})):
            r = self.post("leggi")
        self.assertContains(r, "SNMP-006")
        r = self.post("avanti")  # un contatore non numerico blocca la MFC
        self.assertEqual(self.stato()["passo"], 4)
        self.assertContains(r, "non leggibile")


class WizardProfiloTests(_Base):
    tipo = "profilo"

    def test_slug_automatico_regex_e_anteprima_riconoscimento(self):
        DispositivoSNMP.objects.create(nome="Sw riconosciuto", host="192.0.2.91",
                                       sys_object_id="1.3.6.1.4.1.77777.1.5")
        self.post("avanti", nome="Switch sintetico", slug="", produttore="Syn", categoria="RETE")
        self.assertEqual(self.stato()["passo"], 1)
        r = self.post("avanti", sys_object_id_prefix="", sys_descr_pattern="([", oid_riconoscimento="")
        self.assertContains(r, "Espressione regolare non valida")
        self.post("avanti", sys_object_id_prefix="1.3.6.1.4.1.77777", sys_descr_pattern="", oid_riconoscimento="")
        self.post("vai:1")
        self.assertContains(self.client.get(self.url), "Sw riconosciuto")
        self.post("avanti", sys_object_id_prefix="1.3.6.1.4.1.77777", sys_descr_pattern="", oid_riconoscimento="")
        self.post("avanti", versione="", porta="", timeout="", note="")
        r = self.post("conferma")
        p = ProfiloSNMP.objects.get(nome="Switch sintetico")
        self.assertEqual(p.slug, "syn-switch-sintetico")
        self.assertRedirects(r, reverse("contatori:snmp_profilo_edit", args=[p.pk]), fetch_redirect_response=False)


class WizardColonnaTests(_Base):
    tipo = "colonna"

    def setUp(self):
        self.profilo = ProfiloSNMP.objects.create(slug="syn-p", nome="Profilo sintetico", produttore="Syn")
        self.disp = DispositivoSNMP.objects.create(nome="Banco prova", host="192.0.2.92", community="syn")
        self.query = {"profilo": self.profilo.pk}
        super().setUp()

    def _oid(self, oid=OID):
        return self.post("avanti", nome="Pagine totali", oid=oid, modalita="GET", aggregazione="PRIMO")

    def _resto(self, contatore=""):
        self.post("avanti", tipo_valore="NUMERO", unita="", fattore="1", contatore_mfc=contatore, etichette="")
        self.post("avanti")  # soglie vuote
        return self.post("conferma")

    def test_senza_profilo_non_si_apre(self):
        r = self.client.get(reverse("contatori:wizard_avvia", args=["colonna"]))
        self.assertRedirects(r, reverse("contatori:snmp_centrale"), fetch_redirect_response=False)

    def test_prova_riuscita_rende_la_colonna_verificata(self):
        self._oid()
        with mock.patch(LEGGI_SPEC, return_value=({OID: 1234}, {})) as leggi:
            r = self.post("prova", bersaglio=f"d:{self.disp.pk}")
        self.assertEqual(leggi.call_args.kwargs["community"], "syn")
        self.assertContains(r, "OID risponde su Banco prova")
        self.post("avanti", bersaglio=f"d:{self.disp.pk}")
        self._resto()
        c = ColonnaProfiloSNMP.objects.get(profilo=self.profilo)
        self.assertTrue(c.verificata)
        self.assertIn("Banco prova", c.fonte)

    def test_senza_prova_colonna_non_verificata(self):
        self._oid()
        self.post("avanti", bersaglio="")
        r = self._resto()
        self.assertEqual(r.status_code, 302, r.context and r.context.get("avviso"))
        self.assertFalse(ColonnaProfiloSNMP.objects.get(profilo=self.profilo).verificata)

    def test_prova_fallita_mostra_codice(self):
        self._oid()
        with mock.patch(LEGGI_SPEC, side_effect=SNMPError("192.0.2.92: errore SNMP noSuchName, codice 2")):
            r = self.post("prova", bersaglio=f"d:{self.disp.pk}")
        self.assertContains(r, "SNMP-005")

    def test_apparato_di_prova_non_valido_non_usa_quello_precedente(self):
        self._oid()
        with mock.patch(LEGGI_SPEC, return_value=({OID: 1}, {})):
            self.post("prova", bersaglio=f"d:{self.disp.pk}")
        with mock.patch(LEGGI_SPEC) as leggi:
            r = self.post("prova", bersaglio="d:999999")
        leggi.assert_not_called()
        self.assertContains(r, "Apparato non valido")

    def test_profilo_cancellato_a_meta_wizard(self):
        self._oid()
        self.profilo.delete()
        r = self.client.get(self.url)
        self.assertRedirects(r, reverse("contatori:snmp_centrale"), fetch_redirect_response=False)

    def test_nuova_colonna_in_fondo_all_ordine(self):
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Prima", oid="1.3.6.1.4.1.99999.9.0", ordine=7)
        self._oid()
        self.post("avanti", bersaglio="")
        self._resto()
        self.assertEqual(ColonnaProfiloSNMP.objects.get(profilo=self.profilo, oid=OID).ordine, 8)

    def test_oid_duplicato_bloccato(self):
        ColonnaProfiloSNMP.objects.create(profilo=self.profilo, nome="Esistente", oid=OID)
        r = self._oid()
        self.assertEqual(self.stato()["passo"], 0)
        self.assertContains(r, "già una colonna del profilo")

    def test_contatore_mfc_con_valore_non_numerico_snmp_006(self):
        self._oid()
        with mock.patch(LEGGI_SPEC, return_value=({OID: b"pronto"}, {})):
            self.post("prova", bersaglio=f"d:{self.disp.pk}")
        self.post("avanti", bersaglio=f"d:{self.disp.pk}")
        r = self.post("avanti", tipo_valore="NUMERO", unita="", fattore="1", contatore_mfc="a4_bn", etichette="")
        self.assertContains(r, "SNMP-006")
        self.assertEqual(self.stato()["passo"], 2)

    def test_soglie_incoerenti(self):
        self._oid()
        self.post("avanti", bersaglio="")
        self.post("avanti", tipo_valore="NUMERO", unita="", fattore="1", contatore_mfc="", etichette="")
        r = self.post("avanti", soglia_warning_min="10", soglia_warning_max="5")
        self.assertContains(r, "deve essere ≥ della minima")


class WizardSondaTests(_Base):
    tipo = "sonda"

    def setUp(self):
        self.disp = DispositivoSNMP.objects.create(nome="Ups sintetico", host="192.0.2.93", community="syn")
        self.query = {"dispositivo": self.disp.pk}
        super().setUp()

    def test_prova_obbligatoria_poi_crea(self):
        self.post("avanti", nome="Carica batteria", oid=OID, modalita="GET", aggregazione="PRIMO")
        r = self.post("avanti")
        self.assertEqual(self.stato()["passo"], 1)
        self.assertContains(r, "Esegui la prova")
        with mock.patch(LEGGI_SPEC, return_value=({OID: 97}, {})):
            self.post("prova", bersaglio="d:99999")  # il bersaglio forzato e' sempre il dispositivo
        self.assertIn("Ups sintetico", self.stato()["extra"]["prova"]["bersaglio"])
        self.post("avanti")
        self.post("avanti", tipo_valore="NUMERO", unita="%", fattore="1", etichette="")
        self.post("avanti")
        r = self.post("conferma")
        s = SondaSNMP.objects.get()
        self.assertEqual((s.dispositivo, s.oid, s.unita), (self.disp, OID, "%"))
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[self.disp.pk]),
                             fetch_redirect_response=False)

    def test_tipo_inesistente_404(self):
        self.assertEqual(self.client.get(reverse("contatori:wizard_avvia", args=["nulla"])).status_code, 404)

    def test_sola_consultazione_403_json(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            r = self.client.post(self.url, {"azione": "prova"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 403)
