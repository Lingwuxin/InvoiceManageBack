from rest_framework import viewsets, permissions, status, decorators
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.conf import settings
from django.http import HttpResponse
from .models import Invoice, InvoiceAttachment, Reimbursement, TripGroup, TripGroupInvoice, TripSeparator, User, EmailAccount, ProcessedEmail
from django.db.models import QuerySet
from .serializers import (
    InvoiceSerializer,
    InvoiceAttachmentSerializer,
    ReimbursementSerializer,
    UserSerializer,
    CurrentUserSerializer,
    AdminUserSerializer,
    EmailAccountSerializer,
    ProcessedEmailSerializer,
)
from decimal import Decimal, InvalidOperation
from typing import cast
import datetime
import os
from rest_framework.request import Request
from tools.pdf_parser import PDFInvoiceParser, RideHailingTripStatementParser
from .docx_export import render_reimbursement_docx
from .trip_groups import (
    attach_invoice_to_trip_group,
    build_timeline,
    build_user_trip_summary,
    delete_manual_trip_group,
    delete_separator,
    insert_separator,
    regroup_auto_trip_groups,
    remove_invoice_from_trip_group,
    save_manual_trip_group,
    update_trip_group_title,
    update_trip_group_invoice_category,
)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_user(request: Request):
    """获取当前登录用户信息"""
    serializer = CurrentUserSerializer(request.user)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def accountant_list(request: Request):
    """获取可选审批人列表"""
    accountants = User.objects.filter(role='ACCOUNTANT').order_by('id')
    serializer = UserSerializer(accountants, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_trip_periods(request: Request):
    home_city = request.query_params.get('home_city', '')
    summary = regroup_auto_trip_groups(cast(User, request.user), home_city)
    return Response(summary)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_timeline(request: Request):
    """获取用户行程时间线（含分隔符划分的行程段）"""
    return Response(build_timeline(cast(User, request.user)))


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_separator(request: Request):
    """在指定发票后插入行程分隔符"""
    data = cast(dict, request.data)
    after_invoice_id = data.get('after_invoice_id')
    label = data.get('label', '')
    result = insert_separator(cast(User, request.user), after_invoice_id, label)
    return Response(result, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_separator(request: Request, separator_id: int):
    """删除行程分隔符"""
    result = delete_separator(cast(User, request.user), separator_id)
    return Response(result)


class TripGroupViewSet(viewsets.GenericViewSet):
    queryset = TripGroup.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[TripGroup]:  # type: ignore[override]
        return TripGroup.objects.filter(user=cast(User, self.request.user)).order_by('start_date', 'created_at', 'id')

    def list(self, request: Request):
        home_city = request.query_params.get('home_city', '')
        summary = regroup_auto_trip_groups(cast(User, request.user), home_city)
        return Response(summary)

    def create(self, request: Request):
        data = cast(dict, request.data)
        invoice_ids: list[int] = cast(list, data.get('invoice_ids') or [])
        home_city = data.get('home_city', '')
        save_manual_trip_group(cast(User, request.user), invoice_ids, home_city)
        return Response(build_user_trip_summary(cast(User, request.user), home_city), status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk=None):
        data = cast(dict, request.data)
        trip_group = self.get_object()
        invoice_ids: list[int] = cast(list, data.get('invoice_ids') or [])
        home_city = data.get('home_city', '')
        save_manual_trip_group(cast(User, request.user), invoice_ids, home_city, trip_group)
        return Response(build_user_trip_summary(cast(User, request.user), home_city))

    def destroy(self, request: Request, pk=None):
        trip_group = self.get_object()
        delete_manual_trip_group(cast(User, request.user), trip_group)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=['post'], url_path='attach-invoice')
    def attach_invoice(self, request: Request, pk=None):
        data = cast(dict, request.data)
        trip_group = self.get_object()
        invoice_id = data.get('invoice_id')
        reimbursement_category = data.get('reimbursement_category', 'OTHER')
        summary = attach_invoice_to_trip_group(cast(User, request.user), trip_group, int(invoice_id), reimbursement_category)
        return Response(summary)

    @decorators.action(detail=True, methods=['post'], url_path='update-invoice-category')
    def update_invoice_category(self, request: Request, pk=None):
        data = cast(dict, request.data)
        trip_group = self.get_object()
        invoice_id = data.get('invoice_id')
        reimbursement_category = data.get('reimbursement_category', 'OTHER')
        summary = update_trip_group_invoice_category(cast(User, request.user), trip_group, int(invoice_id), reimbursement_category)
        return Response(summary)

    @decorators.action(detail=True, methods=['post'], url_path='remove-invoice')
    def remove_invoice(self, request: Request, pk=None):
        data = cast(dict, request.data)
        trip_group = self.get_object()
        invoice_id = data.get('invoice_id')
        summary = remove_invoice_from_trip_group(cast(User, request.user), trip_group, int(invoice_id))
        return Response(summary)

    @decorators.action(detail=True, methods=['post'], url_path='update-title')
    def update_title(self, request: Request, pk=None):
        data = cast(dict, request.data)
        trip_group = self.get_object()
        summary = update_trip_group_title(cast(User, request.user), trip_group, data.get('title', ''))
        return Response(summary)

    @decorators.action(detail=False, methods=['post'], url_path='auto-regroup')
    def auto_regroup(self, request: Request):
        data = cast(dict, request.data)
        home_city = data.get('home_city', '')
        summary = regroup_auto_trip_groups(cast(User, request.user), home_city)
        return Response(summary)

    @decorators.action(detail=True, methods=['get'], url_path='download-invoices')
    def download_invoices(self, request: Request, pk=None):
        """下载该行程下所有发票（按 sort_order）合并后的 PDF，附件追加在后面。"""
        from .pdf_merge import build_trip_merged_pdf

        trip_group = self.get_object()
        tg_invoices = (
            TripGroupInvoice.objects
            .filter(trip_group=trip_group)
            .select_related('invoice')
            .order_by('sort_order', 'id')
        )

        invoice_files: list[str] = []
        attachment_files: list[str] = []
        for tgi in tg_invoices:
            inv = tgi.invoice
            if inv.file:
                invoice_files.append(inv.file.path)
            for att in inv.attachments.all():
                if att.file:
                    attachment_files.append(att.file.path)

        if not invoice_files and not attachment_files:
            return Response({'detail': '该行程下没有可下载的发票或附件。'}, status=status.HTTP_404_NOT_FOUND)

        pdf_bytes = build_trip_merged_pdf(invoice_files, attachment_files)

        title = trip_group.title or f'行程{trip_group.pk}'
        filename = f'{title}_发票合并.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        from urllib.parse import quote
        response['Content-Disposition'] = (
            f"attachment; filename=trip_{trip_group.pk}_invoices.pdf; "
            f"filename*=UTF-8''{quote(filename)}"
        )
        return response


class IsSuperUser(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:  # type: ignore[override]
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('id')
    serializer_class = AdminUserSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Invoice]:  # type: ignore[override]
        drf_request = cast(Request, self.request)
        queryset = Invoice.objects.filter(user=cast(User, drf_request.user))
        
        # 支持过滤出可提报的发票（排除已在待审核或已批准的报销单中的发票）
        available_only = drf_request.query_params.get('available_only')
        if available_only and available_only.lower() in ('true', '1', 'yes'):
            # 排除在 PENDING 或 APPROVED 状态报销单中的发票
            queryset = queryset.exclude(
                reimbursements__status__in=['PENDING', 'APPROVED']
            )

        # 支持按类型筛选
        invoice_type = drf_request.query_params.get('invoice_type')
        if invoice_type:
            queryset = queryset.filter(invoice_type=invoice_type)
        
        return queryset

    def perform_create(self, serializer):
        uploaded_file = serializer.validated_data.get('file')
        if not uploaded_file.name.lower().endswith('.pdf'):
             raise ValidationError("只能上传PDF格式的发票文件")

        user = cast(User, self.request.user)

        # 行程单不是发票，自动匹配并附加到对应发票
        is_trip, matched_invoice = self._try_attach_trip_statement(uploaded_file, user)
        if is_trip:
            serializer.instance = matched_invoice
            return

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
        invoice = serializer.save(user=cast(User, self.request.user), invoice_number=invoice_number)

        # 应用其他解析出的字段
        self._apply_parsed_fields(invoice, parsed)
        invoice.save()
        if invoice.invoice_type == 'TRANSPORT':
            regroup_auto_trip_groups(cast(User, self.request.user))

    def _try_attach_trip_statement(self, uploaded_file, user) -> tuple[bool, Invoice | None]:
        """检测是否为网约车行程单 PDF，若是则自动匹配对应发票并附加。

        Returns:
            (is_trip_statement, matched_invoice_or_None)
        """
        # 通过文件名快速判定，避免不必要的 PDF 解析
        lower_name = uploaded_file.name.lower()
        quick_hint = '行程单' in lower_name or 'trip' in lower_name

        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)

        try:
            trip_parser = RideHailingTripStatementParser(uploaded_file)
            if not trip_parser._is_trip_statement():
                if hasattr(uploaded_file, 'seek'):
                    uploaded_file.seek(0)
                return False, None

            trip_data = trip_parser.parse()
        except Exception:
            if not quick_hint:
                if hasattr(uploaded_file, 'seek'):
                    uploaded_file.seek(0)
                return False, None
            # 文件名暗示是行程单但解析失败 → 向上抛出
            raise ValidationError("行程单解析失败，请检查文件是否损坏")

        total_amount = trip_data.get('travel_total_amount') or ''
        if not total_amount:
            raise ValidationError("行程单无法提取金额，无法匹配对应发票")

        try:
            amount_decimal = Decimal(str(total_amount))
        except Exception:
            raise ValidationError(f"行程单金额格式异常: {total_amount}")

        travel_start = trip_data.get('travel_start_date') or ''

        # 匹配：同一用户，金额完全一致
        match = Invoice.objects.filter(
            user=user,
            amount=amount_decimal,
        )
        if travel_start:
            match = match.filter(invoice_date__gte=travel_start)
        match = match.order_by('-created_at').first()

        # 容忍 0.01 误差（PDF 提取格式差异）
        if not match:
            match = Invoice.objects.filter(
                user=user,
                amount__gte=amount_decimal - Decimal('0.01'),
                amount__lte=amount_decimal + Decimal('0.01'),
            ).order_by('-created_at').first()

        if not match:
            raise ValidationError(
                f"未找到金额为 ¥{total_amount} 的对应发票，请先上传发票后再上传行程单"
            )

        # 创建附件
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)

        InvoiceAttachment.objects.create(
            invoice=match,
            file=uploaded_file,
            original_name=uploaded_file.name,
            attachment_type=trip_data.get('attachment_type', 'RIDE_HAILING_TRIP_STATEMENT'),
            travel_start_date=trip_data.get('travel_start_date'),
            travel_end_date=trip_data.get('travel_end_date'),
            travel_departure_place=trip_data.get('travel_departure_place', ''),
            travel_arrival_place=trip_data.get('travel_arrival_place', ''),
            travel_details=trip_data.get('travel_details', []),
            travel_total_amount=amount_decimal,
            application_date=trip_data.get('application_date'),
            applicant_phone=trip_data.get('applicant_phone', ''),
        )

        return True, match

    def perform_destroy(self, instance):
        user = instance.user
        should_regroup = instance.invoice_type == 'TRANSPORT' or instance.trip_group_invoices.exists()
        instance.delete()
        if should_regroup:
            regroup_auto_trip_groups(user)

    @decorators.action(detail=True, methods=['post'], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        invoice = self.get_object()
        uploaded_file = request.FILES.get('file')
        if uploaded_file is None:
            raise ValidationError({'file': '请选择要上传的附件文件'})

        attachment = InvoiceAttachment.objects.create(
            invoice=invoice,
            file=uploaded_file,
            original_name=uploaded_file.name,
        )
        return Response(InvoiceAttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=['delete'], url_path=r'attachments/(?P<attachment_id>[^/.]+)')
    def delete_attachment(self, request, pk=None, attachment_id=None):
        invoice = self.get_object()
        attachment = InvoiceAttachment.objects.filter(invoice=invoice, pk=attachment_id).first()
        if attachment is None:
            raise ValidationError({'attachment_id': '附件不存在'})
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        
        invoice_type_val = parsed.get('invoice_type')
        if invoice_type_val:
            invoice.invoice_type = str(invoice_type_val)
        
        invoice.specification_model = clean_value(parsed.get('specification_model'))
        invoice.unit = clean_value(parsed.get('unit'))
        invoice.quantity = clean_value(parsed.get('quantity'))
        invoice.unit_price = clean_value(parsed.get('unit_price'))
        invoice.money_without_tax = clean_value(parsed.get('money_without_tax'))
        invoice.tax_rate = clean_value(parsed.get('tax_rate'))
        invoice.tax_amount = clean_value(parsed.get('tax_amount'))
        invoice.amount_in_words = clean_value(parsed.get('amount_in_words'))
        invoice.amount_in_figures = clean_value(parsed.get('amount_in_figures'))

        # 服务开始/结束时间（datetime 字段）
        from django.utils.timezone import make_aware
        for field_name in ('service_start_date', 'service_end_date'):
            dt_value = parsed.get(field_name)
            if dt_value:
                try:
                    naive = datetime.datetime.fromisoformat(str(dt_value))
                    setattr(invoice, field_name, make_aware(naive))
                except (ValueError, TypeError):
                    pass

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
            'service_start_date',
            'service_end_date',
        ])

