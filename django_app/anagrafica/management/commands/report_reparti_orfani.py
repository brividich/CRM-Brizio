"""Report + riassegnazione guidata dei dipendenti con reparto legacy "orfano".

Il campo REPARTO mostrato in lista Persone (badge per dipendente e filtro
"Contiene...") legge il testo libero legacy salvato su ogni singolo dipendente
(tabella anagrafica_dipendenti), non il catalogo Reparto (quello con CRUD in
Impostazioni). Cancellare un reparto dal catalogo non tocca il valore già
scritto sui dipendenti: resta "orfano" finché non viene riassegnato.

Uso:
    # Solo report (nessuna modifica)
    python manage.py report_reparti_orfani

    # Anteprima di una rimappatura (dry-run)
    python manage.py report_reparti_orfani --reassign "CNC5G=CNC"

    # Applica la rimappatura (storicizza il cambio e risincronizza area/caporeparto)
    python manage.py report_reparti_orfani --reassign "CNC5G=CNC" --apply --eseguito-da admin
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from anagrafica.models import DipendenteAnagraficaAziendale, Reparto
from core.legacy_anagrafica import fetch_anagrafica_rows, upsert_anagrafica_dipendente


class Command(BaseCommand):
    help = (
        "Elenca i dipendenti con reparto legacy 'orfano' (assente dal catalogo Reparto "
        "attivo) e, opzionalmente, li riassegna a un reparto del catalogo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reassign",
            action="append",
            default=[],
            metavar="VECCHIO=NUOVO",
            help="Rimappa un valore orfano su un reparto del catalogo attivo. Ripetibile.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applica le rimappature indicate con --reassign (default: solo anteprima).",
        )
        parser.add_argument(
            "--eseguito-da",
            default="",
            metavar="USERNAME",
            help="Username Django da registrare come autore dello storico cambiamenti.",
        )

    def handle(self, *args, **options):
        canonici = {r.nome.strip().casefold(): r.nome for r in Reparto.objects.filter(is_active=True)}
        mapping = self._parse_mapping(options["reassign"], canonici)

        cessati_ids = {
            int(lid)
            for lid in DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=False)
            .values_list("legacy_anagrafica_id", flat=True)
            if lid
        }
        rows = [
            row for row in fetch_anagrafica_rows(deduplicate=True)
            if int(row.get("id") or 0) not in cessati_ids
        ]

        orfani: dict[str, list[dict]] = {}
        for row in rows:
            valore = str(row.get("reparto") or "").strip()
            if not valore or valore.casefold() in canonici:
                continue
            orfani.setdefault(valore, []).append(row)

        if not orfani:
            self.stdout.write(self.style.SUCCESS(
                "Nessun reparto orfano: tutti i dipendenti in forza puntano a un reparto attivo del catalogo."
            ))
            return

        totale_dip = sum(len(v) for v in orfani.values())
        self.stdout.write(f"{len(orfani)} valori reparto orfani su {totale_dip} dipendenti in forza:\n")
        for valore, dipendenti in sorted(orfani.items(), key=lambda kv: -len(kv[1])):
            target = mapping.get(valore.casefold())
            freccia = f"  ->  {target}" if target else ""
            self.stdout.write(f"- {valore!r} ({len(dipendenti)} dipendenti){freccia}")
            for dip in sorted(dipendenti, key=lambda d: (str(d.get("cognome") or ""), str(d.get("nome") or ""))):
                self.stdout.write(f"    #{dip.get('id')} {dip.get('cognome')} {dip.get('nome')}")

        if not mapping:
            self.stdout.write(
                "\nNessuna rimappatura richiesta (--reassign). Solo report."
            )
            return

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nDry-run: nessuna modifica applicata. Rilancia con --apply per scrivere."
            ))
            return

        user = None
        username = options["eseguito_da"]
        if username:
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=username)
            except user_model.DoesNotExist:
                raise CommandError(f"Utente '{username}' non trovato.")

        from anagrafica.models import DipendenteCambiamentoOrganizzativo
        from anagrafica.views import _registra_cambiamento, _sync_aziendale_from_reparto

        n_aggiornati = 0
        with transaction.atomic():
            for valore, dipendenti in orfani.items():
                target = mapping.get(valore.casefold())
                if not target:
                    continue
                for dip in dipendenti:
                    legacy_id = int(dip.get("id") or 0)
                    upsert_anagrafica_dipendente(
                        row_id=legacy_id,
                        aliasusername=dip.get("aliasusername") or "",
                        nome=dip.get("nome") or "",
                        cognome=dip.get("cognome") or "",
                        reparto=target,
                        mansione=dip.get("mansione") or "",
                        ruolo=dip.get("ruolo") or "",
                        matricola=dip.get("matricola") or "",
                        email=dip.get("email") or "",
                        email_notifica=dip.get("email_notifica") or "",
                        attivo=bool(dip.get("attivo", True)),
                    )
                    _registra_cambiamento(
                        legacy_id,
                        DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
                        valore, target,
                        user,
                    )
                    _sync_aziendale_from_reparto(legacy_id, target, saved_by=user)
                    n_aggiornati += 1

        self.stdout.write(self.style.SUCCESS(f"\n{n_aggiornati} dipendenti riassegnati a un reparto del catalogo."))

    def _parse_mapping(self, raw_pairs: list[str], canonici: dict[str, str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for pair in raw_pairs:
            if "=" not in pair:
                raise CommandError(f"Formato non valido per --reassign: {pair!r} (atteso VECCHIO=NUOVO)")
            old, new = pair.split("=", 1)
            old, new = old.strip(), new.strip()
            if new.casefold() not in canonici:
                raise CommandError(f"Il reparto di destinazione {new!r} non esiste nel catalogo attivo.")
            mapping[old.casefold()] = canonici[new.casefold()]
        return mapping
