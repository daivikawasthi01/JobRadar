from dataclasses import dataclass, field
import re
from src.config import FilterConfig
from src.models import Job


@dataclass
class FilterResult:
    matched: bool
    reject_reason: str | None = None  # e.g. "title_excluded", "role_not_included", "experience_too_high", "country_not_allowed", "grad_year_mismatch", "grad_year_unknown"
    country: str | None = None
    min_exp: float | None = None
    max_exp: float | None = None
    exp_signal: str = "unknown"  # "fresher_keyword" | "range" | "plus" | "at_least" | "plain" | "up_to" | "title_entry" | "unknown"
    grad_years: list[int] = field(default_factory=list)

# Precompiled experience regexes
RE_FRESHER_KW = re.compile(
    r"\b(freshers?|new grads?|recent graduates?|entry[- ]level|campus hire|graduate trainee)\b",
    re.IGNORECASE,
)
RE_INTERN = re.compile(r"\b(intern|interns|internship|internships)\b", re.IGNORECASE)
RE_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
RE_UP_TO = re.compile(
    r"(?:up\s*to|upto|less than)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
RE_PLUS = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
RE_AT_LEAST = re.compile(
    r"(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
RE_OR_MORE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s+or\s+more",
    re.IGNORECASE,
)
RE_PLAIN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)['’]?\s*(?:of\s*)?"
    r"(?:relevant\s*|professional\s*|hands-on\s*|prior\s*|work\s*|industry\s*)*"
    r"(?:experience|exp\b)",
    re.IGNORECASE,
)

# Title exclusion patterns
RE_SDE_SENIOR = re.compile(r"\bsde[- ]?(2|3|4|ii|iii|iv)\b", re.IGNORECASE)
RE_LEVEL_ROMAN = re.compile(r"\b(engineer|developer|sde)\s+(ii|iii|iv)\b", re.IGNORECASE)
RE_TRAILING_ROMAN = re.compile(r"\b(ii|iii|iv)\b$", re.IGNORECASE)

# Indian cities / regions
INDIAN_CITIES = [
    "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "mumbai",
    "navi mumbai", "bombay", "delhi", "new delhi", "gurgaon", "gurugram", "noida",
    "greater noida", "kolkata", "ahmedabad", "kochi", "cochin", "coimbatore",
    "jaipur", "indore", "chandigarh", "mohali", "thiruvananthapuram",
    "trivandrum", "nagpur", "bhubaneswar", "vadodara", "surat", "lucknow",
    "mysuru", "mysore",
]

# US State abbreviations (50 states + DC)
US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"
}

US_CITIES = ["san francisco", "new york", "seattle", "austin", "boston", "chicago"]

# Precompiled graduation year / batch regexes
RE_BATCH_RANGE = re.compile(
    r"\b(202\d|203\d)\s*(?:-|–|/|to)\s*(202\d|203\d)\s*(?:batch(?:es)?|passout|passouts|passing\s*out|pass-outs?|graduat\w+)\b",
    re.IGNORECASE,
)
RE_BATCH_POSTFIX = re.compile(
    r"\b(202\d|203\d)\s*(?:batch(?:es)?|passout|passouts|passing\s*out|pass-outs?|graduat\w+)\b",
    re.IGNORECASE,
)
RE_BATCH_PREFIX = re.compile(
    r"\b(?:batch(?:es)?|class|graduating\s*(?:in|between)|passing\s*out\s*in|graduates?\s*of|passouts?\s*of|graduation\s*year|year\s*of\s*graduation|year\s*of\s*passing|yog|yop)\s*(?:of\s*|:\s*|\s*-\s*|is\s*)?(202\d|203\d)(?:\s*(?:-|–|/|to|,|and|or)\s*(202\d|203\d))?\b",
    re.IGNORECASE,
)
RE_BATCH_YEAR_LIST = re.compile(
    r"\b((?:20[23]\d\s*(?:,|/|&|and|or)\s*)+20[23]\d)\s*"
    r"(?:batch(?:es)?|passouts?|passing\s*out|graduat\w+)\b",
    re.IGNORECASE,
)
RE_BATCH_LIST = re.compile(
    r"\b(?:batch(?:es)?|graduates?|passing\s*out|yog|yop)\s*[:=-]\s*([0-9\s,/-]+)",
    re.IGNORECASE,
)

def parse_grad_years(title: str, description: str) -> set[int]:
    """Parse explicit graduation or batch years mentioned in title or description."""
    text = title + "\n" + (description or "")
    years: set[int] = set()

    for match in RE_BATCH_YEAR_LIST.finditer(text):
        years.update(int(year) for year in re.findall(r"\b20[23]\d\b", match.group(1)))

    for m in RE_BATCH_RANGE.finditer(text):
        y1, y2 = int(m.group(1)), int(m.group(2))
        if y1 < y2 and y2 - y1 <= 5:
            for y in range(y1, y2 + 1):
                years.add(y)
        else:
            years.add(y1)
            years.add(y2)

    for m in RE_BATCH_POSTFIX.finditer(text):
        years.add(int(m.group(1)))

    for m in RE_BATCH_PREFIX.finditer(text):
        y1 = int(m.group(1))
        years.add(y1)
        if m.group(2):
            y2 = int(m.group(2))
            if y1 < y2 and y2 - y1 <= 5:
                for y in range(y1, y2 + 1):
                    years.add(y)
            else:
                years.add(y2)

    for m in RE_BATCH_LIST.finditer(text):
        for num in re.findall(r"\b(202\d|203\d)\b", m.group(1)):
            years.add(int(num))

    return years


