from django.urls import path

from .views import (
    performance_dashboard,
    performance_review_acknowledge,
    performance_review_comment_create,
    performance_review_create,
    performance_review_force_complete,
    performance_review_print,
    performance_review_update,
    performance_reviewer_queue,
    performance_reviews_export,
    review_cycle_clone,
    review_cycle_close,
    review_cycle_create,
    review_cycle_update,
)

app_name = "performance"

urlpatterns = [
    path("", performance_dashboard, name="dashboard"),
    path("reviewer-queue/", performance_reviewer_queue, name="reviewer_queue"),
    path("export/reviews/", performance_reviews_export, name="reviews_export"),
    path("cycles/create/", review_cycle_create, name="review_cycle_create"),
    path("cycles/<int:cycle_pk>/edit/", review_cycle_update, name="review_cycle_update"),
    path("cycles/<int:cycle_pk>/clone/", review_cycle_clone, name="review_cycle_clone"),
    path("cycles/<int:cycle_pk>/close/", review_cycle_close, name="review_cycle_close"),
    path("employees/<int:employee_pk>/reviews/create/", performance_review_create, name="performance_review_create"),
    path("reviews/<int:review_pk>/edit/", performance_review_update, name="performance_review_update"),
    path("reviews/<int:review_pk>/print/", performance_review_print, name="performance_review_print"),
    path("reviews/<int:review_pk>/acknowledge/", performance_review_acknowledge, name="performance_review_acknowledge"),
    path("reviews/<int:review_pk>/notes/create/", performance_review_comment_create, name="performance_review_comment_create"),
    path("reviews/<int:review_pk>/force-complete/", performance_review_force_complete, name="performance_review_force_complete"),
]
