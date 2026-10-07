"""Form della reportistica: modello, blocchi (formset ordinabile), generazione.

Le opzioni delle sezioni non sono campi Django fissi: ogni sezione le dichiara
nel catalogo e il form dei blocchi le rende e le legge con nomi
``<prefisso>-o__<sezione>__<opzione>``. Aggiungere un'opzione a una sezione non
richiede di toccare form, template o migrazioni.
"""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from anagrafica.models import ReportBlocco, ReportModello

from . import sezioni as catalogo
from .dati import Perimetro, carica_dipendenti

_SELECT_MULTI = {"size": 6, "data-reportistica-multi": "1"}
_DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def scelte_perimetro(dipendenti=None) -> dict[str, list[tuple[str, str]]]:
    """Valori selezionabili per il perimetro: cataloghi canonici + persone."""
    from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Mansione, Reparto, TipoQualifica

    dipendenti = carica_dipendenti() if dipendenti is None else dipendenti
    mansioni = {m for m in Mansione.objects.values_list("nome", flat=True) if m}
    mansioni |= {d.mansione for d in dipendenti if d.mansione}
    oggi = timezone.localdate()
    persone = [
        (str(d.id), d.nominativo + ("" if d.in_forza_al(oggi) else " (cessato)") + (f" · {d.matricola}" if d.matricola else ""))
        for d in dipendenti
    ]
    return {
        "reparti": [(x, x) for x in Reparto.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True)],
        "aree": [(x, x) for x in AreaAziendale.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True)],
        "mansioni": [(x, x) for x in sorted(mansioni, key=str.casefold)],
        "contratti": list(DipendenteAnagraficaAziendale.CONTRATTO_CHOICES),
        "livelli": [(x, x) for x in sorted({d.livello for d in dipendenti if d.livello}, key=str.casefold)],
        "persone": persone,
        "escludi": persone,
        "qualifiche": [(str(t.pk), t.nome) for t in TipoQualifica.objects.filter(is_active=True).order_by("nome")],
    }


class PerimetroMixin:
    """Campi del perimetro di persone, condivisi da modello e generazione."""

    _MULTI = (
        ("reparti", "Reparti", ""),
        ("aree", "Aree aziendali", ""),
        ("mansioni", "Mansioni", ""),
        ("contratti", "Tipologie di contratto", ""),
        ("livelli", "Livelli di inquadramento", ""),
        ("qualifiche", "Con almeno una di queste qualifiche valide", "Es. solo i saldatori patentati."),
        ("persone", "Solo queste persone", "Vuoto = tutte le persone che rispettano gli altri filtri."),
        ("escludi", "Escludi queste persone", ""),
    )

    def _add_perimetro_fields(self, scelte: dict, iniziale: Perimetro) -> None:
        for nome, label, aiuto in self._MULTI:
            self.fields[nome] = forms.MultipleChoiceField(
                label=label, required=False, choices=scelte.get(nome, []), help_text=aiuto,
                widget=forms.SelectMultiple(attrs=_SELECT_MULTI),
            )
        self.fields["assunti_dal"] = forms.DateField(label="Assunti dal", required=False, widget=_DATE)
        self.fields["assunti_al"] = forms.DateField(label="Assunti al", required=False, widget=_DATE)
        self.fields["includi_cessati"] = forms.BooleanField(label="Includi il personale cessato", required=False)
        if not self.is_bound:
            dati = iniziale.as_dict()
            for nome, _l, _a in self._MULTI:
                self.initial[nome] = [str(x) for x in dati.get(nome) or []]
            self.initial.update({"assunti_dal": iniziale.assunti_dal, "assunti_al": iniziale.assunti_al,
                                 "includi_cessati": iniziale.includi_cessati})

    @property
    def campi_perimetro(self):
        return [self[n] for n, _l, _a in self._MULTI if n not in ("persone", "escludi")]

    def perimetro(self) -> Perimetro:
        data = self.cleaned_data
        valori = {nome: data.get(nome) or [] for nome, _l, _a in self._MULTI}
        return Perimetro.from_dict({
            **valori,
            "assunti_dal": data.get("assunti_dal").isoformat() if data.get("assunti_dal") else "",
            "assunti_al": data.get("assunti_al").isoformat() if data.get("assunti_al") else "",
            "includi_cessati": data.get("includi_cessati"),
        })


