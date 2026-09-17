"""
Moduł normalizacji danych ze stacji paliw oraz systemu SAP.
Zapewnia spójność typów, formatów dat, identyfikatorów stacji oraz nazw produktów.
"""
import re
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class Normalizer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.norm_cfg = config.get('normalization', {})
        self.station_len = self.norm_cfg.get('station_code_length', 4)
        self.sap_prefix = self.norm_cfg.get('station_sap_prefix', 'ST').upper()
        self.date_formats = self.norm_cfg.get('supported_date_formats', [
            "%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"
        ])
        
        # Słownik produktów znormalizowany (wielkie litery bez spacji)
        raw_mapping = config.get('product_mapping', {})
        self.product_map = {
            self._clean_text(k): v.strip() for k, v in raw_mapping.items()
        }

    @staticmethod
    def _clean_text(s: Optional[str]) -> str:
        if not s:
            return ""
        return " ".join(str(s).strip().upper().split())

    def normalize_station_id(self, raw_id: Any) -> str:
        """
        Normalizuje identyfikator stacji do formatu 4-cyfrowego (np. 'ST0412' -> '0412', '417' -> '0417').
        """
        if raw_id is None:
            return ""
        s = str(raw_id).strip().upper()
        if s.startswith(self.sap_prefix):
            s = s[len(self.sap_prefix):].strip()
        
        # Wyciągnięcie samych cyfr
        digits = re.sub(r'[^\d]', '', s)
        if not digits:
            return s
        return digits.zfill(self.station_len)

    def normalize_date(self, raw_date: Any) -> str:
        """
        Normalizuje datę do formatu ISO 'YYYY-MM-DD'.
        """
        if not raw_date:
            return ""
        s = str(raw_date).strip()
        for fmt in self.date_formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        logger.warning(f"Nie udało się sparsować daty: '{raw_date}'")
        return s

    def normalize_product(self, raw_product: Any) -> str:
        """
        Mapuje nazwę produktu na kanoniczny kod produktu (np. 'Pb 95' -> 'PB95', 'Olej napędowy' -> 'ON').
        """
        cleaned = self._clean_text(raw_product)
        if cleaned in self.product_map:
            return self.product_map[cleaned]
        logger.warning(f"Nieznany produkt w słowniku: '{raw_product}' (oczyszczony: '{cleaned}')")
        return cleaned

    @staticmethod
    def parse_quantity(raw_qty: Any) -> float:
        """
        Konwertuje tekstową wartość ilości paliwa na liczbę zmiennoprzecinkową.
        Obsługuje przecinek dziesiętny, spacje tysięczne oraz sufiksy jednostek (np. '0,0 l').
        """
        if raw_qty is None:
            return 0.0
        s = str(raw_qty).strip()
        if not s or s.lower() in ['n/d', 'na', 'null', 'brak', '-']:
            return 0.0
        
        # Usunięcie liter (np. 'l'), spacji
        s_clean = re.sub(r'[^\d,\.-]', '', s)
        s_clean = s_clean.replace(',', '.')
        try:
            return float(s_clean)
        except ValueError:
            logger.warning(f"Błąd parsowania wartości ilościowej: '{raw_qty}'")
            return 0.0
