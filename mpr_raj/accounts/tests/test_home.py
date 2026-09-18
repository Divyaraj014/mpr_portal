from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ..captcha import SESSION_KEY
from ..models import (
    MPREntry, MPRLock, MPRPeriod,
)

User = get_user_model()

class SignInFlowTests(TestCase):
    def setUp(self):
        # Admin-created account: temp password, not yet activated.
        self.user = User(email="divyaraj.work@nic.in", name="Divyaraj")
        self.user.set_password("Temp@12345")
        self.user.save()

    def solve_captcha(self):
        self.client.get(reverse("captcha_image"))
        return self.client.session[SESSION_KEY][-1]

    def login(self, captcha):
        return self.client.post(
            reverse("login"),
            {"username": "divyaraj.work", "password": "Temp@12345", "captcha": captcha},
        )

    def test_username_is_email_prefix(self):
        self.assertEqual(self.user.username, "divyaraj.work")

    def test_captcha_image_endpoint(self):
        resp = self.client.get(reverse("captcha_image"))
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertEqual(len(self.client.session[SESSION_KEY][-1]), 5)

    def test_earlier_code_still_accepted_after_refetch(self):
        first = self.solve_captcha()
        self.solve_captcha()  # browser fetched the image again
        self.login(first)
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_captcha_blocks_login(self):
        self.solve_captcha()
        resp = self.login("XXXXX")
        self.assertContains(resp, "didn&#x27;t match")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_captcha_is_single_use(self):
        code = self.solve_captcha()
        self.login(code)
        self.client.post(reverse("logout"))
        self.login(code)  # replayed code must fail
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_first_login_forces_password_change_and_activates(self):
        resp = self.login(self.solve_captcha())
        # Logged in but middleware pins the user to the password-change page.
        self.assertRedirects(resp, reverse("dashboard"), target_status_code=302)
        resp = self.client.get(reverse("dashboard"))
        self.assertRedirects(resp, reverse("password_change"))

        resp = self.client.post(
            reverse("password_change"),
            # First login uses SetPasswordForm — no old_password field.
            {"new_password1": "My0wn-Str0ng-Pass", "new_password2": "My0wn-Str0ng-Pass"},
        )
        self.assertRedirects(resp, reverse("dashboard"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_activated)
        self.assertFalse(self.user.must_change_password)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

class DashboardTests(TestCase):
    def setUp(self):
        self.period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")

    def dash(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_due_date_reads_as_days_left(self):
        dio = User.objects.create_user("d.one", password="x", is_dio=True,
                                       must_change_password=False)
        with patch("accounts.views.home.timezone.localdate", return_value=date(2026, 7, 27)):
            self.assertContains(self.dash(dio), "Due in 9 days")
        with patch("accounts.views.home.timezone.localdate", return_value=date(2026, 8, 5)):
            self.assertContains(self.dash(dio), "Due today")
        with patch("accounts.views.home.timezone.localdate", return_value=date(2026, 8, 8)):
            self.assertContains(self.dash(dio), "3 days overdue")

    def test_admin_who_also_files_gets_both_blocks(self):
        boss = User.objects.create_user("a.boss", password="x", is_staff=True, is_dio=True,
                                        must_change_password=False)
        User.objects.create_user("d.two", password="x", is_dio=True, must_change_password=False)
        MPREntry.objects.create(period=self.period, author=boss, kind=MPREntry.SIGNIFICANT,
                                scope="district", description="Rollout")
        resp = self.dash(boss)
        self.assertContains(resp, "Your report")          # was hidden from staff before
        self.assertContains(resp, "1 entry recorded")
        self.assertContains(resp, "0 of 2 locked")
        self.assertContains(resp, "1 not started yet")

    def test_pending_unlock_requests_surface_for_admin(self):
        admin = User.objects.create_user("a.two", password="x", is_staff=True,
                                         must_change_password=False)
        dio = User.objects.create_user("d.three", password="x", is_dio=True,
                                       must_change_password=False)
        MPRLock.objects.create(period=self.period, user=dio, unlock_requested=True)
        resp = self.dash(admin)
        self.assertContains(resp, "1 of 1 locked")
        self.assertContains(resp, "1 unlock request")

    def test_sio_sees_progress_but_no_report_of_their_own(self):
        sio = User.objects.create_user("s.one", password="x", is_sio=True,
                                       must_change_password=False)
        resp = self.dash(sio)
        self.assertContains(resp, "0 of 0 locked")
        self.assertNotContains(resp, "Fill your report")

    def test_no_open_month_says_so_once(self):
        MPRPeriod.objects.filter(pk=self.period.pk).update(is_open=False)
        dio = User.objects.create_user("d.four", password="x", is_dio=True,
                                       must_change_password=False)
        resp = self.dash(dio)
        self.assertContains(resp, "No reporting month is open")
        self.assertNotContains(resp, "Fill your report")
