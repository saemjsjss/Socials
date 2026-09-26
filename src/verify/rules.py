"""
Document rules for each program, taken from the Hangeul document guidelines
(KLP / EAP / BACHELOR / MASTER).

Each DOCS entry describes one required document: how its file is recognised, and the
checks that run on the text read out of it.  Checks are deliberately conservative — a
rule only fails when the evidence is clear; anything doubtful becomes a FLAG for a human.

Verdicts:  PASS (rule satisfied) · FLAG (needs a human eye) · FAIL (rule broken)
           MISSING (no such file uploaded)
"""
from __future__ import annotations

from typing import Dict, List

PROGRAMS = ["KLP", "EAP", "BACHELOR", "MASTER"]

# Minimum bank balance per program, in taka (guideline: Document 08).
MIN_BANK_TAKA = {"KLP": 1_800_000, "EAP": 1_800_000, "BACHELOR": 2_500_000, "MASTER": 2_500_000}

# Master's-only income-tax expectations (Document 9.1).
MIN_TAX_PAID_TAKA = 10_000
MIN_NET_WEALTH_TAKA = 5_000_000

PASSPORT_MIN_MONTHS = 12          # Document 01 — at least 1 year validity left
FAMILY_CERT_MAX_MONTHS = 3        # Document 06 — issued within the last 3 months
BANK_MIN_ACCOUNT_MONTHS = 6       # Document 08 — account at least 6 months old
BANK_MIN_STATEMENT_MONTHS = 6     # Document 08 — last 6 months of transactions
BANK_RELAXED_STATEMENT_MONTHS = 2  # allowed for "excellent accredited" universities
PHOTO_RATIO = 35 / 45             # Document 02 — 3.5 x 4.5 cm
PHOTO_FORMATS = (".jpg", ".jpeg")  # reviewer rule: photo must be JPG/JPEG

# Reviewer rule (bank): the statement's OPENING balance, not just any figure.
MIN_OPENING_BALANCE = {"KLP": 1_800_000, "EAP": 1_800_000,
                       "BACHELOR": 2_200_000, "MASTER": 2_200_000}
PREFERRED_OPENING_MAX = {"BACHELOR": 2_600_000, "MASTER": 2_600_000}

# A colour scan of a mostly-white document still shows coloured seals, stamps and ink,
# but a single pale government stamp on an otherwise white page can be well under 1% of
# the pixels.  0.5% was overtuned and called 36 genuine colour scans greyscale, so the
# bar is the presence of *any* meaningful colour rather than a share of the page.
MIN_COLOUR_PERCENT = 0.08

# Documents whose names must agree with each other and with the portal record.
IDENTITY_DOCS = ["passport", "student_nid", "birth_cert", "father_nid", "mother_nid",
                 "family_cert", "academic"]
# The only document the guideline requires in its online, QR-verifiable form.  Family
# certificates and academic certificates are issued by hand and usually have no QR at all.
QR_DOCS = ["birth_cert"]
# Bangla-only documents must be translated; these words show a translation is present.
TRANSLATION_WORDS = ["translated", "translation", "true copy", "english translation"]
BANGLA_RANGE = ("ঀ", "৿")

# file-name keywords -> document key.  The portal names files consistently
# (passport_*.pdf, family_cert_*.pdf …), so matching on the name is reliable.
FILE_PATTERNS: Dict[str, List[str]] = {
    "passport": ["passport"],
    "photo": ["passport size photo", "picture", "photo"],
    "student_nid": ["student nid", "student_nid", "nid card", "id card cv", "id_card"],
    "birth_cert": ["birth certificate", "birth_cert"],
    "father_nid": ["father nid", "father_nid"],
    "mother_nid": ["mother nid", "mother_nid"],
    "death_cert": ["death certificate", "death_cert"],
    "family_cert": ["family relationship", "family certificate", "family_cert"],
    "academic": ["academic certificate", "academic_cert", "transcript"],
    "bank": ["bank statement", "bank_statement", "solvency", "sanchay", "savings"],
    "trade_license": ["trade license", "trade_license", "tin", "employment certificate"],
    "income_tax": ["income tax", "tax certificate", "tax challan", "acknowledgement", "acknowledgment"],
    "affidavit": ["affidavit"],
    "personal_statement": ["personal statement", "study plan", "personal_statement"],
    "recommendation": ["recommendation"],
    "eca": ["extra curricular", "eca"],
    "language_cert": ["ielts", "topik", "toefl"],
}

