"""MOD.128 MPQ (Mansionario Processi Qualificati) — F1 modelli.

Test del comportamento dei modelli additivi (models_mpq): anagrafica cliente/ente
qualificante, processo qualificato (con doppia scadenza e stato/dismissione),
abilitazione persona×processo (ruoli + unicità), certificazione individuale
(≥1 per abilitazione), storico append-only, riferimenti/codici multipli.

Nessun dato reale: tutti gli esempi sono fittizi (no PII del MOD.128 reale).
"""
from __future__ import annotations

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    DipendenteQualifica,
    MpqStorico,
    ProcessoQualificato,
    Reparto,
    RiferimentoProcesso,
    TipoQualifica,
)


class ClienteQualificanteTests(TestCase):
    def test_tipo_default_cliente(self):
        c = ClienteQualificante.objects.create(nome="Cliente Aerospace A")
        self.assertEqual(c.tipo, ClienteQualificante.TIPO_CLIENTE)

    def test_nome_unique(self):
        ClienteQualificante.objects.create(nome="Ente Duplicato")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ClienteQualificante.objects.create(nome="Ente Duplicato")

    def test_certificatore_self_fk(self):
        """Ente esterno con relativo organismo certificatore (self-FK)."""
        organismo = ClienteQualificante.objects.create(
            nome="Organismo Cert. X",
            tipo=ClienteQualificante.TIPO_ORGANISMO_CERTIFICAZIONE,
        )
        ente = ClienteQualificante.objects.create(
            nome="Ente Esterno Y",
            tipo=ClienteQualificante.TIPO_ENTE_ESTERNO,
            certificatore=organismo,
        )
        self.assertEqual(ente.certificatore, organismo)
        self.assertIn(ente, organismo.enti_certificati.all())


class ProcessoQualificatoScadenzaTests(TestCase):
    def setUp(self):
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")

    def test_stato_default_attivo(self):
        p = ProcessoQualificato.objects.create(nome="Processo X", cliente=self.cli)
        self.assertEqual(p.stato, ProcessoQualificato.STATO_ATTIVO)

    def test_scadenza_illimitata_none(self):
        p = ProcessoQualificato.objects.create(
            nome="Processo illimitato", cliente=self.cli,
            tipo_validita=ProcessoQualificato.VALIDITA_ILLIMITATA,
        )
        self.assertIsNone(p.scadenza_effettiva)

    def test_scadenza_periodo_calcolata(self):
        """Validità N mesi: scadenza calcolata da conseguimento + durata_mesi."""
        p = ProcessoQualificato.objects.create(
            nome="Processo 36 mesi", cliente=self.cli,
            tipo_validita=ProcessoQualificato.VALIDITA_PERIODO,
            data_conseguimento=date(2025, 6, 1), durata_mesi=36,
        )
        self.assertEqual(p.scadenza_effettiva, date(2028, 6, 1))

    def test_scadenza_data_esplicita(self):
        p = ProcessoQualificato.objects.create(
            nome="Processo data secca", cliente=self.cli,
            tipo_validita=ProcessoQualificato.VALIDITA_DATA,
            data_scadenza=date(2029, 4, 6),
        )
        self.assertEqual(p.scadenza_effettiva, date(2029, 4, 6))

    def test_dismissione_tracciata(self):
        """Processo non più rinnovato con motivo + riferimento (audit)."""
        p = ProcessoQualificato.objects.create(
            nome="Processo dismesso", cliente=self.cli,
            stato=ProcessoQualificato.STATO_NON_RINNOVATO,
            motivo_stato="Non più processo speciale",
            riferimento_stato="rif. comunicazione interna del gg.mm.aa",
        )
        self.assertEqual(p.stato, ProcessoQualificato.STATO_NON_RINNOVATO)
        self.assertTrue(p.riferimento_stato)

    def test_reparti_m2m(self):
        """DISTRIBUZIONE A REPARTO può essere multipla (es. Aggiustaggio + CND PT)."""
        rep1 = Reparto.objects.create(nome="Aggiustaggio")
        rep2 = Reparto.objects.create(nome="CND PT")
        p = ProcessoQualificato.objects.create(nome="Processo multireparto", cliente=self.cli)
        p.reparti.set([rep1, rep2])
        self.assertEqual(p.reparti.count(), 2)

    def test_clienti_addizionali_m2m(self):
        """Riconoscimento condiviso: un processo riconosciuto da più clienti/enti."""
        cli2 = ClienteQualificante.objects.create(nome="Cliente B")
        p = ProcessoQualificato.objects.create(nome="Processo condiviso", cliente=self.cli)
        p.clienti_addizionali.add(cli2)
        self.assertIn(cli2, p.clienti_addizionali.all())

    def test_ente_certificatore_fk(self):
        org = ClienteQualificante.objects.create(
            nome="Ente Accreditamento Z",
            tipo=ClienteQualificante.TIPO_ENTE_ACCREDITAMENTO,
        )
        p = ProcessoQualificato.objects.create(
            nome="Processo accreditato", cliente=self.cli, ente_certificatore=org,
        )
        self.assertEqual(p.ente_certificatore, org)

    def test_tipo_qualifica_fk_opzionale(self):
        tipo = TipoQualifica.objects.create(nome="Processo speciale PT")
        p = ProcessoQualificato.objects.create(
            nome="Processo con tipo", cliente=self.cli, tipo_qualifica=tipo,
        )
        self.assertEqual(p.tipo_qualifica, tipo)


