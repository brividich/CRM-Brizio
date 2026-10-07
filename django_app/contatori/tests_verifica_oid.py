"""Verifica OID su apparato e proposta colonne: dati sintetici, nessuna rete."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from puresnmp.exc import ErrorResponse
from x690.types import ObjectIdentifier

from contatori import services, verifica_oid
from contatori.models import ColonnaProfiloSNMP, DispositivoSNMP, ProfiloSNMP, SondaSNMP

CPU = "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"
SENSORI = "1.3.6.1.4.1.11.2.14.11.1.2.6.1.4"
INVENTATO = "1.3.6.1.4.1.20251.1.1.0"


class EstrazioneTests(SimpleTestCase):
    def test_estrae_oid_da_testo_incollato(self):
        testo = (
            "CPU Load (Media 1 min).1.3.6.1.4.1.3097.6.3.77.0Valore espresso in centesimi\n"
            "Memoria Totale .1.3.6.1.4.1.20251.1.1.0 o .1.3.6.1.4.1.2021.4.5.0In kB\n"
            "Stato (Up/Down).1.3.6.1.2.1.2.2.1.8 (ifOperStatus) e di nuovo 1.3.6.1.2.1.2.2.1.8"
        )
        self.assertEqual(verifica_oid.estrai_oid(testo), [
            "1.3.6.1.4.1.3097.6.3.77.0", "1.3.6.1.4.1.20251.1.1.0",
            "1.3.6.1.4.1.2021.4.5.0", "1.3.6.1.2.1.2.2.1.8",
        ])

    def test_rami_noti_per_produttore_piu_standard(self):
        rami = [b for b, _ in verifica_oid.rami_noti("1.3.6.1.4.1.11.2.3.7.11.181")]
        self.assertIn("1.3.6.1.4.1.11.2.14.11.5.1.9.6", rami)
        self.assertIn("1.3.6.1.2.1.2.2.1.8", rami)
        self.assertNotIn("1.3.6.1.4.1.3097.6.3", rami)

    def test_raggruppa_foglie_per_colonna(self):
        foglie = [(f"{SENSORI}.{i}", 4) for i in (1, 2, 3)] + [("1.3.6.1.4.1.11.2.14.11.1.2.6.1.7.1", b"Fan")]
        cand = verifica_oid.raggruppa_ramo(foglie, "ramo")
        walk = next(c for c in cand if c["oid"] == SENSORI)
        self.assertEqual((walk["modalita"], walk["righe"], walk["max"]), ("WALK", 3, "4"))
        singolo = next(c for c in cand if c["modalita"] == "GET")
        self.assertEqual(singolo["tipo"], ColonnaProfiloSNMP.TipoValore.TESTO)

    def test_valori_timeticks_e_testo_numerico(self):
        self.assertEqual(verifica_oid._valore(timedelta(seconds=90))[0], ColonnaProfiloSNMP.TipoValore.TIMETICKS)
        self.assertEqual(verifica_oid._valore(b"42")[0], ColonnaProfiloSNMP.TipoValore.NUMERO)
        self.assertEqual(verifica_oid._valore(b"Aruba JL260A")[0], ColonnaProfiloSNMP.TipoValore.TESTO)


class _Client:
    """Apparato finto: CPU scalare, tabella sensori, nient'altro."""

    def __init__(self, rifiuta=False):
        self.rifiuta = rifiuta

    async def get(self, oid):
        if self.rifiuta:
            raise ErrorResponse.construct(16, ObjectIdentifier(oid))
        if oid == CPU:
            return 7
        raise ErrorResponse.construct(2, ObjectIdentifier(oid))

    async def walk(self, base):
        if base == SENSORI:
            for i, v in ((1, 4), (2, 4), (3, 2)):
                yield SimpleNamespace(oid=f"{SENSORI}.{i}", value=v)


def _verifica(client, oids):
    with mock.patch("puresnmp.PyWrapper", return_value=client):
        return verifica_oid.verifica("192.0.2.40", oids, community="sintetica", porta=161,
                                     timeout=1, versione="v2c")


class VerificaTests(SimpleTestCase):
    def test_get_walk_e_assenti(self):
        esito = _verifica(_Client(), [CPU, SENSORI, INVENTATO])
        self.assertEqual(esito["errore"], "")
        per_oid = {c["oid"]: c for c in esito["candidati"]}
        self.assertEqual(per_oid[CPU]["modalita"], "GET")
        self.assertEqual((per_oid[SENSORI]["modalita"], per_oid[SENSORI]["righe"]), ("WALK", 3))
        self.assertEqual(esito["assenti"], [INVENTATO])

    def test_rifiuto_dell_apparato_ferma_e_spiega(self):
        esito = _verifica(_Client(rifiuta=True), [CPU, SENSORI])
        self.assertEqual(esito["candidati"], [])
        self.assertIn("codice 16", esito["errore"])
        self.assertNotIn("sintetica", esito["errore"])


