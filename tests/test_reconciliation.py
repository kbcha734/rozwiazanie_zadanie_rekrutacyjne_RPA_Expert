"""
Testy jednostkowe silnika FuelReconciler (modułowość, tolerancje, reguły biznesowe).
Uruchomienie:
    python -m unittest discover tests
"""
import unittest
from engine.normalizer import Normalizer
from engine.reconciler import FuelReconciler


class TestReconciliationEngine(unittest.TestCase):
    def setUp(self):
        self.sample_config = {
            'tolerance': {
                'abs_liters': 50.0,
                'rel_percent': 0.005,
                'use_max_base': True
            },
            'business_rules': {
                'enable_date_shift_matching': True,
                'date_shift_max_days': 1,
                'allow_multi_document_aggregation': True,
                'ignore_sto_as_active_delivery': True,
                'flag_station_reception_with_sto': True,
                'enable_cross_station_correlation': True
            },
            'product_mapping': {
                "PB95": "PB95",
                "PB 95": "PB95",
                "BENZYNA BEZOŁOWIOWA 95": "PB95",
                "PB98": "PB98",
                "PB 98": "PB98",
                "BENZYNA BEZOŁOWIOWA 98": "PB98",
                "ON": "ON",
                "DIESEL": "ON",
                "OLEJ NAPĘDOWY": "ON",
                "LPG": "LPG",
                "GAZ LPG": "LPG"
            },
            'normalization': {
                'station_code_length': 4,
                'station_sap_prefix': "ST",
                'supported_date_formats': [
                    "%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"
                ]
            }
        }
        self.normalizer = Normalizer(self.sample_config)
        self.reconciler = FuelReconciler(self.sample_config, self.normalizer)

    # --------------------------------------------------------------------------
    # 1. TESTY NORMALIZACJI
    # --------------------------------------------------------------------------
    def test_normalize_station_id(self):
        self.assertEqual(self.normalizer.normalize_station_id("ST0412"), "0412")
        self.assertEqual(self.normalizer.normalize_station_id("417"), "0417")
        self.assertEqual(self.normalizer.normalize_station_id(" 523 "), "0523")
        self.assertEqual(self.normalizer.normalize_station_id("0745"), "0745")

    def test_normalize_dates(self):
        self.assertEqual(self.normalizer.normalize_date("2026-08-24"), "2026-08-24")
        self.assertEqual(self.normalizer.normalize_date("24.08.2026"), "2026-08-24")
        self.assertEqual(self.normalizer.normalize_date("2026/08/24"), "2026-08-24")

    def test_normalize_products(self):
        self.assertEqual(self.normalizer.normalize_product("Pb 95"), "PB95")
        self.assertEqual(self.normalizer.normalize_product("Benzyna bezołowiowa 98"), "PB98")
        self.assertEqual(self.normalizer.normalize_product("Diesel"), "ON")
        self.assertEqual(self.normalizer.normalize_product("Olej napędowy"), "ON")
        self.assertEqual(self.normalizer.normalize_product("Gaz LPG"), "LPG")
        self.assertEqual(self.normalizer.normalize_product("LPG "), "LPG")

    def test_parse_quantities(self):
        self.assertEqual(self.normalizer.parse_quantity("20000,0"), 20000.0)
        self.assertEqual(self.normalizer.parse_quantity("0,0 l"), 0.0)
        self.assertEqual(self.normalizer.parse_quantity(" 7 200,50 "), 7200.50)
        self.assertEqual(self.normalizer.parse_quantity("n/d"), 0.0)

    # --------------------------------------------------------------------------
    # 2. TESTY TOLERANCJI (50 l vs 0.5%)
    # --------------------------------------------------------------------------
    def test_tolerance_calculation_small_volume(self):
        # Dla małej dostawy np. 5 000 l: 0.5% = 25 l, więc obowiązuje próg 50 l
        tol = self.reconciler.calculate_tolerance(5000.0, 5035.0)
        self.assertEqual(tol, 50.0)

    def test_tolerance_calculation_large_volume(self):
        # Dla dużej dostawy np. 30 000 l: 0.5% = 150 l, więc obowiązuje próg 150 l
        tol = self.reconciler.calculate_tolerance(30000.0, 30100.0)
        self.assertEqual(tol, 150.5)  # 0.5% z max(30000, 30100) = 150.5

    # --------------------------------------------------------------------------
    # 3. TEST AGREGACJI WIELU DOKUMENTÓW (1 do N)
    # --------------------------------------------------------------------------
    def test_multi_document_aggregation(self):
        st_rows = [{
            '__source_row__': 1,
            'Kod stacji': '0412',
            'Data': '2026-08-25',
            'Produkt': 'PB95',
            'Przyjęto dostawę [l]': '12000,0'
        }]
        sap_rows = [
            {
                '__source_row__': 1,
                'Nr dokumentu': 'DOC-1',
                'Zakład': 'ST0412',
                'Data księgowania': '2026/08/25',
                'Materiał': 'Benzyna bezołowiowa 95',
                'Ilość rzeczywista [l]': '7200',
                'Ilość w 15°C [l]': '7210',
                'Status': 'UTW'
            },
            {
                '__source_row__': 2,
                'Nr dokumentu': 'DOC-2',
                'Zakład': 'ST0412',
                'Data księgowania': '2026/08/25',
                'Materiał': 'Benzyna bezołowiowa 95',
                'Ilość rzeczywista [l]': '4800',
                'Ilość w 15°C [l]': '4805',
                'Status': 'UTW'
            }
        ]
        result = self.reconciler.reconcile(st_rows, sap_rows)
        self.assertEqual(len(result['matched']), 1)
        self.assertEqual(result['matched'][0]['sap_docs_count'], 2)
        self.assertEqual(result['matched'][0]['status'], "ZGODNE")
        self.assertEqual(len(result['exceptions']), 0)

    # --------------------------------------------------------------------------
    # 4. TEST PRZESUNIĘCIA DATY (D+1 PO PÓŁNOCY)
    # --------------------------------------------------------------------------
    def test_date_shift_matching(self):
        st_rows = [{
            '__source_row__': 1,
            'Kod stacji': '0417',
            'Data': '2026-08-25',
            'Produkt': 'LPG',
            'Przyjęto dostawę [l]': '24000,0'
        }]
        sap_rows = [{
            '__source_row__': 1,
            'Nr dokumentu': 'DOC-SHIFT',
            'Zakład': 'ST0417',
            'Data księgowania': '2026/08/26',
            'Materiał': 'Gaz LPG',
            'Ilość rzeczywista [l]': '24000',
            'Ilość w 15°C [l]': '23950',
            'Status': 'UTW'
        }]
        result = self.reconciler.reconcile(st_rows, sap_rows)
        self.assertEqual(len(result['matched']), 0)
        self.assertEqual(len(result['exceptions']), 1)
        self.assertIn("Przesunięcie daty", result['exceptions'][0]['category'])
        self.assertEqual(result['exceptions'][0]['sap_doc_ids'], "DOC-SHIFT")

    # --------------------------------------------------------------------------
    # 5. TEST PRZYJĘCIA ZE STATUSEM STO
    # --------------------------------------------------------------------------
    def test_sto_status_exception(self):
        st_rows = [{
            '__source_row__': 1,
            'Kod stacji': '0412',
            'Data': '2026-08-26',
            'Produkt': 'PB98',
            'Przyjęto dostawę [l]': '12000,0'
        }]
        sap_rows = [{
            '__source_row__': 1,
            'Nr dokumentu': 'DOC-STO',
            'Zakład': 'ST0412',
            'Data księgowania': '2026/08/26',
            'Materiał': 'Benzyna bezołowiowa 98',
            'Ilość rzeczywista [l]': '12000',
            'Ilość w 15°C [l]': '11950',
            'Status': 'STO'
        }]
        result = self.reconciler.reconcile(st_rows, sap_rows)
        self.assertEqual(len(result['matched']), 0)
        self.assertEqual(len(result['exceptions']), 1)
        self.assertIn("STO", result['exceptions'][0]['category'])
        self.assertEqual(result['exceptions'][0]['difference'], 12000.0)

    # --------------------------------------------------------------------------
    # 6. TEST KORELACJI INCYDENTU MIĘDZYSTACYJNEGO (BŁĘDNY ZAKŁAD)
    # --------------------------------------------------------------------------
    def test_cross_station_incident_correlation(self):
        st_rows = [{
            '__source_row__': 1,
            'Kod stacji': '0417',
            'Data': '2026-08-24',
            'Produkt': 'LPG',
            'Przyjęto dostawę [l]': '15000,0'
        }]
        sap_rows = [{
            '__source_row__': 1,
            'Nr dokumentu': 'DOC-MISMATCH',
            'Zakład': 'ST0523',
            'Data księgowania': '2026/08/24',
            'Materiał': 'Gaz LPG',
            'Ilość rzeczywista [l]': '15000',
            'Ilość w 15°C [l]': '14900',
            'Status': 'UTW'
        }]
        result = self.reconciler.reconcile(st_rows, sap_rows)
        self.assertEqual(len(result['incidents']), 1)
        self.assertEqual(result['incidents'][0]['station_reported'], '0417')
        self.assertEqual(result['incidents'][0]['sap_plant'], '0523')
        self.assertEqual(result['incidents'][0]['sap_doc_id'], 'DOC-MISMATCH')


if __name__ == '__main__':
    unittest.main()
