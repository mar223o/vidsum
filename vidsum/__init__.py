"""Vidsumly — lokalna analiza filmów (mowa + obraz) z oznaczaniem źródła każdej informacji."""

__version__ = "0.13.1"

# Etykiety źródeł używane w całym programie (stałe — część formatu JSON).
SRC_SPEECH = "mowa"
SRC_VISION = "obraz"
SRC_ESTIMATE = "szacunek"
SRC_NONE = "brak_danych"

# nazwa widoczna dla użytkownika (0.10.0). Nazwy techniczne — pakiet, foldery, AppId, pliki wydań — zostają „vidsum”/„Vidsumly”,
# żeby istniejące instalacje, analizy i aktualizacje działały bez zmian.
BRAND = "Vidsumly"
