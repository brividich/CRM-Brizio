"""Check di integrita' delle scadenze delle visite mediche. SOLA LETTURA.

Uso:
    python manage.py verifica_scadenze_visite
    python manage.py verifica_scadenze_visite --legacy-id 42 --righe 200
    python manage.py verifica_scadenze_visite --settings=config.settings.prod_readonly

Controlla:
1. Tipi di visita: nome con cadenza («Quinquennale», «Annuale», ...) e
   ``durata_mesi`` diversa da quella cadenza; tipi obbligatori senza durata.
2. Visite correnti delle persone in forza: scadenza salvata contro quella attesa
   dal motore dei requisiti (``requisiti.visite``, ricalcolo prudente). Le
   anticipate con motivo sono corrette e vengono solo contate; le divergenti si
   sistemano con ``ricalcola_scadenze_hr``.
3. Tutte le visite: scadenza mancante con tipo a durata, scadenza precedente
   alla data della visita, scadenza oltre quella del tipo (nessun calcolo la
   allunga).

Non scrive nulla: gira anche col profilo ``prod_readonly``.
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verifica (sola lettura) la coerenza delle scadenze delle visite mediche."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--legacy-id", type=int, action="append", dest="legacy_ids",
                            help="Solo questa persona (ripetibile).")
        parser.add_argument("--righe", type=int, default=50,
                            help="Righe di dettaglio per sezione (default 50, 0 = tutte).")

    def handle(self, *args, **options) -> None:
        from anagrafica.models import TipoVisitaMedica, VisitaMedica, _add_months
        from anagrafica.reportistica.dati import filtra_in
        from anagrafica.services import requisiti
        from anagrafica.services.referti_parsing import PERIODICITA_NOTE
        from anagrafica.services.scadenze import _persone

        self.limite = options["righe"]
        legacy_ids = options["legacy_ids"]
        problemi = 0

        # 1. Catalogo tipi
        cadenze = re.compile(r"\b(" + "|".join(PERIODICITA_NOTE) + r")\b", re.IGNORECASE)
        righe = []
        for t in TipoVisitaMedica.objects.order_by("nome"):
            m = cadenze.search(t.nome or "")
            durata = t.durata_mesi or 0
            if m and durata != PERIODICITA_NOTE[m.group(1).lower()]:
                righe.append(f"tipo #{t.pk} «{t.nome}»: durata_mesi={durata}, "
                             f"il nome indica {PERIODICITA_NOTE[m.group(1).lower()]}")
            elif t.is_active and getattr(t, "obbligatoria", False) and durata <= 0:
                righe.append(f"tipo #{t.pk} «{t.nome}»: obbligatorio ma senza durata (nessuna scadenza)")
        problemi += self._sezione("1. Tipi di visita incoerenti col nome", righe)

        # 2. Visite correnti contro il motore
        ctx = requisiti.ambito()
        persone = _persone(ctx, legacy_ids)
        voci = [v for v in requisiti.visite(ctx, persone) if v.visita_id] if persone else []
        # filtra_in: a blocchi, SQL Server non accetta piu' di 2100 parametri.
        salvate = {v.pk: v for v in filtra_in(VisitaMedica.objects.select_related("tipo"),
                                              "pk", {x.visita_id for x in voci})}
        anticipate, divergenti = [], []
        for voce in voci:
            v = salvate.get(voce.visita_id)
            if v is None:
                continue
            desc = (f"visita #{v.pk} persona {v.legacy_anagrafica_id} «{v.tipo.nome}» del "
                    f"{v.data_svolgimento:%d/%m/%Y}")
            if v.data_scadenza != voce.scadenza or (v.scadenza_nota or "") != voce.nota[:300]:
                divergenti.append(f"{desc}: salvata {self._d(v.data_scadenza)}, attesa {self._d(voce.scadenza)}"
                                  + (f" — {voce.nota}" if voce.nota else ""))
            elif voce.nota:
                anticipate.append(f"{desc}: {self._d(voce.scadenza_propria)} → {self._d(voce.scadenza)} — {voce.nota}")
        problemi += self._sezione("2a. Visite correnti con scadenza diversa dal motore "
                                  "(si sistemano con ricalcola_scadenze_hr)", divergenti)
        self._sezione("2b. Visite correnti con scadenza anticipata dalla mansione (corrette, informativo)",
                      anticipate, problema=False)

        # 3. Controlli su tutte le visite
        qs = VisitaMedica.objects.select_related("tipo").order_by("legacy_anagrafica_id", "data_svolgimento")
        if legacy_ids:
            qs = qs.filter(legacy_anagrafica_id__in=ctx.id_estesi(persone) or legacy_ids)
        mancanti, prima, oltre = [], [], []
        for v in qs.iterator():
            durata = v.tipo.durata_mesi or 0
            propria = _add_months(v.data_svolgimento, durata) if durata > 0 else None
            desc = (f"visita #{v.pk} persona {v.legacy_anagrafica_id} «{v.tipo.nome}» del "
                    f"{v.data_svolgimento:%d/%m/%Y}")
            if propria and v.data_scadenza is None:
                mancanti.append(f"{desc}: nessuna scadenza, il tipo prevede {self._d(propria)}")
            elif v.data_scadenza and v.data_scadenza < v.data_svolgimento:
                prima.append(f"{desc}: scade il {self._d(v.data_scadenza)}, prima della visita")
            elif propria and v.data_scadenza and v.data_scadenza > propria:
                oltre.append(f"{desc}: scade il {self._d(v.data_scadenza)}, oltre il {self._d(propria)} del tipo")
        problemi += self._sezione("3a. Visite senza scadenza con tipo a durata", mancanti)
        problemi += self._sezione("3b. Visite che scadono prima di essere state fatte", prima)
        problemi += self._sezione("3c. Visite con scadenza oltre quella del tipo", oltre)

        self.stdout.write("")
        self.stdout.write(f"Persone in forza esaminate: {len(persone)} · visite correnti: {len(voci)} · "
                          f"anticipate dalla mansione: {len(anticipate)}")
        if problemi:
            self.stdout.write(self.style.WARNING(f"Anomalie trovate: {problemi}"))
        else:
            self.stdout.write(self.style.SUCCESS("Nessuna anomalia."))

    @staticmethod
    def _d(data) -> str:
        return f"{data:%d/%m/%Y}" if data else "—"

    def _sezione(self, titolo: str, righe: list[str], *, problema: bool = True) -> int:
        stile = self.style.WARNING if (righe and problema) else self.style.HTTP_INFO
        self.stdout.write("")
        self.stdout.write(stile(f"{titolo}: {len(righe)}"))
        mostrate = righe if self.limite <= 0 else righe[:self.limite]
        for riga in mostrate:
            self.stdout.write(f"  - {riga}")
        if len(mostrate) < len(righe):
            self.stdout.write(f"  ... altre {len(righe) - len(mostrate)} (usa --righe 0)")
        return len(righe) if problema else 0
