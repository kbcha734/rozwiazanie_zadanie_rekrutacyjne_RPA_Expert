# System Uzgadniania Dostaw Paliw (Fuel Delivery Reconciliation Engine)

Rozwiązanie analityczno-automatyzacyjne przygotowane w ramach zadania rekrutacyjnego na stanowisko **Eksperta ds. automatyzacji procesów (Power Automate, UiPath)**.

System realizuje codzienne, deterministyczne uzgadnianie dobowych raportów stacyjnych (`stacje_raport_dobowy.csv`) z dokumentami magazynowo-finansowymi zaksięgowanymi w systemie centralnym SAP (`sap_dostawy.csv`).

---

## 1. Szybki start (Instrukcja uruchomienia)

### Wymagania wstępne
- Python 3.9+ (rekomendowany 3.10+)
- Zainstalowane pakiety z pliku `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```

### Uruchomienie procesu uzgodnienia
Aby uruchomić pełny proces z domyślną konfiguracją:
```bash
python main.py
```

Opcje wiersza poleceń:
```bash
python main.py --help
# Uruchomienie z inną ścieżką konfiguracji:
python main.py --config config.yaml
# Tryb diagnostyczny (szczegółowe logowanie DEBUG):
python main.py --verbose
# Nadpisanie katalogów wejścia/wyjścia:
python main.py --input-dir dane_zadanie_praktyczne --output-dir output
```

### Uruchomienie testów jednostkowych
Pakiet zawiera zestaw testów regresyjnych pokrywających normalizację, reguły tolerancji i przypadki brzegowe:
```bash
python -m unittest discover tests
```

---

## 2. Struktura repozytorium

```
zadanie orlen praca/
├── config.yaml                    # Główny plik konfiguracji biznesowej (tolerancje, słowniki, reguły)
├── main.py                        # Punkt wejścia CLI (orkiestracja potoku)
├── requirements.txt               # Zależności biblioteczne (pandas, openpyxl, pyyaml)
├── README.md                      # Niniejsza instrukcja
├── engine/                        # Modułowy rdzeń silnika uzgadniającego
│   ├── __init__.py
│   ├── data_loader.py             # Bezpieczny odczyt plików (auto-detekcja kodowania CP1250/UTF-8 i separatorów)
│   ├── normalizer.py              # Normalizacja stacji (padding 4 cyfry), dat (ISO YYYY-MM-DD), produktów i liczb
│   ├── data_quality.py            # Audyt jakości danych (duplikaty, ujemna sprzedaż, brakujące 'n/d', duplikat SAP doc)
│   ├── reconciler.py              # Silnik reguł biznesowych (tolerancje, sumowanie, D+1, status STO, incydenty)
│   └── reporter.py                # Generator sformatowanego raportu Excel (.xlsx), CSV i JSON
├── tests/
│   ├── __init__.py
│   └── test_reconciliation.py     # Zestaw testów jednostkowych
├── output/                        # Wygenerowane raporty wynikowe
│   ├── wynik_uzgodnienia.xlsx     # Wielozakładkowy arkusz analityczny (Podsumowanie, Zgodne, Wyjątki, Jakość, Incydenty)
│   ├── uzgodnienie_podsumowanie.csv
│   ├── uzgodnienie_wyjatki.csv
│   ├── raport_jakosc_danych.csv
│   └── wynik_uzgodnienia.json
└── dokumentacja/
    ├── decyzje_architektoniczne.md # 2-stronicowy dokument decyzji projektowych i architektury docelowej
    ├── przeglad_power_automate.md  # Ekspercki audyt i przegląd przepływu z Części B
    └── przygotowanie_do_obrony.md  # Ściąga i przewodnik na 90-minutową obronę na żywo
```

---

## 3. Podsumowanie wyników uzgodnienia (Dla dostarczonych danych)

Uruchomienie silnika na danych dostarczonych w zadaniu daje w 100% deterministyczny bilans:

