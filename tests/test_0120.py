"""0.12.0 — testy regresji na filmach z komputera użytkownika (0.11.9): tortilla (PL), pancake touch (piłka),
reel modowy („inne”) i dokument 24:50. Dane: tests/data/filmy_0119 (transkrypcja, tłumaczenie, napisy z ekranu, sceny).
Model zastąpiony atrapą — sprawdzamy to, co robi PROGRAM (dobór pól, fakty z linii, reklamy, straże)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data" / "filmy_0119"


def film(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


# ---------------- napisy z ekranu ----------------
def test_ocr_merge_same_caption_with_ten_lines_on_screen():
    """Reel „wisdm”: 9–10 napisów naraz; ten sam napis dopisywał się co klatkę (106 linii zamiast kilku)."""
    from vidsum.ocr import merge_frames
    frame = [("I wish men had sluttier", .95), ("outfit options because", .93), ("why am I in a mini skirt and", .94),
             ("you're in a fucking quarter", .96), ("138.6K", .86), ("Gorgeous ® . 2025-12-12", .92),
             ("#fyp #foryoupage #foryou", .96), ("Contains: Clumsy - Fergie", .95), ("Q Search - Skirt Set Outfit", .93),
             ("3,933", .83)]
    variant = [(t.replace("am I in", "am l in"), s) for t, s in frame]          # OCR myli I z l
    lines = merge_frames([frame, variant, frame, frame, [], [("HENLEY", .83)]], fps=2.0)
    texts = [l.text for l in lines]
    assert texts == ["I wish men had sluttier", "outfit options because", "why am I in a mini skirt and",
                     "you're in a fucking quarter", "HENLEY"]
    assert lines[0].start == 0.0 and lines[0].end == 2.0 and lines[-1].start == 2.5


@pytest.mark.parametrize("text,junk", [
    ("138.6K", True), ("3,933", True), ("#fyp #foryoupage #foryou", True), ("Contains: Clumsy - Fergie", True),
    ("Q Search · Skirt Set Outfit", True), ("Gorgeous ® · 2025-12-12", True), ("@wisdm", True),
    ("180", False), ("2025-12-12", False), ("April 1: 233 TB", False), ("THE CCP IS COMING", False), ("#1 trick", False),
    ("The Mistake", False), ("30 March 2021", False)])
def test_ocr_overlay_junk(text, junk):
    from vidsum.ocr import is_overlay_junk
    assert is_overlay_junk(text) is junk


def test_caption_fixes_only_when_screen_repeats_speech():
    """Dokument: na ekranie cytowane dokumenty, nie napisy do mowy — „Total” nie może stać się „Toial”."""
    from vidsum.ocr import OcrLine, caption_coverage, correct_from_captions
    from vidsum.transcribe import Segment
    d = film("dokument_ambasada")
    segs = [Segment(x["start"], x["end"], x["text"]) for x in d["segmenty"]]
    lines = [OcrLine(x["start"], x["end"], x["text"], x["score"]) for x in d["napisy_ekranowe"]]
    assert caption_coverage(segs, lines) < 0.4
    i = next(k for k, x in enumerate(segs) if "Toial" in x.text)             # w danych jest już błędna „poprawka” z 0.11.9
    segs[i].text = "Total Internal Reflection."
    assert correct_from_captions(segs, lines + [OcrLine(segs[i].start, segs[i].end, "Toial Internal Reflection", 0.95)]) == []
    assert segs[i].text == "Total Internal Reflection."
    p = film("pancake_touch")                                    # wypalone napisy do mowy — poprawki dalej działają
    assert caption_coverage([Segment(x["start"], x["end"], x["text"]) for x in p["segmenty"]],
                            [OcrLine(x["start"], x["end"], x["text"], x["score"]) for x in p["napisy_ekranowe"]]) > 0.8
    s3 = [Segment(0.0, 3.0, "Finish with maldon chocolate flakes now.")]
    fx = correct_from_captions(s3, [OcrLine(0.0, 3.0, "finish with maldon salt flakes", 0.95)])
    assert [(f["bylo"], f["jest"]) for f in fx] == [("chocolate", "salt")]


# ---------------- mowa ----------------
def test_long_sentence_split_at_commas():
    """Tortilla: 12 s wyliczanki jednym zdaniem → linie po przecinkach (kroki mają się czego trzymać)."""
    from vidsum.transcribe import Segment, split_long_segments
    d = film("tortilla")
    out = split_long_segments([Segment(**x) for x in d["segmenty"]])
    texts = [s.text for s in out]
    assert "dodasz sól, pieprz, wymieszasz," in texts and "na to położysz wrapa," in texts
    assert texts[0].startswith("Czy wiesz, że jak wbijesz") and texts[-1] == "pyszne, wysokobiałkowe śniadanie?"
    assert out[0].start == 0.0 and abs(out[-2].end - 11.8) < 0.05
    assert all(a.end <= b.start + 0.02 for a, b in zip(out, out[1:]))
    short = [Segment(0.0, 4.0, "Peel them, cut them, wash them.")]
    assert split_long_segments(short) == short                     # krótkie zdania zostają


# ---------------- typ ----------------
def test_type_from_content_sport_only_with_football_words():
    from vidsum.summary import type_from_content
    p = film("pancake_touch")
    text = " ".join(x["text"] for x in p["segmenty"]) + " " + p["zrodlo"]["opis"]
    assert type_from_content("poradnik", text) == "sport" and type_from_content("", text) == "sport"
    w = film("wisdm_moda")
    assert type_from_content("inne", " ".join(x["text"] for x in w["segmenty"])) == "inne"
    assert type_from_content("poradnik", "Peel the potatoes, fry them in a pot, touch of salt, cook until golden") == "poradnik"
    assert type_from_content("przepis", text) == "przepis"         # przepisu nie zmieniamy


def test_type_sample_covers_whole_film():
    from vidsum.summary import type_sample
    text = "POCZĄTEK " + "x " * 3000 + " ŚRODEK " + "y " * 3000 + " KONIEC"
    s = type_sample(text)
    assert len(s) < 2700 and "POCZĄTEK" in s and "KONIEC" in s and "ŚRODEK" in s


def test_template_fields_follow_type():
    from vidsum.summary import parse_summary
    base = {"tytul": "T", "teza": "x", "streszczenie": ["a"],
            "co_masz_zrobic": {"kroki": [{"t": 1, "tekst": "Option two. The baby tee.", "zrodlo": "mowa"}],
                               "skladniki": [{"nazwa": "mąka", "ilosc": "1 kg"}], "sprzet": ["Henley", "Baby tee"],
                               "cwiczenia": [{"nazwa": "Pokey man", "t": 32}], "wskazowki": ["w"], "bledy": ["b"],
                               "wnioski": ["wn"], "czas": "5 min",
                               "fakty": [{"t": 2, "tekst": "W 2018 roku", "rodzaj": "data", "zrodlo": "mowa"}]}}
    got = {}
    for typ in ("przepis", "poradnik", "trening", "sport", "wyklad", "dokument", "inne"):
        c = parse_summary(json.dumps({**base, "typ": typ}), 60.0)["co_masz_zrobic"]
        got[typ] = {k for k in ("skladniki", "kroki", "sprzet", "cwiczenia", "fakty", "czas") if c[k]}
    assert got["przepis"] == {"skladniki", "kroki", "sprzet", "czas"}
    assert got["poradnik"] == {"kroki", "sprzet", "czas"}
    assert got["trening"] == {"cwiczenia", "sprzet", "czas"}
    assert got["sport"] == {"cwiczenia", "sprzet"}
    assert got["wyklad"] == got["inne"] == got["dokument"] == {"fakty"}


def test_extract_prompt_has_only_fields_of_the_type_and_no_kitchen_glossary():
    from vidsum.summary import staged_summary
    p = film("pancake_touch")
    prompts = []

    class Eng:
        def complete(self, prompt, as_json=False):
            prompts.append(prompt)
            if prompt.startswith("Fragment transkrypcji"):
                return '{"typ": "poradnik"}'                       # model się myli — treść mówi „sport”
            if "ZAPIS:\n" in prompt and "FAKTY Z FILMU" not in prompt:
                return json.dumps({"cwiczenia": [{"nazwa": "Przyjęcie pancake", "t": 0, "technika": "Stopa płasko, palce w dół."}],
                                   "kroki": [{"t": 1, "tekst": "Obierz panki"}], "bledy": ["Stopa za wysoko."], "wskazowki": []})
            return json.dumps({"tytul": "Przyjęcie pancake", "teza": "Jak przyjąć piłkę płaską stopą.", "streszczenie": ["A."],
                               "najwazniejsze": [{"t": 3, "tytul": "Stopa", "opis": "Trzymaj stopę nisko."}],
                               "szczera_ocena": "Krótkie i konkretne. Brakuje proporcji składników."})

    tl = "\n".join(f"[{int(s['start'])}s] MOWA: {s['text']}" for s in p["segmenty"])
    s = staged_summary(Eng(), tl, "tytuł: Pancake Touch Explained", 62.17, segments=p["segmenty"], ocr=p["napisy_ekranowe"])
    assert s["typ"] == "sport" and s["metoda"] == "fakty z fragmentów"
    ex = [x for x in prompts if "ZAPIS:\n" in x and "FAKTY Z FILMU" not in x]
    assert ex and all('"kroki"' not in x and '"skladniki"' not in x and '"cwiczenia"' in x for x in ex)
    assert all("typ\": \"przepis|" not in x for x in ex), "fragment nie zgaduje typu od nowa"
    joined = "\n".join(prompts[1:])
    assert "proszek do pieczenia" not in joined and "taca" not in joined and "żonglerka" in joined
    c = s["co_masz_zrobic"]
    assert c["kroki"] == [] and c["cwiczenia"][0]["nazwa"] == "Przyjęcie pancake" and c["bledy"] == ["Stopa za wysoko."]
    assert s["szczera_ocena"] == "Krótkie i konkretne."            # bez zdania o składnikach


# ---------------- film „opowiadany”: części, fakty z linii, reklamy ----------------
class StoryEngine:
    """Atrapa: typ „wyklad” (jak prawdziwy model w 0.11.9), w każdej części wskazuje linie z cyframi jako fakty,
    najdłuższą linię jako cytat i linie reklamy; opis całości z „najważniejszym” wewnątrz reklamy."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt, as_json=False, **kw):
        self.prompts.append(prompt)
        if prompt.startswith("Fragment transkrypcji"):
            return '{"typ": "wyklad"}'
        if prompt.startswith("Numbered lines"):
            ls = [(int(n), t) for n, t in re.findall(r"^\[(\d+)\] \d\d:\d\d (.*)$", prompt, re.M)]
            want = ("thinner", "uncle and aunt", "343 million", "54 overseas", "Delete.me has found")
            facts = [n for n, t in ls if any(w in t for w in want)] + [n for n, t in ls if re.search(r"\b20[12]\d\b", t)]
            ads = [n for n, t in ls if re.search(r"espresso|Data brokers|Delete", t)]
            quote = max(ls, key=lambda x: len(x[1]))[0]
            return json.dumps({"tytul": f"Część od {ls[0][0]}", "streszczenie": "Chiny kupiły Royal Mint Court. Plany są zaczernione.",
                               "fakty": facts[:5], "cytat": quote, "reklama": ads})
        assert prompt.startswith("Masz streszczenia"), prompt[:60]
        return json.dumps({"tytul": "Ambasada Chin w Londynie", "teza": "Film bada plany ambasady.",
                           "streszczenie": ["A.", "B.", "C.", "D."], "do_zapamietania": "Z.",
                           "najwazniejsze": [{"t": 150, "tytul": "Zakup", "opis": "Chiny kupiły teren."},
                                             {"t": 330, "tytul": "Reklama", "opis": "Usuń swoje dane."},
                                             {"t": 1040, "tytul": "Protest", "opis": "Ludzie protestują."},
                                             {"t": 1370, "tytul": "Decyzja", "opis": "Rząd zatwierdził budowę."}],
                           "wnioski": ["W1", "W2"], "szczera_ocena": "Rzetelne. Brakuje informacji o technikach gotowania.",
                           "czego_nie_wiadomo": ["X"], "pytania": ["P1?"]})


