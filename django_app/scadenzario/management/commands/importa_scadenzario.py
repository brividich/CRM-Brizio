"""Importa il vecchio scadenzario (Flask + MySQL ``scadenziario``) nelle scadenze generiche.

    python manage.py importa_scadenzario                # prova: conta e mostra, non scrive
    python manage.py importa_scadenzario --apply        # scrive
    python manage.py importa_scadenzario --apply --con-avvisi   # anche il registro degli avvisi

Rilanciabile: categorie e attività si riconoscono dal vecchio id (``legacy_id``) e
non si duplicano. Quelle già importate restano come sono, perché nel portale
possono essere state cambiate (rinnovi, destinatari): solo con ``--aggiorna``
vengono riscritte con i dati del vecchio scadenzario. Gli avvisi importati si
riconoscono da (attività, data, esito) e non si ripetono.

Connessione: ``--host``/``--port``/``--database``/``--user``; la password solo
dalla variabile d'ambiente ``SCADENZARIO_DB_PASSWORD`` (mai da riga di comando).
Legge in sola lettura (``SET SESSION TRANSACTION READ ONLY``).
"""
from __future__ import annotations

import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


def _aware(valore):
    if valore is None:
        return None
    if isinstance(valore, datetime) and timezone.is_naive(valore):
        # Il vecchio scadenzario salvava sent_at con datetime.utcnow().
        from datetime import timezone as dt_tz

        return valore.replace(tzinfo=dt_tz.utc)
    return valore


