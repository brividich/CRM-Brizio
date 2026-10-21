"""Dossier PART 145: processo, attrezzature, personale, scadenze e situazioni aperte.

Una sola costruzione (``costruisci``) per pagina, Excel (un foglio per sezione) e PDF:
le tre uscite mostrano gli stessi dati. Il personale (dati MOD.128) compare solo a chi
ha il permesso di vedere i processi qualificati: senza, le sezioni lo omettono.

Allineato all'SGI: perimetro = processo Part 145 + processi speciali autorizzati
(MO-ID-009.24, Annesso 2); attrezzi classificati come il MOE §2.4 (a vista / con
manutenzione / con taratura); documenti di riferimento dal registro SGI.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import timedelta
from html import escape

from django.db.models import Count, Min, Q
from django.urls import reverse
from django.utils import timezone

from automazioni.managed_flows import event_flow

from .part145 import REGIME_PART145, attrezzature_processo, processi_perimetro

GIORNI_SCADENZE = 90

ESITI_IDONEITA = {"ok": "Idoneo", "warn": "In scadenza", "incompleto": "Incompleto", "ko": "Non idoneo",
                  "nessuno": "Nessun requisito"}

# Classi di controllo degli attrezzi (MOE C750-03 §2.4.2), dedotte dai piani di manutenzione.
CLASSE_TARATURA = "Taratura"
CLASSE_MANUTENZIONE = "Manutenzione periodica"
CLASSE_A_VISTA = "A vista"

# Documenti SGI di riferimento: (codice nel registro SGI, perché serve). Si cerca il codice
# esatto, poi il primo che inizia così (i MOE hanno nel codice anche edizione e data).
DOCUMENTI_SGI = [
    ("MO-ID-009.24", "Accordo con l'organizzazione di manutenzione (ATC)"),
    ("MO-ID-009.24 Annesso 1", "P/N autorizzati"),
    ("MO-ID-009.24 Annesso 2", "Processi speciali autorizzati (DQP)"),
    ("MT CN 70", "Memoria tecnica PART 145"),
    ("MT CN 17", "Attrezzature, utensili, strumenti (controllo semestrale)"),
    ("MT CN 68", "Gestione apparecchiature per misurazione"),
    ("MOE Civile C750-03", "Manuale dell'organizzazione di manutenzione — civile"),
    ("MOE Militare C750-29", "Manuale dell'organizzazione di manutenzione — militare"),
]


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
    #: Azione per riga ``(testo, url)`` o None: dove si risolve, solo in pagina (non negli export).
    azioni: list = field(default_factory=list)

    def aggiungi(self, riga, azione=None, asset_id=None):
        self.righe.append(riga)
        self.azioni.append(azione)
        if asset_id is not None or self.asset_ids:
            self.asset_ids += [None] * (len(self.righe) - 1 - len(self.asset_ids))
            self.asset_ids.append(asset_id)

    @property
    def ha_azioni(self) -> bool:
        return any(self.azioni)

    @property
    def righe_link(self):
        ids = self.asset_ids + [None] * (len(self.righe) - len(self.asset_ids))
        azioni = self.azioni + [None] * (len(self.righe) - len(self.azioni))
        return list(zip(self.righe, ids[:len(self.righe)], azioni[:len(self.righe)], strict=True))


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

    return (Asset.objects.filter(Q(part_145=True) | Q(processi_qualificati__regime=REGIME_PART145)
                                 | Q(processi_qualificati__perimetro_part145=True))
            .distinct().select_related("asset_category").order_by("asset_tag"))


def _controlli_attrezzi(ids) -> dict:
    """Per asset: classe di controllo, ente di taratura, ultima e prossima taratura.

    La classe viene dai piani applicati all'asset (anche ereditati da gruppo/categoria):
    piano di taratura → «Taratura»; altro piano non amministrativo → «Manutenzione
    periodica»; nessun piano → «A vista» (controllo visivo prima dell'uso).
    """
    from ..models import Asset, MaintenanceInterventionTemplate as Piano, MaintenanceOccurrence
    from .maintenance_domain import build_plan_resolutions

    esito = {i: {"classe": CLASSE_A_VISTA, "enti": [], "ultima": None, "prossima": None, "scaduta": False}
             for i in ids}
    if not ids:
        return esito
    for (_, asset_id), r in build_plan_resolutions(asset_queryset=Asset.objects.filter(pk__in=ids)).items():
        if not r.is_applied or r.plan.maintenance_type == Piano.TYPE_ADMINISTRATIVE:
            continue
        voce = esito[asset_id]
        if r.plan.maintenance_type == Piano.TYPE_CALIBRATION:
            voce["classe"] = CLASSE_TARATURA
            if r.assignment.effective_execution_mode == Piano.MODE_INTERNAL:
                ente = "Interna"
            else:
                fornitore = r.assignment.effective_supplier
                ente = fornitore.ragione_sociale if fornitore else "Esterna (fornitore non indicato)"
            if ente not in voce["enti"]:
                voce["enti"].append(ente)
        elif voce["classe"] == CLASSE_A_VISTA:
            voce["classe"] = CLASSE_MANUTENZIONE
    oggi = timezone.localdate()
    for o in (MaintenanceOccurrence.objects.filter(asset_id__in=ids, plan__maintenance_type=Piano.TYPE_CALIBRATION)
              .exclude(status=MaintenanceOccurrence.STATUS_CANCELED).values("asset_id", "status", "due_date", "completed_on")):
        voce = esito[o["asset_id"]]
        voce["classe"] = CLASSE_TARATURA
        if o["status"] == MaintenanceOccurrence.STATUS_DONE and o["completed_on"]:
            voce["ultima"] = max(filter(None, [voce["ultima"], o["completed_on"]]))
        elif o["status"] == MaintenanceOccurrence.STATUS_OPEN:
            voce["prossima"] = min(filter(None, [voce["prossima"], o["due_date"]]))
    for voce in esito.values():
        voce["scaduta"] = bool(voce["prossima"] and voce["prossima"] < oggi)
    return esito


def _documenti_sgi() -> list[dict]:
    """Revisione corrente dei documenti SGI di riferimento (registro procedure)."""
    try:
        from procedure_refresh.models import ProcedureRevision
    except Exception:
        return []
    righe = []
    for codice, perche in DOCUMENTI_SGI:
        correnti = ProcedureRevision.objects.filter(is_current=True).select_related("document")
        rev = (correnti.filter(document__code__iexact=codice).first()
               or correnti.filter(document__code__istartswith=codice).order_by("document__code").first())
        righe.append({"codice": codice, "perche": perche, "rev": rev})
    return righe


def costruisci(*, oggi=None, con_personale: bool = True) -> dict:
    from anagrafica.models_mpq import AbilitazioneProcesso, CertificazioneIndividuale, RequisitoQualifica

    from ..models import AssetDocument, MaintenanceInterventionTemplate, MaintenanceOccurrence, WorkOrder

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=GIORNI_SCADENZE)
    stati_asset: dict = {}

    processi = list(processi_perimetro().select_related("cliente", "ente_certificatore")
                    .prefetch_related("riferimenti").order_by("-regime", "nome"))
    requisiti = list(RequisitoQualifica.objects.filter(processo__in=processi, attivo=True)
                     .select_related("processo").order_by("data_scadenza", "processo__nome", "ordine"))
    attrezzature = list(_attrezzature())
    ids = [a.pk for a in attrezzature]
    if attrezzature:
        stati_asset = dict(type(attrezzature[0]).STATUS_CHOICES)
    controlli = _controlli_attrezzi(ids)

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
            AbilitazioneProcesso.objects.filter(Q(is_part145=True) | Q(processo__regime=REGIME_PART145)
                                                | Q(processo__perimetro_part145=True))
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
                         ["Processo", "Ambito", "Cliente / ente", "Livello", "Stato", "Scadenza", "Esito scadenza",
                          "Persone abilitate", "Attrezzature"],
                         nota="Il processo in regime PART 145 e i processi speciali con la casella «Rientra nel "
                              "perimetro Part 145» (MOD.128).",
                         vuoto="Nessun processo in regime PART 145 in MOD.128.")
    def apri_mod128(processo):
        return ("Apri in MOD.128", reverse("anagrafica:mpq_processo_detail", args=[processo.pk])) if con_personale else None

    for p in processi:
        scad = p.scadenza_effettiva
        s_processi.azioni.append(apri_mod128(p))
        s_processi.righe.append([
            p.nome, "Regime PART 145" if p.regime == REGIME_PART145 else "Processo speciale nel perimetro",
            str(p.cliente) if p.cliente_id else "", p.livello, p.get_stato_display(), _d(scad),
            _stato_scadenza(scad, oggi) if p.tipo_validita != p.VALIDITA_ILLIMITATA else "Illimitata",
            p.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA).count() if con_personale else "—",
            attrezzature_processo(p).count(),
        ])

    s_attr = Sezione("attrezzature", "Attrezzature",
                     ["Asset", "Nome", "Categoria", "Reparto", "Stato", "Seriale", "Processi", "Controllo",
                      "Ente taratura", "Ultima taratura", "Prossima taratura", "Ultimo intervento chiuso",
                      "OdL aperti", "Prossima manutenzione", "Documenti"],
                     nota="Asset con la casella «Rientra in PART 145» e asset collegati a un processo del perimetro. "
                          "«Controllo» come il MOE §2.4: «Taratura» se l'asset ha un piano di taratura, «Manutenzione "
                          "periodica» se ha altri piani, altrimenti «A vista» (esame visivo prima dell'uso).",
                     vuoto="Nessuna attrezzatura PART 145.")
    for a in attrezzature:
        chiuso = ultimo_chiuso.get(a.pk)
        processi_a = processi_per_asset.get(a.pk, [])
        if a.part_145 and not processi_a:
            processi_a = ["PART 145"]
        c = controlli[a.pk]
        s_attr.asset_ids.append(a.pk)
        s_attr.righe.append([
            a.asset_tag, a.name, a.category_label or "", a.reparto, stati_asset.get(a.status, a.status),
            a.serial_number or "", ", ".join(processi_a), c["classe"], ", ".join(c["enti"]),
            _d(c["ultima"]), _d(c["prossima"]),
            (f"{timezone.localtime(chiuso['closed_at']):%d/%m/%Y} · {tipi_odl.get(chiuso['kind'], chiuso['kind'])}"
             if chiuso and chiuso["closed_at"] else ""),
            aperti_per_asset.get(a.pk, 0), _d(prossime.get(a.pk)), documenti.get(a.pk, 0),
        ])

    s_req = Sezione("contratti", "Contratti e requisiti dei processi",
                    ["Processo", "Tipo", "Descrizione", "Obbligatorio", "Stato", "Scadenza", "Esito scadenza"],
                    nota="Requisiti dei processi del perimetro in MOD.128: es. il contratto quadro con la sua "
                         "scadenza (tipo «Contratto / accordo»), audit, certificati.",
                    vuoto="Nessun requisito: in MOD.128 aggiungi al processo PART 145 il contratto quadro "
                          "(tipo «Contratto / accordo») con la scadenza.")
    for r in requisiti:
        s_req.aggiungi([r.processo.nome, r.get_tipo_display(), r.descrizione, "Sì" if r.obbligatorio else "No",
                        r.get_stato_display(), _d(r.data_scadenza),
                        _stato_scadenza(r.data_scadenza, oggi) if r.data_scadenza else ""], apri_mod128(r.processo))

    s_doc = Sezione("documenti", "Documenti di riferimento",
                    ["Documento", "A cosa serve", "Titolo nel registro SGI", "Revisione", "Data revisione"],
                    nota="Revisione corrente nel registro SGI (Procedure) e riferimenti registrati sui processi MOD.128.")
    for d in _documenti_sgi():
        rev = d["rev"]
        if rev is None:
            s_doc.aggiungi([d["codice"], d["perche"], "Non trovato nel registro SGI", "", ""])
            continue
        s_doc.aggiungi([rev.document.code, d["perche"], rev.document.title, rev.revision_code or "—",
                        _d(rev.revision_date)],
                       ("Apri il documento", reverse("procedure_refresh:document_open", args=[rev.pk])))
    tipi_rif = None
    for p in processi:
        for rif in p.riferimenti.all():
            tipi_rif = tipi_rif or dict(type(rif).TIPO_CHOICES)
            s_doc.aggiungi([rif.codice, f"{tipi_rif.get(rif.tipo, rif.tipo)} · {p.nome}", rif.note, "", ""],
                           apri_mod128(p))

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
    for r in requisiti:
        if r.data_scadenza and r.data_scadenza <= limite:
            s_scad.righe.append([r.data_scadenza, "Contratto" if r.tipo == r.TIPO_CONTRATTO else "Requisito di processo",
                                 r.descrizione, r.processo.nome, _stato_scadenza(r.data_scadenza, oggi)])
    for o in (MaintenanceOccurrence.objects.filter(asset_id__in=ids, status=MaintenanceOccurrence.STATUS_OPEN, due_date__lte=limite)
              .select_related("asset", "plan").order_by("due_date")):
        tipo = "Taratura" if o.plan.maintenance_type == MaintenanceInterventionTemplate.TYPE_CALIBRATION else "Manutenzione"
        s_scad.righe.append([o.due_date, tipo, f"{o.asset.asset_tag} — {o.asset.name}",
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
            s_aperte.aggiungi(["Processo non attivo", p.nome, p.get_stato_display()], apri_mod128(p))
        scad = p.scadenza_effettiva
        if scad and scad < oggi:
            s_aperte.aggiungi(["Processo scaduto", p.nome, f"scaduto il {_d(scad)}"], apri_mod128(p))
        elif scad is None and p.tipo_validita != p.VALIDITA_ILLIMITATA:
            s_aperte.aggiungi(["Processo senza scadenza", p.nome,
                               "validità a data o a periodo ma nessuna data: imposta la scadenza o «Illimitata»"],
                              apri_mod128(p))
        if con_personale and not any(ab.processo_id == p.pk and ab.stato == ab.STATO_ATTIVA for ab in abilitazioni):
            s_aperte.aggiungi(["Processo senza persone abilitate", p.nome, "nessuna abilitazione attiva in MOD.128"],
                              apri_mod128(p))
    for r in requisiti:
        if r.obbligatorio and (r.stato == r.STATO_SCADUTO or (r.data_scadenza and r.data_scadenza < oggi)):
            tipo = "Contratto scaduto" if r.tipo == r.TIPO_CONTRATTO else "Requisito di processo scaduto"
            s_aperte.aggiungi([tipo, r.descrizione, f"{r.processo.nome}"
                               + (f" · scaduto il {_d(r.data_scadenza)}" if r.data_scadenza else "")],
                              apri_mod128(r.processo))
    for a in attrezzature:
        scheda = ("Apri la scheda", reverse("assets:asset_view", args=[a.pk]))
        if a.status == a.STATUS_IN_REPAIR:
            s_aperte.aggiungi(["Attrezzatura in riparazione", f"{a.asset_tag} — {a.name}", a.reparto or ""], scheda)
        if controlli[a.pk]["scaduta"] and a.status != a.STATUS_RETIRED:
            s_aperte.aggiungi(["Taratura scaduta", f"{a.asset_tag} — {a.name}",
                               f"scaduta il {_d(controlli[a.pk]['prossima'])}: segregare fino alla taratura (MOE §2.4.3.4)"],
                              scheda)
        mancanti = [n for v, n in ((a.serial_number, "seriale"), (a.reparto, "reparto")) if not v]
        if mancanti and a.status != a.STATUS_RETIRED:
            s_aperte.aggiungi(["Attrezzatura con dati mancanti", f"{a.asset_tag} — {a.name}", "manca " + " e ".join(mancanti)],
                              ("Completa la scheda", reverse("assets:asset_edit", args=[a.pk])))
    for wo in odl_aperti:
        s_aperte.aggiungi([f"OdL aperto ({tipi_odl.get(wo.kind, wo.kind)})", f"{wo.asset.asset_tag} — {wo.asset.name}",
                           f"{wo.title} · aperto il {timezone.localtime(wo.opened_at):%d/%m/%Y}"],
                          ("Apri l'OdL", reverse("assets:wo_view", args=[wo.pk])))
    for ab in abilitazioni:
        if ab.stato != ab.STATO_ATTIVA:
            s_aperte.aggiungi([f"Abilitazione {stati_ab.get(ab.stato, ab.stato).lower()}", nome_persona(ab), ab.processo.nome],
                              apri_mod128(ab.processo))
        for t in timbri.get(ab.pk, []):
            if t.is_sospeso:
                s_aperte.aggiungi(["Timbro sospeso", nome_persona(ab), t.sospeso_motivo or ab.processo.nome],
                                  apri_mod128(ab.processo))

    sezioni = ([s_processi, s_req, s_attr] + ([s_pers] if con_personale else [])
               + [s_scad, s_aperte, s_doc])
    in_uso = sum(1 for a in attrezzature if a.status == a.STATUS_IN_USE)
    tarate = sum(1 for c in controlli.values() if c["classe"] == CLASSE_TARATURA)
    riepilogo = [("Processi PART 145", len(processi)), ("Attrezzature", len(attrezzature)), ("In uso", in_uso),
                 ("Con taratura", tarate)]
    if con_personale:
        riepilogo.append(("Persone abilitate", len({(a.legacy_anagrafica_id, a.nominativo_esterno) for a in abilitazioni
                                                     if a.stato == a.STATO_ATTIVA})))
    riepilogo += [("Scadenze 90 giorni", len(s_scad.righe)), ("Situazioni aperte", len(s_aperte.righe))]
    return {"oggi": oggi, "riepilogo": riepilogo, "sezioni": sezioni, "con_personale": con_personale,
            "attrezzature": attrezzature, "controlli": controlli, "stati_asset": stati_asset}


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


# ── Elenchi operativi ─────────────────────────────────────────────────────────


def esporta_tarature_xlsx(dati: dict, utente=None) -> tuple[bytes, str]:
    """Strumenti con taratura: ente, ultima e prossima (MT CN 70 §6.12: elenco da comunicare all'AMO)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from core.excel_export import _brand_header, write_cell

    wb = Workbook()
    ws = wb.active
    ws.title = "Strumenti tarati"
    riga = _brand_header(ws, title="PART 145 — Strumenti con taratura",
                         subtitle=_intestazione(utente, True), filters_label="", logo=True)
    intestazioni = ["Asset", "Nome", "Reparto", "Seriale", "Costruttore / modello", "Stato", "Ente taratura",
                    "Ultima taratura", "Prossima taratura", "Esito"]
    fill = PatternFill("solid", fgColor="0C2545")
    for c, h in enumerate(intestazioni, start=1):
        cella = write_cell(ws, riga, c, h)
        cella.fill, cella.font = fill, Font(bold=True, color="FFFFFF")
    inizio = riga
    oggi = dati["oggi"]
    for a in dati["attrezzature"]:
        c = dati["controlli"][a.pk]
        if c["classe"] != CLASSE_TARATURA:
            continue
        riga += 1
        valori = [a.asset_tag, a.name, a.reparto, a.serial_number or "",
                  " ".join(filter(None, [a.manufacturer, a.model])), dati["stati_asset"].get(a.status, a.status),
                  ", ".join(c["enti"]), _d(c["ultima"]), _d(c["prossima"]),
                  _stato_scadenza(c["prossima"], oggi) if c["prossima"] else "Nessuna taratura pianificata"]
        for col, v in enumerate(valori, start=1):
            write_cell(ws, riga, col, v)
    if riga == inizio:
        write_cell(ws, riga + 1, 1, "Nessuno strumento con piano di taratura tra le attrezzature PART 145.")
    for col, larghezza in enumerate([14, 34, 16, 18, 24, 14, 30, 15, 16, 22], start=1):
        ws.column_dimensions[get_column_letter(col)].width = larghezza
    ws.freeze_panes = ws.cell(row=inizio + 1, column=1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"part145-strumenti-tarati-{oggi:%Y%m%d}.xlsx"


def esporta_controllo_semestrale_pdf(dati: dict, utente=None) -> tuple[bytes, str]:
    """Elenco per il controllo semestrale delle attrezzature (MT CN 17 §6.1.3, Mod.072).

    Una pagina per reparto: il capo reparto esegue l'esame visivo (idoneità, completezza,
    identificazione/targhetta), timbra e firma; poi CQF verifica.
    """
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = io.BytesIO()
    doc = make_document(buf, title="Controllo semestrale attrezzature PART 145", landscape=True)
    larghezza = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
    per_reparto: dict = {}
    for a in dati["attrezzature"]:
        if a.status != a.STATUS_RETIRED:
            per_reparto.setdefault(a.reparto or "Senza reparto", []).append(a)
    elementi: list = []
    colonne = ["Codice", "Nome", "Seriale", "Controllo", "Targhetta presente", "Integra e completa", "Esito", "Note"]
    pesi = [0.11, 0.25, 0.12, 0.12, 0.09, 0.09, 0.09, 0.13]
    for n, (reparto, assets) in enumerate(sorted(per_reparto.items())):
        if n:
            elementi.append(PageBreak())
        elementi += section_heading(escape(f"Reparto: {reparto}"), theme, styles)
        elementi.append(Paragraph(
            "Controllo semestrale (gennaio / giugno) — data: ____________ · Esame visivo: idoneità, completezza "
            "e identificazione. Senza targhetta l'attrezzatura è non conforme e non va immagazzinata.", styles["body"]))
        elementi.append(Spacer(1, 6))
        righe = [[Paragraph(escape(h), styles["table_header"]) for h in colonne]]
        for a in sorted(assets, key=lambda x: x.asset_tag):
            righe.append([Paragraph(escape(str(v)), styles["cell"]) for v in
                          [a.asset_tag, a.name, a.serial_number or "", dati["controlli"][a.pk]["classe"],
                           "[ ] Sì  [ ] No", "[ ] Sì  [ ] No", "", ""]])
        elementi.append(data_table(righe, theme, col_widths=[larghezza * p for p in pesi], repeat_rows=1,
                                   extra_style=[("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elementi.append(Spacer(1, 18))
        elementi.append(Paragraph("Capo reparto (timbro e firma): ______________________________"
                                  "&nbsp;&nbsp;&nbsp;&nbsp;Verifica CQF: ______________________________",
                                  styles["body"]))
    if not elementi:
        elementi.append(Paragraph("Nessuna attrezzatura PART 145 da controllare.", styles["body"]))
    draw = header_footer_callback(theme, title="CONTROLLO SEMESTRALE ATTREZZATURE PART 145",
                                  subtitle="Rif. MT CN 17 §6.1.3 · Mod.072 · " + _intestazione(utente, True))
    doc.build(elementi, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue(), f"part145-controllo-semestrale-{dati['oggi']:%Y%m%d}.pdf"


# ── Avviso scadenze ───────────────────────────────────────────────────────────


@event_flow("part145_scadenze", skipped_result=0)
def notifica_scadenze(*, oggi=None, override=None, fail_silently: bool = True) -> int:
    """Mail settimanale a Qualità: scadenze PART 145 entro 90 giorni e già scadute.

    Contratto, processi, requisiti, tarature/manutenzioni e certificazioni del personale:
    l'accordo con l'organizzazione di manutenzione chiede di avvisare almeno 3 mesi prima
    (MO-ID-009.24 §2). Nessuna scadenza = nessuna mail. Ritorna le mail inviate (0 o 1).
    """
    from anagrafica.services.mpq_timbri import MSM_CONFIG_KEY
    from anagrafica.services.reminders import get_reminder_recipients
    from core.email_utils import send_hub_mail

    recipients = get_reminder_recipients(MSM_CONFIG_KEY, override=override)
    if not recipients:
        return 0
    dati = costruisci(oggi=oggi, con_personale=True)
    scadenze = next(s for s in dati["sezioni"] if s.codice == "scadenze")
    if not scadenze.righe:
        return 0
    cella = "padding:8px 12px;border-top:1px solid #e2e8f0;"
    intestazione = "text-align:left;padding:9px 12px;color:#64748b;font-size:12px;"
    righe = "".join("<tr>" + "".join(f"<td style='{cella}'>{escape(str(v))}</td>" for v in r) + "</tr>"
                    for r in scadenze.righe)
    tabella = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;'>"
        "<tr style='background:#eef3f8;'>"
        + "".join(f"<th style='{intestazione}'>{escape(h)}</th>" for h in scadenze.intestazioni)
        + "</tr>" + righe + "</table>"
    )
    scadute = sum(1 for r in scadenze.righe if r[-1] == "Scaduta")
    testo = (f"{len(scadenze.righe)} scadenze PART 145 entro {GIORNI_SCADENZE} giorni"
             + (f", di cui {scadute} già scadute" if scadute else "")
             + ". Le scadenze della formazione vanno comunicate al Maintenance Manager almeno 3 mesi prima.")
    return send_hub_mail(
        subject=f"[PART 145] Scadenze entro {GIORNI_SCADENZE} giorni ({len(scadenze.righe)})",
        body_text=testo,
        recipients=recipients,
        title="PART 145 — scadenze",
        email_type="Qualità",
        badge="PART 145",
        section_label="Dossier PART 145",
        body_html_fragment=f"<p style='margin:0 0 14px;'>{escape(testo)}</p>{tabella}",
        fail_silently=fail_silently,
    )
