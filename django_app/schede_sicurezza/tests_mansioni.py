from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import (
    DipendenteAnagraficaAziendale,
    DipendenteAssegnazione,
    Mansione,
    Reparto,
)
from anagrafica.services.assegnazioni import attiva_assegnazione
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica, Profile

from .models import PresaVisioneScheda, ProdottoChimico, SchedaSicurezza
from .reports import matrice_presa_visione, prodotti_senza_mansioni
from .services.assegnazioni import (
    conteggio_sds_per_mansione,
    notifica_cambio_mansione,
    notifica_nuova_versione,
    prodotti_sds_per_mansione,
    profilo_sds_utente,
)

User = get_user_model()


def _pdf(nome="sds.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4\n%finto\n", content_type="application/pdf")


class SdsPerMansioneWorkflowTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.vecchia = Mansione.objects.create(nome="Addetto montaggio")
        self.nuova = Mansione.objects.create(nome="Verniciatore", livello_rischio=Mansione.RISCHIO_ALTO)

        self.utente_legacy = UtenteLegacy.objects.create(
            nome="dip-sds", email="dip-sds@example.local", password="x"
        )
        self.anagrafica = AnagraficaDipendente.objects.create(
            aliasusername="dip-sds",
            nome="Mario",
            cognome="Rossi",
            reparto=self.reparto.nome,
            mansione=self.vecchia.nome,
            utente=self.utente_legacy,
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.anagrafica.pk
        )
        self.user = User.objects.create_user(
            username="dip-sds", password="x", is_superuser=True, is_staff=True
        )
        Profile.objects.create(user=self.user, legacy_user_id=self.utente_legacy.pk)

        self.prodotto_vecchio = ProdottoChimico.objects.create(nome="Olio montaggio")
        self.prodotto_vecchio.mansioni.add(self.vecchia)
        self.scheda_vecchia = SchedaSicurezza.objects.create(
            prodotto=self.prodotto_vecchio, pdf=_pdf("vecchia.pdf"), versione="1", is_corrente=True
        )
        self.prodotto_nuovo = ProdottoChimico.objects.create(nome="Diluente verniciatura")
        self.prodotto_nuovo.mansioni.add(self.nuova)
        self.scheda_nuova = SchedaSicurezza.objects.create(
            prodotto=self.prodotto_nuovo, pdf=_pdf("nuova.pdf"), versione="2", is_corrente=True
        )

    def test_cruscotto_personale_mostra_solo_sds_della_mansione_corrente(self):
        profilo = profilo_sds_utente(self.user)
        self.assertEqual(profilo.mansione_nome, self.vecchia.nome)
        self.assertEqual([s.pk for s in profilo.da_leggere], [self.scheda_vecchia.pk])

        self.client.force_login(self.user)
        response = self.client.get(reverse("schede_sicurezza:sds_da_leggere"))
        self.assertContains(response, "Olio montaggio")
        self.assertNotContains(response, "Diluente verniciatura")

    def test_cambio_mansione_attivato_assegna_sds_e_notifica(self):
        assegnazione = DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=self.anagrafica.pk,
            data_inizio=timezone.localdate(),
            reparto=self.reparto.nome,
            mansione=self.nuova.nome,
        )

        self.assertTrue(attiva_assegnazione(assegnazione, user=self.user))

        profilo = profilo_sds_utente(self.user)
        self.assertEqual(profilo.mansione_nome, self.nuova.nome)
        self.assertEqual([s.pk for s in profilo.da_leggere], [self.scheda_nuova.pk])
        notifica = Notifica.objects.get(
            legacy_user_id=self.utente_legacy.pk, tipo="presa_visione"
        )
        self.assertIn("Nuova mansione", notifica.messaggio)
        self.assertEqual(notifica.url_azione, reverse("schede_sicurezza:sds_da_leggere"))

    def test_presa_visione_della_versione_corrente_chiude_il_pendente(self):
        self.anagrafica.mansione = self.nuova.nome
        self.anagrafica.save(update_fields=["mansione"])
        PresaVisioneScheda.objects.create(scheda=self.scheda_nuova, operatore=self.user)

        profilo = profilo_sds_utente(self.user)
        self.assertEqual(profilo.da_leggere, [])
        self.assertEqual([s.pk for s in profilo.completate], [self.scheda_nuova.pk])

    def test_nuova_versione_richiede_una_nuova_presa_visione(self):
        self.anagrafica.mansione = self.nuova.nome
        self.anagrafica.save(update_fields=["mansione"])
        PresaVisioneScheda.objects.create(scheda=self.scheda_nuova, operatore=self.user)
        nuova_versione = SchedaSicurezza.objects.create(
            prodotto=self.prodotto_nuovo,
            pdf=_pdf("nuova-v3.pdf"),
            versione="3",
            is_corrente=True,
        )

        self.assertEqual(notifica_nuova_versione(nuova_versione), 1)
        self.assertEqual(
            [s.pk for s in profilo_sds_utente(self.user).da_leggere], [nuova_versione.pk]
        )

    @override_settings(DEFAULT_FROM_EMAIL="hub@example.local", SITE_URL="https://hub.example.local")
    def test_cambio_mansione_manda_email_al_dipendente(self):
        self.anagrafica.email_notifica = "mario.rossi@example.local"
        self.anagrafica.save(update_fields=["email_notifica"])
        assegnazione = DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=self.anagrafica.pk,
            data_inizio=timezone.localdate(),
            reparto=self.reparto.nome,
            mansione=self.nuova.nome,
        )
        mail.outbox = []

        self.assertTrue(attiva_assegnazione(assegnazione, user=self.user))

        self.assertEqual(len(mail.outbox), 1)
        messaggio = mail.outbox[0]
        self.assertEqual(messaggio.to, ["mario.rossi@example.local"])
        self.assertIn(self.nuova.nome, messaggio.subject)
        # Il prodotto della mansione nuova c'è, quello della vecchia no.
        self.assertIn("Diluente verniciatura", messaggio.body)
        self.assertNotIn("Olio montaggio", messaggio.body)
        # La CTA porta al cruscotto dove la conferma incrementa le prese visione.
        corpo_html = messaggio.alternatives[0][0]
        self.assertIn("https://hub.example.local/schede-sicurezza/da-leggere/", corpo_html)

    @override_settings(DEFAULT_FROM_EMAIL="hub@example.local")
    def test_nessuna_email_se_le_sds_sono_gia_lette(self):
        self.anagrafica.email_notifica = "mario.rossi@example.local"
        self.anagrafica.save(update_fields=["email_notifica"])
        PresaVisioneScheda.objects.create(scheda=self.scheda_nuova, operatore=self.user)
        mail.outbox = []

        self.assertEqual(
            notifica_cambio_mansione(self.anagrafica.pk, self.nuova.nome, self.vecchia.nome), 0
        )
        self.assertEqual(mail.outbox, [])

    def test_conteggi_ed_elenco_sds_per_mansione(self):
        # Prodotto attivo senza scheda corrente: entra nell'elenco della scheda
        # mansione (va caricata la SDS) ma non nel conteggio delle SDS dovute.
        senza_scheda = ProdottoChimico.objects.create(nome="Sgrassante senza SDS")
        senza_scheda.mansioni.add(self.nuova)
        disattivo = ProdottoChimico.objects.create(nome="Prodotto dismesso", attivo=False)
        disattivo.mansioni.add(self.nuova)
        SchedaSicurezza.objects.create(
            prodotto=disattivo, pdf=_pdf("dismesso.pdf"), versione="1", is_corrente=True
        )

        conteggi = conteggio_sds_per_mansione([self.vecchia.pk, self.nuova.pk])
        self.assertEqual(conteggi.get(self.vecchia.pk), 1)
        self.assertEqual(conteggi.get(self.nuova.pk), 1)

        righe = prodotti_sds_per_mansione(self.nuova.pk)
        self.assertEqual(
            [(riga["prodotto"].nome, riga["stato"]) for riga in righe],
            [("Diluente verniciatura", "ok"), ("Sgrassante senza SDS", "bad")],
        )

    def test_conferma_tutte_registra_presa_visione_e_riapre_cruscotto(self):
        self.anagrafica.mansione = self.nuova.nome
        self.anagrafica.save(update_fields=["mansione"])
        self.client.force_login(self.user)

        response = self.client.get(reverse("schede_sicurezza:sds_conferma_tutte"))

        self.assertRedirects(response, reverse("schede_sicurezza:sds_da_leggere"))
        self.assertTrue(
            PresaVisioneScheda.objects.filter(scheda=self.scheda_nuova, operatore=self.user).exists()
        )
        self.assertEqual(profilo_sds_utente(self.user).da_leggere, [])

    def test_conferma_tutte_e_idempotente_se_gia_confermate(self):
        self.client.force_login(self.user)
        self.client.get(reverse("schede_sicurezza:sds_conferma_tutte"))
        prima = PresaVisioneScheda.objects.count()

        response = self.client.get(reverse("schede_sicurezza:sds_conferma_tutte"))

        self.assertRedirects(response, reverse("schede_sicurezza:sds_da_leggere"))
        self.assertEqual(PresaVisioneScheda.objects.count(), prima)

    def test_report_evidenzia_prodotti_senza_mansione(self):
        orfano = ProdottoChimico.objects.create(nome="Prodotto da bonificare")
        self.assertIn(orfano, prodotti_senza_mansioni())

        self.anagrafica.mansione = self.nuova.nome
        self.anagrafica.save(update_fields=["mansione"])
        mansione_row = next(
            row for row in matrice_presa_visione() if row.mansione_id == self.nuova.pk
        )
        riga = mansione_row.righe[0]
        self.assertEqual(riga.totale_dipendenti, 1)
