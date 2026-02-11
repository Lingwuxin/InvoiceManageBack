from rest_framework import serializers
import os
from .models import User, Invoice, Reimbursement

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user


class CurrentUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'is_active', 'is_superuser')


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'is_active', 'is_superuser', 'password')
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

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = (
            'user',
            'created_at',
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
        )

    def get_is_submitted(self, obj):
        # 只有当发票在待审核或已批准的报销单中时，才认为已提报
        # 被驳回的报销单对应的发票可以再次提报
        return obj.reimbursements.filter(status__in=['PENDING', 'APPROVED']).exists()

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
    reviewer_id = serializers.PrimaryKeyRelatedField(
        source='reviewer',
        queryset=User.objects.filter(role='ACCOUNTANT'),
        write_only=True,
        required=True,
    )
    
    class Meta:
        model = Reimbursement
        fields = (
            'id',
            'applicant',
            'invoices',
            'invoices_details',
            'status',
            'reviewer',
            'reviewer_id',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('applicant', 'created_at', 'updated_at', 'reviewer')