@pytest.fixture(scope="module")
def doc():
    from vidsum.summary import staged_summary, tidy, verify_quotes
    d = film("dokument_ambasada")
    eng, log = StoryEngine(), []
    tl = "\n".join(f"[{int(s['start'])}s] MOWA: {s['text']}" for s in d["segmenty"])
    s = staged_summary(eng, tl, "tytuł: The Scariest Building in Europe", d["zrodlo"]["dlugosc_s"], log.append,
                       segments=d["segmenty"], ocr=d["napisy_ekranowe"], trace=[])
    verify_quotes(s, d["segmenty"])
    tidy(s, d["zrodlo"]["dlugosc_s"])
    return d, s, eng, log


def test_story_whole_film_in_chapters_and_few_calls(doc):
    d, s, eng, log = doc
    dur = d["zrodlo"]["dlugosc_s"]
    assert s["typ"] == "wyklad" and s["metoda"] == "części filmu z linii mowy"
    ch = s["rozdzialy"]
    assert 4 <= len(ch) <= 8 and ch[0]["start"] == 0 and abs(ch[-1]["end"] - dur) < 1
    assert all(abs(a["end"] - b["start"]) < 0.01 for a, b in zip(ch, ch[1:]))
    assert len(eng.prompts) == 1 + len([p for p in eng.prompts if p.startswith("Numbered lines")]) + 1 <= 10   # 0.11.9: 19 zapytań
    assert not any("proszek do pieczenia" in p or "tray = taca" in p for p in eng.prompts)
    c = s["co_masz_zrobic"]
    assert c["kroki"] == [] and c["sprzet"] == [] and c["cwiczenia"] == [] and c["skladniki"] == []


