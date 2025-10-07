from django import forms
from .models import Case, Attachment, Lab
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError



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
    new_pin = forms.CharField(
        min_length=6, max_length=10,
        validators=[RegexValidator(r'^[A-Za-z0-9]{6,10}$',
                                   'PIN muss 6–10 Zeichen (nur Buchstaben/Ziffern) haben.')]
    )
    

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
    

class CaseForm(forms.ModelForm):
    class Meta:
        model = Case
        exclude = ['case_code']   # or list all fields EXCEPT case_code
        fields = ['patient_name', 'patient_dob', 'lab']
        widgets = {
            'patient_dob': forms.DateInput(attrs={'type': 'date'}),
        }


class LabStatusForm(forms.ModelForm):
    class Meta:
        model = Case
        fields = ['substage', 'eta']
        widgets = {
            'substage': forms.Select(attrs={'class': 'form-select'}),
            'eta': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class LabReturnForm(forms.ModelForm):
    class Meta:
        model = Case
        fields = ['returned_tracking_no', 'returned_at']
        widgets = {
            'returned_tracking_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sendungsnummer'}),
            'returned_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        }

class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ['file', 'label']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Beschreibung (optional)'}),
        }



# Forms for managing Labs and Lab Users
class LabForm(forms.ModelForm):
    class Meta:
        model = Lab
        fields = ["name", "contact"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Laborname"}),
            "contact": forms.TextInput(attrs={"class": "form-control", "placeholder": "Kontakt (optional)"}),
        }


class LabUserCreateForm(forms.Form):
    lab = forms.ModelChoiceField(queryset=Lab.objects.all(), widget=forms.Select(attrs={'class':'form-select'}))
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class':'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class':'form-control'}))
    password1 = forms.CharField(min_length=8, widget=forms.PasswordInput(attrs={'class':'form-control'}))
    password2 = forms.CharField(min_length=8, widget=forms.PasswordInput(attrs={'class':'form-control'}))
    is_active = forms.BooleanField(required=False, initial=True)

    def clean_username(self):
        u = self.cleaned_data['username']
        if User.objects.filter(username__iexact=u).exists():
            raise ValidationError("Benutzername ist bereits vergeben.")
        return u

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get('password1'), cd.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', "Passwörter stimmen nicht überein.")
        return cd
    

class LabUserEditForm(forms.Form):
    lab = forms.ModelChoiceField(queryset=Lab.objects.all(), widget=forms.Select(attrs={'class':'form-select'}))
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class':'form-control'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class':'form-control'}))
    is_active = forms.BooleanField(required=False)
    password1 = forms.CharField(required=False, min_length=8, widget=forms.PasswordInput(attrs={'class':'form-control'}))
    password2 = forms.CharField(required=False, min_length=8, widget=forms.PasswordInput(attrs={'class':'form-control'}))

    def __init__(self, *args, user_instance: User=None, **kwargs):
        self.user_instance = user_instance
        super().__init__(*args, **kwargs)

    def clean_username(self):
        u = self.cleaned_data['username']
        qs = User.objects.filter(username__iexact=u)
        if self.user_instance:
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise ValidationError("Benutzername ist bereits vergeben.")
        return u

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get('password1'), cd.get('password2')
        if p1 or p2:
            if not p1 or not p2 or p1 != p2:
                self.add_error('password2', "Passwörter stimmen nicht überein.")
        return cd