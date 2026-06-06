"""Built-in example tasks for the web UI's task picker.

costbench ranks targets by cost per *successful* outcome, so every preset here
carries a DETERMINISTIC check — the success test is not a matter of opinion:

  - triage / sentiment  → `contains` a fixed label
  - math                → `numeric` (exact integer match)
  - capitals            → `contains` the right city
  - couplet (creative)  → `contains` a required word (checks the constraint was
                          met and the line is on-topic — NOT artistic quality)

Each preset is
``{id, name, level, task:{system, promptTemplate, check}, cases:[...]}``.
The first preset (support triage) is the default and matches the bundled
``examples/classification.yaml``. Purely subjective tasks (e.g. "is this poem
good?") are intentionally absent: that needs an LLM-as-judge, which costbench
keeps out of core checks (see ``checks.py``).
"""

from __future__ import annotations

from importlib import resources


def _triage_from_yaml() -> dict:
    import yaml

    raw = yaml.safe_load(
        resources.files("costbench").joinpath("examples/classification.yaml").read_text(
            encoding="utf-8"
        )
    )
    return {
        "id": "triage",
        "name": "Support ticket triage",
        "level": 1,
        "task": {
            "system": raw["task"]["system"],
            "promptTemplate": raw["task"].get("prompt_template", "{input}"),
            "check": raw.get("check", "exact"),
        },
        "cases": [{"input": c["input"], "expect": c["expect"]} for c in raw["cases"]],
    }


_MATH = {
    "id": "math",
    "name": "Grade-school math",
    "level": 1,
    "task": {
        "system": (
            "Solve the problem. Reply with ONLY the final numeric answer — digits "
            "only, no units, no words, no explanation."
        ),
        "promptTemplate": "{input}",
        "check": "numeric",
    },
    "cases": [
        {"input": "What is 17 + 28?", "expect": 45},
        {"input": "What is 12 times 12?", "expect": 144},
        {"input": "What is 144 divided by 12?", "expect": 12},
        {"input": "What is 7 squared?", "expect": 49},
        {"input": "What is the sum of the first 10 positive integers?", "expect": 55},
        {"input": "What is 1000 minus 256?", "expect": 744},
        {"input": "How many minutes are in 3 hours?", "expect": 180},
        {"input": "What is 15% of 200?", "expect": 30},
        {"input": "If x + 5 = 12, what is x?", "expect": 7},
        {"input": "A shirt costs $20 with 25% off. What is the sale price in dollars?", "expect": 15},
        {"input": "A train travels 60 km in 1.5 hours. What is its speed in km/h?", "expect": 40},
        {"input": "A dozen eggs costs $3. How much do 3 dozen cost, in dollars?", "expect": 9},
    ],
}

_CAPITALS = {
    "id": "capitals",
    "name": "World capitals",
    "level": 1,
    "task": {
        "system": "Reply with ONLY the capital city name, nothing else.",
        "promptTemplate": "Country: {input}",
        "check": "contains",
    },
    "cases": [
        {"input": "Japan", "expect": "Tokyo"},
        {"input": "France", "expect": "Paris"},
        {"input": "Italy", "expect": "Rome"},
        {"input": "Egypt", "expect": "Cairo"},
        {"input": "Canada", "expect": "Ottawa"},
        {"input": "Australia", "expect": "Canberra"},
        {"input": "Kenya", "expect": "Nairobi"},
        {"input": "Norway", "expect": "Oslo"},
        {"input": "Peru", "expect": "Lima"},
        {"input": "Cuba", "expect": "Havana"},
        {"input": "Greece", "expect": "Athens"},
        {"input": "Spain", "expect": "Madrid"},
    ],
}

_SENTIMENT = {
    "id": "sentiment",
    "name": "Review sentiment",
    "level": 1,
    "task": {
        "system": (
            "Classify the review sentiment. Reply with exactly one word and "
            "nothing else: POSITIVE or NEGATIVE."
        ),
        "promptTemplate": "Review: {input}",
        "check": "contains",
    },
    "cases": [
        {"input": "Absolutely love this, best purchase ever!", "expect": "POSITIVE"},
        {"input": "Terrible quality, it broke in a day.", "expect": "NEGATIVE"},
        {"input": "Exceeded my expectations, highly recommend.", "expect": "POSITIVE"},
        {"input": "Waste of money, very disappointed.", "expect": "NEGATIVE"},
        {"input": "The staff were friendly and helpful.", "expect": "POSITIVE"},
        {"input": "I will never shop here again.", "expect": "NEGATIVE"},
        {"input": "Fast shipping and great packaging.", "expect": "POSITIVE"},
        {"input": "It stopped working after one week.", "expect": "NEGATIVE"},
        {"input": "Five stars, would buy again.", "expect": "POSITIVE"},
        {"input": "Rude service and cold food.", "expect": "NEGATIVE"},
    ],
}

