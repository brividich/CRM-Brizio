"""Dossier PART 145: processo, attrezzature, personale, scadenze e situazioni aperte.

Una sola costruzione (``costruisci``) per pagina, Excel (un foglio per sezione) e PDF:
le tre uscite mostrano gli stessi dati. Il personale (dati MOD.128) compare solo a chi
ha il permesso di vedere i processi qualificati: senza, le sezioni lo omettono.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import timedelta
from html import escape

from django.db.models import Count, Min, Q
from django.utils import timezone

from .part145 import REGIME_PART145, attrezzature_processo

GIORNI_SCADENZE = 90

ESITI_IDONEITA = {"ok": "Idoneo", "warn": "In scadenza", "incompleto": "Incompleto", "ko": "Non idoneo",
                  "nessuno": "Nessun requisito"}


@dataclass
class Sezione:
    codice: str
    titolo: str
    intestazioni: list[str]
    righe: list[list] = field(default_factory=list)
    nota: str = ""
    vuoto: str = "Niente da segnalare."
    #: Id asset per riga (link alla scheda), allineato a ``righe``; vuoto = nessun link.
    asset_ids: list = field(default_factory=list)

    @property
    def righe_link(self):
        ids = self.asset_ids or [None] * len(self.righe)
        return list(zip(self.righe, ids))


def puo_vedere_personale(request) -> bool:
    """Il personale abilitato (dati MOD.128) solo a chi vede i processi qualificati."""
    try:
        from anagrafica.views_mpq import _check_mpq_permission

        return _check_mpq_permission(request)
    except Exception:
        return False


def _d(valore) -> str:
    return valore.strftime("%d/%m/%Y") if valore else ""


def _stato_scadenza(giorno, oggi) -> str:
    if giorno is None:
        return "Senza scadenza"
    if giorno < oggi:
        return "Scaduta"
    if giorno <= oggi + timedelta(days=30):
        return "Entro 30 giorni"
    return "Valida"


def _attrezzature():
    from ..models import Asset

    return (Asset.objects.filter(Q(part_145=True) | Q(processi_qualificati__regime=REGIME_PART145))
            .distinct().select_related("asset_category").order_by("asset_tag"))


def costruisci(*, oggi=None, con_personale: bool = True) -> dict:
    from anagrafica.models_mpq import AbilitazioneProcesso, CertificazioneIndividuale, ProcessoQualificato

    from ..models import AssetDocument, MaintenanceOccurrence, WorkOrder

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=GIORNI_SCADENZE)
    stati_asset: dict = {}

    processi = list(ProcessoQualificato.objects.filter(regime=REGIME_PART145)
                    .select_related("cliente", "ente_certificatore").order_by("nome"))
    attrezzature = list(_attrezzature())
    ids = [a.pk for a in attrezzature]
    if attrezzature:
        stati_asset = dict(type(attrezzature[0]).STATUS_CHOICES)

    # Dati collegati alle attrezzature, in poche query.
    ultimo_chiuso: dict = {}
    for r in (WorkOrder.objects.filter(asset_id__in=ids, status=WorkOrder.STATUS_DONE)
              .order_by("asset_id", "-closed_at").values("asset_id", "closed_at", "kind")):
        ultimo_chiuso.setdefault(r["asset_id"], r)
    odl_aperti = list(WorkOrder.objects.filter(asset_id__in=ids, status=WorkOrder.STATUS_OPEN)
                      .select_related("asset").order_by("opened_at"))
    aperti_per_asset: dict = {}
    for wo in odl_aperti:
        aperti_per_asset[wo.asset_id] = aperti_per_asset.get(wo.asset_id, 0) + 1
    prossime = dict(MaintenanceOccurrence.objects.filter(asset_id__in=ids, status=MaintenanceOccurrence.STATUS_OPEN)
                    .order_by().values("asset_id").annotate(p=Min("due_date")).values_list("asset_id", "p"))
    documenti = dict(AssetDocument.objects.filter(asset_id__in=ids).order_by().values("asset_id")
                     .annotate(n=Count("id")).values_list("asset_id", "n"))
    tipi_odl = dict(WorkOrder.KIND_CHOICES)
    processi_per_asset: dict = {}
    for asset_id, nome in (type(attrezzature[0]).processi_qualificati.through.objects
                           .filter(asset_id__in=ids).values_list("asset_id", "processoqualificato__nome")
                           if attrezzature else []):
        processi_per_asset.setdefault(asset_id, []).append(nome)

    # ── Personale ────────────────────────────────────────────────────────────
    abilitazioni = []
    nomi: dict = {}
    timbri: dict = {}
    if con_personale:
        abilitazioni = list(
            AbilitazioneProcesso.objects.filter(Q(is_part145=True) | Q(processo__regime=REGIME_PART145))
            .select_related("processo").prefetch_related("certificazioni").order_by("processo__nome", "legacy_anagrafica_id")
        )
        from anagrafica.views_mpq import _nomi_map

        nomi = _nomi_map([a.legacy_anagrafica_id for a in abilitazioni])
        try:
            from timbri.models import RegistroTimbro

            for t in RegistroTimbro.objects.filter(abilitazione_processo__in=abilitazioni, is_archived=False):
                timbri.setdefault(t.abilitazione_processo_id, []).append(t)
        except Exception:
            timbri = {}

    def nome_persona(ab):
        if ab.nominativo_esterno:
            return f"{ab.nominativo_esterno} (esterno)"
        return nomi.get(ab.legacy_anagrafica_id) or f"#{ab.legacy_anagrafica_id}"

    stati_ab = dict(AbilitazioneProcesso.STATO_CHOICES)

    # ── Sezioni ──────────────────────────────────────────────────────────────
    s_processi = Sezione("processi", "Processi PART 145",
                         ["Processo", "Cliente / ente", "Livello", "Stato", "Scadenza", "Esito scadenza",
                          "Persone abilitate", "Attrezzature"],
                         vuoto="Nessun processo in regime PART 145 in MOD.128.")
    for p in processi:
        scad = p.scadenza_effettiva
        s_processi.righe.append([
            p.nome, str(p.cliente) if p.cliente_id else "", p.livello, p.get_stato_display(), _d(scad),
            _stato_scadenza(scad, oggi) if p.tipo_validita != p.VALIDITA_ILLIMITATA else "Illimitata",
            p.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA).count() if con_personale else "—",
            attrezzature_processo(p).count(),
        ])

    s_attr = Sezione("attrezzature", "Attrezzature",
                     ["Asset", "Nome", "Categoria", "Reparto", "Stato", "Seriale", "Processi",
                      "Ultimo intervento chiuso", "OdL aperti", "Prossima manutenzione", "Documenti"],
                     nota="Asset con la casella «Rientra in PART 145» e asset collegati a un processo PART 145.",
                     vuoto="Nessuna attrezzatura PART 145.")
    for a in attrezzature:
        chiuso = ultimo_chiuso.get(a.pk)
        processi_a = processi_per_asset.get(a.pk, [])
        if a.part_145 and not processi_a:
            processi_a = ["PART 145"]
        s_attr.asset_ids.append(a.pk)
        s_attr.righe.append([
            a.asset_tag, a.name, a.category_label or "", a.reparto, stati_asset.get(a.status, a.status),
            a.serial_number or "", ", ".join(processi_a),
            (f"{timezone.localtime(chiuso['closed_at']):%d/%m/%Y} · {tipi_odl.get(chiuso['kind'], chiuso['kind'])}"
             if chiuso and chiuso["closed_at"] else ""),
            aperti_per_asset.get(a.pk, 0), _d(prossime.get(a.pk)), documenti.get(a.pk, 0),
        ])

    s_pers = Sezione("personale", "Personale abilitato",
                     ["Persona", "Processo", "Ruoli", "Stato abilitazione", "Certificazioni", "Prima scadenza certificati",
                      "Idoneità requisiti", "Timbro"],
                     nota="Abilitazioni MOD.128 con ruolo «Part 145» o su un processo in regime PART 145.",
                     vuoto="Nessuna persona abilitata: in MOD.128 aggiungi le abilitazioni con ruolo «Part 145».")
    from anagrafica.services.mpq_conformita import verifica_requisiti

    for ab in abilitazioni:
        ruoli = [n for flag, n in ((ab.is_qualificato, "Qualificato"), (ab.is_addetto, "Addetto"),
                                   (ab.is_controllore, "Controllore"), (ab.is_part145, "Part 145")) if flag]
        certs = list(ab.certificazioni.all())
        scad_cert = min((c.data_scadenza for c in certs if c.data_scadenza), default=None)
        idoneita = "—"
        if not ab.nominativo_esterno and ab.legacy_anagrafica_id:
            try:
                idoneita = ESITI_IDONEITA.get(verifica_requisiti(ab.processo, ab.legacy_anagrafica_id, oggi=oggi)["esito"], "—")
            except Exception:
                idoneita = "non calcolabile"
        timbri_ab = timbri.get(ab.pk, [])
        timbro = ", ".join(f"{t.codice_timbro or 'timbro'} ({'sospeso' if t.is_sospeso else 'attivo' if t.is_attivo else 'non attivo'})"
                           for t in timbri_ab)
        s_pers.righe.append([nome_persona(ab), ab.processo.nome, ", ".join(ruoli), stati_ab.get(ab.stato, ab.stato),
                             len(certs), _d(scad_cert), idoneita, timbro])

    s_scad = Sezione("scadenze", f"Scadenze entro {GIORNI_SCADENZE} giorni (e già scadute)",
                     ["Data", "Tipo", "Riferimento", "Dettaglio", "Stato"], vuoto="Nessuna scadenza nei prossimi 90 giorni.")
    for p in processi:
        scad = p.scadenza_effettiva
        if scad and scad <= limite:
            s_scad.righe.append([scad, "Processo", p.nome, str(p.cliente) if p.cliente_id else "", _stato_scadenza(scad, oggi)])
    for o in (MaintenanceOccurrence.objects.filter(asset_id__in=ids, status=MaintenanceOccurrence.STATUS_OPEN, due_date__lte=limite)
              .select_related("asset", "plan").order_by("due_date")):
        s_scad.righe.append([o.due_date, "Manutenzione", f"{o.asset.asset_tag} — {o.asset.name}",
                             getattr(o.plan, "label", "") or "", _stato_scadenza(o.due_date, oggi)])
    if con_personale:
        for c in (CertificazioneIndividuale.objects.filter(abilitazione__in=abilitazioni, data_scadenza__lte=limite)
                  .select_related("abilitazione", "abilitazione__processo").order_by("data_scadenza")):
            s_scad.righe.append([c.data_scadenza, "Certificazione", nome_persona(c.abilitazione),
                                 f"{c.schema} {c.livello}".strip() + f" · {c.abilitazione.processo.nome}",
                                 _stato_scadenza(c.data_scadenza, oggi)])
    s_scad.righe.sort(key=lambda r: r[0])
    for r in s_scad.righe:
        r[0] = _d(r[0])

    s_aperte = Sezione("aperte", "Situazioni aperte", ["Tipo", "Riferimento", "Dettaglio"],
                       vuoto="Nessuna situazione aperta.")
    for p in processi:
        if p.stato != p.STATO_ATTIVO:
            s_aperte.righe.append(["Processo non attivo", p.nome, p.get_stato_display()])
        scad = p.scadenza_effettiva
        if scad and scad < oggi:
            s_aperte.righe.append(["Processo scaduto", p.nome, f"scaduto il {_d(scad)}"])
        if con_personale and not any(ab.processo_id == p.pk and ab.stato == ab.STATO_ATTIVA for ab in abilitazioni):
            s_aperte.righe.append(["Processo senza persone abilitate", p.nome, "nessuna abilitazione attiva in MOD.128"])
    for a in attrezzature:
        if a.status == a.STATUS_IN_REPAIR:
            s_aperte.righe.append(["Attrezzatura in riparazione", f"{a.asset_tag} — {a.name}", a.reparto or ""])
        mancanti = [n for v, n in ((a.serial_number, "seriale"), (a.reparto, "reparto")) if not v]
        if mancanti and a.status != a.STATUS_RETIRED:
            s_aperte.righe.append(["Attrezzatura con dati mancanti", f"{a.asset_tag} — {a.name}", "manca " + " e ".join(mancanti)])
    for wo in odl_aperti:
        s_aperte.righe.append([f"OdL aperto ({tipi_odl.get(wo.kind, wo.kind)})", f"{wo.asset.asset_tag} — {wo.asset.name}",
                               f"{wo.title} · aperto il {timezone.localtime(wo.opened_at):%d/%m/%Y}"])
    for ab in abilitazioni:
        if ab.stato != ab.STATO_ATTIVA:
            s_aperte.righe.append([f"Abilitazione {stati_ab.get(ab.stato, ab.stato).lower()}", nome_persona(ab), ab.processo.nome])
        for t in timbri.get(ab.pk, []):
            if t.is_sospeso:
                s_aperte.righe.append(["Timbro sospeso", nome_persona(ab), t.sospeso_motivo or ab.processo.nome])

    sezioni = [s_processi, s_attr] + ([s_pers] if con_personale else []) + [s_scad, s_aperte]
    in_uso = sum(1 for a in attrezzature if a.status == a.STATUS_IN_USE)
    riepilogo = [("Processi PART 145", len(processi)), ("Attrezzature", len(attrezzature)), ("In uso", in_uso)]
    if con_personale:
        riepilogo.append(("Persone abilitate", len({(a.legacy_anagrafica_id, a.nominativo_esterno) for a in abilitazioni
                                                     if a.stato == a.STATO_ATTIVA})))
    riepilogo += [("Scadenze 90 giorni", len(s_scad.righe)), ("Situazioni aperte", len(s_aperte.righe))]
    return {"oggi": oggi, "riepilogo": riepilogo, "sezioni": sezioni, "con_personale": con_personale}


def _titolo_file(oggi) -> str:
    return f"dossier-part145-{oggi:%Y%m%d}"


def _intestazione(utente, con_personale) -> str:
    chi = ""
    if utente is not None and getattr(utente, "is_authenticated", False):
        chi = f" da {utente.get_full_name() or utente.get_username()}"
    testo = f"Estratto il {timezone.localtime():%d/%m/%Y %H:%M}{chi}"
    if not con_personale:
        testo += " · senza dati del personale (serve l'accesso ai processi qualificati MOD.128)"
    return testo


def esporta_xlsx(dati: dict, utente=None) -> tuple[bytes, str]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from core.excel_export import _brand_header, write_cell

    wb = Workbook()
    ws = wb.active
    ws.title = "Riepilogo"
    riga = _brand_header(ws, title="Dossier PART 145", subtitle=_intestazione(utente, dati["con_personale"]),
                         filters_label="", logo=True)
    for etichetta, valore in dati["riepilogo"]:
        write_cell(ws, riga, 1, etichetta).font = Font(bold=True)
        write_cell(ws, riga, 2, valore)
        riga += 1
    ws.column_dimensions["A"].width = 30
    fill = PatternFill("solid", fgColor="0C2545")
    for s in dati["sezioni"]:
        foglio = wb.create_sheet(s.titolo[:31].replace("/", "-"))
        write_cell(foglio, 1, 1, s.titolo).font = Font(bold=True, size=13, color="0C2545")
        if s.nota:
            write_cell(foglio, 2, 1, s.nota).font = Font(size=9, color="5B6B7C")
        for c, h in enumerate(s.intestazioni, start=1):
            cella = write_cell(foglio, 4, c, h)
            cella.fill, cella.font, cella.alignment = fill, Font(bold=True, color="FFFFFF"), Alignment(vertical="center")
        for r, valori in enumerate(s.righe, start=5):
            for c, v in enumerate(valori, start=1):
                write_cell(foglio, r, c, v)
        if not s.righe:
            write_cell(foglio, 5, 1, s.vuoto)
        for c, h in enumerate(s.intestazioni, start=1):
            larghezza = max([len(str(h))] + [len(str(r[c - 1])) for r in s.righe if c - 1 < len(r)])
            foglio.column_dimensions[get_column_letter(c)].width = min(60, max(10, larghezza + 2))
        foglio.freeze_panes = "A5"
        if s.righe:
            foglio.auto_filter.ref = f"A4:{get_column_letter(len(s.intestazioni))}{4 + len(s.righe)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), _titolo_file(dati["oggi"]) + ".xlsx"


def esporta_pdf(dati: dict, utente=None) -> tuple[bytes, str]:
    from reportlab.platypus import Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = io.BytesIO()
    doc = make_document(buf, title="Dossier PART 145", landscape=True)
    larghezza = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    elementi: list = []
    riepilogo = [[Paragraph(escape(str(e)), styles["table_header"]) for e, _ in dati["riepilogo"]],
                 [Paragraph(escape(str(v)), styles["cell"]) for _, v in dati["riepilogo"]]]
    elementi.append(data_table(riepilogo, theme, col_widths=[larghezza / len(dati["riepilogo"])] * len(dati["riepilogo"])))
    for s in dati["sezioni"]:
        elementi.append(Spacer(1, 10))
        elementi += section_heading(escape(s.titolo), theme, styles)
        if s.nota:
            elementi.append(Paragraph(escape(s.nota), styles["body"]))
        if not s.righe:
            elementi.append(Paragraph(escape(s.vuoto), styles["body"]))
            continue
        righe = [[Paragraph(escape(str(h)), styles["table_header"]) for h in s.intestazioni]]
        righe += [[Paragraph(escape("" if v is None else str(v)), styles["cell"]) for v in r] for r in s.righe]
        elementi.append(data_table(righe, theme, col_widths=[larghezza / len(s.intestazioni)] * len(s.intestazioni),
                                   repeat_rows=1, extra_style=[("FONTSIZE", (0, 0), (-1, -1), 7),
                                                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    draw = header_footer_callback(theme, title="DOSSIER PART 145", subtitle=_intestazione(utente, dati["con_personale"]))
    doc.build(elementi, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue(), _titolo_file(dati["oggi"]) + ".pdf"
