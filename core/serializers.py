from rest_framework import serializers
import os
from .models import User, Invoice, InvoiceAttachment, Reimbursement, TripGroupInvoice, EmailAccount, ProcessedEmail
from .trip_groups import build_default_trip_title, infer_home_city, matches_home_city, is_long_distance_transport


class InvoiceAttachmentSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='original_name', read_only=True)

    class Meta:
        model = InvoiceAttachment
        fields = (
            'id',
            'name',
            'file',
            'attachment_type',
            'travel_start_date',
            'travel_end_date',
            'travel_departure_place',
            'travel_arrival_place',
            'travel_details',
            'travel_total_amount',
            'application_date',
            'applicant_phone',
            'created_at',
        )

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'real_name', 'company', 'city', 'department', 'dept_leader', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class CurrentUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'real_name', 'company', 'city', 'department', 'dept_leader', 'is_active', 'is_superuser')


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'real_name', 'company', 'city', 'department', 'dept_leader', 'is_active', 'is_superuser', 'password')
        extra_kwargs = {
            'is_superuser': {'read_only': True},
        }

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'This field is required.'})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create_user(password=password, **validated_data)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class InvoiceSerializer(serializers.ModelSerializer):
    is_submitted = serializers.SerializerMethodField()
    trip_group_title = serializers.SerializerMethodField()
    reimbursement_status = serializers.SerializerMethodField()
    attachments = InvoiceAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = (
            'user',
            'created_at',
            'invoice_number',
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
            'is_submitted',
            'invoice_type',
            'trip_group_title',
            'reimbursement_status',
        )

    def get_is_submitted(self, obj):
        # 只有当发票在待审核或已批准的报销单中时，才认为已提报
        # 被驳回的报销单对应的发票可以再次提报
        return obj.reimbursements.filter(status__in=['PENDING', 'APPROVED']).exists()

    def get_trip_group_title(self, obj):
        tgi = obj.trip_group_invoices.select_related('trip_group').first()
        if not tgi:
            return None
        trip_group = tgi.trip_group
        # 如果数据库中已有标题，直接返回
        if trip_group.title:
            return trip_group.title
        # 动态计算标题（自动归组的行程 title 存在 null 的情况）
        trip_links = list(
            TripGroupInvoice.objects.select_related('invoice')
            .filter(trip_group=trip_group)
            .order_by('sort_order', 'id')
        )
        trip_invoices = [link.invoice for link in trip_links]
        home_city = trip_group.home_city or infer_home_city(trip_group.user)
        core_invoices = [inv for inv in trip_invoices if is_long_distance_transport(inv)] or trip_invoices
        start_date = core_invoices[0].invoice_date if core_invoices else None
        end_date = core_invoices[-1].invoice_date if core_invoices else None
        destination_places: list[str] = []
        for inv in core_invoices:
            for place in (inv.departure_place, inv.arrival_place):
                if place and not matches_home_city(place, home_city) and place not in destination_places:
                    destination_places.append(place)
        # trip_index 无法精确获取，传 0 使用降级标题
        return build_default_trip_title(home_city, destination_places, 0, start_date, end_date)

    def get_reimbursement_status(self, obj):
        # 报销状态: 已报销(APPROVED) > 报销中(PENDING) > 未报销(无/仅REJECTED)
        statuses = set(obj.reimbursements.values_list('status', flat=True))
        if 'APPROVED' in statuses:
            return 'APPROVED'
        if 'PENDING' in statuses:
            return 'PENDING'
        return 'NONE'

    def validate_file(self, value):
        allowed_exts = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in allowed_exts:
            raise serializers.ValidationError(
                'Unsupported file type. Please upload a PDF or image file.'
            )
        return value

class ReimbursementSerializer(serializers.ModelSerializer):
    applicant = UserSerializer(read_only=True)
    invoices_details = InvoiceSerializer(source='invoices', many=True, read_only=True)
    reviewer = UserSerializer(read_only=True)
    details = serializers.JSONField(required=False)
    reviewer_id = serializers.PrimaryKeyRelatedField(
        source='reviewer',
        queryset=User.objects.filter(role='ACCOUNTANT'),
        write_only=True,
        required=False,
    )
    invoices = serializers.PrimaryKeyRelatedField(
        queryset=Invoice.objects.all(),
        many=True,
        required=False,
    )
    
    class Meta:
        model = Reimbursement
        fields = (
            'id',
            'applicant',
            'invoices',
            'invoices_details',
            'details',
            'status',
            'reviewer',
            'reviewer_id',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('applicant', 'created_at', 'updated_at', 'reviewer')


class EmailAccountSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={'input_type': 'password'})
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = EmailAccount
        fields = (
            'id',
            'email_address',
            'imap_host',
            'imap_port',
            'use_ssl',
            'username',
            'password',
            'has_password',
            'folder',
            'keywords',
            'poll_interval_minutes',
            'enabled',
            'last_checked_at',
            'last_error',
        )
        read_only_fields = ('id', 'last_checked_at', 'last_error', 'has_password')

    def get_has_password(self, obj):
        return bool(obj.password)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.password = password
        instance.save()
        return instance

    def create(self, validated_data):
        if not validated_data.get('password'):
            raise serializers.ValidationError({'password': '首次配置必须填写邮箱密码或授权码'})
        return EmailAccount.objects.create(**validated_data)


class ProcessedEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessedEmail
        fields = (
            'id',
            'message_uid',
            'subject',
            'received_at',
            'processed_at',
            'invoices_created',
            'attachments_attached',
            'note',
        )