class PropostaAITests(SimpleTestCase):
    CAND = [
        {"oid": CPU, "modalita": "GET", "righe": 1, "tipo": "NUMERO", "campione": "7", "min": "", "max": "", "origine": "elenco"},
        {"oid": SENSORI, "modalita": "WALK", "righe": 3, "tipo": "NUMERO", "campione": "4, 4, 2", "min": "2", "max": "4", "origine": "elenco"},
    ]

    def test_scarta_oid_non_verificati_e_valori_non_ammessi(self):
        proposte = verifica_oid.normalizza_proposta({"colonne": [
            {"oid": CPU, "nome": "CPU", "unita": "%", "aggregazione": "SOMMA", "avviso_sopra": "85", "critico_sopra": 95},
            {"oid": "." + SENSORI, "nome": "Sensori", "aggregazione": "boh", "etichette": "2=Guasto, 4=Ok"},
            {"oid": INVENTATO, "nome": "Inventato"},
        ]}, self.CAND)
        self.assertEqual(set(proposte), {CPU, SENSORI})
        self.assertEqual(proposte[CPU]["aggregazione"], "PRIMO")      # GET: sempre primo valore
        self.assertEqual(proposte[CPU]["critico_sopra"], "95")
        self.assertEqual(proposte[SENSORI]["aggregazione"], "MASSIMO")  # non ammessa -> default

    def test_risposta_a_righe_anche_troncata(self):
        raw = (f"{CPU} | CPU | % | 1 | PRIMO | 85 | 95 |  | carico CPU\n"
               f"{INVENTATO} | Inventato | | 1 | PRIMO | | | | x\n"
               f"{SENSORI} | Sensori | | 1 | MAS")  # troncata a meta' riga
        proposte = verifica_oid.leggi_risposta(raw, self.CAND)
        self.assertEqual(proposte[CPU]["nome"], "CPU")
        self.assertEqual(proposte[CPU]["critico_sopra"], "95")
        self.assertEqual(proposte[SENSORI]["aggregazione"], "MASSIMO")  # valore troncato -> default
        self.assertNotIn(INVENTATO, proposte)

    def test_al_modello_al_massimo_un_blocco(self):
        molti = [dict(self.CAND[0], oid=f"1.3.6.1.4.1.9.9.{i}.0") for i in range(40)]
        disp = SimpleNamespace(sys_description="x", modello="", nome="x", sys_object_id="")
        with mock.patch("ai_assistant.services.chat_with_ollama", return_value=SimpleNamespace(content="")) as m:
            verifica_oid.proponi_con_ai(disp, molti)
        contesto = m.call_args.kwargs["runtime_context"]
        self.assertEqual(contesto.count("1.3.6.1.4.1.9.9."), verifica_oid.MAX_AI_PER_VOLTA)

    def test_catalogo_nomi_noti(self):
        cand = [dict(self.CAND[0], oid="1.3.6.1.4.1.3097.6.3.77.0"),
                dict(self.CAND[0], oid="1.3.6.1.2.1.2.2.1.8.3"),
                dict(self.CAND[0], oid="1.3.6.1.4.1.3097.6.3.30.0")]
        proposte = verifica_oid.proposte_catalogo(cand)
        self.assertEqual(proposte["1.3.6.1.4.1.3097.6.3.77.0"]["fattore"], "0.01")
        self.assertEqual(proposte["1.3.6.1.2.1.2.2.1.8.3"]["nome"], "Stato porte (riga 3)")
        self.assertNotIn("1.3.6.1.4.1.3097.6.3.30.0", proposte)  # sconosciuto: resta all'AI

    def test_ai_non_disponibile(self):
        with mock.patch("ai_assistant.services.chat_with_ollama", side_effect=RuntimeError("giu")):
            self.assertEqual(verifica_oid.proponi_con_ai(SimpleNamespace(
                sys_description="", modello="", nome="x", sys_object_id=""), self.CAND), {})

    def test_contesto_senza_community(self):
        disp = SimpleNamespace(sys_description="Aruba JL260A 2930F", modello="", nome="sw", sys_object_id="1.3.6.1.4.1.11.2.3.7.11.181")
        testo = verifica_oid.contesto_ai(disp, self.CAND)
        self.assertIn(SENSORI, testo)
        self.assertIn("2..4", testo)