def test_story_facts_are_transcript_lines_not_paraphrase(doc):
    d, s, eng, log = doc
    facts = s["co_masz_zrobic"]["fakty"]
    speech = " ".join(x["text"] for x in d["segmenty"])
    assert len(facts) >= 8
    assert all(f["oryginal"] in speech or all(part in speech for part in f["oryginal"].split("  ")) for f in facts)
    thin = next(f for f in facts if "thinner" in f["oryginal"])
    assert "thread of glass" in thin["oryginal"], "zdanie urwane na pauzie jest sklejone w całość"
    assert any("343 million" in f["oryginal"] for f in facts)
    assert [f["t"] for f in facts] == sorted(f["t"] for f in facts)
    assert all(f["rodzaj"] in ("liczba", "data", "fakt") for f in facts)


def test_story_ads_marked_and_kept_out_of_facts(doc):
    d, s, eng, log = doc
    ads = s["reklamy"]
    assert len(ads) == 2 and 295 <= ads[0]["start"] <= 302 and 370 <= ads[0]["end"] <= 380, ads
    assert ads[0]["marka"] == "Delete Me" and ads[1]["start"] > 1400
    inside = lambda t: any(a["start"] <= t <= a["end"] for a in ads)   # noqa: E731
    assert not any(inside(f["t"]) for f in s["co_masz_zrobic"]["fakty"]), "„Delete.me has found 247…” to reklama"
    assert not any("Delete" in f["oryginal"] for f in s["co_masz_zrobic"]["fakty"])
    assert [h["tytul"] for h in s["najwazniejsze"]] == ["Zakup", "Protest", "Decyzja"]      # „Reklama” odpada
    assert not any(inside(q["t"]) for q in s["cytaty"])
    assert any("reklamy:" in x for x in log)
    from vidsum.summary import to_markdown
    md = to_markdown(s)
    assert "## Reklamy (pominięte w faktach)" in md and "Delete Me" in md and "## Rozdziały" in md
    assert "gotowania" not in s["szczera_ocena"]


