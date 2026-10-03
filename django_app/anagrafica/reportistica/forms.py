"""Form della reportistica: modello, blocchi (formset ordinabile), generazione."""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from anagrafica.models import ReportBlocco, ReportModello

from . import sezioni as catalogo
from .dati import Perimetro, carica_dipendenti

_SELECT_MULTI = {"size": 6, "data-reportistica-multi": "1"}


def scelte_perimetro() -> dict[str, list[tuple[str, str]]]:
    """Valori selezionabili per il perimetro: cataloghi canonici + persone."""
    from anagrafica.models import AreaAziendale, Mansione, Reparto

    dipendenti = carica_dipendenti()
    mansioni = {m for m in Mansione.objects.values_list("nome", flat=True) if m}
    mansioni |= {d.mansione for d in dipendenti if d.mansione}
    reparti = list(Reparto.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True))
    aree = list(AreaAziendale.objects.filter(is_active=True).order_by("nome").values_list("nome", flat=True))
    oggi = timezone.localdate()
    persone = [
        (str(d.id), d.nominativo + ("" if d.in_forza_al(oggi) else " (cessato)") + (f" · {d.matricola}" if d.matricola else ""))
        for d in dipendenti
    ]
    return {
        "reparti": [(x, x) for x in reparti],
        "aree": [(x, x) for x in aree],
        "mansioni": [(x, x) for x in sorted(mansioni, key=str.casefold)],
        "persone": persone,
    }


