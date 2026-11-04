"""Języki rozpoznawane przez Whispera (kod → nazwa angielska do promptów, nazwa polska do raportów)."""
from __future__ import annotations

# 100 kodów z faster-whisper (large-v3 / turbo); kolejność jak w Whisperze
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("English", "angielski"), "zh": ("Chinese", "chiński"), "de": ("German", "niemiecki"),
    "es": ("Spanish", "hiszpański"), "ru": ("Russian", "rosyjski"), "ko": ("Korean", "koreański"),
    "fr": ("French", "francuski"), "ja": ("Japanese", "japoński"), "pt": ("Portuguese", "portugalski"),
    "tr": ("Turkish", "turecki"), "pl": ("Polish", "polski"), "ca": ("Catalan", "kataloński"),
    "nl": ("Dutch", "niderlandzki"), "ar": ("Arabic", "arabski"), "sv": ("Swedish", "szwedzki"),
    "it": ("Italian", "włoski"), "id": ("Indonesian", "indonezyjski"), "hi": ("Hindi", "hindi"),
    "fi": ("Finnish", "fiński"), "vi": ("Vietnamese", "wietnamski"), "he": ("Hebrew", "hebrajski"),
    "uk": ("Ukrainian", "ukraiński"), "el": ("Greek", "grecki"), "ms": ("Malay", "malajski"),
    "cs": ("Czech", "czeski"), "ro": ("Romanian", "rumuński"), "da": ("Danish", "duński"),
    "hu": ("Hungarian", "węgierski"), "ta": ("Tamil", "tamilski"), "no": ("Norwegian", "norweski"),
    "th": ("Thai", "tajski"), "ur": ("Urdu", "urdu"), "hr": ("Croatian", "chorwacki"),
    "bg": ("Bulgarian", "bułgarski"), "lt": ("Lithuanian", "litewski"), "la": ("Latin", "łacina"),
    "mi": ("Maori", "maoryski"), "ml": ("Malayalam", "malajalam"), "cy": ("Welsh", "walijski"),
    "sk": ("Slovak", "słowacki"), "te": ("Telugu", "telugu"), "fa": ("Persian", "perski"),
    "lv": ("Latvian", "łotewski"), "bn": ("Bengali", "bengalski"), "sr": ("Serbian", "serbski"),
    "az": ("Azerbaijani", "azerski"), "sl": ("Slovenian", "słoweński"), "kn": ("Kannada", "kannada"),
    "et": ("Estonian", "estoński"), "mk": ("Macedonian", "macedoński"), "br": ("Breton", "bretoński"),
    "eu": ("Basque", "baskijski"), "is": ("Icelandic", "islandzki"), "hy": ("Armenian", "ormiański"),
    "ne": ("Nepali", "nepalski"), "mn": ("Mongolian", "mongolski"), "bs": ("Bosnian", "bośniacki"),
    "kk": ("Kazakh", "kazachski"), "sq": ("Albanian", "albański"), "sw": ("Swahili", "suahili"),
    "gl": ("Galician", "galicyjski"), "mr": ("Marathi", "marathi"), "pa": ("Punjabi", "pendżabski"),
    "si": ("Sinhala", "syngaleski"), "km": ("Khmer", "khmerski"), "sn": ("Shona", "shona"),
    "yo": ("Yoruba", "joruba"), "so": ("Somali", "somalijski"), "af": ("Afrikaans", "afrikaans"),
    "oc": ("Occitan", "oksytański"), "ka": ("Georgian", "gruziński"), "be": ("Belarusian", "białoruski"),
    "tg": ("Tajik", "tadżycki"), "sd": ("Sindhi", "sindhi"), "gu": ("Gujarati", "gudźarati"),
    "am": ("Amharic", "amharski"), "yi": ("Yiddish", "jidysz"), "lo": ("Lao", "laotański"),
    "uz": ("Uzbek", "uzbecki"), "fo": ("Faroese", "farerski"), "ht": ("Haitian Creole", "kreolski haitański"),
    "ps": ("Pashto", "paszto"), "tk": ("Turkmen", "turkmeński"), "nn": ("Norwegian Nynorsk", "norweski nynorsk"),
    "mt": ("Maltese", "maltański"), "sa": ("Sanskrit", "sanskryt"), "lb": ("Luxembourgish", "luksemburski"),
    "my": ("Burmese", "birmański"), "bo": ("Tibetan", "tybetański"), "tl": ("Tagalog", "tagalski"),
    "mg": ("Malagasy", "malgaski"), "as": ("Assamese", "asamski"), "tt": ("Tatar", "tatarski"),
    "haw": ("Hawaiian", "hawajski"), "ln": ("Lingala", "lingala"), "ha": ("Hausa", "hausa"),
    "ba": ("Bashkir", "baszkirski"), "jw": ("Javanese", "jawajski"), "su": ("Sundanese", "sundajski"),
    "yue": ("Cantonese", "kantoński"),
}

DEFAULT_TRANSLATIONS = ("pl", "en")


def base(code: str | None) -> str:
    """'en-US' / 'en-orig' / 'EN' → 'en'."""
    return (code or "").strip().lower().split("-")[0].split("_")[0]


def normalize(code: str | None) -> str | None:
    """Kod języka dla Whispera albo None (= wykryj). Rzuca ValueError dla nieznanego kodu."""
    c = base(code)
    if c in ("", "auto"):
        return None
    if c not in LANGUAGES:
        raise ValueError(f"Nieznany język '{code}'. Dostępne kody: {', '.join(sorted(LANGUAGES))}")
    return c


def name_en(code: str | None) -> str:
    return LANGUAGES.get(base(code), (code or "unknown language", ""))[0]


def name_pl(code: str | None) -> str:
    return LANGUAGES.get(base(code), ("", code or "nieznany"))[1]


def translation_targets(original: str | None, wanted=DEFAULT_TRANSLATIONS) -> list[str]:
    """Na jakie języki tłumaczyć. Oryginał zostaje zawsze; tłumaczenia to `wanted` bez języka oryginału.

    Domyślnie: angielski → [pl]; polski → [en]; każdy inny → [pl, en].
    Gdy języka nie rozpoznano (brak mowy) — nic.
    """
    o = base(original)
    if not o:
        return []
    out: list[str] = []
    for w in wanted:
        w = base(w)
        if w and w != o and w in LANGUAGES and w not in out:
            out.append(w)
    return out


def parse_list(s: str | list | tuple | None) -> list[str]:
    """'pl,en' / ['pl','en'] / 'brak' → lista kodów (sprawdzonych)."""
    if s is None:
        return list(DEFAULT_TRANSLATIONS)
    items = s if isinstance(s, (list, tuple)) else str(s).replace(";", ",").split(",")
    out = []
    for x in items:
        x = base(str(x))
        if x in ("", "brak", "none", "nie"):
            continue
        if x not in LANGUAGES:
            raise ValueError(f"Nieznany język tłumaczenia '{x}'.")
        if x not in out:
            out.append(x)
    return out
