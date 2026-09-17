# Szczegółowy Opis Działania Silnika Uzgadniania i Wygenerowanych Raportów

Niniejszy dokument przedstawia kompleksową dokumentację techniczną i biznesową silnika uzgadniania dostaw paliw (**Fuel Delivery Reconciliation Engine**): architekturę przetwarzania danych krok po kroku, zastosowane reguły analityczne oraz dokładną specyfikację wygenerowanych plików raportowych.

---

## I. Architektura i Przepływ Danych (Pipeline Krok po Kroku)

Proces uruchamiany jest jednym poleceniem:
```bash
python main.py
```

Silnik realizuje deterministyczny, wieloetapowy potok przetwarzania danych (ETL/Reconciliation Pipeline):

```
┌────────────────────────────────┐         ┌────────────────────────────────┐
│   stacje_raport_dobowy.csv     │         │        sap_dostawy.csv         │
│  (System stacyjny POS/ATG)     │         │       (Centralny SAP ERP)      │
│   Kodowanie: CP1250, Sep: ';'  │         │   Kodowanie: UTF-8-BOM, Sep: ','│
└───────────────┬────────────────┘         └───────────────┬────────────────┘
                │                                          │
                ▼                                          ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 1. Data Loader (engine/data_loader.py)                                    │
│    - Automatyczna detekcja kodowania znaków (BOM, CP1250, UTF-8)          │
│    - Automatyczne rozpoznanie separatora kolumn (Sniffer: ';', ',')       │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 2. Normalizer (engine/normalizer.py)                                      │
│    - Kody stacji: usunięcie prefiksu 'ST', uzupełnienie do 4 cyfr (zfill) │
│    - Daty: unifikacja formatów (DD.MM.YYYY, YYYY/MM/DD) do ISO YYYY-MM-DD  │
│    - Produkty: mapowanie synonimów na kanoniczne kody z config.yaml       │
│    - Ilości: konwersja do float, usunięcie jednostek ('0,0 l'), przecinki │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 3. Data Quality Engine (engine/data_quality.py)                           │
│    - Wykrywanie i usuwanie technicznych duplikatów wierszy (wiersz 138)   │
│    - Detekcja anomalii: ujemna sprzedaż, awarie sond pomiarowych ('n/d')   │
│    - Weryfikacja unikalności numerów dokumentów w SAP (dok. 4500011399)   │
│    - Klasyfikacja sygnałów DQ: KRYTYCZNY / OSTRZEŻENIE / INFORMACYJNY     │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 4. Fuel Reconciler (engine/reconciler.py) - Wieloetapowe Uzgadnianie      │
│    - Etap 1: Bezpośrednie dopasowanie w tej samej dobie (tolerancja)     │
│              oraz agregacja wielodokumentowa SAP (sumowanie 1-do-N)       │
│    - Etap 2: Wykrywanie przesunięć nocnych po północy (Doba D vs SAP D+1) │
│    - Etap 3: Dopasowanie uwolnionych rekordów D+1 po wydzieleniu nocy     │
│    - Etap 4: Identyfikacja przyjęć fizycznych przy dokumencie STO w SAP   │
│    - Etap 5: Korelacja incydentów krzyżowych (pomyłka zakładu w SAP A!=B) │
│    - Etap 6: Rejestracja dostaw widmo w SAP i braków na stacjach          │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 5. Report Generator (engine/reporter.py)                                  │
│    - Eksport sformatowanego Excela (.xlsx) z 5 dedykowanymi zakładkami    │
│    - Eksport tabelarycznych plików CSV do integracji procesowej           │
│    - Eksport pełnej struktury JSON dla API / Power Automate               │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## II. Szczegółowy Opis Modułów Silnika

### 1. Moduł `engine/data_loader.py` (Odczyt i detekcja formatu)
* **Zadanie:** Rozwiązanie problemu niespójnych stron kodowych i separatorów w plikach z różnych systemów źródłowych.
* **Mechanizm działania:**
  1. Analizuje nagłówek i pierwsze bajty pliku, testując kandydatów kodowań: `utf-8-sig`, `cp1250`, `utf-8`, `iso-8859-2`.
  2. Zlicza wystąpienia znaków `;`, `,`, `\t` w pierwszym wierszu, precyzyjnie określając separator.
  3. Zwraca oczyszczoną listę wierszy z zachowaniem oryginalnego numeru wiersza pliku źródłowego (`__source_row__`) na potrzeby audytu.

### 2. Moduł `engine/normalizer.py` (Standaryzacja danych)
* **Zadanie:** Sprowadzenie danych do jednolitej postaci uniemożliwiającej fałszywe rozbieżności.
* **Mechanizm działania:**
  - **Kody stacji:** Niezależnie czy na wejściu jest `'ST0412'`, `'0412'`, czy `'417'`, moduł usuwa prefiks `'ST'` i dopełnia kod zerami do 4 cyfr (`zfill(4)`), dając kanoniczne `'0412'` lub `'0417'`.
  - **Daty:** Niezależnie czy data zapisana jest jako `'24.08.2026'`, `'2026/08/24'` czy `'2026-08-24'`, zostaje skonwertowana do formatu ISO `'2026-08-24'`.
  - **Słownik produktów:** Na podstawie sekcji `product_mapping` w `config.yaml` mapuje dowolny synonim (`'Pb 95'`, `'Benzyna bezołowiowa 95'`) na kanoniczny kod produktu (`'PB95'`).
  - **Wartości ilościowe:** Czyści zapisy z dopiskami jednostek (`'0,0 l'`), spacjami i zamienia przecinki dziesiętne na kropki, konwertując wartości do typu `float`.

### 3. Moduł `engine/data_quality.py` (Audyt jakości danych wejściowych)
* **Zadanie:** Ochrona silnika przed zafałszowaniem wyników przez błędy techniczne w plikach i precyzyjne oddzielenie błędów danych od problemów biznesowych.
* **Mechanizm działania:**
  - **Deduplikacja wierszy:** Wykrywa wiersz 138 na stacji 0412 (jest dokładną, powtórzoną kopią wiersza 5 na 10 000 l PB98). Generuje sygnał DQ o duplikacie i usuwa go z dalszego uzgadniania, dzięki czemu stacja idealnie bilansuje się z SAP.
  - **Weryfikacja fizycznego bilansu zbiornika:** Sprawdza równanie:
    $$\text{Stan początkowy} + \text{Dostawa} - \text{Sprzedaż} = \text{Stan końcowy}$$
    Dzięki temu natychmiast wykrywa anomalię w wierszu 139 na stacji 0745 z ujemną sprzedażą (`-312,40 l`).
  - **Wykrywanie awarii sond:** Zgłasza 4 rekordy z wartością `'n/d'` w stanie końcowym zbiornika (potencjalna usterka sondy pomiarowej ATG).
  - **Weryfikacja unikalności w SAP:** Wykrywa zduplikowany numer dokumentu dostawy `4500011399` przypisany do dwóch różnych stacji (1210 i 1402).

### 4. Moduł `engine/reconciler.py` (Silnik reguł biznesowych)
* **Zadanie:** Przeprowadzenie właściwego uzgodnienia według ścisłych reguł kontrolingowych.
* **Mechanizm działania:**
  - **Dynamiczna tolerancja:** Wylicza dopuszczalne odchylenie zgodnie ze wzorem:
    $$\text{Tolerancja} = \max(50.0\text{ litrów}, 0.005 \times \text{Wolumen dostawy})$$
  - **Agregacja wielodokumentowa (1-do-N):** Sumuje dokumenty SAP dla tego samego klucza `(Stacja, Doba, Produkt)`. Przykład: stacja 0412 przyjęła 12 000 l PB95, a w SAP zaksięgowano dwa dokumenty (7 200 l + 4 800 l) – silnik łączy je i raportuje pełną zgodność.
  - **Obsługa przesunięć nocnych (D+1):** Weryfikuje dostawy zrealizowane po północy. Dostawa 24 000 l LPG przyjęta na stacji 0417 w dniu 25.08 i zaksięgowana w SAP 26.08 zostaje połączona i oznaczona dedykowaną kategorią `WYJATEK_PRZESUNIECIE_DATY`.
  - **Uwolnienie pozostałych rekordów:** Po wydzieleniu przesunięcia nocnego pozostała dostawa 24 000 l LPG z dnia 26.08 paruje się z drugim dokumentem w SAP jako pełna zgodność `ZGODNE`.
  - **Obsługa statusu STO:** Wykrywa sytuację, w której stacja raportuje fizyczny zlew paliwa (stacja 0412, PB98, 12 000 l w dniu 26.08), ale powiązany dokument SAP `4500011249` ma status `STO` (storno).
  - **Korelacja incydentów krzyżowych (Błędny zakład w SAP):** Silnik łączy brakujący dokument na stacji 0417 (15 000 l LPG w dniu 24.08) z nadmiarowym dokumentem SAP zaksięgowanym w tej samej dobie na zakład ST0523 (15 000 l LPG), gdzie stacja 0523 nie odnotowała żadnej dostawy.

### 5. Moduł `engine/reporter.py` (Generowanie raportów)
* **Zadanie:** Przygotowanie estetycznych, czytelnych i gotowych do audytu zestawień w formatach Excel (.xlsx), CSV i JSON.

---

## III. Co Dokładnie Generuje Silnik (Pliki Wynikowe)

Wszystkie rezultaty pracy silnika zapisywane są automatycznie w katalogu **`output/`**:

```
output/
├── wynik_uzgodnienia.xlsx      # Główny, sformatowany arkusz analityczny Excel (5 zakładek)
├── uzgodnienie_podsumowanie.csv # Wskaźniki KPI w formacie tabelarycznym CSV
├── uzgodnienie_wyjatki.csv      # Lista wyjątków biznesowych do wyjaśnienia przez Kontroling
├── raport_jakosc_danych.csv     # Raport sygnałów jakości danych dla zespołów IT i POS
└── wynik_uzgodnienia.json       # Kompletna struktura danych JSON dla API / Power Automate
```

---

### 1. Arkusz Excel: `output/wynik_uzgodnienia.xlsx`

Arkusz został sformatowany z użyciem stylów korporacyjnych (granatowe nagłówki `#1A365D`, biały tekst, obramowania, formatowanie liczb `#,##0.0` oraz auto-dopasowanie szerokości kolumn). Składa się z **5 wyspecjalizowanych zakładek**:

