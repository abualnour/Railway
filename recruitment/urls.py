from django.urls import path

from .views import (
    CandidateAttachmentCreateView,
    CandidateAttachmentDeleteView,
    CandidateCreateView,
    CandidateDeleteView,
    CandidateDetailView,
    CandidateHireConvertView,
    CandidateInterviewCreateView,
    CandidateInterviewDeleteView,
    CandidateInterviewUpdateView,
    CandidateListView,
    CandidateUpdateView,
    JobPostingCreateView,
    JobPostingDeleteView,
    JobPostingDetailView,
    RecruitmentCandidatesExportView,
    RecruitmentJobPostingsExportView,
    JobPostingListView,
    JobPostingUpdateView,
)

app_name = "recruitment"

urlpatterns = [
    path("", JobPostingListView.as_view(), name="job_posting_list"),
    path("candidates/", CandidateListView.as_view(), name="candidate_list"),
    path("export/candidates/", RecruitmentCandidatesExportView.as_view(), name="export_candidates"),
    path("export/job-postings/", RecruitmentJobPostingsExportView.as_view(), name="export_job_postings"),
    path("job-postings/create/", JobPostingCreateView.as_view(), name="job_posting_create"),
    path("job-postings/<int:pk>/", JobPostingDetailView.as_view(), name="job_posting_detail"),
    path("job-postings/<int:pk>/edit/", JobPostingUpdateView.as_view(), name="job_posting_update"),
    path("job-postings/<int:pk>/delete/", JobPostingDeleteView.as_view(), name="job_posting_delete"),
    path("job-postings/<int:job_posting_pk>/candidates/create/", CandidateCreateView.as_view(), name="candidate_create"),
    path("candidates/<int:pk>/", CandidateDetailView.as_view(), name="candidate_detail"),
    path("candidates/<int:pk>/edit/", CandidateUpdateView.as_view(), name="candidate_update"),
    path("candidates/<int:pk>/delete/", CandidateDeleteView.as_view(), name="candidate_delete"),
    path("candidates/<int:pk>/schedule-interview/", CandidateInterviewCreateView.as_view(), name="candidate_schedule_interview"),
    path("interviews/<int:pk>/edit/", CandidateInterviewUpdateView.as_view(), name="candidate_interview_update"),
    path("interviews/<int:pk>/delete/", CandidateInterviewDeleteView.as_view(), name="candidate_interview_delete"),
    path("candidates/<int:pk>/attachments/create/", CandidateAttachmentCreateView.as_view(), name="candidate_attachment_create"),
    path(
        "candidates/<int:pk>/attachments/<int:attachment_pk>/delete/",
        CandidateAttachmentDeleteView.as_view(),
        name="candidate_attachment_delete",
    ),
    path("candidates/<int:pk>/hire/", CandidateHireConvertView.as_view(), name="candidate_hire"),
]
