import datetime
import tempfile
from typing import Any, cast
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from .models import Invoice, InvoiceAttachment, Reimbursement, TripGroup, TripGroupInvoice, User
from .trip_groups import group_trip_periods, regroup_auto_trip_groups


class TripPeriodLogicTests(SimpleTestCase):
	def setUp(self):
		self.user = cast(User, User(
			username='zhengzhou-user',
			city='郑州',
			company='淘数郑州',
			department='郑州公司交付部',
			real_name='张三',
		))

	def create_invoice(
		self,
		invoice_number: str,
		invoice_date: datetime.date,
		departure_place: str,
		arrival_place: str,
		product_name: str,
		created_at: datetime.datetime,
	) -> Invoice:
		return Invoice(
			id=len(invoice_number),
			user=self.user,
			file='invoices/test.pdf',
			invoice_number=invoice_number,
			invoice_type='TRANSPORT',
			amount='128.50',
			invoice_date=invoice_date,
			product_name=product_name,
			departure_place=departure_place,
			arrival_place=arrival_place,
			created_at=created_at,
		)

	def test_groups_trip_when_depart_and_return_use_different_transport(self):
		invoices = [
			self.create_invoice(
				invoice_number='T1001',
				invoice_date=datetime.date(2026, 4, 1),
				departure_place='郑州东',
				arrival_place='上海虹桥',
				product_name='铁路客票',
				created_at=datetime.datetime(2026, 4, 1, 9, 0),
			),
			self.create_invoice(
				invoice_number='F1002',
				invoice_date=datetime.date(2026, 4, 4),
				departure_place='上海虹桥',
				arrival_place='郑州',
				product_name='航空客票',
				created_at=datetime.datetime(2026, 4, 4, 9, 0),
			),
		]

		result = group_trip_periods(self.user, invoices)

		self.assertEqual(result['home_city'], '郑州')
		self.assertEqual(result['total_trips'], 1)
		self.assertEqual(len(result['trips']), 1)
		self.assertEqual(result['trips'][0]['start_date'], '2026-04-01')
		self.assertEqual(result['trips'][0]['end_date'], '2026-04-04')
		self.assertEqual(result['trips'][0]['duration_days'], 4)
		self.assertEqual(result['trips'][0]['transport_modes'], ['AIR', 'RAIL'])
		self.assertTrue(result['trips'][0]['is_complete'])

	def test_returns_unmatched_transport_invoice_without_home_city_context(self):
		self.user.city = ''
		self.user.company = ''
		self.user.department = '交付部'
		invoices = [
			self.create_invoice(
				invoice_number='T1003',
				invoice_date=datetime.date(2026, 4, 8),
				departure_place='郑州东',
				arrival_place='北京西',
				product_name='铁路客票',
				created_at=datetime.datetime(2026, 4, 8, 9, 0),
			)
		]

		result = group_trip_periods(self.user, invoices)

		self.assertEqual(result['home_city'], '')
		self.assertEqual(result['total_trips'], 0)
		self.assertEqual(len(result['unmatched_invoices']), 1)

	def test_prefers_user_city_for_home_city_inference(self):
		self.user.city = '上海'
		self.user.company = '淘数郑州'
		invoices = [
			self.create_invoice(
				invoice_number='T1004',
				invoice_date=datetime.date(2026, 4, 9),
				departure_place='上海虹桥',
				arrival_place='杭州东',
				product_name='铁路客票',
				created_at=datetime.datetime(2026, 4, 9, 9, 0),
			)
		]

		result = group_trip_periods(self.user, invoices)

		self.assertEqual(result['home_city'], '上海')


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class TripGroupApiTests(APITestCase):
	def setUp(self):
		self.client = cast(APIClient, self.client)
		self.user = User.objects.create_user(
			username='trip-user',
			password='test-pass-123',
			city='郑州',
			company='淘数郑州',
			department='郑州公司交付部',
			real_name='李四',
		)
		self.client.force_authenticate(self.user)

	def create_invoice(
		self,
		invoice_number: str,
		invoice_date: datetime.date,
		departure_place: str,
		arrival_place: str,
		product_name: str,
	) -> Invoice:
		return Invoice.objects.create(
			user=self.user,
			file='invoices/test.pdf',
			invoice_number=invoice_number,
			invoice_type='TRANSPORT',
			amount='128.50',
			invoice_date=invoice_date,
			product_name=product_name,
			departure_place=departure_place,
			arrival_place=arrival_place,
		)

	def test_manual_group_is_marked_and_excluded_from_auto_regroup(self):
		outbound = self.create_invoice('T2001', datetime.date(2026, 4, 1), '郑州东', '上海虹桥', '铁路客票')
		inbound = self.create_invoice('F2002', datetime.date(2026, 4, 4), '上海虹桥', '郑州', '航空客票')
		regroup_auto_trip_groups(self.user)

		response = self.client.post('/api/trip-groups/', {
			'invoice_ids': [outbound.pk, inbound.pk],
			'home_city': '郑州',
		}, format='json')
		response_data = cast(Any, response).data

		self.assertEqual(response.status_code, 201)
		self.assertEqual(TripGroup.objects.filter(user=self.user, source='MANUAL').count(), 1)
		self.assertEqual(TripGroup.objects.filter(user=self.user, source='AUTO').count(), 0)
		self.assertEqual(response_data['trips'][0]['source'], 'MANUAL')
		self.assertTrue(response_data['trips'][0]['manual_adjusted'])

		self.create_invoice('T2003', datetime.date(2026, 4, 10), '郑州东', '北京西', '铁路客票')
		self.create_invoice('F2004', datetime.date(2026, 4, 12), '北京首都', '郑州', '航空客票')
		response = self.client.post('/api/trip-groups/auto-regroup/', {'home_city': '郑州'}, format='json')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(TripGroup.objects.filter(user=self.user, source='MANUAL').count(), 1)
		self.assertEqual(TripGroup.objects.filter(user=self.user, source='AUTO').count(), 1)
		self.assertEqual(TripGroupInvoice.objects.filter(invoice=outbound).get().trip_group.source, 'MANUAL')
		self.assertEqual(TripGroupInvoice.objects.filter(invoice=inbound).get().trip_group.source, 'MANUAL')

	def test_upload_invoice_triggers_auto_regroup(self):
		with patch('core.views.PDFInvoiceParser') as parser_cls:
			parser_cls.return_value.parse.side_effect = [
				{
					'invoice_number': 'UP3001',
					'invoice_type': 'TRANSPORT',
					'invoice_date': '2026-04-01',
					'departure_place': '郑州东',
					'arrival_place': '上海虹桥',
					'product_name': '铁路客票',
					'amount_in_figures': '100.00',
				},
				{
					'invoice_number': 'UP3002',
					'invoice_type': 'TRANSPORT',
					'invoice_date': '2026-04-03',
					'departure_place': '上海虹桥',
					'arrival_place': '郑州',
					'product_name': '航空客票',
					'amount_in_figures': '260.00',
				},
			]

			first_file = SimpleUploadedFile('first.pdf', b'%PDF-1.4 test', content_type='application/pdf')
			second_file = SimpleUploadedFile('second.pdf', b'%PDF-1.4 test', content_type='application/pdf')

			first_response = self.client.post('/api/invoices/', {'file': first_file})
			second_response = self.client.post('/api/invoices/', {'file': second_file})

		self.assertEqual(first_response.status_code, 201)
		self.assertEqual(second_response.status_code, 201)
		self.assertEqual(TripGroup.objects.filter(user=self.user, source='AUTO').count(), 1)

		summary = self.client.get('/api/user/trips/')
		summary_data = cast(Any, summary).data
		self.assertEqual(summary.status_code, 200)
		self.assertEqual(summary_data['total_trips'], 1)
		self.assertEqual(summary_data['trips'][0]['source'], 'AUTO')

	def test_attach_invoice_to_auto_trip_converts_it_to_manual(self):
		outbound = self.create_invoice('T3001', datetime.date(2026, 4, 1), '郑州东', '上海虹桥', '铁路客票')
		inbound = self.create_invoice('F3002', datetime.date(2026, 4, 3), '上海虹桥', '郑州', '航空客票')
		other_invoice = Invoice.objects.create(
			user=self.user,
			file='invoices/test.pdf',
			invoice_number='O3003',
			invoice_type='OTHER',
			amount='88.00',
			invoice_date=datetime.date(2026, 4, 2),
			product_name='打车服务费',
		)

		regroup_auto_trip_groups(self.user)
		trip_group = TripGroup.objects.get(user=self.user, source='AUTO')

		response = self.client.post(
			f'/api/trip-groups/{trip_group.pk}/attach-invoice/',
			{
				'invoice_id': other_invoice.pk,
				'reimbursement_category': 'OTHER',
			},
			format='json',
		)
		response_data = cast(Any, response).data

		self.assertEqual(response.status_code, 200)
		trip_group.refresh_from_db()
		self.assertEqual(trip_group.source, 'MANUAL')
		self.assertTrue(TripGroupInvoice.objects.filter(trip_group=trip_group, invoice=outbound).exists())
		self.assertTrue(TripGroupInvoice.objects.filter(trip_group=trip_group, invoice=inbound).exists())
		self.assertTrue(TripGroupInvoice.objects.filter(trip_group=trip_group, invoice=other_invoice).exists())
		self.assertEqual(response_data['trips'][0]['source'], 'MANUAL')