def detect_country(location: str | None) -> str | None:
    """Detect country from location string."""
    if not location or not isinstance(location, str):
        return None

    loc = location.lower().strip()
    if not loc:
        return None

    # 1. India check
    if re.search(r"\bindia\b", loc):
        return "India"
    for city in INDIAN_CITIES:
        if re.search(r"\b" + re.escape(city) + r"\b", loc):
            return "India"

    # 2. United States check
    if (
        re.search(r"\b(united states|usa|u\.s\.)\b", loc)
        or re.search(r",\s*us\b", loc)
        or loc.endswith(", us")
        or any(re.search(r"\b" + re.escape(c) + r"\b", loc) for c in US_CITIES)
    ):
        return "United States"

    # US state abbreviation as a whole token after comma: e.g. ", ca"
    state_match = re.search(r",\s*([a-z]{2})\b", loc)
    if state_match and state_match.group(1) in US_STATES:
        return "United States"

    # 3. United Kingdom
    if (
        re.search(r"\b(united kingdom|london)\b", loc)
        or re.search(r"\buk\b", loc)
    ):
        return "United Kingdom"

    # 4. Canada
    if re.search(r"\b(canada|toronto|vancouver)\b", loc):
        return "Canada"

    # 5. Singapore
    if re.search(r"\bsingapore\b", loc):
        return "Singapore"

    # 6. Germany
    if re.search(r"\b(germany|berlin|munich|frankfurt)\b", loc):
        return "Germany"

    # 7. Australia
    if re.search(r"\b(australia|sydney|melbourne)\b", loc):
        return "Australia"

    return None


def parse_experience(title: str, description: str) -> tuple[float | None, float | None, str]:
    """Parse experience requirements from title and description.

    Returns (min_exp, max_exp, exp_signal).
    """
    if RE_INTERN.search(title):
        return (0.0, None, "title_entry")

    text = (title + "\n" + (description or "")).lower()

    candidates: list[tuple[float, float | None, str]] = []

    # fresher_keyword -> min=0, max=None
    for _ in RE_FRESHER_KW.finditer(text):
        candidates.append((0.0, None, "fresher_keyword"))

    # range -> min=group1, max=group2
    for m in RE_RANGE.finditer(text):
        try:
            mn = float(m.group(1))
            mx = float(m.group(2))
            if mn < 40 and mx < 40:
                candidates.append((mn, mx, "range"))
        except ValueError:
            pass

    # up_to -> min=0, max=group1
    for m in RE_UP_TO.finditer(text):
        try:
            mx = float(m.group(1))
            if mx < 40:
                candidates.append((0.0, mx, "up_to"))
        except ValueError:
            pass

    # at_least -> min=group1
    for m in RE_AT_LEAST.finditer(text):
        try:
            mn = float(m.group(1))
            if mn < 40:
                candidates.append((mn, None, "at_least"))
        except ValueError:
            pass

    # "N years or more" -> min=N
    for m in RE_OR_MORE.finditer(text):
        try:
            mn = float(m.group(1))
            if mn < 40:
                candidates.append((mn, None, "at_least"))
        except ValueError:
            pass

    # plus -> min=group1
    for m in RE_PLUS.finditer(text):
        try:
            mn = float(m.group(1))
            if mn < 40:
                candidates.append((mn, None, "plus"))
        except ValueError:
            pass

    # plain -> min=group1
    for m in RE_PLAIN.finditer(text):
        try:
            mn = float(m.group(1))
            if mn < 40:
                candidates.append((mn, None, "plain"))
        except ValueError:
            pass

    if candidates:
        # Signal preference tie-breaker priority order
        signal_priority = {
            "fresher_keyword": 0,
            "range": 1,
            "up_to": 2,
            "at_least": 3,
            "plus": 4,
            "plain": 5,
        }

        min_val = min(c[0] for c in candidates)

        # max_exp = smallest max found among range / up_to candidates (if any), else None
        max_candidates = [c[1] for c in candidates if c[1] is not None and c[2] in ("range", "up_to")]
        max_val = min(max_candidates) if max_candidates else None

        # signal = regex that produced the smallest minimum (prefer fresher_keyword on ties)
        min_candidates = [c for c in candidates if c[0] == min_val]
        min_candidates.sort(key=lambda c: signal_priority.get(c[2], 99))
        best_signal = min_candidates[0][2]

        return (min_val, max_val, best_signal)

    # If no candidates: check title for entry level tokens
    title_l = title.lower()
    entry_tokens = [
        "associate", "junior", "jr", "trainee", "graduate",
        "new grad", "entry level", "sde-1", "sde 1", "sde1",
    ]
    for token in entry_tokens:
        if token == "jr":
            if re.search(r"\b(jr|jr\.)\b", title_l):
                return (0.0, None, "title_entry")
        elif token == "sde-1":
            if re.search(r"\bsde-1\b", title_l):
                return (0.0, None, "title_entry")
        else:
            if re.search(r"\b" + re.escape(token) + r"\b", title_l):
                return (0.0, None, "title_entry")

    return (None, None, "unknown")


