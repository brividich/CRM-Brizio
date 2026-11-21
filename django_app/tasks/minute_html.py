"""Corpo HTML della minuta: sezioni leggibili invece di righe di testo con i trattini.

Solo tabelle e stili in linea (i client di posta ignorano <style>), stessa
palette e stessi mattoni delle altre mail del portale (core/email_utils):
pill di stato, card con barra laterale, tabella dei fatti. Ogni testo che
arriva dagli utenti è escapato. La versione testo e il PDF restano in
minute_email.py e usano le stesse fonti.
"""
from __future__ import annotations

import html

from core.email_utils import email_badge

TESTO = "#182232"
GRIGIO = "#64748b"
CHIARO = "#94a3b8"
BORDO = "#e2e8f0"
FONDO = "#f8fafc"
BLU = "#1f5c91"
VERDE = "#15803d"
ARANCIO = "#c2410c"


def _e(valore) -> str:
    return html.escape(str(valore or ""))


def _data(d, fmt: str = "%d/%m/%Y") -> str:
    try:
        return d.strftime(fmt) if d else ""
    except Exception:
        return str(d or "")


GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def _giorno(d) -> str:
    try:
        return f"{GIORNI[d.weekday()].capitalize()} {d:%d/%m/%Y}"
    except Exception:
        return _data(d)


def _nome(user) -> str:
    if not user:
        return ""
    return user.get_full_name() or user.get_username()


def _sezione(titolo: str, contenuto: str, *, conta: int | None = None, colore: str = BLU) -> str:
    """Intestazione di sezione (etichetta maiuscola con filetto colorato) + contenuto."""
    if not contenuto:
        return ""
    numero = (
        f'<span style="display:inline-block;margin-left:8px;padding:1px 8px;border-radius:999px;'
        f'background:#eef2f7;color:{GRIGIO};font-size:11px;font-weight:700;">{conta}</span>'
        if conta else ""
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;margin:26px 0 10px;">'
        f'<tr><td style="border-left:4px solid {colore};padding:2px 0 2px 10px;font-size:12px;'
        f'font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:{TESTO};">'
        f'{_e(titolo)}{numero}</td></tr></table>' + contenuto
    )


def _pill(testo: str, sfondo: str, colore: str, *, barrata: bool = False) -> str:
    deco = "text-decoration:line-through;" if barrata else ""
    return (
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 11px;border-radius:999px;'
        f'background:{sfondo};color:{colore};font-size:13px;font-weight:600;{deco}">{_e(testo)}</span>'
    )


# ── Testata ─────────────────────────────────────────────────────────────────
def _testata(meeting) -> str:
    titolo = (meeting.titolo or "").strip() or f"Incontro {meeting.numero}"
    quando = " · ".join(x for x in (_giorno(meeting.data) if meeting.data else "", _data(meeting.ora, "%H:%M")) if x)
    dove = (meeting.luogo or "").strip()
    if getattr(meeting, "sala_id", None) and getattr(meeting, "sala", None):
        dove = dove or str(meeting.sala)
    stato = []
    if getattr(meeting, "minuta_chiusa", False):
        firma = _nome(meeting.minuta_chiusa_da)
        stato.append(email_badge(
            f"Approvata il {_data(meeting.minuta_chiusa_at)}" + (f" da {firma}" if firma else ""), "success"))
    else:
        stato.append(email_badge(meeting.get_stato_display(), "info"))
    righe = [
        f'<div style="font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:{GRIGIO};">'
        f'Minuta · {_e(getattr(meeting.project, "name", ""))}</div>',
        f'<div style="margin-top:4px;font-size:20px;font-weight:800;color:{TESTO};line-height:1.3;">'
        f'Incontro {meeting.numero} — {_e(titolo)}</div>',
        f'<div style="margin-top:6px;font-size:14px;color:{GRIGIO};">'
        + " &nbsp;·&nbsp; ".join(_e(x) for x in (quando, dove) if x) + '</div>',
        f'<div style="margin-top:10px;">{"".join(stato)}</div>',
    ]
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;background:{FONDO};border:1px solid {BORDO};border-radius:12px;">'
        f'<tr><td style="padding:16px 18px;">{"".join(righe)}</td></tr></table>'
    )


# ── Presenze ────────────────────────────────────────────────────────────────
def _presenze(meeting) -> str:
    if getattr(meeting, "presenze_registrate", False):
        presenti = [_nome(u) for u in meeting.presenti_utenti.all()] + list(meeting.get_presenti_email_list())
        assenti = [_nome(u) for u in meeting.assenti_utenti] + list(meeting.assenti_email)
        corpo = "".join(_pill(n, "#dcfce7", "#166534") for n in presenti)
        if assenti:
            corpo += (f'<div style="margin:6px 0 4px;font-size:12px;color:{GRIGIO};">Assenti</div>'
                      + "".join(_pill(n, "#f1f5f9", CHIARO, barrata=True) for n in assenti))
        return _sezione("Presenti", corpo, conta=len(presenti), colore=VERDE)
    nomi = [_nome(u) for u in meeting.partecipanti_utenti.all()] + [
        r.strip() for r in (meeting.partecipanti_email_extra or "").splitlines() if r.strip()
    ]
    return _sezione("Partecipanti", "".join(_pill(n, "#eef2f7", TESTO) for n in nomi), conta=len(nomi))


