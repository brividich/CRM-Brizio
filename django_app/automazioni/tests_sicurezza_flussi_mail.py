"""AU57 (diario preposto) e AU3 (segnalazioni di sicurezza): pacchetti, mail e approvazioni a cascata."""
from __future__ import annotations

import json
from pathlib import Path

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from automazioni.models import AutomationApproval
from automazioni.package_importer import analyze_package_dict, import_analyzed_package
from automazioni.services import process_approval_decision, run_rule

PACCHETTI = Path(__file__).resolve().parent / "packages"
TRE = {"rspp@costruzioninovicrom.it", "preposti@costruzioninovicrom.it", "rls@costruzioninovicrom.it"}


def _importa(nome):
    dati = json.loads((PACCHETTI / nome).read_text(encoding="utf-8"))
    analisi = analyze_package_dict(dati, filename=nome)
    risultato = import_analyzed_package(analisi, created_by=None, activate_created_rules=True)
    from automazioni.models import AutomationRule

    codici = [r.get("code") or r.get("final_code") for r in risultato.get("created_rules", [])]
    return AutomationRule.objects.get(code=codici[0]) if codici and codici[0] else AutomationRule.objects.latest("id")


def _destinatari(messaggio):
    return {a.lower() for a in messaggio.to}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.test",
                   DEFAULT_FROM_EMAIL="hub@example.test")
class DiarioPrepostoNuovaSegnalazioneTests(TestCase):
    def test_insert_manda_una_mail_ai_tre_indirizzi_con_descrizione_e_link(self):
        from diario_preposto.models import SegnalazionePreposto

        s = SegnalazionePreposto.objects.create(
            titolo="Scaffale instabile", data_segnalazione=timezone.now(), descrizione="Ripiano piegato in corsia B",
            preposto="Preposto Sintetico", chi_segnala="Operatore Sintetico",
        )
        regola = _importa("au57_diario_preposto_nuova_segnalazione.automation_package.json")
        # Payload come lo produce il trigger SQL: senza descrizione.
        run_rule(regola, {"id": s.pk, "codice_identificativo": s.codice_identificativo, "titolo": s.titolo,
                          "preposto": s.preposto, "chi_segnala": s.chi_segnala,
                          "data_segnalazione": s.data_segnalazione.isoformat(), "creato_da_id": None})
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(_destinatari(m), TRE)
        corpo = m.body
        self.assertIn("Ripiano piegato in corsia B", corpo)
        self.assertIn(f"https://hub.example.test/diario-preposto/{s.pk}/", corpo)
        self.assertNotIn("{", corpo)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.test",
                   DEFAULT_FROM_EMAIL="hub@example.test")
class SegnalazioneSicurezzaApprovazioniTests(TestCase):
    def setUp(self):
        from rilevazione_incidenti.models import RilevazioneIncidente

        self.inc = RilevazioneIncidente.objects.create(
            nominativo="Dipendente Sintetico", tipologia_scheda="Near Miss", reparto="Reparto Test",
            descrizione_avvenimento="Caduta di un attrezzo vicino al banco",
        )
        self.regola = _importa("au3_incidente_approvazione_rls_rspp.automation_package.json")
        # Payload come lo produce il trigger SQL: solo campi di stato.
        self.payload = {"id": self.inc.pk, "tipologia_scheda": "Near Miss", "reparto": "Reparto Test",
                        "data_segnalazione": None, "approvazione_rls": "", "chiusura_rspp": False,
                        "data_chiusura_rspp": None}

    def _approvazione(self, n):
        return AutomationApproval.objects.order_by("id")[n]

    def test_avviso_ai_tre_senza_dati_personali_poi_rls(self):
        run_rule(self.regola, self.payload)
        avviso, richiesta_rls = mail.outbox[0], mail.outbox[1]
        self.assertEqual(_destinatari(avviso), TRE)
        self.assertNotIn("Dipendente Sintetico", avviso.body)
        self.assertNotIn("Caduta di un attrezzo", avviso.body)
        self.assertIn(f"/rilevazione-incidenti/{self.inc.pk}/", avviso.body)
        self.assertEqual(_destinatari(richiesta_rls), {"rls@costruzioninovicrom.it"})
        testo_rls = richiesta_rls.body + "".join(str(c) for c, _t in getattr(richiesta_rls, "alternatives", []))
        self.assertIn("Dipendente Sintetico", testo_rls)
        self.assertIn("Caduta di un attrezzo", testo_rls)

    def test_rls_poi_rspp_approvano_e_la_segnalazione_si_chiude_con_le_date(self):
        run_rule(self.regola, self.payload)
        esito = process_approval_decision(str(self._approvazione(0).token), "approved", "rls@costruzioninovicrom.it")
        self.assertEqual(esito["actions_errors"], 0, esito)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.approvazione_rls, "Approvato")
        self.assertEqual(self.inc.data_approvazione_rls, timezone.localdate())
        self.assertFalse(self.inc.chiusura_rspp)
        self.assertEqual(_destinatari(mail.outbox[-1]), {"rspp@costruzioninovicrom.it"})

        esito = process_approval_decision(str(self._approvazione(1).token), "approved", "rspp@costruzioninovicrom.it")
        self.assertEqual(esito["actions_errors"], 0, esito)
        self.inc.refresh_from_db()
        self.assertTrue(self.inc.chiusura_rspp)
        self.assertEqual(self.inc.data_chiusura_rspp, timezone.localdate())

    def test_rls_non_approva_e_il_rspp_non_viene_coinvolto(self):
        run_rule(self.regola, self.payload)
        inviate = len(mail.outbox)
        process_approval_decision(str(self._approvazione(0).token), "rejected", "rls@costruzioninovicrom.it")
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.approvazione_rls, "Non approvato")
        self.assertFalse(self.inc.chiusura_rspp)
        self.assertEqual(AutomationApproval.objects.count(), 1)
        self.assertEqual(len(mail.outbox), inviate)


class StatoSegnalazioneTests(TestCase):
    def test_non_approvato_non_conta_come_approvato(self):
        from rilevazione_incidenti.views import _deriva_stato

        self.assertEqual(_deriva_stato({"Approvazione_RLS": "Non approvato"}), "APERTO")
        self.assertEqual(_deriva_stato({"Approvazione_RLS": "APPROVATO"}), "APPROVATO")
        self.assertEqual(_deriva_stato({"Approvazione_RLS": "Approvato", "Chiusura_RSPP": True}), "CHIUSO")
