from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Konfiguracja aplikacji core (modele abstrakcyjne, walidatory, healthz)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Rdzeń aplikacji"

    def ready(self) -> None:
        """Twarde limity bezpieczeństwa, instalowane raz przy starcie procesu."""
        from PIL import Image

        # Pillow decompression-bomb mitigation — bez tego ogromny PNG (np. 30000x30000)
        # potrafi zjeść kilkadziesiąt GB RAM zanim trafi do naszego validatora.
        # 50 megapikseli ~ 7000x7000 — komfortowy zapas nad realnymi zdjęciami DSLR.
        Image.MAX_IMAGE_PIXELS = 50_000_000