_COUPLET = {
    "id": "couplet",
    "name": "Rhyming couplet (creative)",
    "level": 1,
    "task": {
        "system": (
            "Write a two-line rhyming couplet about the given topic. The final "
            "word of the second line MUST be the topic word itself."
        ),
        "promptTemplate": "Topic: {input}",
        # Deterministic on the CONSTRAINT (does it include the required word?),
        # not on artistry — costbench scores success, not taste.
        "check": "contains",
    },
    "cases": [
        {"input": "moon", "expect": "moon"},
        {"input": "river", "expect": "river"},
        {"input": "autumn", "expect": "autumn"},
        {"input": "dragon", "expect": "dragon"},
        {"input": "coffee", "expect": "coffee"},
        {"input": "ocean", "expect": "ocean"},
        {"input": "winter", "expect": "winter"},
        {"input": "garden", "expect": "garden"},
    ],
}


_LANGUAGE = {
    "id": "language",
    "name": "Language detection",
    "level": 1,
    "task": {
        "system": "Identify the language of the text. Reply with ONLY the language name in English.",
        "promptTemplate": "Text: {input}",
        "check": "contains",
    },
    "cases": [
        {"input": "Bonjour, comment ça va?", "expect": "French"},
        {"input": "Hola, ¿cómo estás?", "expect": "Spanish"},
        {"input": "Guten Tag, wie geht es Ihnen?", "expect": "German"},
        {"input": "こんにちは、お元気ですか？", "expect": "Japanese"},
        {"input": "Ciao, come stai?", "expect": "Italian"},
        {"input": "Olá, tudo bem?", "expect": "Portuguese"},
        {"input": "Привет, как дела?", "expect": "Russian"},
        {"input": "Hello, how are you today?", "expect": "English"},
    ],
}

_YESNO = {
    "id": "yesno",
    "name": "Yes/No facts",
    "level": 1,
    "task": {
        "system": "Answer the question with exactly one word: YES or NO.",
        "promptTemplate": "{input}",
        "check": "contains",
    },
    "cases": [
        {"input": "Is the Earth the third planet from the Sun?", "expect": "YES"},
        {"input": "Is water made of hydrogen and oxygen?", "expect": "YES"},
        {"input": "Is the Sun a planet?", "expect": "NO"},
        {"input": "Do humans have three lungs?", "expect": "NO"},
        {"input": "Is 17 a prime number?", "expect": "YES"},
        {"input": "Is the Great Wall of China located in Brazil?", "expect": "NO"},
        {"input": "Is ice the solid form of water?", "expect": "YES"},
        {"input": "Can penguins fly?", "expect": "NO"},
        {"input": "Is Mount Everest the tallest mountain on Earth?", "expect": "YES"},
        {"input": "Is a tomato a type of mineral?", "expect": "NO"},
    ],
}

_SPELLING = {
    "id": "spelling",
    "name": "Spelling correction",
    "level": 1,
    "task": {
        "system": "Correct the spelling of the word. Reply with ONLY the correctly spelled word.",
        "promptTemplate": "Word: {input}",
        "check": "contains",
    },
    "cases": [
        {"input": "recieve", "expect": "receive"},
        {"input": "definately", "expect": "definitely"},
        {"input": "seperate", "expect": "separate"},
        {"input": "occured", "expect": "occurred"},
        {"input": "tommorow", "expect": "tomorrow"},
        {"input": "untill", "expect": "until"},
        {"input": "begining", "expect": "beginning"},
        {"input": "necesary", "expect": "necessary"},
        {"input": "accomodate", "expect": "accommodate"},
        {"input": "embarass", "expect": "embarrass"},
    ],
}

_UNITS = {
    "id": "units",
    "name": "Unit conversion",
    "level": 1,
    "task": {
        "system": "Convert the units. Reply with ONLY the final number — digits only, no units or words.",
        "promptTemplate": "{input}",
        "check": "numeric",
    },
    "cases": [
        {"input": "How many centimeters are in 2 meters?", "expect": 200},
        {"input": "How many seconds are in 5 minutes?", "expect": 300},
        {"input": "How many grams are in 3 kilograms?", "expect": 3000},
        {"input": "How many millimeters are in 4 centimeters?", "expect": 40},
        {"input": "How many hours are in 2 days?", "expect": 48},
        {"input": "How many feet are in 2 yards?", "expect": 6},
        {"input": "How many ounces are in 2 pounds?", "expect": 32},
        {"input": "How many days are in 3 weeks?", "expect": 21},
        {"input": "How many milliliters are in 2 liters?", "expect": 2000},
        {"input": "How many minutes are in 4 hours?", "expect": 240},
    ],
}