| Wskaźnik / Metryka Kontrolna | Wartość | Uwagi analityczne |
| :--- | :---: | :--- |
| **Wiersze raportu stacji (wejście)** | 140 | 138 unikalnych kluczy (wykryto 1 identyczny duplikat wiersza + 1 konflikt) |
| **Zaraportowane przyjęcia paliwa (> 0 l)** | 47 | Wolumen fizyczny stacji: **861 000,0 l** |
| **Dokumenty dostaw SAP (wejście)** | 49 | 48 aktywnych + 1 o statusie STO. Wolumen: **867 000,0 l** |
| **Dostawy w 100% ZGODNE** | **44** | Wolumen uzgodniony: **810 000,0 l (94.1%)** |
| **WYJĄTKI BIZNESOWE do wyjaśnienia** | **4** | Skategoryzowane i opisane z podaniem przyczyny i akcji |
| **SKORELOWANE INCYDENTY MIĘDZYSTACYJNE** | **1** | Błędny zakład w SAP dla stacji 0417 vs 0523 (LPG 15 000 l) |
| **SYGNAŁY JAKOŚCI DANYCH (DQ)** | **21** | Formaty stacji, dat, duplikaty, wartości 'n/d' w sondach ATG |

### Wykryte wyjątki biznesowe:
1. **Status STO w SAP przy przyjęciu na stacji (`0412|2026-08-26|PB98`)**: Stacja przyjęła 12 000 l paliwa, podczas gdy dokument SAP `4500011249` posiada status STO (storno).
2. **Przesunięcie daty po północy D+1 (`0417|2026-08-25|LPG`)**: Stacja przyjęła 24 000 l w dobie 25.08, natomiast w SAP dostawa została zaksięgowana po północy 26.08 (dokument `4500011269`).
3. **Podejrzenie błędnego zakładu w SAP (`0417|2026-08-24|LPG`)**: Stacja 0417 przyjęła 15 000 l LPG (brak w SAP), a w SAP zaksięgowano 15 000 l LPG na Zakład ST0523 (gdzie stacja 0523 nie miała dostawy LPG).
4. **Dostawa widmo w SAP (`1402|2026-08-26|ON`)**: Dokument SAP `4500011399` na 18 000 l ON, stacja 1402 nie odnotowała przyjęcia. Dokument ten jest jednocześnie zduplikowany w SAP (wystąpił również dla ST1210 na PB98).

---

## 4. Modyfikacja parametrów na żywo podczas obrony (Live-coding)

Wszystkie kluczowe reguły i parametry biznesowe są odseparowane od logiki kodu i znajdują się w pliku `config.yaml`. Umożliwia to błyskawiczną reakcję na polecenia komisji rekrutacyjnej:

### Scenariusz A: Zmiana progu tolerancji
W pliku `config.yaml` zmień sekcję `tolerance`:
```yaml
tolerance:
  abs_liters: 100.0      # Zmiana z 50.0 na 100.0 litrów
  rel_percent: 0.010     # Zmiana z 0.5% (0.005) na 1.0% (0.010)
```
Po zapisaniu pliku uruchom ponownie: `python main.py`.

### Scenariusz B: Dodanie nowego produktu do słownika
W sekcji `product_mapping` dodaj nowy synonim:
```yaml
product_mapping:
  "SUPER DIESEL": "ON"
  "BIO-ON": "ON"
```

### Scenariusz C: Wyłączenie automatycznego łączenia przesunięć nocnych (D+1)
```yaml
business_rules:
  enable_date_shift_matching: false
```
Po wyłączeniu dostawa 24 000 l LPG pojawi się jako osobny brak w SAP na dzień 25.08 oraz nadmiar w SAP na dzień 26.08.

---

## 5. Dokumentacja uzupełniająca

Szczegółowe opracowania znajdują się w katalogu `dokumentacja/`:
- [`decyzje_architektoniczne.md`](file:///c:/Users/kbcha/Desktop/zadanie%20orlen%20praca/dokumentacja/decyzje_architektoniczne.md) – Założenia, architektura, kompromisy, wersja produkcyjna E2E i 3 główne ryzyka awarii.
- [`przeglad_power_automate.md`](file:///c:/Users/kbcha/Desktop/zadanie%20orlen%20praca/dokumentacja/przeglad_power_automate.md) – Ekspercki przegląd i audyt bezpieczeństwa flow Power Automate (Część B).
- [`przygotowanie_do_obrony.md`](file:///c:/Users/kbcha/Desktop/zadanie%20orlen%20praca/dokumentacja/przygotowanie_do_obrony.md) – Notatki kandydata, skrypt wypowiedzi, gotowe odpowiedzi na trudne pytania i schemat wywiadu z biznesem.
