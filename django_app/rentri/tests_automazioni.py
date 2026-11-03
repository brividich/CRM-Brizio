"""Automazioni del registro RENTRI: dati proposti, catena dalla scheda, catalogo EER, lettura FIR, promemoria.

Solo dati sintetici: codici e descrizioni inventati dove non serve l'elenco reale.
"""
import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from . import catalogo
from .lettura_fir import leggi_fir
from .models import CatalogoEER, RegistroRifiuti
from .promemoria import invia_promemoria, scarichi_senza_effettivo


def _pdf(righe):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 60
    for riga in righe:
        page.insert_text((50, y), riga, fontsize=10)
        y += 16
    data = doc.tobytes()
    doc.close()
    return data


class _Base(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="rentri-auto", password="x", is_superuser=True)
        self.client.force_login(self.user)

    def mov(self, tipo, codice="15 01 06", **kw):
        kw.setdefault("data", datetime.date(2026, 10, 1))
        kw.setdefault("quantita", 10)
        kw.setdefault("unita", "kg")
        return RegistroRifiuti.objects.create(tipo=tipo, codice=codice, **kw)


@override_settings(LEGACY_AUTH_ENABLED=False)
class CatalogoTests(_Base):
    def test_normalizza(self):
        self.assertEqual(catalogo.normalizza("15 01 06"), ("150106", False))
        self.assertEqual(catalogo.normalizza("160601*"), ("160601", True))
        self.assertIsNone(catalogo.normalizza("15 01"))

    def test_leggi_csv_e_html(self):
        csv = "codice;descrizione\n15 01 06;imballaggi sintetici misti\n16 06 01*;accumulatori sintetici\n".encode()
        self.assertEqual(catalogo.leggi_file("e.csv", csv), [
            ("150106", False, "imballaggi sintetici misti"), ("160601", True, "accumulatori sintetici"),
        ])
        html = (
            "<html><body><table><tr><td>15</td><td>RIFIUTI DI IMBALLAGGIO</td></tr>"
            "<tr><td>15 01</td><td>imballaggi</td></tr>"
            "<tr><td>15 01 06</td><td>imballaggi in materiali misti</td></tr>"
            "<tr><td>16 06 01*</td><td>batterie al piombo</td></tr></table></body></html>"
        ).encode()
        self.assertEqual(catalogo.leggi_file("e.html", html), [
            ("150106", False, "imballaggi in materiali misti"), ("160601", True, "batterie al piombo"),
        ])

    def test_confronta(self):
        self.assertEqual(catalogo.confronta("15 01 06")["stato"], "assente")
        catalogo.sostituisci([("150106", False, "imballaggi misti"), ("160601", True, "batterie")])
        self.assertEqual(catalogo.confronta("150106")["stato"], "ok")
        self.assertEqual(catalogo.confronta("15 01 06")["descrizione"], "imballaggi misti")
        self.assertEqual(catalogo.confronta("16 06 01")["stato"], "asterisco")
        self.assertEqual(catalogo.confronta("99 99 99")["stato"], "sconosciuto")
        self.assertEqual(catalogo.confronta("1501")["stato"], "formato")
        self.assertEqual([c["codice"] for c in catalogo.cerca("batt")], ["16 06 01*"])

    def test_impostazioni_rifiuta_file_incompleto(self):
        f = SimpleUploadedFile("e.csv", b"15 01 06;imballaggi\n", content_type="text/csv")
        r = self.client.post("/rentri/impostazioni/", {"azione": "catalogo_eer", "file_catalogo": f})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(CatalogoEER.objects.exists())

    def test_impostazioni_carica_catalogo(self):
        righe = "\n".join(f"{c:02d} {s:02d} {n:02d};voce sintetica {c}-{s}-{n}"
                          for c in range(1, 21) for s in range(1, 6) for n in range(1, 7))
        f = SimpleUploadedFile("e.csv", righe.encode(), content_type="text/csv")
        r = self.client.post("/rentri/impostazioni/", {"azione": "catalogo_eer", "file_catalogo": f})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(CatalogoEER.objects.count(), 600)