_EXTRACT_AGE = {
    "id": "extract_age",
    "name": "Extract age (NER)",
    "level": 1,
    "task": {
        "system": "Read the sentence and reply with ONLY the person's age as a number.",
        "promptTemplate": "Sentence: {input}",
        "check": "numeric",
    },
    "cases": [
        {"input": "Maria is 34 years old and lives in Rome.", "expect": 34},
        {"input": "At 12, Tom already spoke three languages.", "expect": 12},
        {"input": "The retiree, aged 67, enjoys gardening.", "expect": 67},
        {"input": "Sara turned 29 last week.", "expect": 29},
        {"input": "He celebrated his 50th birthday yesterday.", "expect": 50},
        {"input": "The toddler is 3 years old.", "expect": 3},
        {"input": "Grandpa Joe is 81 and still hikes.", "expect": 81},
        {"input": "The intern, 22, just graduated.", "expect": 22},
        {"input": "At age 8, Lily won the contest.", "expect": 8},
        {"input": "Now 45, she changed careers.", "expect": 45},
    ],
}

# Level 2 tasks require several facts or rules to be combined before producing
# a short, deterministic answer. They are intentionally closer to production
# workflows than the Level 1 demonstrations.
_RETURNS_POLICY = {
    "id": "returns_policy",
    "name": "Returns policy adjudication",
    "level": 2,
    "task": {
        "system": (
            "You adjudicate ecommerce return requests using this policy, in priority order:\n"
            "1. ESCALATE if fraud is suspected, the item is hazardous, or the customer "
            "threatens legal action.\n"
            "2. DENY if the purchase is over 30 days old, unless it is defective and "
            "covered by the 90-day defect warranty.\n"
            "3. REPLACE if a covered item is defective or arrived damaged and replacement "
            "stock is available.\n"
            "4. REFUND if a covered item is defective/damaged with no replacement stock, "
            "or an unopened non-personalized item is returned within 30 days.\n"
            "5. Otherwise DENY. Personalized items cannot use the unopened-item rule.\n"
            "Reply with exactly one label: ESCALATE, DENY, REPLACE, or REFUND."
        ),
        "promptTemplate": "Return request:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Bought 8 days ago; unopened standard headphones; wants money back.", "expect": "REFUND"},
        {"input": "Bought 45 days ago; works correctly; customer changed their mind.", "expect": "DENY"},
        {"input": "Bought 62 days ago; defective blender; warranty applies; replacement is in stock.", "expect": "REPLACE"},
        {"input": "Bought 62 days ago; defective blender; warranty applies; replacement is out of stock.", "expect": "REFUND"},
        {"input": "Bought 4 days ago; damaged lamp; replacement is in stock.", "expect": "REPLACE"},
        {"input": "Bought 4 days ago; damaged lamp; replacement is out of stock.", "expect": "REFUND"},
        {"input": "Bought 3 days ago; unopened mug personalized with the customer's name.", "expect": "DENY"},
        {"input": "Bought 95 days ago; defective drill; customer asks for replacement.", "expect": "DENY"},
        {"input": "Bought 2 days ago; unopened battery pack is swollen and hot.", "expect": "ESCALATE"},
        {"input": "Bought 10 days ago; unopened shoes; customer threatens to sue unless refunded.", "expect": "ESCALATE"},
        {"input": "Bought 20 days ago; claims three high-value boxes arrived empty; account has repeated conflicting claims.", "expect": "ESCALATE"},
        {"input": "Bought 14 days ago; opened shirt fits but customer dislikes the color; no defect.", "expect": "DENY"},
    ],
}

_INCIDENT_SEVERITY = {
    "id": "incident_severity",
    "name": "Incident severity",
    "level": 2,
    "task": {
        "system": (
            "Assign incident severity using the highest applicable rule:\n"
            "SEV1: confirmed security breach/data exposure, or a total production outage "
            "affecting more than one region.\n"
            "SEV2: total outage in one region, payments/authentication unavailable for "
            "more than 10% of users, or irreversible customer data loss.\n"
            "SEV3: degraded service with a workaround, or a non-critical feature unavailable "
            "for more than 10% of users.\n"
            "SEV4: cosmetic, internal-only, or under 10% of users with no security/data-loss risk.\n"
            "Reply with exactly one label: SEV1, SEV2, SEV3, or SEV4."
        ),
        "promptTemplate": "Incident report:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Production is completely unavailable in US-East and EU-West; no workaround.", "expect": "SEV1"},
        {"input": "An access-control bug exposed customer invoices to other tenants for 18 minutes.", "expect": "SEV1"},
        {"input": "EU-West production is completely down; other regions are healthy.", "expect": "SEV2"},
        {"input": "Login fails for 18% of users; no workaround.", "expect": "SEV2"},
        {"input": "A storage bug permanently deleted uploaded files for 40 customers.", "expect": "SEV2"},
        {"input": "Search is slow for all users; direct URL navigation is a reliable workaround.", "expect": "SEV3"},
        {"input": "CSV export is unavailable for 35% of accounts; core workflows still work.", "expect": "SEV3"},
        {"input": "Checkout latency doubled for 6% of users; purchases still complete.", "expect": "SEV4"},
        {"input": "A dashboard icon is misaligned in Safari.", "expect": "SEV4"},
        {"input": "The internal staging deployment pipeline is unavailable; production is unaffected.", "expect": "SEV4"},
        {"input": "Payments fail for 8% of users, but logs confirm card details were exposed.", "expect": "SEV1"},
        {"input": "Authentication fails for 12% of users; resetting the session cookie restores access.", "expect": "SEV2"},
    ],
}

