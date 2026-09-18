from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
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


class RecordTests(TestCase):
    def request(self, **meta):
        request = RequestFactory().get("/")
        request.META.update(meta)
        return request

    def test_a_spoofed_forwarded_header_does_not_change_the_logged_ip(self):
        from ..models import SecurityEvent
        from ..security import record

        request = self.request(REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4")
        record(SecurityEvent.LOGIN_OK, actor_label="dio.kota", request=request)

        # No trusted-proxy count is configured by default, so the client-supplied
        # header must not win. A forgeable IP is worse than no IP at all.
        self.assertEqual(SecurityEvent.objects.get().ip, "10.0.0.5")

    def test_over_long_labels_are_truncated_not_rejected(self):
        from ..models import SecurityEvent
        from ..security import record

        record(SecurityEvent.LOGIN_FAIL, actor_label="z" * 400)
        self.assertEqual(len(SecurityEvent.objects.get().actor_label), 150)

    def test_a_write_failure_does_not_propagate(self):
        from unittest.mock import patch

        from ..models import SecurityEvent
        from ..security import record

        with patch.object(SecurityEvent.objects, "create", side_effect=RuntimeError("db down")):
            record(SecurityEvent.LOGIN_OK, actor_label="dio.kota")   # must not raise
        self.assertEqual(SecurityEvent.objects.count(), 0)


class AuthSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dio.kota", password="Right@12345",
                                             must_change_password=False)

    def solve_captcha(self):
        self.client.get(reverse("captcha_image"))
        return self.client.session[SESSION_KEY][-1]

    def sign_in(self, username="dio.kota", password="Right@12345"):
        return self.client.post(reverse("login"), {
            "username": username, "password": password, "captcha": self.solve_captcha(),
        })

    def test_a_successful_sign_in_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in()
        event = SecurityEvent.objects.get(action=SecurityEvent.LOGIN_OK)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_label, "dio.kota")

    def test_a_failure_against_a_user_that_does_not_exist_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in(username="root", password="anything")
        event = SecurityEvent.objects.get(action=SecurityEvent.LOGIN_FAIL)
        self.assertIsNone(event.actor)                 # nothing to point at
        self.assertEqual(event.actor_label, "root")    # but we know what was tried

    def test_signing_out_is_recorded(self):
        from ..models import SecurityEvent

        self.sign_in()
        self.client.post(reverse("logout"))
        self.assertTrue(SecurityEvent.objects.filter(action=SecurityEvent.LOGOUT).exists())


class ViewCaptureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin.one", password="Adm!n@12345",
                                              is_staff=True, must_change_password=False)
        self.client.force_login(self.admin)

    def test_a_role_change_records_who_changed_what(self):
        from ..models import SecurityEvent

        staff = User.objects.create_user("emp.one", password="x", name="Asha",
                                         email="emp.one@nic.in")
        self.client.post(reverse("user_edit", args=[staff.pk]), {
            "email": "emp.one@nic.in", "name": "Asha", "employee_code": "", "phone": "",
            "ip_phone": "", "is_dio": "on", "is_active": "on",
        })
        event = SecurityEvent.objects.get(action=SecurityEvent.ROLE_CHANGED)
        self.assertEqual(event.actor, self.admin)     # the admin acted
        self.assertEqual(event.target, staff)         # on this person
        self.assertIn("is_dio", event.detail)
        self.assertIn("No → Yes", event.detail)

    def test_deleting_a_user_records_it_before_the_row_goes(self):
        from ..models import SecurityEvent

        doomed = User.objects.create_user("emp.gone", password="x")
        self.client.post(reverse("user_delete", args=[doomed.pk]))
        self.assertFalse(User.objects.filter(pk=doomed.pk).exists())

        event = SecurityEvent.objects.get(action=SecurityEvent.USER_DELETED)
        self.assertEqual(event.target_label, "emp.gone")   # readable after the fact
        self.assertEqual(event.actor, self.admin)

    def test_a_password_change_is_recorded(self):
        from ..models import SecurityEvent

        self.client.post(reverse("password_change"), {
            "old_password": "Adm!n@12345",
            "new_password1": "My0wn-Str0ng-Pass", "new_password2": "My0wn-Str0ng-Pass",
        })
        self.assertTrue(
            SecurityEvent.objects.filter(action=SecurityEvent.PASSWORD_CHANGED).exists())


class SecurityScreenTests(TestCase):
    def setUp(self):
        from ..models import SecurityEvent

        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)
        SecurityEvent.objects.create(action=SecurityEvent.LOGIN_OK, actor_label="dio.kota")
        SecurityEvent.objects.create(action=SecurityEvent.LOGIN_FAIL, actor_label="root")

    def test_a_non_admin_cannot_reach_it(self):
        plain = User.objects.create_user("dio.kota", password="x", must_change_password=False)
        self.client.force_login(plain)
        self.assertNotEqual(self.client.get(reverse("security_log")).status_code, 200)

    def test_an_admin_sees_every_event(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"))
        self.assertContains(resp, "dio.kota")
        self.assertContains(resp, "root")

    def test_the_user_filter_matches_a_name_with_no_account(self):
        # The whole reason this filter is a text box and not a dropdown.
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"), {"user": "root"})
        self.assertContains(resp, "root")
        self.assertNotContains(resp, "dio.kota")

    def test_the_action_filter_narrows_by_kind(self):
        from ..models import SecurityEvent

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security_log"), {"action": SecurityEvent.LOGIN_FAIL})
        self.assertEqual(len(resp.context["events"]), 1)
