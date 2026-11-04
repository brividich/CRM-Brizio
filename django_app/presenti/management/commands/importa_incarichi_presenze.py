"""Importa gli incarichi di sicurezza dal ``config.ini`` del vecchio script ReportPresenze.

La sezione ``[incarichi_sicurezza]`` ha righe ``matricola = Incarico[, Incarico]``.
Ogni matricola viene risolta in codice fiscale sull'anagrafica Solari e poi nella
persona del portale; ogni incarico diventa un ruolo dell'organigramma della
sicurezza (ambito ISO 45001), creato se manca. Da quel momento la fonte unica è
l'organigramma del portale.

Uso:
    python manage.py importa_incarichi_presenze --ini <percorso config.ini>          # mostra le differenze
    python manage.py importa_incarichi_presenze --ini <percorso config.ini> --apply  # applica

Non toglie niente: chi ha un incarico nel portale e non nel config.ini viene solo segnalato.
"""
from __future__ import annotations

import configparser

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Nome nel config.ini (minuscolo) -> (nome del ruolo nel portale, colore se va creato)
MAPPA_INCARICHI = {
    "preposto": ("Preposto", "#1d4ed8"),
    "antincendio": ("Squadra Antincendio", "#c2410c"),
    "primo soccorso": ("Addetto Primo Soccorso", "#15803d"),
    "rls": ("RLS", "#7c3aed"),
    "aspp": ("ASPP", "#0e7490"),
    "rspp": ("RSPP", "#0e7490"),
}


class Command(BaseCommand):
    help = "Importa gli incarichi di sicurezza del config.ini di ReportPresenze nell'organigramma ISO 45001."

    def add_arguments(self, parser):
        parser.add_argument("--ini", required=True, help="Percorso del config.ini dello script ReportPresenze.")
        parser.add_argument("--apply", action="store_true", help="Applica (senza: solo anteprima).")

    def handle(self, *args, ini: str, apply: bool, **opts):
        from anagrafica.models import AmbitoRuolo, DipendenteAnagraficaCivile, DipendenteRuoloOperativo, RuoloOperativo
        from presenti import solari

        cfg = configparser.ConfigParser()
        if not cfg.read(ini, encoding="utf-8") or not cfg.has_section("incarichi_sicurezza"):
            raise CommandError(f"Sezione [incarichi_sicurezza] non trovata in {ini}.")

        ambito = AmbitoRuolo.objects.filter(nome__icontains="45001").first()
        if ambito is None:
            raise CommandError("Ambito «Sicurezza ISO 45001» non trovato in Anagrafica › Ruoli.")

        try:
            cf_per_matricola = solari.leggi_matricole()
        except solari.SolariNonConfigurato as exc:
            raise CommandError(str(exc)) from exc
        lid_per_cf = {
            (cf or "").strip().upper(): int(lid)
            for cf, lid in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="")
            .values_list("codice_fiscale", "legacy_anagrafica_id")
        }

        voluti: set[tuple[int, str]] = set()
        problemi: list[str] = []
        for matricola, valore in cfg.items("incarichi_sicurezza"):
            chiave = matricola.strip().upper().lstrip("0") or "0"
            cf = cf_per_matricola.get(chiave, "")
            lid = lid_per_cf.get(cf) if cf else None
            if not cf:
                problemi.append(f"matricola {chiave}: non trovata in Solari")
                continue
            if lid is None:
                problemi.append(f"matricola {chiave}: codice fiscale non presente nell'anagrafica del portale")
                continue
            for nome in (v.strip() for v in valore.split(",") if v.strip()):
                voce = MAPPA_INCARICHI.get(nome.lower())
                if voce is None:
                    problemi.append(f"matricola {chiave}: incarico «{nome}» sconosciuto, saltato")
                    continue
                voluti.add((lid, voce[0]))

        nomi_ruoli = {n for n, _ in MAPPA_INCARICHI.values()}
        esistenti_ruoli = {r.nome: r for r in RuoloOperativo.objects.filter(nome__in=nomi_ruoli)}
        da_creare_ruoli = sorted({n for _, n in voluti} - set(esistenti_ruoli))
        attuali = set(
            DipendenteRuoloOperativo.objects.filter(ruolo__nome__in=nomi_ruoli, data_fine__isnull=True)
            .values_list("legacy_anagrafica_id", "ruolo__nome")
        )
        da_aggiungere = sorted(voluti - attuali)
        solo_portale = sorted(attuali - voluti)

        self.stdout.write(f"Incarichi nel config.ini risolti: {len(voluti)}")
        self.stdout.write(f"Ruoli da creare nell'ambito {ambito.nome}: {', '.join(da_creare_ruoli) or 'nessuno'}")
        self.stdout.write(f"Assegnazioni da aggiungere: {len(da_aggiungere)}")
        for lid, nome in da_aggiungere:
            self.stdout.write(f"  + [{lid}] {nome}")
        self.stdout.write(f"Assegnazioni presenti solo nel portale (non toccate): {len(solo_portale)}")
        for lid, nome in solo_portale:
            self.stdout.write(f"  = [{lid}] {nome}")
        for p in problemi:
            self.stdout.write(self.style.WARNING(f"  ! {p}"))

        if not apply:
            self.stdout.write(self.style.NOTICE("Anteprima: niente è stato scritto. Rilancia con --apply."))
            return

        colori = dict(MAPPA_INCARICHI.values())
        with transaction.atomic():
            for nome in da_creare_ruoli:
                esistenti_ruoli[nome] = RuoloOperativo.objects.create(
                    nome=nome, ambito=ambito, colore=colori.get(nome, "#64748b"),
                    descrizione="Incarico di sicurezza (importato da ReportPresenze).",
                )
            for lid, nome in da_aggiungere:
                DipendenteRuoloOperativo.objects.update_or_create(
                    legacy_anagrafica_id=lid, ruolo=esistenti_ruoli[nome],
                    defaults={"tipologia": DipendenteRuoloOperativo.TIPOLOGIA_SECONDARIO, "data_fine": None},
                )
        self.stdout.write(self.style.SUCCESS(
            f"Fatto: {len(da_creare_ruoli)} ruoli creati, {len(da_aggiungere)} assegnazioni aggiunte."))
