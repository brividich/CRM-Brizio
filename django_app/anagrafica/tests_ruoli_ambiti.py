"""Ambiti dei ruoli: più organigrammi che si sovrappongono, non si sostituiscono.

Una persona è insieme *Operatore CNC* nell'assetto produttivo e *Preposto*
nell'organigramma della sicurezza ISO 45001. Prima degli ambiti l'ultimo ruolo
assegnato poteva prendere il posto dell'altro nel campo «Ruolo aziendale» della
scheda; qui si verifica che non succeda più: **solo i ruoli dell'ambito della
scheda** toccano quel campo, gli altri si aggiungono e basta.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    AmbitoRuolo,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    RuoloOperativo,
)
from .services.ruoli_sync import dopo_assegnazione, dopo_rimozione, ruolo_principale
from .tests import _ensure_anagrafica_table

User = get_user_model()


class AmbitoModelloTests(TestCase):
    """Le regole che l'ambito porta con sé, prima di qualsiasi interfaccia."""

    def test_un_solo_ambito_alimenta_la_scheda(self):
        primo = AmbitoRuolo.objects.create(nome="Produttivo TEST", alimenta_scheda=True)
        secondo = AmbitoRuolo.objects.create(nome="Esecutivo TEST", alimenta_scheda=True)
        primo.refresh_from_db()
        self.assertFalse(primo.alimenta_scheda)
        self.assertTrue(AmbitoRuolo.objects.get(pk=secondo.pk).alimenta_scheda)

    def test_ruolo_senza_ambito_alimenta_il_principale(self):
        """Comportamento storico: prima della classificazione erano tutti così."""
        ruolo = RuoloOperativo.objects.create(nome="Capocommessa")
        self.assertTrue(ruolo.alimenta_ruolo_principale)
        self.assertEqual(ruolo.ambito_label, "Non classificato")

    def test_ruolo_di_ambito_non_scheda_non_alimenta(self):
        sgsl = AmbitoRuolo.objects.create(nome="SGSL TEST")
        ruolo = RuoloOperativo.objects.create(nome="Preposto", ambito=sgsl)
        self.assertFalse(ruolo.alimenta_ruolo_principale)
        self.assertEqual(ruolo.ambito_label, "SGSL TEST")

    def test_ruolo_dell_ambito_scheda_alimenta(self):
        produttivo = AmbitoRuolo.objects.create(nome="Assetto TEST", alimenta_scheda=True)
        ruolo = RuoloOperativo.objects.create(nome="Operatore CNC", ambito=produttivo)
        self.assertTrue(ruolo.alimenta_ruolo_principale)

    def test_la_migration_semina_gli_ambiti_di_partenza(self):
        """Produttivo, esecutivo, 45001, 27001: uno solo alimenta la scheda."""
        nomi = set(AmbitoRuolo.objects.values_list("nome", flat=True))
        self.assertIn("Produttivo", nomi)
        self.assertIn("Sicurezza ISO 45001", nomi)
        self.assertIn("Sicurezza informazioni ISO 27001", nomi)
        self.assertEqual(AmbitoRuolo.objects.filter(alimenta_scheda=True).count(), 1)


