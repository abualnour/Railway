from django.contrib import admin

from .models import PerformanceReview, PerformanceReviewComment, ReviewCycle


@admin.register(ReviewCycle)
class ReviewCycleAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "period_start", "period_end", "status")
    list_filter = ("status", "company")
    search_fields = ("title", "company__name")


@admin.register(PerformanceReview)
class PerformanceReviewAdmin(admin.ModelAdmin):
    list_display = ("employee", "cycle", "reviewer", "overall_rating", "status", "submitted_at", "acknowledged_at")
    list_filter = ("status", "overall_rating", "cycle__company")
    search_fields = ("employee__full_name", "employee__employee_id", "reviewer__full_name", "cycle__title")


@admin.register(PerformanceReviewComment)
class PerformanceReviewCommentAdmin(admin.ModelAdmin):
    list_display = ("review", "author", "created_at")
    list_filter = ("created_at",)
    search_fields = ("review__employee__full_name", "review__cycle__title", "author__username", "author__first_name", "author__last_name", "note")
