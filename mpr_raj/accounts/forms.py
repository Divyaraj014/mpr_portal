from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db import models

from . import captcha
from .models import District, MPREntry, MPRPeriod, Project, ProjectParameter, User


class CaptchaAuthenticationForm(AuthenticationForm):
    captcha = forms.CharField(
        label="Captcha",
        max_length=8,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Characters in the image"}),
    )

    error_messages = AuthenticationForm.error_messages | {
        "invalid_captcha": "The characters you entered didn't match the image. Try again.",
    }

    def clean_captcha(self):
        if not captcha.check(self.request, self.cleaned_data.get("captcha", "")):
            raise forms.ValidationError(self.error_messages["invalid_captcha"], code="invalid_captcha")

    def clean(self):
        # Don't attempt authentication (and leak valid/invalid credential info)
        # unless the captcha passed.
        if self.errors:
            return self.cleaned_data
        return super().clean()


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.name or user.username


class DistrictForm(forms.ModelForm):
    officer = EmployeeChoiceField(
        label="Assigned employee",
        queryset=User.objects.order_by("name", "username"),
        required=False,
        empty_label="— None —",
        help_text="The DIO who fills this district.",
    )

    class Meta:
        model = District
        fields = ["name", "officer"]


class ProjectForm(forms.ModelForm):
    leader = EmployeeChoiceField(
        label="Project Leader",
        queryset=User.objects.order_by("name", "username"),
        required=False,
        empty_label="— None —",
        help_text="The Project Leader who fills this project.",
    )

    class Meta:
        model = Project
        fields = ["name", "prism_id", "category", "department", "targeted_user", "url", "leader"]
        help_texts = {"prism_id": "Leave blank if this project has no PRISM ID yet."}

    def clean_prism_id(self):
        # "" would collide with every other blank one on the unique index; NULL won't.
        return self.cleaned_data["prism_id"] or None


class PeriodForm(forms.ModelForm):
    """A month's due date and whether it still accepts data. Manage → Reporting months."""

    class Meta:
        model = MPRPeriod
        fields = ["year", "month", "due_date", "is_open"]
        labels = {"is_open": "Open for filling"}
        help_texts = {
            "is_open": "Closing a month makes it read-only for everyone, locked or not. "
            "Reopen it here at any time; nothing filed is lost either way.",
        }
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}  # native picker, no JS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Which month it is, is set once: renaming it would move everything already
            # filed against it. The unique constraint on (year, month) does the rest.
            del self.fields["year"], self.fields["month"]


class ProjectParameterForm(forms.ModelForm):
    """Add one recurring figure to a project. Lives on the project edit page."""

    class Meta:
        model = ProjectParameter
        fields = ["name"]

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, instance=ProjectParameter(project=project), **kwargs)
        self.fields["name"].label = "Parameter"
        self.fields["name"].widget.attrs["placeholder"] = "e.g. Challans issued"

    def clean_name(self):
        # The (project, name) constraint can't fire here — Django skips unique_together
        # when a member field is off the form — and it wouldn't catch case variants anyway.
        name = self.cleaned_data["name"].strip()
        if self.instance.project.parameters.filter(name__iexact=name).exists():
            raise forms.ValidationError("This project already reports a parameter with that name.")
        return name

    def save(self, commit=True):
        # New rows land at the bottom; `order` exists only to sort the table.
        top = self.instance.project.parameters.aggregate(models.Max("order"))["order__max"]
        self.instance.order = (top or 0) + 1
        return super().save(commit)


MAX_WORDS = 500


def max_words(value):
    if len(value.split()) > MAX_WORDS:
        raise forms.ValidationError(f"Keep this to {MAX_WORDS} words or fewer (it has {len(value.split())}).")


def entry_form_class(kind):
    """Form for one MPR section. Which fields it shows lives on the model (MPREntry.FIELDS)."""
    date_input = forms.DateInput(attrs={"type": "date"})  # native picker, no JS
    prose = forms.Textarea(attrs={"rows": 3})
    form_class = forms.modelform_factory(
        MPREntry,
        fields=MPREntry.FIELDS[kind],
        labels=MPREntry.LABELS.get(kind, {}),
        widgets={
            "date": date_input,
            "to_date": date_input,
            "description": prose,
            "remarks": prose,
            "suggestions": prose,
        },
    )
    # Every column is optional on the model (they differ per section), so the form
    # insists on the one that identifies the row. Otherwise blank rows sail through.
    for name in ("description", "remarks", "suggestions"):
        if name in form_class.base_fields:
            form_class.base_fields[name].validators.append(max_words)
            form_class.base_fields[name].help_text = f"Up to {MAX_WORDS} words."
            form_class.base_fields[name].widget.attrs["data-max-words"] = MAX_WORDS  # app.js counter
    headline = "title" if "title" in form_class.base_fields else "description"
    form_class.base_fields[headline].required = True
    return form_class


class UserForm(forms.ModelForm):
    # Layout order for the "Employee details" block — the template renders
    # form.details() so it doesn't have to name each field.
    DETAIL_FIELDS = ["name", "email", "employee_code", "designation", "phone", "ip_phone", "place_of_posting"]

    temp_password = forms.CharField(
        label="Temporary password",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
        help_text="Share this with the employee. They must replace it on first login.",
    )
    # Reverse side of Project.leader / District.officer — assign this person's
    # projects/districts from here too. Reassigning steals a project from whoever
    # held it (the FK guarantees a single leader/officer).
    projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )
    districts = forms.ModelMultipleChoiceField(
        queryset=District.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = User
        fields = [
            "email",
            "name",
            "employee_code",
            "designation",
            "phone",
            "ip_phone",
            "place_of_posting",
            "is_staff",
            "is_sio",
            "is_gl",
            "is_pl",
            "is_dio",
            "is_active",
        ]
        labels = {"is_staff": "Admin", "is_active": "Account enabled", "ip_phone": "IP phone"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["name"].required = True
        self.fields["email"].help_text = "The login ID is the part before the @."
        if not self.instance.pk:
            self.fields["temp_password"].required = True
        else:
            self.fields["temp_password"].label = "Reset password"
            self.fields["temp_password"].help_text = (
                "Leave blank to keep the current password. Setting one forces a change at the next sign-in."
            )
            self.fields["projects"].initial = self.instance.projects.all()
            self.fields["districts"].initial = self.instance.districts.all()

    def details(self):
        return [self[name] for name in self.DETAIL_FIELDS]

    def clean_email(self):
        email = self.cleaned_data["email"]
        prefix = email.split("@")[0]
        clash = User.objects.filter(username=prefix)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"A user with login ID '{prefix}' already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data["temp_password"]:
            user.set_password(self.cleaned_data["temp_password"])
            user.must_change_password = True
        if commit:
            user.save()
            # Point the selected projects'/districts' FK at this user (and release
            # any that were deselected).
            user.projects.set(self.cleaned_data["projects"])
            user.districts.set(self.cleaned_data["districts"])
        return user
