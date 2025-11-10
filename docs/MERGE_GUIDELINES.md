# Wytyczne dotyczące łączenia gałęzi (Merge Guidelines)

## Przegląd

Ten dokument opisuje proces sprawdzania konfliktów przed połączeniem gałęzi w projekcie LegalSync.

## Automatyczne sprawdzanie przy Pull Request

Gdy tworzysz Pull Request do gałęzi `main`, automatycznie uruchamiają się następujące sprawdzenia:

### 1. Sprawdzanie konfliktów merge
- System automatycznie sprawdza, czy istnieją konflikty między Twoją gałęzią a `main`
- Jeśli zostaną wykryte konflikty, otrzymasz powiadomienie w PR
- PR nie może zostać połączony, dopóki konflikty nie zostaną rozwiązane

### 2. Sprawdzanie kompatybilności kodu
- Weryfikacja składni Python
- Sprawdzanie podstawowych błędów lintingu
- Wykrywanie potencjalnie konfliktowych definicji funkcji/klas

### 3. Podsumowanie gotowości do merge
- Zbiera wyniki wszystkich sprawdzeń
- Dostarcza czytelne podsumowanie stanu PR

## Ręczne sprawdzanie przed push

Możesz uruchomić skrypt sprawdzający lokalnie przed wysłaniem zmian:

```bash
# Sprawdź merge z gałęzią main (domyślnie)
./scripts/check-merge.sh

# Sprawdź merge z inną gałęzią
./scripts/check-merge.sh nazwa-galezi
```

### Co sprawdza skrypt?

1. **Niezatwierdzone zmiany** - Ostrzega jeśli masz niezatwierdzone zmiany
2. **Konflikty merge** - Używa `git merge-tree` do wykrycia konfliktów bez modyfikowania repozytorium
3. **Kompatybilność kodu** - Sprawdza składnię Python w zmienionych plikach
4. **Konflikty funkcjonalne** - Identyfikuje pliki zmodyfikowane w obu gałęziach

## Rozwiązywanie konfliktów

Jeśli zostaną wykryte konflikty:

### Krok 1: Zaktualizuj swoją gałąź
```bash
git fetch origin main
git merge origin/main
```

### Krok 2: Rozwiąż konflikty
- Otwórz pliki z konfliktami
- Znajdź markery konfliktów (`<<<<<<<`, `=======`, `>>>>>>>`)
- Ręcznie wybierz lub połącz zmiany
- Usuń markery konfliktów

### Krok 3: Zatwierdź rozwiązanie
```bash
git add .
git commit -m "Rozwiązanie konfliktów merge z main"
```

### Krok 4: Sprawdź ponownie
```bash
./scripts/check-merge.sh
```

## Najlepsze praktyki

### ✅ Zalecane

- **Synchronizuj regularnie**: Często aktualizuj swoją gałąź z `main`
- **Małe PR-y**: Twórz mniejsze, skoncentrowane Pull Requesty
- **Uruchom sprawdzenie przed push**: Użyj skryptu `check-merge.sh` przed wysłaniem zmian
- **Przejrzyj zmiany**: Sprawdź pliki zmodyfikowane w obu gałęziach
- **Testuj po merge**: Zawsze testuj swoją funkcjonalność po rozwiązaniu konfliktów

### ❌ Unikaj

- **Długo żyjących gałęzi**: Nie trzymaj gałęzi otwartych zbyt długo
- **Wymuszania push**: Nigdy nie używaj `git push --force` na współdzielonych gałęziach
- **Ignorowania ostrzeżeń**: Zawsze badaj ostrzeżenia o konfliktach
- **Łączenia bez sprawdzenia**: Nie łącz bez uruchomienia sprawdzeń

## Przebieg pracy

```
1. Stwórz gałąź feature
   ↓
2. Dokonaj zmian i zatwierdź
   ↓
3. Uruchom ./scripts/check-merge.sh
   ↓
4. Rozwiąż konflikty jeśli występują
   ↓
5. Wyślij i stwórz Pull Request
   ↓
6. Zaczekaj na automatyczne sprawdzenia CI
   ↓
7. Połącz po zatwierdzeniu
```

## Rozwiązywanie problemów

### Problem: "Target branch 'main' does not exist"
**Rozwiązanie**: Upewnij się, że masz lokalną kopię gałęzi main:
```bash
git fetch origin main:main
```

### Problem: "You have uncommitted changes"
**Rozwiązanie**: Zatwierdź lub schowaj swoje zmiany:
```bash
git stash
./scripts/check-merge.sh
git stash pop
```

### Problem: GitHub Actions nie uruchamia się
**Rozwiązanie**: Upewnij się, że:
- Workflow znajduje się w `.github/workflows/`
- Tworzysz PR do gałęzi `main`
- Repozytorium ma włączone GitHub Actions

## Wsparcie

W przypadku pytań lub problemów:
1. Sprawdź dokumentację Git
2. Przejrzyj logi GitHub Actions
3. Skontaktuj się z zespołem
