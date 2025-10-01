from django import forms
from .models import Case

class CaseCreateForm(forms.ModelForm):
    class Meta:
        model = Case
        fields = ["patient_name", "patient_dob", "lab"]
        widgets = {
            "patient_name": forms.TextInput(attrs={"class": "form-control"}),
            "patient_dob": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "lab": forms.Select(attrs={"class": "form-select"}),
        }
from django import forms

class LabSearchForm(forms.Form):
    case_code = forms.CharField(label="Fallnummer", max_length=32)


class LabActionForm(forms.Form):
    # make PIN optional; we’ll ignore it for logged-in LAB users
    code = forms.CharField(label="Schutzcode (PIN)", max_length=6, required=False)
    note = forms.CharField(label="Notiz (optional)", required=False,
                           widget=forms.Textarea(attrs={"rows": 2}))
    action = forms.ChoiceField(choices=[
        ("receive_lab", "Im Labor eingegangen"),
        ("return_lab", "Zurück an Praxis"),
        ("receive_clinic", "In Praxis erhalten"),
    ])


class GlobalPinForm(forms.Form):
    current_pin = forms.CharField(label="Aktueller PIN", max_length=6, required=False)
    new_pin = forms.CharField(label="Neuer PIN (6-stellig)", max_length=6)
    confirm_pin = forms.CharField(label="Bestätigen", max_length=6)

    def clean(self):
        data = super().clean()
        if data.get("new_pin") != data.get("confirm_pin"):
            raise forms.ValidationError("PINs stimmen nicht überein.")
        if not data.get("new_pin").isdigit() or len(data.get("new_pin")) != 6:
            raise forms.ValidationError("PIN muss 6 Ziffern haben.")
        return data
    



class LabPinForm(forms.Form):
    new_pin = forms.CharField(label="Neuer PIN (6-stellig)", max_length=6)
    confirm_pin = forms.CharField(label="Bestätigen", max_length=6)

    def clean(self):
        data = super().clean()
        if data.get("new_pin") != data.get("confirm_pin"):
            raise forms.ValidationError("PINs stimmen nicht überein.")
        if not data.get("new_pin").isdigit() or len(data.get("new_pin")) != 6:
            raise forms.ValidationError("PIN muss 6 Ziffern haben.")
        return data
    

class PraxisPinForm(forms.Form):
    new_pin = forms.CharField(label="Neuer Praxis-PIN (6-stellig)", max_length=6)
    confirm_pin = forms.CharField(label="Bestätigen", max_length=6)

    def clean(self):
        d = super().clean()
        if d.get("new_pin") != d.get("confirm_pin"):
            raise forms.ValidationError("PINs stimmen nicht überein.")
        if not d.get("new_pin").isdigit() or len(d.get("new_pin")) != 6:
            raise forms.ValidationError("PIN muss 6 Ziffern haben.")
        return d