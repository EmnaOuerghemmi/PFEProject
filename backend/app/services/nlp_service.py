import re
from datetime import datetime
from collections import Counter
import logging

logger = logging.getLogger(__name__)

# Month name to number mapping (French + English)
MONTH_MAP = {
    'jan': 1, 'january': 1, 'janvier': 1,
    'feb': 2, 'february': 2, 'fevrier': 2, 'février': 2,
    'mar': 3, 'march': 3, 'mars': 3,
    'apr': 4, 'april': 4, 'avr': 4, 'avril': 4,
    'may': 5, 'mai': 5,
    'jun': 6, 'june': 6, 'juin': 6,
    'jul': 7, 'july': 7, 'juillet': 7,
    'aug': 8, 'august': 8, 'aout': 8, 'août': 8,
    'sep': 9, 'sept': 9, 'september': 9, 'septembre': 9,
    'oct': 10, 'october': 10, 'octobre': 10,
    'nov': 11, 'november': 11, 'novembre': 11,
    'dec': 12, 'december': 12, 'decembre': 12, 'décembre': 12,
}

# Comprehensive skills database
SKILLS_DB = {
    "python", "java", "javascript", "typescript", "csharp", "php", "ruby", "go", "rust", "kotlin",
    "swift", "objectivec", "scala", "perl", "r", "matlab", "sql", "nosql", "postgresql", "mysql",
    "mongodb", "redis", "elasticsearch", "cassandra", "oracle", "mssql", "sqlite",
    "html", "css", "react", "angular", "vue", "svelte", "nextjs", "nuxtjs", "gatsby",
    "fastapi", "django", "flask", "express", "nestjs", "springboot", "spring", "asp",
    "node", "nodejs", "deno", "graphql", "rest", "soap", "grpc",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ansible", "jenkins", "gitlab", "github",
    "git", "svn", "cicd", "devops", "linux", "windows", "macos", "bash", "shell", "powershell",
    "ai", "ml", "machine learning", "deep learning", "tensorflow", "pytorch", "keras", "scikit", "nlp",
    "data science", "big data", "spark", "hadoop", "etl", "analytics", "tableau", "powerbi",
    "agile", "scrum", "kanban", "jira", "confluence", "slack", "communication", "leadership",
    "problem solving", "teamwork", "project management", "planning", "analysis", "design",
    "testing", "qa", "qaa", "manual testing", "automation", "pytest", "junit", "selenium", "cypress",
    "security", "cryptography", "penetration testing", "oauth", "jwt", "ssl", "tls",
    "performance", "optimization", "scaling", "caching", "monitoring", "logging",
    "microservices", "monolithic", "serverless", "lambda", "api", "middleware", "mvc", "mvvm",
    "responsive design", "ux", "ui", "figma", "sketch", "xd", "prototype",
    "mobile", "ios", "android", "flutter", "react native", "xamarin",
    "english", "french", "spanish", "german", "italian", "portuguese", "arabic", "chinese",
    "japanese", "russian", "writing", "presentation", "negotiation",
}

# Education level keywords
EDUCATION_KEYWORDS = {
    "phd": {"phd", "doctorate", "doctorat", "doctor of philosophy", "ph.d"},
    "master": {"master", "msc", "mba", "dea", "dess", "diplôme d'études approfondies", "master degree", "m.sc", "master's"},
    "ingenieur": {"ingénieur", "ingenieur", "diplôme d'ingénieur", "diplome d'ingenieur", "engineering degree", "engineer's degree"},
    "bachelor": {"bachelor", "bsc", "licence", "dut", "bts", "bachelor degree", "b.sc", "bs", "b.a", "licence degree"},
}

# Job title keywords
JOB_TITLES = {
    "developer", "engineer", "architect", "manager", "lead", "senior", "junior", "intern",
    "analyst", "specialist", "consultant", "director", "vp", "cto", "ceo", "cfo", "coo",
    "devops", "datascientist", "designer", "product", "scrum", "agile", "qa", "tester",
    "researcher", "scientist", "professor", "instructor", "trainer", "mentor",
    "administrator", "dba", "sysadmin", "security", "fullstack",
}

# Stopwords for keyword extraction (French + English)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by",
    "from", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can",
    "that", "this", "these", "those", "which", "who", "whom", "whose", "what", "when", "where",
    "why", "how", "all", "each", "every", "both", "such", "so", "more", "most", "other", "some",
    "any", "as", "it", "its", "if", "up", "out", "about", "into", "through", "during",
    "le", "la", "les", "un", "une", "des", "et", "ou", "mais", "en", "à", "de", "du", "par",
    "pour", "sur", "dans", "avec", "sans", "qui", "que", "où", "comment", "quand", "pourquoi",
    "tout", "tous", "chaque", "autre", "même", "très", "plus", "moins", "aussi", "est", "sont",
    "aux", "ce", "mon", "ton", "son", "notre", "votre", "leur", "je", "tu", "il", "elle",
    "nous", "vous", "ils", "elles", "me", "te", "se", "lui", "eux", "y",
}