_BUSINESS_MATH = {
    "id": "business_math",
    "name": "Multi-step business math",
    "level": 2,
    "task": {
        "system": (
            "Solve the business calculation carefully. Apply discounts before tax, "
            "round money to the nearest cent only at the end, and reply with ONLY the "
            "final number. Do not include currency symbols, percent signs, units, or prose."
        ),
        "promptTemplate": "{input}",
        "check": {"type": "numeric", "tolerance": 0.01},
    },
    "cases": [
        {"input": "80 units cost 12.50 each. The supplier gives a 10% discount, then charges 8% tax. What is the final total?", "expect": 972.00},
        {"input": "Revenue is 18,000. Variable costs are 35% of revenue and fixed costs are 4,200. What is profit?", "expect": 7500},
        {"input": "A campaign costs 2,400 and generates 160 orders with an average gross profit of 22.50 each. What is net campaign profit?", "expect": 1200},
        {"input": "A subscription has 1,250 customers at 24 per month. Monthly churn is 4%. Assuming no new customers, what is next month's revenue?", "expect": 28800},
        {"input": "Inventory begins at 480 units. Sales are 35 units per day for 9 days and 60 units are returned to stock. How many units remain?", "expect": 225},
        {"input": "A product sells for 75. Its cost is 42 and payment fees are 3% of the sale price. What is contribution profit per sale?", "expect": 30.75},
        {"input": "Three agents handle 18 tickets per hour each for 6.5 hours. They spend 30 minutes each in meetings. How many tickets can they handle?", "expect": 324},
        {"input": "A 15,000 annual contract receives a 12% discount and then a one-time onboarding fee of 850 is added. What is the first-year total?", "expect": 14050},
        {"input": "A store buys 240 items at 8.40 each. It sells 75% at 14 each and the rest at 9 each. What is total profit?", "expect": 1044},
        {"input": "Monthly recurring revenue grows from 48,000 by 7%, then falls by 2% from that new amount. What is final MRR?", "expect": 50332.80},
        {"input": "A team budget is 90,000. Salaries use 62%, software uses 14,500, and travel uses 8,750. How much remains?", "expect": 10950},
        {"input": "A loan balance of 20,000 accrues simple interest at 6% annually for 9 months. What is the final balance?", "expect": 20900},
    ],
}

_CODE_DIAGNOSIS = {
    "id": "code_diagnosis",
    "name": "Code defect diagnosis",
    "level": 2,
    "task": {
        "system": (
            "Identify the PRIMARY defect in the code or behavior. Reply with exactly one "
            "label: SQL_INJECTION, RACE_CONDITION, NULL_DEREFERENCE, OFF_BY_ONE, "
            "RESOURCE_LEAK, PATH_TRAVERSAL, or NONE. Choose the most direct root cause, "
            "not a downstream symptom."
        ),
        "promptTemplate": "Review this report:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Python: cursor.execute(\"SELECT * FROM users WHERE name = '\" + request.args['name'] + \"'\")", "expect": "SQL_INJECTION"},
        {"input": "Two threads run `counter = counter + 1` on shared state without a lock; increments are occasionally lost.", "expect": "RACE_CONDITION"},
        {"input": "Java: `User u = repository.find(id); return u.getEmail();` The repository may return null.", "expect": "NULL_DEREFERENCE"},
        {"input": "JavaScript: `for (let i = 0; i <= items.length; i++) total += items[i].price;`", "expect": "OFF_BY_ONE"},
        {"input": "Python opens a file on every request with `f = open(path)` and returns early without closing it.", "expect": "RESOURCE_LEAK"},
        {"input": "A download endpoint joins `/srv/files` with an unvalidated query parameter such as `../../etc/passwd`.", "expect": "PATH_TRAVERSAL"},
        {"input": "Go: multiple goroutines append to the same map while requests are served; the process sometimes panics.", "expect": "RACE_CONDITION"},
        {"input": "C: a loop writes `buffer[i]` for i from 0 through size inclusive, but the allocation has exactly size elements.", "expect": "OFF_BY_ONE"},
        {"input": "A parameterized query uses `WHERE email = ?` and passes the email separately to the database driver.", "expect": "NONE"},
        {"input": "A file is opened with a context manager / try-with-resources and is closed on both success and error paths.", "expect": "NONE"},
        {"input": "Node: `const city = profile.address.city` but both profile and address are optional.", "expect": "NULL_DEREFERENCE"},
        {"input": "An export endpoint accepts `filename`, normalizes it, and rejects any resolved path outside the export directory.", "expect": "NONE"},
    ],
}

