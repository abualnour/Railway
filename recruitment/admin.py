from django.contrib import admin

from .models import Candidate, CandidateAttachment, CandidateInterview, CandidateStageAction, JobPosting


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "branch", "status", "posted_date", "closing_date")
    list_filter = ("status", "department__company", "department", "branch")
    search_fields = ("title", "description", "requirements")


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("full_name", "job_posting", "email", "phone", "status", "applied_at", "has_offer_letter")
    list_filter = ("status", "job_posting__department", "job_posting__branch")
    search_fields = ("full_name", "email", "phone", "nationality")

    @admin.display(boolean=True, description="Offer Letter")
    def has_offer_letter(self, obj):
        return bool(obj.offer_letter_file)


@admin.register(CandidateStageAction)
class CandidateStageActionAdmin(admin.ModelAdmin):
    list_display = ("candidate", "stage", "action_by", "created_at")
    list_filter = ("stage", "action_by")
    search_fields = ("candidate__full_name", "note", "action_by__email")


@admin.register(CandidateInterview)
class CandidateInterviewAdmin(admin.ModelAdmin):
    list_display = ("candidate", "scheduled_at", "interview_type", "interviewer", "score", "recommendation")
    list_filter = ("interview_type", "interviewer", "recommendation")
    search_fields = ("candidate__full_name", "location", "note", "outcome")


@admin.register(CandidateAttachment)
class CandidateAttachmentAdmin(admin.ModelAdmin):
    list_display = ("title", "candidate", "uploaded_by", "created_at")
    list_filter = ("uploaded_by", "candidate__job_posting")
    search_fields = ("title", "notes", "candidate__full_name")
