"""Segnala le varianti del glossario presenti in troppi brani (chunk) dei documenti SGI.

Una variante come «posizione» o «passo» che compare in più del 20% dei chunk SGI aiuta
poco il retrieval e può avvicinare documenti che non c'entrano. Il comando la segnala
nella pagina «Da rivedere» con l'etichetta «parola comune: valutare usa_nel_rag».
Nessuna esclusione automatica: decide la Qualità.

Sola lettura sui documenti; scrive solo il risultato in cache. Da lanciare dopo
``index_sgi_documents`` (o quando cambia il glossario).

Esempi:
    python manage.py glossario_varianti_comuni
    python manage.py glossario_varianti_comuni --soglia 0.3
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from glossario_tecnico.services import SOGLIA_PAROLA_COMUNE, calcola_varianti_comuni


class Command(BaseCommand):
    help = "Segnala le varianti del glossario presenti in più del 20% dei chunk SGI (pagina «Da rivedere»)."

    def add_arguments(self, parser):
        parser.add_argument("--soglia", type=float, default=SOGLIA_PAROLA_COMUNE,
                            help="Quota di chunk SGI oltre cui una variante è «comune» (default 0.20).")

    def handle(self, *args, **options):
        from ai_assistant import services

        testi = [f"{c.title}\n{c.content}" for c in services._load_sgi_document_chunks()]
        if not testi:
            self.stdout.write(self.style.WARNING("Nessun chunk SGI: indicizzare prima i documenti."))
            return
        esito = calcola_varianti_comuni(testi, soglia=options["soglia"])
        self.stdout.write(f"Chunk SGI: {esito['chunk_sgi']} · soglia {esito['soglia']:.0%} · "
                          f"varianti comuni: {len(esito['voci'])}")
        for r in esito["voci"]:
            self.stdout.write(f"  {r['testo']} -> {r['termine']} ({r['chunk']} chunk, {r['quota']:.0%})")
