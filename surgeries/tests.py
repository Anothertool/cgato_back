from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APITestCase

from patients.models import Patient
from .models import Surgery, SurgeryLensCheck


class SurgeryAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='surgery-editor')
        cls.patient = Patient.objects.create(first_name='Example', last_name='Patient')

    def setUp(self):
        self.payload = {
            'patient_id': str(self.patient.pk), 'hospital': 'Hospital A',
            'surgery_type': 'Cataracts', 'eye': 'RIGHT',
            'scheduled_at': '2026-11-10T09:30:00+01:00',
        }

    def create_surgery(self, **kwargs):
        values = {
            'patient': self.patient, 'hospital': 'Hospital A',
            'surgery_type': 'Cataracts', 'eye': Surgery.Eye.RIGHT,
            'scheduled_at': timezone.now(),
        }
        values.update(kwargs)
        return Surgery.objects.create(**values)

    def test_existing_patient_creation_returns_complete_output(self):
        response = self.client.post('/api/surgeries/', self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['patient']['id'], str(self.patient.pk))
        self.assertEqual(response.data['patient']['last_name'], 'Patient')
        self.assertEqual(response.data['status'], 'PENDING')
        self.assertIn('created_at', response.data)
        self.assertIn('documentation_ready', response.data)
        self.assertEqual(response.data['lens_checks'], [])
        self.assertEqual(Patient.objects.count(), 1)
        surgery = Surgery.objects.get()
        self.assertTrue(timezone.is_aware(surgery.scheduled_at))
        self.assertEqual(surgery.scheduled_at.hour, 8)

    def test_nested_patient_creation_and_negative_iol_power(self):
        self.payload.pop('patient_id')
        self.payload.update(patient={'first_name': 'New'}, iol_power='-2.50')
        response = self.client.post('/api/surgeries/', self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Patient.objects.count(), 2)
        self.assertEqual(response.data['patient']['first_name'], 'New')
        self.assertEqual(Surgery.objects.get().iol_power, Decimal('-2.50'))

    def test_nested_creation_is_atomic(self):
        self.payload.pop('patient_id')
        self.payload['patient'] = {'first_name': 'New'}
        self.payload['lens_received'] = True
        with patch.object(Surgery, 'record_lens_changes', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/surgeries/', self.payload, format='json')
        self.assertEqual(Patient.objects.count(), 1)
        self.assertFalse(Surgery.objects.exists())

    def test_exactly_one_patient_option_is_required(self):
        for payload in (
            {key: value for key, value in self.payload.items() if key != 'patient_id'},
            {**self.payload, 'patient': {'first_name': 'New'}},
        ):
            with self.subTest(payload_keys=list(payload)):
                self.assertEqual(self.client.post('/api/surgeries/', payload, format='json').status_code, 400)
        self.assertFalse(Surgery.objects.exists())
        self.assertEqual(Patient.objects.count(), 1)

    def test_invalid_existing_patient_does_not_expose_identifier(self):
        self.payload['patient_id'] = '00000000-0000-0000-0000-000000000001'
        response = self.client.post('/api/surgeries/', self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(self.payload['patient_id'], str(response.data))

    def test_invalid_nested_patient_does_not_create_records(self):
        self.payload.pop('patient_id')
        self.payload['patient'] = {'last_name': 'Example'}
        self.assertEqual(self.client.post('/api/surgeries/', self.payload, format='json').status_code, 400)
        self.assertEqual(Patient.objects.count(), 1)

    def test_invalid_amount_choices_and_lens_state(self):
        for field, value in [('amount', '-0.01'), ('eye', 'INVALID'), ('status', 'INVALID'), ('lens_verified', True)]:
            with self.subTest(field=field):
                response = self.client.post('/api/surgeries/', {**self.payload, field: value}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertFalse(Surgery.objects.exists())

    def test_partial_updates_validate_effective_lens_state(self):
        surgery = self.create_surgery(lens_received=True, lens_verified=True)
        url = f'/api/surgeries/{surgery.pk}/'
        self.assertEqual(self.client.patch(url, {'lens_received': False}, format='json').status_code, 400)
        response = self.client.patch(url, {'lens_received': False, 'lens_verified': False}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SurgeryLensCheck.objects.count(), 2)

    def test_lens_changes_record_user_and_time_without_duplicate_events(self):
        self.payload.update(lens_ordered=True)
        response = self.client.post('/api/surgeries/', self.payload, format='json')
        url = f"/api/surgeries/{response.data['id']}/"
        response = self.client.patch(url, {'lens_received': True, 'lens_verified': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['lens_checks']), 3)
        for check in SurgeryLensCheck.objects.all():
            self.assertIsNone(check.checked_by_id)
            self.assertTrue(timezone.is_aware(check.checked_at))
        self.client.patch(url, {'lens_verified': True}, format='json')
        self.assertEqual(SurgeryLensCheck.objects.count(), 3)

    def test_audit_failure_rolls_back_update(self):
        surgery = self.create_surgery()
        with patch.object(Surgery, 'record_lens_changes', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.patch(f'/api/surgeries/{surgery.pk}/', {'lens_received': True}, format='json')
        surgery.refresh_from_db()
        self.assertFalse(surgery.lens_received)

    def test_change_patient_by_id_but_disallow_nested_patch(self):
        surgery = self.create_surgery()
        patient = Patient.objects.create(first_name='Other')
        url = f'/api/surgeries/{surgery.pk}/'
        response = self.client.patch(url, {'patient_id': str(patient.pk)}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['patient']['id'], str(patient.pk))
        response = self.client.patch(url, {'patient': {'first_name': 'New'}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Patient.objects.count(), 2)

    def test_readonly_fields_cannot_be_set_by_client(self):
        surgery = self.create_surgery()
        response = self.client.patch(f'/api/surgeries/{surgery.pk}/', {
            'deleted_at': '2026-01-01T00:00:00Z', 'deleted_by': self.user.pk,
            'lens_checks': [{'field': 'lens_verified', 'value': True}],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        surgery.refresh_from_db()
        self.assertIsNone(surgery.deleted_at)
        self.assertIsNone(surgery.deleted_by)
        self.assertFalse(SurgeryLensCheck.objects.exists())

    def test_filters_ordering_and_pagination(self):
        early = self.create_surgery(scheduled_at='2026-11-09T10:00:00Z', insurer='Insurer A')
        self.create_surgery(scheduled_at='2026-11-11T10:00:00Z', hospital='Hospital B', eye='LEFT', status='READY')
        filters = [
            {'status': 'PENDING'}, {'hospital': 'Hospital A'}, {'eye': 'RIGHT'},
            {'insurer': 'Insurer A'}, {'scheduled_at__gte': '2026-11-10T00:00:00Z'},
            {'scheduled_at__lte': '2026-11-10T00:00:00Z'},
        ]
        for query in filters:
            with self.subTest(query=query):
                response = self.client.get('/api/surgeries/', query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['count'], 1)
        response = self.client.get('/api/surgeries/', {'patient_id': str(self.patient.pk)})
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(response.data['results'][0]['id'], str(early.pk))
        for _ in range(25):
            self.create_surgery()
        response = self.client.get('/api/surgeries/')
        self.assertEqual(len(response.data['results']), 25)
        self.assertIsNotNone(response.data['next'])

    def test_invalid_filter_returns_400(self):
        for query in [{'patient_id': 'invalid'}, {'scheduled_at__gte': 'invalid'}, {'status': 'INVALID'}]:
            self.assertEqual(self.client.get('/api/surgeries/', query).status_code, 400)

    def test_delete_is_logical_and_keeps_patient_protected(self):
        surgery = self.create_surgery()
        url = f'/api/surgeries/{surgery.pk}/'
        self.assertEqual(self.client.delete(url).status_code, 204)
        surgery.refresh_from_db()
        self.assertIsNotNone(surgery.deleted_at)
        self.assertIsNone(surgery.deleted_by_id)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'status': 'READY'}).status_code, 404)
        self.assertEqual(self.client.get('/api/surgeries/').data['count'], 0)
        response = self.client.delete(f'/api/patients/{self.patient.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('Example', str(response.data))
        with self.assertRaises(ProtectedError):
            self.patient.delete()

    def test_cancellation_keeps_surgery_visible(self):
        surgery = self.create_surgery()
        response = self.client.patch(f'/api/surgeries/{surgery.pk}/', {'status': 'CANCELLED'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'CANCELLED')
        self.assertEqual(self.client.get('/api/surgeries/').data['count'], 1)

    def test_read_endpoints_are_public(self):
        surgery = self.create_surgery()
        self.assertEqual(self.client.get('/api/surgeries/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/surgeries/{surgery.pk}/').status_code, 200)

    def test_admin_lens_changes_still_record_user(self):
        surgery = self.create_surgery()
        surgery.lens_received = True
        request = type('Request', (), {'user': self.user})()
        site._registry[Surgery].save_model(request, surgery, form=None, change=True)
        self.assertEqual(SurgeryLensCheck.objects.get().checked_by_id, self.user.pk)

    def test_database_constraints_protect_direct_writes(self):
        for values in [{'amount': Decimal('-0.01')}, {'lens_verified': True}]:
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    self.create_surgery(**values)

    def test_admin_disables_physical_surgery_and_audit_deletion(self):
        request = type('Request', (), {'user': self.user})()
        self.assertFalse(site._registry[Surgery].has_delete_permission(request))
        self.assertFalse(site._registry[SurgeryLensCheck].has_delete_permission(request))