def test_story_facts_get_polish_from_line_translation(doc):
    """„uncle and aunt” ma zostać „wujem i ciocią” z tłumaczenia tej linii (0.11.9: model napisał „brata i siostrę”)."""
    from vidsum.story import localize
    d, s, eng, log = doc
    s = json.loads(json.dumps(s))                                  # kopia — inne testy czytają oryginał
    uncle = next(f for f in s["co_masz_zrobic"]["fakty"] if "uncle and aunt" in f["oryginal"])
    assert uncle["tekst"] == uncle["oryginal"]                      # tłumaczenie jeszcze niegotowe → oryginał
    n = localize(s, d["segmenty"], d["pl"])
    assert n >= 8 and "wuja i ciocię" in uncle["tekst"]
    thin = next(f for f in s["co_masz_zrobic"]["fakty"] if "thinner" in f["oryginal"])
    assert "cieńsza" in thin["tekst"] and "grubsza" not in thin["tekst"]
    assert all(re.search(r"[ąćęłńóśźż]", m["tekst"]) or not re.search(r"\b(the|and|of)\b", m["tekst"]) for m in s["momenty"])
    assert all(q["tlumaczenie"] for q in s["cytaty"])
    assert localize(s, d["segmenty"], d["pl"][:-1]) == 0            # tłumaczenie niepełne → nic nie ruszamy


