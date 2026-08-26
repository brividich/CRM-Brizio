"""Report + riparazione dei ruoli e dei responsabili incoerenti in anagrafica.

Il ruolo di una persona vive in due posti — le assegnazioni del catalogo
(``DipendenteRuoloOperativo``, N per persona) e il campo testuale singolo
``ruolo_aziendale`` della scheda, che è il **ruolo principale**. Finché nessuno
li teneva allineati si vedeva un ruolo «assegnato» nel catalogo e un «Ruolo
aziendale: —» nella scheda della stessa persona, o viceversa.

Nella stessa passata si controlla il responsabile della scheda
(``caporeparto_legacy_id``), che è un valore salvato e non ricalcolato: resta
quello di ieri anche quando il reparto è stato svuotato, e nulla impediva a una
persona di risultare responsabile di sé stessa.

Quattro anomalie, tutte in sola lettura finché non si passa ``--apply``:

1. **assegnato senza principale** — ha ruoli assegnati ma `ruolo_aziendale`
   vuoto. Riparazione: se il ruolo è **uno solo** diventa il principale; con più
   ruoli si elenca e si salta (scegliere quale sia il principale è una
   decisione, non un automatismo).
2. **principale senza assegnazione** — `ruolo_aziendale` valorizzato e presente
   in catalogo, ma nessuna assegnazione. Riparazione: crea l'assegnazione.
3. **responsabile di sé stesso** — `caporeparto_legacy_id` uguale alla persona.
   Riparazione: azzera.
4. **responsabile senza reparto** — nessun reparto in scheda ma un responsabile
   valorizzato. Riparazione: azzera.

Uso:
    python manage.py report_ruoli_disallineati              # solo report
    python manage.py report_ruoli_disallineati --apply      # ripara
    python manage.py report_ruoli_disallineati --solo ruoli # o --solo responsabili
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from anagrafica.models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    RuoloOperativo,
)
from core.legacy_anagrafica import fetch_anagrafica_rows


class Command(BaseCommand):
    help = (
        "Elenca (e con --apply ripara) i ruoli disallineati fra catalogo e scheda "
        "dipendente, e i responsabili incoerenti."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Applica le riparazioni. Senza questo flag il comando non scrive nulla.",
        )
        parser.add_argument(
            "--solo", choices=["ruoli", "responsabili"], default=None,
            help="Limita il controllo a una sola famiglia di anomalie.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        solo = options["solo"]

        rows = fetch_anagrafica_rows(deduplicate=True)
        anagrafica = {
            int(r.get("id") or 0): r for r in rows if int(r.get("id") or 0) > 0
        }

        def label(legacy_id: int) -> str:
            row = anagrafica.get(legacy_id) or {}
            nome = str(row.get("nome") or "").strip()
            cognome = str(row.get("cognome") or "").strip()
            return " ".join(p for p in [cognome, nome] if p) or f"#{legacy_id}"

        def reparto_di(legacy_id: int) -> str:
            return str((anagrafica.get(legacy_id) or {}).get("reparto") or "").strip()

        catalogo = {r.nome.strip().casefold(): r for r in RuoloOperativo.objects.all()}

        assegnazioni: dict[int, list[str]] = {}
        for a in DipendenteRuoloOperativo.objects.select_related("ruolo"):
            assegnazioni.setdefault(a.legacy_anagrafica_id, []).append(a.ruolo.nome)
        for nomi in assegnazioni.values():
            nomi.sort(key=str.casefold)

        schede = {
            az.legacy_anagrafica_id: az
            for az in DipendenteAnagraficaAziendale.objects.all()
        }

        senza_principale: list[tuple[int, list[str]]] = []
        senza_assegnazione: list[tuple[int, str]] = []
        se_stessi: list[int] = []
        capo_senza_reparto: list[tuple[int, int]] = []

        if solo != "responsabili":
            for legacy_id, nomi in assegnazioni.items():
                az = schede.get(legacy_id)
                if not (az and (az.ruolo_aziendale or "").strip()):
                    senza_principale.append((legacy_id, nomi))

            for legacy_id, az in schede.items():
                principale = (az.ruolo_aziendale or "").strip()
                if not principale or principale.casefold() not in catalogo:
                    continue
                gia = {n.casefold() for n in assegnazioni.get(legacy_id, [])}
                if principale.casefold() not in gia:
                    senza_assegnazione.append((legacy_id, principale))

        if solo != "ruoli":
            for legacy_id, az in schede.items():
                capo = az.caporeparto_legacy_id or 0
                if not capo:
                    continue
                if int(capo) == int(legacy_id):
                    se_stessi.append(legacy_id)
                elif not reparto_di(legacy_id):
                    capo_senza_reparto.append((legacy_id, int(capo)))

        # ── Report ───────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Ruoli e responsabili — anomalie"))

        if solo != "responsabili":
            self.stdout.write("")
            self.stdout.write(f"  Ruoli assegnati senza ruolo aziendale principale: {len(senza_principale)}")
            for legacy_id, nomi in sorted(senza_principale, key=lambda x: label(x[0])):
                nota = "" if len(nomi) == 1 else "  (più ruoli: scelta manuale)"
                self.stdout.write(f"    - {label(legacy_id)}: {', '.join(nomi)}{nota}")

            self.stdout.write("")
            self.stdout.write(f"  Ruolo aziendale senza assegnazione nel catalogo: {len(senza_assegnazione)}")
            for legacy_id, nome in sorted(senza_assegnazione, key=lambda x: label(x[0])):
                self.stdout.write(f"    - {label(legacy_id)}: {nome}")

        if solo != "ruoli":
            self.stdout.write("")
            self.stdout.write(f"  Responsabili di sé stessi: {len(se_stessi)}")
            for legacy_id in sorted(se_stessi, key=label):
                self.stdout.write(f"    - {label(legacy_id)}")

            self.stdout.write("")
            self.stdout.write(f"  Responsabile valorizzato senza reparto: {len(capo_senza_reparto)}")
            for legacy_id, capo in sorted(capo_senza_reparto, key=lambda x: label(x[0])):
                self.stdout.write(f"    - {label(legacy_id)} → responsabile: {label(capo)}")

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Nessuna modifica: rilancia con --apply per riparare."))
            return

        # ── Riparazione ──────────────────────────────────────────────────────
        promossi = creati = azzerati = 0
        saltati_multiruolo = 0
        with transaction.atomic():
            for legacy_id, nomi in senza_principale:
                if len(nomi) != 1:
                    saltati_multiruolo += 1
                    continue
                az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
                    legacy_anagrafica_id=legacy_id,
                )
                az.ruolo_aziendale = nomi[0][:200]
                az.save(update_fields=["ruolo_aziendale", "updated_at"])
                promossi += 1

            for legacy_id, nome in senza_assegnazione:
                ruolo = catalogo.get(nome.casefold())
                if ruolo is None:
                    continue
                _, creata = DipendenteRuoloOperativo.objects.get_or_create(
                    legacy_anagrafica_id=legacy_id, ruolo=ruolo,
                )
                creati += int(creata)

            da_azzerare = set(se_stessi) | {lid for lid, _ in capo_senza_reparto}
            if da_azzerare:
                azzerati = (
                    DipendenteAnagraficaAziendale.objects
                    .filter(legacy_anagrafica_id__in=da_azzerare)
                    .update(caporeparto_legacy_id=None)
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Riparati: {promossi} ruoli principali impostati, {creati} assegnazioni create, "
            f"{azzerati} responsabili azzerati."
        ))
        if saltati_multiruolo:
            self.stdout.write(self.style.WARNING(
                f"Saltati {saltati_multiruolo} dipendenti con più ruoli assegnati: "
                "il ruolo principale va scelto a mano dalla scheda."
            ))