#### 📄 Zakładka 1: `Podsumowanie` (Executive KPI Dashboard)
Zawiera kartę wyników dla Dyrekcji Kontrolingu:
* Łączna liczba wierszy wejściowych stacji (138) i dokumentów SAP (49).
* Liczba dostaw w 100% zgodnych: **44**.
* Liczba wyjątków biznesowych do wyjaśnienia: **4**.
* Liczba powiązanych incydentów: **1**.
* Liczba sygnałów jakości danych: **21**.
* Wolumen paliwa zgłoszony przez stacje: **861 000,0 l**.
* Wolumen aktywnych dokumentów w SAP: **867 000,0 l**.
* Wolumen uzgodniony w pełnej zgodności: **810 000,0 l**.
* **Wskaźnik bezpośredniej zgodności wolumenu: 94.1%**.

#### 📄 Zakładka 2: `Zgodne` (Kolor zielony)
Tabela 44 dostaw, które zostały w pełni uzgodnione w ramach dopuszczalnej tolerancji.
* **Kolumny:** Klucz Biznesowy, Stacja, Doba, Produkt, Ilość Stacja [l], Ilość SAP [l], Różnica [l], Tolerancja [l], Status (`ZGODNE`), Kategoria, Liczba Dok. SAP, Numery Dok. SAP, Uwagi / Agregacja.
* **Wartość analityczna:** Pokazuje analitykowi czarno na białym, które dostawy nie wymagają żadnej pracy ludzkiej oraz gdzie nastąpiło automatyczne zsumowanie wielu dokumentów SAP (np. 7200 + 4800 = 12000 l).

