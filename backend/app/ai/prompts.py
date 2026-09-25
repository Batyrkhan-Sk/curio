"""Prompts and response schemas for the synthesis pipeline.

The house style below is the product. Everything else in this repository is
plumbing around it, so it is worth reading in full before changing a word.
"""

from __future__ import annotations

from typing import Any

HOUSE_STYLE = """\
You write for Curio, a platform that indexes human curiosity rather than web pages.

Your single hardest rule: NEVER assume the reader already knows a term.
The moment you need a word a curious 12-year-old would not know, introduce it
in plain language first, in the same breath, without breaking the sentence's
flow. Do not write "Bank transfers go through clearing houses." Write "Instead
of talking to each other thousands of times a second, banks usually send those
transactions through a special organisation called a clearing house — think of
it as a trusted middleman that keeps track of who owes what."

Style rules:
- Warm, calm, and precise. No hype, no exclamation marks, no "dive in", no
  "unlock", no rhetorical questions used as filler.
- Short sentences. Concrete nouns. Prefer a real number to a vague adjective.
- Analogies must be physical and everyday: kitchens, traffic, queues, water,
  paper, doors. Never explain one abstraction with another abstraction.
- Say plainly when something is uncertain, disputed, or a simplification. A
  reader who is told "this is the simplified picture; the full story is X" ends
  up trusting the platform more, not less.
- Never pad. If a section would only restate an earlier one, make it shorter.
- Write in the second person sparingly, and never flatter the reader.

Format rules:
- Plain prose. No markdown headings. Light use of **bold** for the one term a
  paragraph turns on is fine. No bullet lists unless the field asks for a list.
- Never mention that you are an AI, and never refer to "the sources" or "the
  provided text" — the reader cannot see them.
"""

