"""Formularze aplikacji accounts."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from core.forms import INPUT_CSS, SELECT_CSS
from core.validators import normalize_phone_e164, phone_e164_validator

from .models import EmployeeProfile

User = get_user_model()


def _clean_phone_field(raw: str | None) -> str:
    """Normalizuje i waliduje numer telefonu z formularza.

    Akceptuje wpis z separatorami ("+48 600 100 200"), sprowadza go do ścisłego
    E.164 i waliduje; pusty wpis zwraca ``""`` (formularz konwertuje na NULL
    przez ``EmployeeProfile.save``).
    """
    normalized = normalize_phone_e164(raw)
    if normalized is None:
        return ""
    phone_e164_validator(normalized)
    return normalized


class ProfileForm(forms.ModelForm):
    """Formularz edycji profilu pracownika (telefon, motyw, ID pracownika)."""

    class Meta:
        model = EmployeeProfile
        fields = ["phone", "employee_id", "theme_preference", "preferred_language"]
        labels = {
            "phone": _("Telefon"),
            "employee_id": _("Identyfikator pracownika"),
            "theme_preference": _("Motyw interfejsu"),
            "preferred_language": _("Preferowany język"),
        }
        widgets = {
            "phone": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "+48 …"}),
            "employee_id": forms.TextInput(attrs={"class": INPUT_CSS}),
            "theme_preference": forms.Select(attrs={"class": SELECT_CSS}),
            "preferred_language": forms.Select(attrs={"class": SELECT_CSS}),
        }

    def clean_phone(self):
        return _clean_phone_field(self.cleaned_data.get("phone"))


class RegisterEmployeeForm(forms.Form):
    """Wave 14-F O-1: UI dla ``accounts.services.register_employee``.

    Audyt Wave 14-E O-1: ``register_employee`` jako service istniał ale
    nie miał view'a — operator mógł tworzyć pracowników tylko przez
    ``/admin/auth/user/add/`` (raw Django form, bez HIBP walidacji hasła
    i bez profile setup w jednym kroku). Ten formularz expose'uje całą
    funkcjonalność service'u: dane User'a + profile.function/phone +
    walidację match haseł po stronie formularza.

    Walidacja hasła (min. długość, HIBP breach check) odbywa się w samym
    service (``validate_password``) — tu sprawdzamy tylko match dwóch pól
    i unikalność username (defensive, mimo że ``User.objects.create_user``
    rzuci IntegrityError gdyby duplikat się przepchnął).
    """

    username = forms.CharField(
        max_length=150,
        label=_("Login"),
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "username",
                "placeholder": "jan.kowalski",
            }
        ),
        help_text=_("Krótki identyfikator do logowania (bez spacji)."),
    )
    first_name = forms.CharField(
        max_length=150,
        label=_("Imię"),
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        label=_("Nazwisko"),
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "email",
                "placeholder": "jan.kowalski@firma.pl",
            }
        ),
    )
    function = forms.ChoiceField(
        choices=EmployeeProfile.Function.choices,
        initial=EmployeeProfile.Function.MONTAZYSTA,
        label=_("Funkcja w firmie"),
        widget=forms.Select(attrs={"class": SELECT_CSS}),
        help_text=_("Funkcja definiuje grupy RBAC i uprawnienia (Magazynierzy, Kierownicy itd.)."),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        label=_("Telefon"),
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "tel",
                "placeholder": "+48 …",
            }
        ),
    )
    password1 = forms.CharField(
        min_length=10,
        label=_("Hasło"),
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "new-password",
            }
        ),
        help_text=_(
            "Min. 10 znaków. Hasło jest sprawdzane przez Have I Been Pwned — "
            "wycieki publicznych baz są odrzucane."
        ),
    )
    password2 = forms.CharField(
        min_length=10,
        label=_("Potwierdź hasło"),
        widget=forms.PasswordInput(attrs={"class": INPUT_CSS, "autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError(_("Login jest wymagany."))
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("Użytkownik o takim loginie już istnieje."))
        return username

    def clean_phone(self):
        return _clean_phone_field(self.cleaned_data.get("phone"))

    def clean(self):
        cleaned = super().clean()
        pwd1 = cleaned.get("password1")
        pwd2 = cleaned.get("password2")
        if pwd1 and pwd2 and pwd1 != pwd2:
            self.add_error("password2", _("Hasła nie pasują do siebie."))
        return cleaned


class PlanerAuthenticationForm(AuthenticationForm):
    """Formularz logowania z tłumaczalnym placeholderem na polu loginu.

    Rozszerza ``AuthenticationForm`` tylko o ``placeholder`` (przez
    ``gettext_lazy``), żeby tekst podpowiedzi reagował na język UI zamiast
    być wpisanym na stałe w szablonie.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.setdefault("placeholder", _("np. jan.kowalski"))