class UserAdminApiTests(APITestCase):
	def setUp(self):
		self.client = cast(APIClient, self.client)
		self.admin_user = User.objects.create_superuser(
			username='admin-user',
			password='admin-pass-123',
			email='admin@example.com',
		)
		self.client.force_authenticate(self.admin_user)

	def test_can_create_user_with_company(self):
		response = self.client.post('/api/users/', {
			'username': 'company-user',
			'password': 'test-pass-123',
			'real_name': '王五',
			'company': '淘数郑州',
			'city': '郑州',
			'department': '交付部',
			'email': 'company@example.com',
			'role': 'EMPLOYEE',
			'is_active': True,
		}, format='json')
		response_data = cast(Any, response).data

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response_data['company'], '淘数郑州')
		self.assertEqual(response_data['city'], '郑州')
		self.assertTrue(User.objects.filter(username='company-user', company='淘数郑州', city='郑州').exists())


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class InvoiceAttachmentApiTests(APITestCase):
	def setUp(self):
		self.client = cast(APIClient, self.client)
		self.user = User.objects.create_user(
			username='attachment-user',
			password='test-pass-123',
		)
		self.client.force_authenticate(self.user)
		self.invoice = Invoice.objects.create(
			user=self.user,
			file='invoices/test.pdf',
			invoice_number='ATT1001',
			invoice_type='OTHER',
			amount='10.00',
			product_name='办公用品',
		)

	def test_can_upload_and_delete_invoice_attachment(self):
		attachment_file = SimpleUploadedFile('note.txt', b'attachment content', content_type='text/plain')

		upload_response = self.client.post(
			f'/api/invoices/{self.invoice.pk}/attachments/',
			{'file': attachment_file},
		)
		upload_data = cast(Any, upload_response).data

		self.assertEqual(upload_response.status_code, 201)
		self.assertEqual(upload_data['name'], 'note.txt')
		self.assertTrue(InvoiceAttachment.objects.filter(invoice=self.invoice, original_name='note.txt').exists())

		attachment_id = upload_data['id']
		delete_response = self.client.delete(f'/api/invoices/{self.invoice.pk}/attachments/{attachment_id}/')

		self.assertEqual(delete_response.status_code, 204)
		self.assertFalse(InvoiceAttachment.objects.filter(pk=attachment_id).exists())


