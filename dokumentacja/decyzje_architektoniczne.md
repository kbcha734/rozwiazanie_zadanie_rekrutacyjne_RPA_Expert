# Dokument Decyzji Architektonicznych i Biznesowych (Część A)
**Proces:** Codzienne uzgadnianie dostaw paliw (Kontroling Sieci Stacji Paliw)  
**Autor:** Kandydat na stanowisko Eksperta ds. automatyzacji procesów (Power Automate, UiPath)  
**Wymiar dokumentu:** Maksymalnie 2 strony zwięzłej syntezy techniczno-biznesowej  

---

## 1. Założenia i Kontekst Biznesowy

Dział Kontrolingu Sieci odpowiada za integralność bilansu paliwowego tysięcy stacji benzynowych. Każda nieuzgodniona autocysterna to ryzyko strat finansowych, nieprawidłowości w podatku akcyzowym i opłacie paliwowej oraz błędów w rozliczeniach z przewoźnikami (SLA logistyki).
- **Źródła danych:** Niezależne systemy o różnej dojrzałości technologicznej – rozproszone systemy kasowe/zbiornikowe stacji (POS/ATG, eksport CSV w standardzie Windows-1250 z polskimi znakami) oraz centralny system ERP SAP S/4HANA (moduły MM/SD, eksport UTF-8).
- **Kluczowa zasada ilościowa:** Uzgodnieniu podlega **ilość rzeczywista w temperaturze otoczenia**, a nie ilość standaryzowana w 15°C. Stacja przyjmuje paliwo fizycznie do podziemnego zbiornika w aktualnej temperaturze dostawy (pomiar objętościowy).
- **Zasada dynamicznej tolerancji:** Próg zgodności wynosi $\max(50\text{ litrów}, 0.5\%\text{ dostawy})$. Uwzględnia on błędy kalibracji przepływomierzy autocysterny i sond stacyjnych (dla małych dostaw 10 000 l próg to 50 l; dla dużych dostaw 30 000 l próg wynosi 150 l).

---

## 2. Budowa Rozwiązania i Dobór Narzędzi (Dlaczego Python, a nie RPA?)

Zgodnie z zasadą dojrzałości inżynierskiej: **„Automatyzacja procesowa (RPA) nie powinna zastępować silnika transformacji i czyszczenia danych (ETL)”**.
- **Wybór rdzenia analitycznego:** Do normalizacji, deduplikacji, wielowymiarowych agregacji i zaawansowanego łączenia zbiorów tabelarycznych wybrano **język Python (z konfiguracją zewnętrzną YAML)**. Bot RPA klikający w Excelu lub Power Automate Desktop iterujący po tysiącach wierszy byłby rozwiązaniem powolnym, podatnym na awarie interfejsu (COM/UI locks), trudnym do testowania jednostkowego i niemodyfikowalnym na żywo.
- **Rola RPA w procesie E2E:** Narzędzia RPA (UiPath / Power Automate) stanowią warstwę orkiestracji brzegowej:
  1. *UiPath / Power Automate:* Logowanie do SAP GUI / transakcji zrzutowej oraz pobranie plików z SFTP stacji do zabezpieczonego Data Lake / Blob Storage.
  2. *Python Engine (kontener / Azure Function):* Wykonanie deterministycznego, bezbłędnego uzgodnienia w ułamku sekundy.
  3. *Power Automate Cloud Flow:* Dystrybucja raportów Excel do analityków Kontrolingu, generowanie powiadomień w Microsoft Teams oraz tworzenie zadań wyjaśniających w Dataverse/Jira.

---

## 3. Najważniejsze Kompromisy Projektowe (Trade-offs)

1. **Wielodokumentowość (Sumowanie 1-do-N vs Parowanie 1-do-1):**
   - *Decyzja:* Przyjęto sumowanie dokumentów SAP per unikalny klucz `(Stacja, Doba, Produkt)`.
   - *Kompromis:* Jeśli stacja przyjmie 12 000 l, a w SAP są dwie dostawy po 7 200 l i 4 800 l (np. dwie komory autocysterny lub zamówienia dzielone), sumarycznie bilans jest idealny. Tracimy informację o numerze pojedynczego listu przewozowego, ale zachowujemy 100% spójności bilansu dobowego.
2. **Przesunięcia Nocne D+1 (Auto-przypisanie vs Zgłoszenie błędu):**
   - *Decyzja:* Silnik automatycznie wiąże dostawę stacji z dnia $D$ z dokumentem SAP z dnia $D+1$, ale **nie oznacza jej jako pełna zgodność**, lecz kwalifikuje do dedykowanej kategorii: `WYJATEK_PRZESUNIECIE_DATY`.
   - *Kompromis:* Analityk widzi, że wolumen się zgadza i nie musi tracić czasu na szukanie brakującej cysterny, ale kontroling ma formalny ślad opóźnionego księgowania w SAP.
