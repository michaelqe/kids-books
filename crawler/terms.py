"""English for the Estonian headings and statuses we show. Unknown terms pass through."""
from __future__ import annotations

import re

SUBJECTS = {
    # animals
    "loomad": "animals", "koduloomad": "farm animals", "metsloomad": "wild animals",
    "lemmikloomad": "pets", "koerad": "dogs", "kassid": "cats", "karud": "bears",
    "jänesed": "rabbits", "küülikud": "rabbits", "hiired": "mice", "rebased": "foxes",
    "hundid": "wolves", "linnud": "birds", "kanad": "chickens", "pardid": "ducks",
    "öökullid": "owls", "kalad": "fish", "putukad": "insects", "liblikad": "butterflies",
    "mesilased": "bees", "elevandid": "elephants", "lõvid": "lions", "ahvid": "monkeys",
    "kaelkirjakud": "giraffes", "pingviinid": "penguins", "siilid": "hedgehogs",
    "konnad": "frogs", "hobused": "horses", "lehmad": "cows", "lambad": "sheep",
    "sead": "pigs", "dinosaurused": "dinosaurs", "draakonid": "dragons",
    "ükssarvikud": "unicorns", "vaalad": "whales", "haid": "sharks",
    # things that go
    "sõidukid": "vehicles", "autod": "cars", "veoautod": "trucks", "rongid": "trains",
    "lennukid": "planes", "laevad": "boats", "paadid": "boats", "traktorid": "tractors",
    "ehitusmasinad": "construction vehicles", "tuletõrjeautod": "fire engines",
    "jalgrattad": "bikes", "kosmos": "space", "raketid": "rockets",
    # first concepts
    "värvid": "colours", "numbrid": "numbers", "loendamine": "counting",
    "arvud": "numbers", "tähestik": "alphabet", "tähed": "letters", "kujundid": "shapes",
    "vastandid": "opposites", "sõnavara": "first words", "kellaaeg": "telling time",
    # "inglise" (English) marks the language, not a topic; the language filter covers it.
    # everyday life
    "uni": "sleep", "magamaminek": "bedtime", "unejutud": "bedtime stories",
    "õhtujutud": "bedtime stories", "perekond": "family", "emad": "mothers",
    "isad": "fathers", "vanavanemad": "grandparents", "vanaemad": "grandmothers",
    "vanaisad": "grandfathers", "õed": "sisters", "vennad": "brothers",
    "õed-vennad": "siblings", "beebid": "babies", "imikud": "babies", "lapsed": "children",
    "sõprus": "friendship", "sõbrad": "friends", "lasteaiad": "nursery school",
    "kool": "school", "koolid": "schools", "toit": "food", "söömine": "eating",
    "potitreening": "potty training", "pesemine": "washing", "hügieen": "hygiene",
    "riided": "clothes", "riietumine": "getting dressed", "mänguasjad": "toys",
    "mängud": "games", "kodu": "home", "kolimine": "moving house",
    "arstid": "doctors", "haigused": "illness", "hambad": "teeth",
    # feelings
    "tunded": "feelings", "emotsioonid": "emotions", "hirm": "fear", "viha": "anger",
    "kurbus": "sadness", "rõõm": "happiness", "armastus": "love", "julgus": "courage",
    "headus": "kindness", "jagamine": "sharing", "lahkus": "kindness",
    # seasons and festivals
    "aastaajad": "seasons", "kevad": "spring", "suvi": "summer", "sügis": "autumn",
    "talv": "winter", "lumi": "snow", "vihm": "rain", "ilm": "weather",
    "jõulud": "Christmas", "jõuluvana": "Father Christmas", "lihavõtted": "Easter",
    "sünnipäevad": "birthdays", "halloween": "Halloween", "pühad": "holidays",
    # places and nature
    "meri": "the sea", "rand": "the beach", "mets": "the forest", "talud": "farms",
    "maaelu": "country life", "linnad": "cities", "aed": "the garden", "aiad": "gardens",
    "loodus": "nature", "taimed": "plants", "puud": "trees", "lilled": "flowers",
    "keskkonnakaitse": "the environment", "veekogud": "water",
    # characters
    "printsessid": "princesses", "piraadid": "pirates", "nõiad": "witches",
    "kummitused": "ghosts", "robotid": "robots", "koletised": "monsters",
    "päkapikud": "elves", "haldjad": "fairies", "superkangelased": "superheroes",
    "muusika": "music", "sport": "sport", "jalgpall": "football",
    # the natural world (v2: adult nature non-fiction)
    "imetajad": "mammals", "roomajad": "reptiles", "kahepaiksed": "amphibians", "seened": "fungi",
    "ilmastik": "weather", "meteoroloogia": "weather", "kliima": "climate",
    "kliimamuutused": "climate change", "pilved": "clouds", "äike": "thunderstorms", "tormid": "storms",
    "astronoomia": "astronomy", "tähed": "stars", "planeedid": "planets", "päikesesüsteem": "the solar system",
    "kuu": "the moon", "geoloogia": "geology", "kivimid": "rocks", "mineraalid": "minerals",
    "vulkaanid": "volcanoes", "maavärinad": "earthquakes", "mäed": "mountains", "jõed": "rivers",
    "järved": "lakes", "ookeanid": "oceans", "metsad": "forests", "sood": "bogs", "rannad": "beaches",
    "ökoloogia": "ecology", "looduskaitse": "nature conservation", "fossiilid": "fossils",
    "loomade käitumine": "animal behaviour", "linnuvaatlus": "birdwatching", "evolutsioon": "evolution",
    "inimkeha": "the human body", "teadus": "science", "eksperimendid": "experiments",
}