#### 📄 Zakładka 3: `Wyjątki_Biznesowe` (Kolory żółty i czerwony)
Kluczowa zakładka operacyjna dla kontrolera sieci. Zawiera dokładnie 4 przypadki wymagające podjęcia decyzji:
1. **`0412|2026-08-26|PB98` – Przyjęcie na stacji przy dokumencie STO w SAP:**
   * Stacja zaraportowała przyjęcie 12 000 l, w SAP dokument `4500011249` (12 000 l) ma status STO.
   * *Akcja:* Wyjaśnienie z bazą paliwową, czy storno było błędem dyspozytora, czy cysternę wycofano.
2. **`0417|2026-08-25|LPG` – Przesunięcie daty (Doba stacji 25.08 vs Księgowanie SAP 26.08 D+1):**
   * Stacja przyjęła 24 000 l przed północą, w SAP zaksięgowano po północy (dok. `4500011269`).
   * *Akcja:* Standardowa akceptacja kontrolingowa przesunięcia nocnego.
3. **`0417|2026-08-24|LPG` – Podejrzenie błędnego zakładu w SAP (Korelacja incydentu):**
   * Stacja 0417 przyjęła 15 000 l bez SAP, w SAP wisi 15 000 l na zakład ST0523 bez stacji.
   * *Akcja:* Przeksięgowanie storno w SAP z zakładu ST0523 na właściwy ST0417.
4. **`1402|2026-08-26|ON` – Dostawa widmo w SAP:**
   * Dokument SAP `4500011399` na 18 000 l dla zakładu ST1402, stacja nie potwierdziła odbioru paliwa (dodatkowo ten sam numer dokumentu wystąpił dla stacji 1210).
   * *Akcja:* Pilna weryfikacja fizycznego losu cysterny i zgłoszenie błędu numeracji do wsparcia SAP FI/MM.