# ── Ordine del giorno e verbale ─────────────────────────────────────────────
def _ordine_del_giorno(meeting) -> str:
    items = [i for i in (meeting.agenda_items or []) if isinstance(i, dict) and str(i.get("titolo", "")).strip()]
    if not items:
        return ""
    righe = []
    for n, item in enumerate(items, start=1):
        fatto = bool(item.get("done"))
        cerchio = (
            f'<div style="width:26px;height:26px;line-height:26px;border-radius:13px;text-align:center;'
            f'font-size:13px;font-weight:800;color:#fff;background:{VERDE if fatto else CHIARO};">{n}</div>'
        )
        stato = email_badge("Trattato", "success") if fatto else email_badge("Non trattato", "warning")
        dettagli = ""
        nota = str(item.get("nota", "")).strip()
        if nota:
            dettagli += (f'<div style="margin-top:6px;font-size:14px;color:#334155;line-height:1.6;">'
                         f'{_e(nota).replace(chr(10), "<br>")}</div>')
        for campo in item.get("custom_fields") or []:
            if isinstance(campo, dict) and str(campo.get("label", "")).strip() and str(campo.get("value", "")).strip():
                dettagli += (f'<div style="margin-top:3px;font-size:12px;color:{GRIGIO};">'
                             f'{_e(campo["label"])}: <strong style="color:#334155;">{_e(campo["value"])}</strong></div>')
        righe.append(
            f'<tr><td style="width:38px;vertical-align:top;padding:12px 0 12px 14px;">{cerchio}</td>'
            f'<td style="vertical-align:top;padding:12px 14px 12px 8px;border-bottom:1px solid {BORDO};">'
            f'<div style="font-size:15px;font-weight:700;color:{TESTO};">{_e(item.get("titolo"))} '
            f'<span style="margin-left:6px;">{stato}</span></div>{dettagli}</td></tr>'
        )
    corpo = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;border:1px solid {BORDO};border-radius:12px;">'
        + "".join(righe) + '</table>'
    )
    trattati = sum(1 for i in items if i.get("done"))
    return _sezione(f"Ordine del giorno e verbale · {trattati} su {len(items)} trattati", corpo)


def _note_generali(testo: str) -> str:
    testo = (testo or "").strip()
    if not testo:
        return ""
    return _sezione("Note generali", (
        f'<div style="font-size:14px;color:#334155;line-height:1.6;background:{FONDO};'
        f'border:1px solid {BORDO};border-radius:10px;padding:12px 14px;">{_e(testo).replace(chr(10), "<br>")}</div>'
    ))


# ── Decisioni e problemi ────────────────────────────────────────────────────
def _card(titolo: str, *, accento: str, badge: str = "", sotto: str = "", nota: str = "") -> str:
    parti = [f'<div style="font-size:15px;font-weight:700;color:{TESTO};line-height:1.4;">{_e(titolo)}'
             + (f' <span style="margin-left:6px;">{badge}</span>' if badge else "") + '</div>']
    if sotto:
        parti.append(f'<div style="margin-top:3px;font-size:13px;color:{GRIGIO};">{_e(sotto)}</div>')
    if nota:
        parti.append(f'<div style="margin-top:6px;font-size:13px;color:#334155;line-height:1.55;">'
                     f'{_e(nota).replace(chr(10), "<br>")}</div>')
    return (
        '<tr><td style="padding:0 0 10px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;background:{FONDO};border:1px solid {BORDO};border-radius:10px;">'
        f'<tr><td style="width:5px;background:{accento};border-radius:10px 0 0 10px;">&nbsp;</td>'
        f'<td style="padding:12px 14px;">{"".join(parti)}</td></tr></table></td></tr>'
    )


def _elenco_card(cards: list[str]) -> str:
    if not cards:
        return ""
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="width:100%;border-collapse:collapse;">' + "".join(cards) + '</table>')


def _decisioni(meeting) -> str:
    toni = {"ALTO": "danger", "MEDIO": "warning", "BASSO": "neutral"}
    cards = []
    for d in meeting.decisions.select_related("decisa_da").order_by("created_at", "id"):
        cards.append(_card(
            d.testo, accento=VERDE,
            badge=email_badge(f"Impatto {d.get_impatto_display().lower()}", toni.get(str(d.impatto).upper(), "neutral")),
            sotto=f"Decisa da {_nome(d.decisa_da)}" if d.decisa_da_id else "",
            nota=d.dettaglio or "",
        ))
    return _sezione("Decisioni", _elenco_card(cards), conta=len(cards), colore=VERDE)


