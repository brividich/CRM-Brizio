"""Impostazioni KICK-OFF: Modelli ODG, Registro FAI e Registro modifiche (10/11/2026)."""
from __future__ import annotations

from django.urls import reverse

from core.models import AuditLog

from .models import FaiGruppo, FaiOpzione, MeetingAgendaTemplate, TaskImpostazioni
from .tests_programmi import ProgrammiBase
from .views.settings import livello_audit


class ImpostazioniSchedeTests(ProgrammiBase):
    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.url = reverse("tasks:impostazioni")

    # ── Registro modifiche ────────────────────────────────────────────
    def test_livelli_del_registro(self):
        self.assertEqual(livello_audit("kickoff_project_delete"), "critico")
        self.assertEqual(livello_audit("ruoli_aggiornati"), "critico")
        self.assertEqual(livello_audit("reminder_forzati"), "critico")
        self.assertEqual(livello_audit("kickoff_meeting_create"), "importante")
        self.assertEqual(livello_audit("kickoff_sala_verifica"), "routine")
        self.assertEqual(livello_audit("auto_delete"), "routine")

    def test_registro_viste_ricerca_e_filtri(self):
        AuditLog.objects.filter(modulo="tasks").delete()  # voci scritte dalla preparazione del test
        AuditLog.objects.create(utente_display="mario", azione="kickoff_project_delete", modulo="tasks", dettaglio={"nome": "Flangia X"})
        AuditLog.objects.create(utente_display="anna", azione="kickoff_meeting_create", modulo="tasks", dettaglio={"meeting_numero": 3})
        AuditLog.objects.create(utente_display="anna", azione="kickoff_sala_verifica", modulo="tasks", dettaglio={"sala": "Blu"})
        AuditLog.objects.create(utente_display="anna", azione="altro", modulo="soc", dettaglio={})

        miei = {"kickoff_project_delete", "kickoff_meeting_create", "kickoff_sala_verifica"}

        def azioni(risposta):
            # Il portale scrive altre voci «tasks» durante la richiesta: si guardano solo quelle del test.
            return sorted(e.azione for e in risposta.context["audit_entries"] if e.azione in miei)

        essenziali = self.client.get(self.url + "?tab=log")
        self.assertEqual(essenziali.context["log_vista"], "essenziali")
        self.assertEqual(azioni(essenziali), ["kickoff_meeting_create", "kickoff_project_delete"])
        self.assertContains(essenziali, "Kickoff eliminato")
        self.assertContains(essenziali, "Flangia X")

        critico = self.client.get(self.url + "?tab=log&vista=critico")
        self.assertEqual(azioni(critico), ["kickoff_project_delete"])

        tutto = self.client.get(self.url + "?tab=log&vista=tutto")
        self.assertEqual(azioni(tutto), sorted(miei))

        ricerca = self.client.get(self.url + "?tab=log&vista=tutto&q=blu")
        self.assertEqual(azioni(ricerca), ["kickoff_sala_verifica"])

        per_utente = self.client.get(self.url + "?tab=log&vista=tutto&utente=mario")
        self.assertEqual(azioni(per_utente), ["kickoff_project_delete"])

        per_azione = self.client.get(self.url + "?tab=log&vista=tutto&azione=kickoff_meeting_create")
        self.assertEqual(azioni(per_azione), ["kickoff_meeting_create"])
        self.assertContains(per_azione, "Azzera")

    # ── Modelli ODG ───────────────────────────────────────────────────
    def test_modelli_duplica_e_salva_in_pagina(self):
        m = MeetingAgendaTemplate.objects.create(nome="Settimanale", items=[{"titolo": "Stato", "nota": "", "durata_minuti": 15}])
        pagina = self.client.get(self.url + "?tab=modelli")
        self.assertContains(pagina, "1 punto")
        self.assertContains(pagina, "15 min")
        self.assertContains(pagina, 'data-tpl-anteprima')

        self.client.post(self.url, {"tab": "modelli", "tpl_action": "template_duplicate", "template_id": m.pk})
        copia = MeetingAgendaTemplate.objects.get(nome="Settimanale (copia)")
        self.assertFalse(copia.is_active)
        self.assertEqual(copia.items, m.items)

        risposta = self.client.post(
            self.url,
            {"tab": "modelli", "tpl_action": "template_update", "template_id": m.pk, "nome": "Settimanale 2",
             "items_text": "Stato | 10\nRischi", "is_active": "on", "order_index": "5"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(risposta.status_code, 200)
        self.assertTrue(risposta.json()["ok"])
        m.refresh_from_db()
        self.assertEqual((m.nome, len(m.items)), ("Settimanale 2", 2))

        errore = self.client.post(
            self.url, {"tab": "modelli", "tpl_action": "template_update", "template_id": m.pk, "nome": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(errore.status_code, 400)
        self.assertIn("obbligatorio", errore.json()["messaggi"][-1]["testo"])

    # ── Registro FAI ──────────────────────────────────────────────────
    def test_fai_sezioni_e_salvataggio_in_riga(self):
        pagina = self.client.get(self.url + "?tab=fai")
        self.assertContains(pagina, 'data-fai-sezione="causale"')
        self.assertContains(pagina, "data-fai-cerca")

        opzione = FaiOpzione.objects.filter(gruppo=FaiGruppo.STATO).first()
        if opzione is None:
            opzione = FaiOpzione.objects.create(gruppo=FaiGruppo.STATO, etichetta="Aperto", attiva=True)
        risposta = self.client.post(
            self.url,
            {"tab": "fai", "fai_action": "aggiorna", "opzione_id": opzione.pk, "gruppo": opzione.gruppo,
             "etichetta": "Aperto rinominato", "fase": opzione.fase, "attiva": "on", "ordine": "7"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(risposta.status_code, 200, risposta.content)
        opzione.refresh_from_db()
        self.assertEqual((opzione.etichetta, opzione.ordine), ("Aperto rinominato", 7))

        soglie = self.client.post(
            self.url, {"tab": "fai", "fai_action": "soglie", "fai_mesi_verifica": "12", "fai_mesi_ripetizione": "36"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(soglie.status_code, 200)
        cfg = TaskImpostazioni.get_singleton()
        self.assertEqual((cfg.fai_mesi_verifica, cfg.fai_mesi_ripetizione), (12, 36))