class PerimetroMixin:
    """Campi del perimetro di persone, condivisi da modello e generazione."""

    def _add_perimetro_fields(self, scelte: dict, iniziale: Perimetro) -> None:
        def _multi(nome, label, help_text=""):
            self.fields[nome] = forms.MultipleChoiceField(
                label=label, required=False, choices=scelte.get(nome, []), help_text=help_text,
                widget=forms.SelectMultiple(attrs=_SELECT_MULTI),
            )

        _multi("reparti", "Reparti")
        _multi("aree", "Aree aziendali")
        _multi("mansioni", "Mansioni")
        _multi("persone", "Persone specifiche", "Vuoto = tutte le persone che rispettano gli altri filtri.")
        self.fields["includi_cessati"] = forms.BooleanField(label="Includi il personale cessato", required=False)
        if not self.is_bound:
            self.initial.update({
                "reparti": iniziale.reparti, "aree": iniziale.aree, "mansioni": iniziale.mansioni,
                "persone": [str(p) for p in iniziale.persone], "includi_cessati": iniziale.includi_cessati,
            })

    def perimetro(self) -> Perimetro:
        data = self.cleaned_data
        return Perimetro.from_dict({
            "reparti": data.get("reparti") or [], "aree": data.get("aree") or [],
            "mansioni": data.get("mansioni") or [], "persone": data.get("persone") or [],
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

    class Meta:
        model = ReportModello
        fields = [
            "nome", "descrizione", "titolo_documento", "sottotitolo", "destinatario", "norme",
            "riservatezza", "periodo_tipo", "data_da", "data_a", "redatto_da", "verificato_da", "approvato_da",
        ]
        labels = {
            "nome": "Nome del modello", "descrizione": "Descrizione (a cosa serve)",
            "titolo_documento": "Titolo stampato sul documento", "sottotitolo": "Sottotitolo",
            "destinatario": "Destinatario predefinito", "riservatezza": "Classificazione",
            "periodo_tipo": "Periodo predefinito", "data_da": "Dal", "data_a": "Al",
            "redatto_da": "Redatto da", "verificato_da": "Verificato da", "approvato_da": "Approvato da",
        }
        widgets = {
            "data_da": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_a": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, scelte: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sottotitolo"].help_text = "Ammessi i segnaposto, es. {{periodo}}."
        if not self.is_bound:
            self.initial["norme"] = list(self.instance.norme or [])
        self._add_perimetro_fields(scelte or {}, Perimetro.from_dict(self.instance.filtri))

    def clean(self):
        return self._clean_periodo(super().clean())

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.norme = list(self.cleaned_data.get("norme") or [])
        obj.filtri = self.perimetro().as_dict()
        if commit:
            obj.save()
        return obj


def _scelte_sezioni(request) -> list[tuple[str, list[tuple[str, str]]]]:
    return [(gruppo, [(s.key, s.titolo) for s in voci]) for gruppo, voci in catalogo.catalogo_per_gruppo(request)]


def _scelte_colonne() -> list[tuple[str, str]]:
    return [(f"{s.key}:{k}", label) for s in catalogo.catalogo() for k, label in s.colonne]


class ReportBloccoForm(forms.ModelForm):
    mostra_indicatori = forms.BooleanField(label="Indicatori", required=False, initial=True)
    mostra_tabella = forms.BooleanField(label="Tabella", required=False, initial=True)
    mostra_note = forms.BooleanField(label="Note", required=False, initial=True)
    colonne = forms.MultipleChoiceField(required=False, choices=(), widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = ReportBlocco
        fields = ["tipo", "titolo", "testo", "sezione", "ordine"]
        widgets = {
            "ordine": forms.HiddenInput(attrs={"data-rp-ordine": "1"}),
            "testo": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
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
        self.fields["colonne"].choices = _scelte_colonne()
        self.fields["ordine"].required = False
        if self.instance and self.instance.pk and not self.is_bound:
            opzioni = self.instance.opzioni if isinstance(self.instance.opzioni, dict) else {}
            self.initial["mostra_indicatori"] = opzioni.get("mostra_indicatori", True) is not False
            self.initial["mostra_tabella"] = opzioni.get("mostra_tabella", True) is not False
            self.initial["mostra_note"] = opzioni.get("mostra_note", True) is not False
            self.initial["colonne"] = [f"{self.instance.sezione}:{c}" for c in opzioni.get("colonne") or []]

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
        if obj.tipo == ReportBlocco.TIPO_SEZIONE:
            prefisso = f"{obj.sezione}:"
            obj.opzioni = {
                "colonne": [c[len(prefisso):] for c in self.cleaned_data.get("colonne") or [] if c.startswith(prefisso)],
                "mostra_indicatori": bool(self.cleaned_data.get("mostra_indicatori")),
                "mostra_tabella": bool(self.cleaned_data.get("mostra_tabella")),
                "mostra_note": bool(self.cleaned_data.get("mostra_note")),
            }
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


class GeneraForm(PerimetroMixin, _PeriodoCleanMixin, forms.Form):
    titolo = forms.CharField(label="Titolo", max_length=200)
    sottotitolo = forms.CharField(label="Sottotitolo", max_length=200, required=False)
    destinatario = forms.CharField(label="Destinatario", max_length=200, required=False)
    periodo_tipo = forms.ChoiceField(label="Periodo", choices=ReportModello.PERIODO_CHOICES)
    data_da = forms.DateField(label="Dal", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    data_a = forms.DateField(label="Al", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
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
        if not self.is_bound:
            self.initial.update({
                "titolo": modello.titolo_documento, "sottotitolo": modello.sottotitolo,
                "destinatario": modello.destinatario, "periodo_tipo": modello.periodo_tipo,
                "data_da": modello.data_da, "data_a": modello.data_a,
            })
        self._add_perimetro_fields(scelte or {}, Perimetro.from_dict(modello.filtri))
        self.blocchi_testo = []
        for blocco in modello.blocchi.all():
            if blocco.tipo not in (ReportBlocco.TIPO_TESTO, ReportBlocco.TIPO_SEZIONE):
                continue
            nome = f"testo_{blocco.pk}"
            sezione = catalogo.get(blocco.sezione) if blocco.sezione else None
            etichetta = blocco.titolo or (sezione.titolo if sezione else "Testo")
            if blocco.tipo == ReportBlocco.TIPO_SEZIONE:
                etichetta = f"Commento sotto «{etichetta}»"
            self.fields[nome] = forms.CharField(
                label=etichetta, required=False, initial=blocco.testo,
                widget=forms.Textarea(attrs={"rows": 5 if blocco.tipo == ReportBlocco.TIPO_TESTO else 2}),
            )
            self.blocchi_testo.append((blocco, nome))

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