class ReimbursementViewSet(viewsets.ModelViewSet):
    serializer_class = ReimbursementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self) -> QuerySet[Reimbursement]:  # type: ignore[override]
        drf_request = cast(Request, self.request)
        user = cast(User, drf_request.user)
        if user.role == 'ACCOUNTANT':
            qs = Reimbursement.objects.all()
        else:
            qs = Reimbursement.objects.filter(applicant=user)
        
        # 支持按状态过滤
        status_filter = drf_request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(applicant=cast(User, self.request.user), details=cast(dict, cast(Request, self.request).data))

    def destroy(self, request: Request, *args, **kwargs):
        reimbursement = self.get_object()
        if reimbursement.applicant_id != request.user.id:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if reimbursement.status != 'PENDING':
            return Response({'detail': 'Only pending reimbursements can be canceled.'}, status=status.HTTP_400_BAD_REQUEST)

        reimbursement.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request: Request, pk=None):
        reviewer = cast(User, request.user)
        if reviewer.role != 'ACCOUNTANT':
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        
        reimbursement = self.get_object()
        action = cast(dict, request.data).get('action') # 'approve' or 'reject'
        
        if action == 'approve':
            reimbursement.status = 'APPROVED'
        elif action == 'reject':
            reimbursement.status = 'REJECTED'
        else:
            return Response({'detail': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)
            
        reimbursement.reviewer = reviewer
        reimbursement.save()
        return Response({'status': reimbursement.status})

    @decorators.action(detail=True, methods=['post'], url_path='export')
    def export(self, request: Request, pk=None):
        reimbursement = self.get_object()
        base_payload = reimbursement.details or {}
        payload = {**base_payload, **(cast(dict, request.data) or {})}
        context = self._build_export_context(reimbursement, payload)
        template_path = os.path.join(
            settings.BASE_DIR,
            'media',
            'implement',
            '差旅报销单-郑州-模板.docx',
        )

        if not os.path.exists(template_path):
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)

        document_bytes = render_reimbursement_docx(template_path, context)

        filename = f"reimbursement-{reimbursement.id}.docx"
        response = HttpResponse(
            document_bytes,
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

        def compute_travel_range() -> str:
            start = format_date(payload.get('departure_date'))
            end = format_date(payload.get('return_date'))
            if start and end:
                return f'{start} 至 {end}'
            return start or end

        def compute_travel_days() -> str:
            raw_value = payload.get('travel_days')
            if raw_value not in (None, ''):
                return safe_value(raw_value)
            start = payload.get('departure_date')
            end = payload.get('return_date')
            if not start or not end:
                return ''
            try:
                start_date = datetime.date.fromisoformat(str(start))
                end_date = datetime.date.fromisoformat(str(end))
            except ValueError:
                return ''
            diff = (end_date - start_date).days + 1
            return str(diff) if diff > 0 else ''

        def format_count(value, default='1') -> str:
            if value in (None, ''):
                return default
            return str(value)

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

        default_traveler = safe_value(payload.get('traveler'), safe_value(payload.get('payee'), safe_value(user.real_name, safe_value(user.username))))
        destination = safe_value(payload.get('destination'), safe_value(payload.get('departure_place')))
        travel_range = safe_value(payload.get('travel_range'), compute_travel_range())
        travel_days = compute_travel_days()
        contract_signed = safe_value(payload.get('contract_signed'), safe_value(payload.get('signedContract')))

        def to_float(value: object) -> float:
            try:
                return float(str(value))
            except (TypeError, ValueError):
                return 0.0

        def normalize_transport_items(items: list[dict]) -> list[dict]:
            normalized = []
            for item in items:
                normalized.append({
                    'departure_date': format_date(item.get('departure_date')),
                    'departure_place': safe_value(item.get('departure_place')),
                    'arrival_date': format_date(item.get('arrival_date')),
                    'arrival_place': safe_value(item.get('arrival_place')),
                    'transport_type': safe_value(item.get('transport_type')),
                    'invoice_count': format_count(item.get('invoice_count', item.get('quantity'))),
                    'amount': format_amount(item.get('amount')),
                    'dept': safe_value(item.get('dept'), cost_dept),
                })
            return normalized

        def normalize_accommodation_items(items: list[dict]) -> list[dict]:
            normalized = []
            for item in items:
                standard_total = item.get('standard_total', item.get('standard_cost'))
                actual_total = item.get('actual_total', item.get('actual_cost', item.get('amount')))
                diff_value = item.get('diff')
                if diff_value in (None, ''):
                    diff_value = to_float(standard_total) - to_float(actual_total)

                subsidy_value = item.get('subsidy')
                if subsidy_value in (None, ''):
                    subsidy_value = item.get('amount')

                normalized.append({
                    'traveler': safe_value(item.get('traveler'), default_traveler),
                    'roommate': safe_value(item.get('roommate'), '-'),
                    'city_level': safe_value(item.get('city_level'), safe_value(item.get('city'))),
                    'standard_total': format_amount(standard_total),
                    'actual_total': format_amount(actual_total),
                    'diff': format_amount(diff_value),
                    'subsidy': format_amount(subsidy_value),
                    'dept': safe_value(item.get('dept'), cost_dept),
                })
            return normalized

        def normalize_expense_items(items: list[dict]) -> list[dict]:
            normalized = []
            for item in items:
                normalized.append({
                    'expense_type': safe_value(item.get('expense_type'), '其他'),
                    'invoice_subject': safe_value(item.get('invoice_subject'), safe_value(item.get('expense_name'))),
                    'invoice_count': format_count(item.get('invoice_count', item.get('quantity'))),
                    'amount': format_amount(item.get('amount')),
                    'remark': safe_value(item.get('remark'), safe_value(item.get('expense_name'))),
                    'dept': safe_value(item.get('dept'), cost_dept),
                })
            return normalized

        transport_items = normalize_transport_items(payload.get('transport_items') or [])
        accommodation_items = normalize_accommodation_items(payload.get('accommodation_items') or [])
        expense_items = normalize_expense_items(payload.get('expense_items') or [])

        if not (transport_items or accommodation_items or expense_items):
            for invoice in invoices:
                if invoice.invoice_type == 'TRANSPORT':
                    transport_items.append({
                        'departure_date': format_date(invoice.invoice_date),
                        'departure_place': safe_value(invoice.departure_place),
                        'arrival_date': format_date(invoice.invoice_date),
                        'arrival_place': safe_value(invoice.arrival_place),
                        'transport_type': safe_value(invoice.product_name),
                        'invoice_count': '1',
                        'amount': format_amount(invoice.amount),
                        'dept': cost_dept,
                    })
                elif invoice.invoice_type == 'ACCOMMODATION':
                    accommodation_items.append({
                        'traveler': default_traveler,
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
                        'invoice_count': '1',
                        'amount': format_amount(invoice.amount),
                        'remark': safe_value(invoice.product_name),
                        'dept': cost_dept,
                    })

        total_amount = (
            sum(float(item.get('amount') or 0) for item in transport_items)
            + sum(float(item.get('actual_total') or 0) for item in accommodation_items)
            + sum(float(item.get('amount') or 0) for item in expense_items)
        )

        amount_num_value = total_amount
        amount_num_text = format_amount(amount_num_value)
        amount_cn_text = to_cny_upper(amount_num_value)

        return {
            'dept': safe_value(payload.get('dept'), safe_value(user.department)),
            'report_date': safe_value(payload.get('report_date'), today_display()),
            'traveler': default_traveler,
            'project_code': safe_value(payload.get('project_code')),
            'contract_signed': contract_signed,
            'project_name': safe_value(payload.get('project_name')),
            'destination': destination,
            'travel_range': travel_range,
            'travel_days': travel_days,
            'purpose': safe_value(payload.get('purpose')),
            'cost_dept': cost_dept,
            'advance_amount': safe_value(payload.get('advance_amount')),
            'supplement_amount': safe_value(payload.get('supplement_amount')),
            'refund_amount': safe_value(payload.get('refund_amount')),
            'amount_cn': amount_cn_text,
            'amount_num': amount_num_text,
            'payee': safe_value(payload.get('payee'), default_traveler),
            'dept_leader': safe_value(payload.get('dept_leader'), safe_value(user.dept_leader)),
            'finance_leader': safe_value(payload.get('finance_leader')),
            'company_leader': safe_value(payload.get('company_leader')),
            'transport_items': transport_items,
            'accommodation_items': accommodation_items,
            'expense_items': expense_items,
        }


class EmailLogsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class EmailAccountViewSet(viewsets.GenericViewSet):
    """当前登录用户的邮箱账户配置（一个用户最多一个）。"""
    serializer_class = EmailAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_account(self, user: User) -> EmailAccount | None:
        return EmailAccount.objects.filter(user=user).first()

    def list(self, request: Request):
        account = self._get_account(cast(User, request.user))
        if not account:
            return Response(None)
        return Response(EmailAccountSerializer(account).data)

    def create(self, request: Request):
        user = cast(User, request.user)
        if EmailAccount.objects.filter(user=user).exists():
            return Response({'detail': '邮箱账户已存在，请使用更新接口'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = EmailAccountSerializer(data=cast(dict, request.data))
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=False, methods=['put', 'patch'], url_path='update')
    def update_account(self, request: Request):
        user = cast(User, request.user)
        account = self._get_account(user)
        if not account:
            return Response({'detail': '请先创建邮箱配置'}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailAccountSerializer(account, data=cast(dict, request.data), partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @decorators.action(detail=False, methods=['delete'], url_path='remove')
    def remove(self, request: Request):
        user = cast(User, request.user)
        account = self._get_account(user)
        if account:
            account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=False, methods=['post'], url_path='test')
    def test_connection(self, request: Request):
        from .email_service import _open_imap  # noqa: WPS433 局部导入避免循环
        user = cast(User, request.user)
        account = self._get_account(user)
        if not account:
            return Response({'detail': '请先创建邮箱配置'}, status=status.HTTP_404_NOT_FOUND)
        try:
            with _open_imap(account) as imap:
                imap.select(account.folder or 'INBOX')
            return Response({'ok': True, 'message': '连接成功'})
        except Exception as exc:  # noqa: BLE001
            return Response({'ok': False, 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @decorators.action(detail=False, methods=['post'], url_path='sync')
    def sync_now(self, request: Request):
        from .email_service import fetch_account
        user = cast(User, request.user)
        account = self._get_account(user)
        if not account:
            return Response({'detail': '请先创建邮箱配置'}, status=status.HTTP_404_NOT_FOUND)
        summary = fetch_account(account)
        return Response(summary.as_dict())

    @decorators.action(detail=False, methods=['get'], url_path='logs')
    def logs(self, request: Request):
        user = cast(User, request.user)
        account = self._get_account(user)
        if not account:
            return Response({'count': 0, 'results': []})
        qs = ProcessedEmail.objects.filter(account=account).order_by('-processed_at')
        paginator = EmailLogsPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = ProcessedEmailSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = ProcessedEmailSerializer(qs, many=True)
        return Response({'count': qs.count(), 'results': serializer.data})