# --- Date range extraction patterns ---

_CURRENT = (
    r'(?:present|présent|now|current|today'
    r"|aujourd'hui|maintenant|actuel(?:le)?|en\s+cours)"
)
_SEP = r'\s*[-–—]\s*'
# Years 1900-2099
_YEAR = r'(?:19|20)\d{2}'
# Month names (French + English, longest alternatives first to avoid partial matches)
_MWORD = (
    r'(?:january|janvier|jan'
    r'|february|f[eé]vrier|feb'
    r'|march|mars|mar'
    r'|april|avril|avr|apr'
    r'|may|mai'
    r'|june|juin|jun'
    r'|july|juillet|jul'
    r'|august|ao[uû]t|aout|aug'
    r'|september|septembre|sept|sep'
    r'|october|octobre|oct'
    r'|november|novembre|nov'
    r'|december|d[eé]cembre|dec'
    r')'
)

# Pattern 2: "Jan 2022 - Dec 2024" or "Janvier 2022 - Présent"
_PAT_MONTH_YEAR = re.compile(
    rf'({_MWORD})\.?\s+({_YEAR}){_SEP}(?:({_MWORD})\.?\s+({_YEAR})|({_CURRENT}))',
    re.IGNORECASE,
)
# Pattern 3: "03/2021 - 08/2022" or "03/2021 - Present"
_PAT_MM_YYYY = re.compile(
    rf'(1[0-2]|0?[1-9])/({_YEAR}){_SEP}(?:(1[0-2]|0?[1-9])/({_YEAR})|({_CURRENT}))',
    re.IGNORECASE,
)
# Pattern 1: "2022 - 2024" or "2022 - Present" (year only, used last)
_PAT_YEAR_ONLY = re.compile(
    rf'({_YEAR}){_SEP}(?:({_YEAR})|({_CURRENT}))',
    re.IGNORECASE,
)

# Section detection: start of the experience block
_EXP_SECTION_START = re.compile(
    r'(?:^|\n)\s*(?:exp[eé]riences?\s+professionnelles?|professional\s+experience|'
    r'work\s+experience|parcours\s+professionnel|historique\s+professionnel|'
    r'exp[eé]rience)',
    re.IGNORECASE | re.MULTILINE,
)
# Section headers that typically follow experience (end of experience block).
#
# La version précédente exigeait que le mot-clé soit SEUL sur sa ligne et en
# tête de celle-ci. Deux formulations très courantes échappaient donc à la
# détection : un qualificatif AVANT le mot-clé (« SOFT SKILLS », « HARD
# SKILLS ») et un qualificatif APRÈS (« FORMATION ACADÉMIQUE », « COMPÉTENCES
# TECHNIQUES »). Sur un CV réel, la section « expérience » débordait alors
# jusqu'au bloc formation et ses années d'études étaient comptées comme de
# l'expérience professionnelle — 5,9 ans au lieu de 2,7.
#
# On accepte donc quelques mots autour du mot-clé, tout en gardant l'exigence
# d'une LIGNE COURTE : c'est ce qui distingue un titre de section d'une phrase
# qui mentionnerait le même mot.
_SECTION_KEYWORD = (
    r'formations?|[eé]ducations?|[eé]tudes?|dipl[oô]mes?|parcours\s+acad[eé]mique|'
    r'comp[eé]tences?|skills?|langues?|languages?|certifications?|'
    r'loisirs?|centres?\s+d.int[eé]r[eê]ts?|int[eé]r[eê]ts?|hobbies|'
    r'r[eé]f[eé]rences?|projets?|publications?|b[eé]n[eé]volat'
)
_NEXT_SECTION = re.compile(
    rf'(?:^|\n)[ \t]*(?:[\w&/\'-]+[ \t]+){{0,2}}(?:{_SECTION_KEYWORD})'
    rf'(?:[ \t]+[\w&/\'-]+){{0,3}}[ \t]*(?:\n|$)',
    re.IGNORECASE | re.MULTILINE,
)

