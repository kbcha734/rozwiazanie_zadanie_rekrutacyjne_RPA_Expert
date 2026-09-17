# Raport z Przeglądu Przepływu Power Automate (Część B)
**Projekt:** Automatyzacja obsługi reklamacji punktów lojalnościowych  
**Rola:** Ekspert ds. automatyzacji procesów (Bramka Jakościowa / Release Gatekeeper)  
**Status Decyzji:** ⛔ **ODRZUCENIE WDROŻENIA PRODUKCYJNEGO (DEPLOYMENT REJECTED)**  

---

## 1. Werdykt i Ocena Całościowa

Przedstawiony przepływ w chmurze (Cloud Flow) stanowi **wczesny prototyp badawczy (Proof of Concept)**, a nie rozwiązanie gotowe do eksploatacji na środowisku produkcyjnym dużej organizacji.

Uruchomienie procesu w obecnym kształcie w przyszłym tygodniu stwarza **krytyczne ryzyko nadużyć finansowych (fraud)**, bezpośrednie naruszenie przepisów o ochronie danych osobowych (**RODO**), wysokie ryzyko wycieku poświadczeń produkcyjnych oraz paraliż operacyjny w przypadku błędnych danych wejściowych. Rozwiązanie musi zostać wstrzymane i poddane gruntownemu refaktoringowi.

---

## 2. Kategoryzacja Problemów według Modelu Ryzyka

### 🔴 Kategoria 1: Blokery Wdrożenia (Krytyczne / Critical)
*Wady uniemożliwiające uruchomienie produkcyjne pod jakimkolwiek warunkiem (ryzyko finansowe, prawne i bezpieczeństwa).*

1. **Brak jakiejkolwiek autoryzacji, limitu i walidacji punktów (Kroki 3, 9):**
   Liczba punktów jest pobierana wprost z treści e-maila klienta i dodawana bezpośrednio do salda w API. Klient może napisać: `"Liczba punktów: 1000000"` i bezobsługowo zasilić swoje konto punktami o realnej wartości gotówkowej.
2. **Brak odporności na powtórne wykonanie / Idempotencji (Krok 9):**
   W żądaniu `HTTP POST` brak identyfikatora zgłoszenia/transakcji (`Idempotency-Key` / `Ticket_ID`). Jeśli klient wyśle 5 identycznych maili lub kliknie „Wyślij ponownie”, system pięciokrotnie doliczy punkty za ten sam paragon.
3. **Hardkodowany klucz API `x-api-key` w akcji HTTP (Krok 4):**
   Klucz uwierzytelniający do produkcyjnego API jest jawnie wpisany w definicję akcji przepływu. Jest widoczny dla każdego użytkownika z wglądem w przebiegi i nie podlega audytowi ani rotacji w Azure Key Vault.
4. **Ciężkie naruszenie RODO i bezpieczeństwa danych (Kroki 10, 11):**
   Skany paragonów (zawierające dane płatności, numery kart, adresy stacji, czasem dane NIP) są zapisywane w bibliotece SharePoint dostępnej dla wszystkich pracowników firmy. Dodatkowo dane osobowe klientów (imię, nazwisko, treść maila) są logowane do pliku Excel na prywatnym dysku OneDrive autora.
5. **Tożsamość i własność na koncie osobistym pracownika (Kroki 1, 7, 8, 11, 13):**
   Wyzwalacz podpięty pod skrzynkę prywatną pracownika, maile do klientów wysyłane z konta imiennego, pliki na prywatnym OneDrive, środowisko `Default` poza rozwiązaniem (`Solution`). Odejście pracownika lub zmiana hasła w Entra ID natychmiast uśmierca cały proces.

---

### 🟡 Kategoria 2: Wymagane do Poprawy Przed Produkcją (Wysokie / High)
*Błędy stabilności, logiki biznesowej i architektury wykonawczej.*

6. **Fałszywe potwierdzenie sukcesu (Krok 7 przed Krokiem 9):**
   E-mail do klienta z informacją *„Punkty zostały doliczone do Twojego konta”* jest wysyłany w kroku 7, **zanim** nastąpi wywołanie API doliczającego punkty w kroku 9! W przypadku błędu API (np. kod 500/timeout), klient ma pisemne potwierdzenie, a punktów na koncie nie ma.
7. **Brak obsługi błędów (Krok 12):**
   Brak bloków `Scope (Try-Catch-Finally)`. Tłumaczenie autora, że „zobaczy błąd w historii uruchomień”, jest niedopuszczalne w procesie finansowym. W przypadku awarii proces milcząco porzuca zgłoszenie.