class ReimbursementApiTests(APITestCase):
	def setUp(self):
		self.client = cast(APIClient, self.client)
		self.user = User.objects.create_user(
			username='reimbursement-user',
			password='test-pass-123',
		)
		self.other_user = User.objects.create_user(
			username='other-user',
			password='test-pass-123',
		)
		self.client.force_authenticate(self.user)

	def test_applicant_can_delete_pending_reimbursement(self):
		reimbursement = Reimbursement.objects.create(applicant=self.user, status='PENDING', details={})

		response = self.client.delete(f'/api/reimbursements/{reimbursement.pk}/')

		self.assertEqual(response.status_code, 204)
		self.assertFalse(Reimbursement.objects.filter(pk=reimbursement.pk).exists())

	def test_applicant_cannot_delete_non_pending_reimbursement(self):
		reimbursement = Reimbursement.objects.create(applicant=self.user, status='APPROVED', details={})

		response = self.client.delete(f'/api/reimbursements/{reimbursement.pk}/')

		self.assertEqual(response.status_code, 400)
		self.assertTrue(Reimbursement.objects.filter(pk=reimbursement.pk).exists())

	def test_user_cannot_delete_other_users_reimbursement(self):
		reimbursement = Reimbursement.objects.create(applicant=self.other_user, status='PENDING', details={})

		response = self.client.delete(f'/api/reimbursements/{reimbursement.pk}/')

		self.assertEqual(response.status_code, 404)
		self.assertTrue(Reimbursement.objects.filter(pk=reimbursement.pk).exists())
