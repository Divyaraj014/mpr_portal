from django.core.management.base import BaseCommand

from accounts.models import District

# Rajasthan districts as of the January 2025 reorganisation: the 33 long-standing
# districts plus the 8 new ones retained after the 2023 additions were reviewed.
# Verify against the latest state notification before a production rollout —
# district boundaries have changed several times recently. Admins can add/remove
# any district from the Districts page.
DISTRICTS = [
    "Ajmer", "Alwar", "Balotra", "Banswara", "Baran", "Barmer", "Beawar",
    "Bharatpur", "Bhilwara", "Bikaner", "Bundi", "Chittorgarh", "Churu", "Dausa",
    "Deeg", "Dholpur", "Didwana-Kuchaman", "Dungarpur", "Hanumangarh", "Jaipur",
    "Jaisalmer", "Jalore", "Jhalawar", "Jhunjhunu", "Jodhpur", "Karauli",
    "Khairthal-Tijara", "Kota", "Kotputli-Behror", "Nagaur", "Pali", "Phalodi",
    "Pratapgarh", "Rajsamand", "Salumbar", "Sawai Madhopur", "Sikar", "Sirohi",
    "Sri Ganganagar", "Tonk", "Udaipur",
]


class Command(BaseCommand):
    help = "Seed Rajasthan districts (idempotent — safe to re-run)."

    def handle(self, *args, **options):
        added = sum(District.objects.get_or_create(name=name)[1] for name in DISTRICTS)
        self.stdout.write(self.style.SUCCESS(
            f"Districts ensured: {len(DISTRICTS)} total, {added} newly added."))
