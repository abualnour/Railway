from django.urls import path

from .views import (
    mark_all_notifications_read,
    mark_notification_category_read,
    mark_notification_read,
    notification_center,
    update_notification_preferences,
)

app_name = "notifications"

urlpatterns = [
    path("", notification_center, name="home"),
    path("preferences/", update_notification_preferences, name="preferences"),
    path("mark-all-read/", mark_all_notifications_read, name="mark_all_read"),
    path("categories/<str:category>/mark-read/", mark_notification_category_read, name="mark_category_read"),
    path("<int:pk>/mark-read/", mark_notification_read, name="mark_read"),
]
