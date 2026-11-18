"""Development-only: create a superuser from environment variables (no hardcoded password).

    DEV_ADMIN_USERNAME, DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD must be set. For real setups use `createsuperuser`."""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create a development superuser from environment variables."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Only available when DJANGO_DEBUG=True. Use `createsuperuser` in production.")
        username = os.environ.get("DEV_ADMIN_USERNAME")
        email = os.environ.get("DEV_ADMIN_EMAIL")
        password = os.environ.get("DEV_ADMIN_PASSWORD")
        if not (username and email and password):
            raise CommandError("Set DEV_ADMIN_USERNAME, DEV_ADMIN_EMAIL and DEV_ADMIN_PASSWORD.")
        if User.objects.filter(username=username).exists():
            self.stdout.write("User already exists; nothing to do.")
            return
        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser {username} created."))
