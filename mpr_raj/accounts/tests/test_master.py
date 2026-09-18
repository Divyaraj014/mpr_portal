
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from ..admin import LookupAdmin
from ..models import (
    Department, Designation, District, MPREntry, MPRPeriod, ParameterValue,
    PlaceOfPosting, Project, ProjectParameter,
)

User = get_user_model()

class AdminUserManagementTests(TestCase):
    def setUp(self):
        self.admin = User(email="boss@nic.in", is_staff=True, must_change_password=False)
        self.admin.set_password("x")
        self.admin.save()

    def test_non_staff_cannot_open_users_page(self):
        self.client.force_login(User.objects.create_user("pleb", password="x", must_change_password=False))
        self.assertNotEqual(self.client.get(reverse("user_list")).status_code, 200)

    def _roster(self):
        """Three employees who differ in every way the list can filter or sort on."""
        jaipur = PlaceOfPosting.objects.create(name="Jaipur")
        kota = PlaceOfPosting.objects.create(name="Kota")
        scientist = Designation.objects.create(name="Scientist-D")
        User.objects.create_user("zara.pl", password="x", name="Zara", is_pl=True,
                                 place_of_posting=jaipur, designation=scientist)
        User.objects.create_user("amit.dio", password="x", name="Amit", is_dio=True,
                                 place_of_posting=kota, is_active=False)
        User.objects.create_user("neha.gl", password="x", name="Neha", is_gl=True,
                                 place_of_posting=jaipur, is_activated=True)
        return jaipur, kota

    def test_user_list_shows_place_of_posting(self):
        self.client.force_login(self.admin)
        self._roster()
        self.assertContains(self.client.get(reverse("user_list")), "Place of posting")

    def test_user_list_filters(self):
        self.client.force_login(self.admin)
        jaipur, _ = self._roster()
        url = reverse("user_list")

        by_role = self.client.get(url, {"role": "is_gl"}).context["users"]
        self.assertEqual([u.username for u in by_role], ["neha.gl"])

        by_place = self.client.get(url, {"place": jaipur.pk}).context["users"]
        self.assertEqual({u.username for u in by_place}, {"zara.pl", "neha.gl"})

        by_status = self.client.get(url, {"status": "disabled"}).context["users"]
        self.assertEqual([u.username for u in by_status], ["amit.dio"])

        # Filters stack, and an empty result says so rather than looking broken.
        none = self.client.get(url, {"role": "is_gl", "status": "disabled"})
        self.assertEqual(list(none.context["users"]), [])
        self.assertContains(none, "No users match these filters")

    def test_user_list_sorts_both_ways(self):
        self.client.force_login(self.admin)
        self._roster()
        url = reverse("user_list")

        names = [u.name for u in self.client.get(url, {"sort": "name"}).context["users"]]
        self.assertEqual(names, ["", "Amit", "Neha", "Zara"])  # the admin has no name
        self.assertEqual(
            [u.name for u in self.client.get(url, {"sort": "-name"}).context["users"]],
            names[::-1])

        # An unknown sort key falls back to login ID instead of 500-ing.
        self.assertEqual(
            [u.username for u in self.client.get(url, {"sort": "drop table"}).context["users"]],
            ["amit.dio", "boss", "neha.gl", "zara.pl"])

    def test_sort_links_keep_the_active_filters(self):
        self.client.force_login(self.admin)
        jaipur, _ = self._roster()
        columns = self.client.get(reverse("user_list"),
                                  {"place": jaipur.pk, "sort": "name"}).context["columns"]
        by_label = {c["label"]: c for c in columns}
        self.assertIn(f"place={jaipur.pk}", by_label["Name"]["url"])
        # The sorted column offers the reverse; the others start ascending.
        self.assertIn("sort=-name", by_label["Name"]["url"])
        self.assertEqual(by_label["Name"]["arrow"], "▲")
        self.assertIn("sort=roles", by_label["Roles"]["url"])

    def test_admin_creates_user_with_temp_password(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_add"),
            {"email": "new.dio@nic.in", "name": "New DIO", "temp_password": "Temp@999",
             "is_dio": "on", "is_gl": "on", "is_active": "on"},
        )
        self.assertRedirects(resp, reverse("user_list"))
        u = User.objects.get(username="new.dio")
        self.assertTrue(u.is_dio and u.must_change_password and not u.is_activated)
        self.assertTrue(u.is_gl)
        self.assertTrue(u.check_password("Temp@999"))
        self.assertContains(self.client.get(reverse("user_list")), "GL, DIO")

    def test_admin_deletes_user_after_confirming(self):
        self.client.force_login(self.admin)
        emp = User.objects.create_user("some.pl", password="x", is_pl=True)
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042", leader=emp)
        period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        MPREntry.objects.create(period=period, author=emp, kind=MPREntry.SIGNIFICANT, description="x")

        # GET warns about the fallout without touching anything.
        resp = self.client.get(reverse("user_delete", args=[emp.pk]))
        self.assertContains(resp, "1 monthly report entry")
        self.assertContains(resp, "Vahan")
        self.assertTrue(User.objects.filter(pk=emp.pk).exists())

        # Filed entries are PROTECT: the delete is refused, not a 500.
        resp = self.client.post(reverse("user_delete", args=[emp.pk]))
        self.assertContains(resp, escape("Can’t delete"))
        self.assertTrue(User.objects.filter(pk=emp.pk).exists())

        MPREntry.objects.all().delete()
        self.assertRedirects(self.client.post(reverse("user_delete", args=[emp.pk])),
                             reverse("user_list"))
        self.assertFalse(User.objects.filter(pk=emp.pk).exists())
        proj.refresh_from_db()
        self.assertIsNone(proj.leader)                   # project survives, unassigned

    def test_deleting_a_dio_leaves_the_district_without_an_officer(self):
        self.client.force_login(self.admin)
        dio = User.objects.create_user("some.dio", password="x", is_dio=True)
        dist = District.objects.create(name="Kota", officer=dio)

        # District.officer is SET_NULL: the delete goes through, but the warning
        # has to say the district is about to lose its officer.
        resp = self.client.get(reverse("user_delete", args=[dio.pk]))
        self.assertContains(resp, "Left without an officer: Kota")
        self.assertTrue(User.objects.filter(pk=dio.pk).exists())

        self.assertRedirects(self.client.post(reverse("user_delete", args=[dio.pk])),
                             reverse("user_list"))
        self.assertFalse(User.objects.filter(pk=dio.pk).exists())
        dist.refresh_from_db()
        self.assertIsNone(dist.officer)                  # district survives, unassigned

    def test_admin_cannot_delete_own_account(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(reverse("user_delete", args=[self.admin.pk])),
                             reverse("user_list"))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        # ...and the edit page doesn't dangle a Delete link at them.
        self.assertNotContains(self.client.get(reverse("user_edit", args=[self.admin.pk])),
                               "Delete user")

    def test_non_staff_cannot_delete_a_user(self):
        emp = User.objects.create_user("some.pl", password="x")
        self.client.force_login(
            User.objects.create_user("pleb", password="x", must_change_password=False))
        self.client.post(reverse("user_delete", args=[emp.pk]))
        self.assertTrue(User.objects.filter(pk=emp.pk).exists())

    def test_duplicate_login_id_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("user_add"),
            {"email": "boss@other.in", "name": "Imposter", "temp_password": "Temp@999", "is_active": "on"},
        )
        self.assertContains(resp, "already exists")

