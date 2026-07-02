"""Formularze aplikacji accounts."""

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.forms import INPUT_CSS, SELECT_CSS
from core.validators import normalize_local_phone, phone_e164_validator

from .models import EmployeeProfile

User = get_user_model()


def _clean_phone_field(raw: str | None) -> str:
    """Normalizuje i waliduje numer telefonu z formularza.

    Numer krajowy wpisany bez prefiksu (np. "468 27 49 44" albo "0468274944")
    dostaje domyślny kierunkowy +32 (Belgia); numery zagraniczne wpisuje się
    pełne z prefiksem (+33 …). Pusty wpis zwraca ``""`` (formularz konwertuje na
    NULL przez ``EmployeeProfile.save``).
    """
    normalized = normalize_local_phone(raw)
    if normalized is None:
        return ""
    phone_e164_validator(normalized)
    return normalized


class VoicePinForm(forms.Form):
    """Ustawienie/zmiana PIN-u głosowego (drugi czynnik DTMF agenta telefonicznego).

    Waliduje format (4–6 cyfr) i zgodność powtórzenia. Odrzucenie PIN-ów zbyt
    prostych deleguje do :func:`accounts.services.set_voice_pin` (jedno źródło
    reguł) — widok łapie ``ValidationError`` i pokazuje komunikat przy polu.
    """

    new_pin = forms.CharField(
        label=_("Nowy PIN (4–6 cyfr)"),
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput(
            attrs={
                "class": INPUT_CSS,
                "inputmode": "numeric",
                "autocomplete": "off",
                "placeholder": "np. 4821",
            }
        ),
    )
    confirm_pin = forms.CharField(
        label=_("Powtórz PIN"),
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_CSS, "inputmode": "numeric", "autocomplete": "off"}
        ),
    )

    def clean_new_pin(self):
        pin = self.cleaned_data["new_pin"]
        if not pin.isdigit():
            raise forms.ValidationError(_("PIN może zawierać wyłącznie cyfry."))
        return pin

    def clean(self):
        cleaned = super().clean()
        new_pin = cleaned.get("new_pin")
        confirm_pin = cleaned.get("confirm_pin")
        if new_pin and confirm_pin and new_pin != confirm_pin:
            raise forms.ValidationError(_("PIN-y nie są identyczne."))
        return cleaned


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
        help_texts = {
            "phone": _(
                "Numer krajowy bez prefiksu (np. 468 27 49 44) — dodamy +32 automatycznie. "
                "Numer zagraniczny wpisz z prefiksem, np. +33 6 12 34 56 78."
            ),
        }
        widgets = {
            "phone": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "468 27 49 44"}),
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
                "placeholder": "468 27 49 44",
            }
        ),
        help_text=_(
            "Numer krajowy bez prefiksu (np. 468 27 49 44) — dodamy +32. "
            "Zagraniczny wpisz z prefiksem, np. +33…"
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


class BilingualPasswordResetForm(PasswordResetForm):
    """Formularz „zapomniałem hasła" wysyłający dwujęzyczny (PL+EN) mail.

    ``PasswordResetForm`` Django renderuje pojedynczy, jednojęzyczny szablon
    maila. Tutaj nadpisujemy :meth:`send_mail`, by skorzystać z firmowego,
    brandowanego i dwujęzycznego mechanizmu (``core.mailing``) — spójnego z
    pozostałymi mailami transakcyjnymi (potwierdzenie/anulowanie rezerwacji,
    przypomnienia, alerty przeglądowe). Reszta logiki (token, ochrona przed
    enumeracją kont — brak ujawnienia czy adres istnieje) pozostaje z bazowej
    klasy.
    """

    email = forms.EmailField(
        label=_("Adres e-mail"),
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": INPUT_CSS,
                "autocomplete": "email",
                "placeholder": "jan.kowalski@firma.pl",
            }
        ),
    )

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        # Import lokalny — spójny ze wzorcem w ``reservations.emails`` (unika
        # cyklicznych importów i kosztu na ścieżce, gdzie mail nie jest wysyłany).
        from core.mailing import build_bilingual_email, send_bilingual_mail

        base = getattr(settings, "EMAIL_LINK_BASE_URL", "http://localhost:8002").rstrip("/")
        reset_path = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": context["uid"], "token": context["token"]},
        )
        user = context["user"]
        valid_hours = int(getattr(settings, "PASSWORD_RESET_TIMEOUT", 259200) // 3600)
        mail_context = {
            "recipient_name": user.get_full_name() or user.get_username(),
            "reset_url": f"{base}{reset_path}",
            "valid_hours": valid_hours,
        }
        html_body, text_body = build_bilingual_email("password_reset", mail_context)
        subject = "Reset hasła / Password reset — Planer Maszyn Budowlanych"
        send_bilingual_mail(subject, html_body, text_body, [to_email])
