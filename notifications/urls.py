from django.urls import path

from .views import (
    bulk_delete_notifications,
    delete_notification,
    delivery_performance,
    mark_all_read,
    mark_category_read,
    mark_notification_read,
    notification_center,
    update_notification_preferences,
)

app_name = "notifications"

urlpatterns = [
    path("", notification_center, name="home"),
    path("performance/", delivery_performance, name="performance"),
    path("preferences/", update_notification_preferences, name="preferences"),
    path("bulk-delete/", bulk_delete_notifications, name="bulk_delete"),
    path("mark-all-read/", mark_all_read, name="mark_all_read"),
    path("categories/<str:category>/mark-read/", mark_category_read, name="mark_category_read"),
    path("<int:pk>/delete/", delete_notification, name="delete"),
    path("<int:pk>/mark-read/", mark_notification_read, name="mark_read"),
]