#### 📄 Zakładka 4: `Jakość_Danych`
Rejestr 21 technicznych anomalii wejściowych:
* Ucięte wiodące zera w kodach stacji (`'417'`, `'523'`, `'701'`, `'745'`).
* Niestandardowe formaty dat (`24.08.2026`).
* Identyczny powtórzony wiersz 138 na stacji 0412.
* Wiersz 139 z ujemną sprzedażą (`-312,40 l`).
* 4 awarie sond pomiarowych zbiornika (brak odczytu `'n/d'`).
* Zduplikowany numer dokumentu w SAP.
* *Wartość:* Każdy wpis zawiera ocenę ryzyka (`KRYTYCZNY`, `OSTRZEŻENIE`, `INFORMACYJNY`) oraz gotową rekomendację dla zespołów IT/POS.

#### 📄 Zakładka 5: `Incydenty_Powiązane`
Szczegółowa karta incydentu międzystacyjnego dla stacji 0417 i zakładu SAP ST0523 z dokładnym uzasadnieniem korelacji (ta sama doba 2026-08-24, ten sam produkt LPG, identyczna ilość 15 000 l) wraz z instrukcją naprawczą w SAP.

---

### 2. Pliki CSV i JSON (Gotowe do Integracji)

1. **`output/uzgodnienie_podsumowanie.csv`:**
   * Zawiera wszystkie metryki liczbowe procesu w jednym wierszu CSV (idealne do zasilenia kokpitu Power BI).
2. **`output/uzgodnienie_wyjatki.csv`:**
   * Czyste zestawienie 4 wyjątków biznesowych rozdzielane średnikami. Może być bezpośrednio zaczytane przez Power Automate w celu utworzenia zadań w Microsoft Planner / Jira / Dataverse.
3. **`output/raport_jakosc_danych.csv`:**
   * Zestawienie anomalii technicznych przekazywane do zespołu wsparcia technicznego stacji.
4. **`output/wynik_uzgodnienia.json`:**
   * Kompletny zrzut wyników w formacie JSON zawierający sekcje: `metadata`, `statistics`, `matched`, `exceptions`, `incidents`, `data_quality_signals`. Gotowy do wystawienia przez mikroserwis REST API.

---

## IV. Zestawienie Bilansowe (Pewność Danych)

Uruchomienie silnika daje w 100% spójny, zamknięty matematycznie bilans:

| Kategoria uzgodnienia | Liczba zdarzeń | Wolumen fizyczny stacji | Wolumen dokumentów SAP |
| :--- | :---: | :---: | :---: |
| **Dostawy Zgodne (w tolerancji)** | 44 | 810 000,0 l | 810 000,0 l |
| **Przesunięcie nocne D+1** | 1 | 24 000,0 l | 24 000,0 l |
| **Incydent błędnego zakładu w SAP** | 1 | 15 000,0 l | 15 000,0 l |
| **Dostawa ze statusem STO** | 1 | 12 000,0 l | 0,0 l *(aktywne)* |
| **Dostawa widmo w SAP** | 1 | 0,0 l | 18 000,0 l |
| **SUMA BILANSOWA** | **48 pozycji** | **861 000,0 l** | **867 000,0 l** |

Różnica sumaryczna wynosi dokładnie $6\ 000\text{ l}$ ($867\ 000 - 861\ 000$), co wynika precyzyjnie z różnicy między dostawą widmo w SAP ($+18\ 000\text{ l}$) a dostawą przyjętą na stacji z anulowanym dokumentem STO ($-12\ 000\text{ l}$):
$$+18\ 000\text{ l} - 12\ 000\text{ l} = +6\ 000\text{ l}$$
Żaden litr paliwa i żaden wiersz nie został pominięty ani „zgubiony”.

---

## V. Szybka Zmiana Parametrów na Żywo (`config.yaml`)

Wszystkie parametry biznesowe można zmienić w locie podczas spotkania rekrutacyjnego w pliku `config.yaml`:
* **Zmiana progu tolerancji:** Zmiana `abs_liters: 50.0` na `100.0` lub `rel_percent: 0.005` na `0.010`.
* **Dodanie nowego paliwa:** Dopasowanie nowego synonimu w sekcji `product_mapping`.
* **Wyłączenie łączenia D+1:** Przestawienie flagi `enable_date_shift_matching: false`.

Po modyfikacji wystarczy wcisnąć `Ctrl+S` i wpisać w konsoli:
```bash
python main.py
```
Całość przelicza się w ułamku sekundy, a raport Excel natychmiast odzwierciedla nowe reguły.
