import json
import os
import tempfile
import unittest

import app as application


class ShelterSearchTests(unittest.TestCase):
    def setUp(self):
        self.original_shelters = application.shelters
        self.original_data_file = application.DATA_FILE
        application.shelters = [
            {
                'id': 1,
                'name': 'Central School',
                'district': '中央地区',
                'address': '青森市中央1-1',
                'hazards': ['洪水', '土砂災害'],
                'pet_allowed': True,
                'wheelchair_accessible': True,
                'parking': False,
                'capacity': 100,
                'current_evacuees': 40,
                'accepted_disasters': '洪水、土砂災害',
                'amenities': ['pet_allowed', 'barrier_free'],
                'facilities': '備蓄あり',
            },
            {
                'id': 2,
                'name': '東小学校',
                'district': '東地区',
                'address': '青森市東2-2',
                'hazards': ['津波'],
                'pet_allowed': True,
                'wheelchair_accessible': False,
                'parking': True,
                'capacity': 20,
                'current_evacuees': 20,
                'amenities': ['pet_allowed', 'parking'],
            },
            {'id': 3, 'name': '旧データ避難所'},
        ]
        self.client = application.app.test_client()

    def tearDown(self):
        application.shelters = self.original_shelters
        application.DATA_FILE = self.original_data_file

    def search(self, **params):
        return self.client.get('/shelter_search', query_string=params)

    def test_unfiltered_search_and_all_shelter_count(self):
        response = self.search()
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('登録されている避難所', html)
        self.assertIn('3件 / 全3件', html)
        self.assertIn('Central School', html)
        self.assertIn('東小学校', html)
        self.assertIn('旧データ避難所', html)

    def test_query_searches_name_district_address_and_trims_case_insensitively(self):
        cases = (
            ('central', 'Central School'),
            ('中央地区', 'Central School'),
            ('青森市東2-2', '東小学校'),
            ('  cEnTrAl  ', 'Central School'),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                response = self.search(q=query)
                html = response.get_data(as_text=True)
                self.assertIn(expected, html)
                self.assertIn(f'「{query.strip()}」の検索結果', html)
                self.assertIn('1件 / 全3件', html)

    def test_hazard_and_each_accessibility_filter(self):
        cases = (
            ({'disaster': '洪水'}, 'Central School'),
            ({'pet': '1'}, 'Central School'),
            ({'wheelchair': '1'}, 'Central School'),
            ({'parking': '1'}, '東小学校'),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                html = self.search(**params).get_data(as_text=True)
                self.assertIn(expected, html)
                if '洪水' in params.values():
                    self.assertNotIn('東小学校', html)
                if 'parking' in params:
                    self.assertNotIn('Central School', html)

    def test_all_conditions_are_combined_with_and(self):
        response = self.search(
            q='central', disaster='洪水', pet='1', wheelchair='1', parking='1'
        )
        html = response.get_data(as_text=True)
        self.assertIn('0件 / 全3件', html)
        self.assertIn('条件に一致する避難所が見つかりませんでした。', html)

        matched = self.search(q=' CENTRAL ', disaster='洪水', pet='1', wheelchair='1')
        self.assertIn('Central School', matched.get_data(as_text=True))

    def test_search_form_preserves_values_and_clear_link_removes_conditions(self):
        response = self.search(q=' 中央 ', disaster='洪水', pet='1', wheelchair='1')
        html = response.get_data(as_text=True)
        self.assertIn('value="中央"', html)
        self.assertIn('<option value="洪水" selected>', html)
        self.assertIn('name="pet" value="1" checked', html)
        self.assertIn('name="wheelchair" value="1" checked', html)
        self.assertIn('href="/shelter_search"', html)

    def test_empty_results_show_message_and_retry_action(self):
        html = self.search(q='存在しない避難所').get_data(as_text=True)
        self.assertIn('条件に一致する避難所が見つかりませんでした。', html)
        self.assertIn('条件を変えて再検索', html)

    def test_missing_optional_fields_are_safe(self):
        response = self.client.get('/all_shelters')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('旧データ避難所', html)
        self.assertIn('未登録', html)

    def test_shelter_data_is_html_escaped(self):
        application.shelters = [{'id': 4, 'name': '<script>alert(1)</script>'}]
        html = self.search(q='script').get_data(as_text=True)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_existing_api_supports_district_and_search_filters(self):
        response = self.client.get('/shelters', query_string={'district': '東地区'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['name'] for item in response.get_json()], ['東小学校'])

        filtered = self.client.get('/shelters', query_string={'q': '中央', 'disaster': '洪水'})
        self.assertEqual([item['name'] for item in filtered.get_json()], ['Central School'])

        missing = self.client.get('/shelters', query_string={'district': '該当なし'})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json(), {'error': 'No shelters found'})

    def test_authenticated_status_update_form_keeps_search_conditions(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        response = self.search(q='Central', disaster='洪水', pet='1')
        html = response.get_data(as_text=True)
        self.assertIn('/shelter_status/1?q=Central&amp;disaster=%E6%B4%AA%E6%B0%B4&amp;pet=1', html)

    def test_registration_persists_searchable_attributes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            application.DATA_FILE = os.path.join(temp_dir, 'shelters.json')
            with self.client.session_transaction() as session:
                session['logged_in'] = True

            response = self.client.post('/shelter_register', data={
                'name': '登録テスト避難所',
                'district': '南地区',
                'address': '青森市南3-3',
                'hazards': ['洪水'],
                'amenities': ['pet_allowed', 'barrier_free', 'parking'],
            })
            self.assertEqual(response.status_code, 200)
            with open(application.DATA_FILE, encoding='utf-8') as data_file:
                saved = next(
                    item for item in json.load(data_file)
                    if item['name'] == '登録テスト避難所'
                )

            self.assertEqual(saved['hazards'], ['洪水'])
            self.assertTrue(saved['pet_allowed'])
            self.assertTrue(saved['wheelchair_accessible'])
            self.assertTrue(saved['parking'])
            self.assertIn('登録テスト避難所', self.search(
                q='南地区', disaster='洪水', pet='1', wheelchair='1', parking='1'
            ).get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