def test_ad_spans_without_model_and_no_false_alarm():
    from vidsum.story import ad_spans
    from vidsum.summary import speech_lines
    d = film("dokument_ambasada")
    lines = speech_lines(d["segmenty"])
    ads = ad_spans(lines, set())                                   # model nic nie wskazał — zostają pewne sygnały
    assert len(ads) == 2 and ads[0]["marka"] == "Delete Me" and 325 <= ads[0]["start"] <= 335
    w = speech_lines(film("wisdm_moda")["segmenty"])
    assert ad_spans(w, {3, 4, 5}) == []                             # samo wskazanie modelu nie wystarcza
    assert ad_spans(speech_lines(film("pancake_touch")["segmenty"]), set()) == []


def test_sentence_at_joins_split_sentence():
    from vidsum.story import sentence_at
    by_n = {1: {"tekst": "Before that."}, 2: {"tekst": "In August 2025,"},
            3: {"tekst": "then Deputy Prime Minister Angela Rayner asked China to explain."}, 4: {"tekst": "But Beijing refused."}}
    assert sentence_at(3, by_n) == [2, 3] and sentence_at(2, by_n) == [2, 3] and sentence_at(4, by_n) == [4]


def test_thin_timeline_keeps_the_end():
    from vidsum.summary import thin_timeline
    tl = "\n".join(f"[{i * 5}s] MOWA: zdanie numer {i} " + "x" * 80 for i in range(400))
    th = thin_timeline(tl, 9000)
    assert len(th) < 9200 and th.startswith("[0s]") and "[1975s]" in th and "co 5. linia" in th
    assert thin_timeline("krótki", 9000) == "krótki"


