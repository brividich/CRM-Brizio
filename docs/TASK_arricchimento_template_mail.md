# TASK (per un'altra sessione di Claude Code) — Arricchire i template email dei moduli allo standard "anomalie"

**Contesto scritto per una sessione che parte da zero.** Progetto: NOVICROM HUB (Django, `django_app/`).

## Obiettivo

Portare le email di **gestione_specifiche**, **anagrafica** (digest/reminder) e **monitoring**
allo stesso livello grafico delle email di **gestione anomalie**, che sono il riferimento.

## Scoperta chiave (NON ripartire da zero sul look)

Il layout grafico **esiste già ed è condiviso**: `core/email_utils.py::send_hub_mail()` genera
HTML+testo usando `core/templates/core/email/base_email.html`, che è **identico** allo stile
delle email di anomalie (header blu `#002b5c` + barra arancio `#ff6b00`, logo, card bianca
arrotondata, blocco eyebrow/titolo/intro, slot CTA, footer, responsive `@media`, Outlook-safe).

**Il gap NON è il look, è il CONTENUTO:**
- I moduli che usano `send_hub_mail` spesso passano **solo `body_text`** → escono come un
  paragrafo semplice dentro la bella cornice, senza tabelle/card/badge come anomalie.
- **gestione_specifiche** NON usa `send_hub_mail`: costruisce `EmailMultiAlternatives` a mano
  e (bug) mette l'HTML **anche nel corpo `text/plain`**.
- **monitoring** usa `send_mail` plain-text puro, fuori dal frame.

## Riferimenti da leggere prima

- **Gold standard**: `django_app/anomalie/templates/anomalie/email/anomalie_action_email.html`
  (+ `anomalie_update_confirmation.html`, `anomalie_escalation_resoconto.html`). Nota: card con
  indicatore laterale, badge di stato pill, tabella fatti, CTA, avviso scadenza, preheader nascosto.
- **Helper e frame condivisi**: `django_app/core/email_utils.py` — `send_hub_mail(...)`,
  `render_hub_email_html(...)`, `text_to_html(...)`; e `core/templates/core/email/base_email.html`
  (parametri: `title`, `section_label`/`email_type`, `intro`, `body_content` [HTML libero],
  `cta_buttons`, `expires_html`, `badge`, `preheader`, `footer_note`).

## Lavoro richiesto

### 1. Blocchi-contenuto riusabili (DRY) — `core/email_utils.py`
Aggiungi 2-3 helper Python che restituiscono frammenti HTML email-safe (tabelle + inline style),
da passare a `send_hub_mail(..., body_html_fragment=...)`. Suggeriti:
- `email_facts_table(rows: list[tuple[str, str]]) -> str` — tabella "etichetta → valore".
- `email_item_cards(items: list[dict]) -> str` — elenco di card con titolo, sottotitolo, badge
  di stato (verde/ambra/rosso) e note (come le card anomalie). Utile per liste di scadenze.
- `email_badge(text, tone)` / `email_cta(label, url)` — pill di stato e bottone CTA coerenti.
Tutti con stile **inline** (niente `<style>`/CSS esterno), palette del frame (`#002b5c`, `#ff6b00`,
grigi `#64748b`/`#e2e8f0`, verdi/ambra/rossi per gli stati). Testabili in isolamento.

### 2. Migrazione mittenti
- **gestione_specifiche** — `django_app/gestione_specifiche/notifiche_gs.py` (≈riga 68) e
  `gestione_specifiche/scadenze.py` (≈riga 78): sostituire la costruzione manuale di
  `EmailMultiAlternatives` con `send_hub_mail(...)` passando un `body_text` **pulito** (plain vero,
  niente HTML) e un `body_html_fragment` costruito con gli helper del punto 1. Elimina il bug
  dell'HTML nel corpo testo.
- **anagrafica** — i digest che già usano `send_hub_mail` ma passano solo testo:
  `management/commands/send_visite_mediche_digest.py`, `send_visite_expiry_reminders.py`,
  `send_idoneita_digest.py`, `send_formazione_session_reminders.py`, `send_formazione_audit_digest.py`,
  `send_contratti_expiry_reminders.py`. Aggiungere `body_html_fragment` con tabella/elenco card
  delle scadenze e badge di stato (scaduto/in scadenza), tenendo il `body_text` come riassunto.
- **monitoring** — `django_app/monitoring/health.py` (≈riga 649) e `monitoring/tasks.py` (≈riga 53):
  passare da `send_mail` plain a `send_hub_mail(...)` con `email_type="Monitoraggio"` e un
  `body_html_fragment` (stato servizi, badge). Mantenere il fail-safe esistente.

### 3. Vincoli (importanti)
- **Destinatari**: sempre `email_notifica` (mai il campo `email` legacy che è il login);
  usare `core.legacy_anagrafica.resolve_notification_email` / `anagrafica.services.reminders.get_reminder_recipients`.
- Email-client-safe: solo tabelle + inline style + accorgimenti `mso` per Outlook; responsive.
- Il **plain-text alternativo** deve restare leggibile (niente tag HTML grezzi nel testo).
- **Non toccare** le 3 email di anomalie (sono il riferimento, già a posto) né la parte "plumbing"
  del sistema notifiche (fatta a parte: from-email, console backend dev, fallback destinatario,
  logging notifiche non consegnate).

### 4. Qualità
- **TDD**: per gli helper, assert che l'HTML contenga i blocchi attesi; per i mittenti migrati,
  assert (via `locmem` email backend / `mail.outbox`) che l'HTML alternativo contenga le card/tabelle
  e che il `text/plain` **non** contenga `<` tag. Suite scoped per modulo
  (`... test gestione_specifiche` / `anagrafica.<modulo>` / `monitoring --settings=config.settings.test`).
- `manage.py check` pulito; **CHANGELOG.md** + eventuale README.
- Commit mirati per modulo (`git add` esplicito). ⚠️ Il working tree è **condiviso** con altre
  sessioni: verifica `git diff --cached` prima di ogni commit, non inglobare WIP altrui, niente file dati.

## Fuori scope
- Il ridisegno/dispatcher del sistema notifiche e i template di anomalie.
- Le notifiche in-app (canale separato dal frame email).
