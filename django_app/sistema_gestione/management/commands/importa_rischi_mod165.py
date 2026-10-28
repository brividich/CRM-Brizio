"""Importa l'analisi del rischio del MOD.165 in una revisione della SoA.

Esempio: manage.py importa_rischi_mod165 "<percorso PDF MOD.165>" --numero 4 [--apply] [--sostituisci]

Legge «Threat Risk», «Threats vs Controls», «Threat Monitoring» e «OT Treatment Plan»; senza --apply
mostra solo il riepilogo e il confronto fra il residuo del PDF e quello ricalcolato dalla SoA.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sistema_gestione.models import ControlloIso27002, RischioMinaccia, ScenarioRischioOT, SoaRevisione
from sistema_gestione.services.mod165_import import Mod165FormatoNonRiconosciuto
from sistema_gestione.services.mod165_rischi_import import leggi_analisi_rischio
from sistema_gestione.services.rischio import residuo


class Command(BaseCommand):
    help = "Importa l'analisi del rischio (minacce, matrice controlli, scenari OT) dal PDF del MOD.165."

    def add_arguments(self, parser):
        parser.add_argument("pdf")
        parser.add_argument("--numero", type=int, required=True, help="Revisione della SoA (MOD.165) di destinazione.")
        parser.add_argument("--apply", action="store_true", help="Scrive nel database (senza: solo verifica).")
        parser.add_argument("--sostituisci", action="store_true",
                            help="Sostituisce un'analisi già presente (solo revisione in bozza).")

    def handle(self, *args, **options):
        revisione = SoaRevisione.objects.filter(numero=options["numero"]).first()
        if revisione is None:
            raise CommandError(f"La revisione {options['numero']} della SoA non esiste: importa prima la Control Matrix "
                               "con importa_soa_mod165.")
        try:
            analisi = leggi_analisi_rischio(options["pdf"])
        except (OSError, RuntimeError) as exc:
            raise CommandError(f"File non leggibile: {options['pdf']}") from exc
        except Mod165FormatoNonRiconosciuto as exc:
            raise CommandError(str(exc)) from exc

        voci = dict(revisione.voci.values_list("controllo__codice", "vulnerabilita"))
        controlli = {c.codice: c for c in ControlloIso27002.objects.all()}
        sconosciuti = sorted({c for m in analisi.minacce for c in m.controlli if c not in controlli})
        coerenti = diverse = 0
        for m in analisi.minacce:
            vuln = [voci[c] for c in m.controlli if c in voci]
            calcolato = residuo(m.rischio_inerente, max(vuln) if vuln else None)
            if m.residuo is None or calcolato is None:
                continue
            if calcolato == m.residuo:
                coerenti += 1
            else:
                diverse += 1
        self.stdout.write(
            f"Minacce: {len(analisi.minacce)} (con controlli: {sum(1 for m in analisi.minacce if m.controlli)}); "
            f"soglia: {analisi.soglia}; scenari OT: {len(analisi.scenari_ot)}; "
            f"vulnerabilità attese: {len(analisi.vulnerabilita_attese)}"
        )
        self.stdout.write(f"Residuo del PDF ricalcolato dalla SoA Rev.{revisione.numero}: {coerenti} uguali, {diverse} diversi.")
        if sconosciuti:
            self.stdout.write(self.style.WARNING(f"Controlli non nel catalogo: {', '.join(sconosciuti)}"))
        if diverse:
            self.stdout.write(self.style.WARNING(
                "Le differenze indicano che la SoA della revisione non è quella del PDF: verifica il numero di revisione."))
        if not options["apply"]:
            self.stdout.write(self.style.NOTICE("DRY-RUN: nessuna scrittura. Rilancia con --apply."))
            return
        if revisione.minacce.exists() or revisione.scenari_ot.exists():
            if not options["sostituisci"]:
                raise CommandError("La revisione ha già un'analisi del rischio: usa --sostituisci (solo in bozza).")
            if revisione.stato != SoaRevisione.STATO_BOZZA:
                raise CommandError("Si sostituisce l'analisi solo di una revisione in bozza.")
        with transaction.atomic():
            revisione.minacce.all().delete()
            revisione.scenari_ot.all().delete()
            if analisi.soglia:
                revisione.soglia_rischio = analisi.soglia
                revisione.origine = (revisione.origine or f"Import PDF: {Path(options['pdf']).name}")[:255]
                revisione.save(update_fields=["soglia_rischio", "origine", "updated_at"])
            for ordine, m in enumerate(analisi.minacce, start=1):
                riga = RischioMinaccia.objects.create(
                    revisione=revisione, ordine=ordine * 10, gruppo=m.gruppo[:100], agente=m.agente[:150],
                    minaccia=(m.minaccia or m.agente or "Minaccia")[:255], rischio_inerente=m.rischio_inerente,
                    residuo_registrato=m.residuo,
                )
                riga.controlli.set([controlli[c] for c in m.controlli if c in controlli])
            for s in analisi.scenari_ot:
                scadenza = None
                if s.scadenza:
                    try:
                        scadenza = datetime.strptime(s.scadenza, "%d/%m/%Y").date()
                    except ValueError:
                        scadenza = None
                scenario = ScenarioRischioOT.objects.create(
                    revisione=revisione, codice=s.codice[:20], scenario=s.scenario, minacce=s.minacce,
                    misure=s.misure, rischio_inerente=s.rischio_inerente,
                    vulnerabilita_attesa=s.vulnerabilita_attesa if s.vulnerabilita_attesa in range(5) else None,
                    azioni=s.azioni, opzione=s.opzione[:120], responsabile=s.responsabile[:150], scadenza=scadenza,
                    stato=s.stato[:80], riferimenti=s.riferimenti,
                )
                scenario.controlli.set([controlli[c] for c in s.controlli.split() if c in controlli])
            for codice, valore in analisi.vulnerabilita_attese.items():
                revisione.voci.filter(controllo__codice=codice, vulnerabilita_attesa__isnull=True).update(
                    vulnerabilita_attesa=valore)
        self.stdout.write(self.style.SUCCESS(
            f"Analisi del rischio importata nella SoA Rev.{revisione.numero}: {len(analisi.minacce)} minacce, "
            f"{len(analisi.scenari_ot)} scenari OT."
        ))
