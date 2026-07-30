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

class MPREntryFormTests(TestCase):
    def test_each_section_gets_only_its_own_fields(self):
        for kind, expected in MPREntry.FIELDS.items():
            self.assertEqual(list(entry_form_class(kind).base_fields), expected, kind)

    def test_django_admin_offers_the_same_fields_as_the_filling_form(self):
        # Admin was the one path that could write a training row an award level.
        entry_admin = MPREntryAdmin(MPREntry, AdminSite())
        for kind, expected in MPREntry.FIELDS.items():
            fields = entry_admin.get_fields(None, MPREntry(kind=kind))
            self.assertEqual(fields[len(entry_admin.BASE_FIELDS):], expected, kind)
            for other in set(sum(MPREntry.FIELDS.values(), [])) - set(expected):
                self.assertNotIn(other, fields, f"{other} leaked into {kind}")
        self.assertEqual(entry_admin.get_readonly_fields(None, MPREntry()), ("kind",))

    def test_training_labels_and_save(self):
        form_cls = entry_form_class(MPREntry.TRAINING)
        self.assertEqual(form_cls.base_fields["title"].label, "Topic")
        period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        author = User.objects.create_user("dio.one", password="x")
        form = form_cls({"title": "GIS basics", "date": "2026-07-01", "to_date": "2026-07-03",
                         "participants": 40, "target_user": "Patwaris", "remarks": ""})
        self.assertTrue(form.is_valid(), form.errors)
        entry = form.save(commit=False)
        entry.period, entry.author, entry.kind = period, author, MPREntry.TRAINING
        entry.save()
        self.assertEqual(period.entries.get().participants, 40)

