"""MOD.128 — avviso settimanale: persone e macchine qualificate da sistemare.

Persone (abilitazioni attive) non qualificate o con scadenza entro 60 giorni e
macchine non operative o in scadenza, per tutti i processi attivi. Destinatari:
gli stessi dei timbri sospesi MOD.128 (``mpq_msm_reminder_emails``).
"""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from automazioni.managed_flows import event_flow

GIORNI = 60


def raccogli(*, giorni=GIORNI, oggi=None) -> dict:
    from .mpq_macchine import macchine_in_scadenza
    from .mpq_persone import persone_in_scadenza

    oggi = oggi or timezone.localdate()
    return {
        "persone": persone_in_scadenza(giorni=giorni, oggi=oggi),
        "macchine": macchine_in_scadenza(giorni=giorni, oggi=oggi),
    }


def _nome(ab, nomi):
    return ab.nominativo_esterno or nomi.get(ab.legacy_anagrafica_id) or f"#{ab.legacy_anagrafica_id}"


@event_flow("mpq_qualifiche_scadenze", skipped_result=0)
def notifica_scadenze(*, override=None, fail_silently: bool = True, giorni=GIORNI) -> int:
    from core.email_utils import send_hub_mail

    from ..views_mpq import _nomi_map
    from .mpq_timbri import MSM_CONFIG_KEY
    from .reminders import get_reminder_recipients

    recipients = get_reminder_recipients(MSM_CONFIG_KEY, override=override)
    if not recipients:
        return 0
    dati = raccogli(giorni=giorni)
    n = len(dati["persone"]) + len(dati["macchine"])
    if not n:
        return 0
    nomi = _nomi_map([r["abilitazione"].legacy_anagrafica_id for r in dati["persone"]])
    cella = "padding:8px 12px;border-top:1px solid #e2e8f0;"
    intest = "text-align:left;padding:9px 12px;color:#64748b;font-size:12px;"
    righe = []
    for r in dati["persone"]:
        st = r["stato"]
        cosa = ", ".join(v["nome"] for v in st["voci"]
                         if v.get("bloccante", True) and v["stato"] in ("scaduto", "mancante", "in_scadenza"))
        url = reverse("anagrafica:mpq_processo_detail", args=[r["processo"].pk]) + "#persone"
        righe.append(
            f"<tr><td style='{cella}'>Persona</td><td style='{cella}'>{escape(_nome(r['abilitazione'], nomi))}</td>"
            f"<td style='{cella}'>{escape(r['processo'].nome)}</td>"
            f"<td style='{cella}'><strong>{escape(st['label'])}</strong>"
            + (f" · scade {st['scadenza']:%d-%m-%Y}" if st["scadenza"] else "")
            + (f"<br>{escape(cosa)}" if cosa else "")
            + f"</td><td style='{cella}'><a href='{escape(url)}'>Apri</a></td></tr>"
        )
    for r in dati["macchine"]:
        qm = r["qualifica"]
        url = reverse("anagrafica:mpq_qualifica_macchina", args=[qm.pk])
        righe.append(
            f"<tr><td style='{cella}'>Macchina</td>"
            f"<td style='{cella}'>{escape(qm.asset.asset_tag)} — {escape(qm.asset.name)}</td>"
            f"<td style='{cella}'>{escape(qm.processo.nome)}</td>"
            f"<td style='{cella}'><strong>{escape(r['stato']['label'])}</strong></td>"
            f"<td style='{cella}'><a href='{escape(url)}'>Apri</a></td></tr>"
        )
    tabella = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;'>"
        f"<tr style='background:#eef3f8;'><th style='{intest}'></th><th style='{intest}'>Chi / cosa</th>"
        f"<th style='{intest}'>Processo</th><th style='{intest}'>Stato</th><th style='{intest}'></th></tr>"
        + "".join(righe) + "</table>"
    )
    testo = (f"{len(dati['persone'])} persone e {len(dati['macchine'])} macchine dei processi qualificati "
             f"non sono in regola o scadono entro {giorni} giorni.")
    return send_hub_mail(
        subject=f"[MOD.128] Persone e macchine qualificate da sistemare ({n})",
        body_text=testo, recipients=recipients,
        title="Processi qualificati — scadenze", email_type="Qualità", badge="MOD.128",
        section_label="Processi qualificati",
        body_html_fragment=f"<p style='margin:0 0 14px;'>{escape(testo)}</p>{tabella}",
        fail_silently=fail_silently,
    )