class Command(BaseCommand):
    help = "Importa categorie, attività (e facoltativamente avvisi) dal vecchio scadenzario MySQL."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="10.0.0.7")
        parser.add_argument("--port", type=int, default=3306)
        parser.add_argument("--database", default="scadenziario")
        parser.add_argument("--user", default="hub_readonly")
        parser.add_argument("--apply", action="store_true", help="Scrive nel database dell'HUB (senza: solo prova).")
        parser.add_argument("--con-avvisi", action="store_true", help="Importa anche alert_logs.")
        parser.add_argument("--aggiorna", action="store_true",
                            help="Riscrive anche categorie e attività già importate, perdendo le modifiche fatte nel portale.")

    def _righe(self, conn, sql):
        with conn.cursor() as cur:
            cur.execute(sql)
            return list(cur.fetchall())

    def handle(self, *args, **opts):
        try:
            import pymysql
            import pymysql.cursors
        except ImportError as exc:  # pragma: no cover
            raise CommandError("PyMySQL non installato.") from exc
        password = os.environ.get("SCADENZARIO_DB_PASSWORD", "")
        try:
            conn = pymysql.connect(
                host=opts["host"], port=opts["port"], user=opts["user"], password=password,
                database=opts["database"], charset="utf8mb4", connect_timeout=10, read_timeout=60,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as exc:
            raise CommandError(f"Connessione a MySQL non riuscita: {exc.__class__.__name__}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
            famiglie = self._righe(conn, "SELECT id, name, description, alert_emails FROM families ORDER BY id")
            prodotti = self._righe(conn, "SELECT * FROM products ORDER BY id")
            avvisi = self._righe(conn, "SELECT id, product_id, sent_at, note FROM alert_logs ORDER BY id") if opts["con_avvisi"] else []
        finally:
            conn.close()

        self.stdout.write(f"Vecchio scadenzario: {len(famiglie)} categorie, {len(prodotti)} attività"
                          + (f", {len(avvisi)} avvisi" if opts["con_avvisi"] else ""))
        if not opts["apply"]:
            attive = sum(1 for p in prodotti if p.get("is_active", 1))
            con_scadenza = sum(1 for p in prodotti if p.get("expiry_date"))
            self.stdout.write(f"  attive {attive}, con scadenza {con_scadenza}")
            self.stdout.write(self.style.WARNING("Prova: nulla è stato scritto. Rilancia con --apply."))
            return

        with transaction.atomic():
            esito = self._scrivi(famiglie, prodotti, avvisi, aggiorna=opts["aggiorna"])
        self.stdout.write(self.style.SUCCESS(
            "Importati: categorie {cat_nuove} nuove / {cat_agg} aggiornate / {cat_ferme} lasciate come sono, "
            "attività {att_nuove} nuove / {att_agg} aggiornate / {att_ferme} lasciate come sono, "
            "avvisi {avvisi}.".format(**esito)
        ))

    def _scrivi(self, famiglie, prodotti, avvisi, *, aggiorna: bool = False) -> dict:
        from scadenzario.models import AvvisoInviato, CategoriaScadenza, ScadenzaGenerica

        esito = {"cat_nuove": 0, "cat_agg": 0, "cat_ferme": 0, "att_nuove": 0, "att_agg": 0, "att_ferme": 0, "avvisi": 0}
        categorie = {}
        for f in famiglie:
            nome = (f.get("name") or "").strip()[:150] or f"Categoria {f['id']}"
            cat = CategoriaScadenza.objects.filter(legacy_id=f["id"]).first()
            if cat is None:
                # Una categoria con lo stesso nome creata a mano nell'HUB: la si collega.
                cat = CategoriaScadenza.objects.filter(nome__iexact=nome, legacy_id__isnull=True).first()
            dati = {"nome": nome, "descrizione": f.get("description") or "", "email_avviso": f.get("alert_emails") or ""}
            if cat is None:
                cat = CategoriaScadenza.objects.create(legacy_id=f["id"], **dati)
                esito["cat_nuove"] += 1
            elif aggiorna or cat.legacy_id is None:
                for k, v in dati.items():
                    setattr(cat, k, v)
                cat.legacy_id = f["id"]
                cat.save()
                esito["cat_agg"] += 1
            else:
                esito["cat_ferme"] += 1
            categorie[f["id"]] = cat

        attivita = {}
        for p in prodotti:
            cat = categorie.get(p.get("family_id"))
            if cat is None:
                continue
            dati = {
                "categoria": cat,
                "titolo": (p.get("name") or "").strip()[:200] or f"Attività {p['id']}",
                "descrizione": p.get("description") or "",
                "ubicazione": (p.get("location") or "")[:200],
                "ultimo_controllo": p.get("last_check_date"),
                "validita_mesi": p.get("validita_mesi"),
                "data_scadenza": p.get("expiry_date"),
                "preavviso_giorni": p.get("preavviso_days"),
                "ripeti_ogni_giorni": p.get("repeat_interval_days"),
                "email_avviso": p.get("alert_emails") or "",
                "is_active": bool(p.get("is_active", 1)),
            }
            s = ScadenzaGenerica.objects.filter(legacy_id=p["id"]).first()
            if s is not None and not aggiorna:
                esito["att_ferme"] += 1
            else:
                s, creata = ScadenzaGenerica.objects.update_or_create(legacy_id=p["id"], defaults=dati)
                esito["att_nuove" if creata else "att_agg"] += 1
            attivita[p["id"]] = s

        for a in avvisi:
            s = attivita.get(a.get("product_id"))
            inviato = _aware(a.get("sent_at")) or timezone.now()
            nota = (a.get("note") or "")[:500]
            riepilogo = nota.lower().startswith(("riepilogo", "errore riepilogo"))
            filtro = {"importato": True, "inviato_il": inviato, "esito": nota}
            if s is not None:
                filtro["scadenza"] = s
            if AvvisoInviato.objects.filter(**filtro).exists():
                continue
            AvvisoInviato.objects.create(
                tipo=AvvisoInviato.TIPO_RIEPILOGO if (riepilogo or s is None) else AvvisoInviato.TIPO_ATTIVITA,
                scadenza=s, categoria=s.categoria if s else None, riuscito=not nota.lower().startswith(("error", "errore")),
                esito=nota, inviato_il=inviato, importato=True,
            )
            esito["avvisi"] += 1
        return esito