@override_settings(LEGACY_AUTH_ENABLED=False)
class DatiPropostiTests(_Base):
    def test_cer_info_propone_unita_pericolosita_e_giacenza(self):
        self.mov("C", "16 06 01*", unita="kg", quantita=12, pericolosita="HP8")
        catalogo.sostituisci([("160601", True, "batterie sintetiche")])
        r = self.client.get("/rentri/api/cer-info/", {"codice": "16 06 01*"}).json()
        self.assertEqual(r["unita"], "kg")
        self.assertEqual(r["pericolosita"], "HP8")
        self.assertEqual(r["giacenza"], "12.000")
        self.assertEqual(r["catalogo"]["stato"], "ok")

    def test_codici_include_catalogo_per_nome(self):
        catalogo.sostituisci([("150106", False, "imballaggi misti"), ("150102", False, "imballaggi plastica")])
        self.mov("C", "15 01 06")
        r = self.client.get("/rentri/api/codici/", {"q": "imballaggi"}).json()
        self.assertEqual([c["codice"] for c in r["catalogo"]], ["15 01 02", "15 01 06"])
        r = self.client.get("/rentri/api/codici/", {"q": "1501"}).json()
        self.assertEqual(r["codici"], ["15 01 06"])
        self.assertEqual([c["codice"] for c in r["catalogo"]], ["15 01 02"])

    def test_scarica_da_carico_precompila(self):
        c = self.mov("C", quantita=7.5)
        r = self.client.get(f"/rentri/scarico-originale/?da={c.pk}")
        self.assertContains(r, 'value="15 01 06"')
        self.assertContains(r, 'value="7.500"')
        self.assertContains(r, f'["{c.id_registrazione}"]')
        self.assertContains(r, f"Compilato da C - Carico {c.id_registrazione}")

    def test_da_di_tipo_sbagliato_ignorato(self):
        o = self.mov("O")
        r = self.client.get(f"/rentri/scarico-originale/?da={o.pk}")
        self.assertNotContains(r, "Compilato da")

    def test_duplica_e_codice(self):
        c = self.mov("C", "16 06 01*", unita="t", pericolosita="HP8")
        r = self.client.get(f"/rentri/carico/?duplica={c.pk}")
        self.assertContains(r, 'value="16 06 01*"')
        self.assertContains(r, 'value="HP8"')
        self.assertContains(r, '<option value="t" selected>')
        r = self.client.get("/rentri/scarico-originale/?codice=15%2001%2006")
        self.assertContains(r, 'value="15 01 06"')

    def test_scheda_mostra_il_passo_successivo(self):
        c = self.mov("C")
        r = self.client.get(f"/rentri/{c.pk}/")
        self.assertContains(r, f"/rentri/scarico-originale/?da={c.pk}")
        self.assertContains(r, f"/rentri/carico/?duplica={c.pk}")
        o = self.mov("O", rif_op=c.id_registrazione, data=datetime.date(2026, 10, 2))
        r = self.client.get(f"/rentri/{c.pk}/")
        self.assertNotContains(r, "Scarica (O)")
        r = self.client.get(f"/rentri/{o.pk}/")
        self.assertContains(r, f"/rentri/scarico-effettivo/?da={o.pk}")

    def test_giacenze_link_scarica(self):
        self.mov("C")
        r = self.client.get("/rentri/giacenze/")
        self.assertContains(r, "/rentri/scarico-originale/?codice=15%2001%2006")

    def test_inserito_da_legacy_id_valorizzato_se_presente(self):
        r = self.client.post("/rentri/carico/", {
            "tipo": "C", "data": "2026-10-01", "codice": "15 01 06", "quantita": "3", "unita": "kg", "rentri_si_no": "false",
        })
        self.assertTrue(r.json()["ok"], r.content)


