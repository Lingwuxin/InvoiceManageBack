from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, ReimbursementViewSet, UserViewSet, current_user, accountant_list

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'reimbursements', ReimbursementViewSet, basename='reimbursement')
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('user/me/', current_user, name='current-user'),
    path('users/accountants/', accountant_list, name='accountant-list'),
    path('', include(router.urls)),
]
