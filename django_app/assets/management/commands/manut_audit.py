"""Audit di sola lettura del dominio manutenzione (Fase 0 del refactoring stati).

Risponde ai punti 3, 4 e 6 della ricognizione:

3. **Debito storico** — ordini di lavoro chiusi che contengono ancora occorrenze
   non registrate. Chiudere un OdL non registra le manutenzioni che raccoglie
   (``assets/views.py`` ``workorder_close``): la scadenza dell'asset resta
   aperta. Qui si misura quanto e' grande il fenomeno.
4. **Uso reale** — ultimi 12 mesi: OdL aperti per mese, occorrenze registrate
   dentro/fuori un OdL, utenti distinti che hanno registrato.
6. **Concetti non definiti** — follow-up e conflitti di periodicita'.

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
    MaintenanceOccurrence,
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
        self.today: date = timezone.localdate()
        self.window_start = self.today - timedelta(days=self.months * 31)

        self._header()
        self._punto3_debito_storico()
        self._punto4_uso_reale()
        self._punto6_concetti()
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