class SincronizzazionePerAmbitoTests(TestCase):
    """Il ruolo principale è una faccenda del solo ambito della scheda."""

    def setUp(self):
        AmbitoRuolo.objects.all().delete()
        self.produttivo = AmbitoRuolo.objects.create(
            nome="Produttivo", alimenta_scheda=True, ordine=10
        )
        self.sgsl = AmbitoRuolo.objects.create(nome="Sicurezza ISO 45001", ordine=30)
        self.operatore = RuoloOperativo.objects.create(
            nome="Operatore CNC", ambito=self.produttivo
        )
        self.preposto = RuoloOperativo.objects.create(nome="Preposto", ambito=self.sgsl)

    def test_ruolo_45001_non_diventa_principale_neanche_da_solo(self):
        creato = dopo_assegnazione(4001, self.preposto)
        self.assertFalse(creato)
        self.assertEqual(ruolo_principale(4001), "")

    def test_ruolo_produttivo_diventa_principale(self):
        self.assertTrue(dopo_assegnazione(4002, self.operatore))
        self.assertEqual(ruolo_principale(4002), "Operatore CNC")

    def test_il_ruolo_45001_non_scalza_il_principale_produttivo(self):
        dopo_assegnazione(4003, self.operatore)
        dopo_assegnazione(4003, self.preposto)
        self.assertEqual(ruolo_principale(4003), "Operatore CNC")

    def test_togliere_il_principale_non_promuove_un_ruolo_45001(self):
        """Il campo si svuota: un ruolo della sicurezza non è un ruolo aziendale."""
        dopo_assegnazione(4004, self.operatore)
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=4004, ruolo=self.preposto
        )
        nuovo = dopo_rimozione(4004, "Operatore CNC")
        self.assertEqual(nuovo, "")
        self.assertEqual(ruolo_principale(4004), "")

    def test_togliere_il_principale_promuove_un_altro_ruolo_produttivo(self):
        attrezzista = RuoloOperativo.objects.create(
            nome="Attrezzista", ambito=self.produttivo
        )
        dopo_assegnazione(4005, self.operatore)
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=4005, ruolo=attrezzista
        )
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=4005, ruolo=self.preposto
        )
        self.assertEqual(dopo_rimozione(4005, "Operatore CNC"), "Attrezzista")

    def test_togliere_un_ruolo_45001_non_tocca_il_principale(self):
        dopo_assegnazione(4006, self.operatore)
        self.assertEqual(dopo_rimozione(4006, "Preposto"), "Operatore CNC")
        self.assertEqual(ruolo_principale(4006), "Operatore CNC")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AmbitiInterfacciaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="ambiti_admin", email="ambiti_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        AmbitoRuolo.objects.all().delete()
        self.produttivo = AmbitoRuolo.objects.create(
            nome="Produttivo", alimenta_scheda=True, ordine=10
        )
        self.sgsl = AmbitoRuolo.objects.create(nome="Sicurezza ISO 45001", ordine=30)
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti")
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ["m.multiruolo", "Marta", "Multiruolo", "CNC", "Operatore", 1],
            )
            cur.execute("SELECT id FROM anagrafica_dipendenti")
            self.legacy_id = int(cur.fetchone()[0])

    # -- catalogo --------------------------------------------------------------

    def test_catalogo_espone_ambiti_e_conteggi(self):
        RuoloOperativo.objects.create(nome="Operatore CNC", ambito=self.produttivo)
        RuoloOperativo.objects.create(nome="Non classificato storico")
        resp = self.client.get(reverse("anagrafica:ruoli_operativi_list"))
        self.assertEqual(resp.status_code, 200)
        conteggi = {a.nome: a.n_ruoli for a in resp.context["ambiti"]}
        self.assertEqual(conteggi["Produttivo"], 1)
        self.assertEqual(conteggi["Sicurezza ISO 45001"], 0)
        self.assertEqual(resp.context["n_senza_ambito"], 1)

    def test_creazione_ruolo_con_ambito(self):
        self.client.post(
            reverse("anagrafica:ruolo_operativo_create"),
            {"nome": "RSPP", "ambito": str(self.sgsl.pk)},
        )
        self.assertEqual(RuoloOperativo.objects.get(nome="RSPP").ambito_id, self.sgsl.pk)

    def test_modifica_sposta_il_ruolo_di_ambito(self):
        ruolo = RuoloOperativo.objects.create(nome="Preposto", ambito=self.produttivo)
        self.client.post(
            reverse("anagrafica:ruolo_operativo_edit", args=[ruolo.pk]),
            {"nome": "Preposto", "ambito": str(self.sgsl.pk), "is_active": "1"},
        )
        ruolo.refresh_from_db()
        self.assertEqual(ruolo.ambito_id, self.sgsl.pk)

    # -- CRUD ambiti -----------------------------------------------------------

    def test_creazione_ambito(self):
        self.client.post(
            reverse("anagrafica:ambito_ruolo_create"),
            {"nome": "Ambiente ISO 14001", "icona": "🌿", "ordine": "50"},
        )
        self.assertTrue(AmbitoRuolo.objects.filter(nome="Ambiente ISO 14001").exists())

    def test_ambito_con_ruoli_non_si_elimina(self):
        RuoloOperativo.objects.create(nome="Preposto", ambito=self.sgsl)
        self.client.post(reverse("anagrafica:ambito_ruolo_delete", args=[self.sgsl.pk]))
        self.assertTrue(AmbitoRuolo.objects.filter(pk=self.sgsl.pk).exists())

    def test_ambito_della_scheda_non_si_elimina(self):
        self.client.post(
            reverse("anagrafica:ambito_ruolo_delete", args=[self.produttivo.pk])
        )
        self.assertTrue(AmbitoRuolo.objects.filter(pk=self.produttivo.pk).exists())

    def test_ambito_vuoto_si_elimina(self):
        self.client.post(reverse("anagrafica:ambito_ruolo_delete", args=[self.sgsl.pk]))
        self.assertFalse(AmbitoRuolo.objects.filter(pk=self.sgsl.pk).exists())

    def test_spostare_la_stella_su_un_altro_ambito(self):
        self.client.post(
            reverse("anagrafica:ambito_ruolo_edit", args=[self.sgsl.pk]),
            {"nome": "Sicurezza ISO 45001", "alimenta_scheda": "1", "is_active": "1"},
        )
        self.produttivo.refresh_from_db()
        self.sgsl.refresh_from_db()
        self.assertTrue(self.sgsl.alimenta_scheda)
        self.assertFalse(self.produttivo.alimenta_scheda)

    def test_togliere_la_stella_senza_darla_a_nessuno_non_lascia_la_scheda_orfana(self):
        self.client.post(
            reverse("anagrafica:ambito_ruolo_edit", args=[self.produttivo.pk]),
            {"nome": "Produttivo", "is_active": "1"},
        )
        self.produttivo.refresh_from_db()
        self.assertTrue(self.produttivo.alimenta_scheda)

    # -- scheda dipendente -----------------------------------------------------

    def test_assegnare_un_ruolo_45001_non_scrive_il_ruolo_aziendale(self):
        preposto = RuoloOperativo.objects.create(nome="Preposto", ambito=self.sgsl)
        self.client.post(
            reverse("anagrafica:dipendente_ruolo_assegna", args=[self.legacy_id]),
            {"ruolo_id": str(preposto.pk)},
        )
        self.assertTrue(
            DipendenteRuoloOperativo.objects.filter(
                legacy_anagrafica_id=self.legacy_id, ruolo=preposto
            ).exists()
        )
        az = DipendenteAnagraficaAziendale.objects.filter(
            legacy_anagrafica_id=self.legacy_id
        ).first()
        self.assertEqual((az.ruolo_aziendale or "") if az else "", "")

    def test_la_scheda_raggruppa_i_ruoli_per_ambito(self):
        operatore = RuoloOperativo.objects.create(
            nome="Operatore CNC", ambito=self.produttivo
        )
        preposto = RuoloOperativo.objects.create(nome="Preposto", ambito=self.sgsl)
        for r in (operatore, preposto):
            DipendenteRuoloOperativo.objects.create(
                legacy_anagrafica_id=self.legacy_id, ruolo=r
            )
        resp = self.client.get(
            reverse("anagrafica:dipendente_detail", args=[self.legacy_id])
        )
        gruppi = resp.context["ruoli_per_ambito"]
        self.assertEqual(
            [g["ambito"].nome for g in gruppi],
            ["Produttivo", "Sicurezza ISO 45001"],
        )
        self.assertEqual(len(gruppi[0]["elementi"]), 1)


