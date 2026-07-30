from django.db import migrations


def backfill_project(apps, schema_editor):
    """
    Project rows used to belong to the author's whole project set; now each one belongs
    to a single project's report. Rows that already named a project keep it; the rest go
    to their author's first project, so nothing becomes invisible. A Project Leader with
    several projects should check the ones that landed on the wrong report.
    """
    MPREntry = apps.get_model("accounts", "MPREntry")
    Project = apps.get_model("accounts", "Project")
    first = {}
    for project in Project.objects.order_by("name"):
        first.setdefault(project.leader_id, project.id)
    for entry in MPREntry.objects.filter(scope="project", project__isnull=True):
        if first.get(entry.author_id):
            entry.project_id = first[entry.author_id]
            entry.save(update_fields=["project"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_alter_mprentry_options_mprentry_scope"),
    ]

    operations = [
        migrations.RunPython(backfill_project, migrations.RunPython.noop),
    ]
