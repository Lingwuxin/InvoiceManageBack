from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, ReimbursementViewSet, TripGroupViewSet, UserViewSet, EmailAccountViewSet, current_user, accountant_list, my_trip_periods, my_timeline, create_separator, remove_separator

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'reimbursements', ReimbursementViewSet, basename='reimbursement')
router.register(r'trip-groups', TripGroupViewSet, basename='trip-group')
router.register(r'users', UserViewSet, basename='user')
router.register(r'email-account', EmailAccountViewSet, basename='email-account')

urlpatterns = [
    path('user/me/', current_user, name='current-user'),
    path('user/trips/', my_trip_periods, name='my-trip-periods'),
    path('user/timeline/', my_timeline, name='my-timeline'),
    path('user/separators/', create_separator, name='create-separator'),
    path('user/separators/<int:separator_id>/', remove_separator, name='remove-separator'),
    path('users/accountants/', accountant_list, name='accountant-list'),
    path('', include(router.urls)),
]
