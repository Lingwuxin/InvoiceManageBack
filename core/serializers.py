from rest_framework import serializers
from .models import User, Invoice, Reimbursement

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user

class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ('user', 'created_at')

class ReimbursementSerializer(serializers.ModelSerializer):
    applicant = UserSerializer(read_only=True)
    invoices_details = InvoiceSerializer(source='invoices', many=True, read_only=True)
    
    class Meta:
        model = Reimbursement
        fields = '__all__'
        read_only_fields = ('applicant', 'created_at', 'updated_at', 'reviewer')