def evaluate(job: Job, cfg: FilterConfig) -> FilterResult:
    result = _evaluate(job, cfg)
    result.grad_years = sorted(parse_grad_years(job.title, job.description))
    if not result.matched or not cfg.target_grad_years:
        return result

    if result.grad_years:
        if not set(result.grad_years) & set(cfg.target_grad_years):
            result.matched = False
            result.reject_reason = "grad_year_mismatch"
    elif not cfg.allow_unspecified_grad_year:
        result.matched = False
        result.reject_reason = "grad_year_unknown"
    return result


def _evaluate(job: Job, cfg: FilterConfig) -> FilterResult:
    """Evaluate a job against the filter configuration.

    Order of checks (stops at first rejection):
    1. Title excluded
    2. Role included
    3. Experience
    4. Country / Location
    """
    title_l = job.title.lower()

    # Always compute exp and country for metadata / debugging
    min_exp, max_exp, exp_signal = parse_experience(job.title, job.description)
    country = detect_country(job.location)

    # 1. Excluded title check
    for token in cfg.roles_exclude_title:
        tok = token.lower().strip()
        if tok == "sr":
            if re.search(r"\b(sr|sr\.)\b", title_l):
                return FilterResult(
                    matched=False,
                    reject_reason="title_excluded",
                    country=country,
                    min_exp=min_exp,
                    max_exp=max_exp,
                    exp_signal=exp_signal,
                )
        else:
            if re.search(r"\b" + re.escape(tok) + r"\b", title_l):
                return FilterResult(
                    matched=False,
                    reject_reason="title_excluded",
                    country=country,
                    min_exp=min_exp,
                    max_exp=max_exp,
                    exp_signal=exp_signal,
                )

    if (
        RE_SDE_SENIOR.search(title_l)
        or RE_LEVEL_ROMAN.search(title_l)
        or RE_TRAILING_ROMAN.search(title_l)
    ):
        return FilterResult(
            matched=False,
            reject_reason="title_excluded",
            country=country,
            min_exp=min_exp,
            max_exp=max_exp,
            exp_signal=exp_signal,
        )

    if cfg.require_title_any and not any(
        re.search(r"\b" + re.escape(token.lower()) + r"\b", title_l)
        for token in cfg.require_title_any
    ):
        return FilterResult(
            matched=False,
            reject_reason="title_required_missing",
            country=country,
            min_exp=min_exp,
            max_exp=max_exp,
            exp_signal=exp_signal,
        )

    # 2. Role included check
    matched_role = False
    for role_token in cfg.roles_include:
        tok = role_token.lower().strip()
        if re.search(r"\b" + re.escape(tok) + r"\b", title_l):
            matched_role = True
            break

    if not matched_role:
        return FilterResult(
            matched=False,
            reject_reason="role_not_included",
            country=country,
            min_exp=min_exp,
            max_exp=max_exp,
            exp_signal=exp_signal,
        )

    # 3. Experience check
    if min_exp is not None and min_exp > cfg.max_min_experience:
        return FilterResult(
            matched=False,
            reject_reason="experience_too_high",
            country=country,
            min_exp=min_exp,
            max_exp=max_exp,
            exp_signal=exp_signal,
        )

    if min_exp is None and not cfg.keep_unknown_experience:
        return FilterResult(
            matched=False,
            reject_reason="experience_unknown",
            country=country,
            min_exp=min_exp,
            max_exp=max_exp,
            exp_signal=exp_signal,
        )

    # 4. Country check
    loc_clean = (job.location or "").lower().strip()
    if loc_clean == "remote":
        if not cfg.include_remote_unspecified:
            return FilterResult(
                matched=False,
                reject_reason="country_unknown",
                country=country,
                min_exp=min_exp,
                max_exp=max_exp,
                exp_signal=exp_signal,
            )
    else:
        if not loc_clean or country is None:
            return FilterResult(
                matched=False,
                reject_reason="country_unknown",
                country=country,
                min_exp=min_exp,
                max_exp=max_exp,
                exp_signal=exp_signal,
            )

        if cfg.countries and country not in cfg.countries:
            return FilterResult(
                matched=False,
                reject_reason="country_not_allowed",
                country=country,
                min_exp=min_exp,
                max_exp=max_exp,
                exp_signal=exp_signal,
            )

    return FilterResult(
        matched=True,
        reject_reason=None,
        country=country,
        min_exp=min_exp,
        max_exp=max_exp,
        exp_signal=exp_signal,
    )
