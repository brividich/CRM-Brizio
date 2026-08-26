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
4. **senza collocazione ma con responsabile** — né reparto, né area, né area
   aziendale, eppure un responsabile valorizzato. È una **segnalazione**: il
   dato che manca è la collocazione, non il responsabile, e `--apply` non lo
   tocca. Solo `--azzera-responsabili-scollegati` lo cancella davvero.

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
        parser.add_argument(
            "--azzera-responsabili-scollegati", action="store_true",
            help=(
                "Con --apply, azzera il responsabile anche a chi non ha alcuna "
                "collocazione (né reparto né area). Da usare solo sapendo che quel "
                "responsabile è sbagliato: di norma il dato mancante è il reparto."
            ),
        )
        parser.add_argument(
            "--persona", default=None,
            help=(
                "Diagnosi mirata: stampa TUTTE le righe di anagrafica che contengono "
                "questo testo in nome/cognome/username, con id, reparto, ruoli assegnati "
                "e responsabile. Serve a smascherare i doppioni, dove scheda e ruolo "
                "vivono su due id diversi della stessa persona."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        solo = options["solo"]
        persona = (options["persona"] or "").strip()

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

        if persona:
            self._diagnosi_persona(persona, anagrafica)
            return

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
                    continue
                # «Senza reparto» va guardato su tutte e tre le collocazioni: il
                # reparto legacy è testo libero e in produzione è vuoto per la
                # maggioranza, ma la persona può essere collocata via `area` o
                # via FK `area_aziendale`. Chi ha una di queste NON è anomalo:
                # il responsabile che porta è quello vero.
                if (
                    not reparto_di(legacy_id)
                    and not (az.area or "").strip()
                    and not az.area_aziendale_id
                ):
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
            self.stdout.write(
                f"  Senza alcuna collocazione (né reparto, né area) ma con responsabile: "
                f"{len(capo_senza_reparto)}"
            )
            self.stdout.write(
                "    SEGNALAZIONE, non riparazione: il dato mancante è la collocazione, "
                "non il responsabile."
            )
            self.stdout.write(
                "    --apply NON li tocca. Per azzerare comunque i responsabili: "
                "--azzera-responsabili-scollegati."
            )
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

            # Di default si azzera solo chi è responsabile di sé stesso: è un
            # dato senza significato. Chi è privo di collocazione ha quasi
            # sempre un responsabile corretto e un reparto da compilare —
            # cancellarlo perderebbe l'unica informazione buona che ha.
            da_azzerare = set(se_stessi)
            if options["azzera_responsabili_scollegati"]:
                da_azzerare |= {lid for lid, _ in capo_senza_reparto}
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

    def _diagnosi_persona(self, testo: str, anagrafica: dict[int, dict]) -> None:
        """Tutte le righe legacy che somigliano a `testo`, con quanto ci sta attaccato.

        Non deduplica di proposito: due righe per la stessa persona sono
        esattamente ciò che si sta cercando, e la fusione le nasconderebbe.
        """
        ago = testo.casefold()
        grezze = [
            r for r in fetch_anagrafica_rows()
            if ago in " ".join(
                str(r.get(c) or "") for c in ("nome", "cognome", "aliasusername")
            ).casefold()
        ]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Diagnosi «{testo}» — {len(grezze)} righe in anagrafica"))
        if not grezze:
            return

        ids = [int(r.get("id") or 0) for r in grezze]
        # Con chi e quando: «questo ruolo da dove salta fuori?» si risponde solo
        # guardando l'autore e la data dell'assegnazione.
        ruoli_per_id: dict[int, list[str]] = {}
        for a in DipendenteRuoloOperativo.objects.filter(
            legacy_anagrafica_id__in=ids
        ).select_related("ruolo", "assegnato_da"):
            autore = getattr(a.assegnato_da, "username", "") or "origine non tracciata"
            quando = a.assegnato_il.strftime("%d/%m/%Y") if a.assegnato_il else "?"
            periodo = ""
            if a.data_inizio or a.data_fine:
                periodo = " · dal {}{}".format(
                    a.data_inizio.strftime("%d/%m/%Y") if a.data_inizio else "?",
                    f" al {a.data_fine.strftime('%d/%m/%Y')}" if a.data_fine else "",
                )
            tipologia = f" [{a.get_tipologia_display()}]" if a.tipologia else ""
            ruoli_per_id.setdefault(a.legacy_anagrafica_id, []).append(
                f"{a.ruolo.nome}{tipologia}{periodo} — assegnato da {autore} il {quando}"
            )

        schede = {
            az.legacy_anagrafica_id: az
            for az in DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=ids)
        }

        def nome_di(legacy_id: int) -> str:
            row = anagrafica.get(legacy_id) or {}
            return " ".join(
                p for p in [
                    str(row.get("cognome") or "").strip(),
                    str(row.get("nome") or "").strip(),
                ] if p
            ) or f"#{legacy_id}"

        for row in grezze:
            legacy_id = int(row.get("id") or 0)
            az = schede.get(legacy_id)
            self.stdout.write("")
            self.stdout.write(f"  id {legacy_id} — {nome_di(legacy_id)} (username: {row.get('aliasusername') or '—'})")
            self.stdout.write(f"    reparto legacy : {row.get('reparto') or '—'}")
            self.stdout.write(f"    mansione legacy: {row.get('mansione') or '—'}")
            self.stdout.write(f"    utente_id      : {row.get('utente_id') or '—'}")
            righe_ruoli = sorted(ruoli_per_id.get(legacy_id, []))
            if righe_ruoli:
                self.stdout.write("    ruoli assegnati:")
                for voce in righe_ruoli:
                    self.stdout.write(f"      · {voce}")
            else:
                self.stdout.write("    ruoli assegnati: —")
            if az is None:
                self.stdout.write("    scheda aziendale: ASSENTE")
                continue
            capo = az.caporeparto_legacy_id or 0
            capo_txt = f"{nome_di(capo)} (id {capo})" if capo else "—"
            self.stdout.write(f"    ruolo aziendale : {az.ruolo_aziendale or '—'}")
            self.stdout.write(f"    responsabile    : {capo_txt}")
            self.stdout.write(f"    area aziendale  : {az.area_aziendale.nome if az.area_aziendale_id else '—'}")