def test_drop_frame_echo_and_review_cleanup():
    from vidsum.summary import clean_review, drop_frame_echo
    tl = ("[0s] MOWA: x | OBRAZ: Mężczyzna je bułkę z żółtym składnikiem. (je, trzyma bułkę)\n"
          "[70s] OBRAZ: Mężczyzna od tyłu, patrzy w górę.")
    s = {"typ": "inne",
         "momenty": [{"t": 1, "tekst": "Obraz przedstawia mężczyznę od tyłu patrzącego w górę."},
                     {"t": 2, "tekst": "Prezentacja dwóch stylów."}],
         "najwazniejsze": [{"t": 0, "tytul": "a", "opis": "Mężczyzna je bułkę z żółtym składnikiem. (je, trzyma bułkę)"},
                           {"t": 1, "tytul": "b", "opis": "Henley jako pierwsza propozycja."},
                           {"t": 2, "tytul": "c", "opis": "Koszulka baby tee jako druga."}],
         "szczera_ocena": "Film jest luźny. Brak instrukcji dotyczących proporcji lub ilości składników. Brakuje informacji o technikach gotowania.",
         "czego_nie_wiadomo": ["Nie wiemy, kim jest autor.", "Nie podano czasu pieczenia."]}
    assert drop_frame_echo(s, tl) == 2
    assert [m["tekst"] for m in s["momenty"]] == ["Prezentacja dwóch stylów."] and [h["tytul"] for h in s["najwazniejsze"]] == ["b", "c"]
    clean_review(s, "Ladies. There are indeed copious ways for a man to dress.")
    assert s["szczera_ocena"] == "Film jest luźny." and s["czego_nie_wiadomo"] == ["Nie wiemy, kim jest autor."]
    r = {"typ": "przepis", "szczera_ocena": "Brak ilości składników.", "czego_nie_wiadomo": []}
    clean_review(r, "fry the potatoes")
    assert r["szczera_ocena"] == "Brak ilości składników."           # przy przepisie to uczciwa uwaga


# ---------------- straże tłumaczenia ----------------
def test_clean_script_and_line_problem():
    from vidsum.translate import clean_script, line_problem
    assert clean_script("Oferтoвaнo nagrodę w wysokości 130\x9f۰۰۰ dolarów", "pl") == "Ofertowano nagrodę w wysokości 130000 dolarów"
    src = "A $130,000 reward is offered for information leading to her capture."
    assert line_problem(src, "Oferowano nagrodę 130 000 dolarów za informacje.", "pl") is None
    assert "zgubiona liczba 130000" in line_problem(src, "Oferowano nagrodę 13 000 dolarów.", "pl")
    assert line_problem("That came to an end in the 1970s, but", "To się skończyło w latach 70-tych, ale", "pl") is None
    assert line_problem("Fry at 140 degrees for 5 minutes", "Smaż w 180 stopniach przez 5 minut", "pl").startswith("zgubiona liczba 140")
    assert line_problem("Add 3 eggs", "Dodaj trzy jajka", "pl") is None                      # małe liczby słownie — w porządku
    assert line_problem("Several hundred pages of them.", "Kilkaset stron tych planów.", "pl") is None
    assert line_problem("more than a hundred Chinese nationals", "ponad 100 obywateli Chin", "pl") is None
    assert "Tower Bridge" in line_problem("a busy road leading directly to Tower Bridge.", "ulica prowadząca do Wieży Cytadeli.", "pl")
    assert line_problem("right next to Mansell Street, near Tower Bridge.", "tuż obok Mansell Street, blisko Tower Bridge.", "pl") is None
    assert line_problem("In London", "В Лондоне", "pl") == "obce pismo"


def test_all_recorded_translations_pass_except_known_error():
    """Tłumaczenia z 0.11.9: straż wskazuje tylko „Tower Bridge → Wieża Cytadeli”, bez fałszywych alarmów."""
    from vidsum.translate import clean_script, line_problem
    bad = []
    for name in ("dokument_ambasada", "wisdm_moda", "pancake_touch"):
        d = film(name)
        bad += [why for s, p in zip(d["segmenty"], d["pl"]) for why in [line_problem(s["text"], clean_script(p["text"], "pl"), "pl")] if why]
    assert bad == ["zmieniona nazwa „Tower Bridge”"]


