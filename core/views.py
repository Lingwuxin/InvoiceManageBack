from rest_framework import viewsets, permissions, status, decorators
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import Invoice, Reimbursement, User
from .serializers import (
    InvoiceSerializer,
    ReimbursementSerializer,
    UserSerializer,
    CurrentUserSerializer,
    AdminUserSerializer,
)
from decimal import Decimal, InvalidOperation
import datetime
import os
from tools.pdf_parser import PDFInvoiceParser
from tools.ocr_parser import OCRInvoiceParser


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_user(request):
    """获取当前登录用户信息"""
    serializer = CurrentUserSerializer(request.user)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def accountant_list(request):
    """获取可选审批人列表"""
    accountants = User.objects.filter(role='ACCOUNTANT').order_by('id')
    serializer = UserSerializer(accountants, many=True)
    return Response(serializer.data)


class IsSuperUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('id')
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Invoice.objects.filter(user=self.request.user)
        
        # 支持过滤出可提报的发票（排除已在待审核或已批准的报销单中的发票）
        available_only = self.request.query_params.get('available_only')
        if available_only and available_only.lower() in ('true', '1', 'yes'):
            # 排除在 PENDING 或 APPROVED 状态报销单中的发票
            queryset = queryset.exclude(
                reimbursements__status__in=['PENDING', 'APPROVED']
            )
        
        return queryset

    def perform_create(self, serializer):
        invoice = serializer.save(user=self.request.user)
        self._try_parse_invoice(invoice)

    def _try_parse_invoice(self, invoice: Invoice) -> None:
        file_path = invoice.file.path
        parsed = None
        ext = os.path.splitext(file_path)[1].lower()
        image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

        if ext == '.pdf':
            try:
                parser = PDFInvoiceParser(file_path)
                parsed = parser.parse()
            except Exception:
                parsed = None

            if parsed and not self._needs_ocr(parsed):
                self._apply_parsed_fields(invoice, parsed)
                return

        if ext in image_exts or ext == '.pdf':
            ocr_parsed = self._try_ocr_parse(file_path)
            if ocr_parsed:
                self._apply_parsed_fields(invoice, ocr_parsed)

    def _needs_ocr(self, parsed: dict) -> bool:
        return not parsed.get('amount_in_figures') or not parsed.get('invoice_date')

    def _try_ocr_parse(self, file_path: str) -> dict | None:
        try:
            parser = OCRInvoiceParser(file_path, lang='ch')
            return parser.parse()
        except Exception:
            return None

    def _apply_parsed_fields(self, invoice: Invoice, parsed: dict) -> None:
        amount_value = parsed.get('amount_in_figures')
        if amount_value:
            try:
                invoice.amount = Decimal(str(amount_value))
            except (InvalidOperation, TypeError):
                pass
        date_value = parsed.get('invoice_date')
        if date_value:
            try:
                invoice.invoice_date = datetime.date.fromisoformat(str(date_value))
            except ValueError:
                pass

        def clean_value(value):
            return value if value not in (None, '') else None

        invoice.product_name = clean_value(parsed.get('product_name'))
        invoice.specification_model = clean_value(parsed.get('specification_model'))
        invoice.unit = clean_value(parsed.get('unit'))
        invoice.quantity = clean_value(parsed.get('quantity'))
        invoice.unit_price = clean_value(parsed.get('unit_price'))
        invoice.money_without_tax = clean_value(parsed.get('money_without_tax'))
        invoice.tax_rate = clean_value(parsed.get('tax_rate'))
        invoice.tax_amount = clean_value(parsed.get('tax_amount'))
        invoice.amount_in_words = clean_value(parsed.get('amount_in_words'))
        invoice.amount_in_figures = clean_value(parsed.get('amount_in_figures'))
        invoice.save(update_fields=[
            'amount',
            'invoice_date',
            'product_name',
            'specification_model',
            'unit',
            'quantity',
            'unit_price',
            'money_without_tax',
            'tax_rate',
            'tax_amount',
            'amount_in_words',
            'amount_in_figures',
        ])

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