# Lignes décrivant un cursus scolaire plutôt qu'un poste. Une date portée par
# une telle ligne n'est pas de l'expérience professionnelle — garde-fou utile
# quand le CV n'a aucun en-tête de section exploitable.
# « ingénieur » en est volontairement absent : en Tunisie c'est d'abord un
# INTITULÉ DE POSTE (« Ingénieur logiciel — Société X »), et l'écarter ferait
# disparaître de vraies expériences. Les cursus le mentionnant restent captés
# par « diplôme » (« Diplôme national d'ingénieur »).
_EDUCATION_LINE = re.compile(
    r'(licence|master|doctorat|baccalaur[eé]at|\bbac\b|dipl[oô]me|'
    r'universit[eé]|facult[eé]|[eé]cole|institut|iset|insat|enis|enit|esprit|'
    r'cycle\s+pr[eé]paratoire|pr[eé]pa)',
    re.IGNORECASE,
)


class NLPService:
    @staticmethod
    def extract_skills(text: str, skills_db: set = SKILLS_DB) -> list[str]:
        """Extract skills from text using keyword matching."""
        if not text:
            return []

        text_lower = text.lower()
        found_skills = set()

        for skill in skills_db:
            pattern = rf"\b{re.escape(skill)}\b"
            if re.search(pattern, text_lower):
                found_skills.add(skill)

        return sorted(list(found_skills))

    # ------------------------------------------------------------------
    # Experience extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _month_to_abs(month: int, year: int) -> int:
        """Convert (month, year) to absolute month count (year*12 + month)."""
        return year * 12 + month

    @staticmethod
    def _extract_date_ranges(text: str) -> list[tuple[int, int]]:
        """
        Extract work-period date ranges from CV text.
        Returns a list of (start_abs_month, end_abs_month) pairs.
        """
        now = datetime.now()
        current_abs = NLPService._month_to_abs(now.month, now.year)
        ranges: list[tuple[int, int]] = []
        # Track matched spans to avoid double-counting overlapping patterns
        matched_spans: list[tuple[int, int]] = []

        def _span_used(span: tuple[int, int]) -> bool:
            s, e = span
            return any(s < me and e > ms for ms, me in matched_spans)

        def _ligne_de(position: int) -> str:
            """Ligne portant cette position — pour juger de sa nature."""
            debut = text.rfind("\n", 0, position) + 1
            fin = text.find("\n", position)
            return text[debut: fin if fin != -1 else len(text)]

        def _retenir(start_abs: int, end_abs: int, span: tuple[int, int]) -> None:
            """
            Enregistre une période, après deux garde-fous.

            1. Une date portée par une ligne de cursus scolaire (« Diplôme
               d'ingénieur — 2021-2024 ») n'est pas de l'expérience
               professionnelle. Ce contrôle protège même quand le découpage en
               sections a échoué.
            2. Une période ne peut pas s'étendre dans le futur : « 2025-2026 »
               saisi en septembre 2026 signifie « en cours », pas « jusqu'en
               décembre ». Sans ce plafond, on comptait des mois non travaillés.
            """
            if _EDUCATION_LINE.search(_ligne_de(span[0])):
                return
            end_abs = min(end_abs, current_abs)
            if start_abs <= end_abs:
                ranges.append((start_abs, end_abs))
                matched_spans.append(span)

        # --- Pattern 2: "Month YYYY - Month YYYY / Present" ---
        for m in _PAT_MONTH_YEAR.finditer(text):
            start_mword = m.group(1).lower()[:3]
            start_year = int(m.group(2))
            start_month = MONTH_MAP.get(start_mword, 1)
            start_abs = NLPService._month_to_abs(start_month, start_year)

            if m.group(5):  # "Present"
                end_abs = current_abs
            else:
                end_mword = m.group(3).lower()[:3]
                end_year = int(m.group(4))
                end_month = MONTH_MAP.get(end_mword, 12)
                end_abs = NLPService._month_to_abs(end_month, end_year)

            if 1970 * 12 <= start_abs:
                _retenir(start_abs, end_abs, (m.start(), m.end()))

        # --- Pattern 3: "MM/YYYY - MM/YYYY / Present" ---
        for m in _PAT_MM_YYYY.finditer(text):
            if _span_used((m.start(), m.end())):
                continue
            start_month = int(m.group(1))
            start_year = int(m.group(2))
            start_abs = NLPService._month_to_abs(start_month, start_year)

            if m.group(5):  # "Present"
                end_abs = current_abs
            else:
                end_month = int(m.group(3))
                end_year = int(m.group(4))
                end_abs = NLPService._month_to_abs(end_month, end_year)

            if 1 <= start_month <= 12 and 1970 * 12 <= start_abs:
                _retenir(start_abs, end_abs, (m.start(), m.end()))

        # --- Pattern 1: "YYYY - YYYY / Present" (year only, last resort) ---
        for m in _PAT_YEAR_ONLY.finditer(text):
            if _span_used((m.start(), m.end())):
                continue
            start_year = int(m.group(1))
            start_abs = NLPService._month_to_abs(1, start_year)  # assume January

            if m.group(3):  # "Present"
                end_abs = current_abs
            else:
                end_year = int(m.group(2))
                end_abs = NLPService._month_to_abs(12, end_year)  # assume December

            if 1970 * 12 <= start_abs:
                _retenir(start_abs, end_abs, (m.start(), m.end()))

        return ranges

    @staticmethod
    def _merge_periods(periods: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Merge overlapping or adjacent work periods to avoid double-counting."""
        if not periods:
            return []
        sorted_periods = sorted(periods)
        merged: list[tuple[int, int]] = [sorted_periods[0]]
        for start, end in sorted_periods[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end + 1:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _find_experience_text(text: str) -> str:
        """
        Isolate the professional experience section of the CV to avoid
        counting education or project dates as work experience.

        Returns the experience section if section headers are found,
        otherwise returns the full text as fallback.
        """
        exp_match = _EXP_SECTION_START.search(text)
        if not exp_match:
            return text

        exp_start = exp_match.end()
        # Look for the next major section at least 30 chars after the header
        next_match = _NEXT_SECTION.search(text, exp_start + 30)
        exp_end = next_match.start() if next_match else len(text)

        section = text[exp_start:exp_end].strip()
        # Only use the isolated section if it's substantial
        return section if len(section) > 20 else text

    @staticmethod
    def extract_experience_years(text: str) -> float | None:
        """
        Calculate total years of professional experience from the CV.

        Strategy:
        1. Isolate the experience section (avoids counting education dates).
        2. Extract date ranges, merge overlaps, sum durations.
        3. Fallback to explicit "X ans d'expérience" mention.
        """
        if not text:
            return None

        # Primary: compute from date ranges in the experience section only
        exp_text = NLPService._find_experience_text(text)
        ranges = NLPService._extract_date_ranges(exp_text)
        if ranges:
            merged = NLPService._merge_periods(ranges)
            total_months = sum(end - start for start, end in merged)
            years = round(total_months / 12, 1)
            if years > 0:
                return years

        # Fallback: explicit mention ("3 ans d'expérience", "5 years of experience")
        # La liaison française « d' » / « de » manquait : « 5 ans d'expérience »,
        # la formulation la plus courante sur un CV francophone, n'était jamais
        # reconnue et le repli ne servait donc à rien.
        pattern = (
            r"(\d+(?:\.\d+)?)\+?\s*(?:years?|ans?|années?)"
            r"\s*(?:d['’]|de\s+|of\s+)?\s*(?:experience|expérience|expérience)"
        )
        matches = re.findall(pattern, text.lower())
        if matches:
            try:
                return max(float(m) for m in matches)
            except ValueError:
                pass

        return None

    @staticmethod
    def extract_education_level(text: str) -> str:
        """Extract education level from text."""
        if not text:
            return "NONE"

        text_lower = text.lower()
        found_levels = []

        for level, keywords in EDUCATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_levels.append(level)
                    break

        if not found_levels:
            return "NONE"

        level_priority = {"phd": 3, "master": 2, "ingenieur": 2, "bachelor": 1, "none": 0}
        return max(found_levels, key=lambda x: level_priority.get(x, 0))

    @staticmethod
    def extract_job_titles(text: str) -> list[str]:
        """Extract job titles from text."""
        if not text:
            return []

        text_lower = text.lower()
        found_titles = []

        for title in JOB_TITLES:
            pattern = rf"\b{re.escape(title)}\b"
            if re.search(pattern, text_lower):
                found_titles.append(title)

        return sorted(list(set(found_titles)))

    @staticmethod
    def extract_keywords(text: str, top_n: int = 30) -> list[str]:
        """Extract top keywords from text (frequency-based, excluding stopwords)."""
        if not text:
            return []

        text_lower = text.lower()
        words = re.findall(r"\b[a-z0-9]+\b", text_lower)

        filtered_words = [w for w in words if w not in STOPWORDS and len(w) > 2]
        if not filtered_words:
            return []

        word_freq = Counter(filtered_words)
        top_keywords = [word for word, _ in word_freq.most_common(top_n)]

        return top_keywords

    @staticmethod
    def extract_all(text: str) -> dict:
        """Extract all information from CV text."""
        return {
            "skills": NLPService.extract_skills(text),
            "experience_years": NLPService.extract_experience_years(text),
            "education_level": NLPService.extract_education_level(text),
            "job_titles": NLPService.extract_job_titles(text),
            "keywords": NLPService.extract_keywords(text),
        }


nlp_service = NLPService()
