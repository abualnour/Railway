from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0006_alter_branchdocumentrequirement_options_and_more"),
    ]

    # The fields were already added in 0006. Keep this migration as a no-op so
    # environments that expect 0007 in the chain can still migrate cleanly.
    operations = []