def test_translate_segments_retries_bad_line_then_keeps_original():
    from vidsum.translate import translate_segments
    segs = [{"start": 0, "end": 2, "text": "It leads directly to Tower Bridge."},
            {"start": 2, "end": 4, "text": "China bought it for 343 million dollars."},
            {"start": 4, "end": 6, "text": "It has been vacant since 2013."}]

    class Eng:
        def __init__(self):
            self.calls = []

        def complete(self, prompt, as_json=False):
            lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("LINES:")[1], re.M)
            self.calls.append([t for _, t in lines])
            if len(lines) == 3:
                assert "Names to keep exactly as written" in prompt and "Tower Bridge" in prompt
                return json.dumps({"1": "Prowadzi prosto do Wieży Cytadeli.", "2": "Chiny kupiły to za 34 miliony dolarów.",
                                   "3": "Stoi puste od 2013 roku."})
            if "Tower Bridge" in lines[0][1]:
                return json.dumps({"1": "Prowadzi prosto do Tower Bridge."})       # druga próba dobra
            return json.dumps({"1": "Chiny kupiły to za 34 miliony dolarów."})      # dalej zła liczba

    eng, log = Eng(), []
    out, failed = translate_segments(eng, segs, "en", "pl", log.append)
    assert [x["text"] for x in out] == ["Prowadzi prosto do Tower Bridge.", None, "Stoi puste od 2013 roku."]
    assert failed == 1 and len(eng.calls) == 3
    assert any("poprawiono 1, bez tłumaczenia 1" in x for x in log)


def test_translation_prompt_gets_football_terms():
    from vidsum.summary import SPORT_TERMS
    from vidsum.translate import translate_lines
    seen = []

    class Eng:
        def complete(self, prompt, as_json=False):
            seen.append(prompt)
            return json.dumps({"1": "Wejdź w żonglerkę."})

    assert translate_lines(Eng(), ["Step into the juggle."], "en", "pl", terms=SPORT_TERMS) == ["Wejdź w żonglerkę."]
    assert "juggle / juggling = żonglerka" in seen[0]


# ---------------- kontrola jakości ----------------
def test_quality_check_flags_what_0119_got_wrong():
    from vidsum import quality
    from vidsum.summary import parse_summary
    d = film("dokument_ambasada")
    s = parse_summary(json.dumps({"typ": "dokument", "tytul": "T", "teza": "x", "streszczenie": ["Kupiono za 999 milionów."],
                                  "najwazniejsze": [{"t": 61, "tytul": "a", "opis": "o"}, {"t": 84, "tytul": "b", "opis": "o"},
                                                    {"t": 118, "tytul": "c", "opis": "o"}],
                                  "cytaty": [{"t": 5, "tekst": "This sentence was never said in the film at all."}],
                                  "co_masz_zrobic": {"fakty": [{"t": 361, "tekst": "Otrzymaj 20% rabatu na Delete Me", "rodzaj": "liczba"},
                                                               {"t": 1028, "tekst": "Public is worried too and the people of the city are in the streets.", "rodzaj": "fakt"}]}}),
                      d["zrodlo"]["dlugosc_s"])
    a = {"zrodlo": d["zrodlo"], "transkrypcja": {"segmenty": d["segmenty"], "tlumaczenia": {"pl": {"segmenty": d["pl"]}}},
         "napisy_ekranowe": d["napisy_ekranowe"], "os_czasu": [], "streszczenie": {"dane": s}}
    codes = {i["kod"] for i in quality.check(a)}
    assert {"brak_rozdzialow", "najwazniejsze_poczatek", "liczby_spoza_filmu", "reklama_w_tresci", "cytat_nie_z_filmu",
            "tlumaczenie_bledy"} <= codes
    assert quality.score(quality.check(a)) < 40
    assert "❌ `brak_rozdzialow`" in quality.to_markdown("dokument", quality.check(a))


def test_quality_check_clean_result_has_no_issues(doc):
    from vidsum import quality
    from vidsum.story import localize
    d, s, eng, log = doc
    s = json.loads(json.dumps(s))
    localize(s, d["segmenty"], d["pl"])
    pl = [dict(x) for x in d["pl"]]
    for x in pl:                                                   # znany błąd tłumaczenia z 0.11.9 poprawiony
        x["text"] = x["text"].replace("Wieży Cytadeli", "Tower Bridge")
    a = {"zrodlo": d["zrodlo"], "transkrypcja": {"segmenty": d["segmenty"], "tlumaczenia": {"pl": {"segmenty": pl}}},
         "napisy_ekranowe": d["napisy_ekranowe"], "os_czasu": [], "streszczenie": {"dane": s}}
    issues = quality.check(a)
    assert [i for i in issues if i["poziom"] == "blad"] == [], issues
