"""Audit di sola lettura del dominio manutenzione (Fase 0 del refactoring stati).

Risponde ai punti 3, 4 e 6 della ricognizione:

3. **Debito storico** — ordini di lavoro chiusi che contengono ancora occorrenze
   non registrate. Chiudere un OdL non registra le manutenzioni che raccoglie
   (``assets/views.py`` ``workorder_close``): la scadenza dell'asset resta
   aperta. Qui si misura quanto e' grande il fenomeno.
4. **Uso reale** — ultimi 12 mesi: OdL aperti per mese, occorrenze registrate
   dentro/fuori un OdL, utenti distinti che hanno registrato.
6. **Concetti non definiti** — follow-up e conflitti di periodicita'.

Fase 0bis (ricognizione dei motori) aggiunge tre sezioni, tutte opzionali:

7. **Runtime dello scheduler** (``--runtime``) — Schedule django-q registrate a
   DB con ``next_run``/``last_run``, esito dell'ultima corsa, e versione del
   pacchetto installato da ``BUILD_INFO.json``. Risponde alla domanda "cosa gira
   davvero", che il codice da solo non puo' chiudere.
8. **Sorgente delle occorrenze** (``--sorgenti``) — conteggi separati per
   ``MaintenanceOccurrence.source``: quale motore ha prodotto cosa.
9. **Fonti di scadenza parallele** (``--fonti-parallele``) — quanti asset hanno
   una scadenza attiva in piu' di una fonte contemporaneamente.

Vincoli rispettati, per costruzione:

- **Nessuna scrittura.** Solo ``values()``/``annotate()``/``aggregate()`` e
  ``build_plan_resolutions`` (che non scrive). Nessun ``save``, ``create``,
  ``update``, ``delete``, nessun invio mail, nessun file prodotto.
- **Aggregazione server-side.** I conteggi per mese e per stato sono
  ``GROUP BY`` in SQL, non cicli Python su queryset interi.
- **Niente N+1.** Le righe di dettaglio arrivano da una sola query con i join
  gia' risolti (``values()`` sulle colonne dei modelli correlati); l'unica
  eccezione dichiarata sono i piani per OdL, risolti con una seconda query
  aggregata e ricuciti in memoria.
- **Query stampate prima dell'esecuzione**, e con ``--explain`` stampate soltanto.

Uso::

    python manage.py manut_audit                 # stampa le query, poi i risultati
    python manage.py manut_audit --explain       # stampa solo le query, non tocca il DB
    python manage.py manut_audit --months 24     # finestra diversa per il punto 4
    python manage.py manut_audit --limit 50      # righe di dettaglio del punto 3

I conteggi valgono per il database su cui il comando gira: eseguirlo in
sviluppo produce numeri di sviluppo, non di produzione.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Max, Min, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    MaintenanceOccurrence,
    PeriodicVerification,
    WorkMachine,
    WorkOrder,
    WorkOrderLog,
)

SEPARATOR = "=" * 78
RULE = "-" * 78


def _sql(queryset) -> str:
    """SQL della query, per stamparla prima di eseguirla.

    ``str(qs.query)`` non e' l'SQL definitivo inviato al driver (i parametri sono
    interpolati in modo approssimativo), ma mostra tabelle, join, filtri e
    ``GROUP BY``: basta a verificare che l'aggregazione sia server-side.
    """
    try:
        return str(queryset.query)
    except Exception as exc:  # pragma: no cover - dipende dal backend
        return f"<SQL non rappresentabile: {exc}>"


class Command(BaseCommand):
    help = "Audit di sola lettura del dominio manutenzione: debito storico, uso reale, follow-up e conflitti."

    def add_arguments(self, parser):
        parser.add_argument(
            "--explain",
            action="store_true",
            help="Stampa le query senza eseguirle. Non apre nessuna transazione.",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Ampiezza della finestra del punto 4, in mesi (default 12).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Righe di dettaglio stampate per il punto 3 (default 100). 0 = tutte.",
        )
        parser.add_argument(
            "--runtime",
            action="store_true",
            help="Punto 7: Schedule django-q registrate (next_run/last_run, esito ultima corsa) e versione installata.",
        )
        parser.add_argument(
            "--sorgenti",
            action="store_true",
            help="Punto 8: conteggio delle occorrenze per sorgente (quale motore le ha generate).",
        )
        parser.add_argument(
            "--fonti-parallele",
            action="store_true",
            help="Punto 9: asset con una scadenza attiva in piu' di una fonte contemporaneamente.",
        )
        parser.add_argument(
            "--skip-conflicts",
            action="store_true",
            help="Salta il calcolo dei conflitti di periodicita' (3 query su tutti gli asset attivi).",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.explain = bool(options["explain"])
        self.months = max(1, int(options["months"]))
        self.limit = max(0, int(options["limit"]))
        self.skip_conflicts = bool(options["skip_conflicts"])
        self.runtime = bool(options["runtime"])
        self.sorgenti = bool(options["sorgenti"])
        self.fonti_parallele = bool(options["fonti_parallele"])
        self.today: date = timezone.localdate()
        self.window_start = self.today - timedelta(days=self.months * 31)

        self._header()
        self._punto3_debito_storico()
        self._punto4_uso_reale()
        self._punto6_concetti()
        if self.runtime:
            self._punto7_runtime()
        if self.sorgenti:
            self._punto8_sorgenti()
        if self.fonti_parallele:
            self._punto9_fonti_parallele()
        self._footer()

    # ------------------------------------------------------------------
    def _header(self) -> None:
        self.stdout.write(SEPARATOR)
        self.stdout.write("AUDIT MANUTENZIONE - SOLA LETTURA")
        self.stdout.write(SEPARATOR)
        self.stdout.write(f"Data di riferimento : {self.today:%d-%m-%Y}")
        self.stdout.write(f"Finestra punto 4    : ultimi {self.months} mesi (da {self.window_start:%d-%m-%Y})")
        self.stdout.write(
            f"Modalita'           : {'EXPLAIN (nessuna query eseguita)' if self.explain else 'esecuzione'}"
        )
        self.stdout.write("")

    def _footer(self) -> None:
        self.stdout.write("")
        self.stdout.write(SEPARATOR)
        if self.explain:
            self.stdout.write("EXPLAIN: nessuna query e' stata eseguita, nessun dato letto.")
        else:
            self.stdout.write("Audit completato. Nessuna scrittura effettuata.")
        self.stdout.write(SEPARATOR)

    def _section(self, title: str) -> None:
        self.stdout.write("")
        self.stdout.write(SEPARATOR)
        self.stdout.write(title)
        self.stdout.write(SEPARATOR)

    def _show(self, label: str, queryset) -> None:
        """Stampa la query prima di eseguirla (o al posto di eseguirla)."""
        self.stdout.write("")
        self.stdout.write(f"[QUERY] {label}")
        self.stdout.write(RULE)
        self.stdout.write(_sql(queryset))
        self.stdout.write(RULE)

    # ==================================================================
    # PUNTO 3 - Debito storico
    # ==================================================================
    def _punto3_debito_storico(self) -> None:
        self._section(
            "PUNTO 3 - OdL CHIUSI CON OCCORRENZE NON REGISTRATE\n"
            "Definizione: WorkOrder.status in (DONE, CANCELED) con almeno una\n"
            "MaintenanceOccurrence collegata in status=OPEN."
        )

        chiusi = (WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED)

        # Una sola query: raggruppa gli OdL chiusi contando le occorrenze aperte.
        # Il filtro sull'aggregato sta in `filter(...)` dopo l'annotate, cioe' in
        # HAVING lato server: nessuna riga inutile viaggia fino a Python.
        aggregato = (
            WorkOrder.objects.filter(status__in=chiusi, occurrences__isnull=False)
            .values("id", "status", "closed_at", "asset__asset_tag", "asset__name", "is_massive")
            .annotate(
                aperte=Count("occurrences", filter=Q(occurrences__status=MaintenanceOccurrence.STATUS_OPEN)),
                totali=Count("occurrences"),
                scadenza_min=Min(
                    "occurrences__due_date",
                    filter=Q(occurrences__status=MaintenanceOccurrence.STATUS_OPEN),
                ),
                scadenza_max=Max(
                    "occurrences__due_date",
                    filter=Q(occurrences__status=MaintenanceOccurrence.STATUS_OPEN),
                ),
            )
            .filter(aperte__gt=0)
            .order_by("closed_at", "id")
        )
        self._show("punto 3 - OdL chiusi con occorrenze aperte (GROUP BY + HAVING)", aggregato)

        # Distribuzione per mese di chiusura, aggregata server-side.
        per_mese = (
            WorkOrder.objects.filter(
                status__in=chiusi,
                occurrences__status=MaintenanceOccurrence.STATUS_OPEN,
            )
            .annotate(mese=TruncMonth("closed_at"))
            .values("mese")
            .annotate(odl=Count("id", distinct=True), occorrenze=Count("occurrences"))
            .order_by("mese")
        )
        self._show("punto 3 - distribuzione per mese di chiusura (GROUP BY mese)", per_mese)

        if self.explain:
            return

        righe = list(aggregato)
        if not righe:
            self.stdout.write("")
            self.stdout.write("Nessun OdL chiuso con occorrenze non registrate.")
            return

        # I piani coinvolti: seconda query aggregata, ricucita in memoria sugli id
        # gia' noti. E' l'alternativa a un accesso per riga (N+1).
        wo_ids = [r["id"] for r in righe]
        piani_qs = (
            MaintenanceOccurrence.objects.filter(
                work_order_id__in=wo_ids, status=MaintenanceOccurrence.STATUS_OPEN
            )
            .values("work_order_id", "plan__label", "asset__asset_tag")
            .annotate(n=Count("id"))
            .order_by("work_order_id", "plan__label")
        )
        self._show("punto 3 - piani e asset delle occorrenze aperte (una query per tutti gli OdL)", piani_qs)

        piani_per_wo: dict[int, list[str]] = {}
        asset_per_wo: dict[int, set[str]] = {}
        for row in piani_qs:
            wid = row["work_order_id"]
            piani_per_wo.setdefault(wid, []).append(f"{row['plan__label']} x{row['n']}")
            asset_per_wo.setdefault(wid, set()).add(row["asset__asset_tag"] or "-")

        self.stdout.write("")
        self.stdout.write(f"TOTALE OdL chiusi con occorrenze non registrate : {len(righe)}")
        self.stdout.write(f"TOTALE occorrenze rimaste aperte                : {sum(r['aperte'] for r in righe)}")

        self.stdout.write("")
        self.stdout.write("DETTAGLIO")
        self.stdout.write(
            f"{'OdL':>7}  {'stato':<9} {'chiuso il':<12} {'aperte':>6} {'/tot':>5} "
            f"{'gg scoperto':>11}  asset capofila / piani"
        )
        self.stdout.write(RULE)
        mostrate = righe if self.limit == 0 else righe[: self.limit]
        for r in mostrate:
            chiusura = r["closed_at"]
            chiusura_d = timezone.localtime(chiusura).date() if chiusura else None
            # "Giorni di scoperto": da quando l'OdL risulta chiuso mentre la
            # manutenzione e' ancora dovuta. Senza closed_at non e' calcolabile.
            scoperto = (self.today - chiusura_d).days if chiusura_d else None
            capofila = r["asset__asset_tag"] or r["asset__name"] or "-"
            piani = "; ".join(piani_per_wo.get(r["id"], [])) or "-"
            altri = asset_per_wo.get(r["id"], set())
            asset_txt = capofila if len(altri) <= 1 else f"{capofila} (+{len(altri) - 1} asset)"
            self.stdout.write(
                f"{r['id']:>7}  {r['status']:<9} "
                f"{chiusura_d.strftime('%d-%m-%Y') if chiusura_d else 'n.d.':<12} "
                f"{r['aperte']:>6} {r['totali']:>5} "
                f"{(str(scoperto) if scoperto is not None else 'n.d.'):>11}  {asset_txt} / {piani}"
            )
        if self.limit and len(righe) > self.limit:
            self.stdout.write(f"... altre {len(righe) - self.limit} righe non stampate (--limit 0 per tutte).")

        self.stdout.write("")
        self.stdout.write("DISTRIBUZIONE PER MESE DI CHIUSURA")
        self.stdout.write(f"{'mese':<10} {'OdL':>6} {'occorrenze aperte':>18}")
        self.stdout.write(RULE)
        vuoto = True
        for row in per_mese:
            vuoto = False
            mese = row["mese"]
            etichetta = mese.strftime("%Y-%m") if mese else "senza data"
            self.stdout.write(f"{etichetta:<10} {row['odl']:>6} {row['occorrenze']:>18}")
        if vuoto:
            self.stdout.write("(nessuna riga)")

    # ==================================================================
    # PUNTO 4 - Uso reale
    # ==================================================================
    def _punto4_uso_reale(self) -> None:
        self._section(f"PUNTO 4 - USO REALE, ULTIMI {self.months} MESI")

        self.stdout.write("")
        self.stdout.write(
            "AVVERTENZA SULLA RICOSTRUIBILITA'\n"
            "  - WorkOrder NON ha un campo di creazione (ne' created_at ne' created_by:\n"
            "    assets/models.py, classe WorkOrder). 'OdL creati per mese' si approssima\n"
            "    con `opened_at`, che alcune registrazioni storiche retrodatano\n"
            "    deliberatamente (assets/views.py, _build_execution_workorder).\n"
            "  - 'Utenti distinti che hanno creato un OdL' NON e' ricostruibile dal DB.\n"
            "    Sotto se ne stampa una PROSSIMA: l'autore del log piu' vecchio dell'OdL\n"
            "    (WorkOrderLog.author), che esiste solo per gli OdL nati da un percorso\n"
            "    che scrive un log e che puo' essere NULL. Va letta come limite inferiore."
        )

        # --- OdL per mese (GROUP BY server-side) ---
        odl_per_mese = (
            WorkOrder.objects.filter(opened_at__date__gte=self.window_start)
            .annotate(mese=TruncMonth("opened_at"))
            .values("mese")
            .annotate(
                totali=Count("id"),
                massivi=Count("id", filter=Q(is_massive=True)),
                chiusi=Count("id", filter=Q(status=WorkOrder.STATUS_DONE)),
            )
            .order_by("mese")
        )
        self._show("punto 4 - OdL per mese di apertura", odl_per_mese)

        # --- Proxy autori: autore del log piu' vecchio per OdL ---
        autori_proxy = (
            WorkOrderLog.objects.filter(
                work_order__opened_at__date__gte=self.window_start,
                author__isnull=False,
            )
            .values("author_id")
            .annotate(odl=Count("work_order_id", distinct=True))
            .order_by("-odl")
        )
        self._show("punto 4 - PROSSIMA autori OdL (WorkOrderLog.author, non e' il creatore)", autori_proxy)

        # --- Occorrenze registrate: dentro o fuori un OdL ---
        registrate = (
            MaintenanceOccurrence.objects.filter(
                status=MaintenanceOccurrence.STATUS_DONE,
                completed_on__gte=self.window_start,
            )
            .values("source")
            .annotate(
                totali=Count("id"),
                con_odl=Count("id", filter=Q(work_order__isnull=False)),
                senza_odl=Count("id", filter=Q(work_order__isnull=True)),
                con_autore=Count("id", filter=Q(completed_by__isnull=False)),
            )
            .order_by("source")
        )
        self._show("punto 4 - occorrenze registrate, dentro/fuori un OdL, per origine", registrate)

        registrate_mese = (
            MaintenanceOccurrence.objects.filter(
                status=MaintenanceOccurrence.STATUS_DONE,
                completed_on__gte=self.window_start,
            )
            .annotate(mese=TruncMonth("completed_on"))
            .values("mese")
            .annotate(
                totali=Count("id"),
                con_odl=Count("id", filter=Q(work_order__isnull=False)),
                senza_odl=Count("id", filter=Q(work_order__isnull=True)),
            )
            .order_by("mese")
        )
        self._show("punto 4 - occorrenze registrate per mese", registrate_mese)

        registranti = (
            MaintenanceOccurrence.objects.filter(
                status=MaintenanceOccurrence.STATUS_DONE,
                completed_on__gte=self.window_start,
                completed_by__isnull=False,
            )
            .values("completed_by_id", "completed_by__username")
            .annotate(registrate=Count("id"))
            .order_by("-registrate")
        )
        self._show("punto 4 - utenti distinti che hanno registrato (completed_by)", registranti)

        if self.explain:
            return

        self.stdout.write("")
        self.stdout.write("ORDINI DI LAVORO PER MESE DI APERTURA (opened_at)")
        self.stdout.write(f"{'mese':<10} {'totali':>7} {'massivi':>8} {'chiusi':>7}")
        self.stdout.write(RULE)
        righe_odl = list(odl_per_mese)
        for row in righe_odl:
            mese = row["mese"]
            self.stdout.write(
                f"{(mese.strftime('%Y-%m') if mese else 'n.d.'):<10} "
                f"{row['totali']:>7} {row['massivi']:>8} {row['chiusi']:>7}"
            )
        if not righe_odl:
            self.stdout.write("(nessun OdL nella finestra)")
        self.stdout.write(f"{'TOTALE':<10} {sum(r['totali'] for r in righe_odl):>7}")

        righe_autori = list(autori_proxy)
        self.stdout.write("")
        self.stdout.write(
            f"UTENTI CHE HANNO SCRITTO ALMENO UN LOG SU UN OdL DELLA FINESTRA: {len(righe_autori)}"
        )
        self.stdout.write("  (PROSSIMA, non il numero di creatori: vedi avvertenza sopra)")

        self.stdout.write("")
        self.stdout.write("OCCORRENZE REGISTRATE, PER ORIGINE")
        self.stdout.write(f"{'origine':<12} {'totali':>7} {'con OdL':>8} {'senza OdL':>10} {'con autore':>11}")
        self.stdout.write(RULE)
        tot = con = senza = 0
        for row in registrate:
            tot += row["totali"]
            con += row["con_odl"]
            senza += row["senza_odl"]
            self.stdout.write(
                f"{row['source']:<12} {row['totali']:>7} {row['con_odl']:>8} "
                f"{row['senza_odl']:>10} {row['con_autore']:>11}"
            )
        self.stdout.write(RULE)
        self.stdout.write(f"{'TOTALE':<12} {tot:>7} {con:>8} {senza:>10}")

        self.stdout.write("")
        self.stdout.write("OCCORRENZE REGISTRATE PER MESE")
        self.stdout.write(f"{'mese':<10} {'totali':>7} {'con OdL':>8} {'senza OdL':>10}")
        self.stdout.write(RULE)
        vuoto = True
        for row in registrate_mese:
            vuoto = False
            mese = row["mese"]
            self.stdout.write(
                f"{(mese.strftime('%Y-%m') if mese else 'n.d.'):<10} "
                f"{row['totali']:>7} {row['con_odl']:>8} {row['senza_odl']:>10}"
            )
        if vuoto:
            self.stdout.write("(nessuna registrazione nella finestra)")

        righe_reg = list(registranti)
        self.stdout.write("")
        self.stdout.write(f"UTENTI DISTINTI CHE HANNO REGISTRATO: {len(righe_reg)}")
        for row in righe_reg[:20]:
            self.stdout.write(f"  {row['completed_by__username']:<30} {row['registrate']:>6}")


    # ==================================================================
    # PUNTO 7 - Runtime dello scheduler (Fase 0bis)
    # ==================================================================
    def _punto7_runtime(self) -> None:
        """Cosa e' registrato nello scheduler e cosa ha girato davvero.

        Il codice dice cosa *dovrebbe* girare; ``django_q.Schedule`` dice cosa e'
        registrato a DB; ``next_run`` e l'esito dell'ultimo Task dicono cosa ha
        girato davvero. Sono tre cose diverse: un deploy che non riesegue
        ``setup_q_schedules`` lascia a DB il job della release precedente, che resta
        schedulato con un ``func`` che il codice nuovo non definisce piu'.

        Un job assente a DB ha pero' due cause opposte: **perso** (mai registrato, ed
        e' un guasto) oppure **spento di proposito** dalla Centrale di comando
        (``monitoring.ScheduleControl``, che ``setup_q_schedules`` rispetta). Vengono
        stampati separatamente: un rapporto che grida al guasto davanti a una scelta
        deliberata smette di essere creduto proprio quando serve.
        """
        self._section("PUNTO 7 - RUNTIME DELLO SCHEDULER (cosa gira davvero)")

        self.stdout.write("")
        self.stdout.write("[FILE] BUILD_INFO.json (versione del pacchetto installato)")
        self.stdout.write(RULE)
        self.stdout.write("EXPLAIN: non letto." if self.explain else self._build_info())
        self.stdout.write(RULE)

        try:
            from django_q.models import Schedule
        except Exception as exc:  # pragma: no cover - dipende dall'installazione
            self.stdout.write(self.style.WARNING("django_q non disponibile: %s" % exc))
            return

        schedules = Schedule.objects.all().order_by("name")
        self._show("Schedule django-q registrate a DB", schedules)
        if self.explain:
            return

        rows = list(
            schedules.values(
                "name", "func", "schedule_type", "cron", "minutes",
                "repeats", "next_run", "task",
            )
        )
        if not rows:
            self.stdout.write(self.style.WARNING(
                "  Nessuno Schedule registrato: nessun job periodico girera'. "
                "Rimedio: manage.py setup_q_schedules"
            ))
            return

        self.stdout.write("  Schedule registrate: %d" % len(rows))
        self.stdout.write("")
        self.stdout.write(
            "  %-34s %-14s %-17s %-12s %s" % ("NOME", "CADENZA", "PROSSIMA CORSA", "ULTIMO ESITO", "FUNC")
        )
        self.stdout.write("  " + "-" * 116)

        esiti = self._task_outcomes([r["task"] for r in rows if r["task"]])

        orfani: list[str] = []
        for row in rows:
            cadenza = (
                "cron %s" % row["cron"] if row["schedule_type"] == "C"
                else "ogni %sm" % row["minutes"]
            )
            prossima = row["next_run"].strftime("%d-%m-%Y %H:%M") if row["next_run"] else "-"
            esito = esiti.get(row["task"], "-")
            self.stdout.write(
                "  %-34s %-14s %-17s %-12s %s"
                % (row["name"][:34], cadenza[:14], prossima, esito, row["func"])
            )
            if not self._func_importabile(row["func"]):
                orfani.append("%s -> %s" % (row["name"], row["func"]))

        if orfani:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(
                "  SCHEDULE ORFANE: il 'func' registrato non esiste nel codice installato."
            ))
            self.stdout.write(self.style.ERROR(
                "  Il cluster fallisce a ogni corsa, e il job che lo sostituisce non e' registrato."
            ))
            for voce in orfani:
                self.stdout.write(self.style.ERROR("    - %s" % voce))
            self.stdout.write(self.style.ERROR(
                "  Rimedio: manage.py setup_q_schedules  (rimuove i ritirati, registra i nuovi)"
            ))

        try:
            from automazioni.schedules import SCHEDULES, disabled_schedule_names

            attesi = {spec["name"] for spec in SCHEDULES}
            mancanti = attesi - {row["name"] for row in rows}
            # Un job assente a DB perche' disattivato dalla Centrale di comando NON e'
            # un guasto: e' una scelta durevole (monitoring.ScheduleControl), che
            # ``setup_q_schedules`` rispetta anche dopo un redeploy. Confonderlo con un
            # job perso rende il rapporto rumoroso proprio dove deve essere creduto.
            try:
                disattivati = set(disabled_schedule_names())
            except Exception:
                disattivati = set()

            spenti = sorted(mancanti & disattivati)
            persi = sorted(mancanti - disattivati)

            if spenti:
                self.stdout.write("")
                self.stdout.write(
                    "  DISATTIVATI dalla Centrale di comando (scelta deliberata, non un guasto): %d"
                    % len(spenti)
                )
                for name in spenti:
                    self.stdout.write("    - %s" % name)

            if persi:
                self.stdout.write("")
                self.stdout.write(self.style.ERROR(
                    "  NON REGISTRATE: %d job esistono nel codice, non sono disattivati "
                    "e non sono a DB - non girano." % len(persi)
                ))
                for name in persi:
                    self.stdout.write(self.style.ERROR("    - %s" % name))
                self.stdout.write(self.style.ERROR(
                    "  Rimedio: manage.py setup_q_schedules"
                ))
        except Exception as exc:  # pragma: no cover
            self.stdout.write(self.style.WARNING("  Confronto col codice non riuscito: %s" % exc))

    def _build_info(self) -> str:
        """Versione installata: il file sta nella radice del pacchetto, sopra django_app/."""
        import json
        from pathlib import Path

        from django.conf import settings

        base = Path(getattr(settings, "BASE_DIR", "."))
        for candidate in (base / "BUILD_INFO.json", base.parent / "BUILD_INFO.json"):
            if candidate.is_file():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception as exc:
                    return "%s: illeggibile (%s)" % (candidate, exc)
                return "\n".join([
                    str(candidate),
                    "  versione  : %s" % data.get("version"),
                    "  commit    : %s (%s)" % (data.get("commit_short"), data.get("branch")),
                    "  costruito : %s da %s" % (data.get("built_at"), data.get("built_by")),
                    "  dirty     : %s | delta vs branch: %s"
                    % (data.get("dirty"), data.get("delta_vs_export_branch")),
                ])
        return "BUILD_INFO.json non trovato (sviluppo, o pacchetto non tracciabile)."

    @staticmethod
    def _func_importabile(dotted: str) -> bool:
        """True se il ``func`` registrato e' ancora risolvibile nel codice installato."""
        import importlib

        try:
            module_path, _, attr = str(dotted or "").rpartition(".")
            if not module_path:
                return False
            return hasattr(importlib.import_module(module_path), attr)
        except Exception:
            return False

    @staticmethod
    def _task_outcomes(task_ids: list) -> dict:
        """Esito dell'ultima corsa, per id di Task django-q."""
        if not task_ids:
            return {}
        try:
            from django_q.models import Task

            return {
                row["id"]: ("Success" if row["success"] else "FAILURE")
                for row in Task.objects.filter(id__in=task_ids).values("id", "success")
            }
        except Exception:
            return {}

    # ==================================================================
    # PUNTO 8 - Sorgente delle occorrenze (Fase 0bis)
    # ==================================================================
    def _punto8_sorgenti(self) -> None:
        """Quale motore ha prodotto quali occorrenze.

        ``MaintenanceOccurrence.source`` e' indicizzato e valorizzato alla creazione
        da ogni percorso di scrittura: e' la traccia che rende i record attribuibili
        a posteriori, senza euristiche sulle date.
        """
        self._section("PUNTO 8 - SORGENTE DELLE OCCORRENZE (quale motore ha generato cosa)")

        per_sorgente = (
            MaintenanceOccurrence.objects.values("source", "status")
            .annotate(n=Count("id"), prima=Min("due_date"), ultima=Max("due_date"))
            .order_by("source", "status")
        )
        self._show("Occorrenze per sorgente e stato", per_sorgente)

        scadute = (
            MaintenanceOccurrence.objects.filter(
                status=MaintenanceOccurrence.STATUS_OPEN, due_date__lt=self.today
            )
            .values("source")
            .annotate(n=Count("id"), piu_vecchia=Min("due_date"))
            .order_by("source")
        )
        self._show("Occorrenze APERTE gia' scadute, per sorgente", scadute)
        if self.explain:
            return

        etichette = dict(MaintenanceOccurrence.SOURCE_CHOICES)
        righe = list(per_sorgente)
        if not righe:
            self.stdout.write("  Nessuna occorrenza a DB.")
            return

        self.stdout.write("")
        self.stdout.write("  %-32s %-12s %6s  %-10s %-10s" % ("SORGENTE", "STATO", "N", "DA", "A"))
        self.stdout.write("  " + "-" * 80)
        totale = 0
        for row in righe:
            totale += row["n"]
            self.stdout.write(
                "  %-32s %-12s %6d  %s %s"
                % (
                    etichette.get(row["source"], row["source"])[:32],
                    str(row["status"])[:12],
                    row["n"],
                    row["prima"].strftime("%d-%m-%Y") if row["prima"] else "-",
                    row["ultima"].strftime("%d-%m-%Y") if row["ultima"] else "-",
                )
            )
        self.stdout.write("  " + "-" * 80)
        self.stdout.write("  %-45s %6d" % ("TOTALE", totale))

        righe_scadute = list(scadute)
        if righe_scadute:
            self.stdout.write("")
            self.stdout.write("  Aperte e gia' scadute alla data di oggi (nate nel passato):")
            for row in righe_scadute:
                self.stdout.write(
                    "    %-32s %6d   la piu' vecchia: %s"
                    % (
                        etichette.get(row["source"], row["source"]),
                        row["n"],
                        row["piu_vecchia"].strftime("%d-%m-%Y") if row["piu_vecchia"] else "-",
                    )
                )

    # ==================================================================
    # PUNTO 9 - Fonti di scadenza parallele (Fase 0bis)
    # ==================================================================
    def _punto9_fonti_parallele(self) -> None:
        """Quanti asset hanno una scadenza attiva in piu' di una fonte.

        Quattro fonti indipendenti possono dire "questo asset scade": l'occorrenza
        del nuovo dominio, la verifica periodica, la scadenza amministrativa e la
        data denormalizzata sulla macchina. Nessuna delle quattro sa delle altre.
        """
        self._section("PUNTO 9 - FONTI DI SCADENZA PARALLELE (sovrapposizioni per asset)")

        occorrenze = MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_OPEN
        ).order_by().values_list("asset_id", flat=True)
        verifiche = PeriodicVerification.objects.filter(
            is_active=True, next_verification_date__isnull=False
        ).order_by().values_list("assets__id", flat=True)
        amministrative = AssetAdministrativeDeadline.objects.filter(
            is_active=True
        ).order_by().values_list("asset_id", flat=True)
        macchine = WorkMachine.objects.filter(
            next_maintenance_date__isnull=False
        ).order_by().values_list("asset_id", flat=True)

        self._show("Asset con occorrenza aperta", occorrenze)
        self._show("Asset con verifica periodica attiva", verifiche)
        self._show("Asset con scadenza amministrativa attiva", amministrative)
        self._show("Asset con next_maintenance_date valorizzata", macchine)
        if self.explain:
            return

        fonti = {
            "occorrenza aperta": {a for a in occorrenze if a},
            "verifica periodica": {a for a in verifiche if a},
            "scadenza amministrativa": {a for a in amministrative if a},
            "next_maintenance_date": {a for a in macchine if a},
        }

        self.stdout.write("")
        for nome, insieme in fonti.items():
            self.stdout.write("  %-28s asset distinti: %6d" % (nome, len(insieme)))

        conteggio: dict[int, list[str]] = {}
        for nome, insieme in fonti.items():
            for asset_id in insieme:
                conteggio.setdefault(asset_id, []).append(nome)

        sovrapposti = {a: f for a, f in conteggio.items() if len(f) > 1}
        self.stdout.write("")
        self.stdout.write(
            "  ASSET CON SCADENZA ATTIVA IN PIU' DI UNA FONTE: %d" % len(sovrapposti)
        )
        if not sovrapposti:
            return

        combinazioni: dict[tuple, int] = {}
        for elenco in sovrapposti.values():
            chiave = tuple(sorted(elenco))
            combinazioni[chiave] = combinazioni.get(chiave, 0) + 1
        self.stdout.write("")
        self.stdout.write("  Combinazioni osservate:")
        for combo, n in sorted(combinazioni.items(), key=lambda kv: -kv[1]):
            self.stdout.write("    %5dx  %s" % (n, " + ".join(combo)))

        limite = self.limit or len(sovrapposti)
        primi = list(sovrapposti)[:limite]
        etichette_asset = dict(
            Asset.objects.filter(pk__in=primi).values_list("pk", "asset_tag")
        )
        self.stdout.write("")
        self.stdout.write("  Dettaglio (primi %d):" % len(primi))
        for asset_id in primi:
            self.stdout.write(
                "    %-28s %s"
                % (
                    str(etichette_asset.get(asset_id) or asset_id)[:28],
                    ", ".join(sovrapposti[asset_id]),
                )
            )

    # ==================================================================
    # PUNTO 6 - Concetti non definiti
    # ==================================================================
    def _punto6_concetti(self) -> None:
        self._section("PUNTO 6 - FOLLOW-UP E CONFLITTI DI PERIODICITA'")

        self.stdout.write("")
        self.stdout.write(
            "FOLLOW-UP: e' un WorkOrder, non un modello a se'. Due sorgenti distinte:\n"
            "  (a) chiusura con esito 'Risolto temporaneamente' -> figlio con follow_up_of\n"
            "      valorizzato (assets/views.py, workorder_close);\n"
            "  (b) anomalia rilevata su una singola occorrenza -> figlio con\n"
            "      follow_up_occurrence valorizzato (assets/views_maintenance.py,\n"
            "      occurrence_followup_create).\n"
            "Non esiste un flag unico: un OdL e' un follow-up se ha almeno uno dei due."
        )

        follow_up = (
            WorkOrder.objects.filter(Q(follow_up_of__isnull=False) | Q(follow_up_occurrence__isnull=False))
            .values("status")
            .annotate(
                totali=Count("id"),
                da_esito=Count("id", filter=Q(follow_up_of__isnull=False)),
                da_occorrenza=Count("id", filter=Q(follow_up_occurrence__isnull=False)),
                da_checklist=Count("id", filter=Q(follow_up_checklist_item__isnull=False)),
            )
            .order_by("status")
        )
        self._show("punto 6 - follow-up per stato e per sorgente", follow_up)

        # OdL chiusi 'Risolto temporaneamente' con una data di verifica gia' passata
        # e nessun figlio: la verifica promessa non e' mai stata aperta.
        temp_scaduti = (
            WorkOrder.objects.filter(
                outcome=WorkOrder.OUTCOME_RESOLVED_TEMP,
                follow_up_date__lt=self.today,
            )
            # `values()` PRIMA di `annotate()`: altrimenti il GROUP BY include
            # ogni colonna di WorkOrder, e SQL Server non raggruppa su
            # nvarchar(max) (description, resolution, notes).
            .values("id", "asset__asset_tag", "follow_up_date")
            .annotate(figli=Count("follow_ups"))
            .filter(figli=0)
            .order_by("follow_up_date")
        )
        self._show("punto 6 - 'risolto temporaneamente' con verifica scaduta e senza figlio", temp_scaduti)

        self.stdout.write("")
        self.stdout.write(
            "CONFLITTI DI PERIODICITA': non sono persistiti. Sono uno stato calcolato\n"
            "da assets/services/maintenance_domain.py (build_plan_resolutions): due o piu'\n"
            "applicazioni dello stesso piano, di pari specificita' (ASSET/GRUPPO/CATEGORIA),\n"
            "che dichiarano tempi diversi. 'Tempi diversi' = firma di ricorrenza diversa\n"
            "(frequency, interval, weekday, week_of_month, day_of_month, month_of_year,\n"
            "warning_days, ancoraggio). Un conflitto SOSPENDE la generazione: la coppia\n"
            "(piano, asset) viene saltata e nessuna occorrenza nasce."
        )

        if self.explain:
            self.stdout.write("")
            self.stdout.write(
                "[QUERY] punto 6 - conflitti: build_plan_resolutions(asset_queryset=Asset in uso)\n"
                "        Non e' una singola query SQL: sono 3 query (asset, applicazioni,\n"
                "        membership dei gruppi) e la risoluzione avviene in memoria.\n"
                "        Non scrive nulla."
            )
            return

        if self.skip_conflicts:
            self.stdout.write("")
            self.stdout.write("Conflitti: saltati (--skip-conflicts).")
        else:
            self._conflitti()

        righe_fu = list(follow_up)
        self.stdout.write("")
        self.stdout.write("FOLLOW-UP PER STATO")
        self.stdout.write(f"{'stato':<10} {'totali':>7} {'da esito':>9} {'da occorrenza':>14} {'da checklist':>13}")
        self.stdout.write(RULE)
        for row in righe_fu:
            self.stdout.write(
                f"{row['status']:<10} {row['totali']:>7} {row['da_esito']:>9} "
                f"{row['da_occorrenza']:>14} {row['da_checklist']:>13}"
            )
        if not righe_fu:
            self.stdout.write("(nessun follow-up)")
        self.stdout.write(RULE)
        self.stdout.write(f"{'TOTALE':<10} {sum(r['totali'] for r in righe_fu):>7}")

        righe_temp = list(temp_scaduti)
        self.stdout.write("")
        self.stdout.write(f"'RISOLTO TEMPORANEAMENTE' CON VERIFICA SCADUTA E NESSUN FOLLOW-UP: {len(righe_temp)}")
        for row in righe_temp[:20]:
            self.stdout.write(
                f"  OdL #{row['id']:<8} {row['asset__asset_tag'] or '-':<16} "
                f"verifica entro {row['follow_up_date']:%d-%m-%Y}"
            )

    def _conflitti(self) -> None:
        from assets.services.maintenance_domain import build_plan_resolutions

        self.stdout.write("")
        self.stdout.write("[QUERY] punto 6 - conflitti di periodicita'")
        self.stdout.write(RULE)
        self.stdout.write(
            "build_plan_resolutions(asset_queryset=Asset.objects.filter(status=IN_USE))\n"
            "-> 3 query in lettura (asset, applicazioni attive, membership gruppi),\n"
            "   risoluzione in memoria. Nessuna scrittura."
        )
        self.stdout.write(RULE)

        resolutions = build_plan_resolutions(asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE))
        conflitti = [r for r in resolutions.values() if r.is_conflict]
        esclusi = [r for r in resolutions.values() if r.is_excluded]
        applicati = [r for r in resolutions.values() if r.is_applied]

        self.stdout.write("")
        self.stdout.write(f"Coppie (piano, asset) risolte : {len(resolutions)}")
        self.stdout.write(f"  applicate                   : {len(applicati)}")
        self.stdout.write(f"  escluse                     : {len(esclusi)}")
        self.stdout.write(f"  IN CONFLITTO                : {len(conflitti)}")

        if not conflitti:
            return
        self.stdout.write("")
        self.stdout.write("DETTAGLIO CONFLITTI (la generazione delle occorrenze e' sospesa su queste coppie)")
        self.stdout.write(RULE)
        for resolution in conflitti[: (self.limit or len(conflitti))]:
            asset_label = resolution.asset.asset_tag or resolution.asset.name
            self.stdout.write(f"  {resolution.plan.label} su {asset_label}")
            for voce in resolution.conflict_description():
                self.stdout.write(f"      {voce['target']:<28} {voce['recurrence']}")
