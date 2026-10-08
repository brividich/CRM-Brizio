"""Propone i collegamenti documento SGI ↔ processo dai codici citati nel processo (A2).

Legge i campi di testo libero ``Processo.procedure`` e ``Processo.fonte_documentale``,
riconosce i codici SGI con la stessa regola del grafo dei riferimenti e crea
``SgiDocumentoProcesso`` con ``confermato=False``: una proposta, da confermare.
Il testo del processo non viene mai modificato; i collegamenti già presenti
(confermati o no) restano come sono.

Esempi:
    python manage.py sgi_collega_processi --dry-run
    python manage.py sgi_collega_processi --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from procedure_refresh.models import SgiDocumentoProcesso
from procedure_refresh.sgi_riferimenti import Catalogo, codici_citati


class Command(BaseCommand):
    help = "Propone i collegamenti tra processi e documenti SGI dai codici citati (--dry-run / --apply)."

    def add_arguments(self, parser):
        gruppo = parser.add_mutually_exclusive_group(required=True)
        gruppo.add_argument("--dry-run", action="store_true", help="Mostra le proposte senza scrivere.")
        gruppo.add_argument("--apply", action="store_true", help="Crea le proposte (confermato=False).")

    def handle(self, *args, **opts):
        try:
            from sistema_gestione.models import Processo
        except Exception as exc:  # pragma: no cover - app sempre installata nel portale
            raise CommandError(f"App sistema_gestione non disponibile: {exc}") from exc

        catalogo = Catalogo()
        try:
            esistenti = set(SgiDocumentoProcesso.objects.values_list("documento_id", "processo_id"))
        except DatabaseError:
            if opts["apply"]:
                raise
            # Dry-run su un DB senza la migrazione 0009 (es. dev in sola lettura).
            self.stdout.write(self.style.WARNING("Tabella dei collegamenti assente: considero nessun collegamento esistente."))
            esistenti = set()
        proposte = nuove = gia_presenti = 0
        non_trovati: dict[str, set[str]] = {}
        famiglie: dict[str, set[str]] = {}
        for processo in Processo.objects.order_by("codice"):
            testo = f"{processo.procedure or ''}\n{processo.fonte_documentale or ''}"
            visti = set()
            for codice in codici_citati(testo):
                esito = catalogo.dettaglio(codice)
                doc = esito.documento
                if doc is None:
                    # Famiglia (es. «MT CN 125»): nessun documento singolo da collegare.
                    destinazione = famiglie if esito.tipo == "famiglia" else non_trovati
                    destinazione.setdefault(codice, set()).add(processo.codice)
                    continue
                if doc.pk in visti:
                    continue
                visti.add(doc.pk)
                proposte += 1
                if (doc.pk, processo.pk) in esistenti:
                    gia_presenti += 1
                    continue
                self.stdout.write(f"  {processo.codice} -> {doc.code}" + ("" if codice == doc.code else f" (citato «{codice}»)"))
                if opts["apply"]:
                    SgiDocumentoProcesso.objects.create(
                        documento=doc, processo=processo, codice_citato=codice[:60],
                        origine=SgiDocumentoProcesso.ORIGINE_PROCESSO_TESTO, confermato=False,
                    )
                nuove += 1
        verbo = "create" if opts["apply"] else "da creare"
        self.stdout.write(f"Collegamenti trovati: {proposte} · {verbo}: {nuove} · già presenti: {gia_presenti}")
        if famiglie:
            self.stdout.write(f"Famiglie di documenti citate (non collegate a un documento singolo): {len(famiglie)}")
            for codice in sorted(famiglie):
                self.stdout.write(f"  {codice} (processi: {', '.join(sorted(famiglie[codice]))})")
        if non_trovati:
            self.stdout.write(f"Codici citati nei processi ma non nel catalogo: {len(non_trovati)}")
            for codice in sorted(non_trovati):
                self.stdout.write(f"  {codice} (processi: {', '.join(sorted(non_trovati[codice]))})")
