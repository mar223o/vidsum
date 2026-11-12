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
                           "najwazniejsze": [{"zrodlo": "C1", "tytul": "Zakup", "opis": "Chiny kupiły Royal Mint Court za 343 miliony."},
                                             {"zrodlo": "C2", "tytul": "Reklama", "opis": "Delete Me usuwa twoje dane."},
                                             {"zrodlo": "C5", "tytul": "Protest", "opis": "Setki ludzi protestują, wśród nich Carmen Lau."},
                                             {"zrodlo": "C6", "tytul": "Decyzja", "opis": "Rząd zatwierdził budowę."}],
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


# ---------------- narzędzia kontroli ----------------
def _analysis(d: dict, s: dict | None, pl: bool = True) -> dict:
    return {"narzedzie": {"wersja": "0.12.0"}, "zrodlo": d["zrodlo"], "ustawienia": {"streszczenie": "ollama:gemma3:4b"},
            "transkrypcja": {"jezyk": "en", "segmenty": d["segmenty"],
                             "tlumaczenia": {"pl": {"segmenty": d["pl"]}} if pl else {}},
            "napisy_ekranowe": d["napisy_ekranowe"], "os_czasu": [], "kadry": [], "luki": [],
            "czasy": {"razem_s": 568.0, "ocr_s": 309.0, "streszczenie_s": 161.0},
            "streszczenie": {"dane": s} if s else None}


def test_control_report_for_a_folder_of_analyses(tmp_path, doc):
    from vidsum.cli import main
    from vidsum.control import check_path, read_list
    d, s, eng, log = doc
    (tmp_path / "dobry").mkdir()
    (tmp_path / "dobry" / "analiza.json").write_text(json.dumps(_analysis(d, s)), encoding="utf-8")
    (tmp_path / "bez streszczenia ąę").mkdir()
    (tmp_path / "bez streszczenia ąę" / "analiza.json").write_text(json.dumps(_analysis(d, None)), encoding="utf-8")
    out = check_path(tmp_path)
    md = out.read_text(encoding="utf-8")
    assert out.name == "zestaw_wynik.md" and "| The Scariest Building in Europe | wyklad | pelna | 24:50 | 9 min 28 s | 0.38× |" in md
    assert "`brak_streszczenia`" in md and "napisy (OCR) 5 min 9 s" in md
    data = json.loads((tmp_path / "zestaw_wynik.json").read_text(encoding="utf-8"))
    assert len(data) == 2 and {x["folder"] for x in data} == {"dobry", "bez streszczenia ąę"}
    assert main(["--kontrola", str(tmp_path / "dobry")]) == 0 and (tmp_path / "dobry" / "zestaw_wynik.md").exists()
    assert main(["--kontrola", str(tmp_path / "nie ma")]) == 1
    lst = tmp_path / "lista.txt"
    lst.write_text('\ufeff# komentarz\nhttps://youtu.be/abc\n\n"C:\\Filmy\\film ąę.mp4"\n', encoding="utf-8")
    assert read_list(lst) == ["https://youtu.be/abc", "C:\\Filmy\\film ąę.mp4"]


def test_resummarize_from_saved_analysis_without_touching_it(tmp_path, doc):
    from vidsum.control import resummarize
    d, s, eng, log = doc
    old = dict(s, rozdzialy=[], cytaty=[])                          # „stare” streszczenie bez rozdziałów (jak 0.11.9)
    f = tmp_path / "film"
    f.mkdir()
    (f / "analiza.json").write_text(json.dumps(_analysis(d, old)), encoding="utf-8")
    before = (f / "analiza.json").read_bytes()
    out = resummarize(f, engine=StoryEngine(), log=lambda m: None)
    md = out.read_text(encoding="utf-8")
    assert (f / "analiza.json").read_bytes() == before, "zapisana analiza zostaje nietknięta"
    assert "Kontrola — nowe streszczenie" in md and "`brak_rozdzialow`" in md.split("Kontrola — streszczenie zapisane")[1]
    assert "`brak_rozdzialow`" not in md.split("Kontrola — streszczenie zapisane")[0]
    new = json.loads((f / "streszczenie_ponowne.json").read_text(encoding="utf-8"))
    uncle = next(x for x in new["streszczenie"]["co_masz_zrobic"]["fakty"] if "uncle and aunt" in x["oryginal"])
    assert "wuja i ciocię" in uncle["tekst"], "tłumaczenie było gotowe — fakty od razu po polsku"


