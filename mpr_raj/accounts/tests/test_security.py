from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ..captcha import SESSION_KEY

User = get_user_model()


class LockoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dio.kota", password="Right@12345",
                                             must_change_password=False)

    def solve_captcha(self):
        self.client.get(reverse("captcha_image"))
        return self.client.session[SESSION_KEY][-1]

    def attempt(self, password):
        return self.client.post(reverse("login"), {
            "username": "dio.kota", "password": password, "captcha": self.solve_captcha(),
        })

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_lockout_after_the_failure_limit(self):
        for _ in range(3):
            self.attempt("Wrong@12345")
        # The right password now fails too: the pair is locked, not the password.
        self.attempt("Right@12345")
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_a_wrong_captcha_is_not_a_login_failure(self):
        # CaptchaAuthenticationForm.clean() returns early when the captcha fails,
        # so authenticate() is never called and axes never counts it.
        for _ in range(5):
            self.client.post(reverse("login"), {
                "username": "dio.kota", "password": "Right@12345", "captcha": "XXXXX",
            })
        self.attempt("Right@12345")
        self.assertIn("_auth_user_id", self.client.session)


class SecurityEventModelTests(TestCase):
    def test_labels_outlive_the_user_they_name(self):
        from ..models import SecurityEvent

        admin = User.objects.create_user("admin.one", password="x", is_staff=True)
        victim = User.objects.create_user("dio.gone", password="x")
        SecurityEvent.objects.create(
            action=SecurityEvent.USER_DELETED,
            actor=admin, actor_label=admin.username,
            target=victim, target_label=victim.username,
        )
        victim.delete()

        event = SecurityEvent.objects.get()
        self.assertIsNone(event.target)                    # FK went null
        self.assertEqual(event.target_label, "dio.gone")   # the record still reads

    def test_a_failed_login_can_name_a_user_that_never_existed(self):
        from ..models import SecurityEvent

        SecurityEvent.objects.create(
            action=SecurityEvent.LOGIN_FAIL, actor=None, actor_label="root",
        )
        self.assertEqual(SecurityEvent.objects.get().actor_label, "root")
