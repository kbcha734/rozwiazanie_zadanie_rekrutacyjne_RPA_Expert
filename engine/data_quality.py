"""
Moduł audytu jakości danych wejściowych (Data Quality Engine).
Wykrywa sygnały anomalii, błędy formatowania, duplikaty, wartości 'n/d'
oraz niespójności fizyczne bilansu zbiorników, oddzielając je od wyjątków biznesowych.
"""
import logging
from collections import defaultdict
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class DataQualityAuditor:
    def __init__(self, normalizer):
        self.normalizer = normalizer

    def audit_station_data(self, raw_rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Audytuje raporty dobowe ze stacji.
        Zwraca listę wykrytych sygnałów jakości oraz zdeduplikowane/oczyszczone rekordy do uzgodnienia.
        """
        dq_signals = []
        key_groups = defaultdict(list)

        for row in raw_rows:
            source_row = row.get('__source_row__')
            st_raw = row.get('Kod stacji', '')
            dt_raw = row.get('Data', '')
            pr_raw = row.get('Produkt', '')
            dost_raw = row.get('Przyjęto dostawę [l]', '')
            sprz_raw = row.get('Sprzedaż [l]', '')
            pocz_raw = row.get('Stan pocz. [l]', '')
            konc_raw = row.get('Stan konc. [l]', '')

            st_norm = self.normalizer.normalize_station_id(st_raw)
            dt_norm = self.normalizer.normalize_date(dt_raw)
            pr_norm = self.normalizer.normalize_product(pr_raw)
            biz_key = f"{st_norm}|{dt_norm}|{pr_norm}"

            # 1. Sprawdzenie formatu stacji
            if st_raw.strip() != st_norm and not st_raw.strip().startswith('ST'):
                dq_signals.append({
                    'signal_id': f"DQ-ST-FMT-{source_row}",
                    'source': "STACJE",
                    'source_row': source_row,
                    'business_key': biz_key,
                    'signal_type': "NIESTANDARDOWY_KOD_STACJI",
                    'severity': "INFORMACYJNY",
                    'field': "Kod stacji",
                    'raw_value': st_raw,
                    'normalized_value': st_norm,
                    'description': f"Brak zera wiodącego w kodzie stacji '{st_raw}' -> uzupełniono do '{st_norm}'",
                    'recommended_action': "Dostosować generowanie raportu po stronie systemu POS stacji."
                })

            # 2. Sprawdzenie formatu daty
            if '.' in dt_raw:
                dq_signals.append({
                    'signal_id': f"DQ-DT-FMT-{source_row}",
                    'source': "STACJE",
                    'source_row': source_row,
                    'business_key': biz_key,
                    'signal_type': "NIESTANDARDOWY_FORMAT_DATY",
                    'severity': "INFORMACYJNY",
                    'field': "Data",
                    'raw_value': dt_raw,
                    'normalized_value': dt_norm,
                    'description': f"Format daty DD.MM.YYYY ('{dt_raw}') zamiast ISO YYYY-MM-DD",
                    'recommended_action': "Ujednolicić format daty w eksporcie POS."
                })

            # 3. Sprawdzenie wartości 'n/d' w stanach magazynowych
            if konc_raw.lower() in ['n/d', 'na', 'null']:
                dq_signals.append({
                    'signal_id': f"DQ-PROBE-{source_row}",
                    'source': "STACJE",
                    'source_row': source_row,
                    'business_key': biz_key,
                    'signal_type': "AWARYJNY_BRAK_ODCZYTU_SONDY",
                    'severity': "OSTRZEŻENIE",
                    'field': "Stan konc. [l]",
                    'raw_value': konc_raw,
                    'normalized_value': "BRAK DANYCH",
                    'description': f"Wartość 'n/d' w stanie końcowym zbiornika (potencjalna awaria sondy pomiarowej ATG)",
                    'recommended_action': "Zgłoszenie do serwisu automatyki stacyjnej i weryfikacja ręcznego pomiaru łatą."
                })

            # 4. Sprawdzenie ujemnych wartości
            sprz_val = self.normalizer.parse_quantity(sprz_raw)
            if sprz_val < 0:
                dq_signals.append({
                    'signal_id': f"DQ-NEG-VAL-{source_row}",
                    'source': "STACJE",
                    'source_row': source_row,
                    'business_key': biz_key,
                    'signal_type': "UJEMNA_SPRZEDAZ",
                    'severity': "KRYTYCZNY",
                    'field': "Sprzedaż [l]",
                    'raw_value': sprz_raw,
                    'normalized_value': str(sprz_val),
                    'description': f"Ujemna sprzedaż ({sprz_val} l). Może oznaczać błędną storno-korektę lub błąd oprogramowania dystrybutora.",
                    'recommended_action': "Wyjaśnienie z kierownikiem stacji i działem rozliczeń sprzedaży."
                })

            # 5. Kontrola bilansu zbiornika: Stan_pocz + Dostawa - Sprzedaż == Stan_konc
            dost_val = self.normalizer.parse_quantity(dost_raw)
            pocz_val = self.normalizer.parse_quantity(pocz_raw) if pocz_raw.lower() not in ['n/d', 'na', ''] else None
            konc_val = self.normalizer.parse_quantity(konc_raw) if konc_raw.lower() not in ['n/d', 'na', ''] else None

            if pocz_val is not None and konc_val is not None:
                calculated_konc = pocz_val + dost_val - sprz_val
                bilans_diff = konc_val - calculated_konc
                # Jeśli różnica > 50 litrów i nie jest to znany rekord z ujemną sprzedażą
                if abs(bilans_diff) > 50.0 and sprz_val >= 0:
                    dq_signals.append({
                        'signal_id': f"DQ-TANK-DIFF-{source_row}",
                        'source': "STACJE",
                        'source_row': source_row,
                        'business_key': biz_key,
                        'signal_type': "ROZBIEZNOSC_BILANSU_ZBIORNIKA",
                        'severity': "OSTRZEŻENIE",
                        'field': "Bilans [l]",
                        'raw_value': f"Pocz={pocz_val}, Dost={dost_val}, Sprz={sprz_val}, Konc={konc_val}",
                        'normalized_value': f"Różnica bilansowa: {bilans_diff:+.2f} l",
                        'description': f"Fizyczna niezgodność bilansu zbiornika o {bilans_diff:+.2f} litrów",
                        'recommended_action': "Kontrola szczelności instalacji paliwowej / kalibracji sondy ATG."
                    })

            # Dodanie do grupy kluczy
            key_groups[biz_key].append(row)

        # 6. Sprawdzenie duplikatów i konfliktów w kluczu biznesowym stacji
        clean_rows = []
        for biz_key, rows in key_groups.items():
            if len(rows) == 1:
                clean_rows.append(rows[0])
            else:
                # Sprawdzenie czy wiersze są identyczne (duplikat techniczny)
                first_row = rows[0]
                is_exact_duplicate = all(
                    {k: v for k, v in r.items() if k != '__source_row__'} ==
                    {k: v for k, v in first_row.items() if k != '__source_row__'}
                    for r in rows[1:]
                )

                if is_exact_duplicate:
                    for dup_row in rows[1:]:
                        s_row = dup_row.get('__source_row__')
                        dq_signals.append({
                            'signal_id': f"DQ-ST-DUP-{s_row}",
                            'source': "STACJE",
                            'source_row': s_row,
                            'business_key': biz_key,
                            'signal_type': "DUPLIKAT_WIERSZA_STACJI",
                            'severity': "OSTRZEŻENIE",
                            'field': "Wiersz raportu",
                            'raw_value': str({k: v for k, v in dup_row.items() if k != '__source_row__'}),
                            'normalized_value': "Zignorowano w uzgodnieniu (deduplikacja)",
                            'description': f"Identyczny powtórzony wiersz w raporcie dobowym stacji (wiersz {s_row} jest duplikatem wiersza {first_row.get('__source_row__')}).",
                            'recommended_action': "Usunięcie redundancji w module generowania/przesyłania plików z POS."
                        })
                    # Do dalszego uzgodnienia bierzemy tylko jeden egzemplarz
                    clean_rows.append(first_row)
                else:
                    # Konflikt: różne dane dla tego samego klucza biznesowego
                    for r in rows:
                        s_row = r.get('__source_row__')
                        dq_signals.append({
                            'signal_id': f"DQ-ST-CONF-{s_row}",
                            'source': "STACJE",
                            'source_row': s_row,
                            'business_key': biz_key,
                            'signal_type': "KONFLIKT_WIERSZY_KLUCZA",
                            'severity': "KRYTYCZNY",
                            'field': "Wiersz raportu",
                            'raw_value': str({k: v for k, v in r.items() if k != '__source_row__'}),
                            'normalized_value': "Wymaga wyjaśnienia",
                            'description': f"Wielokrotny wiersz o różnych wartościach dla tej samej stacji, daty i produktu.",
                            'recommended_action': "Pilna weryfikacja logów stacji przez wsparcie IT POS."
                        })
                    # Do uzgodnienia bierzemy wiersz z nieujemną sprzedażą / poprawny
                    valid_row = [r for r in rows if self.normalizer.parse_quantity(r.get('Sprzedaż [l]', 0)) >= 0]
                    if valid_row:
                        clean_rows.append(valid_row[0])
                    else:
                        clean_rows.append(rows[0])

        return dq_signals, clean_rows

    def audit_sap_data(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Audytuje dokumenty dostaw pobrane z SAP.
        """
        dq_signals = []
        seen_docs = defaultdict(list)

        for row in raw_rows:
            source_row = row.get('__source_row__')
            doc_id = row.get('Nr dokumentu', '').strip()
            plant_raw = row.get('Zakład', '')
            dt_raw = row.get('Data księgowania', '')
            mat_raw = row.get('Materiał', '')
            qty_real_raw = row.get('Ilość rzeczywista [l]', '')
            status_raw = row.get('Status', '').strip().upper()

            seen_docs[doc_id].append(row)

            # Sprawdzenie statusu STO (jako sygnał procesowy)
            if status_raw == 'STO':
                dq_signals.append({
                    'signal_id': f"DQ-SAP-STO-{source_row}",
                    'source': "SAP",
                    'source_row': source_row,
                    'business_key': f"{self.normalizer.normalize_station_id(plant_raw)}|{self.normalizer.normalize_date(dt_raw)}|{self.normalizer.normalize_product(mat_raw)}",
                    'signal_type': "DOKUMENT_STATUS_STO",
                    'severity': "OSTRZEŻENIE",
                    'field': "Status",
                    'raw_value': f"Dokument {doc_id}, Status={status_raw}",
                    'normalized_value': "Nieaktywna dostawa (STO)",
                    'description': f"Dokument dostawy w SAP posiada status STO (storno / anulowanie). Nie stanowi aktywnej dostawy.",
                    'recommended_action': "Weryfikacja w SAP przyczyny anulowania dokumentu dostawy."
                })

        # Wykrycie zduplikowanych numerów dokumentów w SAP
        for doc_id, occurrences in seen_docs.items():
            if len(occurrences) > 1:
                for occ in occurrences:
                    s_row = occ.get('__source_row__')
                    dq_signals.append({
                        'signal_id': f"DQ-SAP-DUPDOC-{s_row}",
                        'source': "SAP",
                        'source_row': s_row,
                        'business_key': f"DOC-{doc_id}",
                        'signal_type': "ZDUPLIKOWANY_NUMER_DOKUMENTU_SAP",
                        'severity': "KRYTYCZNY",
                        'field': "Nr dokumentu",
                        'raw_value': f"Dokument {doc_id} w Zakładzie {occ.get('Zakład')} dla materiału {occ.get('Materiał')} ({occ.get('Ilość rzeczywista [l]')} l)",
                        'normalized_value': "Anomalia SAP",
                        'description': f"Ten sam numer dokumentu ({doc_id}) został przypisany do różnych zakładów lub materiałów w SAP!",
                        'recommended_action': "Pilne zgłoszenie do zespołu wsparcia SAP FI/MM (naruszenie unikalności numeracji dokumentów dostaw)."
                    })

        return dq_signals