class _PeriodoCleanMixin:
    def _clean_periodo(self, cleaned):
        if cleaned.get("periodo_tipo") == ReportModello.PERIODO_PERSONALIZZATO:
            if not cleaned.get("data_da") or not cleaned.get("data_a"):
                raise forms.ValidationError("Con «Date personalizzate» indica sia la data di inizio sia quella di fine.")
        return cleaned


class ReportModelloForm(PerimetroMixin, _PeriodoCleanMixin, forms.ModelForm):
    norme = forms.MultipleChoiceField(
        label="Norme di riferimento", required=False, choices=[(n, n) for n in catalogo.NORME],
        widget=forms.CheckboxSelectMultiple,
    )

    CAMPI_OPZIONI_STAMPA = (
        "mostra_frontespizio", "mostra_indice", "mostra_riferimenti", "mostra_note_calcolo",
        "excel_foglio_documento", "excel_foglio_indicatori",
    )

    class Meta:
        model = ReportModello
        fields = [
            "nome", "descrizione", "titolo_documento", "sottotitolo", "destinatario", "norme",
            "riservatezza", "periodo_tipo", "data_da", "data_a", "redatto_da", "verificato_da", "approvato_da",
            "codice_documento", "revisione", "orientamento", "formato_predefinito", "filigrana", "piede_pagina",
            "nome_file", "mostra_frontespizio", "mostra_indice", "mostra_riferimenti", "mostra_note_calcolo",
            "excel_foglio_documento", "excel_foglio_indicatori",
        ]
        labels = {
            "nome": "Nome del modello", "descrizione": "Descrizione (a cosa serve)",
            "titolo_documento": "Titolo stampato sul documento", "sottotitolo": "Sottotitolo",
            "destinatario": "Destinatario predefinito", "riservatezza": "Classificazione",
            "periodo_tipo": "Periodo predefinito", "data_da": "Dal", "data_a": "Al",
            "redatto_da": "Redatto da", "verificato_da": "Verificato da", "approvato_da": "Approvato da",
            "codice_documento": "Codice documento", "revisione": "Revisione", "orientamento": "Orientamento pagina",
            "formato_predefinito": "Formato predefinito", "filigrana": "Filigrana",
            "piede_pagina": "Testo a piè di pagina", "nome_file": "Nome del file",
            "mostra_frontespizio": "Frontespizio con destinatario, periodo, perimetro",
            "mostra_indice": "Indice delle sezioni",
            "mostra_riferimenti": "Riferimenti normativi sotto ogni sezione",
            "mostra_note_calcolo": "Note di calcolo sotto le tabelle",
            "excel_foglio_documento": "Excel: foglio «Documento» con i testi",
            "excel_foglio_indicatori": "Excel: foglio «Indicatori» riepilogativo",
        }
        widgets = {"data_da": _DATE, "data_a": _DATE}

    def __init__(self, *args, scelte: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sottotitolo"].help_text = "Ammessi i segnaposto, es. {{periodo}}."
        self.fields["piede_pagina"].help_text = "Ammessi i segnaposto, es. {{codice}} rev. {{revisione}}."
        if not self.is_bound:
            self.initial["norme"] = list(self.instance.norme or [])
        for nome in ("orientamento", "formato_predefinito"):
            self.fields[nome].required = False
        self._add_perimetro_fields(scelte or {}, Perimetro.from_dict(self.instance.filtri))

    def clean_orientamento(self):
        return self.cleaned_data.get("orientamento") or ReportModello.ORIENTAMENTO_ORIZZONTALE

    def clean_formato_predefinito(self):
        return self.cleaned_data.get("formato_predefinito") or "pdf"

    @property
    def campi_opzioni_stampa(self):
        return [self[n] for n in self.CAMPI_OPZIONI_STAMPA]

    def clean(self):
        return self._clean_periodo(super().clean())

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.norme = list(self.cleaned_data.get("norme") or [])
        obj.filtri = self.perimetro().as_dict()
        if commit:
            obj.save()
        return obj


# ── Blocchi ──────────────────────────────────────────────────────────────────

def _scelte_sezioni(request) -> list[tuple[str, list[tuple[str, str]]]]:
    return [(gruppo, [(s.key, s.titolo) for s in voci]) for gruppo, voci in catalogo.catalogo_per_gruppo(request)]


def _cache_scelte(request) -> dict:
    """Scelte delle opzioni (con query) calcolate una volta per richiesta, non per blocco."""
    cache = getattr(request, "_rp_scelte_opzioni", None) if request is not None else None
    if cache is None:
        cache = {(s.key, o.nome): o.elenco_scelte() for s in catalogo.catalogo() for o in s.tutte_le_opzioni()
                 if o.tipo in (catalogo.SCELTA, catalogo.MULTI)}
        if request is not None:
            request._rp_scelte_opzioni = cache
    return cache


class ReportBloccoForm(forms.ModelForm):
    mostra_indicatori = forms.BooleanField(label="Indicatori", required=False, initial=True)
    mostra_tabella = forms.BooleanField(label="Tabella", required=False, initial=True)
    mostra_note = forms.BooleanField(label="Note", required=False, initial=True)

    class Meta:
        model = ReportBlocco
        fields = ["tipo", "titolo", "testo", "sezione", "ordine"]
        widgets = {
            "ordine": forms.HiddenInput(attrs={"data-rp-ordine": "1"}),
            "testo": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._request = request
        sezioni_ok = _scelte_sezioni(request)
        attuale = self.instance.sezione if self.instance and self.instance.pk else ""
        chiavi_ok = {k for _g, voci in sezioni_ok for k, _l in voci}
        if attuale and attuale not in chiavi_ok:
            # Sezione salvata da altri e non visibile a chi modifica: la si conserva.
            sezione = catalogo.get(attuale)
            sezioni_ok.append(("Non disponibili con i tuoi permessi", [(attuale, sezione.titolo if sezione else attuale)]))
        self.fields["sezione"] = forms.ChoiceField(
            required=False, choices=[("", "— scegli la sezione —"), *sezioni_ok], label="Sezione dati",
        )
        self.fields["ordine"].required = False
        self._opzioni_salvate = self.instance.opzioni if self.instance and isinstance(self.instance.opzioni, dict) else {}
        if self.instance and self.instance.pk and not self.is_bound:
            for flag in ("mostra_indicatori", "mostra_tabella", "mostra_note"):
                self.initial[flag] = self._opzioni_salvate.get(flag, True) is not False
        self._chiavi_visibili = chiavi_ok | ({attuale} if attuale else set())

    # Nomi dei campi "dinamici" del blocco.
    def nome_opzione(self, sezione: str, opzione: str) -> str:
        return f"{self.prefix}-o__{sezione}__{opzione}"

    def nome_colonne(self, sezione: str) -> str:
        return f"{self.prefix}-col__{sezione}"

    def _valori_correnti(self, sezione) -> dict:
        if self.is_bound:
            return {o.nome: o.normalizza(self._grezzo(sezione.key, o)) for o in sezione.tutte_le_opzioni()}
        salvate = self._opzioni_salvate.get("valori") if self.instance.sezione == sezione.key else None
        return sezione.valori_opzioni(salvate)

    def _grezzo(self, sezione_key: str, opzione):
        nome = self.nome_opzione(sezione_key, opzione.nome)
        if opzione.tipo == catalogo.SI_NO:
            return nome in self.data
        if opzione.tipo == catalogo.MULTI:
            return self.data.getlist(nome)
        return self.data.get(nome)

    def _colonne_correnti(self, sezione) -> list[str]:
        if self.is_bound:
            return [c for c in self.data.getlist(self.nome_colonne(sezione.key)) if c in dict(sezione.colonne)]
        if self.instance.sezione == sezione.key:
            return list(self._opzioni_salvate.get("colonne") or [])
        return []

    @property
    def gruppi_sezione(self) -> list[dict]:
        """Per ogni sezione selezionabile: colonne (nell'ordine scelto) e opzioni con i valori correnti."""
        scelte = _cache_scelte(self._request)
        out = []
        for s in catalogo.catalogo():
            if s.key not in self._chiavi_visibili:
                continue
            scelte_col = self._colonne_correnti(s)
            effettive = s.colonne_effettive(scelte_col)
            ordinate = effettive + [k for k, _l in s.colonne if k not in effettive]
            etichette = dict(s.colonne)
            valori = self._valori_correnti(s)
            opzioni = []
            for o in s.tutte_le_opzioni():
                v = valori.get(o.nome)
                elenco = scelte.get((s.key, o.nome), [])
                opzioni.append({
                    "nome": self.nome_opzione(s.key, o.nome), "etichetta": o.etichetta, "tipo": o.tipo,
                    "aiuto": o.aiuto, "valore": v, "minimo": o.minimo, "massimo": o.massimo,
                    "generale": o.nome in ("ordina_per", "ordine", "raggruppa_per", "solo_criticita",
                                           "max_righe", "nascondi_se_vuota"),
                    "scelte": [(k, l, (k in v) if o.tipo == catalogo.MULTI else k == v) for k, l in elenco],
                    "molte": len(elenco) > 8,
                })
            predefiniti = s.valori_opzioni(None)
            generali = [o for o in opzioni if o["generale"]]
            out.append({
                "key": s.key, "nome_colonne": self.nome_colonne(s.key),
                "colonne": [(k, etichette[k], k in effettive) for k in ordinate],
                "specifiche": [o for o in opzioni if not o["generale"]],
                "generali": generali,
                # Il riquadro delle opzioni generali si apre da solo se qualcosa e' gia' impostato.
                "generali_attive": any(valori.get(n) != predefiniti.get(n) for n in
                                       ("ordina_per", "raggruppa_per", "solo_criticita", "max_righe", "nascondi_se_vuota")),
            })
        return out

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        tipo = cleaned.get("tipo")
        if tipo == ReportBlocco.TIPO_SEZIONE and not cleaned.get("sezione"):
            self.add_error("sezione", "Scegli la sezione dati da inserire.")
        if tipo == ReportBlocco.TIPO_TESTO and not (cleaned.get("testo") or "").strip() and not (cleaned.get("titolo") or "").strip():
            self.add_error("testo", "Un blocco di testo vuoto non serve: scrivi il testo o eliminalo.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        sezione = catalogo.get(obj.sezione) if obj.tipo == ReportBlocco.TIPO_SEZIONE else None
        if sezione is not None:
            obj.opzioni = {
                "colonne": self._colonne_correnti(sezione),
                "mostra_indicatori": bool(self.cleaned_data.get("mostra_indicatori")),
                "mostra_tabella": bool(self.cleaned_data.get("mostra_tabella")),
                "mostra_note": bool(self.cleaned_data.get("mostra_note")),
                "valori": self._valori_correnti(sezione),
            }
        elif obj.tipo == ReportBlocco.TIPO_SEZIONE:
            pass  # sezione sparita dal catalogo: si conservano le opzioni salvate
        else:
            obj.sezione = ""
            obj.opzioni = {}
        obj.ordine = obj.ordine or 0
        if commit:
            obj.save()
        return obj


class _BaseBlocchiFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, request=None, **kwargs):
        self._request = request
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["request"] = self._request
        return kwargs

    @property
    def empty_form(self):
        form = self.form(
            auto_id=self.auto_id, prefix=self.add_prefix("__prefix__"), empty_permitted=True,
            use_required_attribute=False, request=self._request,
        )
        self.add_fields(form, None)
        return form


BlocchiFormSet = inlineformset_factory(
    ReportModello, ReportBlocco, form=ReportBloccoForm, formset=_BaseBlocchiFormSet,
    extra=0, can_delete=True,
)


# ── Generazione ──────────────────────────────────────────────────────────────

class GeneraForm(PerimetroMixin, _PeriodoCleanMixin, forms.Form):
    titolo = forms.CharField(label="Titolo", max_length=200)
    sottotitolo = forms.CharField(label="Sottotitolo", max_length=200, required=False)
    destinatario = forms.CharField(label="Destinatario", max_length=200, required=False)
    periodo_tipo = forms.ChoiceField(label="Periodo", choices=ReportModello.PERIODO_CHOICES)
    data_da = forms.DateField(label="Dal", required=False, widget=_DATE)
    data_a = forms.DateField(label="Al", required=False, widget=_DATE)
    includi_blocchi = forms.MultipleChoiceField(
        label="Blocchi da includere questa volta", required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Togli la spunta per escludere un blocco solo da questo documento.",
    )
    note_archivio = forms.CharField(
        label="Nota per l'archivio", max_length=300, required=False,
        help_text="Es. «inviato a ufficio qualità cliente il …». Resta solo nell'archivio interno.",
    )
    salva_nel_modello = forms.BooleanField(
        label="Salva testi, periodo e perimetro nel modello", required=False,
        help_text="Le prossime generazioni partiranno da queste scelte.",
    )

    def __init__(self, *args, modello: ReportModello, scelte: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.modello = modello
        blocchi = list(modello.blocchi.all())
        etichette_tipo = dict(ReportBlocco.TIPO_CHOICES)
        self.fields["includi_blocchi"].choices = [
            (str(b.pk), f"{i}. {self._etichetta_blocco(b) or etichette_tipo[b.tipo]}")
            for i, b in enumerate(blocchi, start=1)
        ]
        if not self.is_bound:
            self.initial.update({
                "titolo": modello.titolo_documento, "sottotitolo": modello.sottotitolo,
                "destinatario": modello.destinatario, "periodo_tipo": modello.periodo_tipo,
                "data_da": modello.data_da, "data_a": modello.data_a,
                "includi_blocchi": [str(b.pk) for b in blocchi],
            })
        self._add_perimetro_fields(scelte or {}, Perimetro.from_dict(modello.filtri))
        self.blocchi_testo = []
        for blocco in blocchi:
            if blocco.tipo not in (ReportBlocco.TIPO_TESTO, ReportBlocco.TIPO_SEZIONE):
                continue
            nome = f"testo_{blocco.pk}"
            etichetta = self._etichetta_blocco(blocco) or "Testo"
            if blocco.tipo == ReportBlocco.TIPO_SEZIONE:
                etichetta = f"Commento sotto «{etichetta}»"
            self.fields[nome] = forms.CharField(
                label=etichetta, required=False, initial=blocco.testo,
                widget=forms.Textarea(attrs={"rows": 5 if blocco.tipo == ReportBlocco.TIPO_TESTO else 2}),
            )
            self.blocchi_testo.append((blocco, nome))

    @staticmethod
    def _etichetta_blocco(blocco) -> str:
        sezione = catalogo.get(blocco.sezione) if blocco.sezione else None
        return blocco.titolo or (sezione.titolo if sezione else "")

    def clean(self):
        return self._clean_periodo(super().clean())

    @property
    def campi_testo(self):
        return [self[nome] for _blocco, nome in self.blocchi_testo]

    def testi(self) -> dict[int, str]:
        # Campo non inviato (richiesta non dal form) = testo del modello, non un testo vuoto.
        return {
            blocco.pk: (self.cleaned_data.get(nome, "") or "") if self.add_prefix(nome) in self.data else blocco.testo
            for blocco, nome in self.blocchi_testo
        }

    def escludi_blocchi(self) -> set[int]:
        # Campo non inviato = tutti inclusi (stessa regola dei testi).
        if self.add_prefix("includi_blocchi") not in self.data and not self.data.get("blocchi_inviati"):
            return set()
        inclusi = {int(x) for x in self.cleaned_data.get("includi_blocchi") or []}
        return {b.pk for b in self.modello.blocchi.all() if b.pk not in inclusi}