8. **Niezwykle kruchy parsing tekstu funkcją `split()` (Kroki 2, 3):**
   Jakakolwiek literówka klienta (np. `"Nr karty :"`, `"Numer karty:"`, mail HTML z formatowaniem) spowoduje błąd wykonania `ActionFailed` i przerwanie przepływu.
9. **Niewydajna i blokująca pętla `Apply to each` z Excelem (Krok 8):**
   Pętla po transakcjach z 90 dni wykonuje zapytanie Dataverse i dopisuje wiersz do Excela w każdej iteracji. Przy domyślnej współbieżności spowoduje to natychmiastowe zablokowanie pliku (`File Locked / 423 Locked`) oraz przekroczenie limitów API Power Automate (Throttling).
10. **Schemat JSON wygenerowany z jednej próbki (Krok 5):**
    Brak uwzględnienia pól opcjonalnych (`null`) w schemacie `Parse JSON` wywoła błąd walidacji schematu przy innej strukturze odpowiedzi.
11. **Pozorne testy (Krok 14):**
    Wysłanie 3 poprawnych maili do samego siebie to weryfikacja tzw. „happy path”. Nie przetestowano żadnego przypadku negatywnego, błędnego formatu, duplikatu, braku załącznika ani próby nadużycia.

---

### 🟢 Kategoria 3: Dług Technologiczny / Może Poczekać (Średnie / Low)
*Usprawnienia ergonomii i standaryzacji w kolejnych sprintach.*

12. **Brak ustrukturyzowanego formularza wejściowego:**
    Zastąpienie wyzwalacza mailowego dedykowanym formularzem (Power Pages / Microsoft Forms) z walidacją numeru karty na poziomie wprowadzania.
13. **Nazewnictwo plików oparte o temat maila (Krok 10):**
    Tematy maili często zawierają znaki niedozwolone w SharePoint (`\ / : * ? " < > |`), co wywoła błędy zapisu.

---

## 3. Szczegółowa Analiza 3 Najpoważniejszych Problemów i Sposób Naprawy

### Problem 1: Brak weryfikacji kwoty, limitu i brak idempotencji (Ryzyko Oszustwa Finansowego)
- **Realny skutek produkcyjny:**
  Narażenie spółki na bezpośrednie straty finansowe. Po odkryciu podatności klienci mogą generować miliony punktów wymienialnych na paliwo i nagrody. Zautomatyzowany skrypt wysyłający 100 maili na minutę doprowadzi do niekontrolowanego drenażu budżetu programu lojalnościowego. Brak `Ticket_ID` w żądaniu POST uniemożliwia audyt i odwrócenie transakcji w bazie.
- **Konkretny sposób naprawy:**
  1. Wprowadzenie twardej reguły biznesowej w API/Dataverse: maksymalny limit punktów dodawanych automatycznie (np. do 200 pkt). Powyżej tego progu przepływ tworzy zadanie w **Power Automate Approvals** dla konsultanta BOK.
  2. Wyliczenie unikalnego hasha zgłoszenia (np. `sha256(NrKarty + DataTransakcji + KwotaParagonu)`).
  3. W żądaniu `HTTP POST` wymuszenie nagłówka idempotencji: `X-Idempotency-Key: @{variables('RequestHash')}`. Jeśli API otrzyma ten sam klucz w ciągu 30 dni, zwraca status `200 OK (Duplicate Ignored)` zamiast powtórnego naliczenia.

### Problem 2: Jawny klucz produkcyjny API `x-api-key` w definicji akcji (Złamanie Bezpieczeństwa)
- **Realny skutek produkcyjny:**
  Klucz jest zapisany czystym tekstem w definicji JSON przepływu. Dostęp do niego ma każdy pracownik posiadający uprawnienia do środowiska. W przypadku eksportu rozwiązania lub wycieku logów klucz trafia w niepowołane ręce. Unieważnienie klucza wymaga ręcznej edycji przepływu na produkcji.
- **Konkretny sposób naprawy:**
  1. Przeniesienie klucza API do **Azure Key Vault**.
  2. W Power Automate utworzenie zmiennej środowiskowej typu **Azure Key Vault Secret** lub użycie dedykowanego łącznika *Azure Key Vault Connector* z uwierzytelnianiem poprzez **Managed Identity / Service Principal**.
  3. W akcji HTTP włączenie flagi **Secure Inputs** i **Secure Outputs**, co uniemożliwia podgląd wartości klucza w historii uruchomień przepływu.

### Problem 3: Naruszenie RODO i brak retencji danych w SharePoint/OneDrive
- **Realny skutek produkcyjny:**
  Przechowywanie danych wrażliwych klientów w pliku Excel na prywatnym OneDrive i ogólnodostępnym SharePointcie stanowi bezpośrednie naruszenie art. 5 ust. 1 lit. f RODO (integralność i poufność) oraz art. 32 RODO (bezpieczeństwo przetwarzania). W przypadku kontroli UODO grożą milionowe kary finansowe. Ponadto usunięcie konta pracownika powoduje bezpowrotną utratę historii reklamacji.
