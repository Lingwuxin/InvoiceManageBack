from django.contrib import admin
from .models import User, Invoice, InvoiceAttachment, Reimbursement, TripGroup, TripGroupInvoice

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


@admin.register(TripGroup)
class TripGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'source', 'home_city', 'start_date', 'end_date', 'is_complete')
    list_filter = ('source', 'is_complete', 'home_city')


@admin.register(TripGroupInvoice)
class TripGroupInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'trip_group', 'invoice', 'sort_order', 'created_at')
    list_filter = ('trip_group__source',)


@admin.register(InvoiceAttachment)
class InvoiceAttachmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'invoice', 'original_name', 'attachment_type', 'travel_total_amount', 'application_date', 'created_at')
    list_filter = ('attachment_type',)
