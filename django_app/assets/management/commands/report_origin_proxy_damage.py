"""Ricognizione (SOLA LETTURA) del danno lasciato nei dati dalla classe di bug "origin come proxy".

Il generatore di OdL usava ``origin=PERIODIC`` come proxy per due domande diverse:
  - "quando è stata eseguita l'ultima volta?"  → non vedeva le esecuzioni registrate a mano
    (che nascono ORIGIN_MANUAL) né lo storico registrato senza OdL;
  - "c'è già lavoro pendente su questa regola?" → non vedeva gli OdL aperti a mano.

Conseguenze già scritte a database:
  1. OdL periodici generati su regole che erano appena state eseguite, o su cui c'era già
     un intervento aperto → duplicati;
  2. per le regole a contatore, la baseline tornava a 0 quando l'ultima esecuzione non era
     un OdL periodico → il consumo calcolato risultava enorme (l'intero valore del contatore
     invece della differenza) e poteva far scattare manutenzioni molto in anticipo.

Il comando NON scrive nulla: nessuna migrazione, nessuna correzione, nessun effetto collaterale.
Serve solo a mettere i numeri sul tavolo prima di decidere se una bonifica serva davvero.

    python manage.py report_origin_proxy_damage
    python manage.py report_origin_proxy_damage --limit 50
    python manage.py report_origin_proxy_damage --json

Solo ORM (nessun SQL raw): gira identico su SQLite (dev) e SQL Server (prod).
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from assets.models import (
    AssetMaintenanceRuleState,
    AssetMeter,
    MaintenanceRule,
    WorkOrder,
)

_METER_TYPE_MAP = {
    MaintenanceRule.THRESHOLD_HOURS: AssetMeter.METER_HOURS,
    MaintenanceRule.THRESHOLD_KM: AssetMeter.METER_KM,
    MaintenanceRule.THRESHOLD_CYCLES: AssetMeter.METER_CYCLES,
}


def _as_date(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()


class Command(BaseCommand):
    help = "SOLA LETTURA: riporta OdL periodici duplicati e consumi contatore falsati dal bug 'origin come proxy'."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Righe di dettaglio da elencare per sezione (0 = tutte). Default: 25.",
        )
        parser.add_argument("--json", action="store_true", help="Output JSON invece che testo.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Accettato per abitudine e ignorato: il comando è SEMPRE di sola lettura.",
        )

    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        limit: int = int(options.get("limit") or 0)
        as_json: bool = bool(options.get("json"))

        duplicates = self._find_duplicate_periodic_workorders()
        meter_anomalies = self._find_meter_baseline_anomalies()
        downstream = self._downstream_impact(duplicates)

        if as_json:
            self.stdout.write(
                json.dumps(
                    {
                        "odl_periodici_sospetti": duplicates,
                        "consumi_contatore_falsati": meter_anomalies,
                        "impatto_a_valle": downstream,
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
            return

        self._render_text(duplicates, meter_anomalies, downstream, limit=limit)

    # ------------------------------------------------------------------ #
    # 1. OdL periodici duplicati
    # ------------------------------------------------------------------ #

    def _find_duplicate_periodic_workorders(self) -> list[dict]:
        """OdL periodici che il generatore non avrebbe dovuto aprire.

        Due cause distinte, entrambe figlie del proxy su ``origin``:
          - "premature": alla data di apertura la regola era già stata eseguita di recente
            (l'esecuzione esisteva, ma con un'origine che il generatore non guardava);
          - "concorrente": alla data di apertura c'era già un altro OdL aperto sulla regola.
        """
        periodic = list(
            WorkOrder.objects
            .filter(origin=WorkOrder.ORIGIN_PERIODIC)
            .exclude(maintenance_rule_id=None)
            .select_related("asset", "maintenance_rule", "maintenance_rule__intervention_template")
            .order_by("opened_at", "id")
        )
        if not periodic:
            return []

        # Storico completo degli interventi per coppia (asset, regola), qualunque origine.
        history: dict[tuple[int, int], list[WorkOrder]] = {}
        for workorder in (
            WorkOrder.objects
            .exclude(maintenance_rule_id=None)
            .only("id", "asset_id", "maintenance_rule_id", "status", "origin", "opened_at", "closed_at")
            .order_by("opened_at", "id")
        ):
            history.setdefault((workorder.asset_id, workorder.maintenance_rule_id), []).append(workorder)

        findings: list[dict] = []
        for wo in periodic:
            rule = wo.maintenance_rule
            key = (wo.asset_id, wo.maintenance_rule_id)
            opened_at = wo.opened_at
            opened_on = _as_date(opened_at)
            siblings = [other for other in history.get(key, []) if other.id != wo.id]

            # (a) esecuzione precedente, di QUALUNQUE origine, chiusa prima di questa apertura
            previous_executions = [
                other for other in siblings
                if other.status == WorkOrder.STATUS_DONE
                and other.closed_at is not None
                and other.closed_at <= opened_at
            ]
            premature = None
            if previous_executions and rule.threshold_type == MaintenanceRule.THRESHOLD_DAYS:
                last_exec = max(previous_executions, key=lambda o: o.closed_at)
                last_exec_on = _as_date(last_exec.closed_at)
                giorni_dall_ultima = (opened_on - last_exec_on).days
                # Quando sarebbe realmente scaduta, con la regola attuale
                due_on = last_exec_on + timedelta(days=int(rule.threshold_value or 0))
                anticipo = (due_on - timedelta(days=int(rule.warning_days or 0))) - opened_on
                if anticipo.days > 0:
                    premature = {
                        "ultima_esecuzione": str(last_exec_on),
                        "origine_ultima_esecuzione": last_exec.origin,
                        "giorni_dall_ultima": giorni_dall_ultima,
                        "sarebbe_scaduta_il": str(due_on),
                        "generato_con_anticipo_giorni": anticipo.days,
                    }

            # (b) un altro OdL era già aperto sulla regola quando questo è stato generato
            concurrent = [
                other for other in siblings
                if other.opened_at <= opened_at
                and (other.closed_at is None or other.closed_at > opened_at)
                and other.id < wo.id
            ]
            concorrente = None
            if concurrent:
                blocking = concurrent[-1]
                concorrente = {
                    "odl_gia_aperto": blocking.id,
                    "origine": blocking.origin,
                    "aperto_il": str(_as_date(blocking.opened_at)),
                }

            if not premature and not concorrente:
                continue

            findings.append(
                {
                    "workorder_id": wo.id,
                    "asset": wo.asset.asset_tag,
                    "asset_id": wo.asset_id,
                    "regola_id": rule.id,
                    "regola": getattr(rule.intervention_template, "label", "") or "",
                    "soglia": f"{rule.threshold_value} {rule.threshold_type}",
                    "aperto_il": str(opened_on),
                    "stato": wo.status,
                    "causa_anticipo": premature,
                    "causa_concorrenza": concorrente,
                }
            )
        return findings

    # ------------------------------------------------------------------ #
    # 2. Consumi contatore calcolati su baseline 0
    # ------------------------------------------------------------------ #

    def _find_meter_baseline_anomalies(self) -> list[dict]:
        """Regole a contatore la cui ultima esecuzione NON è un OdL periodico.

        Per queste, il vecchio generatore non trovava alcun ``meter_value_at_close`` e ripartiva
        da 0: il consumo che calcolava era l'intero valore del contatore, non la differenza.
        """
        states = list(
            AssetMaintenanceRuleState.objects
            .select_related("asset", "base_rule", "base_rule__intervention_template", "last_work_order")
            .filter(base_rule__threshold_type__in=list(_METER_TYPE_MAP.keys()))
        )
        if not states:
            return []

        meter_map = {
            (m["asset_id"], m["meter_type"]): m["current_value"]
            for m in AssetMeter.objects.values("asset_id", "meter_type", "current_value")
        }

        anomalies: list[dict] = []
        for state in states:
            rule = state.base_rule
            last_wo = state.last_work_order
            if last_wo is None or last_wo.meter_value_at_close is None:
                continue
            # Se l'ultima esecuzione era già un OdL periodico, il vecchio codice la vedeva: nessun danno.
            if last_wo.origin == WorkOrder.ORIGIN_PERIODIC:
                continue

            meter_type = _METER_TYPE_MAP[rule.threshold_type]
            current_value = meter_map.get((state.asset_id, meter_type))
            if current_value is None:
                continue

            baseline = float(last_wo.meter_value_at_close)
            current = float(current_value)
            soglia = float(rule.threshold_value or 0)
            consumo_calcolato = current           # ciò che il generatore vedeva (baseline 0)
            consumo_reale = max(0.0, current - baseline)
            anomalies.append(
                {
                    "asset": state.asset.asset_tag,
                    "asset_id": state.asset_id,
                    "regola_id": rule.id,
                    "regola": getattr(rule.intervention_template, "label", "") or "",
                    "unita": rule.threshold_type,
                    "soglia": soglia,
                    "contatore_attuale": current,
                    "baseline_corretta": baseline,
                    "origine_ultima_esecuzione": last_wo.origin,
                    "consumo_calcolato_dal_bug": consumo_calcolato,
                    "consumo_reale": consumo_reale,
                    "scatto_falso": consumo_calcolato >= soglia > consumo_reale,
                }
            )
        return anomalies

    # ------------------------------------------------------------------ #
    # 3. Impatto a valle
    # ------------------------------------------------------------------ #

    def _downstream_impact(self, duplicates: list[dict]) -> dict:
        """Cosa questi dati hanno mosso a valle — e cosa non è ricostruibile.

        Le email di reminder NON sono tracciate: il comando send_maintenance_reminders non
        scrive alcun flag "inviato" (è dichiarato nel suo stesso docstring). Quante mail siano
        partite citando un OdL spurio è quindi **non ricostruibile a posteriori**.
        Le notifiche in-app invece esistono come righe (core.Notifica) e sono contabili, ma il
        loro testo non porta l'id dell'OdL: si può solo contare la categoria.
        """
        ids = [row["workorder_id"] for row in duplicates]
        aperti = WorkOrder.objects.filter(id__in=ids, status=WorkOrder.STATUS_OPEN).count()
        chiusi = WorkOrder.objects.filter(id__in=ids, status=WorkOrder.STATUS_DONE).count()
        annullati = WorkOrder.objects.filter(id__in=ids, status=WorkOrder.STATUS_CANCELED).count()

        notifiche_asset = None
        try:
            from core.models import Notifica

            notifiche_asset = Notifica.objects.filter(tipo="asset_scadenza").count()
        except Exception:
            notifiche_asset = None

        return {
            "odl_sospetti_totali": len(ids),
            "di_cui_ancora_aperti": aperti,
            "di_cui_chiusi_come_eseguiti": chiusi,
            "di_cui_annullati": annullati,
            "notifiche_in_app_asset_scadenza_totali": notifiche_asset,
            "email_reminder_inviate": "NON TRACCIABILE (send_maintenance_reminders non registra alcun flag di invio)",
            "attribuzione_notifiche_al_singolo_odl": "NON TRACCIABILE (il messaggio della notifica non porta l'id dell'OdL)",
        }

    # ------------------------------------------------------------------ #

    def _render_text(self, duplicates, meter_anomalies, downstream, *, limit: int) -> None:
        write = self.stdout.write
        write(self.style.WARNING("RICOGNIZIONE SOLA LETTURA — nessun dato è stato modificato."))
        write("")

        write(self.style.MIGRATE_HEADING(f"1. OdL periodici sospetti: {len(duplicates)}"))
        if not duplicates:
            write("   Nessuno.")
        else:
            anticipo = [row for row in duplicates if row["causa_anticipo"]]
            concorrenza = [row for row in duplicates if row["causa_concorrenza"]]
            write(f"   - generati su una manutenzione già eseguita di recente: {len(anticipo)}")
            write(f"   - generati mentre un altro OdL era già aperto sulla regola: {len(concorrenza)}")
            rows = duplicates if limit <= 0 else duplicates[:limit]
            for row in rows:
                write(
                    f"   #{row['workorder_id']} {row['asset']} — {row['regola']} "
                    f"(regola {row['regola_id']}, {row['soglia']}) aperto il {row['aperto_il']} [{row['stato']}]"
                )
                if row["causa_anticipo"]:
                    causa = row["causa_anticipo"]
                    write(
                        f"       ultima esecuzione {causa['ultima_esecuzione']} "
                        f"(origine {causa['origine_ultima_esecuzione']}, {causa['giorni_dall_ultima']} gg prima); "
                        f"sarebbe scaduta il {causa['sarebbe_scaduta_il']} → generato con "
                        f"{causa['generato_con_anticipo_giorni']} gg di anticipo"
                    )
                if row["causa_concorrenza"]:
                    causa = row["causa_concorrenza"]
                    write(
                        f"       OdL #{causa['odl_gia_aperto']} ({causa['origine']}) era già aperto "
                        f"dal {causa['aperto_il']}"
                    )
            if limit > 0 and len(duplicates) > limit:
                write(f"   … e altri {len(duplicates) - limit} (usa --limit 0 per l'elenco completo)")
        write("")

        write(self.style.MIGRATE_HEADING(f"2. Consumi contatore calcolati su baseline 0: {len(meter_anomalies)}"))
        if not meter_anomalies:
            write("   Nessuno.")
        else:
            falsi = [row for row in meter_anomalies if row["scatto_falso"]]
            write(f"   - di cui avrebbero fatto scattare la soglia SENZA averla realmente raggiunta: {len(falsi)}")
            rows = meter_anomalies if limit <= 0 else meter_anomalies[:limit]
            for row in rows:
                marker = " ← SCATTO FALSO" if row["scatto_falso"] else ""
                write(
                    f"   {row['asset']} — {row['regola']} (regola {row['regola_id']}, soglia {row['soglia']:.0f}){marker}"
                )
                write(
                    f"       contatore {row['contatore_attuale']:.0f}, baseline corretta {row['baseline_corretta']:.0f} "
                    f"(ultima esecuzione origine {row['origine_ultima_esecuzione']})"
                )
                write(
                    f"       consumo calcolato dal bug: {row['consumo_calcolato_dal_bug']:.0f} — "
                    f"consumo reale: {row['consumo_reale']:.0f}"
                )
            if limit > 0 and len(meter_anomalies) > limit:
                write(f"   … e altri {len(meter_anomalies) - limit} (usa --limit 0 per l'elenco completo)")
        write("")

        write(self.style.MIGRATE_HEADING("3. Impatto a valle"))
        for key, value in downstream.items():
            write(f"   {key}: {value}")
