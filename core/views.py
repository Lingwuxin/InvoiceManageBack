from rest_framework import viewsets, permissions, status, decorators
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.conf import settings
from django.http import HttpResponse
from .models import Invoice, Reimbursement, User
from django.db.models import QuerySet
from .serializers import (
    InvoiceSerializer,
    ReimbursementSerializer,
    UserSerializer,
    CurrentUserSerializer,
    AdminUserSerializer,
)
from decimal import Decimal, InvalidOperation
import datetime
from io import BytesIO
import os
from docxtpl import DocxTemplate
from tools.pdf_parser import PDFInvoiceParser


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
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Invoice]:
        queryset = Invoice.objects.filter(user=self.request.user)
        
        # 支持过滤出可提报的发票（排除已在待审核或已批准的报销单中的发票）
        available_only = self.request.query_params.get('available_only')
        if available_only and available_only.lower() in ('true', '1', 'yes'):
            # 排除在 PENDING 或 APPROVED 状态报销单中的发票
            queryset = queryset.exclude(
                reimbursements__status__in=['PENDING', 'APPROVED']
            )

        # 支持按类型筛选
        invoice_type = self.request.query_params.get('invoice_type')
        if invoice_type:
            queryset = queryset.filter(invoice_type=invoice_type)
        
        return queryset

    def perform_create(self, serializer):
        uploaded_file = serializer.validated_data.get('file')
        if not uploaded_file.name.lower().endswith('.pdf'):
             raise ValidationError("只能上传PDF格式的发票文件")
        
        try:
             # 直接从上传的文件对象解析
             parser = PDFInvoiceParser(uploaded_file)
             parsed = parser.parse()
        except Exception as e:
             raise ValidationError(f"发票解析失败: {str(e)}")
        
        # 重置文件指针，确保保存时文件内容完整
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)
            
        invoice_number = parsed.get("invoice_number")
        if Invoice.objects.filter(invoice_number=invoice_number).exists():
             raise ValidationError(f"发票号码 {invoice_number} 已存在，请勿重复上传")
        
        # 保存时传入发票号码
        invoice = serializer.save(user=self.request.user, invoice_number=invoice_number)
        
        # 应用其他解析出的字段
        self._apply_parsed_fields(invoice, parsed)
        invoice.save()

    def _try_parse_invoice(self, invoice: Invoice) -> None:
        # 该方法可以保留用于重新解析或其他用途，但在创建时不再调用
        file_path = invoice.file.path
        parsed = None
        ext = os.path.splitext(file_path)[1].lower()


        # 仅尝试PDF解析
        if ext == '.pdf':
            try:
                parser = PDFInvoiceParser(file_path)
                parsed = parser.parse()
            except Exception:
                parsed = None

            if parsed:
                self._apply_parsed_fields(invoice, parsed)

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
        
        # Attach extra parsed fields to the instance so they appear in the response
        if parsed.get('departure_place'):
            invoice.departure_place = parsed.get('departure_place')
        if parsed.get('arrival_place'):
            invoice.arrival_place = parsed.get('arrival_place')
        if parsed.get('invoice_type'):
            invoice.invoice_type = parsed.get('invoice_type')
        
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
            'invoice_type',
            'departure_place',
            'arrival_place',
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
        serializer.save(applicant=self.request.user, details=self.request.data)

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

    @decorators.action(detail=True, methods=['post'], url_path='export')
    def export(self, request, pk=None):
        reimbursement = self.get_object()
        base_payload = reimbursement.details or {}
        payload = {**base_payload, **(request.data or {})}
        context = self._build_export_context(reimbursement, payload)
        template_path = os.path.join(
            settings.BASE_DIR,
            'media',
            'implement',
            '差旅报销单-郑州-模板.docx',
        )

        if not os.path.exists(template_path):
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)

        doc = DocxTemplate(template_path)
        doc.render(context)
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        filename = f"reimbursement-{reimbursement.id}.docx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _build_export_context(self, reimbursement: Reimbursement, payload: dict) -> dict:
        user = reimbursement.applicant
        invoices = reimbursement.invoices.all()

        def safe_value(value, default=''):
            return value if value not in (None, '') else default

        def format_amount(value) -> str:
            if value is None:
                return ''
            return f"{value:.2f}" if isinstance(value, (int, float, Decimal)) else str(value)

        def format_date(value) -> str:
            if isinstance(value, (datetime.date, datetime.datetime)):
                return value.strftime('%Y-%m-%d')
            return safe_value(value)

        def today_display() -> str:
            today = datetime.date.today()
            return f"{today.year}年 {today.month} 月{today.day} 日"

        def to_cny_upper(value) -> str:
            if value in (None, ''):
                return ''
            try:
                amount = Decimal(str(value)).quantize(Decimal('0.01'))
            except (InvalidOperation, TypeError):
                return ''

            if amount == 0:
                return '零元整'

            digits = '零壹贰叁肆伍陆柒捌玖'
            units = ['元', '拾', '佰', '仟', '万', '拾', '佰', '仟', '亿']
            fraction_units = ['角', '分']

            integer_part = int(amount)
            fraction_part = int((amount - integer_part) * 100)

            integer_str = ''
            int_digits = list(str(integer_part))
            for i, num_char in enumerate(int_digits):
                num = int(num_char)
                unit = units[len(int_digits) - i - 1]
                if num == 0:
                    if not integer_str.endswith('零') and integer_str:
                        integer_str += '零'
                else:
                    integer_str += digits[num] + unit

            integer_str = integer_str.replace('零零', '零').replace('零万', '万').replace('零亿', '亿')
            integer_str = integer_str.rstrip('零')
            if not integer_str.endswith('元'):
                integer_str += '元'

            fraction_str = ''
            jiao = fraction_part // 10
            fen = fraction_part % 10
            if jiao:
                fraction_str += digits[jiao] + fraction_units[0]
            if fen:
                fraction_str += digits[fen] + fraction_units[1]

            return integer_str + (fraction_str or '整')

        cost_dept = safe_value(payload.get('cost_dept'), safe_value(user.department))

        transport_items = payload.get('transport_items') or []
        accommodation_items = payload.get('accommodation_items') or []
        expense_items = payload.get('expense_items') or []

        if not (transport_items or accommodation_items or expense_items):
            for invoice in invoices:
                if invoice.invoice_type == 'TRANSPORT':
                    transport_items.append({
                        'departure_date': format_date(invoice.invoice_date),
                        'departure_place': safe_value(invoice.departure_place),
                        'arrival_date': format_date(invoice.invoice_date),
                        'arrival_place': safe_value(invoice.arrival_place),
                        'transport_type': safe_value(invoice.product_name),
                        'invoice_count': 1,
                        'amount': format_amount(invoice.amount),
                        'dept': cost_dept,
                    })
                elif invoice.invoice_type == 'ACCOMMODATION':
                    accommodation_items.append({
                        'traveler': safe_value(user.real_name, safe_value(user.username)),
                        'roommate': '-',
                        'city_level': safe_value(invoice.product_name),
                        'standard_total': '',
                        'actual_total': format_amount(invoice.amount),
                        'diff': '',
                        'subsidy': '',
                        'dept': cost_dept,
                    })
                else:
                    expense_items.append({
                        'expense_type': safe_value(invoice.product_name, '其他'),
                        'invoice_subject': safe_value(invoice.product_name),
                        'invoice_count': 1,
                        'amount': format_amount(invoice.amount),
                        'remark': safe_value(invoice.product_name),
                        'dept': cost_dept,
                    })

        total_amount = sum(
            float(item.get('amount') or 0)
            for group in (transport_items, accommodation_items, expense_items)
            for item in group
        )

        amount_num_value = payload.get('amount_num')
        if amount_num_value in (None, ''):
            amount_num_value = total_amount
        amount_num_text = format_amount(amount_num_value)
        amount_cn_text = safe_value(payload.get('amount_cn'), to_cny_upper(amount_num_value))

        return {
            'dept': safe_value(payload.get('dept'), safe_value(user.department)),
            'report_date': safe_value(payload.get('report_date'), today_display()),
            'traveler': safe_value(payload.get('traveler'), safe_value(user.real_name, safe_value(user.username))),
            'project_code': safe_value(payload.get('project_code')),
            'contract_signed': safe_value(payload.get('contract_signed')),
            'project_name': safe_value(payload.get('project_name')),
            'destination': safe_value(payload.get('destination')),
            'travel_range': safe_value(payload.get('travel_range')),
            'travel_days': safe_value(payload.get('travel_days')),
            'purpose': safe_value(payload.get('purpose')),
            'cost_dept': cost_dept,
            'advance_amount': safe_value(payload.get('advance_amount')),
            'supplement_amount': safe_value(payload.get('supplement_amount')),
            'refund_amount': safe_value(payload.get('refund_amount')),
            'amount_cn': amount_cn_text,
            'amount_num': amount_num_text,
            'payee': safe_value(payload.get('payee'), safe_value(user.real_name, safe_value(user.username))),
            'dept_leader': safe_value(payload.get('dept_leader')),
            'finance_leader': safe_value(payload.get('finance_leader')),
            'company_leader': safe_value(payload.get('company_leader')),
            'transport_items': transport_items,
            'accommodation_items': accommodation_items,
            'expense_items': expense_items,
        }
