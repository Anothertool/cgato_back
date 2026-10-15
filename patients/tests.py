from rest_framework.test import APIClient, APITestCase

from .models import Patient


class PatientAPITests(APITestCase):
    def test_read_endpoints_are_public(self):
        patient = Patient.objects.create(first_name='Example')
        self.assertEqual(self.client.get('/api/patients/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/patients/{patient.pk}/').status_code, 200)

    def test_public_writes_do_not_require_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post('/api/patients/', {'first_name': 'Example'}, format='json')
        self.assertEqual(response.status_code, 201)
        url = f"/api/patients/{response.data['id']}/"
        self.assertEqual(client.patch(url, {'first_name': 'Changed'}, format='json').status_code, 200)
        self.assertEqual(client.delete(url).status_code, 204)

    def test_create_retrieve_patch_and_delete(self):
        response = self.client.post('/api/patients/', {'first_name': 'Example'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('id', response.data)
        self.assertIn('created_at', response.data)
        url = f"/api/patients/{response.data['id']}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.patch(url, {'phone': '5550100'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['phone'], '5550100')
        self.assertIn('updated_at', response.data)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(Patient.objects.exists())

    def test_readonly_fields_cannot_be_changed(self):
        patient = Patient.objects.create(first_name='Example')
        response = self.client.patch(f'/api/patients/{patient.pk}/', {
            'id': '00000000-0000-0000-0000-000000000001',
            'created_at': '2000-01-01T00:00:00Z',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], str(patient.pk))
        patient.refresh_from_db()
        self.assertNotEqual(patient.created_at.year, 2000)

    def test_clinical_reference_is_unique_only_when_present(self):
        for value in ('', None, '   '):
            response = self.client.post('/api/patients/', {
                'first_name': 'Example', 'clinical_reference': value,
            }, format='json')
            self.assertEqual(response.status_code, 201)
            self.assertIsNone(response.data['clinical_reference'])
        payload = {'first_name': 'Example', 'clinical_reference': 'REF-1'}
        self.assertEqual(self.client.post('/api/patients/', payload, format='json').status_code, 201)
        response = self.client.post('/api/patients/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('REF-1', str(response.data))
        self.assertNotIn('Example', str(response.data))

    def test_same_names_do_not_merge_patients(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/patients/', {'first_name': 'Example'}).status_code, 201)
        self.assertEqual(Patient.objects.count(), 2)

    def test_search_and_pagination(self):
        Patient.objects.create(first_name='First', last_name='Last', clinical_reference='LEXI-1')
        Patient.objects.create(first_name='Other')
        for term in ('First', 'Last', 'LEXI-1'):
            response = self.client.get('/api/patients/', {'search': term})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 1)
        Patient.objects.bulk_create([Patient(first_name=f'Patient {i}') for i in range(25)])
        response = self.client.get('/api/patients/')
        self.assertEqual(len(response.data['results']), 25)
        self.assertIsNotNone(response.data['next'])