class RiferimentoProcessoTests(TestCase):
    def test_codici_multipli_per_processo(self):
        cli = ClienteQualificante.objects.create(nome="Cliente A")
        proc = ProcessoQualificato.objects.create(nome="Processo codici", cliente=cli)
        RiferimentoProcesso.objects.create(processo=proc, codice="COP001")
        RiferimentoProcesso.objects.create(processo=proc, codice="MCG000")
        self.assertEqual(proc.riferimenti.count(), 2)


class AbilitazioneProcessoTests(TestCase):
    def setUp(self):
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")
        self.proc = ProcessoQualificato.objects.create(nome="Processo X", cliente=self.cli)

    def test_ruoli_default_solo_qualificato(self):
        a = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=11, processo=self.proc)
        self.assertTrue(a.is_qualificato)
        self.assertFalse(a.is_addetto)
        self.assertFalse(a.is_controllore)
        self.assertFalse(a.is_part145)

    def test_stato_default_attiva(self):
        a = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=12, processo=self.proc)
        self.assertEqual(a.stato, AbilitazioneProcesso.STATO_ATTIVA)

    def test_unique_persona_processo(self):
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=10, processo=self.proc)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AbilitazioneProcesso.objects.create(legacy_anagrafica_id=10, processo=self.proc)

    def test_stessa_persona_processi_diversi(self):
        proc2 = ProcessoQualificato.objects.create(nome="Processo Y", cliente=self.cli)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=10, processo=self.proc)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=10, processo=proc2)
        self.assertEqual(
            AbilitazioneProcesso.objects.filter(legacy_anagrafica_id=10).count(), 2
        )

    def test_qualificatore_esterno(self):
        """Un qualificatore esterno (non a organico) è modellato con
        ``nominativo_esterno`` e ``legacy_anagrafica_id=0`` (nessun dipendente)."""
        a = AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=0, processo=self.proc,
            nominativo_esterno="Cognome Esterno", is_controllore=True,
        )
        self.assertTrue(a.is_esterno)
        self.assertEqual(a.nominativo_esterno, "Cognome Esterno")

    def test_due_esterni_stesso_processo(self):
        """Due esterni diversi sullo stesso processo non collidono (unicità
        include il nominativo esterno, SQL-Server-safe senza NULL)."""
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=0, processo=self.proc, nominativo_esterno="Esterno A")
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=0, processo=self.proc, nominativo_esterno="Esterno B")
        self.assertEqual(self.proc.abilitazioni.filter(legacy_anagrafica_id=0).count(), 2)

    def test_interno_non_esterno(self):
        a = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=99, processo=self.proc)
        self.assertFalse(a.is_esterno)

    def test_link_dipendente_qualifica_opzionale(self):
        tipo = TipoQualifica.objects.create(nome="PT Level 2")
        dq = DipendenteQualifica.objects.create(legacy_anagrafica_id=13, tipo=tipo)
        a = AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=13, processo=self.proc, dipendente_qualifica=dq,
        )
        self.assertEqual(a.dipendente_qualifica, dq)


class CertificazioneIndividualeTests(TestCase):
    def setUp(self):
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")
        self.proc = ProcessoQualificato.objects.create(nome="Processo X", cliente=self.cli)
        self.ab = AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=20, processo=self.proc
        )

    def test_multiple_certs_per_abilitazione(self):
        """Una persona → più certificati con schemi e scadenze diverse."""
        CertificazioneIndividuale.objects.create(
            abilitazione=self.ab, schema="ITA", numero="AAA",
            data_scadenza=date(2029, 10, 31),
        )
        CertificazioneIndividuale.objects.create(
            abilitazione=self.ab, schema="ASNT", numero="BBB",
            data_scadenza=date(2030, 1, 31),
        )
        self.assertEqual(self.ab.certificazioni.count(), 2)

    def test_ente_certificatore_opzionale(self):
        org = ClienteQualificante.objects.create(
            nome="Organismo ITA",
            tipo=ClienteQualificante.TIPO_ORGANISMO_CERTIFICAZIONE,
        )
        c = CertificazioneIndividuale.objects.create(
            abilitazione=self.ab, schema="ITA", ente_certificatore=org,
        )
        self.assertEqual(c.ente_certificatore, org)


class MpqStoricoTests(TestCase):
    def setUp(self):
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")
        self.proc = ProcessoQualificato.objects.create(nome="Processo X", cliente=self.cli)

    def test_registrato_il_auto(self):
        s = MpqStorico.objects.create(processo=self.proc, evento="Creazione processo")
        self.assertIsNotNone(s.registrato_il)

    def test_origine_default_manuale(self):
        s = MpqStorico.objects.create(processo=self.proc, evento="x")
        self.assertEqual(s.origine, MpqStorico.Origine.MANUALE)


class AdminRegistrationTests(TestCase):
    def test_models_registered_in_admin(self):
        from django.contrib import admin
        for model in (
            ClienteQualificante, ProcessoQualificato,
            AbilitazioneProcesso, CertificazioneIndividuale,
        ):
            self.assertIn(model, admin.site._registry)
