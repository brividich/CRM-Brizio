"""MOD.128 MPQ — F5: propagazione stato abilitazioni → timbri fisici.

Quando un'abilitazione persona×processo (MOD.128) **non è più operativa**
(revocata/sospesa/dismessa, oppure il processo qualificato è scaduto) il timbro
fisico collegato (``timbri.RegistroTimbro.abilitazione_processo``) viene
**sospeso automaticamente** (MT CN 06 §10.3: con data di sospensione). Al ritorno
operativo l'auto-sospensione viene revocata. È **entrambe** le cose richieste:
(a) sospensione del timbro **e** (b) notifica MSM/Qualità.

Speculare a ``skillmatrix_continuita.applica_sospensioni``: idempotente, con un
MARKER in ``sospeso_riferimento`` che distingue le sospensioni **automatiche**
(riattivabili da qui) da quelle **manuali** (mai toccate). I modelli ``timbri``
sono importati **localmente** dentro le funzioni (cross-module, come da regola
del progetto). La notifica riusa l'infrastruttura email esistente
(``send_hub_mail`` + ``get_reminder_recipients``), non ne crea una nuova.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..models_mpq import AbilitazioneProcesso

# Config key per i destinatari del digest MSM (cascata SiteConfig → ADMINS → superuser).
MSM_CONFIG_KEY = "mpq_msm_reminder_emails"

# Marcatore in ``sospeso_riferimento``: distingue le sospensioni automatiche
# (riattivabili) da quelle manuali/di altra origine (che NON vanno riattivate).
MARKER = "[mpq-abilitazione]"


def _abilitazione_operativa(ab, oggi) -> bool:
    """True se l'abilitazione è operativa (attiva e processo non scaduto)."""
    if ab is None:
        return True
    if ab.stato != AbilitazioneProcesso.STATO_ATTIVA:
        return False
    scad = ab.processo.scadenza_effettiva if ab.processo_id else None
    if scad is not None and scad < oggi:
        return False
    return True


def _motivo(ab, oggi) -> str:
    """Motivo leggibile della sospensione automatica."""
    labels = {
        AbilitazioneProcesso.STATO_REVOCATA: "Abilitazione revocata",
        AbilitazioneProcesso.STATO_SOSPESA: "Abilitazione sospesa",
        AbilitazioneProcesso.STATO_DISMESSA: "Abilitazione dismessa",
    }
    if ab.stato in labels:
        return labels[ab.stato]
    scad = ab.processo.scadenza_effettiva if ab.processo_id else None
    if scad is not None and scad < oggi:
        return f"Processo qualificato scaduto il {scad:%d-%m-%Y}"
    return "Abilitazione non operativa"


def propaga_sospensioni(*, oggi=None, apply: bool = True) -> dict:
    """Sospende i timbri collegati ad abilitazioni non operative, riattiva quelli
    tornati operativi (solo le auto-sospensioni). Idempotente.

    Con ``apply=False`` calcola soltanto il piano (nessuna scrittura). Ritorna
    conteggi + ``nuovi_sospesi`` (pk dei timbri appena sospesi, per la notifica).
    """
    from timbri.models import RegistroTimbro

    oggi = oggi or timezone.localdate()
    stats = {"apply": apply, "sospesi": 0, "riattivati": 0, "nuovi_sospesi": []}

    qs = (
        RegistroTimbro.objects
        .select_related("abilitazione_processo", "abilitazione_processo__processo")
        .filter(abilitazione_processo__isnull=False)
    )

    with transaction.atomic():
        for t in qs:
            ab = t.abilitazione_processo
            operativa = _abilitazione_operativa(ab, oggi)

            if not operativa:
                if t.is_archived or t.is_sospeso:
                    continue
                stats["sospesi"] += 1
                stats["nuovi_sospesi"].append(t.pk)
                if apply:
                    t.is_sospeso = True
                    t.is_attivo = False
                    t.sospeso_dal = oggi
                    t.sospeso_motivo = _motivo(ab, oggi)[:255]
                    t.sospeso_riferimento = MARKER
                    t.save(update_fields=[
                        "is_sospeso", "is_attivo", "sospeso_dal",
                        "sospeso_motivo", "sospeso_riferimento", "updated_at",
                    ])
            else:
                # Riattiva SOLO se l'avevamo sospesa noi (MARKER presente).
                if t.is_sospeso and MARKER in (t.sospeso_riferimento or ""):
                    stats["riattivati"] += 1
                    if apply:
                        t.is_sospeso = False
                        t.is_attivo = True
                        t.sospeso_dal = None
                        t.sospeso_al = None
                        t.sospeso_motivo = ""
                        t.sospeso_riferimento = ""
                        t.save(update_fields=[
                            "is_sospeso", "is_attivo", "sospeso_dal", "sospeso_al",
                            "sospeso_motivo", "sospeso_riferimento", "updated_at",
                        ])
    return stats