GENRES = {
    "pildiraamatud": "picture books", "lastekirjandus": "children's books",
    "luuletused": "poems", "lasteluule": "poems", "muinasjutud": "fairy tales",
    "jutud": "stories", "jutustused": "stories", "vigurraamatud": "novelty books",
    "papp-raamatud": "board books", "pappraamatud": "board books",
    "katsumisraamatud": "touch-and-feel", "heliraamatud": "sound books",
    "voldikraamatud": "pop-up books", "klappraamatud": "lift-the-flap books",
    "ruumilised raamatud": "pop-up books", "aimekirjandus": "non-fiction",
    "õpperaamatud": "learning books", "tegevusraamatud": "activity books",
    "koomiksid": "comics", "pildiromaanid": "graphic novels", "naljad": "jokes",
    "mõistatused": "riddles", "laulud": "songs", "lastelaulud": "nursery songs",
    "liisusalmid": "nursery rhymes", "piltsõnastikud": "picture dictionaries",
    "sõnaraamatud": "dictionaries", "entsüklopeediad": "encyclopaedias",
    "värvimisraamatud": "colouring books", "kleepsuraamatud": "sticker books",
    "noorsookirjandus": "teen fiction", "koomiksid": "comics", "graafilised romaanid": "graphic novels",
    "mangad": "manga", "fantaasiaromaanid": "fantasy", "seiklusromaanid": "adventure",
    "põnevusromaanid": "thrillers", "kriminaalromaanid": "crime", "ulmeromaanid": "science fiction",
    "loomajutud": "animal stories", "vigurraamatud": "novelty books", "teatmikud": "reference",
    "määrajad": "field guides", "käsiraamatud": "handbooks", "biograafiad": "biographies",
    "suurtähtraamatud": "early readers", "lektüür": "graded readers", "tegelusraamatud": "activity books",
    "nuputamisülesanded": "puzzles", "piltmõistatused": "picture puzzles", "huumor": "humour",
    "romaanid": "novels", "aimekirjandus": "non-fiction", "õppematerjalid": "learning books",
}