class LetturaFirTests(TestCase):
    RIGHE = [
        "FORMULARIO DI IDENTIFICAZIONE DEL RIFIUTO",
        "Formulario n. ABCD 012345/26",
        "Data emissione 14/10/2026",
        "Destinatario",
        "Denominazione: Impianto Sintetico Srl",
        "Codice EER 15 01 06",
        "Quantita: 1.250,5 kg",
        "Peso da verificarsi a destino: 1.198 kg",
    ]

    def test_regole(self):
        esito = leggi_fir(_pdf(self.RIGHE), tipo="O", usa_ai=False)
        campi = {k: v["valore"] for k, v in esito["campi"].items()}
        self.assertEqual(campi["numero_fir"], "ABCD 012345/26")
        self.assertEqual(campi["data"], "2026-10-14")
        self.assertEqual(campi["codice"], "15 01 06")
        self.assertEqual(campi["quantita"], "1250.5")
        self.assertEqual(campi["unita"], "kg")
        self.assertFalse(esito["ai"])

    def test_scarico_effettivo_preferisce_peso_a_destino(self):
        esito = leggi_fir(_pdf(self.RIGHE), tipo="M", usa_ai=False)
        self.assertEqual(esito["campi"]["quantita"]["valore"], "1198")

    def test_ai_solo_per_campi_mancanti_e_verificati(self):
        class Risposta:
            content = '{"codice_eer": "15 01 06", "quantita": 40, "unita": "kg", "numero_fir": "INVENTATO 1"}'

        righe = ["Formulario", "Rifiuto 15 01 06 imballaggi", "quaranta chilogrammi"]
        with patch("ai_assistant.services.chat_with_ollama", return_value=Risposta()):
            esito = leggi_fir(_pdf(righe), tipo="O")
        self.assertTrue(esito["ai"])
        self.assertEqual(esito["campi"]["quantita"]["fonte"], "ai")
        # Un numero che non compare nel testo non viene proposto.
        self.assertNotIn("numero_fir", esito["campi"])

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_api(self):
        User = get_user_model()
        self.client.force_login(User.objects.create_user(username="fir", password="x", is_superuser=True))
        f = SimpleUploadedFile("fir.pdf", _pdf(self.RIGHE), content_type="application/pdf")
        with patch("ai_assistant.services.chat_with_ollama", side_effect=RuntimeError("spento")):
            r = self.client.post("/rentri/api/leggi-fir/", {"file": f, "tipo": "O"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["campi"]["codice"]["valore"], "15 01 06")


@override_settings(LEGACY_AUTH_ENABLED=False)
class PromemoriaTests(_Base):
    def test_scarico_senza_effettivo_notifica_una_volta_a_settimana(self):
        oggi = datetime.date(2026, 12, 15)
        c = self.mov("C", data=datetime.date(2026, 9, 1))
        o = self.mov("O", rif_op=c.id_registrazione, data=datetime.date(2026, 10, 1), inserito_da_legacy_id=4242)
        c2 = self.mov("C", data=datetime.date(2026, 9, 2))
        o2 = self.mov("O", rif_op=c2.id_registrazione, data=datetime.date(2026, 10, 1))
        self.mov("M", rif_op=o2.id_registrazione, data=datetime.date(2026, 10, 5))
        self.assertEqual([r.pk for r in scarichi_senza_effettivo(oggi, 60)], [o.pk])

        with patch("core.notifiche.invia_notifica") as invia:
            esito = invia_promemoria(oggi)
        self.assertEqual(esito["scarichi"], 1)
        uid, tipo, messaggio, url = invia.call_args.args
        self.assertEqual(uid, 4242)
        self.assertIn(o.id_registrazione, messaggio)
        self.assertEqual(url, f"/rentri/scarico-effettivo/?da={o.pk}")
        o.refresh_from_db()
        self.assertEqual(o.promemoria_m_il, oggi)

        with patch("core.notifiche.invia_notifica") as invia:
            invia_promemoria(oggi + datetime.timedelta(days=3))
        invia.assert_not_called()
        with patch("core.notifiche.invia_notifica") as invia:
            invia_promemoria(oggi + datetime.timedelta(days=7))
        invia.assert_called_once()

    def test_recente_non_notificato(self):
        self.mov("O", data=datetime.date(2026, 12, 1), inserito_da_legacy_id=1)
        with patch("core.notifiche.invia_notifica") as invia:
            esito = invia_promemoria(datetime.date(2026, 12, 15))
        self.assertEqual(esito["scarichi"], 0)
        invia.assert_not_called()
