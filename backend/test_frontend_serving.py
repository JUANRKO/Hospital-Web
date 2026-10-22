import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from app import app


class FrontendServingTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_root_serves_frontend_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Hospital de Clínicas'.encode('utf-8'), response.data)

    def test_index_css_is_served(self):
        response = self.client.get('/css/index.css')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