_DATA_HANDLING = {
    "id": "data_handling",
    "name": "Data-handling compliance",
    "level": 2,
    "task": {
        "system": (
            "Classify a proposed data action using the highest-priority rule:\n"
            "ESCALATE: legal hold, regulator/law-enforcement request, or uncertain breach.\n"
            "BLOCK: secrets/payment data sent externally, personal data used without a "
            "valid purpose/consent, or production customer data copied to a personal device.\n"
            "REDACT: the action is allowed after removing direct identifiers or credentials.\n"
            "ALLOW: public, synthetic, or properly authorized minimum-necessary data sent "
            "to an approved destination.\n"
            "Reply with exactly one label: ESCALATE, BLOCK, REDACT, or ALLOW."
        ),
        "promptTemplate": "Proposed action:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Post an already-public product price list on the company website.", "expect": "ALLOW"},
        {"input": "Send synthetic test customers to the approved staging environment.", "expect": "ALLOW"},
        {"input": "Email a customer-support transcript containing names and phone numbers to an approved analytics vendor; identifiers are not needed.", "expect": "REDACT"},
        {"input": "Share application logs with an approved vendor; logs contain an API token and user email addresses.", "expect": "REDACT"},
        {"input": "Copy the production customer database to an engineer's personal laptop for debugging.", "expect": "BLOCK"},
        {"input": "Paste live credit-card numbers into a public issue tracker.", "expect": "BLOCK"},
        {"input": "Use customer email addresses for a new advertising campaign without consent or another valid purpose.", "expect": "BLOCK"},
        {"input": "Delete records covered by an active legal hold because they exceed the normal retention period.", "expect": "ESCALATE"},
        {"input": "Send account records after receiving an informal law-enforcement email with no verified process.", "expect": "ESCALATE"},
        {"input": "Logs may show unauthorized access to personal records, but the evidence is incomplete.", "expect": "ESCALATE"},
        {"input": "Give an approved payroll processor the minimum employee bank details required under the signed processing agreement.", "expect": "ALLOW"},
        {"input": "Publish a research table after removing names, but each row still contains a unique customer email.", "expect": "REDACT"},
    ],
}

# Level 3 cases were authored with the real Anthropic API using
# `claude-opus-4-6`, then reviewed manually. These tasks intentionally contain
# noise, conflicts, vague referents, and misleading correlations. The rules are
# still explicit enough to preserve deterministic labels.
_AMBIGUITY_TRIAGE = {
    "id": "ambiguity_triage",
    "name": "Ambiguity & nonsense triage",
    "level": 3,
    "authoring": {
        "model": "anthropic/claude-opus-4-6",
        "promptTokens": 346,
        "outputTokens": 1084,
        "reviewed": True,
        "validation": {
            "date": "2026-06-06",
            "passes": 11,
            "cases": 12,
            "inputTokens": 2091,
            "outputTokens": 123,
        },
    },
    "task": {
        "system": (
            "Classify a request using the first matching definition. ANSWERABLE: "
            "coherent and contains enough information for the requested result. "
            "CLARIFY: coherent and potentially solvable, but a required parameter "
            "or referent is missing or materially ambiguous. CONTRADICTORY: two or "
            "more explicit requirements/facts cannot all be true. NONSENSE: no stable "
            "semantic interpretation exists, including category errors or word salad. "
            "Do not repair or creatively reinterpret the request. Reply with exactly "
            "one label: ANSWERABLE, CLARIFY, CONTRADICTORY, or NONSENSE."
        ),
        "promptTemplate": "Request:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "I manage 14 trucks. Fuel cost averaged $1.23 per mile. Each truck drove between 8,000 and 12,000 miles. The exact mileage logs are in the spreadsheet I mentioned earlier. Compute total Q3 fuel cost.", "expect": "CLARIFY"},
        {"input": "Our nonprofit raised $340,000. Allocate 40% to programs, 25% to admin, 20% to fundraising, and 30% to reserves, using every dollar exactly once. Confirm each amount.", "expect": "CONTRADICTORY"},
        {"input": "A rectangular garden is 12 meters long and 8 meters wide. Calculate its perimeter and the diagonal distance between opposite corners.", "expect": "ANSWERABLE"},
        {"input": "The quarterly revenue smells increasingly triangular, while perpendicular stakeholders ferment adjacency matrices into a broth of compliance. Evaluate the flavor of fiscal bandwidth and recommend a color for headcount.", "expect": "NONSENSE"},
        {"input": "Standard shipping takes 5-7 business days. Express takes 2-3. A package ordered Monday must arrive by Thursday that week. Which listed option can meet the deadline?", "expect": "ANSWERABLE"},
        {"input": "Translate into formal French: 'The meeting has been rescheduled to next Wednesday at 3 PM.'", "expect": "ANSWERABLE"},
        {"input": "Each of 5,000 customer records weighs 3.2 emotions. Calculate the server's total sadness capacity before migrating the happiness index to a colder partition.", "expect": "NONSENSE"},
        {"input": "Sort one list of distinct integers so the same final ordering is both strictly ascending and strictly descending, without changing or duplicating any values.", "expect": "CONTRADICTORY"},
        {"input": "Plant A makes 600 units/day at $2.10 each and Plant B makes 400 at $1.85. We have three product lines with different constraints, but I have not said which line or order quantity. Find the optimal production split.", "expect": "CLARIFY"},
        {"input": "Under this local rule, readings at or above 140 systolic OR 90 diastolic are Stage B. A patient's three readings are 150/95, 147/92, and 151/94. Return the stage.", "expect": "ANSWERABLE"},
        {"input": "Schedule the meeting on a weekday that is before Monday and after Friday of the same calendar week. All weekdays are available.", "expect": "CONTRADICTORY"},
        {"input": "Choose linear regression or gradient boosting for my house-price model. I have not provided the evaluation metric, accuracy target, interpretability requirement, or validation results.", "expect": "CLARIFY"},
    ],
}