class MPRFillFlowTests(TestCase):
    def setUp(self):
        self.pl = User.objects.create_user("pl.one", password="x", is_pl=True,
                                           must_change_password=False)
        self.period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        self.client.force_login(self.pl)

    def test_month_page_lists_every_section_for_a_pl(self):
        Project.objects.create(name="Sarathi", prism_id="PR-01", leader=self.pl)
        resp = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        for _, label in MPREntry.KIND_CHOICES:
            self.assertContains(resp, escape(label))

    def test_a_pl_with_no_project_has_nothing_to_file(self):
        # Every project row belongs to a project now, so an unassigned PL has no report.
        resp = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertContains(resp, "Nothing to fill")
        self.assertEqual(self.client.post(
            reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
            {"description": "Nowhere to put this"}).status_code, 404)
        self.assertFalse(MPREntry.objects.exists())

    def test_each_project_is_its_own_report(self):
        vahan = Project.objects.create(name="Vahan", prism_id="PR-01", leader=self.pl)
        emitra = Project.objects.create(name="eMitra", prism_id="PR-02", leader=self.pl)

        month = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertTrue(month.context["split"])
        self.assertContains(month, "Vahan")
        self.assertContains(month, "eMitra")
        self.assertNotContains(month, "Major events planned")  # sections live one click in

        add = reverse("mpr_entry_add", args=[self.period.pk, MPREntry.EVENT])
        resp = self.client.post(f"{add}?scope=project&project={vahan.pk}",
                                {"event_category": "launch", "date": "2026-07-09",
                                 "description": "e-challan app launch"})
        self.assertRedirects(resp, reverse("mpr_project_report", args=[self.period.pk, vahan.pk]))
        self.assertEqual(MPREntry.objects.get().project, vahan)

        # The row shows on its own project's page and nowhere else.
        self.assertContains(
            self.client.get(reverse("mpr_project_report", args=[self.period.pk, vahan.pk])),
            "e-challan app launch")
        self.assertNotContains(
            self.client.get(reverse("mpr_project_report", args=[self.period.pk, emitra.pk])),
            "e-challan app launch")

    def test_cannot_file_into_a_project_you_do_not_lead(self):
        mine = Project.objects.create(name="Vahan", prism_id="PR-01", leader=self.pl)
        other = Project.objects.create(
            name="Theirs", prism_id="PR-02",
            leader=User.objects.create_user("pl.other", password="x", is_pl=True))
        add = reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT])
        self.assertEqual(self.client.post(f"{add}?scope=project&project={other.pk}",
                                          {"description": "Not mine"}).status_code, 404)
        self.assertEqual(self.client.get(
            reverse("mpr_project_report", args=[self.period.pk, other.pk])).status_code, 404)
        self.assertFalse(MPREntry.objects.exists())
        # Their own project is reachable.
        self.assertEqual(self.client.get(
            reverse("mpr_project_report", args=[self.period.pk, mine.pk])).status_code, 200)

    def test_both_roles_get_separate_district_and_project_reports(self):
        District.objects.create(name="Udaipur", officer=self.pl)
        project = Project.objects.create(name="Vahan", prism_id="PR-1042", leader=self.pl)
        User.objects.filter(pk=self.pl.pk).update(is_dio=True)
        district_url = reverse("mpr_district_report", args=[self.period.pk])
        project_url = reverse("mpr_project_report", args=[self.period.pk, project.pk])

        # The month page picks a report; it does not stack them.
        month = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertTrue(month.context["split"])
        self.assertContains(month, district_url)
        self.assertContains(month, project_url)
        self.assertContains(month, "Udaipur")
        self.assertNotContains(month, "Major events planned")

        # A row filed under one report stays under that one, and returns there.
        add = reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT])
        resp = self.client.post(f"{add}?scope=district", {"description": "District rollout"})
        self.assertRedirects(resp, district_url)
        self.client.post(f"{add}?scope=project&project={project.pk}",
                         {"description": "Project rollout"})

        district, proj = self.client.get(district_url), self.client.get(project_url)
        self.assertContains(district, "District rollout")
        self.assertNotContains(district, "Project rollout")
        self.assertContains(proj, "Project rollout")
        self.assertNotContains(proj, "District rollout")
        # Enhancements and the figures table belong to the project report only.
        self.assertNotContains(district, "Major enhancements")
        self.assertContains(proj, "Major enhancements")
        self.assertNotContains(district, "Vahan")

    def test_a_report_you_do_not_owe_is_not_reachable(self):
        # self.pl holds no district, so the district report page is not theirs.
        self.assertEqual(
            self.client.get(reverse("mpr_district_report", args=[self.period.pk])).status_code,
            404)

    def test_one_report_means_no_chooser_at_all(self):
        project = Project.objects.create(name="Vahan", prism_id="PR-01", leader=self.pl)
        resp = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertFalse(resp.context["split"])
        self.assertContains(resp, "Major events planned")  # sections right there
        # No query string needed — there is only one report it could belong to.
        self.client.post(reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
                         {"description": "Rollout"})
        entry = MPREntry.objects.get()
        self.assertEqual((entry.scope, entry.project), (MPREntry.PROJECT, project))

    def test_cannot_file_into_a_report_you_do_not_owe(self):
        add = reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT])
        # self.pl is not a DIO, so the district report isn't theirs to fill.
        self.assertEqual(self.client.post(f"{add}?scope=district",
                                          {"description": "Not mine"}).status_code, 404)
        self.assertFalse(MPREntry.objects.exists())

        dio = User.objects.create_user("dio.solo", password="x", is_dio=True,
                                       must_change_password=False)
        self.client.force_login(dio)
        # ...and the PL-only section isn't part of a district report.
        self.assertEqual(self.client.post(
            reverse("mpr_entry_add", args=[self.period.pk, MPREntry.ENHANCEMENT]),
            {"title": "Nope"}).status_code, 404)
        self.assertFalse(MPREntry.objects.exists())

    def test_dio_does_not_get_the_pl_only_section(self):
        dio = User.objects.create_user("dio.two", password="x", is_dio=True,
                                       must_change_password=False)
        self.client.force_login(dio)
        resp = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertNotContains(resp, "Major enhancements")

    def test_add_entry_then_see_it_on_the_month_page(self):
        Project.objects.create(name="Sarathi", prism_id="PR-01", leader=self.pl)
        resp = self.client.post(
            reverse("mpr_entry_add", args=[self.period.pk, MPREntry.AWARD]),
            {"award_level": "national", "title": "Digital India Award",
             "date": "2026-07-12", "description": "For the Vahan rollout."},
        )
        self.assertRedirects(resp, reverse("mpr_month", args=[self.period.pk]))
        entry = MPREntry.objects.get()
        self.assertEqual((entry.author, entry.kind), (self.pl, MPREntry.AWARD))
        self.assertContains(self.client.get(reverse("mpr_month", args=[self.period.pk])),
                            "Digital India Award")

    def test_closed_month_rejects_new_entries(self):
        MPRPeriod.objects.filter(pk=self.period.pk).update(is_open=False)
        resp = self.client.post(
            reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
            {"description": "Anything"})
        self.assertRedirects(resp, reverse("mpr_month", args=[self.period.pk]))
        self.assertFalse(MPREntry.objects.exists())

    def test_cannot_edit_someone_elses_entry(self):
        other = User.objects.create_user("pl.two", password="x", is_pl=True)
        entry = MPREntry.objects.create(period=self.period, author=other,
                                        kind=MPREntry.SIGNIFICANT, description="Theirs")
        resp = self.client.get(
            reverse("mpr_entry_edit", args=[self.period.pk, MPREntry.SIGNIFICANT, entry.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_parameters_carry_last_months_reporting_figure_forward(self):
        project = Project.objects.create(name="Vahan", prism_id="PR-77", leader=self.pl)
        param = ProjectParameter.objects.create(project=project, name="Challans issued")
        june = MPRPeriod.objects.create(year=2026, month=6, due_date="2026-07-05")
        ParameterValue.objects.create(period=june, parameter=param, reporting_month="1,204")

        url = reverse("mpr_parameters", args=[self.period.pk, project.pk])
        self.client.get(url)
        value = ParameterValue.objects.get(period=self.period, parameter=param)
        self.assertEqual(value.previous_month, "1,204")

        resp = self.client.post(url, {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-0-id": str(value.pk), "form-0-previous_month": "1,204",
            "form-0-reporting_month": "1,318", "form-0-cumulative": "48,902",
        })
        self.assertRedirects(resp, reverse("mpr_month", args=[self.period.pk]))
        value.refresh_from_db()
        self.assertEqual(value.reporting_month, "1,318")

    def test_parameters_of_someone_elses_project_are_not_reachable(self):
        other = User.objects.create_user("pl.three", password="x", is_pl=True)
        project = Project.objects.create(name="Theirs", prism_id="PR-99", leader=other)
        resp = self.client.get(reverse("mpr_parameters", args=[self.period.pk, project.pk]))
        self.assertEqual(resp.status_code, 404)


class LockFlowTests(TestCase):
    """Freezing a month, and getting it reopened."""

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

    def test_locking_asks_first_and_says_unlocking_needs_an_admin(self):
        resp = self.client.get(reverse("mpr_lock", args=[self.period.pk]))
        self.assertContains(resp, "Lock July 2026?")
        self.assertContains(resp, "request an unlock")
        self.assertContains(resp, "admin to reopen")
        self.assertFalse(MPRLock.objects.exists())  # GET never locks

        self.lock()
        self.assertTrue(MPRLock.objects.exists())
        # Already locked: the confirm page bounces instead of offering a second lock.
        self.assertRedirects(self.client.get(reverse("mpr_lock", args=[self.period.pk])),
                             reverse("mpr_month", args=[self.period.pk]))
        self.assertEqual(MPRLock.objects.count(), 1)

    def test_locking_freezes_adds_edits_and_deletes(self):
        self.assertRedirects(self.lock(), reverse("mpr_month", args=[self.period.pk]))
        self.assertTrue(MPRLock.objects.filter(period=self.period, user=self.user).exists())

        self.client.post(reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
                         {"description": "Sneaked in after locking"})
        self.client.post(reverse("mpr_entry_delete", args=[self.entry.pk]))
        self.assertEqual([e.description for e in MPREntry.objects.all()], ["Rollout"])

        month = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertNotContains(month, "Lock month")
        self.assertContains(month, "Request unlock")

    def test_locked_figures_ignore_a_posted_change(self):
        project = Project.objects.create(name="eMitra", prism_id="PR-31", leader=self.user)
        param = ProjectParameter.objects.create(project=project, name="Transactions")
        url = reverse("mpr_parameters", args=[self.period.pk, project.pk])
        self.client.get(url)
        value = ParameterValue.objects.get(parameter=param)
        self.lock()
        self.client.post(url, {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                               "form-0-id": str(value.pk), "form-0-reporting_month": "9,999"})
        value.refresh_from_db()
        self.assertEqual(value.reporting_month, "")

    def test_unlock_request_then_admin_reopens(self):
        self.lock()
        self.client.post(reverse("mpr_unlock_request", args=[self.period.pk]),
                         {"reason": "Participant count was wrong."})
        lock = MPRLock.objects.get()
        self.assertTrue(lock.unlock_requested)
        self.assertEqual(lock.unlock_reason, "Participant count was wrong.")

        self.client.force_login(self.admin)
        report = self.client.get(reverse("report_status"))
        self.assertContains(report, "Participant count was wrong.")
        self.client.post(reverse("report_unlock", args=[lock.pk]))
        self.assertFalse(MPRLock.objects.exists())

        # Reopened: the user can edit again.
        self.client.force_login(self.user)
        self.client.post(reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
                         {"description": "Added after reopening"})
        self.assertEqual(MPREntry.objects.count(), 2)
