"""
Silnik uzgadniania dostaw paliw (Reconciliation Engine).
Realizuje wieloetapowe uzgodnienie biznesowe pomiędzy danymi stacyjnymi a SAP:
1. Bezpośrednie dopasowanie 1-do-1 oraz 1-do-wielu (agregacja dokumentów SAP) w tej samej dobie.
2. Wykrywanie przesunięć dat (dostawy nocne po północy D+1).
3. Dopasowanie pozostałych dostaw w dobie D+1 po wydzieleniu przesunięcia nocnego.
4. Wykrywanie przyjęć ze statusem STO (anulowane w SAP).
5. Korelacja incydentów krzyżowych (błędny zakład w SAP, stacja A != zakład B).
6. Wykrywanie dostaw widmo (brak na stacji) oraz braków w SAP.
"""
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class FuelReconciler:
    def __init__(self, config: Dict[str, Any], normalizer):
        self.config = config
        self.normalizer = normalizer
        
        # Parametry tolerancji
        tol_cfg = config.get('tolerance', {})
        self.tol_abs = float(tol_cfg.get('abs_liters', 50.0))
        self.tol_rel = float(tol_cfg.get('rel_percent', 0.005))
        self.use_max_base = tol_cfg.get('use_max_base', True)
        
        # Reguły biznesowe
        biz_cfg = config.get('business_rules', {})
        self.enable_date_shift = biz_cfg.get('enable_date_shift_matching', True)
        self.date_shift_days = biz_cfg.get('date_shift_max_days', 1)
        self.enable_multi_doc = biz_cfg.get('allow_multi_document_aggregation', True)
        self.ignore_sto_active = biz_cfg.get('ignore_sto_as_active_delivery', True)
        self.flag_sto_station = biz_cfg.get('flag_station_reception_with_sto', True)
        self.enable_cross_station = biz_cfg.get('enable_cross_station_correlation', True)

    def calculate_tolerance(self, qty_stacja: float, qty_sap: float) -> float:
        """
        Oblicza dynamiczny próg tolerancji: max(50 litrów, 0.5% dostawy).
        Baza procentowa liczona z większej wartości lub aktywnej dostawy.
        """
        base = max(qty_stacja, qty_sap) if self.use_max_base else qty_stacja
        rel_tol = base * self.tol_rel
        return max(self.tol_abs, rel_tol)

    def reconcile(
        self,
        station_rows: List[Dict[str, Any]],
        sap_rows: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Główna funkcja wykonująca pełne uzgodnienie.
        Zwraca słownik z listami: matched, exceptions, incidents, summary_stats.
        """
        # 1. Przygotowanie i grupowanie rekordów dostaw ze stacji (dostawa > 0)
        station_deliveries = []
        for r in station_rows:
            dost_qty = self.normalizer.parse_quantity(r.get('Przyjęto dostawę [l]', 0))
            if dost_qty > 0:
                station_deliveries.append({
                    'source_row': r.get('__source_row__'),
                    'station': self.normalizer.normalize_station_id(r.get('Kod stacji')),
                    'date': self.normalizer.normalize_date(r.get('Data')),
                    'product': self.normalizer.normalize_product(r.get('Produkt')),
                    'qty_station': dost_qty,
                    'raw': r,
                    'assigned': False
                })

        # 2. Przygotowanie i grupowanie rekordów dostaw z SAP
        sap_deliveries = []
        for r in sap_rows:
            qty_real = self.normalizer.parse_quantity(r.get('Ilość rzeczywista [l]', 0))
            qty_15 = self.normalizer.parse_quantity(r.get('Ilość w 15°C [l]', 0))
            status = r.get('Status', '').strip().upper()
            sap_deliveries.append({
                'source_row': r.get('__source_row__'),
                'doc_id': r.get('Nr dokumentu', '').strip(),
                'station': self.normalizer.normalize_station_id(r.get('Zakład')),
                'date': self.normalizer.normalize_date(r.get('Data księgowania')),
                'product': self.normalizer.normalize_product(r.get('Materiał')),
                'qty_real': qty_real,
                'qty_15': qty_15,
                'status': status,
                'is_sto': (status == 'STO'),
                'raw': r,
                'assigned': False
            })

        matched_results = []
        exception_results = []
        incidents = []

        # Pomocnicze mapy
        sap_by_key = defaultdict(list)
        for sp in sap_deliveries:
            sap_by_key[(sp['station'], sp['date'], sp['product'])].append(sp)

        station_by_key = defaultdict(list)
        for st in station_deliveries:
            station_by_key[(st['station'], st['date'], st['product'])].append(st)

        all_keys = sorted(set(list(station_by_key.keys()) + list(sap_by_key.keys())))

        # ----------------------------------------------------------------------
        # ETAP 1: Bezpośrednie dopasowanie w tej samej dobie (gdzie sumy są równe w tolerancji)
        # ----------------------------------------------------------------------
        for key in all_keys:
            st_list = station_by_key.get(key, [])
            sp_list = sap_by_key.get(key, [])

            st_qty = sum(x['qty_station'] for x in st_list if not x['assigned'])
            sp_active = [x for x in sp_list if not x['is_sto'] and not x['assigned']]
            sp_active_qty = sum(x['qty_real'] for x in sp_active)

            if st_qty > 0 and sp_active_qty > 0:
                diff = st_qty - sp_active_qty
                tol = self.calculate_tolerance(st_qty, sp_active_qty)

                if abs(diff) <= tol:
                    for item in st_list:
                        item['assigned'] = True
                    for item in sp_active:
                        item['assigned'] = True

                    doc_ids_str = ", ".join(x['doc_id'] for x in sp_active)
                    matched_results.append({
                        'business_key': f"{key[0]}|{key[1]}|{key[2]}",
                        'station': key[0],
                        'date': key[1],
                        'product': key[2],
                        'station_qty': st_qty,
                        'sap_qty': sp_active_qty,
                        'difference': diff,
                        'tolerance': tol,
                        'status': "ZGODNE",
                        'category': "Pełna zgodność (w tolerancji)" if abs(diff) < 0.01 else "Zgodność w granicach tolerancji",
                        'sap_docs_count': len(sp_active),
                        'sap_doc_ids': doc_ids_str,
                        'notes': f"Agregacja {len(sp_active)} dokumentów SAP ({doc_ids_str})" if len(sp_active) > 1 else f"Dokument SAP {doc_ids_str}"
                    })

        # ----------------------------------------------------------------------
        # ETAP 2: Wykrywanie przesunięć dat po północy (Stacja doba D -> SAP doba D+1)
        # ----------------------------------------------------------------------
        if self.enable_date_shift:
            unassigned_st = [st for st in station_deliveries if not st['assigned']]

            for st_item in unassigned_st:
                curr_date = datetime.strptime(st_item['date'], "%Y-%m-%d")
                target_date = (curr_date + timedelta(days=1)).strftime("%Y-%m-%d")
                candidate_key = (st_item['station'], target_date, st_item['product'])

                # Dostępne nieprzypisane aktywne dokumenty SAP na dzień D+1
                cand_sap = [sp for sp in sap_by_key.get(candidate_key, []) if not sp['assigned'] and not sp['is_sto']]

                for sp_item in cand_sap:
                    tol = self.calculate_tolerance(st_item['qty_station'], sp_item['qty_real'])
                    diff = st_item['qty_station'] - sp_item['qty_real']

                    if abs(diff) <= tol:
                        st_item['assigned'] = True
                        sp_item['assigned'] = True

                        exception_results.append({
                            'exception_id': f"EXC-SHIFT-{st_item['station']}-{st_item['date']}",
                            'business_key': f"{st_item['station']}|{st_item['date']}|{st_item['product']}",
                            'station': st_item['station'],
                            'date': st_item['date'],
                            'product': st_item['product'],
                            'station_qty': st_item['qty_station'],
                            'sap_qty': sp_item['qty_real'],
                            'difference': diff,
                            'tolerance': tol,
                            'status': "WYJATEK_BIZNESOWY",
                            'category': "Przesunięcie daty (Księgowanie w SAP dzień później D+1)",
                            'sap_doc_ids': sp_item['doc_id'],
                            'reason': f"Dostawa przyjęta na stacji w dobie {st_item['date']} ({st_item['qty_station']:.1f} l), natomiast w SAP zaksięgowana po północy dnia {sp_item['date']} (dokument {sp_item['doc_id']}). Zgodność ilościowa w tolerancji.",
                            'action_required': "Standardowa akceptacja kontrolingowa przesunięcia nocnego."
                        })
                        break

        # ----------------------------------------------------------------------
        # ETAP 3: Ponowne dopasowanie tej samej doby dla rekordów uwolnionych po wydzieleniu D+1
        # ----------------------------------------------------------------------
        for key in all_keys:
            st_list = [x for x in station_by_key.get(key, []) if not x['assigned']]
            sp_active = [x for x in sap_by_key.get(key, []) if not x['is_sto'] and not x['assigned']]

            st_qty = sum(x['qty_station'] for x in st_list)
            sp_active_qty = sum(x['qty_real'] for x in sp_active)

            if st_qty > 0 and sp_active_qty > 0:
                diff = st_qty - sp_active_qty
                tol = self.calculate_tolerance(st_qty, sp_active_qty)

                if abs(diff) <= tol:
                    for item in st_list:
                        item['assigned'] = True
                    for item in sp_active:
                        item['assigned'] = True

                    doc_ids_str = ", ".join(x['doc_id'] for x in sp_active)
                    matched_results.append({
                        'business_key': f"{key[0]}|{key[1]}|{key[2]}",
                        'station': key[0],
                        'date': key[1],
                        'product': key[2],
                        'station_qty': st_qty,
                        'sap_qty': sp_active_qty,
                        'difference': diff,
                        'tolerance': tol,
                        'status': "ZGODNE",
                        'category': "Pełna zgodność (w tolerancji)" if abs(diff) < 0.01 else "Zgodność w granicach tolerancji",
                        'sap_docs_count': len(sp_active),
                        'sap_doc_ids': doc_ids_str,
                        'notes': f"Dopasowanie po wydzieleniu przesunięcia nocnego (dokument {doc_ids_str})"
                    })

        # ----------------------------------------------------------------------
        # ETAP 4: Wykrywanie dokumentów SAP ze statusem STO
        # ----------------------------------------------------------------------
        for key in all_keys:
            st_list = [x for x in station_by_key.get(key, []) if not x['assigned']]
            sp_sto = [x for x in sap_by_key.get(key, []) if x['is_sto'] and not x['assigned']]

            st_qty = sum(x['qty_station'] for x in st_list)
            sto_qty = sum(x['qty_real'] for x in sp_sto)

            if st_qty > 0 and sp_sto:
                for item in st_list:
                    item['assigned'] = True
                for item in sp_sto:
                    item['assigned'] = True

                sto_doc_ids = ", ".join(x['doc_id'] for x in sp_sto)
                exception_results.append({
                    'exception_id': f"EXC-STO-{key[0]}-{key[1]}",
                    'business_key': f"{key[0]}|{key[1]}|{key[2]}",
                    'station': key[0],
                    'date': key[1],
                    'product': key[2],
                    'station_qty': st_qty,
                    'sap_qty': 0.0,
                    'difference': st_qty,
                    'tolerance': self.calculate_tolerance(st_qty, 0.0),
                    'status': "WYJATEK_BIZNESOWY",
                    'category': "Przyjęcie na stacji przy dokumencie STO w SAP",
                    'sap_doc_ids': sto_doc_ids,
                    'reason': f"Stacja zaraportowała fizyczne przyjęcie {st_qty:.1f} l, jednak dokument SAP ({sto_doc_ids}) o ilości {sto_qty:.1f} l posiada status STO (storno/anulowany). Wymaga wyjaśnienia czy paliwo faktycznie zjechało do zbiornika.",
                    'action_required': "Wyjaśnienie z logistyką i dyspozycją baz paliwowych, czy storno w SAP było omyłkowe czy dostawę anulowano."
                })

        # ----------------------------------------------------------------------
        # ETAP 5: Korelacja incydentów krzyżowych (Błędny zakład w SAP: stacja A != zakład B)
        # ----------------------------------------------------------------------
        if self.enable_cross_station:
            unassigned_st = [st for st in station_deliveries if not st['assigned']]
            unassigned_sap = [sp for sp in sap_deliveries if not sp['assigned'] and not sp['is_sto']]

            for st_item in unassigned_st:
                for sp_item in unassigned_sap:
                    # RÓŻNE STACJE, ta sama data, ten sam produkt, ta sama ilość (w tolerancji)
                    if (st_item['station'] != sp_item['station'] and
                        st_item['date'] == sp_item['date'] and
                        st_item['product'] == sp_item['product']):
                        
                        tol = self.calculate_tolerance(st_item['qty_station'], sp_item['qty_real'])
                        diff = st_item['qty_station'] - sp_item['qty_real']

                        if abs(diff) <= tol:
                            st_item['assigned'] = True
                            sp_item['assigned'] = True

                            inc_id = f"INC-CROSS-{st_item['date']}-{st_item['product']}"
                            inc_desc = (
                                f"Stacja {st_item['station']} przyjęła {st_item['qty_station']:.1f} l {st_item['product']} w dniu {st_item['date']} (brak w SAP), "
                                f"podczas gdy w SAP zaksięgowano {sp_item['qty_real']:.1f} l tego samego produktu na Zakład ST{sp_item['station']} "
                                f"(dokument {sp_item['doc_id']}, brak przyjęcia na stacji {sp_item['station']}). "
                                f"Wysokie prawdopodobieństwo błędnego wyboru zakładu docelowego w SAP przez spedytora."
                            )

                            inc_recommendation = f"Korekta księgowania w SAP (storno z błędnego zakładu ST{sp_item['station']} i przeksięgowanie na właściwy ST{st_item['station']})."

                            incidents.append({
                                'incident_id': inc_id,
                                'date': st_item['date'],
                                'product': st_item['product'],
                                'station_reported': st_item['station'],
                                'sap_plant': sp_item['station'],
                                'station_qty': st_item['qty_station'],
                                'sap_qty': sp_item['qty_real'],
                                'sap_doc_id': sp_item['doc_id'],
                                'incident_type': "PODEJRZENIE_BLEDNEGO_ZAKLADU_SAP",
                                'description': inc_desc,
                                'recommendation': inc_recommendation
                            })

                            exception_results.append({
                                'exception_id': f"EXC-CROSS-{st_item['station']}-{st_item['date']}",
                                'business_key': f"{st_item['station']}|{st_item['date']}|{st_item['product']}",
                                'station': st_item['station'],
                                'date': st_item['date'],
                                'product': st_item['product'],
                                'station_qty': st_item['qty_station'],
                                'sap_qty': sp_item['qty_real'],
                                'difference': diff,
                                'tolerance': tol,
                                'status': "WYJATEK_BIZNESOWY",
                                'category': "Podejrzenie błędnego zakładu w SAP (Korelacja incydentu)",
                                'sap_doc_ids': sp_item['doc_id'],
                                'reason': inc_desc,
                                'action_required': inc_recommendation
                            })
                            break

        # ----------------------------------------------------------------------
        # ETAP 6: Pozostałe nieprzypisane rekordy (Braki po jednej ze stron)
        # ----------------------------------------------------------------------
        # A. Nieprzypisane dostawy stacyjne -> Brak w SAP
        remaining_st = [st for st in station_deliveries if not st['assigned']]
        for st_item in remaining_st:
            exception_results.append({
                'exception_id': f"EXC-NO-SAP-{st_item['station']}-{st_item['date']}",
                'business_key': f"{st_item['station']}|{st_item['date']}|{st_item['product']}",
                'station': st_item['station'],
                'date': st_item['date'],
                'product': st_item['product'],
                'station_qty': st_item['qty_station'],
                'sap_qty': 0.0,
                'difference': st_item['qty_station'],
                'tolerance': self.calculate_tolerance(st_item['qty_station'], 0.0),
                'status': "WYJATEK_BIZNESOWY",
                'category': "Dostawa na stacji brakująca w SAP",
                'sap_doc_ids': "-",
                'reason': f"Stacja zaraportowała przyjęcie {st_item['qty_station']:.1f} l paliwa, brak jakiegokolwiek aktywnego dokumentu dostawy w SAP.",
                'action_required': "Wyjaśnienie z operatorem logistycznym dostawy (brak awizacji/zlecenia w SAP)."
            })

        # B. Nieprzypisane dokumenty SAP -> Brak na stacji (Dostawa widmo)
        remaining_sap = [sp for sp in sap_deliveries if not sp['assigned'] and not sp['is_sto']]
        for sp_item in remaining_sap:
            exception_results.append({
                'exception_id': f"EXC-GHOST-{sp_item['station']}-{sp_item['date']}",
                'business_key': f"{sp_item['station']}|{sp_item['date']}|{sp_item['product']}",
                'station': sp_item['station'],
                'date': sp_item['date'],
                'product': sp_item['product'],
                'station_qty': 0.0,
                'sap_qty': sp_item['qty_real'],
                'difference': -sp_item['qty_real'],
                'tolerance': self.calculate_tolerance(0.0, sp_item['qty_real']),
                'status': "WYJATEK_BIZNESOWY",
                'category': "Dostawa w SAP brakująca na stacji (Dostawa widmo)",
                'sap_doc_ids': sp_item['doc_id'],
                'reason': f"Dokument SAP {sp_item['doc_id']} na ilość {sp_item['qty_real']:.1f} l w Zakładzie ST{sp_item['station']}, jednak stacja nie potwierdziła żadnego przyjęcia.",
                'action_required': "Weryfikacja czy autocysterna nie została przekierowana lub czy dokument nie jest zdublowany."
            })

        # Sortowanie wyników
        matched_results.sort(key=lambda x: (x['station'], x['date'], x['product']))
        exception_results.sort(key=lambda x: (x['station'], x['date'], x['product']))

        total_st_vol = sum(st['qty_station'] for st in station_deliveries)
        total_sap_vol = sum(sp['qty_real'] for sp in sap_deliveries if not sp['is_sto'])
        matched_vol = sum(m['station_qty'] for m in matched_results)

        stats = {
            'input_station_records_total': len(station_rows),
            'input_station_delivery_events': len(station_deliveries),
            'input_sap_records_total': len(sap_rows),
            'input_sap_active_deliveries': len([sp for sp in sap_deliveries if not sp['is_sto']]),
            'input_sap_sto_deliveries': len([sp for sp in sap_deliveries if sp['is_sto']]),
            'matched_count': len(matched_results),
            'exceptions_count': len(exception_results),
            'incidents_count': len(incidents),
            'total_station_volume_liters': total_st_vol,
            'total_sap_active_volume_liters': total_sap_vol,
            'matched_volume_liters': matched_vol,
            'reconciliation_rate_pct': (matched_vol / total_st_vol * 100.0) if total_st_vol > 0 else 0.0
        }

        logger.info(f"Uzgodnienie zakończone: Zgodne={stats['matched_count']}, Wyjątki={stats['exceptions_count']}, Incydenty={stats['incidents_count']}")

        return {
            'matched': matched_results,
            'exceptions': exception_results,
            'incidents': incidents,
            'stats': stats
        }