_EVIDENCE_ADJUDICATION = {
    "id": "evidence_adjudication",
    "name": "Conflicting evidence",
    "level": 3,
    "authoring": {
        "model": "anthropic/claude-opus-4-6",
        "promptTokens": 365,
        "outputTokens": 1862,
        "reviewed": True,
        "validation": {
            "date": "2026-06-06",
            "passes": 12,
            "cases": 12,
            "inputTokens": 2860,
            "outputTokens": 69,
        },
    },
    "task": {
        "system": (
            "Classify whether the evidence establishes the stated claim. Direct "
            "instrument readings and signed system-of-record entries are authoritative; "
            "contemporaneous direct evidence outranks older direct evidence; summaries, "
            "rumors, and correlations are indirect. SUPPORTED: authoritative direct "
            "evidence supports the claim with no equal-or-newer authoritative conflict. "
            "CONTRADICTED: equal-or-newer authoritative direct evidence disproves it. "
            "INSUFFICIENT: evidence is only indirect, missing, or authoritative sources "
            "remain in unresolved conflict. IRRELEVANT: all supplied evidence concerns "
            "a different entity or metric and therefore does not bear on the claim. "
            "Use INSUFFICIENT, not IRRELEVANT, when evidence concerns the right entity "
            "but lacks a decisive fact. Reply with exactly one label: SUPPORTED, CONTRADICTED, "
            "INSUFFICIENT, or IRRELEVANT."
        ),
        "promptTemplate": "{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Claim: Tank 7 pressure was 42.1 psi at 14:00. Evidence: calibrated gauge P-7A logged 42.1 at 14:00; calibrated gauge P-7B logged 41.8 at the same time; both entries are signed. A supervisor summary says 'around 42.'", "expect": "INSUFFICIENT"},
        {"input": "Claim: Warehouse temperature was below 0°C at 08:00. Evidence: two calibrated thermocouples auto-recorded -1.3°C and -0.8°C at 08:00. A driver later said it felt cold; outdoor temperature was 22°C.", "expect": "SUPPORTED"},
        {"input": "Claim: Adams received 500mg amoxicillin at 09:00. Evidence: signed administration record says 250mg at 09:00; pharmacy dispensed one 250mg dose. The physician had ordered 500mg.", "expect": "CONTRADICTED"},
        {"input": "Claim: Coolant flow exceeded 200 L/min during the test. Evidence: calibrated flow meter system log records 203.4 L/min at 11:32. An engineer's later email only says flow was high.", "expect": "SUPPORTED"},
        {"input": "Claim: Bridge deflection exceeded its safety limit. Evidence: authoritative gauge recorded 12mm; signed design specification sets the limit at 15mm. A newspaper called the movement concerning.", "expect": "CONTRADICTED"},
        {"input": "Claim: Shipment #4412 contained Product X. Evidence: the signed bill of lading says Product Y, while the earlier purchase order requested X. The receiving tally has not identified the product.", "expect": "CONTRADICTED"},
        {"input": "Claim: Bus 14 dropped below 110V on October 8. Evidence: calibrated system-of-record min/max log shows a minimum of 112.3V. A rumor mentions a dip; Bus 12, not Bus 14, recorded 108V.", "expect": "CONTRADICTED"},
        {"input": "Claim: Garcia worked overtime Saturday. Evidence: badge logs show a 56-minute visit; the signed system-of-record timesheet records no Saturday work; a coworker says Garcia collected a personal item. Overtime requires actual work over 40 hours.", "expect": "CONTRADICTED"},
        {"input": "Claim: Q3 revenue exceeded $5 million. Evidence: a magazine says sources expect a strong quarter; the CEO says performance was pleasing; Q2 signed revenue was $4.8 million. No Q3 ledger or filing is provided.", "expect": "INSUFFICIENT"},
        {"input": "Claim: Valve V-22 was closed at 16:00. Evidence: the DCS system log reads CLOSED at 16:00 and a signed operator round confirms closed at 16:15. An older work order had requested it be opened.", "expect": "SUPPORTED"},
        {"input": "Claim: Room 204 exceeded 85 dB. Evidence: ocean salinity at Pier 6 was 34 PSU; Employee 204 submitted payroll on time; a meter in Room 108 recorded humidity of 44%.", "expect": "IRRELEVANT"},
        {"input": "Claim: Parcel 88 arrived before noon Tuesday. Evidence: Parcel 91 was signed for at 11:20; Truck 88 passed its emissions test; Tuesday's closing exchange rate was 1.08.", "expect": "IRRELEVANT"},
    ],
}

