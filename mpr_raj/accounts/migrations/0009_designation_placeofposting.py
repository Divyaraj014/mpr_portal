"""
`place_of_posting` and `designation` become admin-managed lists instead of free text.

The old text columns are renamed aside, the FKs added, the distinct values lifted
into the new tables, and only then are the text columns dropped — so whatever was
already typed into them survives the switch.
"""
import django.db.models.deletion
from django.db import migrations, models


def text_to_fk(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for model_name, field in (("PlaceOfPosting", "place_of_posting"), ("Designation", "designation")):
        Lookup = apps.get_model("accounts", model_name)
        for value in (User.objects.exclude(**{f"{field}_text": ""})
                      .values_list(f"{field}_text", flat=True).distinct()):
            row, _ = Lookup.objects.get_or_create(name=value.strip())
            User.objects.filter(**{f"{field}_text": value}).update(**{field: row})


def fk_to_text(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for field in ("place_of_posting", "designation"):
        for user in User.objects.exclude(**{field: None}).select_related(field):
            User.objects.filter(pk=user.pk).update(
                **{f"{field}_text": getattr(user, field).name})


class Migration(migrations.Migration):

    dependencies = [("accounts", "0008_entry_project_backfill")]

    operations = [
        migrations.CreateModel(
            name="Designation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PlaceOfPosting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True)),
            ],
            options={
                "verbose_name": "place of posting",
                "verbose_name_plural": "places of posting",
                "ordering": ["name"],
            },
        ),
        migrations.RenameField(
            model_name="user", old_name="place_of_posting", new_name="place_of_posting_text"),
        migrations.RenameField(
            model_name="user", old_name="designation", new_name="designation_text"),
        migrations.AddField(
            model_name="user",
            name="place_of_posting",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="users", to="accounts.placeofposting"),
        ),
        migrations.AddField(
            model_name="user",
            name="designation",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="users", to="accounts.designation"),
        ),
        migrations.RunPython(text_to_fk, fk_to_text),
        migrations.RemoveField(model_name="user", name="place_of_posting_text"),
        migrations.RemoveField(model_name="user", name="designation_text"),
    ]
