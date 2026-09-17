"""
Moduł odpowiedzialny za bezpieczne wczytywanie plików źródłowych z obsługą
różnych stron kodowych (CP1250, UTF-8-SIG, UTF-8) i separatorów (;, ,).
"""
import os
import csv
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

ENCODING_CANDIDATES = ['utf-8-sig', 'cp1250', 'utf-8', 'iso-8859-2']
DELIMITER_CANDIDATES = [';', ',', '\t']


def detect_encoding_and_delimiter(file_path: str) -> Tuple[str, str]:
    """
    Automatycznie wykrywa właściwe kodowanie znaków oraz separator kolumn w pliku CSV.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Plik nie istnieje: {file_path}")

    # 1. Próba odczytu z różnymi kodowaniami
    valid_encoding = None
    sample_text = ""
    for enc in ENCODING_CANDIDATES:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                sample_text = f.read(4096)
            valid_encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if not valid_encoding:
        raise ValueError(f"Nie udało się rozpoznać kodowania pliku: {file_path}")

    # 2. Wykrycie separatora z pierwszej linii
    first_line = sample_text.splitlines()[0] if sample_text else ""
    delimiter_counts = {d: first_line.count(d) for d in DELIMITER_CANDIDATES}
    best_delimiter = max(delimiter_counts, key=delimiter_counts.get)
    if delimiter_counts[best_delimiter] == 0:
        best_delimiter = ','  # domyślny fallback

    logger.info(f"Plik '{os.path.basename(file_path)}': wykryto kodowanie={valid_encoding}, separator='{best_delimiter}'")
    return valid_encoding, best_delimiter


def load_csv_data(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Wczytuje dane z pliku CSV zwracając listę słowników (wierszy) oraz metadane pliku.
    """
    encoding, delimiter = detect_encoding_and_delimiter(file_path)
    rows = []

    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        # Czyszczenie nagłówków (usunięcie zbędnych spacji/BOM)
        fieldnames = [fn.strip() if fn else "" for fn in reader.fieldnames]
        reader.fieldnames = fieldnames
        
        for idx, row in enumerate(reader, start=1):
            cleaned_row = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
            cleaned_row['__source_row__'] = idx
            rows.append(cleaned_row)

    metadata = {
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'file_size_bytes': os.path.getsize(file_path),
        'encoding': encoding,
        'delimiter': delimiter,
        'row_count': len(rows),
        'columns': fieldnames
    }

    return rows, metadata
