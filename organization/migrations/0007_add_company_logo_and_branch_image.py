from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0006_alter_branchdocumentrequirement_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="logo",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="companies/logos/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["jpg", "jpeg", "png", "webp"]
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="branch",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="branches/images/",
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["jpg", "jpeg", "png", "webp"]
                    )
                ],
            ),
        ),
    ]