_RELEASE_GOVERNANCE = {
    "id": "release_governance",
    "name": "Release governance",
    "level": 3,
    "authoring": {
        "model": "anthropic/claude-opus-4-6",
        "promptTokens": 392,
        "outputTokens": 1271,
        "reviewed": True,
        "validation": {
            "date": "2026-06-06",
            "passes": 12,
            "cases": 12,
            "inputTokens": 2701,
            "outputTokens": 89,
        },
    },
    "task": {
        "system": (
            "Decide a software release using the highest-priority applicable rule. "
            "SECURITY_HOLD: a confirmed exploitable vulnerability, exposed secret, or "
            "unauthorized data access exists. ROLLBACK: the change is already deployed "
            "and causes an SLO breach or material data corruption with no proven immediate "
            "mitigation. HOLD: not fully deployed and a required test/approval is missing "
            "or failing, or an irreversible migration lacks a verified backup. "
            "SHIP_WITH_GUARDRAIL: all mandatory gates pass and a remaining operational "
            "risk is bounded by a tested flag, canary, rollback, or rate limit. SHIP: all "
            "gates pass and no material unresolved risk remains. Reply with exactly one "
            "label: SECURITY_HOLD, ROLLBACK, HOLD, SHIP_WITH_GUARDRAIL, or SHIP."
        ),
        "promptTemplate": "Release report:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "An irreversible database migration was tested in staging. The current production backup was restored successfully to a test cluster. Integration, review, and security gates pass; deployment has not started; no unresolved risk is recorded.", "expect": "SHIP"},
        {"input": "All gates pass. Load tests show a small latency increase still within SLO but near its threshold. A tested feature flag disables the new cache instantly. Deployment has not started.", "expect": "SHIP_WITH_GUARDRAIL"},
        {"input": "Deployed 45 minutes ago. Errors are 8.2% against a 1% SLO. A config mitigation was tried and errors remain 7.9%; no other proven immediate mitigation exists.", "expect": "ROLLBACK"},
        {"input": "A new image-proxy path sends user URLs to the metadata endpoint without validation. Security reproduced an exploitable SSRF in staging. All other tests pass; deployment has not started.", "expect": "SECURITY_HOLD"},
        {"input": "The candidate drops a legacy column irreversibly. A current backup exists but restoration has not been tested. An older backup restored successfully. Other gates pass; deployment has not begun.", "expect": "HOLD"},
        {"input": "A payment refactor passed all mandatory gates and PCI checks. It is bounded by a 2% canary with tested automatic rollback. The canary is healthy, but full deployment is pending.", "expect": "SHIP_WITH_GUARDRAIL"},
        {"input": "Already deployed. A race causes 0.3% checkout errors, still within the 1% SLO. A validated feature flag routes traffic to the old path immediately; an untested hotfix is also available.", "expect": "SHIP_WITH_GUARDRAIL"},
        {"input": "The candidate logs live Authorization bearer tokens into a broadly readable bucket. A current security engineer confirmed the exposure. Deployment has not started.", "expect": "SECURITY_HOLD"},
        {"input": "A TLS handling update passed every gate, was deployed blue-green, and has run for six hours with zero errors, all SLOs met, and no alerts.", "expect": "SHIP"},
        {"input": "Deployed 20 minutes ago. Write latency is 12 seconds against a 500ms SLO and 3% of new order indexes are corrupt. Rebuilding takes four hours; no immediate mitigation is proven.", "expect": "ROLLBACK"},
        {"input": "All technical tests pass, but the mandatory QA approval tool still says pending. An informal Slack approval came from a delegate not authorized by the checklist. Deployment has not started.", "expect": "HOLD"},
        {"input": "The artifact contains a revoked historical AWS key. The mandatory secret-scanning gate fails on any credential-shaped material, active or not. No exploitable active secret is present; deployment has not started.", "expect": "HOLD"},
    ],
}

