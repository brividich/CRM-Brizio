from django import forms
from django.utils import timezone

from .models import AssetReportSchedule


class AssetReportScheduleForm(forms.ModelForm):
    class Meta:
        model = AssetReportSchedule
        fields = ["name", "asset_type", "asset_category", "reparto", "include_snmp", "frequency", "next_run", "export_pdf", "export_excel", "enabled"]
        widgets = {"next_run": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})}

    def clean(self):
        data = super().clean()
        if not data.get("export_pdf") and not data.get("export_excel"):
            raise forms.ValidationError("Seleziona almeno un formato di esportazione.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.anchor_day = timezone.localtime(obj.next_run).day
        if commit:
            obj.save()
        return obj