def _problemi(meeting) -> str:
    from django.db.models import Q

    from tasks.models import MeetingIssue

    qs = (MeetingIssue.objects.filter(Q(source_meeting=meeting) | Q(resolution_meeting=meeting))
          .select_related("assigned_to").distinct().order_by("status", "due_date", "id"))
    cards = []
    for p in qs:
        aperto = str(p.status).upper() == "OPEN"
        sotto = " · ".join(x for x in (_nome(p.assigned_to), f"entro {_data(p.due_date)}" if p.due_date else "") if x)
        nota = (p.description or "").strip()
        if p.resolution_note:
            nota = (nota + "\n" if nota else "") + f"Risoluzione: {p.resolution_note.strip()}"
        cards.append(_card(p.title, accento=ARANCIO if aperto else VERDE,
                           badge=email_badge(p.get_status_display(), "warning" if aperto else "success"),
                           sotto=sotto, nota=nota))
    if not cards and (meeting.problemi_aperti or "").strip():
        return _sezione("Problemi", f'<div style="font-size:14px;color:#334155;line-height:1.6;">'
                                    f'{_e(meeting.problemi_aperti.strip()).replace(chr(10), "<br>")}</div>')
    return _sezione("Problemi", _elenco_card(cards), conta=len(cards), colore=ARANCIO)


# ── Attività ────────────────────────────────────────────────────────────────
def _riga_attivita(titolo: str, *, chi: str, entro, stato: str, tono: str, nota: str = "") -> str:
    nota_html = (f'<div style="margin-top:5px;font-size:13px;color:{GRIGIO};line-height:1.5;">'
                 f'{_e(nota).replace(chr(10), "<br>")}</div>') if nota else ""
    chi_html = (f'<strong style="color:#334155;">{_e(chi)}</strong>' if chi
                else f'<span style="color:{ARANCIO};font-weight:700;">Responsabile da decidere</span>')
    entro_html = f' &nbsp;·&nbsp; entro <strong style="color:#334155;">{_e(_data(entro))}</strong>' if entro else ""
    return (
        f'<tr><td style="padding:12px 14px;border-bottom:1px solid {BORDO};vertical-align:top;">'
        f'<div style="font-size:14px;font-weight:700;color:{TESTO};line-height:1.4;">{_e(titolo)}</div>'
        f'<div style="margin-top:3px;font-size:13px;color:{GRIGIO};">{chi_html}{entro_html}</div>{nota_html}</td>'
        f'<td style="padding:12px 14px;border-bottom:1px solid {BORDO};vertical-align:top;text-align:right;white-space:nowrap;width:1%;">'
        f'{email_badge(stato, tono)}</td></tr>'
    )


def _attivita(meeting) -> str:
    from tasks.models import MeetingActionItem, TaskStatus
    from tasks.services.kickoff_avvio import attivita_dell_incontro, nota_attivita

    toni = {TaskStatus.TODO: "neutral", TaskStatus.IN_PROGRESS: "info", TaskStatus.DONE: "success", TaskStatus.CANCELED: "neutral"}
    tasks = list(attivita_dell_incontro(meeting))
    righe = [
        _riga_attivita(t.title, chi=_nome(t.assigned_to), entro=t.due_date, stato=t.get_status_display(),
                       tono=toni.get(t.status, "neutral"), nota=nota_attivita(t))
        for t in tasks
    ]
    voci = (MeetingActionItem.objects.filter(source_meeting=meeting).exclude(linked_task_id__in=[t.pk for t in tasks])
            .select_related("assigned_to").order_by("status", "due_date", "id"))
    for a in voci:
        righe.append(_riga_attivita(a.title, chi=_nome(a.assigned_to), entro=a.due_date, stato=a.get_status_display(),
                                    tono="success" if a.is_done else "neutral", nota=a.description or ""))
    if not righe:
        testo = (meeting.next_steps or "").strip()
        return _sezione("Attività", (f'<div style="font-size:14px;color:#334155;line-height:1.6;">'
                                     f'{_e(testo).replace(chr(10), "<br>")}</div>') if testo else "")
    tabella = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:collapse;border:1px solid {BORDO};border-radius:12px;">'
        f'{"".join(righe)}</table>'
    )
    return _sezione("Attività", tabella, conta=len(righe))


def corpo_minuta(meeting, *, note_generali: str = "", testo_storico: list[tuple[str, str]] | None = None) -> str:
    """Frammento HTML della minuta (va dentro la cornice di send_hub_mail)."""
    parti = [_testata(meeting), _presenze(meeting)]
    if any(isinstance(i, dict) and str(i.get("titolo", "")).strip() for i in (meeting.agenda_items or [])):
        parti += [_ordine_del_giorno(meeting), _note_generali(note_generali)]
    else:
        # Incontri storici senza punti strutturati: le due sezioni di testo libero.
        for titolo, testo in testo_storico or []:
            parti.append(_note_generali(testo).replace("Note generali", _e(titolo), 1) if testo else "")
    parti += [_decisioni(meeting), _problemi(meeting), _attivita(meeting)]
    return "".join(p for p in parti if p)
