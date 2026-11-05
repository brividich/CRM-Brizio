"""Dashboard «Da fare» e «La mia dotazione», nuova richiesta guidata: stessi numeri delle liste."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from . import dotazione, magazzino
from .models import CategoriaDPI, ConsegnaDPI, ModelloDPI, RichiestaDPI, StatoRichiesta, TagliaDPI, TipoDPI

User = get_user_model()
PERSONA = 501


def _richiesta(categoria, stato=StatoRichiesta.CONSEGNATA, persona=PERSONA, **campi):
    return RichiestaDPI.objects.create(
        categoria=categoria, stato=stato, richiedente_legacy_id=persona, richiedente_nome="Persona Prova", **campi
    )


def _consegna(richiesta, tra_giorni, **campi):
    oggi = timezone.localdate()
    consegna = ConsegnaDPI.objects.create(richiesta=richiesta, data_consegna=oggi - timedelta(days=100), **campi)
    # La scadenza si imposta dopo la creazione: save() puo' ricalcolarla dalla vita utile.
    scadenza = oggi + timedelta(days=tra_giorni) if tra_giorni is not None else None
    ConsegnaDPI.objects.filter(pk=consegna.pk).update(data_scadenza_stimata=scadenza)
    consegna.refresh_from_db()
    return consegna


class DotazioneTests(TestCase):
    def setUp(self):
        self.guanti = CategoriaDPI.objects.create(nome="Guanti")
        self.occhiali = CategoriaDPI.objects.create(nome="Occhiali")
        self.scarpe = CategoriaDPI.objects.create(nome="Scarpe")

    def _dotazione(self, previste=()):
        with patch("dpi.dotazione._categorie_previste", return_value=list(previste)):
            return dotazione.dotazione(PERSONA)

    def test_ordina_dal_piu_urgente_e_conta_da_sostituire(self):
        _consegna(_richiesta(self.occhiali), 200)
        _consegna(_richiesta(self.guanti), -5)
        _consegna(_richiesta(self.scarpe), 10)
        d = self._dotazione()
        self.assertEqual([x["semaforo"] for x in d["righe"]], ["rosso", "arancione", "verde"])
        self.assertEqual(d["righe"][0]["giorni_fa"], 5)
        self.assertEqual(d["n_da_sostituire"], 2)

    def test_sostituita_non_conta_e_non_e_di_altri(self):
        nuova = _consegna(_richiesta(self.guanti), 100)
        vecchia = _consegna(_richiesta(self.guanti), -50)
        ConsegnaDPI.objects.filter(pk=vecchia.pk).update(sostituita_da=nuova)
        _consegna(_richiesta(self.occhiali, persona=999), -1)
        d = self._dotazione()
        self.assertEqual([x["consegna"].pk for x in d["righe"]], [nuova.pk])
        self.assertEqual(d["n_da_sostituire"], 0)

    def test_ricambio_gia_richiesto_non_e_da_sostituire(self):
        _consegna(_richiesta(self.guanti), -1)
        aperta = _richiesta(self.guanti, stato=StatoRichiesta.INVIATA)
        d = self._dotazione()
        self.assertEqual(d["righe"][0]["ricambio_aperto"].pk, aperta.pk)
        self.assertEqual(d["n_da_sostituire"], 0)

    def test_mancanti_escludono_consegnati_e_gia_richiesti(self):
        _consegna(_richiesta(self.guanti), 100)
        _richiesta(self.occhiali, stato=StatoRichiesta.APPROVATA)
        d = self._dotazione(previste=[self.guanti, self.occhiali, self.scarpe])
        self.assertEqual([x["categoria"].pk for x in d["mancanti"]], [self.scarpe.pk])
        self.assertIn(f"categoria={self.scarpe.pk}", d["mancanti"][0]["url"])

    def test_aiuti_danno_ultima_consegna_e_richieste_aperte(self):
        tipo = TipoDPI.objects.create(categoria=self.guanti, nome="Antitaglio")
        modello = ModelloDPI.objects.create(tipo=tipo, codice="GT-1", nome="Blade")
        taglia = TagliaDPI.objects.create(modello=modello, valore="9")
        _consegna(_richiesta(self.guanti, tipo_dpi=tipo, modello_dpi=modello, taglia_dpi=taglia), -1)
        aperta = _richiesta(self.occhiali, stato=StatoRichiesta.INVIATA)
        aiuti = dotazione.aiuti_per_categoria(self._dotazione())
        ultima = aiuti[self.guanti.pk]["ultima"]
        self.assertEqual((ultima["tipo"], ultima["modello"], ultima["taglia"]), (tipo.pk, modello.pk, taglia.pk))
        self.assertEqual(ultima["etichetta"], "Antitaglio, Blade, taglia 9")
        self.assertEqual(dotazione.etichetta_categoria(aiuti[self.guanti.pk])["testo"], "Scaduto")
        self.assertEqual(aiuti[self.occhiali.pk]["aperte"][0]["numero"], aperta.numero)
        self.assertEqual(dotazione.etichetta_categoria(aiuti[self.occhiali.pk])["testo"], "Già richiesto")
        self.assertIsNone(dotazione.etichetta_categoria(None))


class DaRiordinareTests(TestCase):
    def test_senza_movimenti_il_magazzino_non_e_in_uso(self):
        tipo = TipoDPI.objects.create(categoria=CategoriaDPI.objects.create(nome="Mani"), nome="Guanti")
        esaurito = ModelloDPI.objects.create(tipo=tipo, codice="A", nome="A")
        self.assertEqual(magazzino.da_riordinare(), 0)
        ok = ModelloDPI.objects.create(tipo=tipo, codice="B", nome="B")
        magazzino.carica_ddt(ok, 5)
        self.assertEqual(magazzino.da_riordinare(), 1)
        magazzino.carica_ddt(esaurito, 5)
        self.assertEqual(magazzino.da_riordinare(), 0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PagineTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-dot", password="x", email="d@y.z")
        self.client.force_login(self.admin)
        self.guanti = CategoriaDPI.objects.create(nome="Guanti prova")
        self.occhiali = CategoriaDPI.objects.create(nome="Occhiali prova")

    def _tessere(self):
        return {t["etichetta"]: t for t in self.client.get(reverse("dpi:dashboard")).context["da_fare"]}

    def test_ogni_numero_coincide_con_la_lista_che_apre(self):
        _consegna(_richiesta(self.guanti), -3)
        _consegna(_richiesta(self.occhiali), 5)
        _consegna(_richiesta(self.occhiali), 200)
        _richiesta(self.guanti, stato=StatoRichiesta.INVIATA)
        tessere = self._tessere()
        for etichetta in ("In attesa di approvazione", "DPI scaduti", "In scadenza (30 gg)"):
            with self.subTest(etichetta):
                t = tessere[etichetta]
                self.assertEqual(t["n"], 1)
                self.assertEqual(self.client.get(t["url"]).context["page_obj"].paginator.count, t["n"])

    def test_da_consegnare_distingue_il_magazzino(self):
        scarpe = CategoriaDPI.objects.create(nome="Scarpe prova", consegna_magazzino=False)
        _richiesta(self.guanti, stato=StatoRichiesta.APPROVATA)
        _richiesta(scarpe, stato=StatoRichiesta.APPROVATA)
        t = self._tessere()["Da consegnare"]
        self.assertEqual(t["n"], 1)
        self.assertEqual(t["nota"], "+ 1 non del magazzino")

    def test_dipendente_senza_coda_non_vede_da_fare(self):
        utente = User.objects.create_user(username="dpi-dip", password="x")
        UserOnboarding.objects.create(user=utente, completed=True)
        self.client.force_login(utente)
        with patch("dpi.views._is_gestore", return_value=False), patch("dpi.views._gestione_scope", return_value=(False, set())):
            response = self.client.get(reverse("dpi:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["da_fare"], [])
        self.assertNotContains(response, "Da riordinare")

    def test_da_consegnare_solo_fuori_magazzino_apre_il_banco_completo(self):
        scarpe = CategoriaDPI.objects.create(nome="Scarpe sole", consegna_magazzino=False)
        _richiesta(scarpe, stato=StatoRichiesta.APPROVATA)
        self.assertTrue(self._tessere()["Da consegnare"]["url"].endswith("?tutte=1"))

    def test_dashboard_mostra_la_dotazione_con_il_link_al_ricambio(self):
        _consegna(_richiesta(self.guanti), -3)
        with patch("dpi.views._legacy_id", return_value=PERSONA), patch("dpi.dotazione._categorie_previste", return_value=[self.occhiali]):
            body = self.client.get(reverse("dpi:dashboard")).content.decode()
        self.assertIn("La mia dotazione", body)
        self.assertIn("Richiedi il ricambio", body)
        self.assertIn("scaduto da 3 giorni", body)
        self.assertIn(f"categoria={self.guanti.pk}", body)
        self.assertIn("Previsto dalla tua mansione", body)

    def test_nuova_precompila_dal_link(self):
        response = self.client.get(reverse("dpi:nuova"), {"categoria": self.guanti.pk, "motivo": "scadenza", "tipo": "x"})
        self.assertEqual(response.context["scelta"]["categoria"], self.guanti.pk)
        self.assertIsNone(response.context["scelta"]["tipo"])
        self.assertEqual(response.context["testo_motivazione"], "Sostituzione alla scadenza")

    def test_motivo_sconosciuto_non_finisce_nel_modulo(self):
        response = self.client.get(reverse("dpi:nuova"), {"motivo": "<script>"})
        self.assertEqual(response.context["testo_motivazione"], "")

    def test_errore_nel_modulo_non_perde_quanto_scritto(self):
        response = self.client.post(reverse("dpi:nuova"), {
            "categoria_id": self.guanti.pk, "tipo_dpi_id": "999999", "quantita": "4", "motivazione": "Rotti ieri",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scelta"]["categoria"], self.guanti.pk)
        self.assertEqual(response.context["quantita_scelta"], "4")
        self.assertContains(response, "Rotti ieri")

    def test_chi_gestisce_vede_il_menu_completo_anche_in_nuova_richiesta(self):
        self.assertContains(self.client.get(reverse("dpi:nuova")), reverse("dpi:banco"))

    def test_senza_anagrafica_me_stesso_e_la_scelta_iniziale(self):
        """Prima il primo dipendente in elenco risultava scelto e riceveva la richiesta."""
        persone = [{"id": 77, "nome": "Altra Persona"}]
        with patch("dpi.views._dipendenti_selezionabili", return_value=persone), patch("dpi.views._legacy_id", return_value=None):
            body = self.client.get(reverse("dpi:nuova")).content.decode()
        self.assertLess(body.index("Me stesso"), body.index("Altra Persona"))
        self.assertIn('<option value="" selected>Me stesso</option>', body)