LANGUAGES = {
    "eng": "English", "est": "Estonian", "rus": "Russian", "fin": "Finnish",
    "ger": "German", "swe": "Swedish", "fre": "French", "ukr": "Ukrainian",
    "spa": "Spanish", "ita": "Italian", "lav": "Latvian", "lit": "Lithuanian",
    "nor": "Norwegian", "dan": "Danish", "dut": "Dutch", "pol": "Polish",
    "jpn": "Japanese", "chi": "Chinese", "mul": "Multiple languages",
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def subject_en(term: str) -> str:
    t = term.strip().lower()
    if t in SUBJECTS:
        return SUBJECTS[t]
    # "koerad (loomad)" / "jõulud -- lastekirjandus"
    base = re.split(r"\s*(?:\(|--)", t)[0].strip()
    return SUBJECTS.get(base, "")


def genre_en(term: str) -> str:
    return GENRES.get(term.strip().lower(), "")


def status_en(status: str) -> str:
    s = status.strip().upper()
    if s == "KOHAL":
        return "Available"
    m = re.search(r"(\d{2})[-.](\d{2})[-.](\d{2})", s)
    if ("TAGASTAMIS" in s or "TÄHTAEG" in s) and m:
        day, month, year = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        if 1 <= month <= 12:
            return f"On loan, due {day} {MONTHS[month - 1]} {year}"
    if "TAGASTAMIS" in s or "TÄHTAEG" in s or "LAENUTATUD" in s:
        return "On loan"
    if "TELLITUD" in s or "BRONEERITUD" in s or "RESERV" in s:
        return "Reserved"
    if "KOHAL KASUTAMISEKS" in s or "LUGEMISSAAL" in s:
        return "Library use only"
    if "TÖÖTLEMISEL" in s or "TELLIMISEL" in s:
        return "Being processed"
    if "KADUNUD" in s:
        return "Missing"
    if "TEEL" in s or "TRANSIIT" in s:
        return "In transit"
    return status.strip().capitalize()


def branch_name(location: str) -> str:
    """'TlnRK Kännukuke lastekirjandus' -> 'Kännukuke'."""
    name = re.sub(r"^TlnRK\s+", "", location.strip())
    name = re.sub(r"\s+(lastekirjandus|laste.*|täiskasvanute.*|kojulaenutus.*)$", "", name, flags=re.I)
    return name or location.strip()


# Genres that make a "picture book" not worth showing to parents of toddlers.
EXCLUDED_GENRES = {"värvimisraamatud", "kleepsuraamatud"}


# --- v2 classification (crawler/classify.py) -------------------------------------------

# UDC classes that count as "the natural world" for adult non-fiction. Matched as a prefix
# of the main number (080 $a before any auxiliary). 91 (geography) is left out on purpose:
# in ESTER it is mostly travel guides (913). Add prefixes here to widen the adult scope.
ADULT_NATURE_UDC = (
    "502", "504",   # nature, the environment, conservation
    "52",           # astronomy
    "549",          # minerals
    "55",           # earth sciences: 551.5 weather, 551.21 volcanoes, 552 rocks
    "56",           # palaeontology, fossils
    "57",           # biology, natural history
    "58",           # botany
    "59",           # zoology
    "630", "635.9", # forestry; flowers (gardening as such is out)
)

# Estonian subject headings (650, base form) that mark a book about the natural world.
NATURE_SUBJECTS = {
    "loodus", "loomad", "linnud", "taimed", "puud", "lilled", "seened", "putukad", "liblikad",
    "kalad", "imetajad", "roomajad", "kahepaiksed", "metsloomad", "ilm", "ilmastik",
    "meteoroloogia", "kliima", "kliimamuutused", "pilved", "vihm", "lumi", "äike", "tormid",
    "aastaajad", "kosmos", "astronoomia", "tähed", "planeedid", "päikesesüsteem", "geoloogia",
    "kivimid", "mineraalid", "vulkaanid", "maavärinad", "mäed", "jõed", "järved", "meri",
    "ookeanid", "mets", "metsad", "sood", "keskkonnakaitse", "ökoloogia", "looduskaitse",
    "dinosaurused", "fossiilid", "loomade käitumine", "linnuvaatlus", "evolutsioon", "vaalad",
    "haid", "mesilased", "elevandid", "karud", "hundid", "rebased", "öökullid",
}

# English topic tags from UDC (longest matching prefix wins).
UDC_TOPICS = {
    "502": "nature", "504": "the environment", "52": "space", "523": "the solar system",
    "524": "stars", "549": "minerals", "55": "the earth", "551.5": "weather", "551.21": "volcanoes",
    "551.4": "landscapes", "551.46": "oceans", "552": "rocks", "56": "fossils", "567": "dinosaurs",
    "568": "dinosaurs", "57": "nature", "574": "ecology", "575": "evolution", "58": "plants",
    "582": "plants", "59": "animals", "591": "animals", "594": "sea creatures", "595.7": "insects",
    "595.78": "butterflies", "597": "fish", "598.1": "reptiles", "598.2": "birds", "599": "mammals",
    "61": "the human body", "611": "the human body", "612": "the human body",
    "62": "machines", "629": "vehicles", "629.7": "aircraft", "629.78": "space travel",
    "004": "computers", "641.5": "cooking", "7": "art", "74": "drawing", "78": "music",
    "79": "sport", "9": "history", "91": "geography", "912": "maps", "93": "history", "94": "history",
    "030": "reference", "811": "language learning",
}
