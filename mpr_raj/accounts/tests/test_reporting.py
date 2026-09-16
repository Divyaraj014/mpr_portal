from datetime import date
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from .. import exports
from ..admin import MPREntryAdmin
from ..captcha import SESSION_KEY
from ..forms import entry_form_class
from ..models import (
    District, MPREntry, MPRLock, MPRPeriod, ParameterValue, Project, ProjectParameter,
)

User = get_user_model()


class ReportsTests(TestCase):
    """Filing status, per-category reports, exports."""

    def setUp(self):
        self.user = User.objects.create_user("dio.jaipur", password="x", name="Kavita Bhargava",
                                             is_dio=True, must_change_password=False)
        self.admin = User.objects.create_user("admin.one", password="x", is_staff=True,
                                              must_change_password=False)
        self.period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        self.entry = MPREntry.objects.create(period=self.period, author=self.user,
                                             kind=MPREntry.SIGNIFICANT, description="Rollout")
        self.client.force_login(self.user)

    def lock(self):
        return self.client.post(reverse("mpr_lock", args=[self.period.pk]))

    def test_reports_show_per_section_counts_and_are_closed_to_fillers(self):
        MPREntry.objects.create(period=self.period, author=self.user, kind=MPREntry.TRAINING,
                                title="GIS basics", participants=12)
        self.assertEqual(self.client.get(reverse("report_status")).status_code, 302)  # DIO -> login
        self.client.logout()
        self.assertEqual(self.client.get(reverse("report_status")).status_code, 302)  # anonymous -> login

        self.client.force_login(self.admin)
        resp = self.client.get(reverse("report_status"), {"period": self.period.pk})
        self.assertContains(resp, "Kavita Bhargava")
        row = next(r for r in resp.context["rows"] if r["user"] == self.user)
        kinds = [k for k, _ in MPREntry.KIND_CHOICES]
        self.assertEqual(row["counts"][kinds.index(MPREntry.TRAINING)], 1)
        self.assertEqual(row["counts"][kinds.index(MPREntry.SIGNIFICANT)], 1)
        self.assertEqual(row["counts"][kinds.index(MPREntry.AWARD)], 0)
        self.assertEqual(row["total"], 2)

    def test_export_carries_every_section_in_every_format(self):
        project = Project.objects.create(name="eMitra", prism_id="PR-31", leader=self.user)
        param = ProjectParameter.objects.create(project=project, name="Transactions")
        ParameterValue.objects.create(period=self.period, parameter=param,
                                      reporting_month="9,120", cumulative="4,10,332")
        MPREntry.objects.create(period=self.period, author=self.user, kind=MPREntry.AWARD,
                                scope=MPREntry.PROJECT, project=project,
                                award_level="national", title="Digital India Award",
                                date="2026-07-12")

        tables = exports.tables(self.period)
        awards = next(t for t in tables if t["title"] == "Major awards")
        self.assertEqual(awards["headers"][:3], ["Filed by", "Project", "Award level"])
        # Project is a column, not a form field — it comes from the report it was filed in.
        self.assertEqual(awards["rows"],
                         [["Kavita Bhargava", "eMitra (PR-31)", "National",
                           "Digital India Award", "12-07-2026", "", ""]])
        figures = next(t for t in tables if t["title"] == "Project parameters")
        self.assertEqual(figures["rows"], [[project.code, "eMitra", "PR-31", "Kavita Bhargava",
                                            "Transactions", "", "9,120", "4,10,332"]])
        # Every section gets a block, even the empty ones.
        self.assertEqual(len(tables), len(MPREntry.KIND_CHOICES) + 1)

        self.client.force_login(self.admin)
        for fmt, magic in [("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("docx", b"PK")]:
            resp = self.client.get(reverse("report_export", args=[self.period.pk, fmt]))
            self.assertEqual(resp.status_code, 200, fmt)
            self.assertTrue(resp.content.startswith(magic), fmt)
            self.assertIn(f'filename="MPR July 2026.{fmt}"', resp["Content-Disposition"])
        self.assertContains(self.client.get(
            reverse("report_export", args=[self.period.pk, "csv"])), "Digital India Award")

    def test_each_category_is_its_own_report_and_its_own_download(self):
        MPREntry.objects.create(period=self.period, author=self.user, kind=MPREntry.TRAINING,
                                scope="district", title="GIS basics", participants=12)
        self.client.force_login(self.admin)

        # The index lists every category with its size and a way in.
        index = self.client.get(reverse("reports"), {"period": self.period.pk})
        for _, label in MPREntry.KIND_CHOICES:
            self.assertContains(index, escape(label))
        self.assertContains(index, "Project parameters")
        self.assertContains(index, reverse("report_table", args=[MPREntry.TRAINING]))

        # A category page shows only its own rows, under its own headers.
        training = self.client.get(reverse("report_table", args=[MPREntry.TRAINING]),
                                   {"period": self.period.pk})
        self.assertContains(training, "GIS basics")
        self.assertContains(training, "No. of participants")
        self.assertNotContains(training, "Rollout")          # the SIGNIFICANT row from setUp
        self.assertNotContains(training, "Award level")

        empty = self.client.get(reverse("report_table", args=[MPREntry.AWARD]),
                                {"period": self.period.pk})
        self.assertContains(empty, "Nothing filed here yet")
        self.assertEqual(self.client.get(reverse("report_table", args=["nonsense"]),
                                         {"period": self.period.pk}).status_code, 404)

        # ...and downloads the same rows the page showed, in any format.
        url = reverse("report_export", args=[self.period.pk, "csv"])
        one = self.client.get(url, {"only": MPREntry.TRAINING})
        self.assertContains(one, "GIS basics")
        self.assertNotContains(one, "Rollout")
        self.assertNotContains(one, "Major awards")          # only the asked-for block
        self.assertIn("Major training.csv", one["Content-Disposition"])
        for fmt in ["xlsx", "docx", "pdf"]:
            resp = self.client.get(reverse("report_export", args=[self.period.pk, fmt]),
                                   {"only": MPREntry.TRAINING})
            self.assertIn(resp.status_code, (200, 503), fmt)  # 503 only if WeasyPrint libs absent
        self.assertEqual(self.client.get(url, {"only": "nonsense"}).status_code, 404)

        # The whole month still comes down in one file.
        every = self.client.get(url)
        self.assertContains(every, "Major awards")
        self.assertContains(every, "GIS basics")

    def test_fillers_cannot_export(self):
        # self.user is the DIO — monitoring and exports are admin/SIO only.
        resp = self.client.get(reverse("report_export", args=[self.period.pk, "xlsx"]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_sio_can_monitor_but_not_reopen(self):
        self.lock()
        sio = User.objects.create_user("sio.one", password="x", is_sio=True,
                                       must_change_password=False)
        self.client.force_login(sio)
        self.assertContains(self.client.get(reverse("report_status")), "Kavita Bhargava")
        self.assertEqual(
            self.client.post(reverse("report_unlock", args=[MPRLock.objects.get().pk])).status_code, 302)
        self.assertTrue(MPRLock.objects.exists())

    def test_group_leader_monitors_like_an_sio(self):
        self.lock()
        gl = User.objects.create_user("gl.one", password="x", is_gl=True,
                                      must_change_password=False)
        self.client.force_login(gl)
        self.assertContains(self.client.get(reverse("report_status")), "Kavita Bhargava")
        self.assertEqual(self.client.get(reverse("reports")).status_code, 200)
        # Read-only, same as an SIO: reopening someone's month stays admin-only.
        self.client.post(reverse("report_unlock", args=[MPRLock.objects.get().pk]))
        self.assertTrue(MPRLock.objects.exists())