- **Konkretny sposób naprawy:**
  1. Całkowite wyeliminowanie pliku Excel i prywatnego OneDrive z architektury procesu.
  2. Zapisywanie danych reklamacji wyłącznie do dedykowanej tabeli w **Microsoft Dataverse** (`cr_reklamacja_punktowa`) z precyzyjnie nadanymi rolami bezpieczeństwa (Security Roles – dostęp tylko dla BOK).
  3. Skany paragonów zapisywane do zabezpieczonej biblioteki SharePoint ze ściśle ograniczonym dostępem (lub jako załącznik do rekordu Dataverse) z nałożoną polityką retencji Microsoft Purview (automatyczne usuwanie po 90 dniach).

---

## 4. Elementy Pozytywne i Dobre Intencje w Rozwiązaniu Kolegi

Audyt nie może być wyłącznie krytyką – należy docenić wysiłek i kierunek myślenia młodszego inżyniera:
1. **Dążenie do pełnego End-to-End Self-Service:** Kolega trafnie zidentyfikował proces o wysokim wolumenie (reklamacje punktowe) i podjął próbę jego automatycznego zamknięcia bez angażowania człowieka w prostych sprawach.
2. **Wykorzystanie integracji hybrydowej:** Zamiast symulować klikanie w interfejsie użytkownika (RPA), połączył ze sobą nowoczesne komponenty: Power Automate, Microsoft Dataverse oraz REST API systemu lojalnościowego.
3. **Prawidłowe założenie o potrzebie weryfikacji klienta:** Krok 6 (`Get a row w Dataverse`) pokazuje, że autor rozumiał konieczność sprawdzenia tożsamości klienta w bazie CRM przed wykonaniem operacji.

---

## 5. Enterprise Standard Produkcyjny dla Przepływów Chmurowych (5-10 Zdań)

> 1. **Tożsamość i uprawnienia:** Przepływy produkcyjne muszą być wyzwalane ze skrzynek współdzielonych (Shared Mailbox), a wszystkie połączenia do API i baz danych muszą wykorzystywać jednostki usługi (Service Principal) z poświadczeniami pobieranymi w locie z Azure Key Vault z włączonym Secure Inputs/Outputs.  
> 2. **Zarządzanie środowiskami i wersjami (ALM):** Całość procesu musi być zamknięta w zarządzanym rozwiązaniu (Managed Solution) w dedykowanym środowisku produkcyjnym, wdrażanym automatycznie poprzez potoki CI/CD (Azure DevOps / GitHub Actions) z zachowaniem separacji Dev $\rightarrow$ Test $\rightarrow$ Prod.  
> 3. **Własność i ciągłość:** Właścicielem przepływów i obiektów Dataverse musi być bezimienne konto serwisowe (Service Account) z przypisaną licencją procesową (Power Automate Process License), co zapobiega przestojom po rotacji personelu.  
> 4. **Obsługa błędów i odporność (Resilience):** Przepływ musi implementować wzorzec Scope (Try $\rightarrow$ Catch $\rightarrow$ Finally) z konfiguracją „Run After”, a kluczowe operacje modyfikujące saldo muszą być zabezpieczone unikalnym kluczem idempotencji (Idempotency Key) uniemożliwiającym wielokrotne wykonanie.  
> 5. **Architektura operacji i komunikacji:** Powiadomienie klienta o sukcesie może nastąpić wyłącznie po pomyślnym zatwierdzeniu transakcji przez API, a operacje przekraczające limit bezpieczeństwa muszą trafiać do ścieżki akceptacji w Power Automate Approvals.  
> 6. **Baza danych i RODO:** Magazynem danych procesowych i logów musi być wyłącznie Microsoft Dataverse z restrykcyjnymi rolami bezpieczeństwa (Security Roles) i polityką retencji Purview, wykluczając pliki Excel i prywatne dyski OneDrive.  
> 7. **Monitoring i telemetria:** Logi wykonania muszą być przekazywane do Azure Application Insights / Log Analytics z automatycznymi alertami wysyłanymi na kanał dyżurny MS Teams w przypadku przekroczenia progu błędów.  
> 8. **Testy i walidacja:** Wdrożenie na produkcję wymaga przeprowadzenia pełnego zestawu testów akceptacyjnych (UAT), w tym testów negatywnych, prób wstrzyknięcia niepoprawnych danych, testów obciążeniowych oraz weryfikacji zgodności bezpieczeństwa (SecOps Sign-off).
