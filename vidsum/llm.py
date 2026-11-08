"""Modele: Ollama (lokalnie, obraz + tekst) oraz Claude Code (`claude -p`, subskrypcja Pro)."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from .tools import run

VISION_PROMPT = """Opisz WYŁĄCZNIE to, co widać na tym jednym kadrze z filmu (czas {t}). Nie zgaduj treści filmu.
Pisz tylko po polsku, wyłącznie alfabetem łacińskim (bez znaków chińskich ani innych pism).
Odpowiedz jako JSON z kluczami:
"scena": krótki opis (1 zdanie),
"czynnosci": lista czynności widocznych w kadrze, szczególnie rąk (np. krojenie, obieranie, mieszanie, wlewanie, smażenie, podnoszenie ciężaru),
"obiekty": lista widocznych składników, narzędzi, sprzętu,
"tekst_na_ekranie": TYLKO napisy dodane do filmu przez autora (podpisy, nazwy kroków, ilości) — przepisane dokładnie,
"napisy_na_przedmiotach": napisy wydrukowane na sprzęcie, opakowaniach, etykietach (osobno, nie mieszaj z poprzednim),
"cialo": ustawienie ciała / pozycja / zakres ruchu, jeśli widać osobę ćwiczącą (inaczej pusty string),
"pewnosc": "wysoka" | "srednia" | "niska".
Zasady: nazwij przedmiot konkretnie tylko, gdy jest wyraźnie widoczny (nóż to nie nożyce, ziemniak to nie ciasto);
gdy nie masz pewności, użyj nazwy ogólnej (np. „narzędzie kuchenne”, „produkt”) i ustaw "pewnosc" na "niska".
Jeśli czegoś nie da się rozpoznać, zostaw pustą listę zamiast zgadywać.
Krótko: "scena" do 15 słów, najwyżej 6 "obiekty" i 4 "czynnosci" (szybkość — kadrów jest wiele)."""

# kontekst modelu obrazu: kadr (≤512 px szerokości ≈ 450 tokenów) + polecenie + odpowiedź ≈ 1,5 tys. tokenów.
# Stała wartość (ta sama przy wczytaniu i przy kadrach — inaczej Ollama przeładowuje model) i mniejsza niż domyślna:
# przy kilku zapytaniach naraz zostaje miejsce na karcie dla Whispera, który liczy w tym czasie poprawkę mowy.
VISION_CTX = 3072
TEXT_CTX = 8192

# Schemat JSON odpowiedzi o kadrze (limit długości list). Pomiar na komputerze testowym (--pomiar-kadrow, RTX 3070 Ti, 20 kadrów):
# 29,7 s zamiast 40,4 s przy tej samej liczbie tokenów; opisy w 89% słów takie same (17/20 kadrów praktycznie identyczne).
_ARR = lambda n: {"type": "array", "items": {"type": "string"}, "maxItems": n}  # noqa: E731
FRAME_SCHEMA = {"type": "object", "properties": {
    "scena": {"type": "string"}, "czynnosci": _ARR(4), "obiekty": _ARR(6), "tekst_na_ekranie": _ARR(4),
    "napisy_na_przedmiotach": _ARR(3), "cialo": {"type": "string"},
    "pewnosc": {"type": "string", "enum": ["wysoka", "srednia", "niska"]}},
    "required": ["scena", "czynnosci", "obiekty", "tekst_na_ekranie", "napisy_na_przedmiotach", "cialo", "pewnosc"]}

VISION_KEYS = {"scena": "", "czynnosci": [], "obiekty": [], "tekst_na_ekranie": [], "napisy_na_przedmiotach": [],
               "cialo": "", "pewnosc": "niska"}

# pisma, które mały model czasem „wtrąca” do polskiego tekstu (np. „metalowy滤网”)
_FOREIGN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]+")
_LOWER = {"wysoka": "srednia", "srednia": "niska", "niska": "niska"}


# Domyślny lokalny model TEKSTOWY (streszczenie, czat, tłumaczenia) — wybrany pomiarem, zob. docs/modele.md
DEFAULT_TEXT_MODEL = "gemma3:4b"


class LLMError(RuntimeError):
    pass


def _clean_vision(d: dict) -> dict:
    out: dict = {}
    foreign = False

    def fix(x: str) -> str:
        nonlocal foreign
        y = _FOREIGN.sub(" [?] ", x)
        if y != x:
            foreign = True
        return re.sub(r"\s{2,}", " ", y).strip()

    for k, default in VISION_KEYS.items():
        v = d.get(k, default)
        if isinstance(default, list):
            if isinstance(v, str):
                v = [v] if v.strip() else []
            v = [fix(str(x)) for x in (v or []) if str(x).strip()]
            v = [x for x in v if x]
        else:
            v = "" if v is None else fix(str(v))
        out[k] = v
    if out["pewnosc"] not in ("wysoka", "srednia", "niska"):
        out["pewnosc"] = "niska"
    if foreign:   # model „zgubił” język — mniej mu ufamy
        out["pewnosc"] = _LOWER[out["pewnosc"]]
    return out


_FIELD_STR = re.compile(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_FIELD_LIST = re.compile(r'"(\w+)"\s*:\s*\[([^\]]*)\]')


def salvage_json(txt: str) -> dict:
    """Wyciąga kompletne pola z uciętego JSON-a, np. '{"scena": "X", "obiekty": ["a", "b' → {"scena": "X"}."""
    d: dict = {}
    for k, v in _FIELD_STR.findall(txt):
        d.setdefault(k, v.replace('\\"', '"'))
    for k, v in _FIELD_LIST.findall(txt):
        d.setdefault(k, re.findall(r'"((?:[^"\\]|\\.)*)"', v))
    if not d and not txt.lstrip().startswith("{"):
        d["scena"] = txt.strip()[:200]       # zwykły tekst zamiast JSON-a
    return d


def ollama_parallel() -> int:
    """Ile zapytań naraz obsługuje Ollama (zmienna OLLAMA_NUM_PARALLEL ustawiona przez użytkownika; 1–4)."""
    try:
        return max(1, min(4, int(os.environ.get("OLLAMA_NUM_PARALLEL") or 1)))
    except ValueError:
        return 1


class Ollama:
    def __init__(self, model: str, host: str | None = None, timeout: float = 600):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.timeout = timeout
        self._think_ok = True
        self.parallel = ollama_parallel()


    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.host + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"Ollama {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Nie mogę połączyć się z Ollamą pod {self.host} — czy jest uruchomiona? ({e.reason})") from e
        except (TimeoutError, OSError) as e:   # przekroczenie czasu przy czytaniu odpowiedzi
            raise LLMError(f"Ollama nie odpowiedziała w {self.timeout:.0f} s ({type(e).__name__}).") from e

    def check(self) -> None:
        names = self.installed()
        want = self.model if ":" in self.model else self.model + ":latest"
        if want not in names:
            raise LLMError(f"Brak modelu '{self.model}' w Ollamie. Uruchom: ollama pull {self.model}")

    def describe_frame(self, image: Path, t_label: str) -> dict:
        b64 = base64.b64encode(Path(image).read_bytes()).decode("ascii")
        r = self._post("/api/chat", {
            "model": self.model, "stream": False, "format": FRAME_SCHEMA, "keep_alive": "5m",
            "options": {"temperature": 0, "num_predict": 400, "num_ctx": VISION_CTX},
            "messages": [{"role": "user", "content": VISION_PROMPT.format(t=t_label), "images": [b64]}],
        })
        txt = r.get("message", {}).get("content", "")
        try:
            return _clean_vision(json.loads(txt))
        except json.JSONDecodeError:
            # model urwał JSON w połowie — odzyskaj kompletne pola zamiast wklejać surowy tekst
            d = salvage_json(txt)
            d["pewnosc"] = "niska"
            return _clean_vision(d)

    def complete(self, prompt: str, as_json: bool = False, max_tokens: int | None = None,
                 seed: int = 7, temperature: float | None = None) -> str:
        # STAŁY kontekst 8192 (większy tylko dla bardzo długich promptów): Ollama przeładowuje model, gdy kolejne
        # zapytania mają różne num_ctx — przy równoległym tłumaczeniu i streszczeniu to kosztowało sekundy
        need = len(prompt) // 3 + 1500
        num_ctx = TEXT_CTX if need <= TEXT_CTX else min(32768, -(-need // 4096) * 4096)
        # JSON (streszczenie, tłumaczenie): temperatura 0 — ten sam film daje to samo streszczenie
        # (na komputerze testowym przy 0.2 raz 11 kroków, raz 2); rozmowa (czat) zostaje lekko swobodniejsza
        body = {"model": self.model, "stream": False, "keep_alive": "5m",
                # limit długości + kara za powtórzenia: mały model potrafi się zapętlić
                "options": {"temperature": temperature if temperature is not None else (0 if as_json else 0.2),
                            "num_ctx": num_ctx, "seed": seed,
                            "num_predict": max_tokens or (3000 if as_json else 1200), "repeat_penalty": 1.15},
                **({"format": "json"} if as_json else {}),
                "messages": [{"role": "user", "content": prompt}]}
        if self._think_ok:
            # modele „myślące” (qwen3) bez myślenia: kilka razy szybciej, a w tym zadaniu nie gorzej
            body["think"] = False
        try:
            r = self._post("/api/chat", body)
        except LLMError as e:
            if "think" not in str(e).lower() or not self._think_ok:
                raise
            self._think_ok = False            # starsza Ollama / model bez tej opcji
            body.pop("think", None)
            r = self._post("/api/chat", body)
        return r.get("message", {}).get("content", "").strip()

    def installed(self) -> list[str]:
        try:
            with urllib.request.urlopen(urllib.request.Request(self.host + "/api/tags"), timeout=10) as r:
                return [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
        except Exception as e:
            raise LLMError(f"Ollama nie odpowiada pod {self.host}: {e}") from e

    def has_model(self) -> bool:
        want = self.model if ":" in self.model else self.model + ":latest"
        return want in self.installed()

    def pull(self, log=print) -> None:
        """Pobiera model do Ollamy (jednorazowo), z postępem w logu co ~10%."""
        req = urllib.request.Request(self.host + "/api/pull", data=json.dumps({"model": self.model}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        last = -10
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    if not line.strip():
                        continue
                    d = json.loads(line.decode("utf-8"))
                    if d.get("error"):
                        raise LLMError(f"Pobieranie modelu {self.model}: {d['error']}")
                    if d.get("total") and d.get("completed") is not None:
                        pct = int(100 * d["completed"] / d["total"])
                        if pct >= last + 10:
                            last = pct
                            log(f"        pobieranie {self.model}: {pct}% z {d['total'] / 1e9:.1f} GB")
        except urllib.error.URLError as e:
            raise LLMError(f"Nie mogę pobrać modelu {self.model}: {e}") from e
        except (TimeoutError, OSError) as e:
            raise LLMError(f"Przerwane pobieranie modelu {self.model} ({type(e).__name__}).") from e

    def ensure(self, log=print) -> None:
        """Model jest w Ollamie albo zostaje pobrany (aplikacja ma działać bez ręcznego `ollama pull`)."""
        if not self.has_model():
            log(f"        model {self.model} nie jest pobrany — pobieram (jednorazowo)…")
            self.pull(log)

    def preload(self, num_ctx: int = VISION_CTX) -> None:
        """Wczytuje model do pamięci karty z wyprzedzeniem (pusty prompt) — na komputerze testowym samo wczytanie
        modelu obrazu zajmowało ~20 s przed pierwszym kadrem; tak dzieje się to w tle, w czasie OCR/kadrów."""
        try:
            self._post("/api/generate", {"model": self.model, "keep_alive": "10m", "options": {"num_ctx": num_ctx}})
        except LLMError:
            pass

    def gpu_share(self) -> float | None:
        """Jaka część wczytanego modelu jest w pamięci karty (1.0 = cały; <1 = część na procesorze, wolniej)."""
        try:
            with urllib.request.urlopen(urllib.request.Request(self.host + "/api/ps"), timeout=10) as r:
                ms = json.loads(r.read().decode("utf-8")).get("models", [])
        except Exception:
            return None
        want = self.model if ":" in self.model else self.model + ":latest"
        for m in ms:
            if m.get("name") == want or m.get("model") == want:
                size = m.get("size") or 0
                return round((m.get("size_vram") or 0) / size, 3) if size else None
        return None

    def unload(self) -> None:
        try:
            self._post("/api/generate", {"model": self.model, "keep_alive": 0})
        except LLMError:
            pass


class ClaudeCode:
    """Wywołuje lokalny Claude Code w trybie nieinteraktywnym (`claude -p`).

    Przy zalogowaniu kontem Pro zużycie liczy się w limitach subskrypcji. Jeśli ustawiona
    jest zmienna ANTHROPIC_API_KEY, Claude Code użyłby płatnego API — dlatego odmawiamy,
    chyba że użytkownik świadomie na to pozwoli (allow_api_key=True).
    """

    def __init__(self, exe: str | None = None, allow_api_key: bool = False, timeout: float = 900):
        self.exe = exe or shutil.which("claude")
        self.allow_api_key = allow_api_key
        self.timeout = timeout

    def check(self) -> None:
        if not self.exe:
            raise LLMError("Nie znaleziono polecenia 'claude' (Claude Code). Zainstaluj Claude Code i zaloguj się kontem Pro.")
        if os.environ.get("ANTHROPIC_API_KEY") and not self.allow_api_key:
            raise LLMError("Ustawiona jest zmienna ANTHROPIC_API_KEY — Claude Code naliczałby płatne API zamiast "
                           "subskrypcji Pro. Usuń zmienną albo użyj --allow-api-key.")

    def complete(self, prompt: str, as_json: bool = False, max_tokens: int | None = None,
                 seed: int = 7, temperature: float | None = None) -> str:
        self.check()
        proc = run([self.exe, "-p", "Wykonaj zadanie opisane na wejściu. Odpowiedz tylko wynikiem.",
                    "--output-format", "text"], input_text=prompt, timeout=self.timeout)
        return proc.stdout_text.strip()  # type: ignore[attr-defined]