LEVEL_BRIEFS = {
    1: (
        "Level 1 — Simple intuition. The honest one-paragraph reason, using only "
        "words an average 12-year-old knows. This is the paragraph most readers "
        "will remember, so it must be right, not just simple. 90-140 words."
    ),
    2: (
        "Level 2 — Visual analogy. One vivid, physical comparison the reader can "
        "picture, then one sentence on exactly where the analogy stops being true. "
        "That limit sentence is mandatory. 90-140 words."
    ),
    3: (
        "Level 3 — Real-world example. A specific, verifiable situation: a named "
        "device, event, company, year, or measurement. No invented specifics — if "
        "you are unsure of a number, describe it qualitatively instead. 110-170 words."
    ),
    4: (
        "Level 4 — Technical explanation. The mechanism as an engineer or scientist "
        "would state it. Introduce each technical term as you use it. Include the "
        "quantities that actually matter. 150-230 words."
    ),
    5: (
        "Level 5 — Expert details. The edge cases, trade-offs, and open questions a "
        "specialist would raise: what the simplified account leaves out, where the "
        "field disagrees, what changes at the limits. 150-230 words."
    ),
}


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": _string("The canonical question, ending in '?'. Max 90 characters."),
        "one_sentence_answer": _string(
            "One sentence, under 200 characters, that genuinely answers the question."
        ),
        "summary": _string("Two sentences of context for a preview card."),
        "category_slug": _string("One slug from the provided category list."),
        "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
        "reading_minutes": {"type": "integer"},
        "levels": {
            "type": "array",
            "description": "Exactly five entries, level 1 through 5, in order.",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer"},
                    "label": _string("Short name for this level."),
                    "body": _string("The explanation text for this level."),
                },
                "required": ["level", "label", "body"],
            },
        },
        "key_terms": {
            "type": "array",
            "description": "Every term the card introduces that a beginner would not know.",
            "items": {
                "type": "object",
                "properties": {
                    "term": _string("The term."),
                    "plain_definition": _string("One sentence, no jargon inside it."),
                },
                "required": ["term", "plain_definition"],
            },
        },
        "misconceptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "myth": _string("What many people believe."),
                    "reality": _string("Why it is wrong, and what is true instead."),
                },
                "required": ["myth", "reality"],
            },
        },
        "why_it_matters": _string(
            "Two or three sentences on the practical consequence of understanding this."
        ),
        "historical_background": {
            "type": "object",
            "properties": {
                "origin": _string("Who worked it out or built it, and roughly when."),
                "motivation": _string("What problem forced the discovery or invention."),
                "evolution": _string("How the understanding or technology changed since."),
            },
        },
        "diagrams": {
            "type": "array",
            "description": (
                "One or two diagrams. Use Mermaid syntax (flowchart LR / graph TD / "
                "sequenceDiagram). Keep to at most 8 nodes and label every edge."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "title": _string("What the diagram shows."),
                    "kind": {"type": "string", "enum": ["mermaid", "steps"]},
                    "content": _string("Mermaid source, or newline-separated steps."),
                    "caption": _string("One sentence explaining how to read it."),
                },
                "required": ["title", "kind", "content"],
            },
        },
        "image": {
            "type": "object",
            "description": (
                "Which of the offered pictures, if any, belongs on this card. "
                "Omit entirely, or set candidate to -1, when none of them earns "
                "its place — that is the usual answer."
            ),
            "properties": {
                "candidate": {
                    "type": "integer",
                    "description": (
                        "The index from the [image N] list, or -1 for no picture."
                    ),
                },
                "caption": _string(
                    "One sentence saying what the reader is looking at and how it "
                    "relates to the question. Not a description of the picture."
                ),
                "alt": _string("Plain alt text for a reader who cannot see it."),
            },
            "required": ["candidate"],
        },
        "related_questions": {
            "type": "array",
            "description": "4-6 questions a curious reader would ask immediately after.",
            "items": {"type": "string"},
        },
        "concepts": {
            "type": "array",
            "description": "3-6 underlying concepts, as short noun phrases.",
            "items": {
                "type": "object",
                "properties": {
                    "name": _string("Concept name, e.g. 'Stress concentration'."),
                    "plain_definition": _string("One beginner-safe sentence."),
                    "role": {"type": "string", "enum": ["covers", "requires", "mentions"]},
                },
                "required": ["name", "plain_definition", "role"],
            },
        },
        "next_steps": {
            "type": "array",
            "description": "2-4 concrete things to learn next, and why each follows.",
            "items": {
                "type": "object",
                "properties": {
                    "label": _string("What to learn next."),
                    "reason": _string("Why it follows from this card."),
                },
                "required": ["label", "reason"],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "one_sentence_answer",
        "summary",
        "category_slug",
        "levels",
        "key_terms",
        "misconceptions",
        "why_it_matters",
        "related_questions",
        "concepts",
    ],
}


def practical_tag_hints() -> str:
    """The practical vocabulary, grouped by the shelf each group feeds.

    Derived rather than listed. This was a hand-kept subset that had drifted
    away from what `is_practical` actually matches: it suggested "energy",
    which the shelf rule excludes on purpose, and never mentioned "phishing"
    or "poisoning", which it wants. A card tagged from the wrong list reads as
    practical to the model and to a human, and is then filed as neither.
    """
    from app.services.discovery import PRACTICAL_DOMAINS

    # The group names are prose, never tags. Naming them in the shelf's own
    # words ("money-sense") invited the model to use the heading as a tag,
    # which shelves nothing and pollutes the tag list.
    described = {
        "safety-first": "for danger, injury and emergencies",
        "not-getting-fooled": "for scams, accounts and privacy",
        "money-sense": "for cost, saving and household finance",
        "around-the-house": "for keeping possessions working",
        "out-in-the-world": "for getting places",
    }
    lines = [
        f"  {described.get(name, name)} — " + ", ".join(sorted(vocab))
        for name, vocab in PRACTICAL_DOMAINS.items()
    ]
    return "\n".join(lines)


