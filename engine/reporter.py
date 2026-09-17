"""
Moduł raportowania i eksportu wyników uzgodnienia (Reporter).
Generuje elegancki, wielozakładkowy arkusz Excel (.xlsx) z kolorowaniem statusów,
auto-dopasowaniem szerokości kolumn oraz pliki CSV i JSON dla procesów downstream.
"""
import os
import json
import logging
from typing import Dict, List, Any
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_all_reports(
        self,
        reconciliation_data: Dict[str, Any],
        data_quality_signals: List[Dict[str, Any]],
        files_metadata: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Generuje komplet raportów: Excel (.xlsx), CSV oraz JSON.
        """
        excel_path = os.path.join(self.output_dir, "wynik_uzgodnienia.xlsx")
        summary_csv_path = os.path.join(self.output_dir, "uzgodnienie_podsumowanie.csv")
        exceptions_csv_path = os.path.join(self.output_dir, "uzgodnienie_wyjatki.csv")
        dq_csv_path = os.path.join(self.output_dir, "raport_jakosc_danych.csv")
        json_path = os.path.join(self.output_dir, "wynik_uzgodnienia.json")

        self._export_excel(
            excel_path=excel_path,
            reconciliation_data=reconciliation_data,
            dq_signals=data_quality_signals,
            files_meta=files_metadata
        )

        self._export_csvs(
            summary_csv_path=summary_csv_path,
            exceptions_csv_path=exceptions_csv_path,
            dq_csv_path=dq_csv_path,
            reconciliation_data=reconciliation_data,
            dq_signals=data_quality_signals
        )

        self._export_json(
            json_path=json_path,
            reconciliation_data=reconciliation_data,
            dq_signals=data_quality_signals,
            files_meta=files_metadata
        )

        return {
            'excel': excel_path,
            'summary_csv': summary_csv_path,
            'exceptions_csv': exceptions_csv_path,
            'dq_csv': dq_csv_path,
            'json': json_path
        }

    def _export_csvs(
        self,
        summary_csv_path: str,
        exceptions_csv_path: str,
        dq_csv_path: str,
        reconciliation_data: Dict[str, Any],
        dq_signals: List[Dict[str, Any]]
    ):
        # 1. Podsumowanie statystyk do CSV
        stats_df = pd.DataFrame([reconciliation_data['stats']])
        stats_df.to_csv(summary_csv_path, index=False, encoding='utf-8-sig', sep=';')

        # 2. Wyjątki biznesowe do CSV
        if reconciliation_data['exceptions']:
            exc_df = pd.DataFrame(reconciliation_data['exceptions'])
            exc_df.to_csv(exceptions_csv_path, index=False, encoding='utf-8-sig', sep=';')

        # 3. Sygnały jakości danych do CSV
        if dq_signals:
            dq_df = pd.DataFrame(dq_signals)
            dq_df.to_csv(dq_csv_path, index=False, encoding='utf-8-sig', sep=';')

    def _export_json(
        self,
        json_path: str,
        reconciliation_data: Dict[str, Any],
        dq_signals: List[Dict[str, Any]],
        files_meta: List[Dict[str, Any]]
    ):
        full_payload = {
            'metadata': files_meta,
            'statistics': reconciliation_data['stats'],
            'matched': reconciliation_data['matched'],
            'exceptions': reconciliation_data['exceptions'],
            'incidents': reconciliation_data['incidents'],
            'data_quality_signals': dq_signals
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(full_payload, f, ensure_ascii=False, indent=2)

    def _export_excel(
        self,
        excel_path: str,
        reconciliation_data: Dict[str, Any],
        dq_signals: List[Dict[str, Any]],
        files_meta: List[Dict[str, Any]]
    ):
        wb = Workbook()
        wb.remove(wb.active)  # Usunięcie domyślnego pustego arkusza

        # Style firmowe (Orlen Red & Slate Blue)
        header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1A365D")
        sub_font = Font(name="Calibri", size=10, italic=True, color="555555")
        bold_font = Font(name="Calibri", size=11, bold=True)
        regular_font = Font(name="Calibri", size=11)
        
        thin_border = Border(
            left=Side(style='thin', color='D3D3D3'),
            right=Side(style='thin', color='D3D3D3'),
            top=Side(style='thin', color='D3D3D3'),
            bottom=Side(style='thin', color='D3D3D3')
        )

        green_fill = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
        orange_fill = PatternFill(start_color="FEF7E0", end_color="FEF7E0", fill_type="solid")
        red_fill = PatternFill(start_color="FCE8E6", end_color="FCE8E6", fill_type="solid")

        # ======================================================================
        # ARKUSZ 1: PODSUMOWANIE (EXECUTIVE SUMMARY & KPIS)
        # ======================================================================
        ws_sum = wb.create_sheet(title="Podsumowanie")
        ws_sum.views.sheetView[0].showGridLines = True

        ws_sum.cell(row=2, column=2, value="RAPORT UZGODNIENIA DOSTAW PALIW - KONTROLING SIECI").font = title_font
        ws_sum.cell(row=3, column=2, value="Wygenerowano automatycznie przez silnik FuelReconciler").font = sub_font

        stats = reconciliation_data['stats']
        kpis = [
            ("Liczba wierszy w raporcie stacji (wejście)", stats['input_station_records_total'], "wierszy"),
            ("Liczba zaraportowanych dostaw na stacjach (> 0 l)", stats['input_station_delivery_events'], "dostaw"),
            ("Liczba dokumentów dostaw w SAP (wejście)", stats['input_sap_records_total'], "dokumentów"),
            ("Liczba aktywnych dokumentów SAP", stats['input_sap_active_deliveries'], "dokumentów"),
            ("Liczba dokumentów SAP ze statusem STO (anulowane)", stats['input_sap_sto_deliveries'], "dokumentów"),
            ("Liczba dostaw w 100% ZGODNYCH (w tolerancji)", stats['matched_count'], "dostaw"),
            ("Liczba WYJĄTKÓW BIZNESOWYCH wymagających wyjaśnienia", stats['exceptions_count'], "przypadków"),
            ("Liczba POWIĄZANYCH INCYDENTÓW (np. błędny zakład)", stats['incidents_count'], "incydentów"),
            ("Liczba wykrytych SYGNAŁÓW JAKOŚCI DANYCH", len(dq_signals), "sygnałów"),
            ("Wolumen zgłoszony przez stacje", f"{stats['total_station_volume_liters']:,.1f} l", "litrów"),
            ("Wolumen aktywnych dostaw SAP", f"{stats['total_sap_active_volume_liters']:,.1f} l", "litrów"),
            ("Wolumen uzgodniony w pełnej zgodności", f"{stats['matched_volume_liters']:,.1f} l", "litrów"),
            ("Wskaźnik bezpośredniej zgodności wolumenu", f"{stats['reconciliation_rate_pct']:.1f}%", "skuteczność")
        ]

        # Tabela KPI
        ws_sum.cell(row=5, column=2, value="Wskaźnik / Metryka Kontrolna").font = header_font
        ws_sum.cell(row=5, column=2).fill = header_fill
        ws_sum.cell(row=5, column=3, value="Wartość").font = header_font
        ws_sum.cell(row=5, column=3).fill = header_fill
        ws_sum.cell(row=5, column=4, value="Jednostka").font = header_font
        ws_sum.cell(row=5, column=4).fill = header_fill

        for idx, (label, val, unit) in enumerate(kpis, start=6):
            c1 = ws_sum.cell(row=idx, column=2, value=label)
            c2 = ws_sum.cell(row=idx, column=3, value=val)
            c3 = ws_sum.cell(row=idx, column=4, value=unit)

            c1.font = regular_font
            c2.font = bold_font
            c3.font = regular_font
            c2.alignment = Alignment(horizontal="right")

            for cell in [c1, c2, c3]:
                cell.border = thin_border

        # ======================================================================
        # ARKUSZ 2: ZGODNE DOSTAWY
        # ======================================================================
        ws_match = wb.create_sheet(title="Zgodne")
        ws_match.views.sheetView[0].showGridLines = True

        match_headers = [
            "Klucz Biznesowy", "Stacja", "Doba", "Produkt",
            "Ilość Stacja [l]", "Ilość SAP [l]", "Różnica [l]",
            "Tolerancja [l]", "Status", "Kategoria", "Liczba Dok. SAP",
            "Numery Dok. SAP", "Uwagi / Agregacja"
        ]

        for col_idx, h in enumerate(match_headers, start=1):
            cell = ws_match.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, m in enumerate(reconciliation_data['matched'], start=2):
            ws_match.cell(row=r_idx, column=1, value=m['business_key']).font = regular_font
            ws_match.cell(row=r_idx, column=2, value=m['station']).font = regular_font
            ws_match.cell(row=r_idx, column=3, value=m['date']).font = regular_font
            ws_match.cell(row=r_idx, column=4, value=m['product']).font = bold_font
            
            c_sq = ws_match.cell(row=r_idx, column=5, value=m['station_qty'])
            c_sq.number_format = '#,##0.0'
            c_sq.font = regular_font

            c_pq = ws_match.cell(row=r_idx, column=6, value=m['sap_qty'])
            c_pq.number_format = '#,##0.0'
            c_pq.font = regular_font

            c_df = ws_match.cell(row=r_idx, column=7, value=m['difference'])
            c_df.number_format = '#,##0.0'
            c_df.font = regular_font

            c_tl = ws_match.cell(row=r_idx, column=8, value=m['tolerance'])
            c_tl.number_format = '#,##0.0'
            c_tl.font = regular_font

            c_st = ws_match.cell(row=r_idx, column=9, value=m['status'])
            c_st.font = bold_font
            c_st.fill = green_fill
            c_st.alignment = Alignment(horizontal="center")

            ws_match.cell(row=r_idx, column=10, value=m['category']).font = regular_font
            ws_match.cell(row=r_idx, column=11, value=m['sap_docs_count']).font = regular_font
            ws_match.cell(row=r_idx, column=12, value=m['sap_doc_ids']).font = regular_font
            ws_match.cell(row=r_idx, column=13, value=m['notes']).font = regular_font

            for c in range(1, 14):
                ws_match.cell(row=r_idx, column=c).border = thin_border

        # ======================================================================
        # ARKUSZ 3: WYJĄTKI BIZNESOWE
        # ======================================================================
        ws_exc = wb.create_sheet(title="Wyjątki_Biznesowe")
        ws_exc.views.sheetView[0].showGridLines = True

        exc_headers = [
            "ID Wyjątku", "Klucz Biznesowy", "Stacja", "Doba", "Produkt",
            "Ilość Stacja [l]", "Ilość SAP [l]", "Różnica [l]", "Tolerancja [l]",
            "Status", "Kategoria Wyjątku", "Numery Dok. SAP",
            "Powód Wyjątku / Uzasadnienie", "Rekomendowana Akcja Biznesowa"
        ]

        for col_idx, h in enumerate(exc_headers, start=1):
            cell = ws_exc.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, exc in enumerate(reconciliation_data['exceptions'], start=2):
            ws_exc.cell(row=r_idx, column=1, value=exc['exception_id']).font = bold_font
            ws_exc.cell(row=r_idx, column=2, value=exc['business_key']).font = regular_font
            ws_exc.cell(row=r_idx, column=3, value=exc['station']).font = regular_font
            ws_exc.cell(row=r_idx, column=4, value=exc['date']).font = regular_font
            ws_exc.cell(row=r_idx, column=5, value=exc['product']).font = bold_font

            c_sq = ws_exc.cell(row=r_idx, column=6, value=exc['station_qty'])
            c_sq.number_format = '#,##0.0'
            c_sq.font = regular_font

            c_pq = ws_exc.cell(row=r_idx, column=7, value=exc['sap_qty'])
            c_pq.number_format = '#,##0.0'
            c_pq.font = regular_font

            c_df = ws_exc.cell(row=r_idx, column=8, value=exc['difference'])
            c_df.number_format = '#,##0.0'
            c_df.font = bold_font

            c_tl = ws_exc.cell(row=r_idx, column=9, value=exc['tolerance'])
            c_tl.number_format = '#,##0.0'
            c_tl.font = regular_font

            c_st = ws_exc.cell(row=r_idx, column=10, value=exc['status'])
            c_st.font = bold_font
            c_st.alignment = Alignment(horizontal="center")
            if "PRZESUNIECIE" in exc['category'].upper():
                c_st.fill = orange_fill
            else:
                c_st.fill = red_fill

            ws_exc.cell(row=r_idx, column=11, value=exc['category']).font = bold_font
            ws_exc.cell(row=r_idx, column=12, value=exc['sap_doc_ids']).font = regular_font
            ws_exc.cell(row=r_idx, column=13, value=exc['reason']).font = regular_font
            ws_exc.cell(row=r_idx, column=14, value=exc['action_required']).font = regular_font

            for c in range(1, 15):
                ws_exc.cell(row=r_idx, column=c).border = thin_border

        # ======================================================================
        # ARKUSZ 4: SYGNAŁY JAKOŚCI DANYCH (DATA QUALITY)
        # ======================================================================
        ws_dq = wb.create_sheet(title="Jakość_Danych")
        ws_dq.views.sheetView[0].showGridLines = True

        dq_headers = [
            "ID Sygnału", "Źródło", "Wiersz Pliku", "Klucz / Identyfikator",
            "Typ Sygnału", "Poziom Ryzyka", "Badane Pole", "Wartość Surowa",
            "Wartość Znormalizowana / Akcja", "Opis Problemu", "Rekomendowane Działanie IT / Biznesu"
        ]

        for col_idx, h in enumerate(dq_headers, start=1):
            cell = ws_dq.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, sig in enumerate(dq_signals, start=2):
            ws_dq.cell(row=r_idx, column=1, value=sig['signal_id']).font = bold_font
            ws_dq.cell(row=r_idx, column=2, value=sig['source']).font = regular_font
            ws_dq.cell(row=r_idx, column=3, value=sig['source_row']).font = regular_font
            ws_dq.cell(row=r_idx, column=4, value=sig['business_key']).font = regular_font
            ws_dq.cell(row=r_idx, column=5, value=sig['signal_type']).font = bold_font

            c_sev = ws_dq.cell(row=r_idx, column=6, value=sig['severity'])
            c_sev.font = bold_font
            c_sev.alignment = Alignment(horizontal="center")
            if sig['severity'] == 'KRYTYCZNY':
                c_sev.fill = red_fill
            elif sig['severity'] == 'OSTRZEŻENIE':
                c_sev.fill = orange_fill
            else:
                c_sev.fill = green_fill

            ws_dq.cell(row=r_idx, column=7, value=sig['field']).font = regular_font
            ws_dq.cell(row=r_idx, column=8, value=str(sig['raw_value'])).font = regular_font
            ws_dq.cell(row=r_idx, column=9, value=str(sig['normalized_value'])).font = regular_font
            ws_dq.cell(row=r_idx, column=10, value=sig['description']).font = regular_font
            ws_dq.cell(row=r_idx, column=11, value=sig['recommended_action']).font = regular_font

            for c in range(1, 12):
                ws_dq.cell(row=r_idx, column=c).border = thin_border

        # ======================================================================
        # ARKUSZ 5: INCYDENTY POWIĄZANE
        # ======================================================================
        ws_inc = wb.create_sheet(title="Incydenty_Powiązane")
        ws_inc.views.sheetView[0].showGridLines = True

        inc_headers = [
            "ID Incydentu", "Data", "Produkt", "Stacja Zgłaszająca", "Zakład w SAP",
            "Ilość Stacja [l]", "Ilość SAP [l]", "Dokument SAP", "Typ Incydentu",
            "Szczegółowy Opis Powiązania", "Rekomendacja Naprawcza"
        ]

        for col_idx, h in enumerate(inc_headers, start=1):
            cell = ws_inc.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for r_idx, inc in enumerate(reconciliation_data['incidents'], start=2):
            ws_inc.cell(row=r_idx, column=1, value=inc['incident_id']).font = bold_font
            ws_inc.cell(row=r_idx, column=2, value=inc['date']).font = regular_font
            ws_inc.cell(row=r_idx, column=3, value=inc['product']).font = bold_font
            ws_inc.cell(row=r_idx, column=4, value=inc['station_reported']).font = regular_font
            ws_inc.cell(row=r_idx, column=5, value=inc['sap_plant']).font = regular_font
            
            c_sq = ws_inc.cell(row=r_idx, column=6, value=inc['station_qty'])
            c_sq.number_format = '#,##0.0'
            c_sq.font = regular_font

            c_pq = ws_inc.cell(row=r_idx, column=7, value=inc['sap_qty'])
            c_pq.number_format = '#,##0.0'
            c_pq.font = regular_font

            ws_inc.cell(row=r_idx, column=8, value=inc['sap_doc_id']).font = regular_font
            ws_inc.cell(row=r_idx, column=9, value=inc['incident_type']).font = bold_font
            ws_inc.cell(row=r_idx, column=10, value=inc['description']).font = regular_font
            ws_inc.cell(row=r_idx, column=11, value=inc['recommendation']).font = regular_font

            for c in range(1, 12):
                ws_inc.cell(row=r_idx, column=c).border = thin_border

        # Auto-dopasowanie szerokości kolumn we wszystkich arkuszach
        for sheet in wb.worksheets:
            for col in sheet.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value:
                        lines = str(cell.value).split("\n")
                        line_len = max(len(l) for l in lines)
                        if line_len > max_len:
                            max_len = line_len
                sheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)

        wb.save(excel_path)
        logger.info(f"Zapisano arkusz Excel: {excel_path}")
