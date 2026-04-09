# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    ROLE_HR = "hr"
    ROLE_SUPERVISOR = "supervisor"
    ROLE_OPERATIONS_MANAGER = "operations_manager"
    ROLE_EMPLOYEE = "employee"

    ROLE_CHOICES = [
        (ROLE_HR, "HR"),
        (ROLE_SUPERVISOR, "Supervisor"),
        (ROLE_OPERATIONS_MANAGER, "Operations Manager"),
        (ROLE_EMPLOYEE, "Employee"),
    ]

    username = None
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=30, blank=True)
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        blank=True,
        help_text="Business role used for HR workflow permissions.",
    )
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def role_label(self):
        return self.get_role_display() if self.role else "No Role"

    @property
    def is_hr(self):
        return self.is_superuser or self.role == self.ROLE_HR

    @property
    def is_supervisor(self):
        return self.is_superuser or self.role == self.ROLE_SUPERVISOR

    @property
    def is_operations_manager(self):
        return self.is_superuser or self.role == self.ROLE_OPERATIONS_MANAGER

    @property
    def is_employee_role(self):
        return self.is_superuser or self.role == self.ROLE_EMPLOYEE

    @property
    def is_management_role(self):
        return self.is_superuser or self.role in {
            self.ROLE_HR,
            self.ROLE_SUPERVISOR,
            self.ROLE_OPERATIONS_MANAGER,
        }