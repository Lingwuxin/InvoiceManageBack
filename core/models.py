from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = (
        ('EMPLOYEE', 'Employee'),
        ('ACCOUNTANT', 'Accountant'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='EMPLOYEE')

class Invoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    file = models.FileField(upload_to='invoices/')
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice {self.id} - {self.user.username}"

class Reimbursement(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reimbursements')
    invoices = models.ManyToManyField(Invoice, related_name='reimbursements')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reimbursements')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Reimbursement {self.id} - {self.applicant.username}"
