from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Konfiguracja aplikacji accounts (profile pracowników, auth flow)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Konta i profile pracowników"

    def ready(self):
        # Import sygnałów żeby zostały zarejestrowane przy starcie aplikacji.
        from . import signals  # noqa: F401