class OrganigrammaPerAmbitoTests(TestCase):
    """Ogni ambito disegna il proprio organigramma."""

    def setUp(self):
        AmbitoRuolo.objects.all().delete()
        RuoloOperativo.objects.all().delete()
        self.produttivo = AmbitoRuolo.objects.create(
            nome="Produttivo", alimenta_scheda=True, ordine=10
        )
        self.sgsl = AmbitoRuolo.objects.create(nome="Sicurezza ISO 45001", ordine=30)
        self.direttore = RuoloOperativo.objects.create(
            nome="Direttore di produzione", ambito=self.produttivo
        )
        self.operatore = RuoloOperativo.objects.create(
            nome="Operatore CNC", ambito=self.produttivo, riporta_a=self.direttore
        )
        self.datore = RuoloOperativo.objects.create(
            nome="Datore di lavoro", ambito=self.sgsl
        )
        # Riporta a un ruolo di un altro ambito: nell'organigramma 45001 deve
        # comunque comparire, come radice.
        self.preposto = RuoloOperativo.objects.create(
            nome="Preposto", ambito=self.sgsl, riporta_a=self.direttore
        )

    def _nomi(self, albero):
        nomi = []
        for nodo in albero:
            nomi.append(nodo["ruolo"].nome)
            nomi.extend(self._nomi(nodo["figli"]))
        return nomi

    def test_senza_filtro_l_albero_contiene_tutto(self):
        from .services.organigramma_albero import build_ruolo_albero

        nomi = self._nomi(build_ruolo_albero())
        self.assertIn("Operatore CNC", nomi)
        self.assertIn("Preposto", nomi)

    def test_filtro_su_un_ambito_lascia_fuori_gli_altri(self):
        from .services.organigramma_albero import build_ruolo_albero

        nomi = self._nomi(build_ruolo_albero(self.sgsl.pk))
        self.assertIn("Datore di lavoro", nomi)
        self.assertIn("Preposto", nomi)
        self.assertNotIn("Operatore CNC", nomi)

    def test_il_ruolo_col_capo_fuori_ambito_diventa_radice(self):
        from .services.organigramma_albero import build_ruolo_albero

        radici = [n["ruolo"].nome for n in build_ruolo_albero(self.sgsl.pk)]
        self.assertIn("Preposto", radici)

    def test_filtro_senza_ambito(self):
        from .services.organigramma_albero import build_ruolo_albero

        RuoloOperativo.objects.create(nome="Ruolo storico")
        nomi = self._nomi(build_ruolo_albero(0))
        self.assertEqual(nomi, ["Ruolo storico"])
