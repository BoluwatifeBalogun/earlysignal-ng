from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.services import predictor


class Command(BaseCommand):
    help = "One step setup: migrate, train the model if needed, load demo data."

    def handle(self, *args, **opts):
        call_command("migrate", verbosity=0)
        self.stdout.write("Database ready.")
        if not predictor.model_ready():
            call_command("train_model")
        else:
            self.stdout.write("Trained model found.")
        call_command("seed_demo")
        self.stdout.write(self.style.SUCCESS("Done. Start the server with: python manage.py runserver"))
