from django.db import migrations, models


def assign_codes(apps, schema_editor):
    """Give the projects that already exist their codes, oldest first."""
    Project = apps.get_model("accounts", "Project")
    for number, project in enumerate(Project.objects.order_by("pk"), start=1):
        project.code = f"P{number:03d}"
        project.save(update_fields=["code"])


class Migration(migrations.Migration):
    """
    Three steps rather than one: the column has to exist and be filled before it
    can be unique, otherwise every pre-existing project collides on the empty
    default the moment there is more than one of them.
    """

    dependencies = [("accounts", "0013_alter_district_officer")]

    operations = [
        migrations.AddField(
            model_name="project",
            name="code",
            field=models.CharField(blank=True, default="", max_length=10,
                                   verbose_name="Project ID"),
            preserve_default=False,
        ),
        migrations.RunPython(assign_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="project",
            name="code",
            field=models.CharField(blank=True, max_length=10, unique=True,
                                   verbose_name="Project ID"),
        ),
    ]
