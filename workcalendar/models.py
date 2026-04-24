from django.core.exceptions import ValidationError
from django.db import models


WEEKDAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class RegionalWorkCalendar(models.Model):
    name = models.CharField(max_length=150, default="Kuwait Government Work Calendar")
    region_code = models.CharField(max_length=10, default="KW")
    weekend_days = models.CharField(max_length=20, default="4")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regional Work Calendar"
        verbose_name_plural = "Regional Work Calendars"
        ordering = ["-is_active", "name", "-id"]
        indexes = [
            models.Index(fields=["is_active", "region_code"]),
        ]

    def __str__(self):
        return self.name

    @property
    def weekend_day_numbers(self):
        values = set()
        for raw_value in (self.weekend_days or "").split(","):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            try:
                weekday_number = int(raw_value)
            except (TypeError, ValueError):
                continue
            if 0 <= weekday_number <= 6:
                values.add(weekday_number)
        return values

    @property
    def weekend_day_labels(self):
        label_map = dict(WEEKDAY_CHOICES)
        return [label_map[number] for number in sorted(self.weekend_day_numbers) if number in label_map]

    def clean(self):
        errors = {}
        parsed_days = self.weekend_day_numbers
        if not parsed_days:
            errors["weekend_days"] = "Select at least one weekly off day."

        if self.is_active:
            existing_active = RegionalWorkCalendar.objects.filter(is_active=True)
            if self.pk:
                existing_active = existing_active.exclude(pk=self.pk)
            if existing_active.exists():
                errors["is_active"] = "Only one active regional work calendar can be enabled at a time."

        if errors:
            raise ValidationError(errors)


class RegionalHoliday(models.Model):
    HOLIDAY_TYPE_PUBLIC = "public"
    HOLIDAY_TYPE_OBSERVANCE = "observance"

    HOLIDAY_TYPE_CHOICES = [
        (HOLIDAY_TYPE_PUBLIC, "Public Holiday"),
        (HOLIDAY_TYPE_OBSERVANCE, "Official Observance"),
    ]

    calendar = models.ForeignKey(
        RegionalWorkCalendar,
        on_delete=models.CASCADE,
        related_name="holidays",
    )
    holiday_date = models.DateField(db_index=True)
    title = models.CharField(max_length=160)
    holiday_type = models.CharField(
        max_length=20,
        choices=HOLIDAY_TYPE_CHOICES,
        default=HOLIDAY_TYPE_PUBLIC,
    )
    is_non_working_day = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["holiday_date", "title", "id"]
        indexes = [
            models.Index(fields=["calendar", "holiday_date"]),
            models.Index(fields=["is_non_working_day", "holiday_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "holiday_date", "title"],
                name="workcal_holiday_calendar_date_title_uniq",
            )
        ]
        verbose_name = "Regional Holiday"
        verbose_name_plural = "Regional Holidays"

    def __str__(self):
        return f"{self.title} ({self.holiday_date})"