# ---------------- tryby analizy i kadry wskazane mową ----------------
def test_speech_cues_on_documentary_and_limits():
    from vidsum.modes import extra_cue_picks, light_picks, speech_cues, thumbnail_times
    from vidsum.story import ad_spans
    from vidsum.summary import speech_lines
    d = film("dokument_ambasada")
    dur = d["zrodlo"]["dlugosc_s"]
    ads = [(a["start"], a["end"]) for a in ad_spans(speech_lines(d["segmenty"]), set())]
    cues = speech_cues(d["segmenty"], dur, ads)
    at = {round(c["t"]): c["zwrot"].lower() for c in cues}
    # miejsca, które pełna analiza 0.11.9 przegapiła: mapa 06:47, kable 07:58, list 19:30
    assert any(406 <= t <= 412 and z == "located here" for t, z in at.items())
    assert any(478 <= t <= 484 and z == "right here" for t, z in at.items())
    assert any(1170 <= t <= 1174 and z == "this one" for t, z in at.items())
    assert not any(372 <= t <= 376 for t in at), "„Scan this QR code” jest w reklamie"
    assert all(b["t"] - a["t"] >= 4 for a, b in zip(cues, cues[1:]))
    extra = extra_cue_picks([k["t"] for k in d["kadry"]], cues)
    assert {round(e["t"]) // 60 for e in extra} >= {6, 8, 19} and len(extra) <= 12
    picks = light_picks(dur, cues, [0, 263, 506, 745, 991, 1263], max_frames=100)
    assert len(picks) <= 30 and [p["t"] for p in picks] == sorted(p["t"] for p in picks)
    assert sum("wskazany_w_mowie" in p["reasons"] for p in picks) == len(cues)
    assert all(b["t"] - a["t"] >= 3 for a, b in zip(picks, picks[1:]))
    assert len(light_picks(dur, cues, [], max_frames=10)) == 10                   # nigdy więcej niż limit pełnej analizy
    chatty = [{"start": i * 6.0, "end": i * 6.0 + 5, "text": "Look at this, it is great."} for i in range(100)]
    assert len(speech_cues(chatty, 600.0)) == 18                                  # gadatliwy narrator — limit
    assert speech_cues(film("wisdm_moda")["segmenty"], 88.5) == [] and speech_cues(film("tortilla")["segmenty"], 14) == []
    pl = speech_cues([{"start": 10, "end": 14, "text": "No i zobaczcie, jak widać ciasto jest gotowe."}], 60)
    assert [c["zwrot"].lower() for c in pl] == ["zobaczcie"]
    assert len(thumbnail_times(1490.0)) == 12 and thumbnail_times(14.0) == [7.0] and len(thumbnail_times(62.0)) == 4


def test_suggest_mode_for_hardware():
    from vidsum.modes import normalize_mode, suggest_mode
    assert suggest_mode(60, 8192)[0] == "pelna" and suggest_mode(1500, 8192)[0] == "pelna"
    assert suggest_mode(60, None)[0] == "mowa" and "NVIDIA" in suggest_mode(60, None)[1]
    assert suggest_mode(60, 4096)[0] == "mowa"
    assert normalize_mode("SZYBKI") == "szybki" and normalize_mode("cokolwiek") == "pelna" and normalize_mode(None) == "pelna"


@pytest.fixture()
def cue_subs(tmp_path):
    f = tmp_path / "napisy_cue.json"
    f.write_text(json.dumps({"language": "pl", "segments": [
        {"start": 0.5, "end": 6.0, "text": "Najpierw kroimy jedną cebulę w drobną kostkę."},
        {"start": 8.5, "end": 14.0, "text": "Teraz wlewamy dwieście mililitrów mleka, zobaczcie jak to wygląda."},
        {"start": 16.5, "end": 25.0, "text": "Mieszamy przez pięć minut na małym ogniu."},
        {"start": 26.5, "end": 31.0, "text": "Gotowe, smacznego."}]}), encoding="utf-8")
    return f


def _images(calls):
    return [c for c in calls if c.get("messages") and c["messages"][0].get("images")]


def test_mode_speech_only_never_touches_vision(tmp_path, cue_subs, monkeypatch):
    from test_vidsum import FILM, FakeOllama
    import http.server
    import threading as th
    from vidsum import pipeline
    from vidsum.pipeline import Options, analyze
    FakeOllama.calls, FakeOllama.fail_images = [], set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(pipeline, "scene_scores", lambda *a, **k: (_ for _ in ()).throw(AssertionError("analiza scen w trybie mowa")))
        got = {}
        opt = Options(out_root=tmp_path / "w", transcript_file=cue_subs, ollama_host=f"http://127.0.0.1:{srv.server_address[1]}",
                      vision_model="fake-vl", text_model="fake-txt", mode="mowa", on_partial=lambda k, d: got.__setitem__(k, d))
        out = analyze(str(FILM), opt, log=lambda m: None)
    finally:
        srv.shutdown()
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert _images(FakeOllama.calls) == [], "tryb „mowa” nie wysyła żadnego kadru do modelu"
    assert r["ustawienia"]["tryb"] == "mowa" and r["ustawienia"]["obraz"] == "brak" and r["napisy_ekranowe"] == []
    assert 1 <= len(r["kadry"]) <= 4 and all(k["vision"] is None for k in r["kadry"])
    assert all((out / k["file"]).is_file() for k in r["kadry"])
    assert any("Tylko mowa" in g for g in r["luki"]) and not any("Kadry co najwyżej" in g for g in r["luki"])
    assert r["streszczenie"]["dane"]["streszczenie"] and "kontrola" in r and "pokazane" in r["streszczenie"]["dane"]
    assert r["streszczenie"]["dane"]["pokazane"] == []


def test_mode_fast_speech_report_first_then_selected_frames(tmp_path, cue_subs):
    from test_vidsum import FILM, FakeOllama
    import http.server
    import threading as th
    from vidsum.pipeline import Options, analyze
    FakeOllama.calls, FakeOllama.fail_images = [], set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    order = []
    try:
        opt = Options(out_root=tmp_path / "w", transcript_file=cue_subs, ocr=False, ollama_host=f"http://127.0.0.1:{srv.server_address[1]}",
                      vision_model="fake-vl", text_model="fake-txt", mode="szybki",
                      on_partial=lambda k, d: order.append((k, len(_images(FakeOllama.calls)))))
        log = []
        out = analyze(str(FILM), opt, log=log.append)
    finally:
        srv.shutdown()
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    first = next(i for i, (k, _) in enumerate(order) if k == "streszczenie_mowa")
    assert order[first][1] == 0, "raport z mowy trafia do interfejsu, zanim model obrazu dostanie pierwszy kadr"
    imgs = _images(FakeOllama.calls)
    assert 2 <= len(imgs) == len(r["kadry"]) <= 30
    assert all(k["vision"] and (out / k["file"]).is_file() for k in r["kadry"])
    cue = [k for k in r["kadry"] if "wskazany_w_mowie" in k["reasons"]]
    assert len(cue) == 1 and 11 <= cue[0]["t"] <= 16, r["kadry"]
    assert sorted(p.name for p in (out / "kadry").iterdir()) == sorted(Path(k["file"]).name for k in r["kadry"]), "bez osieroconych miniatur"
    assert r["ustawienia"]["tryb"] == "szybki" and r["ustawienia"]["obraz"] == "ollama:fake-vl"
    assert {b["widac"]["zrodlo"] for b in r["os_czasu"]} == {"obraz"}
    shown = r["streszczenie"]["dane"]["pokazane"]
    assert len(shown) == 1 and "zobaczcie" in shown[0]["mowa"] and shown[0]["obraz"].startswith("deska i nóż")
    assert "## Pokazane na ekranie" in r["streszczenie"]["markdown"] and "zobaczcie jak to wygląda" in r["streszczenie"]["markdown"]
    assert any("Mowa + szybki obraz" in g for g in r["luki"])
    assert "raport_z_mowy_po_s" in r["czasy"] and r["czasy"]["obraz_s"] > 0
    assert "OBRAZ: deska i nóż" in (out / "prompt_dla_claude.md").read_text(encoding="utf-8")
    assert any("szybki obraz gotowy" in x for x in log)


def test_mode_full_adds_frames_pointed_by_speech(tmp_path, cue_subs):
    from test_vidsum import FILM, FakeOllama
    import http.server
    import threading as th
    from vidsum.pipeline import Options, analyze
    FakeOllama.calls, FakeOllama.fail_images = [], set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        opt = Options(out_root=tmp_path / "w", transcript_file=cue_subs, ocr=False, ollama_host=f"http://127.0.0.1:{srv.server_address[1]}",
                      vision_model="fake-vl", text_model="fake-txt")
        out = analyze(str(FILM), opt, log=lambda m: None)
    finally:
        srv.shutdown()
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert r["ustawienia"]["tryb"] == "pelna" and len(_images(FakeOllama.calls)) == len(r["kadry"])
    ts_ = [k["t"] for k in r["kadry"]]
    assert ts_ == sorted(ts_) and any(11 <= t <= 16 for t in ts_)
    shown = r["streszczenie"]["dane"]["pokazane"]
    assert len(shown) == 1 and "zobaczcie" in shown[0]["mowa"]
    assert any("Kadry co najwyżej" in g for g in r["luki"])


# ---------------- długie filmy, prognoza czasu, interfejs ----------------
def test_ocr_budget_for_long_films():
    from vidsum.ocr import ocr_fps
    assert ocr_fps(60) == 2.0 and ocr_fps(600) == 1.0 and ocr_fps(900) == 1.0       # bez zmian do 15 min
    for dur in (1000, 1490, 3600, 7200):
        assert 235 <= dur * ocr_fps(dur) <= 241, "długi film: najwyżej 240 klatek OCR"
    assert ocr_fps(1490) < 0.5                                                      # 0.11.9: 0,5 kl./s = 745 klatek, 257 s


def test_eta_starts_from_measured_points_and_learns(tmp_path):
    from vidsum import eta
    # pięć pomiarów użytkownika (0.11.5–0.11.9, RTX 3070 Ti, tryb pełny): prognoza startowa trafia w ±15%
    for dur, real in ((14, 54), (58, 69), (62, 82), (88, 85), (1490, 568)):
        p = eta.predict(None, "pelna", dur)
        assert abs(p["razem_s"] - real) / real < 0.15 and p["z_pomiarow"] == 0
    assert eta.predict(None, "mowa", 1490)["razem_s"] < eta.predict(None, "szybki", 1490)["razem_s"] < eta.predict(None, "pelna", 1490)["razem_s"]
    assert eta.predict(tmp_path, "nieznany", 60)["razem_s"] == eta.predict(None, "pelna", 60)["razem_s"]
    # wolniejszy komputer: dwa pomiary → prognoza przeskalowana; od trzech (różne długości) — własne a i b
    eta.record(tmp_path, "pelna", 60, 142, "0.12.0")
    eta.record(tmp_path, "pelna", 62, 143, "0.12.0")
    slow = eta.predict(tmp_path, "pelna", 60)
    assert slow["z_pomiarow"] == 2 and 130 <= slow["razem_s"] <= 155
    eta.record(tmp_path, "pelna", 1500, 1100, "0.12.0")
    assert 1050 <= eta.predict(tmp_path, "pelna", 1500)["razem_s"] <= 1150 and 130 <= eta.predict(tmp_path, "pelna", 61)["razem_s"] <= 160
    assert eta.predict(tmp_path, "mowa", 60)["z_pomiarow"] == 0, "pomiary jednego trybu nie mieszają się z drugim"
    eta.record(tmp_path, "pelna", 0, 10)                                              # zły pomiar — pomijany
    for i in range(80):
        eta.record(tmp_path, "mowa", 100 + i, 40 + i)
    assert len(json.loads((tmp_path / eta.FILE).read_text(encoding="utf-8"))) == eta.KEEP
    (tmp_path / eta.FILE).write_text("{zepsuty", encoding="utf-8")
    assert eta.predict(tmp_path, "pelna", 60)["z_pomiarow"] == 0                      # zepsuty plik nie psuje prognozy


def test_gui_mode_per_video_status_and_eta(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum import eta
    from vidsum.gui import App, Job
    app = App(tmp_path / "wyniki", "tok")
    assert app.settings["tryb"] == "pelna" and app.options(app.settings).mode == "pelna"
    s = app.job_settings("zawsze", "szybki")
    assert s["tryb"] == "szybki" and app.settings["tryb"] == "szybki" and app.options(s).mode == "szybki"
    assert app.job_settings(None, "zly tryb")["tryb"] == "szybki"                     # zła wartość — zostaje ostatni wybór
    assert app.job_settings(None, "mowa")["tryb"] == "mowa"
    st = app.status()
    assert st["tryb_proponowany"] in ("pelna", "mowa") and "karta_pamiec_mb" in st
    if not st["gpu_nvidia"]:
        assert st["tryb_proponowany"] == "mowa" and "NVIDIA" in st["tryb_powod"]
    job = Job("a1", "https://example.com/x", "x", app.options(app.settings), None)
    assert job.to_dict()["eta_s"] is None and job.to_dict()["tryb"] == "mowa"       # jeszcze nie trwa
    job.status, job.started = "trwa", __import__("time").time()
    assert job.to_dict()["eta_s"] is None                                             # długość jeszcze nieznana
    job.partial["meta"] = {"dlugosc_s": 1490.0}
    assert job.to_dict()["eta_s"] == eta.predict(tmp_path / "wyniki", "mowa", 1490.0)["razem_s"]


def test_index_has_mode_switch_and_eta_texts():
    html = (Path(__file__).parents[1] / "vidsum" / "web" / "index.html").read_text(encoding="utf-8")
    for needle in ('id="amode"', 'data-mode="pelna"', 'data-mode="szybki"', 'data-mode="mowa"', "X-Mode", "tryb: aMode()",
                   "mode_hint_szybki", "eta_left", "streszczenie_mowa", "qcHtml(r.kontrola)", 't("shown")'):
        assert needle in html, needle
    for lang_block in html.split("const I18N = {")[1].split("\n };")[0].split("\n en:"):
        for key in ("mode_full:", "mode_fast:", "mode_speech:", "eta_soon:", "qc_ok:", "shown:", "ads:", "zmowy_badge:", "t_todo_wyklad:"):
            assert key in lang_block, key


# ---------------- odtworzenie na odpowiedziach PRAWDZIWEGO modelu (gemma3:4b, pomiar CI z 2026-11-12) ----------------
class Replay:
    """Oddaje po kolei odpowiedzi, które prawdziwy model dał na zapytania danego etapu (tests/data/model_0120)."""
    parallel = 1

    def __init__(self, name: str):
        self.left = json.loads((DATA.parent / "model_0120" / f"{name}.json").read_text(encoding="utf-8"))
        self.prompts: list[str] = []

    def complete(self, prompt, as_json=False, **kw):
        self.prompts.append(prompt)
        kind = ("typ" if prompt.startswith("Fragment transkrypcji") else "czesc" if prompt.startswith("Numbered lines")
                else "opis_calosci" if prompt.startswith("Masz streszczenia")
                else "skladniki" if "Lines of a video transcript (a recipe)" in prompt
                else "kroki" if 'Answer ONLY with JSON: {"1":' in prompt
                else "fakty" if "ZAPIS:" in prompt and "FAKTY Z FILMU" not in prompt
                else "opis" if any(r["etap"] == "opis" for r in self.left)
                else "opis_b" if '"cytaty"' in prompt else "opis_a")
        for i, r in enumerate(self.left):
            if r["etap"] == kind:
                del self.left[i]
                return r["odpowiedz"]
        raise AssertionError(f"brak nagranej odpowiedzi etapu {kind}: {prompt[:60]}")


def replay(name: str):
    from vidsum.summary import compact_timeline, staged_summary, tidy, verify_quotes
    from vidsum.transcribe import Segment, split_long_segments
    import sys
    sys.path.insert(0, str(Path(__file__).parent / "bench"))
    from story_bench import beats_from
    d = film(name)
    d["segmenty"] = [{"start": x.start, "end": x.end, "text": x.text}
                     for x in split_long_segments([Segment(**x) for x in d["segmenty"]])]
    dur = float(d["zrodlo"]["dlugosc_s"])
    eng, log = Replay(name), []
    s = staged_summary(eng, compact_timeline(beats_from(d)), "tytuł: " + (d["zrodlo"].get("tytul") or ""), dur, log.append,
                       segments=d["segmenty"], ocr=d["napisy_ekranowe"])
    verify_quotes(s, d["segmenty"])
    tidy(s, dur, max_quotes=4 if dur < 600 else 8, max_chapters=max(6, min(12, round(dur / 300))))
    return d, s, eng, log


def test_real_model_documentary_facts_quotes_and_moments():
    """Prawdziwy model oddał: listy 20–40 kolejnych numerów jako „fakty”, cytat TEKSTEM zamiast numeru, czas „najważniejszych”
    w minutach. Wynik 0.12.0 w pierwszej wersji: fakt „Hej, nasza autorka Amanda…”, zero cytatów, „Najważniejsze” całe
    na 00:00. Teraz fakty to zdania z liczbami, datami i nazwami z całego filmu."""
    from vidsum import quality
    d, s, eng, log = replay("dokument_ambasada")
    facts = s["co_masz_zrobic"]["fakty"]
    orig = " | ".join(f["oryginal"] for f in facts)
    for must in ("343 million", "In August 2025, then Deputy Prime Minister Angela Rayner", "January 20th, 2026",
                 "over 200 secret rooms", "420 million pounds", "at least 54 overseas police"):
        assert must in orig, must
    assert "Amanda" not in orig and "it's a 10" not in orig and len(facts) >= 15
    assert facts[-1]["t"] > 1200 and facts[0]["t"] < 200, "fakty z całego filmu"
    assert len(s["cytaty"]) >= 3 and any("Netflix espionage thriller" in q["tekst"] for q in s["cytaty"])
    hl = s["najwazniejsze"]
    assert len(hl) >= 4 and max(h["t"] for h in hl) > 900 and len({round(h["t"] / 240) for h in hl}) >= 3, hl
    lau = next(h for h in hl if "Lau" in h["tytul"])
    assert 1040 <= lau["t"] <= 1060, "pozycja o Carmen Lau wskazuje zdanie, w którym pada jej nazwisko (17:28)"
    ads = s["reklamy"]
    assert 298 <= ads[0]["start"] <= 302 and ads[0]["marka"] == "Delete Me", "wstęp reklamy od „Wait, you've been shopping…”"
    assert not any(ads[0]["start"] <= f["t"] <= ads[0]["end"] for f in facts)
    a = {"zrodlo": d["zrodlo"], "transkrypcja": {"jezyk": "en", "segmenty": d["segmenty"], "tlumaczenia": {}},
         "napisy_ekranowe": d["napisy_ekranowe"], "os_czasu": [], "streszczenie": {"dane": s}}
    codes = {i["kod"] for i in quality.check(a)}
    assert not codes & {"najwazniejsze_poczatek", "brak_cytatow", "puste_streszczenie", "reklama_w_faktach"}, codes
    assert not any("Delete" in x for x in s["streszczenie"]) and not any("Delete" in c["opis"] for c in s["rozdzialy"])
    sent = eng.prompts[2]                                   # druga część — w niej jest reklama
    assert "Delete.me removes" not in sent and "(an advertisement was removed here)" in sent


def test_real_model_reel_no_line_numbers_and_screen_context():
    d, s, eng, log = replay("wisdm_moda")
    blob = json.dumps(s, ensure_ascii=False)
    assert "linia" not in blob and "linie" not in blob, "„Henley (linia 8)” — numery linii nie trafiają do wyniku"
    assert [f["oryginal"] for f in s["co_masz_zrobic"]["fakty"]] == ["Exhibit A. The Henley.", "Option two. The baby tee.",
                                                                     "Exhibit C. The Tank."]
    henley = next(h for h in s["najwazniejsze"] if "Henley" in h["tytul"])
    assert 15 <= henley["t"] <= 18
    part = eng.prompts[1]
    assert "I wish men had sluttier outfit options because why am I in a mini skirt" in part, "komentarz z ekranu jako kontekst"
    assert "138.6K" not in part and "#fyp" not in part and "Contains:" not in part
    assert s["cytaty"] and s["cytaty"][0]["tekst"].endswith("don't do it.")


def test_real_model_polish_recipe_steps_from_second_person_speech():
    """Tortilla (PL): „położysz wrapa”, „zdejmiesz z patelni i dodasz szynkę…” to instrukcje, nie wskazówki; ilość z klucza „ilość”."""
    d, s, eng, log = replay("tortilla")
    c = s["co_masz_zrobic"]
    steps = [k["tekst"] for k in c["kroki"]]
    assert steps == ["Wbijesz do miski 3 jajka.", "Dodasz sól, pieprz, wymieszasz.", "Wrzucisz na rozgrzaną patelnię.",
                     "Na to położysz wrapa.", "Po chwili zdejmiesz z patelni i dodasz szynkę, sałatę, mozzarellę i pomidora."], steps
    assert {"nazwa": "jajka", "ilosc": "3", "zrodlo": "mowa"} in c["skladniki"]
    assert {x["nazwa"] for x in c["skladniki"]} >= {"sól", "pieprz", "wrapa", "szynka", "sałata", "mozzarella", "pomidor"}
    assert not any(x.rstrip().endswith("?") for x in c["wskazowki"])
    assert s["rozdzialy"][0]["tytul"] == "Wbijesz do miski 3 jajka"


def test_real_model_football_reel_is_sport_without_duplicate_drills():
    from vidsum.summary import to_markdown
    d, s, eng, log = replay("pancake_touch")
    assert s["typ"] == "sport" and any("z treści wynika „sport”" in x for x in log)
    ex = s["co_masz_zrobic"]["cwiczenia"]
    assert 3 <= len(ex) <= 7 and len({x["nazwa"] for x in ex}) == len(ex), [x["nazwa"] for x in ex]
    md = to_markdown(s)
    assert "? × ?" not in md and "### Ćwiczenia i elementy techniki" in md and "### Kroki" not in md
    assert "żongler" in json.dumps(s, ensure_ascii=False).lower()


def test_story_fact_scoring_quote_by_text_and_scrub():
    from vidsum.story import find_quote, info_score, pick_facts, scrub
    assert info_score("In 2018, the Chinese government bought Royal Mint Court for $343 million.") >= 6
    assert info_score("It is a symbol of the CCP's growing influence and it's a 10.") < 3
    assert info_score("Hey, as a little experiment, our writer Amanda is going to narrate this episode.") < 3
    assert info_score("One of these is the United States.") < 3
    lines = [{"n": i, "t": float(i), "end": i + 1.0, "tekst": t} for i, t in enumerate(
        ["Hey guys, welcome to the channel.", "In 2018, China bought the site for $343 million.", "It was empty.",
         "The plans show over 200 secret rooms.", "That is a lot.", "But in practice, things are more complicated."], 1)]
    by_n = {x["n"]: x for x in lines}
    assert pick_facts(lines, by_n, list(range(1, 10)), set()) == [[2], [4]], "zalew numerów od modelu nie decyduje"
    assert pick_facts(lines, by_n, [3], set(), k=1) == [[2]], "konkret wygrywa ze wskazaniem linii bez treści"
    assert find_quote("But in practice, things are more complicated.", lines, by_n) == [6]
    assert find_quote(4, lines, by_n) == [4] and find_quote("zupełnie inne zdanie", lines, by_n) == []
    assert scrub("Henley (linia 8), baby tee (linie 11 i 12) oraz Tank [F3].") == "Henley, baby tee oraz Tank."


def test_polish_spoken_instructions_and_not_instructions():
    from vidsum.summary import _imperative, _pl_instruction, _short_title
    for t in ("Na to położysz wrapa.", "Kroimy cebulę w kostkę.", "Należy dodać sól.", "Po chwili zdejmiesz z patelni."):
        assert _pl_instruction(t), t
    for t in ("Możesz też użyć masła.", "Mamy tutaj piękne ziemniaki.", "To jest bardzo ważne.", "Gulasz jest gotowy.",
              "Pyszne, wysokobiałkowe śniadanie?"):
        assert not _pl_instruction(t) and not (_imperative(t) and t.startswith(("Możesz", "Mamy"))), t
    assert _short_title("Wbijesz do miski 3 jajka.") == "Wbijesz do miski 3 jajka"
    assert _short_title("Po chwili zdejmiesz z patelni i dodasz szynkę.") == "Po chwili zdejmiesz z patelni"


# ---------------- pierwsze uruchomienie bez PowerShella ----------------
def test_ollama_setup_state_steps(monkeypatch, tmp_path):
    from vidsum import ollama_setup as osu
    models = ["qwen3-vl:4b-instruct", "gemma3:4b"]
    monkeypatch.setattr(osu, "installed_models", lambda host=None, timeout=3: None)
    monkeypatch.setattr(osu, "find_exe", lambda: None)
    st = osu.state(models)
    assert st["krok"] == "zainstaluj" and not st["dziala"] and not st["zainstalowana"] and st["strona"].startswith("https://ollama.com")
    monkeypatch.setattr(osu, "find_exe", lambda: tmp_path / "ollama.exe")
    assert osu.state(models)["krok"] == "uruchom" and osu.state(models)["zainstalowana"]
    monkeypatch.setattr(osu, "installed_models", lambda host=None, timeout=3: ["gemma3:4b"])
    st = osu.state(models)
    assert st["krok"] == "pobierz" and [m["pobrany"] for m in st["modele"]] == [False, True]
    monkeypatch.setattr(osu, "installed_models", lambda host=None, timeout=3: models + ["inny:latest"])
    assert osu.state(models)["krok"] == "gotowe"
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "2")
    assert osu.state(models)["rownolegle"] == 2
    assert osu.state(["gemma3"])["modele"] == [{"nazwa": "gemma3", "pobrany": False}]        # bez „:latest” w Ollamie


def test_ollama_setup_task_reports_progress_and_errors():
    import time
    from vidsum.ollama_setup import Task
    task = Task()
    gate = __import__("threading").Event()

    def slow(t, x):
        t.set(etap=f"krok {x}", procent=40)
        gate.wait(5)

    assert task.run("modele", slow, 7) is True
    time.sleep(0.05)
    snap = task.snapshot()
    assert snap["trwa"] and snap["etap"] == "krok 7" and snap["procent"] == 40 and snap["co"] == "modele"
    assert task.run("instalacja", slow, 1) is False, "drugi krok nie startuje, gdy pierwszy trwa"
    gate.set()
    task.thread.join(5)
    assert not task.snapshot()["trwa"]

    def boom(t):
        raise RuntimeError("Nie udało się pobrać instalatora")

    task.run("instalacja", boom)
    task.thread.join(5)
    assert task.snapshot()["blad"] == "Nie udało się pobrać instalatora" and not task.snapshot()["trwa"]


def test_ollama_setup_pull_streams_progress(monkeypatch):
    """Pobieranie modeli przez API Ollamy: postęp z pól completed/total, pobrane modele pomijane, błąd po polsku."""
    import http.server
    import threading
    from vidsum import ollama_setup as osu
    pulled: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = json.dumps({"models": [{"name": "gemma3:4b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            model = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["model"]
            pulled.append(model)
            rows = ([{"error": "pull model manifest: file does not exist"}] if model == "zly:model" else
                    [{"status": "pulling", "total": 4_000_000_000, "completed": 1_000_000_000},
                     {"status": "pulling", "total": 4_000_000_000, "completed": 4_000_000_000}, {"status": "success"}])
            b = "".join(json.dumps(r) + "\n" for r in rows).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        seen: list[dict] = []
        task = osu.Task()
        orig = task.set
        task.set = lambda **kw: (seen.append(kw), orig(**kw))[1]
        osu.pull(task, ["qwen3-vl:4b-instruct", "gemma3:4b"], host)
        assert pulled == ["qwen3-vl:4b-instruct"], "gemma3:4b już jest — nie pobieramy drugi raz"
        assert any(x.get("procent") == 25 and "1.0 z 4.0 GB" in x.get("etap", "") for x in seen)
        assert task.snapshot()["procent"] == 100 and task.snapshot()["etap"] == "Modele pobrane."
        with pytest.raises(RuntimeError, match="zly:model"):
            osu.pull(osu.Task(), ["zly:model"], host)
        with pytest.raises(RuntimeError, match="nie odpowiada"):
            osu.pull(osu.Task(), ["x"], "http://127.0.0.1:9")
    finally:
        srv.shutdown()


def test_ollama_setup_install_only_on_windows_and_start_needs_exe(monkeypatch):
    from vidsum import ollama_setup as osu
    monkeypatch.setattr(osu.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="tylko w Windows"):
        osu.install(osu.Task())
    with pytest.raises(RuntimeError, match="tylko w Windows"):
        osu.enable_parallel(osu.Task())
    monkeypatch.setattr(osu, "installed_models", lambda host=None, timeout=3: None)
    monkeypatch.setattr(osu, "find_exe", lambda: None)
    with pytest.raises(RuntimeError, match="najpierw go zainstaluj"):
        osu.start()
    # jest plik programu: startujemy `ollama serve` z dwoma zapytaniami naraz i czekamy na API
    started = {}

    def fake_popen(cmd, **kw):
        started["cmd"], started["env"] = cmd, kw.get("env", {})
        monkeypatch.setattr(osu, "installed_models", lambda host=None, timeout=3: [])

    monkeypatch.setattr(osu, "find_exe", lambda: Path("C:/Users/x/AppData/Local/Programs/Ollama/ollama.exe"))
    monkeypatch.setattr(osu.subprocess, "Popen", fake_popen)
    monkeypatch.delenv("OLLAMA_NUM_PARALLEL", raising=False)
    assert osu.start(wait=3) is True
    assert started["cmd"][1] == "serve" and started["env"]["OLLAMA_NUM_PARALLEL"] == "2" \
        and started["env"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    from vidsum.llm import ollama_parallel
    assert ollama_parallel() == 2, "program wysyła wtedy 2 zapytania naraz"


def test_gui_ollama_setup_endpoint_and_card(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App
    app = App(tmp_path / "wyniki", "tok")
    assert app.models_needed() == ["qwen3-vl:4b-instruct", "gemma3:4b"]
    app.settings["obraz"] = "brak"
    assert app.models_needed() == ["gemma3:4b"], "opis kadrów wyłączony — modelu obrazu nie pobieramy"
    html = (Path(__file__).parents[1] / "vidsum" / "web" / "index.html").read_text(encoding="utf-8")
    for key in ("setup_h", "setup_install", "setup_pull", "setup_par", "setup_recheck", 'id="setup"', '"/api/ollama"'):
        assert key in html, key
    assert html.count("setup_s1_missing:") == 2 and html.count("setup_pull:") == 2, "teksty po polsku i po angielsku"
    readme = (Path(__file__).parents[1] / "packaging" / "CZYTAJ_MNIE.txt").read_text(encoding="utf-8")
    first = readme.split("PIERWSZE URUCHOMIENIE")[1].split("CO MOŻNA WRZUCIĆ")[0]
    assert "bez PowerShella" in first and "winget" not in readme and "setx" not in readme and "Zainstaluj Ollamę" in first


# ---------------- pliki dźwiękowe (mp3, m4a, wav…) ----------------
def _make_mp3(path: Path, seconds: int = 32, cover: bool = False) -> Path:
    from vidsum.tools import find_tool, run
    ff = find_tool("ffmpeg")
    plain = path if not cover else path.with_name(path.stem + "_bez.mp3")
    run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", "-q:a", "9", str(plain)])
    if cover:                                               # okładka albumu = „strumień wideo” attached_pic
        jpg = path.with_suffix(".jpg")
        run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(jpg)])
        run([ff, "-v", "error", "-y", "-i", str(plain), "-i", str(jpg), "-map", "0:a", "-map", "1:v", "-c", "copy",
             "-disposition:v", "attached_pic", "-id3v2_version", "3", str(path)])
    return path


def test_probe_audio_file_with_and_without_cover(tmp_path):
    from vidsum.media import AUDIO_EXT, probe
    info = probe(_make_mp3(tmp_path / "nagranie.mp3"))
    assert not info.has_video and info.has_audio and 31 <= info.duration <= 33 and info.width is None
    cov = probe(_make_mp3(tmp_path / "z_okladka.mp3", cover=True))
    assert not cov.has_video and cov.has_audio and 31 <= cov.duration <= 33, "okładka w mp3 to nie film"
    assert ".mp3" in AUDIO_EXT and ".m4a" in AUDIO_EXT and ".wav" in AUDIO_EXT


def test_audio_beats_cover_whole_recording():
    from vidsum.analysis import audio_beats
    from vidsum.transcribe import Segment
    segs = [Segment(i * 7.0, i * 7.0 + 6.0, f"Zdanie numer {i}.") for i in range(14)]          # 0…97 s
    beats = audio_beats(segs, 100.0)
    assert beats[0]["start"] == 0.0 and beats[-1]["end"] == 100.0 and 3 <= len(beats) <= 4
    assert all(a["end"] == b["start"] for a, b in zip(beats, beats[1:])) and all(b["kadr"] is None for b in beats)
    said = " ".join(b["slychac"]["tekst"] for b in beats)
    assert all(f"Zdanie numer {i}." in said for i in range(14)) and said.count("Zdanie numer 5.") == 1
    empty = audio_beats([], 12.0)
    assert len(empty) == 1 and empty[0]["slychac"]["zrodlo"] == "brak_danych"


def test_mp3_is_summarized_from_speech_without_frames(tmp_path, cue_subs, monkeypatch):
    """Plik mp3: pełny wynik z samej mowy — bez kadrów, bez modelu obrazu i OCR, niezależnie od wybranego trybu."""
    from test_vidsum import FakeOllama
    import http.server
    import threading as th
    from vidsum import pipeline
    from vidsum.pipeline import Options, analyze
    mp3 = _make_mp3(tmp_path / "podcast.mp3", cover=True)
    FakeOllama.calls, FakeOllama.fail_images = [], set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(pipeline, "scene_scores", lambda *a, **k: (_ for _ in ()).throw(AssertionError("analiza scen pliku dźwiękowego")))
        log: list[str] = []
        opt = Options(out_root=tmp_path / "w", transcript_file=cue_subs, ollama_host=f"http://127.0.0.1:{srv.server_address[1]}",
                      vision_model="fake-vl", text_model="fake-txt", mode="pelna")          # użytkownik miał „Pełną”
        out = analyze(str(mp3), opt, log=log.append)
    finally:
        srv.shutdown()
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert _images(FakeOllama.calls) == [] and r["kadry"] == [] and r["napisy_ekranowe"] == []
    assert r["zrodlo"]["wideo"] is False and r["zrodlo"]["audio"] is True and r["ustawienia"]["tryb"] == "mowa"
    assert any("plik dźwiękowy" in x for x in log) and any("Plik dźwiękowy" in g for g in r["luki"])
    assert r["os_czasu"] and r["os_czasu"][0]["kadr"] is None and "kroimy jedną cebulę" in r["os_czasu"][0]["slychac"]["tekst"]
    assert r["streszczenie"]["dane"]["streszczenie"], "streszczenie powstało"
    md = (out / "raport.md").read_text(encoding="utf-8")
    assert "plik dźwiękowy (bez obrazu)" in md and "![kadr]" not in md and "**Obraz**" not in md and "kroimy jedną cebulę" in md
    html = (Path(__file__).parents[1] / "vidsum" / "web" / "index.html").read_text(encoding="utf-8")
    assert ".mp3" in html and "audio/*" in html and 'z.wideo === false' in html
