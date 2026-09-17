"""
Główny punkt wejścia do aplikacji uzgadniania dostaw paliw (CLI).
Uruchomienie:
    python main.py
    python main.py --config config.yaml --verbose
"""
import os
import sys
import yaml
import argparse
import logging
from typing import Dict, Any

from engine.data_loader import load_csv_data
from engine.normalizer import Normalizer
from engine.data_quality import DataQualityAuditor
from engine.reconciler import FuelReconciler
from engine.reporter import ReportGenerator


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )


def load_config(config_path: str) -> Dict[str, Any]:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Nie znaleziono pliku konfiguracyjnego: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config


def main():
    parser = argparse.ArgumentParser(
        description="Silnik uzgadniania dostaw paliw (Raporty stacyjne vs SAP MM/SD)"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Ścieżka do pliku konfiguracyjnego YAML (domyślnie: config.yaml)"
    )
    parser.add_argument(
        "--input-dir", "-i",
        default=None,
        help="Opcjonalne nadpisanie katalogu z danymi wejściowymi"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Opcjonalne nadpisanie katalogu wynikowego"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Szczegółowe logowanie diagnostyczne (DEBUG)"
    )

    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("FuelReconcilerMain")

    print("\n" + "=" * 80)
    print("      AUTOMATYZACJA UZGODNIEŃ DOSTAW PALIW - KONTROLING SIECI")
    print("=" * 80)

    # 1. Wczytanie konfiguracji
    logger.info(f"Wczytywanie konfiguracji z: {args.config}")
    config = load_config(args.config)

    input_dir = args.input_dir or config.get('paths', {}).get('input_dir', 'dane_zadanie_praktyczne')
    output_dir = args.output_dir or config.get('paths', {}).get('output_dir', 'output')
    stations_filename = config.get('paths', {}).get('stations_file', 'stacje_raport_dobowy.csv')
    sap_filename = config.get('paths', {}).get('sap_file', 'sap_dostawy.csv')

    stations_path = os.path.join(input_dir, stations_filename)
    sap_path = os.path.join(input_dir, sap_filename)

    # 2. Wczytanie plików wejściowych
    logger.info(f"Wczytywanie raportów stacji: {stations_path}")
    st_rows, st_meta = load_csv_data(stations_path)
    logger.info(f"Wczytano {len(st_rows)} wierszy ze stacji (kodowanie: {st_meta['encoding']}, separator: '{st_meta['delimiter']}')")

    logger.info(f"Wczytywanie dokumentów SAP: {sap_path}")
    sap_rows, sap_meta = load_csv_data(sap_path)
    logger.info(f"Wczytano {len(sap_rows)} wierszy z SAP (kodowanie: {sap_meta['encoding']}, separator: '{sap_meta['delimiter']}')")

    # 3. Inicjalizacja komponentów
    normalizer = Normalizer(config)
    dq_auditor = DataQualityAuditor(normalizer)
    reconciler = FuelReconciler(config, normalizer)
    reporter = ReportGenerator(output_dir)

    # 4. Audyt jakości danych wejściowych (Data Quality)
    logger.info("Rozpoczęcie audytu jakości danych wejściowych...")
    st_dq_signals, st_clean_rows = dq_auditor.audit_station_data(st_rows)
    sap_dq_signals = dq_auditor.audit_sap_data(sap_rows)
    all_dq_signals = st_dq_signals + sap_dq_signals
    logger.info(f"Zidentyfikowano {len(all_dq_signals)} sygnałów jakości danych (stacje: {len(st_dq_signals)}, SAP: {len(sap_dq_signals)})")

    # 5. Wykonanie uzgodnienia
    logger.info("Uruchamianie silnika uzgadniania dostaw paliw...")
    recon_result = reconciler.reconcile(st_clean_rows, sap_rows)

    # 6. Generowanie raportów
    logger.info("Generowanie raportów końcowych (XLSX, CSV, JSON)...")
    exported_files = reporter.generate_all_reports(
        reconciliation_data=recon_result,
        data_quality_signals=all_dq_signals,
        files_metadata=[st_meta, sap_meta]
    )

    # 7. Wyświetlenie podsumowania w konsoli
    stats = recon_result['stats']
    print("\n" + "-" * 80)
    print("                 PODSUMOWANIE WYNIKÓW UZGODNIENIA")
    print("-" * 80)
    print(f" * Wiersze wejściowe stacji:         {stats['input_station_records_total']} (w tym {stats['input_station_delivery_events']} z dostawą > 0)")
    print(f" * Dokumenty wejściowe SAP:          {stats['input_sap_records_total']} (aktywne: {stats['input_sap_active_deliveries']}, STO: {stats['input_sap_sto_deliveries']})")
    print(f" * Dostawy w 100% ZGODNE:            {stats['matched_count']}")
    print(f" * WYJĄTKI BIZNESOWE do wyjaśnienia: {stats['exceptions_count']}")
    print(f" * POWIĄZANE INCYDENTY:              {stats['incidents_count']}")
    print(f" * SYGNAŁY JAKOŚCI DANYCH:           {len(all_dq_signals)}")
    print(f" * Wolumen stacji vs SAP:            {stats['total_station_volume_liters']:,.1f} l vs {stats['total_sap_active_volume_liters']:,.1f} l")
    print(f" * Wolumen uzgodniony:               {stats['matched_volume_liters']:,.1f} l ({stats['reconciliation_rate_pct']:.1f}%)")
    print("-" * 80)

    if recon_result['exceptions']:
        print("\n[!] LISTA WYJĄTKÓW BIZNESOWYCH:")
        for idx, exc in enumerate(recon_result['exceptions'], start=1):
            print(f"  {idx}. [{exc['category']}] Klucz: {exc['business_key']} | Stacja: {exc['station_qty']} l | SAP: {exc['sap_qty']} l | Dok SAP: {exc['sap_doc_ids']}")
            print(f"     -> Powód: {exc['reason']}")

    if recon_result['incidents']:
        print("\n[!] SKORELOWANE INCYDENTY MIĘDZYSTACYJNE:")
        for idx, inc in enumerate(recon_result['incidents'], start=1):
            print(f"  {idx}. [{inc['incident_type']}] Data: {inc['date']}, Produkt: {inc['product']}")
            print(f"     -> Zgłoszenie stacji {inc['station_reported']} ({inc['station_qty']} l) vs Zakład SAP ST{inc['sap_plant']} ({inc['sap_qty']} l, dok: {inc['sap_doc_id']})")
            print(f"     -> {inc['recommendation']}")

    print("\n" + "=" * 80)
    print("WYGENEROWANE PLIKI RAPORTOWE:")
    for k, path in exported_files.items():
        print(f"  - [{k:13s}]: {path}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