def image_brief(candidates: str) -> str:
    """The picture-selection section, appended only when there are candidates.

    Written to make refusal comfortable. Offer a model a list and a slot to put
    an answer in and it will fill the slot, so the instruction has to say
    plainly that most cards get nothing and that saying so is the right answer
    rather than a failure to find one.
    """
    if not candidates:
        return ""
    return f"""

These pictures came with the sources. Decide whether one of them belongs on the
card, and set `image.candidate` to its number:

{candidates}

Include one only if seeing it teaches a reader something the prose cannot: the
object the question is about, the mechanism in action, the difference between
two things being compared. A photograph of a person who worked on the topic, a
building where it happened, or a thing merely adjacent to the subject teaches
nothing about how it works — those are decoration, and decoration on a
knowledge card is a small lie about what the picture is doing there.

`-1` is always a legitimate answer and costs the card nothing, so refuse a list
of near-misses rather than settling for the least bad one. But a diagram of the
mechanism, or a photograph of the actual subject, is not settling — when the
list genuinely contains one, take it."""


def synthesis_prompt(
    question: str,
    *,
    evidence: str,
    categories: list[str],
    also_asked_as: list[str],
    image_candidates: str = "",
) -> str:
    level_brief = "\n".join(LEVEL_BRIEFS[i] for i in range(1, 6))
    variants = (
        "\nThe same curiosity showed up phrased as:\n"
        + "\n".join(f"- {v}" for v in also_asked_as[:8])
        if also_asked_as
        else ""
    )
    return f"""\
Write a Curio knowledge card for this question:

  {question}
{variants}

Source material gathered from public references follows. Synthesise across it —
do not copy any passage, and do not trust any single source. Where sources
disagree, say so in the card rather than silently picking one.

<evidence>
{evidence}
</evidence>

Build the five explanation levels so they can each be read alone, but reward
reading in order. Each level goes deeper; none repeats an earlier one.

{level_brief}

Choose `category_slug` from exactly this list: {", ".join(categories)}

Tags are lowercase and hyphenated. When knowing this answer would actually
change what someone does — protecting their safety, health, money or time —
include the tag from this list that names the stake. Only the lowercase words
after each dash are tags; the words before it describe the group and must
never appear as a tag:

{practical_tag_hints()}

Use "practical" for a card that is useful without belonging to any of those.
Do not add one to earn the label; a card that is merely interesting should not
claim to be useful. "energy" and "physics" are subject tags, not stakes.

If the evidence is too thin to answer honestly, still produce the card but keep
every claim to what you are confident about, and leave `historical_background`
fields empty rather than guessing.{image_brief(image_candidates)}
"""


VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confidence": {
            "type": "number",
            "description": "0..1 — how well the evidence supports the card's claims.",
        },
        "confidence_reason": _string("One sentence justifying the score."),
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": _string("The claim in the card that is disputed."),
                    "conflict": _string("What the disagreeing source says."),
                    "resolution": _string("The most defensible reading, or 'unresolved'."),
                },
                "required": ["claim", "conflict"],
            },
        },
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "jargon_violations": {
            "type": "array",
            "description": "Terms used before being explained — a hard style failure.",
            "items": {"type": "string"},
        },
    },
    "required": ["confidence", "confidence_reason"],
}


def verification_prompt(card_json: str, evidence: str) -> str:
    return f"""\
You are fact-checking a draft knowledge card before publication. Be strict and
unsentimental; your job is to find what is wrong, not to praise what is right.

Check three things:
1. Is every factual claim supported by the evidence? List any that are not.
2. Do the sources contradict each other on anything the card asserts?
3. Does the card use any technical term before explaining it in plain words?
   List every such term — this is the platform's one unbreakable rule.

Score confidence honestly:
- 0.9-1.0  multiple independent, high-quality sources agree
- 0.7-0.89 well supported, minor gaps
- 0.5-0.69 broadly right, thin or single-sourced in places
- below 0.5 speculative, or the sources conflict on the core mechanism

<card>
{card_json}
</card>

<evidence>
{evidence}
</evidence>
"""


