from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from employees.access import is_admin_compatible as is_admin_compatible_role, is_hr_user as is_hr_user_role
from notifications.models import InAppNotification, build_in_app_notification
from notifications.views import persist_in_app_notifications

from .forms import RegionalHolidayForm, RegionalWorkCalendarForm
from .models import RegionalHoliday, RegionalWorkCalendar
from .services import build_work_calendar_overview, get_active_calendar, recalculate_employee_leave_totals


def can_manage_work_calendar(user):
    return bool(
        user
        and user.is_authenticated
        and (is_admin_compatible_role(user) or is_hr_user_role(user))
    )


def get_calendar_notification_users():
    user_model = get_user_model()
    return list(user_model.objects.filter(is_active=True).order_by("email"))


def dispatch_calendar_notifications(*, title, body, level=InAppNotification.LEVEL_INFO, excluded_users=None):
    notifications = []
    for user in get_calendar_notification_users():
        notifications.append(
            build_in_app_notification(
                recipient=user,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_CALENDAR,
                level=level,
                action_url="/work-calendar/",
                exclude_users=excluded_users,
            )
        )
    notifications = [notification for notification in notifications if notification is not None]
    if notifications:
        persist_in_app_notifications(notifications)


@login_required
def work_calendar_home(request):
    if not can_manage_work_calendar(request.user):
        raise PermissionDenied("You do not have permission to manage the work calendar.")

    active_calendar = get_active_calendar() or RegionalWorkCalendar(
        name="Kuwait Government Work Calendar",
        region_code="KW",
        weekend_days="4",
        is_active=True,
    )

    calendar_form = RegionalWorkCalendarForm(instance=active_calendar)
    holiday_form = RegionalHolidayForm()

    if request.method == "POST":
        action = (request.POST.get("calendar_action") or "").strip()

        if action == "save_calendar":
            calendar_form = RegionalWorkCalendarForm(request.POST, instance=active_calendar)
            if calendar_form.is_valid():
                saved_calendar = calendar_form.save()
                dispatch_calendar_notifications(
                    title=f"Work calendar updated: {saved_calendar.name}",
                    body=(
                        f"Weekly off days are now {', '.join(saved_calendar.weekend_day_labels)} "
                        f"for region {saved_calendar.region_code}."
                    ),
                    level=InAppNotification.LEVEL_INFO,
                    excluded_users=[request.user],
                )
                recalculated_count = recalculate_employee_leave_totals()
                messages.success(request, "Regional work calendar saved successfully.")
                if recalculated_count:
                    messages.info(request, f"Updated {recalculated_count} existing leave record totals to match the active calendar.")
                return redirect("workcalendar:home")
            messages.error(request, "Please review the work calendar settings and try again.")
        elif action == "add_holiday":
            holiday_form = RegionalHolidayForm(request.POST)
            if holiday_form.is_valid():
                active_calendar = get_active_calendar() or active_calendar
                if not active_calendar.pk:
                    messages.error(request, "Save the active Kuwait work calendar before adding holidays.")
                else:
                    holiday = holiday_form.save(commit=False)
                    holiday.calendar = active_calendar
                    holiday.save()
                    dispatch_calendar_notifications(
                        title=f"Holiday added: {holiday.title}",
                        body=(
                            f"{holiday.title} was added for {holiday.holiday_date:%b %d, %Y}."
                            + (
                                " It is marked as a non-working day."
                                if holiday.is_non_working_day
                                else " It is marked as an official observance."
                            )
                        ),
                        level=InAppNotification.LEVEL_WARNING if holiday.is_non_working_day else InAppNotification.LEVEL_INFO,
                        excluded_users=[request.user],
                    )
                    messages.success(request, f"{holiday.title} added to the work calendar.")
                    recalculated_count = recalculate_employee_leave_totals()
                    if recalculated_count:
                        messages.info(request, f"Updated {recalculated_count} existing leave record totals after the holiday change.")
                    return redirect("workcalendar:home")
            else:
                messages.error(request, "Please review the holiday entry and try again.")
        elif action == "delete_holiday":
            holiday = get_object_or_404(RegionalHoliday, pk=request.POST.get("holiday_id"))
            holiday_title = holiday.title
            holiday_date = holiday.holiday_date
            holiday.delete()
            dispatch_calendar_notifications(
                title=f"Holiday removed: {holiday_title}",
                body=f"{holiday_title} on {holiday_date:%b %d, %Y} was removed from the work calendar.",
                level=InAppNotification.LEVEL_INFO,
                excluded_users=[request.user],
            )
            messages.success(request, f"{holiday_title} was removed from the work calendar.")
            recalculated_count = recalculate_employee_leave_totals()
            if recalculated_count:
                messages.info(request, f"Updated {recalculated_count} existing leave record totals after the holiday change.")
            return redirect("workcalendar:home")

    today = timezone.localdate()
    overview = build_work_calendar_overview(today.year)
    holidays = overview["holidays"]
    upcoming_holidays = [holiday for holiday in holidays if holiday.holiday_date >= today][:10]

    context = {
        "workspace_title": "Kuwait Work Calendar",
        "calendar_form": calendar_form,
        "holiday_form": holiday_form,
        "active_calendar": get_active_calendar() or active_calendar,
        "current_year": overview["current_year"],
        "holiday_total": overview["holiday_total"],
        "non_working_holiday_total": overview["non_working_holiday_total"],
        "working_day_total": overview["working_day_total"],
        "today_context": overview["today_context"],
        "holidays": holidays,
        "upcoming_holidays": upcoming_holidays,
    }
    return render(request, "workcalendar/home.html", context)