# Which documents every program expects.  "required" drives the MISSING check;
# conditional ones are only expected when the student's portal record says so.
REQUIRED: Dict[str, List[str]] = {
    "KLP": ["passport", "photo", "birth_cert", "father_nid", "mother_nid", "family_cert",
            "academic", "bank", "trade_license"],
    "EAP": ["passport", "photo", "birth_cert", "father_nid", "mother_nid", "family_cert",
            "academic", "bank", "trade_license"],
    "BACHELOR": ["passport", "photo", "birth_cert", "father_nid", "mother_nid", "family_cert",
                 "academic", "bank", "trade_license"],
    "MASTER": ["passport", "photo", "birth_cert", "father_nid", "mother_nid", "family_cert",
               "academic", "bank", "trade_license", "income_tax"],
}
OPTIONAL = ["student_nid", "death_cert", "affidavit", "personal_statement", "recommendation", "eca",
            "language_cert"]

# Wording the checks look for in the OCR text (lower-cased, accents/spacing ignored).
NOTARY_WORDS = ["notar", "advocate", "attested", "authenticated", "affidavit", "judge court"]
# A translation must sit on a lawyer's pad OR any licensed/authorised pad.
# "ADV." is the usual abbreviation on notary stamps, and OCR often mangles the name.
LAWYER_PAD_WORDS = ["advocate", "adv.", "adv:", "adv ", "judge court", "bar association",
                    "notary public", "notarised by", "notarized by",
                    "translation centre", "translation center", "govt approved translation",
                    "government approved translation", "translation reg", "approved translation"]
APOSTILLE_WORDS = ["apostille", "e-apostille", "eapostille", "ministry of foreign affairs", "mofa"]
PROVISIONAL_WORDS = ["provisional"]
ONLINE_BIRTH_WORDS = ["bdris", "birth registration", "online", "qr"]
# How Bangladeshi banks label the balance a statement starts from.
OPENING_BALANCE_WORDS = ["opening balance", "previous balance", "initial balance",
                         "starting balance", "brought forward", "b/fwd", "b/f", "bf balance",
                         "balance b/f", "last balance"]
SOLVENCY_WORDS = ["solvency", "to whom it may concern", "certify"]
SEAL_WORDS = ["manager", "branch", "signature", "seal", "authorized signature"]
USD_WORDS = ["usd", "u.s. dollar", "us dollar", "equivalent to usd"]
UNION_ISSUER_WORDS = ["union parishad", "pourashava", "paurasava", "city corporation", "municipality",
                      "poura", "union porishod", "union porishad"]
REF_NO_WORDS = ["ref", "memo", "serial", "certificate no", "registration no"]
TRADE_RUNNING_WORDS = ["renewal", "valid", "fiscal year", "financial year", "validity"]

# Numbers that look like an NID but are not one.  Derived from the corpus: any number
# printed on many different students' documents belongs to the form, the notary or a
# phone line rather than to a person.  1301109623 appears on 49 students' NIDs.
BOILERPLATE_NUMBERS = {"1301109623"}

# Documents the applicant types and prints rather than photocopies from an original.
# "Clear colour scans only" is a rule about copies of issued originals, so it does not
# apply to these — they are black text on white by nature.
TYPED_DOCS = {"personal_statement", "recommendation", "eca"}

# Human-readable titles for the report
TITLES = {
    "passport": "01 Passport", "photo": "02 Photo", "student_nid": "03 Student NID",
    "birth_cert": "04 Birth Certificate", "father_nid": "05 Father NID", "mother_nid": "05 Mother NID",
    "death_cert": "05 Death Certificate", "family_cert": "06 Family Relationship Certificate",
    "academic": "07 Academic Certificate & Transcript", "bank": "08 Bank Solvency & Statement",
    "trade_license": "09 Financial (Trade Licence / TIN / Employment)",
    "income_tax": "09.1 Income Tax", "affidavit": "10 Affidavit",
    "personal_statement": "Personal Statement / Study Plan", "recommendation": "Recommendation Letter",
    "eca": "Extra Curricular (ECA)", "language_cert": "IELTS / TOPIK Certificate",
}
