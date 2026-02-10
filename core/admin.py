from django.contrib import admin
from .models import User, Invoice, Reimbursement

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'role')
    list_filter = ('role',)

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'amount', 'invoice_date', 'created_at')
    list_filter = ('user',)

@admin.register(Reimbursement)
class ReimbursementAdmin(admin.ModelAdmin):
    list_display = ('id', 'applicant', 'status', 'reviewer', 'created_at')
    list_filter = ('status',)
