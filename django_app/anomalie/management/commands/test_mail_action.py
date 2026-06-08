"""
Management command: test_mail_action

Testa il sistema mail-action anomalie end-to-end senza toccare dati reali:
1. Crea un token AnomaliaMailActionToken con anomalie sintetiche.
2. Costruisce l'email HTML (con 1, 3 o N anomalie sintetiche).
3. Invia l'email al destinatario specificato (default: usa EMAIL_BACKEND configurato).
4. Stampa il link di test e il token.

Non modifica anomalie reali, non attiva automazioni reali, usa dati sintetici.

Utilizzo:
    python manage.py test_mail_action --to cc@esempio.it
    python manage.py test_mail_action --to cc@esempio.it --n 5 --action prendi_in_carico
    python manage.py test_mail_action --to cc@esempio.it --dry-run
    python manage.py test_mail_action --to cc@esempio.it --expires 24
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


_AZIONI_VALIDE = ["prendi_in_carico", "approva", "respingi", "richiedi_modifica", "chiudi", "visualizza"]

_ANOMALIE_SINTETICHE = [
    {"id": 9001, "descrizione": "Diametro foro fuori tolleranza +0.15 mm", "avanzamento": "In attesa", "seriale": "SN-TEST-001", "note_capocommessa": ""},
    {"id": 9002, "descrizione": "Rugosità superficie Ra > 3.2 — rilavorazione necessaria", "avanzamento": "In attesa", "seriale": "SN-TEST-002", "note_capocommessa": "Verificare con CMM prima della rilavorazione"},
    {"id": 9003, "descrizione": "Mancanza di trattamento superficiale su zona B", "avanzamento": "In attesa", "seriale": "SN-TEST-003", "note_capocommessa": ""},
    {"id": 9004, "descrizione": "Marcatura CE assente sul lotto 2406", "avanzamento": "In attesa", "seriale": "SN-TEST-004", "note_capocommessa": ""},
    {"id": 9005, "descrizione": "Saldatura cricca visibile lato flangia", "avanzamento": "In attesa", "seriale": "SN-TEST-005", "note_capocommessa": "Bloccare il lotto"},
    {"id": 9006, "descrizione": "Spessore parete inferiore al minimo di progetto", "avanzamento": "In attesa", "seriale": "SN-TEST-006", "note_capocommessa": ""},
    {"id": 9007, "descrizione": "Coppia di serraggio non conforme — documentazione mancante", "avanzamento": "In attesa", "seriale": "SN-TEST-007", "note_capocommessa": ""},
    {"id": 9008, "descrizione": "Difetto di planarità > 0.05 mm su piano di appoggio", "avanzamento": "In attesa", "seriale": "SN-TEST-008", "note_capocommessa": ""},
    {"id": 9009, "descrizione": "Codice materiale errato sul cartellino (Ti-6Al-4V vs Al 7075)", "avanzamento": "In attesa", "seriale": "SN-TEST-009", "note_capocommessa": ""},
    {"id": 9010, "descrizione": "Finitura cromatura parziale — 20% area scoperta", "avanzamento": "In attesa", "seriale": "SN-TEST-010", "note_capocommessa": ""},
    {"id": 9011, "descrizione": "Filettatura M8 strappata — non recuperabile", "avanzamento": "In attesa", "seriale": "SN-TEST-011", "note_capocommessa": "Scarto definitivo"},
    {"id": 9012, "descrizione": "Posizione foro sfasata di 2 mm rispetto al disegno", "avanzamento": "In attesa", "seriale": "SN-TEST-012", "note_capocommessa": ""},
]


class Command(BaseCommand):
    help = "Testa il sistema mail-action anomalie: crea token sintetico e invia email di test."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            required=True,
            help="Email del destinatario di test (es. cc@costruzioninovicrom.it).",
        )
        parser.add_argument(
            "--n",
            type=int,
            default=3,
            help="Numero di anomalie sintetiche da includere nell'email (1-12, default 3).",
        )
        parser.add_argument(
            "--action",
            default="visualizza",
            choices=_AZIONI_VALIDE,
            help="Azione da testare (default: visualizza).",
        )
        parser.add_argument(
            "--op-id",
            default="OP-TEST-2026-001",
            help="Codice OP sintetico da mostrare nell'email (default: OP-TEST-2026-001).",
        )
        parser.add_argument(
            "--expires",
            type=int,
            default=48,
            help="Ore di validità del token (default 48).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Costruisce l'email e il token ma non li invia né li persiste a DB.",
        )
        parser.add_argument(
            "--site-url",
            default="",
            help="Override SITE_URL per il link nell'email (es. https://hub.example.local).",
        )
        parser.add_argument(
            "--display",
            default="Capocommessa Test",
            help="Nome visualizzato del destinatario nell'email (default: Capocommessa Test).",
        )

    def handle(self, *args, **options):
        from django.conf import settings as _s

        to_email: str = options["to"].strip()
        n: int = max(1, min(12, options["n"]))
        action: str = options["action"]
        op_id: str = options["op_id"].strip()
        expires_hours: int = max(1, options["expires"])
        dry_run: bool = bool(options.get("dry_run"))
        recipient_display: str = options["display"].strip()

        # Risolvi SITE_URL: --site-url > settings.SITE_URL > errore esplicito
        site_url: str = options["site_url"].strip()
        if not site_url:
            site_url = str(getattr(_s, "SITE_URL", "") or "").rstrip("/")
        if not site_url:
            raise CommandError(
                "SITE_URL non configurato. Usare --site-url https://hub.costruzioninovicrom.it "
                "oppure impostare SITE_URL nel file .env."
            )
        site_url = site_url.rstrip("/")

        anomalie_rows = _ANOMALIE_SINTETICHE[:n]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'[DRY-RUN] ' if dry_run else ''}Test mail-action anomalie"
        ))
        self.stdout.write(f"  Destinatario  : {to_email}")
        self.stdout.write(f"  Nome display  : {recipient_display}")
        self.stdout.write(f"  OP sintetico  : {op_id}")
        ids_str = ", ".join(f"#{a['id']}" for a in anomalie_rows)
        self.stdout.write(f"  Anomalie      : {n} ({ids_str})")
        self.stdout.write(f"  Azione        : {action}")
        self.stdout.write(f"  Scadenza token: {expires_hours}h")
        self.stdout.write("")

        from anomalie.mail_action_service import build_anomalie_action_email, send_anomalie_action_email

        if dry_run:
            # Solo rendering — niente DB, niente SMTP
            from django.utils import timezone
            from datetime import timedelta
            from anomalie.mail_action_models import AnomaliaMailActionToken

            fake_token = "DRY-RUN-TOKEN-NON-PERSISTITO-xxxxxxxxxxxxxxxxxxx"
            expires_at = timezone.now() + timedelta(hours=expires_hours)
            subject, body_text, body_html = build_anomalie_action_email(
                recipient_email=to_email,
                recipient_display=recipient_display,
                op_id=op_id,
                op_nominativo="Lavorazione flangia prova — SINTETICO",
                anomalie_rows=anomalie_rows,
                action=action,
                token_str=fake_token,
                expires_at=expires_at,
                site_url=site_url,
            )
            self.stdout.write(self.style.SUCCESS("[DRY-RUN] Rendering email OK"))
            self.stdout.write(f"  Subject : {subject}")
            self.stdout.write(f"  HTML len: {len(body_html)} chars")
            self.stdout.write(f"  Text len: {len(body_text)} chars")
            self.stdout.write("")
            self.stdout.write("  Link simulato (token fittizio, non valido):")
            self.stdout.write(f"  ->{site_url}/gestione-anomalie/mail-action/{fake_token}/")
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Dry-run completato. Nessun dato scritto a DB, nessuna email inviata."))
            return

        # Invio reale
        try:
            token_obj = send_anomalie_action_email(
                recipient_email=to_email,
                recipient_display=recipient_display,
                op_id=op_id,
                op_nominativo="Lavorazione flangia prova — SINTETICO",
                anomalie_rows=anomalie_rows,
                action=action,
                expires_hours=expires_hours,
                source_automation="test_mail_action_command",
                site_url=site_url,
            )
        except Exception as exc:
            raise CommandError(f"Invio email fallito: {exc}") from exc

        action_url = f"{site_url}/gestione-anomalie/mail-action/{token_obj.token}/"
        done_url = f"{site_url}/gestione-anomalie/mail-action/{token_obj.token}/fatto/"

        self.stdout.write(self.style.SUCCESS("Email inviata con successo."))
        self.stdout.write("")
        self.stdout.write(f"  Token ID   : {token_obj.pk}")
        self.stdout.write(f"  Token      : {token_obj.token}")
        self.stdout.write(f"  Scade il   : {token_obj.expires_at.strftime('%d/%m/%Y %H:%M')}")
        self.stdout.write("")
        self.stdout.write("  Link azione (da aprire dopo login nel browser):")
        self.stdout.write(f"  ->{action_url}")
        self.stdout.write("")
        self.stdout.write("  Link pagina 'fatto' (dopo conferma):")
        self.stdout.write(f"  ->{done_url}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "NOTA: le anomalie sintetiche (ID 9001+) non esistono nel DB legacy.\n"
            "  La pagina portale mostrerà 'Nessuna anomalia trovata' nel corpo — comportamento atteso.\n"
            "  Per un test completo usare ID anomalie reali con --n 1 e un ID esistente nel package service."
        ))