_ROOT_CAUSE = {
    "id": "root_cause",
    "name": "Production root cause",
    "level": 3,
    "authoring": {
        "model": "anthropic/claude-opus-4-6",
        "promptTokens": 385,
        "outputTokens": 1990,
        "reviewed": True,
        "validation": {
            "date": "2026-06-06",
            "passes": 12,
            "cases": 12,
            "inputTokens": 2715,
            "outputTokens": 62,
        },
    },
    "task": {
        "system": (
            "Identify the best-supported primary cause from the timeline and telemetry. "
            "DEPLOYMENT: onset aligns with a code/config rollout and rollback reverses it. "
            "CAPACITY: saturation, queueing, or throttling rises with load and improves "
            "when capacity/load changes. DEPENDENCY: failures originate in a downstream "
            "service while the caller is otherwise healthy. DATA_QUALITY: malformed, "
            "stale, duplicated, or missing data explains the behavior. CLIENT: failures "
            "are isolated to a client version/network while server health is normal. "
            "INSUFFICIENT: observations conflict or no causal discriminator is present. "
            "Prefer causal interventions over temporal correlation. Reply with exactly "
            "one label: DEPLOYMENT, CAPACITY, DEPENDENCY, DATA_QUALITY, CLIENT, or "
            "INSUFFICIENT."
        ),
        "promptTemplate": "Timeline and telemetry:\n{input}",
        "check": "exact",
    },
    "cases": [
        {"input": "Deploy v2.87 completed at 14:02; checkout latency and errors rose at 14:08. Rollback at 14:31 restored both by 14:35. Payment, CPU, and memory stayed healthy. Redis had recovered before the deploy.", "expect": "DEPLOYMENT"},
        {"input": "Order-service is healthy but its recommendation dependency returns 503s and is in an OOM crash loop. Removing that dependency via feature flag drops order-service errors to zero. No recent caller deployment.", "expect": "DEPENDENCY"},
        {"input": "Only mobile v4.12 shows blank products. Servers return valid JSON; v4.11 and web succeed across the same networks. v4.12 introduced a JSON parser and reproduces on WiFi, LTE, and VPN.", "expect": "CLIENT"},
        {"input": "Dashboards show revenue 2.3x high. Source transactions are duplicated exactly twice after retries ran without idempotency. Deduplicating and rerunning the unchanged ETL restores correct values.", "expect": "DATA_QUALITY"},
        {"input": "A flash sale raises traffic 4x; all workers reach 98% CPU and queue depth hits 45,000. Adding eight workers drains the queue. Database latency stays flat and no deployment occurred.", "expect": "CAPACITY"},
        {"input": "A gateway TLS config deploy is followed by 500s across auth, billing, and notifications. Rolling back the gateway config resolves all errors. Backend services and network remain healthy.", "expect": "DEPLOYMENT"},
        {"input": "Search slows after a rebuilt index omits a boost field from 40% of documents, triggering fallback scoring. Rebuilding with complete data restores latency; cluster load and queries otherwise stay healthy.", "expect": "DATA_QUALITY"},
        {"input": "Partner traffic doubles connection demand; the pool reaches its 200 maximum while database CPU and query time stay low. Raising the pool to 400 immediately resolves timeouts.", "expect": "CAPACITY"},
        {"input": "Payment-service is healthy but times out on fraud-detection, whose batch job causes lock contention and eight-second responses. Bypassing fraud-detection restores payment success.", "expect": "DEPENDENCY"},
        {"input": "API errors consist equally of 502s beginning after a deploy and 422s beginning earlier from malformed partner dates. Rollback removes only 502s; fixing partner data removes only 422s. The request asks for one primary cause.", "expect": "INSUFFICIENT"},
        {"input": "Only desktop client 9.3 behind any network shows corrupt uploads. Server checksums and health are normal; 9.2 and web work. Disabling 9.3's new chunk combiner fixes uploads without server changes.", "expect": "CLIENT"},
        {"input": "Latency begins when traffic doubles and a config rollout completes in the same minute. CPU rises to 88%, but no capacity change is attempted; the config is not rolled back. Dependency metrics are normal.", "expect": "INSUFFICIENT"},
    ],
}


def presets() -> list[dict]:
    """All UI example tasks; the first is the default."""
    return [
        _triage_from_yaml(),
        _MATH,
        _CAPITALS,
        _SENTIMENT,
        _COUPLET,
        _LANGUAGE,
        _YESNO,
        _SPELLING,
        _UNITS,
        _EXTRACT_AGE,
        _RETURNS_POLICY,
        _INCIDENT_SEVERITY,
        _BUSINESS_MATH,
        _CODE_DIAGNOSIS,
        _DATA_HANDLING,
        _AMBIGUITY_TRIAGE,
        _EVIDENCE_ADJUDICATION,
        _RELEASE_GOVERNANCE,
        _ROOT_CAUSE,
    ]
