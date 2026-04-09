from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0004_alter_jobtitle_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BranchDocumentRequirement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("legal", "Legal Document"),
                            ("ad_license", "Ad License"),
                            ("store_license", "Store License"),
                            ("municipality", "Municipality / Permit"),
                            ("lease", "Lease / Contract"),
                            ("civil_defense", "Civil Defense / Safety"),
                            ("insurance", "Insurance"),
                            ("service", "Service Contract"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=30,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("is_mandatory", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_requirements",
                        to="organization.branch",
                    ),
                ),
            ],
            options={
                "ordering": ["branch__company__name", "branch__name", "title", "id"],
                "unique_together": {("branch", "document_type", "title")},
            },
        ),
    ]