class TimeTicksTests(SimpleTestCase):
    def test_timedelta_diventa_centesimi(self):
        self.assertEqual(services._intero_grezzo(timedelta(seconds=12)), 1200)
        sonda = SondaSNMP(tipo_valore=SondaSNMP.TipoValore.TIMETICKS, fattore=Decimal("1"))
        self.assertEqual(services._numero_sonda(sonda, timedelta(seconds=12)), Decimal("12"))


class PaginaTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser(
            username="verifica_oid_admin", password="test-only-password"))
        self.profilo = ProfiloSNMP.objects.get(slug="hpe-aruba")
        self.disp = DispositivoSNMP.objects.create(
            nome="Switch prova", host="192.0.2.41", profilo_snmp=self.profilo,
            sys_object_id="1.3.6.1.4.1.11.2.3.7.11.181", sys_description="Aruba JL260A 2930F-48G")
        self.url = reverse("contatori:snmp_dispositivo_verifica_oid", args=[self.disp.pk])

    def _verifica(self):
        esito = {"candidati": PropostaAITests.CAND, "assenti": [INVENTATO], "errore": ""}
        with mock.patch.object(verifica_oid, "verifica_dispositivo", return_value=esito) as m:
            r = self.client.post(self.url, {"azione": "verifica", "oids": f"{CPU} {SENSORI} {INVENTATO}"})
        self.assertEqual(r.status_code, 302)
        m.assert_called_once()
        self.assertEqual(m.call_args.args[1], [CPU, SENSORI, INVENTATO])

    def test_pagina_e_pulsante_in_scheda(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        scheda = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.disp.pk]))
        self.assertContains(scheda, self.url)

    def test_verifica_poi_aggiunta_al_profilo(self):
        self._verifica()
        pagina = self.client.get(self.url)
        self.assertContains(pagina, SENSORI)
        self.assertContains(pagina, INVENTATO)  # tra gli assenti
        with mock.patch.object(verifica_oid, "proponi_con_ai", return_value={
                CPU: {"nome": "CPU", "unita": "%", "fattore": "1", "aggregazione": "PRIMO",
                      "avviso_sopra": "85", "critico_sopra": "95", "etichette": "", "motivo": "carico CPU"}}):
            self.client.post(self.url, {"azione": "proponi"})
        self.assertContains(self.client.get(self.url), "carico CPU")
        r = self.client.post(self.url, {
            "azione": "aggiungi", "sel": ["0", "1"], "destinazione": "profilo", "profilo": self.profilo.pk,
            "nome_0": "CPU", "unita_0": "%", "fattore_0": "1", "avviso_0": "85", "critico_0": "95",
            "nome_1": "Sensori peggiore", "aggregazione_1": "MASSIMO", "critico_1": "",
            "etichette_1": "2=Guasto, 3=Attenzione, 4=Ok",
        })
        self.assertEqual(r.status_code, 302)
        cpu = ColonnaProfiloSNMP.objects.get(profilo=self.profilo, oid=CPU)
        self.assertTrue(cpu.verificata)
        self.assertIn("Verifica OID", cpu.fonte)
        self.assertEqual(cpu.soglia_critica_max, Decimal("95"))
        sens = ColonnaProfiloSNMP.objects.get(profilo=self.profilo, oid=SENSORI)
        self.assertEqual((sens.modalita, sens.aggregazione), ("WALK", "MASSIMO"))
        self.assertTrue(self.disp.sonde.filter(oid=SENSORI).exists())  # profilo riapplicato
        self.assertFalse(ColonnaProfiloSNMP.objects.filter(oid=INVENTATO).exists())

    def test_proponi_solo_righe_spuntate(self):
        self._verifica()
        with mock.patch.object(verifica_oid, "proponi_con_ai", return_value={}) as m:
            self.client.post(self.url, {"azione": ["aggiungi", "proponi"], "sel": ["1"]})
        self.assertEqual([c["oid"] for c in m.call_args.args[1]], [SENSORI])
        self.assertFalse(ColonnaProfiloSNMP.objects.filter(oid=SENSORI).exists())  # proponi non aggiunge

    def test_solo_sul_dispositivo(self):
        self._verifica()
        self.client.post(self.url, {"azione": "aggiungi", "sel": ["0"], "destinazione": "dispositivo", "nome_0": "CPU"})
        self.assertTrue(SondaSNMP.objects.filter(dispositivo=self.disp, oid=CPU, nome="CPU").exists())
        self.assertFalse(ColonnaProfiloSNMP.objects.filter(profilo=self.profilo, oid=CPU).exists())

    def test_testo_senza_oid(self):
        r = self.client.post(self.url, {"azione": "verifica", "oids": "niente qui"}, follow=True)
        self.assertTrue(any("Nessun OID trovato" in str(m) for m in r.context["messages"]))