3. **Korelacja Incydentów Międzystacyjnych (Podejrzenie błędnego zakładu):**
   - *Decyzja:* Zaimplementowano regułę łączącą brakującą dostawę na stacji $A$ z nadmiarowym dokumentem w zakładzie $B$ w tej samej dobie, przy identycznym produkcie i wolumenie.
   - *Kompromis:* Heurystyka ta doskonale identyfikuje błędy ludzkie dyspozytorów baz paliwowych, wymagając jednak ostatecznej autoryzacji człowieka przed wykonaniem przeksięgowania w SAP.

---

## 4. Wersja Produkcyjna (End-to-End Target Architecture)

W środowisku produkcyjnym przedsiębiorstwa naftowego rozwiązanie powinno funkcjonować w pełni autonomicznie w architekturze chmurowej/hybrydowej:

```
[Systemy POS Stacji] ---> (SFTP Dobowy) --\
                                          +--> [Azure Function / Python Engine] ---> [Dataverse / Synapse]
[SAP S/4HANA (RFC)] ---> (Azure Data Factory) -/          | (config.yaml w Key Vault)               |
                                                         v                                         v
                                              [Wielozakładkowy XLSX]                  [Power Automate Cloud Flow]
                                              [Archiwum Immutable GCS]                            |
                                                                                    +--------------+--------------+
                                                                                    v                             v
                                                                             [Kanał MS Teams]             [Powiadomienia Mail]
                                                                             (Alerty o wyjątkach)         (Raport do Kontrolingu)
```

1. **Wyzwalanie i Kompletność:** Proces odpala się codziennie o godz. 04:00 (po zamknięciu doby stacyjnej i spływie księgowań nocnych w SAP). Skrypt sprawdza tzw. *Heartbeat* stacji (kompletność plików ze wszystkich aktywnych stacji z listy master data). Brak pliku natychmiast generuje alert techniczny o braku transmisji z danej stacji.
2. **Walidacja Schematu (Schema Validation):** Przed processingiem następuje rygorystyczna kontrola nagłówków, typów danych oraz sumy kontrolnej SHA-256 plików wejściowych.
3. **Monitoring i Idempotencja:** Każdy przebieg otrzymuje unikalny identyfikator procesu (`Execution_Run_ID`). Ponowne uruchomienie dla tej samej doby (re-processing po korektach) zastępuje poprzedni wynik, zachowując pełną historię wersji w hurtowni danych.
4. **Archiwizacja i Audyt:** Wyniki uzgodnień oraz surowe pliki źródłowe trafiają do magazynu o polityce WORM (Write Once, Read Many) z retencją 5 lat na potrzeby kontroli skarbowej i audytu celnego.
5. **Własność (Ownership):**
   - *Właściciel Biznesowy (BPO):* Dyrektor Kontrolingu Sieci Stacji Paliw (odbiera raport i zatwierdza wyjątki).
   - *Właściciel Techniczny:* Zespół Centrum Doskonałości Automatyzacji i Danych (utrzymanie kodu, integracji i infrastruktury).

---

## 5. Trzy Najbardziej Prawdopodobne Sposoby Awarii na Produkcji i Środki Zaradcze

| # | Ryzyko Produkcyjne (Failure Mode) | Realny Skutek | Architektoniczny Środek Zaradczy |
| :-: | :--- | :--- | :--- |
| **1** | **Nieanonsowana zmiana formatu pliku lub kodowania znaków** (np. aktualizacja POS stacji zmieniająca separator na przecinek lub kodowanie na UTF-8). | Błąd parsowania, odrzucenie pliku, zatrzymanie procesu uzgadniania. | Moduł `data_loader.py` posiada mechanizm **auto-detekcji kodowania (BOM/CP1250/UTF-8) i separatorów (Sniffer)**. Dodatkowo bramka walidacji schematu zgłasza precyzyjny alert IT przed rozpoczęciem uzgadniania. |
| **2** | **Przesunięcia datowe w okresach świątecznych/weekendowych > 1 doba** lub zlewki wielokomorowe realizowane w ratach. | Oznaczenie dostawy jako „Brak w SAP” w piątek i „Nadmiar w SAP” w poniedziałek. | Parametryzacja okna przesunięcia w `config.yaml` (`date_shift_max_days: 3` w weekendy) lub wprowadzenie mechanizmu *Pending Deliveries Buffer* (uzgadnianie w kroczącym oknie 3-dniowym). |
| **3** | **Awaria transmisji danych z grupy stacji (np. blackout/awaria łącza)** przy jednoczesnym zaksięgowaniu dostaw w SAP. | Pozorny alarm o masowych brakach dostaw na stacjach, fałszywe powiadomienia do kierowników. | Weryfikacja kompletności transmisji stacyjnej przed uruchomieniem silnika. Jeśli brak raportu z $>5\%$ stacji, proces wstrzymuje generowanie raportu biznesowego i podnosi incydent infrastrukturalny P2. |
