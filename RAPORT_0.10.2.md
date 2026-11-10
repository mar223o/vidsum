# Vidsumly 0.10.2: przygotowanie pod „jeden model do wszystkiego”

## Zmiana
Gdy w ustawieniach **Model obrazu** wpiszesz ten sam model co tekstowy (np. `gemma3:4b`):
- opis kadrów używa tego samego kontekstu co tekst (8192), więc Ollama nie przeładowuje modelu między kadrami,
  podglądem i streszczeniem (przy różnym `num_ctx` przeładowuje);
- szybki podgląd włącza się sam (od 0.10.0, bo nie kosztuje przerzucania modeli).

Przy domyślnych modelach (`qwen3-vl:4b-instruct` do obrazu) nic się nie zmienia.

Gemma 3 w wersji 4B przyjmuje obrazy ([Hugging Face, ogłoszenie Gemma 3](https://huggingface.co/blog/gemma3)).

## Testy
- Kadry na innym modelu: kontekst 3072. Na tym samym co tekst: 8192, i jest wstępne streszczenie (atrapa Ollamy).
- Cała reszta: 120 testów przechodzi (2 pominięte, tylko Windows).

## Czego nie przetestowałem
- **Czasu i jakości opisu kadrów na gemma3:4b na Twojej karcie.** Tu nie mam karty ani Ollamy. Większy kontekst
  (8192 zamiast 3072) może trochę spowolnić pojedynczy kadr. Zysk ma przyjść z braku przerzucania modeli i z darmowego
  podglądu. Nie wiem, co przeważy, dopóki tego nie zmierzysz.