def reexplain_prompt(
    question: str,
    previous: str,
    mode: str,
    attempt: int,
) -> str:
    """The 'I still don't understand' path.

    The rule that matters: never restate. Each attempt must change the *shape*
    of the explanation, not just its wording.
    """
    modes = {
        "simpler": (
            "Explain it again for someone younger than last time. Cut every "
            "abstraction. Use only words from ordinary conversation. Shorter "
            "sentences than before. If you used a number, replace it with a "
            "comparison to something the reader can hold or see."
        ),
        "analogy": (
            "Give a completely different analogy from the one already used — a "
            "different domain of life entirely. Then say where it breaks down."
        ),
        "example": (
            "Give a different, very concrete worked example. Walk through one "
            "specific case start to finish with real particulars."
        ),
        "steps": (
            "Break the mechanism into numbered steps, cause to effect. Each step "
            "states what happens and why it must happen. 4-8 steps."
        ),
        "visual": (
            "Describe it as a picture, then give a Mermaid diagram. Start with two "
            "sentences on what the reader should imagine seeing, then the diagram "
            "in a ```mermaid fenced block, then one sentence on how to read it."
        ),
        "first_principles": (
            "Rebuild the answer from first principles. Start from something the "
            "reader certainly already believes, and take one small, undeniable step "
            "at a time until the conclusion is unavoidable."
        ),
    }
    instruction = modes.get(mode, modes["simpler"])

    return f"""\
A reader has said they still do not understand this question:

  {question}

They have already read this explanation, and it did not land:

<already_tried>
{previous}
</already_tried>

{instruction}

This is attempt number {attempt}. Do not reuse the framing, the analogy, or the
opening sentence of what they already read — repeating it in new words is the
one thing that is guaranteed not to help. Do not apologise or acknowledge the
confusion; just explain it differently. Under 220 words.
"""


QUESTION_TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "canonical_question": _string(
                        "The question rewritten cleanly, ending in '?'."
                    ),
                    "underlying_concept": _string("The one concept it really turns on."),
                    "curiosity_score": {
                        "type": "number",
                        "description": "0..1 — how widely and enduringly people wonder this.",
                    },
                    "reason": _string("Why kept or dropped."),
                },
                "required": ["index", "keep", "canonical_question", "curiosity_score"],
            },
        }
    },
    "required": ["results"],
}


def triage_prompt(questions: list[str]) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
    return f"""\
Below are raw questions scraped from public forums. Decide which deserve a
permanent knowledge card on a platform about durable, satisfying curiosity.

Keep a question when it:
- has a real, explainable mechanism behind it,
- will still be interesting in ten years,
- makes a reader think "I've always wondered that" or "I never questioned this".

Also keep a question when knowing the answer would genuinely help someone —
questions whose mechanism has consequences for safety, health, money, or time.
"Why does water make a pan fire worse?" and "Why does saving early beat saving
more later?" both qualify: each has one durable explanation, and knowing it
changes what a person would do. Judge these on the same standard as the rest —
there must be a mechanism to explain, not merely a recommendation to repeat.

Drop it when it is:
- personal help, debugging, or shopping advice ("why won't my laptop boot"),
- news-dependent or about a specific current event,
- opinion or politics,
- a request for individual medical or legal advice about someone's own case
  (a question about how a drug or a law works is fine; "should I take this"
  is not),
- so vague it has no single answer,
- trivially answerable by a definition.

Rewrite every kept question into a clean canonical form: plain English, no
platform-specific slang, no first person, starting with Why/How/What, ending
with a question mark.

<questions>
{numbered}
</questions>
"""


RESEARCH_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "description": (
                "2-3 encyclopaedia-style topic names to look up. Not questions "
                "— the names of the things involved."
            ),
            "items": {"type": "string"},
        },
        "stackexchange_sites": {
            "type": "array",
            "description": "1-2 Stack Exchange site slugs most likely to have answers.",
            "items": {"type": "string"},
        },
    },
    "required": ["topics", "stackexchange_sites"],
}


def research_plan_prompt(question: str, sites: list[str]) -> str:
    return f"""\
Before researching this question, decide what to actually look up.

  {question}

Give the encyclopaedia topic names a librarian would search for — the names of
the mechanisms, effects, and technologies involved, not the question reworded.
For "How can two computers agree on a secret key over an insecure connection?"
the topics are "Diffie-Hellman key exchange" and "public-key cryptography", not
"computers agreeing on secret keys".

Then pick the Stack Exchange sites most likely to hold good answers, from:
{", ".join(sites)}
"""
