from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, ReimbursementViewSet, current_user

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'reimbursements', ReimbursementViewSet, basename='reimbursement')

urlpatterns = [
    path('user/me/', current_user, name='current-user'),
    path('', include(router.urls)),
]