def notifica_msm_sospensioni(pks, *, oggi=None, override=None, fail_silently: bool = True) -> int:
    """Notifica MSM/Qualità dei timbri sospesi automaticamente (digest email).

    Riusa ``get_reminder_recipients`` (cascata SiteConfig → ADMINS → superuser) e
    ``send_hub_mail``. Ritorna il numero di email inviate (0 se nessun timbro o
    nessun destinatario). Fail-safe di default.
    """
    if not pks:
        return 0
    from timbri.models import RegistroTimbro
    from core.email_utils import send_hub_mail
    from .reminders import get_reminder_recipients

    recipients = get_reminder_recipients(MSM_CONFIG_KEY, override=override)
    if not recipients:
        return 0

    oggi = oggi or timezone.localdate()
    timbri = list(
        RegistroTimbro.objects
        .select_related("operatore", "abilitazione_processo", "abilitazione_processo__processo")
        .filter(pk__in=list(pks))
    )
    if not timbri:
        return 0

    righe = []
    for t in timbri:
        ab = t.abilitazione_processo
        processo = ab.processo.nome if (ab and ab.processo_id) else "—"
        righe.append(
            f"<tr>"
            f"<td style='padding:8px 12px;border-top:1px solid #e2e8f0;'>{t.operatore.full_name}</td>"
            f"<td style='padding:8px 12px;border-top:1px solid #e2e8f0;'>{t.codice_timbro or '—'}</td>"
            f"<td style='padding:8px 12px;border-top:1px solid #e2e8f0;'>{processo}</td>"
            f"<td style='padding:8px 12px;border-top:1px solid #e2e8f0;'>{t.sospeso_motivo}</td>"
            f"</tr>"
        )
    tabella = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;border-radius:10px;overflow:hidden;'>"
        "<tr style='background:#eef3f8;'>"
        "<th style='text-align:left;padding:9px 12px;color:#64748b;font-size:12px;'>Operatore</th>"
        "<th style='text-align:left;padding:9px 12px;color:#64748b;font-size:12px;'>Timbro</th>"
        "<th style='text-align:left;padding:9px 12px;color:#64748b;font-size:12px;'>Processo qualificato</th>"
        "<th style='text-align:left;padding:9px 12px;color:#64748b;font-size:12px;'>Motivo</th>"
        "</tr>"
        + "".join(righe) +
        "</table>"
    )
    testo = (
        f"Sono stati sospesi automaticamente {len(timbri)} timbri collegati ad "
        f"abilitazioni MOD.128 non più operative (aggiornamento del {oggi:%d-%m-%Y}). "
        f"Verificare e regolarizzare secondo MT CN 06 §10.3."
    )
    return send_hub_mail(
        subject=f"[MOD.128] Timbri sospesi automaticamente ({len(timbri)})",
        body_text=testo,
        recipients=recipients,
        title="Timbri sospesi — MOD.128",
        email_type="Qualità",
        badge="MOD.128",
        section_label="Processi qualificati",
        body_html_fragment=f"<p style='margin:0 0 14px;'>{testo}</p>{tabella}",
        fail_silently=fail_silently,
    )
