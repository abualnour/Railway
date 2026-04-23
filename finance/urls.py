from django.urls import path

from .views import expense_claim_dashboard, expense_claim_review

app_name = "finance"

urlpatterns = [
    path("", expense_claim_dashboard, name="expense_claim_dashboard"),
    path("expense-claims/<int:claim_pk>/review/", expense_claim_review, name="expense_claim_review"),
]