class MasterDataTests(TestCase):
    def setUp(self):
        self.admin = User(email="boss@nic.in", is_staff=True, must_change_password=False)
        self.admin.set_password("x")
        self.admin.save()
        self.client.force_login(self.admin)

    def test_non_staff_cannot_manage_master_data(self):
        self.client.logout()
        self.client.force_login(User.objects.create_user("pleb", password="x", must_change_password=False))
        self.assertNotEqual(self.client.get(reverse("project_list")).status_code, 200)
        self.assertNotEqual(self.client.get(reverse("district_list")).status_code, 200)

    def test_delete_confirmation_then_delete(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        dist = District.objects.create(name="Kotaville")
        # GET warns without deleting.
        resp = self.client.get(reverse("project_delete", args=[proj.pk]))
        self.assertContains(resp, "can’t be undone")
        self.assertTrue(Project.objects.filter(pk=proj.pk).exists())
        # POST deletes.
        self.assertRedirects(self.client.post(reverse("project_delete", args=[proj.pk])),
                             reverse("project_list"))
        self.assertFalse(Project.objects.filter(pk=proj.pk).exists())
        self.assertRedirects(self.client.post(reverse("district_delete", args=[dist.pk])),
                             reverse("district_list"))
        self.assertFalse(District.objects.filter(pk=dist.pk).exists())

    def test_deleting_project_unassigns_leader_not_the_user(self):
        emp = User.objects.create_user("pl1", password="x", must_change_password=False)
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042", leader=emp)
        self.client.post(reverse("project_delete", args=[proj.pk]))
        self.assertFalse(Project.objects.filter(pk=proj.pk).exists())
        self.assertTrue(User.objects.filter(pk=emp.pk).exists())  # user survives

    def test_reported_data_blocks_deleting_the_project(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        entry = MPREntry.objects.create(period=period, author=self.admin, project=proj,
                                        kind=MPREntry.SIGNIFICANT, description="rollout")

        # GET says why before the admin clicks.
        resp = self.client.get(reverse("project_delete", args=[proj.pk]))
        self.assertContains(resp, "1 monthly report entry")

        # POST is refused, and the entry keeps pointing at the project.
        resp = self.client.post(reverse("project_delete", args=[proj.pk]))
        self.assertContains(resp, escape("Can’t delete"))
        self.assertTrue(Project.objects.filter(pk=proj.pk).exists())
        entry.refresh_from_db()
        self.assertEqual(entry.project_id, proj.pk)

    def test_non_staff_cannot_delete(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        self.client.logout()
        self.client.force_login(User.objects.create_user("pleb", password="x", must_change_password=False))
        resp = self.client.post(reverse("project_delete", args=[proj.pk]))
        self.assertIn(reverse("login"), resp.url)  # bounced to login, not deleted
        self.assertTrue(Project.objects.filter(pk=proj.pk).exists())

    def test_project_list_filters_and_sorts(self):
        self.client.force_login(self.admin)
        finance = Department.objects.create(name="Finance")
        pl = User.objects.create_user("some.pl", password="x", name="Zara", is_pl=True)
        Project.objects.create(name="Vahan", prism_id="PR-1", category="central")
        Project.objects.create(name="Sarathi", department=finance, leader=pl)
        Project.objects.create(name="eMitra", category="central")
        url = reverse("project_list")

        by_category = self.client.get(url, {"category": "central"}).context["projects"]
        self.assertEqual({p.name for p in by_category}, {"Vahan", "eMitra"})

        by_dept = self.client.get(url, {"department": finance.pk}).context["projects"]
        self.assertEqual([p.name for p in by_dept], ["Sarathi"])

        # The filter that matters: projects nobody files an MPR for.
        orphans = self.client.get(url, {"leader": "unassigned"}).context["projects"]
        self.assertEqual({p.name for p in orphans}, {"Vahan", "eMitra"})

        # Default order is by Project ID; the Name heading re-sorts and reverses.
        self.assertEqual([p.code for p in self.client.get(url).context["projects"]],
                         ["P001", "P002", "P003"])
        # Name sorts case-insensitively (Lower), so eMitra files under E, not after V.
        self.assertEqual([p.name for p in self.client.get(url, {"sort": "-name"}).context["projects"]],
                         ["Vahan", "Sarathi", "eMitra"])

        none = self.client.get(url, {"category": "state", "leader": "unassigned"})
        self.assertEqual(list(none.context["projects"]), [])
        self.assertContains(none, "No projects match these filters")

    def test_name_sort_ignores_case(self):
        self.client.force_login(self.admin)
        for name in ("ShalaDarpan", "e-Procurement", "AshaSoft"):
            Project.objects.create(name=name)
        # Byte-order collation would file both lowercase-leading names last.
        self.assertEqual(
            [p.name for p in self.client.get(reverse("project_list"),
                                             {"sort": "name"}).context["projects"]],
            ["AshaSoft", "e-Procurement", "ShalaDarpan"])

    def test_projects_are_numbered_on_creation(self):
        first = Project.objects.create(name="Vahan", prism_id="PR-1")
        second = Project.objects.create(name="Sarathi", prism_id="PR-2")
        self.assertEqual([first.code, second.code], ["P001", "P002"])

        # A code, once assigned, survives later edits.
        first.name = "Vahan 4.0"
        first.save()
        self.assertEqual(Project.objects.get(pk=first.pk).code, "P001")

    def test_deleting_the_last_project_frees_its_code(self):
        Project.objects.create(name="Vahan", prism_id="PR-1")
        Project.objects.create(name="Sarathi", prism_id="PR-2").delete()
        # Numbering stays gapless, which means the highest code is reusable once
        # its project is gone. See Project.next_code — deliberate, not accidental.
        self.assertEqual(Project.objects.create(name="eMitra", prism_id="PR-3").code, "P002")

    def test_deleting_a_middle_project_leaves_its_gap(self):
        Project.objects.create(name="Vahan", prism_id="PR-1")
        middle = Project.objects.create(name="Sarathi", prism_id="PR-2")
        Project.objects.create(name="eMitra", prism_id="PR-3")
        middle.delete()
        # P002 is gone but P003 is still taken, so the next project gets P004.
        self.assertEqual(Project.objects.create(name="Raj Kaj", prism_id="PR-4").code, "P004")

    def test_projects_without_a_prism_id_coexist(self):
        # Most projects have no PRISM ID. They must not fight over the unique index,
        # which is why the column is NULL-when-absent rather than "".
        self.client.force_login(self.admin)
        for name in ("Vahan", "Sarathi", "eMitra"):
            resp = self.client.post(reverse("project_add"),
                                    {"name": name, "prism_id": "", "category": "state"})
            self.assertRedirects(resp, reverse("project_list"))
        self.assertEqual(Project.objects.filter(prism_id__isnull=True).count(), 3)
        self.assertEqual([p.code for p in Project.objects.order_by("code")],
                         ["P001", "P002", "P003"])
        # A real PRISM ID is still unique.
        Project.objects.create(name="Raj Kaj", prism_id="1951")
        self.assertContains(
            self.client.post(reverse("project_add"),
                             {"name": "Clash", "prism_id": "1951", "category": "state"}),
            "already exists")

    def test_hundredth_project_keeps_the_width(self):
        Project.objects.create(name="Ninety-nine", prism_id="PR-99", code="P099")
        self.assertEqual(Project.objects.create(name="Hundred", prism_id="PR-100").code, "P100")

    def test_admin_creates_project_with_prism_id(self):
        resp = self.client.post(
            reverse("project_add"),
            {"name": "Vahan", "prism_id": "PR-1042", "category": "central"},
        )
        self.assertRedirects(resp, reverse("project_list"))
        p = Project.objects.get(prism_id="PR-1042")
        self.assertEqual((p.name, p.category), ("Vahan", "central"))

    def test_duplicate_prism_id_rejected(self):
        Project.objects.create(name="Vahan", prism_id="PR-1042")
        resp = self.client.post(
            reverse("project_add"),
            {"name": "Sarathi", "prism_id": "PR-1042", "category": "state"},
        )
        self.assertEqual(Project.objects.count(), 1)
        self.assertContains(resp, "already exists")

    def test_admin_adds_and_removes_project_parameters(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        edit = reverse("project_edit", args=[proj.pk])
        for name in ["Challans issued", "Permits granted"]:
            self.assertRedirects(
                self.client.post(edit, {"name": name, "add_parameter": "1"}), edit)
        # Added at the bottom, in the order the admin typed them.
        self.assertEqual([p.name for p in proj.parameters.all()],
                         ["Challans issued", "Permits granted"])
        self.assertEqual([p.order for p in proj.parameters.all()], [1, 2])
        # The project itself is untouched by a parameter POST.
        proj.refresh_from_db()
        self.assertEqual(proj.name, "Vahan")

        resp = self.client.post(edit, {"name": "challans ISSUED", "add_parameter": "1"})
        self.assertContains(resp, "already reports a parameter")
        self.assertEqual(proj.parameters.count(), 2)

        # Removing one warns about the figures that go with it, then deletes on POST.
        param = proj.parameters.first()
        period = MPRPeriod.objects.create(year=2026, month=7, due_date="2026-08-05")
        ParameterValue.objects.create(period=period, parameter=param, reporting_month="1,318")
        url = reverse("project_parameter_delete", args=[param.pk])
        self.assertContains(self.client.get(url), "1 month")
        self.assertRedirects(self.client.post(url), edit)
        self.assertEqual([p.name for p in proj.parameters.all()], ["Permits granted"])
        self.assertFalse(ParameterValue.objects.exists())

    def test_non_staff_cannot_touch_parameters(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        param = ProjectParameter.objects.create(project=proj, name="Challans issued")
        self.client.logout()
        self.client.force_login(
            User.objects.create_user("pleb", password="x", must_change_password=False))
        self.client.post(reverse("project_edit", args=[proj.pk]),
                         {"name": "Sneaked in", "add_parameter": "1"})
        self.client.post(reverse("project_parameter_delete", args=[param.pk]))
        self.assertEqual([p.name for p in proj.parameters.all()], ["Challans issued"])

    def test_admin_creates_district(self):
        resp = self.client.post(reverse("district_add"), {"name": "Udaipur"})
        self.assertRedirects(resp, reverse("district_list"))
        self.assertTrue(District.objects.filter(name="Udaipur").exists())

    def test_admin_allots_employees_from_project_and_district(self):
        # The reverse of user-side assignment: map employees straight from the
        # project/district edit page.
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        dist = District.objects.create(name="Udaipur")
        emp = User.objects.create_user("some.pl", email="some.pl@nic.in", password="x",
                                       must_change_password=False)
        self.client.post(reverse("project_edit", args=[proj.pk]),
                         {"name": "Vahan", "prism_id": "PR-1042", "category": "state",
                          "leader": emp.pk})
        self.client.post(reverse("district_edit", args=[dist.pk]),
                         {"name": "Udaipur", "officer": emp.pk})
        proj.refresh_from_db()
        dist.refresh_from_db()
        self.assertEqual(proj.leader, emp)
        self.assertEqual(dist.officer, emp)
        # Clearing the selection unmaps them.
        self.client.post(reverse("project_edit", args=[proj.pk]),
                         {"name": "Vahan", "prism_id": "PR-1042", "category": "state", "leader": ""})
        proj.refresh_from_db()
        self.assertIsNone(proj.leader)

    def test_admin_assigns_project_and_district_to_employee(self):
        proj = Project.objects.create(name="Vahan", prism_id="PR-1042")
        dist = District.objects.create(name="Udaipur")
        emp = User.objects.create_user("some.pl", email="some.pl@nic.in", password="x",
                                       is_pl=True, is_dio=True, must_change_password=False)
        resp = self.client.post(
            reverse("user_edit", args=[emp.pk]),
            {"email": "some.pl@nic.in", "name": "Some PL", "is_pl": "on", "is_dio": "on",
             "is_active": "on", "projects": [proj.pk], "districts": [dist.pk]},
        )
        self.assertRedirects(resp, reverse("user_list"))
        self.assertEqual(list(emp.projects.all()), [proj])
        self.assertEqual(list(emp.districts.all()), [dist])
        # And the FK side agrees (the project's single leader is this employee).
        proj.refresh_from_db()
        self.assertEqual(proj.leader, emp)


class ReportingMonthTests(TestCase):
    """Due dates and open/closed, from Manage."""

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

    def test_admin_opens_a_new_month_and_cannot_duplicate_one(self):
        self.client.force_login(self.admin)
        self.assertRedirects(
            self.client.post(reverse("period_add"),
                             {"year": "2026", "month": "8", "due_date": "2026-09-05",
                              "is_open": "on"}),
            reverse("period_list"))
        august = MPRPeriod.objects.get(year=2026, month=8)
        self.assertEqual(str(august.due_date), "2026-09-05")
        self.assertTrue(august.is_open)
        self.assertContains(self.client.get(reverse("period_list")), "August 2026")

        # Same month twice would split a month's data across two rows.
        self.assertContains(
            self.client.post(reverse("period_add"),
                             {"year": "2026", "month": "8", "due_date": "2026-09-30"}),
            "already exists")
        self.assertEqual(MPRPeriod.objects.filter(year=2026, month=8).count(), 1)

        # The month itself is fixed once opened — editing only offers date and status.
        self.assertNotContains(self.client.get(reverse("period_edit", args=[august.pk])),
                               'name="month"')

    def test_only_admins_can_open_a_month(self):
        self.client.post(reverse("period_add"),  # setUp logs in the DIO
                         {"year": "2026", "month": "9", "due_date": "2026-10-05"})
        self.assertFalse(MPRPeriod.objects.filter(month=9).exists())

    def test_admin_extends_the_due_date_from_manage(self):
        july = self.period
        august = MPRPeriod.objects.create(year=2026, month=8, due_date="2026-09-05")
        self.client.force_login(self.admin)

        listing = self.client.get(reverse("period_list"))
        self.assertContains(listing, "5 August 2026")
        self.assertContains(listing, "1 entry")  # setUp filed one

        url = reverse("period_edit", args=[july.pk])
        self.assertRedirects(
            self.client.post(url, {"due_date": "2026-08-20", "is_open": "on"}),
            reverse("period_list"))
        july.refresh_from_db()
        self.assertEqual(str(july.due_date), "2026-08-20")
        self.assertTrue(july.is_open)
        august.refresh_from_db()
        self.assertEqual(str(august.due_date), "2026-09-05")  # only the edited month moved

        # A date it can't parse is rejected and shown, not swallowed.
        self.assertContains(self.client.post(url, {"due_date": "next tuesday", "is_open": "on"}),
                            "Enter a valid date")
        july.refresh_from_db()
        self.assertEqual(str(july.due_date), "2026-08-20")

        # The filler sees the new date on their month page.
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("mpr_month", args=[july.pk])),
                            "Due 20 August 2026")

    def test_admin_closes_and_reopens_a_month(self):
        url = reverse("period_edit", args=[self.period.pk])
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(url, {"due_date": "2026-08-05"}),  # box unticked
                             reverse("period_list"))
        self.period.refresh_from_db()
        self.assertFalse(self.period.is_open)
        self.assertContains(self.client.get(reverse("period_list")), "Closed")

        # Closed means read-only for the filler, lock or no lock.
        self.client.force_login(self.user)
        month = self.client.get(reverse("mpr_month", args=[self.period.pk]))
        self.assertContains(month, "This month is closed")
        self.assertNotContains(month, "Lock month")
        self.client.post(reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
                         {"description": "Sneaked in after closing"})
        self.assertEqual(MPREntry.objects.count(), 1)  # only setUp's row

        # Reopening puts it back, with nothing lost.
        self.client.force_login(self.admin)
        self.client.post(url, {"due_date": "2026-08-05", "is_open": "on"})
        self.period.refresh_from_db()
        self.assertTrue(self.period.is_open)
        self.client.force_login(self.user)
        self.client.post(reverse("mpr_entry_add", args=[self.period.pk, MPREntry.SIGNIFICANT]),
                         {"description": "Added after reopening"})
        self.assertEqual(MPREntry.objects.count(), 2)

    def test_sio_reads_the_due_date_on_reports_but_cannot_reach_the_editor(self):
        sio = User.objects.create_user("sio.two", password="x", is_sio=True,
                                       must_change_password=False)
        self.client.force_login(sio)
        self.assertContains(self.client.get(reverse("reports")), "Due 5 August 2026")
        self.assertEqual(self.client.get(reverse("period_list")).status_code, 302)
        self.client.post(reverse("period_edit", args=[self.period.pk]),
                         {"due_date": "2026-12-31"})
        self.period.refresh_from_db()
        self.assertEqual(str(self.period.due_date), "2026-08-05")


class PostingAndDesignationTests(TestCase):
    """The two admin-managed lists behind User.place_of_posting / User.designation."""

    def test_deleting_a_posting_keeps_its_employees(self):
        place = PlaceOfPosting.objects.create(name="Jodhpur")
        grade = Designation.objects.create(name="Scientist-D")
        user = User.objects.create_user("dio.jodhpur", password="x",
                                        place_of_posting=place, designation=grade)
        place.delete()
        user.refresh_from_db()
        self.assertIsNone(user.place_of_posting)
        self.assertEqual(user.designation.name, "Scientist-D")

    def test_admin_counts_the_employees_on_each_list_row(self):
        place = PlaceOfPosting.objects.create(name="Rajasthan State Centre, Jaipur")
        for i in range(3):
            User.objects.create_user(f"emp{i}", password="x", place_of_posting=place)
        model_admin = LookupAdmin(PlaceOfPosting, AdminSite())
        row = model_admin.get_queryset(None).get(pk=place.pk)
        self.assertEqual(model_admin.user_count(row), 3)
