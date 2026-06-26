from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    """Konfiguracja aplikacji accounts (profile pracowników, auth flow)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = _("Konta i profile pracowników")

    def ready(self):
        # Import sygnałów żeby zostały zarejestrowane przy starcie aplikacji.
        from . import signals  # noqa: F401
