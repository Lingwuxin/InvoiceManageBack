from rest_framework import viewsets, permissions, status, decorators
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import Invoice, Reimbursement
from .serializers import InvoiceSerializer, ReimbursementSerializer, UserSerializer


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_user(request):
    """获取当前登录用户信息"""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Invoice.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class ReimbursementViewSet(viewsets.ModelViewSet):
    serializer_class = ReimbursementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ACCOUNTANT':
            qs = Reimbursement.objects.all()
        else:
            qs = Reimbursement.objects.filter(applicant=user)
        
        # 支持按状态过滤
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(applicant=self.request.user)

    @decorators.action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        if request.user.role != 'ACCOUNTANT':
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        
        reimbursement = self.get_object()
        action = request.data.get('action') # 'approve' or 'reject'
        
        if action == 'approve':
            reimbursement.status = 'APPROVED'
        elif action == 'reject':
            reimbursement.status = 'REJECTED'
        else:
            return Response({'detail': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)
            
        reimbursement.reviewer = request.user
        reimbursement.save()
        return Response({'status': reimbursement.status})
