#!/usr/bin/env python3
"""
End-to-End Voice Ordering Test with AI Customer
Integrates: launch_and_invoke_voice.py + manual_voice_test.py + verify_order.py

Physical audio setup:
- Computer speakers → Phone microphone (Ravi's TTS reaches phone)
- Phone speaker → Computer microphone (App's voice reaches Ravi's STT)
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml
import speech_recognition as sr
from src.ollama_client import OllamaClient
from src.voice_ai import speak_sync, speak_digits_sync


_APPIUM_URL = "http://localhost:4723/status"
_OLLAMA_URL = "http://localhost:11434/api/tags"


def _appium_ready() -> bool:
    try:
        import json
        with urllib.request.urlopen(_APPIUM_URL, timeout=3) as resp:
            return json.loads(resp.read()).get("value", {}).get("ready", False)
    except Exception:
        return False


def _ensure_appium_running(wait_secs: int = 20) -> None:
    if _appium_ready():
        print("✅ Appium already running")
        return
    print("⚡ Appium not running — starting in background...")
    log_path = Path("logs/appium.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log_f:
        subprocess.Popen(["appium"], stdout=log_f, stderr=log_f, start_new_session=True)
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        time.sleep(2)
        if _appium_ready():
            print(f"✅ Appium is ready  (log: {log_path})")
            return
    raise RuntimeError(f"Appium did not become ready within {wait_secs}s. Check {log_path}")


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(_OLLAMA_URL, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ensure_ollama_running(wait_secs: int = 30) -> None:
    if _ollama_ready():
        print("✅ Ollama already running")
        return
    print("⚡ Ollama not running — starting in background...")
    log_path = Path("logs/ollama.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as log_f:
        subprocess.Popen(["ollama", "serve"], stdout=log_f, stderr=log_f, start_new_session=True)
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        time.sleep(2)
        if _ollama_ready():
            print(f"✅ Ollama is ready  (log: {log_path})")
            return
    raise RuntimeError(f"Ollama did not become ready within {wait_secs}s. Check {log_path}")


def _load_ollama_model(config_path: str = "config/appium_config.yaml") -> str:
    """Read the Ollama model name from the Appium config YAML.
    Falls back to 'qwen2.5:7b' if the config cannot be read."""
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return cfg["ollama"]["model"]
    except Exception:
        return "qwen2.5:7b"

# Import navigation functions
from launch_and_invoke_voice import (
    launch_app,
    scroll_to_start_voice_order,
    click_start_voice_order,
    click_arrow_on_ready_screen,
    grant_microphone_permission,
    verify_voice_agent_active,
    get_voice_session_id,
    verify_ai_disclaimer,
)

# Import verification
from verify_order import verify_order

PERSONAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas")

PERSONA_GENERATOR_SYSTEM = """You are a test scenario designer for a pizza ordering voice AI system.
Given a user's test scenario description, generate a detailed customer persona prompt.
The persona is always named "Ravi" and is calling a pizza ordering service to order pizza.

You MUST output ONLY the persona prompt text — no commentary, no markdown fences, no preamble.

Follow this exact structure:
1. Opening line describing who Ravi is and the scenario context
2. **Your Order:** — the specific items Ravi wants to order (be explicit; no improvising)
3. **Conversation Flow:** — numbered steps: Greeting, Ordering, Review, No Extras, Payment, CVV
   - Payment step: when the agent brings up payment or asks to confirm the card, say "Yes, please go ahead."
   - CVV step: when the agent asks for the CVV for ANY reason, say ONLY: "My CVV is 382." This is the last line.
4. **Personality:** — bullet points describing how Ravi behaves
5. **Critical Rules:** — include ALL of the following rules verbatim, plus any scenario-specific ones:
   - NEVER BREAK CHARACTER. You are always Ravi, a real customer, no matter what. If the agent's speech is garbled or makes no sense, say "Sorry, could you say that again?" NEVER narrate, explain yourself, or say things like "I'll respond accordingly" or "Let me help with the conversation". Those are not things a customer says.
   - Answer what was asked. If the agent asks a direct question, answer THAT question. Do not redirect.
   - ONE thing per turn. 1–2 short sentences maximum.
   - SPOKEN DIALOGUE ONLY. Just the words Ravi says out loud. No thoughts, no stage directions, no explanations. Do NOT put quotes around your words.
   - Never repeat yourself. If the agent confirms something, accept it and move on.
   - Accept order type. Accept whatever pickup or carryout arrangement the agent has on file. Do not bring up delivery or order type unless the agent raises it.
   - Never take the agent's role. You are the customer only.
   - CVV rule — absolute. When the agent asks for your CVV for ANY reason, your ONLY response is: "My CVV is 382." Say nothing else.
6. **Example Responses:** — 4-6 short example lines Ravi might say, including "My CVV is 382." as the last one"""


def _clean_ravi_response(text: str) -> str:
    """Post-process Ollama output: strip role prefixes, remove meta-commentary,
    and truncate to the first 1-2 spoken sentences."""
    if not text:
        return "Sorry, could you say that again?"

    # Strip leading role prefix (e.g. "Ravi:", "Agent:", "You:")
    text = re.sub(
        r'^(?:Ravi|Agent|Customer|You|User|Caller)\s*:\s*',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Drop any line that contains LLM meta-commentary
    META_PATTERNS = [
        "my response is", "as per instruction", "as per guideline",
        "i'll respond", "let me help with the conversation",
        "based on the", "following the rules", "adhering to",
        "note that", "would not be a direct", "however, considering",
        "ravi would say", "ravi's response", "per the instruction",
        "i should not", "i cannot", "i am not able",
    ]
    clean_lines = []
    for line in text.splitlines():
        if any(p in line.lower() for p in META_PATTERNS):
            continue
        clean_lines.append(line)
    text = " ".join(clean_lines).strip()

    if not text:
        return "Sorry, could you say that again?"

    # Truncate to first 2 sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    text = " ".join(sentences[:2]).strip()

    # If still too long (>200 chars) fall back to first sentence only
    if len(text) > 200:
        text = re.split(r'(?<=[.!?])\s+', text)[0].strip()

    return text or "Sorry, could you say that again?"


def _parse_items_from_persona(persona_text: str) -> list:
    """Extract the ordered list of items from the persona's 'Your Order:' section.

    Looks for a line matching '**Your Order' then collects every numbered line
    (e.g. '1. One large pepperoni pizza') until the next bold section header.
    Returns an empty list if the section cannot be found.
    """
    items = []
    in_order_section = False
    for line in persona_text.splitlines():
        if re.search(r'\*\*your order', line, re.IGNORECASE):
            in_order_section = True
            continue
        if in_order_section:
            if line.startswith("**"):          # next bold section — stop
                break
            m = re.match(r'^\d+\.\s+(.+)', line.strip())
            if m:
                items.append(m.group(1).strip())
    return items


def _format_order_item(item_text: str, is_first: bool) -> str:
    """Wrap a persona item in natural spoken dialogue.
    Lowercases the first character so 'One large pizza' → 'I'd like one large pizza.'
    """
    item = item_text.strip()
    if item:
        item = item[0].lower() + item[1:]
    if is_first:
        return f"I'd like {item}."
    return f"And {item} please."


_ONES = [
    "zero", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty",
         "sixty", "seventy", "eighty", "ninety"]


def _cvv_to_spoken_words(cvv: str) -> str:
    """Convert a CVV string to natural speech matching how humans say a CVV aloud.

    For a 3-digit CVV, say the first digit then the last two as a single number —
    exactly how a real customer says it: '382' → 'three eighty two'.
    This matches TTS prosody to human prosody, which the physical audio loop
    delivers to the voice agent's STT more reliably than individual digit words.

    For non-3-digit CVVs falls back to individual digit words.
    """
    digits = [d for d in cvv if d.isdigit()]
    if len(digits) == 3:
        first = _ONES[int(digits[0])]
        last_two = int(digits[1] + digits[2])
        if last_two < 20:
            rest = _ONES[last_two]
        else:
            tens, ones = divmod(last_two, 10)
            rest = _TENS[tens] + (" " + _ONES[ones] if ones else "")
        return f"{first} {rest}"
    return " ".join(_ONES[int(d)] for d in digits)


_QUESTION_STARTERS = re.compile(
    r'^\s*(how|do|does|did|are|is|isn\'t|aren\'t|can|can\'t|could|would|will|what|when|where|why|which|have|has|may|might)\b'
)
_QUESTION_PHRASES = [
    "do you", "would you", "can you", "are you", "have you",
    "how much", "how many", "how would", "how do",
    "does that", "is that correct", "is that right",
]

# Phrases the agent uses when prompting Ravi to place/continue an order.
# Also used by _get_pre_order_query() to detect when to inject a pre-order question.
ORDER_PROMPTS = [
    "what can i get you", "what can i get for you",
    "what can i get started", "what can i start you",
    "what would you like", "what would you like to order",
    "how can i help", "what can i do for you",
    "can i take your order", "ready to take your order",
    "what are you ordering", "what can i start with",
    "go ahead", "tell me your order", "start with your order",
    "place your order", "what are you having",
    # Whisper-truncated tails — Ava's full question arrives split across SR chunks;
    # these are the recognisable endings that uniquely identify an order prompt.
    "started for you", "get you started", "for you today",
    "help you today", "get you today",
]


def _is_question(agent_speech: str, agent_lower: str) -> bool:
    """True if the agent utterance is a question — by punctuation or vocabulary."""
    return (
        "?" in agent_speech
        or bool(_QUESTION_STARTERS.match(agent_lower))
        or any(p in agent_lower for p in _QUESTION_PHRASES)
    )


def _get_pre_order_query(
    agent_lower: str,
    pre_order_queries: list,
    queries_asked_idx: int,
) -> tuple | None:
    """Return (query_text, new_idx) when an un-asked pre-order query should be
    injected instead of ordering item[0].  Returns None when all queries have
    been asked or the agent speech is not an order prompt."""
    if not pre_order_queries or queries_asked_idx >= len(pre_order_queries):
        return None
    if any(p in agent_lower for p in ORDER_PROMPTS):
        return (pre_order_queries[queries_asked_idx], queries_asked_idx + 1)
    return None


def _get_deterministic_response(
    agent_speech: str,
    agent_lower: str,
    turn: int,
    items_to_order: list,
    items_ordered_idx: int,
    rejected_items: list,
    items_to_remove: list = None,
    items_removed_idx: int = 0,
    post_order_requests: list = None,
    requests_idx: int = 0,
    mind_change_item: str = None,
    pipa_dough_action: str = "apply",
):
    """Return (response_text, new_items_ordered_idx, new_items_removed_idx, new_requests_idx)
    for predictable patterns, or None to fall through to Ollama.

    Checked in priority order:
      1. Turn 1  — always greet
      2. Pending rejection  — defer to Ollama (it has the rejection constraint)
      3. "Anything else?"  — order next item, or wrap up if all ordered
      4. Open-ended order prompts  — order next item
      5. Full-order review/confirmation  — "Yes, that's right."
    """
    # 1. Turn 1: always open with a greeting regardless of what the agent said
    if turn == 1:
        return ("Hi, I'd like to place an order please.", items_ordered_idx, items_removed_idx, requests_idx)

    # 2. Pending rejection: the Ollama constraint block handles this correctly
    if rejected_items:
        return None

    # 2b. Tip / gratuity question — checked BEFORE loyalty so that a combined
    # "Pipa Doe applied. What amount would you like to tip?" turn is handled
    # here and doesn't accidentally trigger the loyalty bypass.
    # Guard: skip when mind_change_item is pending — agent may ask about tip
    # before the order review; let Ollama handle it so Ravi stays on-track.
    TIP_PHRASES = [
        "add a tip", "leave a tip", "tip for the driver",
        "tip for your driver", "add tip", "driver tip",
        "would you like to tip", "gratuity",
        "what amount", "how much would you like to tip",
    ]
    if (not mind_change_item
            and _is_question(agent_speech, agent_lower)
            and any(p in agent_lower for p in TIP_PHRASES)):
        return ("I'd like to add a five dollar tip please.", items_ordered_idx, items_removed_idx, requests_idx)

    # 2c. Loyalty / rewards questions — agent asks about pipa dough.
    # Two sub-cases:
    #   "How much would you like to apply?" → apply $1
    #   "Do you have an account / balance?" → decline politely
    #
    # Guard: if tip phrases are present the tip handler above already answered;
    # this block only fires for genuine loyalty-only turns.
    #
    # Use a regex for "pipa <anything starting with d>" to survive all Whisper
    # mis-transcriptions (pipa dough, pipa doe, pipa delo, pipa doo, pipa dou…).
    # Also match fixed phrases for rewards/loyalty account questions.
    _PIPA_D_RE = re.compile(
        r'\bp\w{0,3}[pf]a\s+d\w*\b'         # pipa/popa/pompa/puffa + d-word (space-separated)
        r'|\bpop[-\s](?:a|an?d?)[-\s]d\w*\b' # pop-a-/pop-and-/pop-an- + d-word
        r'|\bpipadot\b',                      # pipadot (fully merged single word)
        re.IGNORECASE,
    )
    LOYALTY_FIXED = [
        "rewards account", "reward account", "rewards balance",
        "loyalty account", "loyalty points", "reward points",
    ]
    _is_loyalty = bool(_PIPA_D_RE.search(agent_speech)) or any(
        p in agent_lower for p in LOYALTY_FIXED
    )
    # Guard: skip loyalty handler when mind_change_item is pending (same reason as tip).
    if (not mind_change_item
            and _is_loyalty
            and not any(p in agent_lower for p in TIP_PHRASES)):
        # Only ask to apply when the agent is actually asking a question.
        # "I'll apply $1 to your order." is a confirmation statement — not a question.
        _apply_words = ["would you like to use", "would you like to apply",
                        "like to apply", "like to use", "apply", "use towards"]
        if _is_question(agent_speech, agent_lower) and any(w in agent_lower for w in _apply_words):
            if pipa_dough_action == "decline":
                return ("No thank you, I'll skip the Pipa Dough.", items_ordered_idx, items_removed_idx, requests_idx)
            return ("I'd like to apply one dollar please.", items_ordered_idx, items_removed_idx, requests_idx)
        # Confirmation statement ("I've applied $1…", "I'll apply…") — just ack
        _confirmation_words = ["i've applied", "i'll apply", "applied", "will be applied",
                               "has been applied", "i have applied"]
        if any(w in agent_lower for w in _confirmation_words):
            return ("Okay, thanks.", items_ordered_idx, items_removed_idx, requests_idx)
        # Account-existence question ("Do you have a rewards account?", "Are you a member?")
        # Guard: only fire when the agent is asking whether Ravi has an account,
        # NOT when announcing a balance ("You have $4,813 in Pipa Dough available.").
        _account_question_phrases = [
            "do you have", "have an account", "have a rewards",
            "are you a", "are you a member",
        ]
        if (_is_question(agent_speech, agent_lower)
                and any(p in agent_lower for p in _account_question_phrases)):
            return ("No, I don't have a rewards account, thanks.", items_ordered_idx, items_removed_idx, requests_idx)
        # Balance announcement or other loyalty context without a clear action prompt —
        # fall through so Ollama or the next SR chunk's question handles it.

    # 2c. Agent asks Ravi to repeat — re-state the most recently requested item.
    # Happens when TTS audio is unclear over the phone line or there is background
    # noise.  Deterministic re-statement prevents Ollama from hallucinating a
    # different order.
    REPEAT_REQUEST_PHRASES = [
        "could you repeat", "can you repeat",
        "didn't catch", "didn't quite catch", "didn't get that",
        "didn't understand", "couldn't understand",
        "could you say that again", "say that again",
        "come again", "pardon",
        "couldn't hear", "having trouble hearing",
        "what did you say", "what was that",
        "i'm sorry?", "i beg your pardon",
    ]
    if any(p in agent_lower for p in REPEAT_REQUEST_PHRASES):
        if items_to_order and items_ordered_idx > 0:
            last_item = items_to_order[items_ordered_idx - 1]
            return (f"I said I'd like {last_item}.", items_ordered_idx, items_removed_idx, requests_idx)
        return ("I said I'd like to place an order please.", items_ordered_idx, items_removed_idx, requests_idx)

    # 3. "Anything else?" — order the next queued item, or say we're done
    ANYTHING_ELSE = [
        "anything else", "what else", "is there anything else",
        "can i get you anything else", "would you like anything else",
        "anything more", "anything additional",
        "will that be all", "is that all", "is that everything",
        "will that do it", "is that it for you",
    ]
    if any(p in agent_lower for p in ANYTHING_ELSE):
        if items_to_order and items_ordered_idx < len(items_to_order):
            response = _format_order_item(
                items_to_order[items_ordered_idx], is_first=False
            )
            return (response, items_ordered_idx + 1, items_removed_idx, requests_idx)
        if items_to_remove and items_removed_idx < len(items_to_remove):
            item = _yaml_item_to_speech(items_to_remove[items_removed_idx])
            return (f"Actually, could you remove {item} please?", items_ordered_idx, items_removed_idx + 1, requests_idx)
        if post_order_requests and requests_idx < len(post_order_requests):
            return (post_order_requests[requests_idx], items_ordered_idx, items_removed_idx, requests_idx + 1)
        return ("No, that's all, thank you.", items_ordered_idx, items_removed_idx, requests_idx)

    # 4. Open-ended order prompt (agent asking what Ravi wants)
    if (items_to_order
            and items_ordered_idx < len(items_to_order)
            and any(p in agent_lower for p in ORDER_PROMPTS)):
        response = _format_order_item(
            items_to_order[items_ordered_idx],
            is_first=(items_ordered_idx == 0),
        )
        return (response, items_ordered_idx + 1, items_removed_idx, requests_idx)

    # 5a. Scheduled-time confirmation — agent asks "Does that work for you?"
    # Also handles Whisper-truncated variants like "does that work" without trailing "for you".
    SCHEDULE_CONFIRM_PHRASES = [
        "does that work for you", "does that work",
        "does the time work",
    ]
    if any(p in agent_lower for p in SCHEDULE_CONFIRM_PHRASES) and _is_question(agent_speech, agent_lower):
        return ("Yes, that works.", items_ordered_idx, items_removed_idx, requests_idx)

    # 5. Agent reading back / asking Ravi to confirm the full order.
    REVIEW_PHRASES = [
        "your order is", "you have ordered", "let me confirm",
        "to confirm your order", "does that sound right", "is that correct",
        "is that right", "does that look right", "let me repeat that back",
        "so just to confirm", "is that everything", "does that look good",
    ]
    _review_match = any(p in agent_lower for p in REVIEW_PHRASES)
    if _review_match:
        if mind_change_item:
            # Fire change-of-mind on any review phrase (statement OR question).
            # The agent may review without a trailing "?" e.g. "Your order is one
            # large pepperoni pizza." — waiting for a question would lose the window.
            return (mind_change_item, items_ordered_idx, items_removed_idx, requests_idx)
        if _is_question(agent_speech, agent_lower):
            return ("Yes, that's right.", items_ordered_idx, items_removed_idx, requests_idx)

    # 6. Short agent acknowledgment with no question (e.g. "Got it!", "Perfect.", "Alright.")
    # These require no substantive reply — "Okay, thanks." keeps the flow moving.
    ACK_ONLY_PHRASES = [
        "got it", "perfect", "alright", "great", "sounds good",
        "sure thing", "absolutely", "of course", "no problem",
        "okay", "ok,", "thank you", "thanks",
    ]
    # Guard: tip-confirmation statements (e.g. "Okay, I've added a $5 tip.") start with
    # an ack word but are actually the first clause of a longer agent utterance ending in
    # a payment question.  SR splits at the comma pause — don't fire here.
    _tip_confirmation = re.search(r'\btip\b', agent_lower)
    if (
        "?" not in agent_speech
        and len(agent_speech.split()) <= 10
        and any(p in agent_lower for p in ACK_ONLY_PHRASES)
        and not _tip_confirmation
    ):
        return ("Okay, thanks.", items_ordered_idx, items_removed_idx, requests_idx)

    # 7. Item-added confirmation: agent says "[Item] added." (or similar short statement).
    # CRITICAL: do NOT let Ollama respond here — it tends to say "Yes, that's right."
    # which the voice agent interprets as full order-review confirmation, causing it to
    # finalise the cart early (before all items are queued).  "Okay, thanks." is the
    # natural customer reply and keeps the ordering flow moving forward.
    #
    # Guard: "I've added a $5 tip" is always the first clause of a two-part agent
    # utterance: "...your credit card ending in XXXX will be charged, is that correct?"
    # SR splits at the comma pause and delivers the tip-confirmation clause alone.
    # Rule 7 must NOT fire here — let the payment bypass handle the full sentence on
    # the next listen cycle when the "?" arrives.
    if (
        "?" not in agent_speech
        and re.search(r'\badded\b', agent_lower)
        and len(agent_speech.split()) <= 12
        and not re.search(r'\btip\b', agent_lower)
    ):
        return ("Okay, thanks.", items_ordered_idx, items_removed_idx, requests_idx)

    # 8. All items ordered — agent makes a non-question statement.
    # Once every item has been queued, agent statements that aren't questions
    # need no substantive reply.  Calling Ollama risks hallucinating wrong
    # items (e.g. re-ordering breadsticks when agent mentions Pepsi pricing).
    # "Okay, thanks." is the safest universal acknowledgment at this stage.
    # Questions (finalize?, payment?) still fall through to Ollama / bypasses.
    #
    # Guard: payment/charge statements are often truncated mid-sentence by SR
    # (e.g. "A total of $25 would be charged to your card ending in 1234" —
    # the agent hasn't finished saying "...and if that's correct?" yet).
    # Let these fall through so the payment bypass can handle the full phrase
    # on the next listen cycle, or Ollama gives a safe reply.
    _PAYMENT_CONTEXT_RE = re.compile(
        r'\b(charged|charge to|card ending|credit card ending|'
        r'finalize|finalise|confirm your order|place your order|tip)\b'
    )
    if (
        items_to_order
        and items_ordered_idx >= len(items_to_order)
        and not mind_change_item       # don't swallow review statements while awaiting change-of-mind
        and not _is_question(agent_speech, agent_lower)
        and not _PAYMENT_CONTEXT_RE.search(agent_lower)
        and not _review_match          # SR may truncate "Your order is X, does that sound right?" at the comma
        and not _PIPA_D_RE.search(agent_lower)  # SR may truncate "You have $X in Pipa Dough. How much...?"
    ):
        return ("Okay, thanks.", items_ordered_idx, items_removed_idx, requests_idx)

    # No deterministic match — call Ollama
    return None


def load_persona(name):
    """Load persona text from personas/ directory."""
    filepath = os.path.join(PERSONAS_DIR, f"{name}.txt")
    if not os.path.isfile(filepath):
        filepath = os.path.join(PERSONAS_DIR, "default.txt")
    with open(filepath, "r") as f:
        return f.read()


def prepare_persona(persona_name=None, scenario=None):
    """
    Load or generate the Ravi persona text before app navigation starts.

    Priority order:
      1. Named persona file (persona_name) — load directly, no Ollama needed.
      2. Free-text scenario description only — generate via Ollama.
      3. Neither provided — fall back to default.txt.

    Call this BEFORE launching the app so that any Ollama generation time
    does not delay the conversation after the voice agent is already live.

    Returns the persona as a plain string ready to pass to
    run_ai_customer_conversation(persona_text=...).
    """
    if persona_name:
        # Explicit persona file wins — never call Ollama in this path.
        persona = load_persona(persona_name)
        print(f"📋 Loaded persona: {persona_name}")
        return persona
    if scenario:
        # Free-text CLI scenario with no named persona file — generate via Ollama.
        ollama = OllamaClient(model=_load_ollama_model())
        persona = generate_persona_from_scenario(scenario, ollama)
        print(f'📋 Generated persona from scenario: "{scenario}"')
        print("-" * 60)
        print(persona)
        print("-" * 60)
        return persona
    persona = load_persona("default")
    print("📋 Loaded persona: default")
    return persona


def generate_persona_from_scenario(scenario, ollama):
    """Use Ollama to generate a persona prompt from a free-text scenario description."""
    example_persona = load_persona("default")
    prompt = f"""Here is an example persona for reference:

---
{example_persona}
---

Now generate a NEW persona for this test scenario:
"{scenario}"

Output only the persona text, matching the structure of the example above."""

    print("🧠 Generating persona from scenario description...")
    try:
        persona = ollama.generate(prompt, system=PERSONA_GENERATOR_SYSTEM, num_predict=800)
        if not persona:
            print("❌ Failed to generate persona (Ollama returned empty). Falling back to default.")
            return load_persona("default")
        return persona
    except Exception as e:
        print(f"❌ An error occurred during persona generation: {e}")
        print("   Falling back to default persona.")
        return load_persona("default")


def _yaml_item_to_speech(item: str) -> str:
    """Convert a YAML expected_item string to a natural spoken form.

    '1 Large Pepperoni Pizza'  → 'a large pepperoni pizza'
    '1 Order of Garlic Knots' → 'an order of garlic knots'
    '2-Liter Pepsi'           → 'a 2-liter pepsi'
    """
    cleaned = re.sub(r'^\d+\s+', '', item.strip()).lower()
    if cleaned and cleaned[0] in 'aeiou':
        return 'an ' + cleaned
    return 'a ' + cleaned


_ORDER_COMPLETE_PHRASES = [
    "thank you for your order",
    "order has been placed", "has been placed",
    "order is placed",
    "placed successfully", "successfully placed",
    "order is confirmed", "order confirmed",
    "your order is complete", "order complete",
    "order was placed", "order was confirmed",
    "payment was successful", "successfully processed",
    # Whisper sometimes returns only a fragment of the confirmation
    # (e.g. " successfully.") — safe to match in the post-CVV context.
    "successfully",
]

_PAYMENT_FAILURE_PHRASES = [
    "card was declined", "card declined", "payment declined",
    "unable to process", "could not process", "failed to process",
    "payment failed", "payment unsuccessful", "transaction failed",
    "transaction declined", "problem with your payment",
    "issue with your payment", "issue processing your payment",
    "issue processing", "there was an issue processing",
    "payment could not be", "sorry, we couldn't process",
    "payment error", "not able to process your payment",
    "try another payment method", "check your card details",
    # Agent-side payment failure phrases observed in live runs
    "update your payment method", "check the app to update",
    "please check the app",
    # Observed: "I'm sorry, Ravi, but there is an error processing your request"
    "error processing", "an error processing",
]


def _classify_confirmation_speech(speech: str) -> str:
    """
    Classify one STT chunk from the post-CVV confirmation wait loop.

    Returns:
        "confirmed"      — order placed successfully
        "payment_failed" — agent reported a payment error
        "unknown"        — no conclusive phrase
    """
    clean = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', speech.lower()))
    if any(p in clean for p in _PAYMENT_FAILURE_PHRASES):
        return "payment_failed"
    if any(p in clean for p in _ORDER_COMPLETE_PHRASES):
        return "confirmed"
    return "unknown"


def _wait_for_order_confirmation(recognizer, mic_index, log_f, timeout=90):
    """
    After Ravi speaks the CVV, keep listening until the agent confirms the order
    has been placed (or reports a payment failure) before returning control to
    the caller (which then starts order verification).

    Returns:
        "confirmed"      — agent said order was placed successfully
        "payment_failed" — agent reported a payment error/decline
        "timeout"        — no conclusive phrase heard within timeout
    """
    print(f"\n⏳ Waiting for agent order confirmation (up to {timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            with sr.Microphone(device_index=mic_index) as source:
                recognizer.dynamic_energy_threshold = True
                recognizer.pause_threshold = 1.8
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                print("   🔴 Listening for order confirmation...")
                audio = recognizer.listen(source, timeout=15, phrase_time_limit=30)

            speech = recognizer.recognize_whisper(audio, model="base.en")
            print(f'   👨‍💼 Agent: "{speech}"')
            log_f.write(f"Agent: {speech}\n")

            result = _classify_confirmation_speech(speech)

            if result == "payment_failed":
                print("❌ Payment failure detected from agent.")
                log_f.write("[PAYMENT FAILED — agent reported payment could not be processed]\n")
                return "payment_failed"

            if result == "confirmed":
                print("✅ Order placed confirmation received.")
                log_f.write("[Order placed confirmed — proceeding to verification]\n")
                return "confirmed"

        except sr.WaitTimeoutError:
            elapsed = int(time.time() - start)
            print(f"   ... still waiting ({elapsed}s elapsed)")
        except sr.UnknownValueError:
            pass  # noise or silence — keep listening
        except Exception as e:
            print(f"   ⚠️  STT error during confirmation wait: {e}")

    print(f"⚠️  Order confirmation not heard within {timeout}s — proceeding to verification anyway.")
    log_f.write("[Order confirmation timeout — proceeding to verification]\n")
    return "timeout"


def _is_room_echo(agent_speech: str, last_ravi_response: str) -> bool:
    """Return True if agent_speech looks like a room echo of last_ravi_response.

    Uses Jaccard similarity on word sets (punctuation stripped, lowercased).
    Threshold 0.7 catches near-exact echoes while keeping genuine short replies
    from Ava that happen to share common words.
    """
    if not last_ravi_response:
        return False
    a = set(re.sub(r'[^\w\s]', '', agent_speech.lower()).split())
    b = set(re.sub(r'[^\w\s]', '', last_ravi_response.lower()).split())
    if not a or not b:
        return False
    return len(a & b) / max(len(a), len(b)) >= 0.7


def run_ai_customer_conversation(
    persona_name=None, scenario=None, mic_name="MacBook Pro Microphone",
    termination_trigger="cvv", persona_text=None, cvv="382",
    expected_items=None, expected_schedule=None, driver=None,
    phase_statuses=None, pre_order_queries=None,
    voice_items=None, items_to_remove=None, post_order_requests=None,
    mind_change_item=None, pipa_dough_action="apply",
):
    """
    Run AI customer conversation loop.
    Replicates manual_voice_test.py conversation logic exactly.

    Args:
        persona_text: pre-built persona string returned by prepare_persona().
            When supplied, persona_name and scenario are ignored for persona
            loading — pass them only so the log label is correct.
        termination_trigger: controls when the conversation exits.
            "cvv"            — exit when the agent asks for CVV; Ravi's response is
                               bypassed (Ollama not called) and the stored cvv value
                               is spoken directly.
            "order_confirmed" — exit only when agent says an order-confirmation phrase;
                               use when payment is saved card, Apple Pay, PayPal, etc.
        cvv: the CVV string Ravi speaks when the agent requests it (default "382").

    Returns: path to conversation log file
    """
    # Kill any afplay orphan left by a previous interrupted run so we don't
    # start the conversation with stale audio still playing in the background.
    import subprocess as _sp, sys as _sys
    if _sys.platform == "darwin":
        _sp.run(["pkill", "-x", "afplay"], capture_output=True)

    # Flush the OS microphone buffer before entering the conversation loop.
    # Ava starts speaking the moment the voice session opens (Phase 1 end).
    # Keep the flush fast (0.2 s drain max) to minimise the gap between the
    # session going live and us actually listening — a long flush causes us to
    # miss more of Ava's greeting, which then arrives truncated on Turn 1.
    try:
        with sr.Microphone() as _flush_src:
            _flush_rec = sr.Recognizer()
            try:
                _flush_rec.listen(_flush_src, timeout=0.2, phrase_time_limit=0.5)
                print("   🎙️ Mic buffer flushed (stale audio discarded)")
            except sr.WaitTimeoutError:
                pass  # buffer was already empty — good
    except Exception:
        pass  # flush is best-effort; never block the test
    print("   🎙️ Microphone ready.\n")

    # Set up logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"test_run_{timestamp}.txt"

    ollama = OllamaClient(model=_load_ollama_model())

    # Use pre-built persona if caller already ran prepare_persona() before
    # app navigation. Fall back to load/generate here only when called directly
    # without a pre-built persona (e.g. standalone testing).
    if persona_text:
        ravi_persona = persona_text
    elif scenario:
        ravi_persona = generate_persona_from_scenario(scenario, ollama)
        print(f'📋 Generated persona from scenario: "{scenario}"')
        print("-" * 60)
        print(ravi_persona)
        print("-" * 60)
    else:
        name = persona_name or "default"
        ravi_persona = load_persona(name)
        print(f"📋 Loaded persona: {name}")

    # Set up microphone
    mic_index = find_microphone_index(mic_name)
    recognizer = sr.Recognizer()
    # Start from a known-good threshold so a stale high value from a previous
    # run doesn't cause Turn 1 to sit in listen() indefinitely.
    # dynamic_energy_threshold=True will self-correct from here once audio arrives.
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    # Pre-warm Whisper so turn 1 transcription doesn't pay the model-load cost.
    print("⏳ Loading Whisper model (base.en)...")
    import whisper as _whisper_lib
    _whisper_lib.load_model("base.en")
    print("✅ Whisper ready.")

    # Initialize log
    persona_label = persona_name or scenario or "default"
    with open(log_file, "w") as f:
        f.write(f"Persona: {persona_label}\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-" * 20 + "\n\n")

    conversation_history = []
    rejected_items = []    # Items the agent has explicitly said are unavailable
    confirmed_updates = [] # Actions the agent has confirmed are already done
    last_offer = None      # Most recent list of options the agent asked Ravi to choose from
    turn = 1

    # State machine: build the ordered item list.
    # Priority: voice_items (ordering script) > expected_items > persona text.
    # voice_items lets removal scenarios order more items than the final verified set.
    if voice_items:
        items_to_order = [_yaml_item_to_speech(i) for i in voice_items]
        print(f"📋 State machine loaded {len(items_to_order)} item(s) from voice_items: {items_to_order}")
    elif expected_items:
        items_to_order = [_yaml_item_to_speech(i) for i in expected_items]
        print(f"📋 State machine loaded {len(items_to_order)} item(s) from YAML: {items_to_order}")
    else:
        items_to_order = _parse_items_from_persona(ravi_persona)
        if items_to_order:
            print(f"📋 State machine loaded {len(items_to_order)} item(s) from persona: {items_to_order}")
        else:
            print("⚠️  Could not parse items — ordering turns will fall back to Ollama")
    items_ordered_idx = 0   # index of the next item to order
    items_removed_idx = 0   # index of the next item to remove (via items_to_remove)
    requests_idx = 0        # index of the next post-order request (via post_order_requests)
    queries_asked_idx = 0   # index of the next pre-order query to ask
    _awaiting_recommendation = False  # True after a pre_order_query fires; tags next agent turn
    _awaiting_acceptance = False      # True after recommendation is tagged; forces acceptance response
    _post_query_order_next = False    # True after pre_order_query answered w/ items remaining; orders next item

    print("\n🎤 AI Customer (Ravi) is listening for the voice agent...")
    print("   Make sure phone speaker volume is up so computer mic can hear it.")
    print("   Press Ctrl+C to end conversation early.\n")

    cvv_spoken = False  # set True when CVV bypass fires; triggers post-loop confirmation wait
    ravi_just_spoke = False   # True after any speak_sync(); triggers calibration next listen
    prev_agent_word_count = 0  # word count of last agent utterance; drives pause_threshold
    last_ravi_response = ""   # last thing Ravi said — used for echo detection

    try:
        with open(log_file, "a") as log_f:
            while True:
                print(f"--- Turn {turn} ---")

                try:
                    # 1. Listen for the voice agent (phone) speaking
                    #
                    # Echo-decay sleep BEFORE opening the mic so adjust_for_ambient_noise
                    # doesn't consume agent speech.  Ravi's TTS echo takes ~0.3–0.5 s to
                    # decay; sleeping here (mic not open) drains the room without losing
                    # any of Ava's next utterance.  Inside the mic we calibrate for only
                    # 0.2 s — just enough to reset the elevated energy threshold.
                    if ravi_just_spoke:
                        time.sleep(0.5)
                    with sr.Microphone(device_index=mic_index) as source:
                        recognizer.dynamic_energy_threshold = True
                        recognizer.pause_threshold = 1.5
                        if ravi_just_spoke:
                            recognizer.adjust_for_ambient_noise(source, duration=0.2)
                            ravi_just_spoke = False
                        # Turn 1: ravi_just_spoke=False — skip calibration entirely so
                        # we start listening the instant the mic opens.

                        print("\n   🔴 Listening for Agent...")
                        audio = recognizer.listen(source, timeout=45, phrase_time_limit=30)

                    print("   🔄 Transcribing agent's speech...")
                    agent_speech = recognizer.recognize_whisper(audio, model="base.en")
                    print(f'   👨‍💼 Agent: "{agent_speech}"')
                    prev_agent_word_count = len(agent_speech.split())

                    # Echo guard — Ravi's voice travels Mac speakers → room → Mac mic.
                    # See _is_room_echo() for the Jaccard similarity logic.
                    if _is_room_echo(agent_speech, last_ravi_response):
                        print("   🔇 Echo of Ravi's last utterance detected — skipping")
                        log_f.write("[Echo skipped]\n")
                        continue

                    # Skip blank / noise transcriptions — don't call Ollama on silence.
                    # Exception: Turn 1 state machine always fires regardless of agent
                    # speech so we don't loop forever when the agent spoke before the
                    # test started listening.
                    if len(agent_speech.strip()) < 4 and turn != 1:
                        print("   ⚠️  Agent speech too short — waiting for next turn")
                        log_f.write("[Agent speech too short — skipped]\n")
                        continue

                    agent_line = f"Agent: {agent_speech}"
                    conversation_history.append(agent_line)
                    log_f.write(agent_line + "\n")
                    if _awaiting_recommendation:
                        log_f.write(f"[AGENT RECOMMENDATION]: {agent_speech}\n")
                        _awaiting_recommendation = False
                        if not items_to_order:
                            # Pure recommendation scenario (vegetarian/group_order): accept whatever the agent suggested.
                            _awaiting_acceptance = True
                        else:
                            # Items are pre-defined (e.g. gluten_free_inquiry, menu_inquiry_dessert).
                            # The agent answered a question but may not re-ask an order prompt.
                            # Flag so Ollama is bypassed if the state machine also misses this turn.
                            _post_query_order_next = True

                    # Disclaimer check on Turn 1: Ava's greeting and the disclaimer
                    # render simultaneously, so this is the earliest reliable moment.
                    if turn == 1 and driver is not None:
                        disclaimer_ok = verify_ai_disclaimer(driver)
                        if phase_statuses is not None:
                            phase_statuses["disclaimer"] = "passed" if disclaimer_ok else "failed"
                        log_f.write(f"[DISCLAIMER: {'passed' if disclaimer_ok else 'failed'}]\n")

                    if "exit" in agent_speech.lower() or "goodbye" in agent_speech.lower():
                        print("\n🛑 Agent ended the session.")
                        break

                    # Check for agent-side termination conditions.
                    # Only match phrases that confirm the order is COMPLETED —
                    # NOT phrases that merely mention payment or transfer in
                    # the context of asking for CVV / card details.
                    # "payment" and "transfer" alone are intentionally excluded
                    # because they also appear in "please provide your payment
                    # details" / "I'll process your payment", which would cause
                    # Ravi to exit before supplying the CVV.
                    agent_lower = agent_speech.lower()
                    # Strip punctuation and collapse spaces — Whisper inserts periods/
                    # commas mid-sentence (e.g. "placed. successfully") which breaks
                    # substring checks.
                    agent_stripped = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', agent_lower))
                    order_complete_phrases = [
                        "thank you for your order",
                        "order has been placed", "has been placed",
                        "order is placed",
                        "placed successfully", "successfully placed",
                        "order is confirmed", "order confirmed",
                        "your order is complete", "order complete",
                        "order was placed", "order was confirmed",
                        "payment was successful", "successfully processed",
                        "done processing your order",
                    ]
                    if any(phrase in agent_stripped for phrase in order_complete_phrases):
                        print("\n✅ Order confirmed by agent. Ending conversation.")
                        speak_sync("Thank you.")
                        log_f.write("Ravi: Thank you.\n")
                        break

                    # Agent audio failure — agent can't hear Ravi. This is a
                    # terminal condition; the session cannot progress.
                    _audio_fail_phrases = [
                        "sorry your audio", "audio cannot be",
                        "cannot hear your audio", "can't hear your audio",
                        "having trouble hearing you", "unable to hear you",
                        "audio is not coming through", "can't hear you",
                        "cannot hear you",
                    ]
                    if any(p in agent_lower for p in _audio_fail_phrases):
                        print("\n⚠️  Agent reports audio failure. Ending conversation.")
                        log_f.write("[AUDIO_FAILURE]\n")
                        break

                    # ── CVV bypass ────────────────────────────────────────────────────
                    # When the agent explicitly requests the CVV, skip Ollama entirely
                    # and respond with the stored CVV value. This is 100% reliable —
                    # Ollama has repeatedly failed to follow the CVV rule in personas.
                    #
                    # STT commonly mis-transcribes "CVV" as:
                    #   "CV"  — detected via \bcv\b (word boundary, safe against
                    #           "receive"/"service"/"active" false matches)
                    #   "CVD" / "CVC" — detected as substrings (uncommon in other contexts)
                    # Multi-word variants: "security code", "card verification", etc.
                    # Also match phrasing like "3-digit code on the back of your card"
                    # which Whisper transcribes when the agent doesn't say "CVV" aloud.
                    # Search agent_stripped (punctuation removed) so "C.V.V." → "CVV".
                    CVV_KEYWORD_RE = re.compile(
                        r'\bcvv\b|\bcvd\b|\bcdv\b|\bcvc\b|\bcbv\b|\bcv\b|\bcdd\b|\bcd\b'
                        r'|security code|card verification|verification code'
                        r'|back of your card|back of the card'
                        r'|\bthree.?digit\b|\b3.?digit\b'
                        r'|card number on the back|number on the back',
                        re.IGNORECASE,
                    )
                    # "?" alone is sufficient — if the agent asks ANY question that
                    # contains a CVV keyword it is requesting the CVV.
                    # "asked for" / "requested" cover rephrases like
                    # "I asked for the CVV code to process your payment."
                    CVV_REQUEST_WORDS = [
                        "provide", "enter", "give", "need your", "need the",
                        "please", "what is", "tell me", "supply", "confirm",
                        "say", "share", "asked", "requested",
                    ]
                    # Search both raw lowercased and punctuation-stripped strings so
                    # Whisper artefacts like "C.V.V." (periods between letters) still match.
                    _cvv_search_text = agent_lower + " " + agent_stripped
                    if (termination_trigger == "cvv"
                            and CVV_KEYWORD_RE.search(_cvv_search_text)
                            and (any(w in _cvv_search_text for w in CVV_REQUEST_WORDS)
                                 or "?" in agent_speech)):
                        ravi_response = f"My CVV is {cvv}."
                        print(f"   🔑 CVV requested — bypassing Ollama")
                        print(f'   👤 Ravi (AI): "{ravi_response}"')
                        # Speak with the same natural grouping a human uses for CVV:
                        # '382' → 'three eighty two' as one continuous phrase at
                        # natural rate. Separate-digit utterances triggered the IVR's
                        # end-of-input timeout after the first digit; a single phrase
                        # with human-style prosody avoids that.
                        speak_sync(_cvv_to_spoken_words(cvv), rate="+0%")
                        last_ravi_response = ravi_response
                        ravi_line = f"Ravi: {ravi_response}"
                        conversation_history.append(ravi_line)
                        log_f.write(ravi_line + "\n")
                        print("\n✅ CVV provided. Waiting for order confirmation...")
                        cvv_spoken = True
                        break

                    # ── Payment confirmation bypass ───────────────────────────────────
                    # When the agent asks Ravi to confirm paying with a saved card,
                    # respond with "Yes, please go ahead." deterministically.
                    # This prevents Ollama from producing vague replies like
                    # "I'd like to pay by card" that confuse the agent.
                    PAYMENT_CONFIRM_PHRASES = [
                        "would you like to pay with",
                        "would you like to paint with",   # STT: "pay" → "paint"
                        "pay with your credit card",
                        "paint with your credit card",    # STT variant
                        "credit card ending",
                        "card ending in",
                        "shall i charge",
                        "charge to your card",
                        "use your card",
                        "use the card",
                        "would you like to finalize",     # order finalization confirm
                        "would you like to confirm your order",
                        "ready to place your order",
                        "place your order",
                    ]
                    # Guard: don't fire payment bypass if agent is asking for a
                    # verification code — e.g. "provide the CDV code for your
                    # card ending in 007?" contains "card ending in" but should
                    # go to CVV bypass, not payment bypass.
                    _asking_for_code = (
                        bool(re.search(
                            r'\b(provide|enter|give|supply|share|tell me)\b.{0,40}\bcode\b',
                            agent_lower,
                        ))
                        or bool(CVV_KEYWORD_RE.search(_cvv_search_text))
                    )
                    if ("?" in agent_speech
                            and any(p in agent_lower for p in PAYMENT_CONFIRM_PHRASES)
                            and not _asking_for_code):
                        if mind_change_item:
                            # Change-of-mind still pending — speak it now (last chance
                            # before payment locks in) instead of confirming payment.
                            # Agent will add the item and loop back to payment.
                            ravi_response = mind_change_item
                            mind_change_item = None
                            print(f"   🔄 Change-of-mind at payment — deferring confirmation")
                        else:
                            ravi_response = "Yes, please go ahead."
                        print(f"   💳 Payment confirmation — bypassing Ollama")
                        print(f'   👤 Ravi (AI): "{ravi_response}"')
                        speak_sync(ravi_response)
                        ravi_just_spoke = True
                        last_ravi_response = ravi_response
                        ravi_line = f"Ravi: {ravi_response}"
                        conversation_history.append(ravi_line)
                        log_f.write(ravi_line + "\n")
                        last_offer = None
                        turn += 1
                        print("-" * 60)
                        continue  # wait for agent's next turn (CVV request)

                    # CVV failure — agent gave up collecting CVV and is routing
                    # to checkout. This is a terminal condition: no CVV was
                    # collected and the session is over.
                    _cvv_fail_phrases = [
                        "wasn't able to get", "was not able to get",
                        "unable to get", "couldn't get", "could not get",
                        "failed to get",
                    ]
                    if (CVV_KEYWORD_RE.search(_cvv_search_text)
                            and any(p in agent_lower for p in _cvv_fail_phrases)):
                        print("\n⚠️  Agent could not collect CVV — routing to checkout. Ending conversation.")
                        log_f.write("[CVV_COLLECTION_FAILED]\n")
                        break

                    # Track items the agent has explicitly said are unavailable.
                    # The full agent sentence is stored so specific sizes/items
                    # can be injected verbatim into the constraint block.
                    # Note: "i'm sorry," (bare) is intentionally excluded — it
                    # matches CVV failure messages ("I'm sorry, I wasn't able to
                    # get your CVV") which are NOT item rejections.
                    rejection_phrases = [
                        "don't have", "do not have", "we don't", "we do not",
                        "not available", "unfortunately", "i'm sorry, we",
                        "sorry, we don't", "sorry, we do not",
                        "i'm sorry, that's", "i'm sorry, that",
                        "can't add", "cannot add",
                    ]
                    if any(p in agent_lower for p in rejection_phrases):
                        if agent_speech.strip() not in rejected_items:
                            rejected_items.append(agent_speech.strip())
                            print(f"   📋 Rejection noted: \"{agent_speech.strip()}\"")

                    # Track when the agent confirms an action is already done.
                    # e.g. "I've already updated your order", "You already have wings"
                    confirmation_phrases = [
                        "i've already", "i have already", "already updated",
                        "already added", "already removed", "already swapped",
                        "already changed", "already included", "already have the",
                        "you already have", "i've updated your order",
                        "i've added", "i've removed", "i've swapped",
                    ]
                    if any(p in agent_lower for p in confirmation_phrases):
                        if agent_speech.strip() not in confirmed_updates:
                            confirmed_updates.append(agent_speech.strip())
                            print(f"   ✅ Confirmation noted: \"{agent_speech.strip()}\"")

                    # Track when the agent offers a list of options to choose from.
                    # Detected when agent asks a question AND lists specific items
                    # (e.g. "We have Pepsi, Diet Pepsi and Mountain Dew. Which would you like?")
                    # Unambiguous choice phrases — set last_offer regardless of "or"
                    CHOICE_PHRASES = [
                        "we have", "you can choose", "you can pick",
                        "which would you", "what size", "what kind", "what flavor",
                        "which size", "which flavor", "do you prefer", "would you prefer",
                        "which one", "which do you",
                    ]
                    # Ambiguous yes/no phrases — only set last_offer when real options
                    # ("or", a size/flavor word) are also present; avoids treating
                    # "Would you like to add a tip?" as an option-selection prompt.
                    AMBIGUOUS_PHRASES = ["would you like", "do you want"]
                    _has_options = (
                        " or " in agent_lower
                        or any(w in agent_lower for w in ("small", "medium", "large",
                                                          "original", "garlic", "thin",
                                                          "regular", "extra"))
                    )
                    _is_quantity_q = re.search(r'\bhow (much|many)\b', agent_lower)
                    _triggers_offer = (
                        any(p in agent_lower for p in CHOICE_PHRASES)
                        or (any(p in agent_lower for p in AMBIGUOUS_PHRASES) and _has_options)
                    )
                    if (_is_question(agent_speech, agent_lower)
                            and _triggers_offer
                            and not _is_quantity_q):
                        last_offer = agent_speech.strip()
                        print(f"   🍕 Offer noted: \"{last_offer}\"")

                    # ── Pre-order query interception ─────────────────────────────────
                    # If the scenario defines pre_order_queries (e.g. "What desserts do
                    # you have?"), inject the next query when the agent says an order
                    # prompt instead of ordering item[0].  Once all queries are asked,
                    # control falls through to the normal deterministic state machine.
                    pre_q = _get_pre_order_query(agent_lower, pre_order_queries, queries_asked_idx)
                    if pre_q:
                        ravi_response, queries_asked_idx = pre_q
                        _awaiting_recommendation = True  # tag the agent's next turn as recommendation
                        print(f"   ❓ Pre-order query ({queries_asked_idx}/{len(pre_order_queries)}): {ravi_response!r}")
                        speak_sync(ravi_response)
                        log_f.write(f"Ravi: {ravi_response} [DETERMINISTIC]\n")
                        ravi_just_spoke = True
                        last_ravi_response = ravi_response
                        turn += 1
                        continue

                    # ── Recommendation acceptance ─────────────────────────────────────
                    # After the agent responds to a pre_order_query (dietary restriction,
                    # group size, etc.), accept the recommendation deterministically.
                    # Without this, Ollama loops back to the original query because the
                    # recommendation turn doesn't match any order/review/ack pattern.
                    if _awaiting_acceptance:
                        ravi_response = "Yes, that sounds great, please add those."
                        _awaiting_acceptance = False
                        print(f"   🎯 Recommendation acceptance (deterministic)")
                        print(f'   👤 Ravi (AI): "{ravi_response}"')
                        speak_sync(ravi_response)
                        ravi_line = f"Ravi: {ravi_response} [DETERMINISTIC]"
                        conversation_history.append(ravi_line)
                        log_f.write(ravi_line + "\n")
                        ravi_just_spoke = True
                        last_ravi_response = ravi_response
                        turn += 1
                        print("-" * 60)
                        continue

                    # ── Deterministic state machine ───────────────────────────────────
                    # Handle predictable turns without Ollama:
                    #   turn 1 greeting / order prompts / "anything else?" / order review
                    # Ollama is only called when no pattern matches (ambiguous turns).
                    det = _get_deterministic_response(
                        agent_speech, agent_lower, turn,
                        items_to_order, items_ordered_idx, rejected_items,
                        items_to_remove, items_removed_idx,
                        post_order_requests, requests_idx,
                        mind_change_item, pipa_dough_action,
                    )
                    # Same-response cooldown: if the state machine would repeat Ravi's
                    # last response, don't silence Ravi entirely — fall through to Ollama
                    # so a different phrase is used.  A bare `continue` left the agent
                    # waiting in silence, which caused "I'm ready whenever you are" loops.
                    # _is_room_echo() is the primary echo guard; this is the variety guard.
                    if det is not None and det[0] == last_ravi_response:
                        print(f"   🔇 Same-response cooldown — using Ollama for variety")
                        log_f.write(f"[Repeat suppressed: '{det[0]}' — Ollama]\n")
                        det = None  # fall through to Ollama below
                    if det is not None:
                        ravi_response, items_ordered_idx, items_removed_idx, requests_idx = det
                        if mind_change_item and ravi_response == mind_change_item:
                            mind_change_item = None  # consumed — next review returns "Yes, that's right."
                        print(f"   🎯 Deterministic ({items_ordered_idx}/{len(items_to_order)} items ordered)")

                        # Schedule validation: when Rule 5a fires ("Yes, that works.")
                        # check that the agent's speech contains the pre-selected slot.
                        if (
                            expected_schedule
                            and ravi_response == "Yes, that works."
                            and any(p in agent_lower for p in (
                                "does that work", "does the time work"
                            ))
                        ):
                            norm = re.sub(r'\b0(\d:\d{2})', r'\1', expected_schedule)
                            # Whisper mis-transcribes times in several ways:
                            #   "7:00 PM" → "7 o'clock p.m."  (spoken form + dotted am/pm)
                            #   "6:30 PM" → "6.30pm"           (dot separator, no space)
                            # Step 0: strip dots from "p.m."/"a.m." → "pm"/"am"
                            agent_norm = re.sub(r'\b([ap])\.m\.?\b', r'\1m', agent_lower, flags=re.IGNORECASE)
                            # Step 1: "6.30pm" or "6.30 pm" → "6:30pm" or "6:30 pm"
                            #   No trailing \b — "30pm" has no word boundary before "p".
                            agent_norm = re.sub(r'\b(\d{1,2})\.(\d{2})', r'\1:\2', agent_norm)
                            # Step 2: "7 o'clock pm" → "7:00 pm"
                            agent_norm = re.sub(r"\b(\d{1,2})\s+o'?clock\b", r'\1:00', agent_norm)
                            # Step 3: "6:30pm" → "6:30 pm" (add space before am/pm)
                            agent_norm = re.sub(r'(\d{2})([ap]m)\b', r'\1 \2', agent_norm, flags=re.IGNORECASE)
                            if norm.lower() in agent_norm:
                                print(f"   ✅ Schedule confirmed by agent: '{expected_schedule}' in speech")
                                log_f.write(f"[SCHEDULE CONFIRMED: agent mentioned '{expected_schedule}']\n")
                            else:
                                print(f"   ⚠️  Schedule mismatch in conversation: expected '{expected_schedule}' not found in agent speech")
                                log_f.write(f"[SCHEDULE MISMATCH: expected '{expected_schedule}' not in agent speech]\n")

                        print(f'   👤 Ravi (AI): "{ravi_response}"')
                        speak_sync(ravi_response)
                        ravi_just_spoke = True
                        last_ravi_response = ravi_response
                        ravi_line = f"Ravi: {ravi_response}"
                        conversation_history.append(ravi_line)
                        log_f.write(ravi_line + " [DETERMINISTIC]\n")
                        last_offer = None
                        turn += 1
                        print("-" * 60)
                        continue

                    # ── Post-query order injection ────────────────────────────────────
                    # After a pre_order_query was answered (e.g. "Do you have
                    # gluten-free crust?") the agent may not re-issue an order prompt.
                    # Without this, Ollama loops back to re-asking the question.
                    # Inject the next item directly if the flag is set.
                    if _post_query_order_next and items_ordered_idx < len(items_to_order):
                        _post_query_order_next = False
                        ravi_response = f"I'd like {items_to_order[items_ordered_idx]} please."
                        items_ordered_idx += 1
                        print(f"   🎯 Post-query order ({items_ordered_idx}/{len(items_to_order)} items ordered)")
                        print(f'   👤 Ravi (AI): "{ravi_response}"')
                        speak_sync(ravi_response)
                        ravi_just_spoke = True
                        last_ravi_response = ravi_response
                        ravi_line = f"Ravi: {ravi_response}"
                        conversation_history.append(ravi_line)
                        log_f.write(ravi_line + " [DETERMINISTIC]\n")
                        turn += 1
                        print("-" * 60)
                        continue
                    _post_query_order_next = False  # clear flag if state machine already handled the turn

                    # 2. Get AI response (Ollama fallback for ambiguous turns).
                    # Mandatory preamble is injected at the top of EVERY prompt so
                    # the LLM reads it before conversation history. Conditional blocks
                    # (rejections, confirmations, offers) follow after.
                    print("   🤖 Ravi is thinking (Ollama)...")
                    prompt = (
                        "MANDATORY — obey these before reading anything else:\n"
                        "• You are Ravi, a real customer. Speak ONLY as Ravi. "
                        "Never explain, narrate, or break character. "
                        "If the agent's speech is garbled or confusing, say: Sorry, could you say that again?\n"
                        "• STOP after 1–2 short spoken sentences. "
                        "Output NOTHING after your second sentence. "
                        "Do NOT put quotes around your words.\n"
                        "• Answer the agent's last sentence directly. "
                        "Do not redirect to a different topic.\n"
                        "• Do NOT repeat anything you already said in a previous turn.\n"
                        "• Do NOT output any prefix like 'Ravi:', 'Agent:', 'Customer:'. "
                        "Output ONLY the spoken words.\n"
                        "• If the agent gives a short acknowledgment "
                        "('Okay', 'Got it', 'Alright') with no question, "
                        "say ONLY: Okay, thanks.\n"
                        "• If the agent asks you to confirm payment or a card, "
                        "say ONLY: Yes, please go ahead.\n"
                        "\n"
                    )
                    has_rules = rejected_items or confirmed_updates or last_offer
                    if has_rules:
                        prompt += "ADDITIONAL RULES FOR THIS RESPONSE:\n"

                    if rejected_items:
                        prompt += (
                            "The agent has confirmed these items are NOT AVAILABLE.\n"
                            "You MUST NOT mention, request, or reference any of them again "
                            "in any form (including size variants):\n"
                        )
                        for r in rejected_items:
                            prompt += f"  ✗ {r}\n"
                        prompt += "If the agent offered alternatives, pick one of those instead.\n"

                    if confirmed_updates:
                        prompt += (
                            "The agent has ALREADY CONFIRMED these actions are done. "
                            "Do NOT ask for them again, do NOT reference these items as missing or unresolved. "
                            "Treat them as complete:\n"
                        )
                        for c in confirmed_updates:
                            prompt += f"  ✓ {c}\n"
                        if len(confirmed_updates) >= 2:
                            prompt += (
                                "WARNING: You have been repeating yourself. "
                                "The agent has confirmed the same thing multiple times. "
                                "Stop asking about it and move the conversation forward. "
                                "If your order is complete, say so and wrap up the call.\n"
                            )

                    if last_offer:
                        # Parse "X or Y" options for explicit guidance
                        _or_match = re.search(
                            r'\b([\w][\w\s]+?)\s+or\s+([\w][\w\s]+?)(?:\?|$)',
                            last_offer, re.IGNORECASE,
                        )
                        _offer_options = (
                            [_or_match.group(1).strip(), _or_match.group(2).strip()]
                            if _or_match else []
                        )
                        prompt += (
                            f"The agent is asking you to choose a TYPE or VARIANT. "
                            f"You MUST pick EXACTLY ONE option. "
                            f"Say: 'I'd like the [option] please.' "
                            f"Do NOT re-order items. Do NOT say 'I'd also like...'\n"
                            f"Agent's question: \"{last_offer}\"\n"
                        )
                        if _offer_options:
                            prompt += (
                                f"Your choices are: '{_offer_options[0]}' OR "
                                f"'{_offer_options[1]}'. Pick one.\n"
                            )

                    # Loop detection: if Ravi just repeated the same response the
                    # agent rejected it — inject a hard "do NOT repeat" rule.
                    _ravi_turns = [l for l in conversation_history if l.startswith("Ravi: ")]
                    if len(_ravi_turns) >= 2:
                        def _strip_tag(line):
                            return re.sub(r'\s+\[(DETERMINISTIC|OLLAMA)\]$', '', line
                                          ).replace("Ravi: ", "").strip()
                        _last_r = _strip_tag(_ravi_turns[-1])
                        _prev_r = _strip_tag(_ravi_turns[-2])
                        if _last_r.lower() == _prev_r.lower():
                            prompt += (
                                f"CRITICAL: You just said '{_last_r}' but the agent "
                                f"asked the same question again — that response was wrong. "
                                f"Do NOT repeat it. Give a COMPLETELY DIFFERENT answer "
                                f"that directly answers the agent's current question.\n"
                            )

                    if has_rules:
                        prompt += "\n"

                    # Only include the last 8 turns — prevents context overflow and
                    # keeps mandatory rules at the top in the LLM's active attention.
                    # Strip [DETERMINISTIC]/[OLLAMA] debug tags — they add noise that
                    # can anchor the model to previous wrong responses.
                    recent_history = [
                        re.sub(r'\s+\[(DETERMINISTIC|OLLAMA)\]$', '', line)
                        for line in conversation_history[-8:]
                    ]
                    prompt += "Conversation History:\n" + "\n".join(recent_history)
                    prompt += (
                        "\n\nYou are Ravi. Respond with ONLY your spoken words — "
                        "no quotes, no stage directions, no explanations. "
                        "What do you say next? (1–2 sentences max)"
                    )

                    ravi_response = ollama.generate(prompt, system=ravi_persona)
                    ravi_response = _clean_ravi_response(ravi_response)

                    # 3. Ravi (AI) speaks
                    print(f'   👤 Ravi (AI): "{ravi_response}"')
                    speak_sync(ravi_response)
                    ravi_just_spoke = True
                    last_ravi_response = ravi_response

                    ravi_line = f"Ravi: {ravi_response}"
                    conversation_history.append(ravi_line)
                    log_f.write(ravi_line + " [OLLAMA]\n")
                    last_offer = None  # Ravi has responded — clear pending offer

                    # Sync items_ordered_idx with what Ollama just said.
                    # When Ollama handles a turn (e.g. agent acknowledgment like
                    # "One large pepperoni pizza.") it may order the next queued
                    # item. Without this sync the state machine's idx is still
                    # pointing at that same item, so the next "Anything else?"
                    # turn re-orders it as a duplicate.
                    # Check: if any distinctive keyword (len > 4) from the next
                    # queued item appears in Ravi's response, assume that item
                    # was just ordered and advance the index.
                    if items_to_order and items_ordered_idx < len(items_to_order):
                        next_item = items_to_order[items_ordered_idx]
                        next_item_kws = [w for w in next_item.lower().split() if len(w) > 4]
                        if next_item_kws and any(kw in ravi_response.lower() for kw in next_item_kws):
                            items_ordered_idx += 1
                            print(f"   📋 Ollama ordered '{next_item}' — "
                                  f"idx → {items_ordered_idx}/{len(items_to_order)}")

                    # 4. Check if Ravi is ending the conversation.
                    # Note: CVV is now handled by the agent-side bypass above.
                    # This only catches explicit goodbye phrases.
                    end_phrases = ["goodbye", "thanks, bye"]
                    if any(phrase in ravi_response.lower() for phrase in end_phrases):
                        print("\n✅ Ravi has ended the conversation. Test complete.")
                        break

                except sr.UnknownValueError:
                    print("   ⚠️  Could not understand audio. Please try again.")
                    log_f.write("[Audio not understood]\n")
                    continue
                except sr.RequestError as e:
                    print(f"   Could not request results; {e}")
                    log_f.write(f"[Request Error: {e}]\n")
                    continue

                turn += 1
                print("-" * 60)

            # CVV has been spoken — keep listening until the agent confirms the
            # order is placed (or reports a failure) before handing off to verification.
            if cvv_spoken:
                confirmation_status = _wait_for_order_confirmation(recognizer, mic_index, log_f)
                if confirmation_status == "payment_failed":
                    log_f.write("[PAYMENT FAILED — skipping to verification for failure report]\n")

    except KeyboardInterrupt:
        print("\n🛑 Session interrupted by user. Exiting.")
    except sr.WaitTimeoutError:
        print("\n\n[Timeout: No speech detected from phone]")
    except Exception as e:
        print(f"\n\n[Error: {e}]")
        import traceback
        traceback.print_exc()

    print(f"\n✅ Conversation saved to: {log_file}")
    return str(log_file)


def _log_has_payment_failure(log_file: str) -> bool:
    """Return True if the conversation log contains a payment failure marker."""
    if not log_file:
        return False
    try:
        with open(log_file) as f:
            return "[PAYMENT FAILED" in f.read()
    except Exception:
        return False


def find_microphone_index(mic_name):
    """Find microphone by name. Returns None (system default) when mic_name is None."""
    import speech_recognition as sr

    if not mic_name:
        return None  # Use system default

    mics = sr.Microphone.list_microphone_names()
    for index, name in enumerate(mics):
        if mic_name.lower() in name.lower():
            print(f"  Using microphone: {name}")
            return index
    print(f"  Microphone '{mic_name}' not found, using default")
    return None  # Use default


def run_dump_screen(args):
    """
    Navigate to the voice ordering screen and dump all visible text + full
    page_source to logs/.  Exits immediately after — no conversation, no test.

    Usage:
        python end_to_end_voice_test.py --dump-screen
        python end_to_end_voice_test.py --dump-screen --mic "External Microphone"

    Output files (in logs/):
        dump_screen_<ts>.json   texts list + page_source as JSON
    """
    import json
    from datetime import datetime as _dt

    driver = launch_app()
    element = scroll_to_start_voice_order(driver)
    if not element:
        print("❌ Could not find 'Start Voice Order' button")
        return 1
    click_start_voice_order(driver, element)
    click_arrow_on_ready_screen(driver)

    time.sleep(3)  # let Ava's greeting and the disclaimer render

    # Scrape element texts
    driver.driver.implicitly_wait(0)
    try:
        elements = driver.driver.find_elements(
            AppiumBy.XPATH, "//*[@text != '' or @content-desc != '']"
        )
        texts = []
        for el in elements:
            for attr in ("text", "content-desc"):
                val = el.get_attribute(attr)
                if val and val.strip():
                    texts.append(val.strip())
    except Exception as e:
        print(f"⚠️  Element scrape error: {e}")
        texts = []
    finally:
        driver.driver.implicitly_wait(10)

    # Full page_source
    try:
        source = driver.driver.page_source
    except Exception as e:
        print(f"⚠️  page_source error: {e}")
        source = ""

    print(f"\n{'='*60}")
    print(f"Screen texts ({len(texts)}):")
    for t in texts:
        print(f"  {t!r}")
    print(f"\npage_source length: {len(source)} chars")

    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(logs_dir, f"dump_screen_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"texts": texts, "page_source": source}, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved → {out_path}")
    print("   Copy texts/page_source into unit_tests/fixtures/ and write tests against them.")
    return 0


def run_full_flow(args):
    """
    Full flow: Launch app → AI customer conversation → verify cart
    """
    driver = None
    phase_statuses = {"navigation": "skipped", "conversation": "skipped", "verification": "skipped"}
    start_time = datetime.now()
    log_file   = None
    session_id = ""   # initialised here so report generation can always reference it
    results = {
        "passed": False, "score": 0,
        "matched_items": [], "missing_items": [], "extra_items": [],
        "reasoning": "Test did not complete.", "overview": {},
    }

    try:
        _ensure_ollama_running()
        _ensure_appium_running()

        # ── Pre-flight: generate persona BEFORE launching the app ─────────
        # Ollama generation can take several seconds. Doing it here avoids a
        # gap between the voice agent going live and Ravi being ready to respond.
        print("\n" + "=" * 70)
        print("PRE-FLIGHT: Preparing Ravi's Persona")
        print("=" * 70)
        ravi_persona = prepare_persona(
            persona_name=args.persona, scenario=args.scenario
        )

        # Clear stale screenshots from previous runs so the report only
        # shows images captured during this run.
        _config_path = getattr(args, "config", "config/appium_config.yaml")
        screenshot_dir = Path(_config_path)  # resolve below
        try:
            import yaml
            with open(_config_path) as _f:
                _cfg = yaml.safe_load(_f)
            raw = _cfg["test"].get("screenshot_dir", "")
            screenshot_dir = Path(raw) if raw else Path(tempfile.gettempdir()) / "screenshots"
        except Exception:
            screenshot_dir = Path(tempfile.gettempdir()) / "screenshots"

        if screenshot_dir.is_dir():
            removed = 0
            for f in glob.glob(str(screenshot_dir / "*.png")):
                try:
                    os.remove(f)
                    removed += 1
                except Exception:
                    pass
            if removed:
                print(f"🧹 Cleared {removed} screenshot(s) from previous run in {screenshot_dir}")

        print("\n" + "=" * 70)
        print("PHASE 1: Navigate to Voice Agent")
        print("=" * 70)

        driver = launch_app(config_path=getattr(args, "config", "config/appium_config.yaml"))
        element = scroll_to_start_voice_order(driver)
        if not element:
            print("❌ Could not find 'Start Voice Order' button")
            phase_statuses["navigation"] = "failed"
            return 1

        click_start_voice_order(driver, element)
        click_arrow_on_ready_screen(driver)
        #grant_microphone_permission(driver)

        agent_active = verify_voice_agent_active(driver)
        if not agent_active:
            print("⚠️  Voice agent verification failed, but continuing...")
            phase_statuses["navigation"] = "failed"
        else:
            phase_statuses["navigation"] = "passed"

        session_id = get_voice_session_id(driver)

        print("\n" + "=" * 70)
        print("PHASE 2: AI Customer Conversation")
        print("=" * 70)
        print("\n🤖 Starting AI customer (Ravi)...")
        print("\nAudio Setup:")
        print("  • Computer speakers playing Ravi's voice → Phone mic hears it")
        print("  • Phone speaker playing agent → Computer mic hears it")
        print("\n🎤 Voice agent is already speaking - starting conversation now...")

        # Run AI customer conversation (persona already prepared above)
        try:
            log_file = run_ai_customer_conversation(
                persona_name=args.persona, scenario=args.scenario, mic_name=args.mic,
                termination_trigger=args.termination_trigger,
                persona_text=ravi_persona,
                cvv=args.cvv,
                driver=driver,
                phase_statuses=phase_statuses,
            )
        except Exception as e:
            print(f"\n❌ AI customer conversation failed: {e}")
            print("   No conversation took place — cart verification cannot proceed.")
            phase_statuses["conversation"] = "failed"
            return 1

        if log_file is None:
            print("\n❌ Conversation ended without producing a log.")
            phase_statuses["conversation"] = "failed"
            return 1

        phase_statuses["conversation"] = "passed"

        print("\n" + "=" * 70)
        print("PHASE 3: Verify Order Complete Screen")
        print("=" * 70)

        if _log_has_payment_failure(log_file):
            print("❌ Payment failure detected in conversation log — skipping order verification.")
            results = {
                "passed": False, "score": 0,
                "matched_items": [], "missing_items": [],
                "extra_items": [],
                "reasoning": "Payment failed — the app could not process the payment.",
                "overview": {},
            }
            phase_statuses["verification"] = "failed"
        else:
            print("\n🔍 Verifying order complete screen...")
            results = verify_order(driver, log_file=log_file)
            phase_statuses["verification"] = "passed" if results["passed"] else "failed"

        print(f"\n{'='*70}")
        print("VERIFICATION RESULTS")
        print(f"{'='*70}")
        print(f"  Status: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")
        print(f"  Score: {results['score']}/100")
        print(f"  Matched: {results['matched_items']}")
        print(f"  Missing: {results['missing_items']}")
        print(f"  Extra: {results['extra_items']}")
        print(f"  Reasoning: {results['reasoning']}")

        return 0 if results["passed"] else 1

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Generate the HTML report regardless of pass/fail/exception so there
        # is always a report to review.  driver may be None if launch failed.
        try:
            from src.report_generator import generate_report
            end_time      = datetime.now()
            screenshot_dir = (
                driver.config["test"]["screenshot_dir"] if driver else str(Path(tempfile.gettempdir()) / "screenshots")
            )
            report_path = generate_report(
                suite_results=[{
                    "name":           args.scenario or args.persona or "default",
                    "results":        results,
                    "phase_statuses": phase_statuses,
                    "log_file":       log_file,
                    "screenshot_dir": screenshot_dir,
                    "start_time":     start_time,
                    "end_time":       end_time,
                    "metadata": {
                        "persona":    args.persona,
                        "scenario":   args.scenario,
                        "mic":        args.mic,
                        "session_id": session_id,
                        "start_time": start_time,
                        "end_time":   end_time,
                    },
                }],
                suite_start=start_time,
                suite_end=end_time,
                show_images=args.show_images,
            )
            print(f"\n📊 HTML Report: {report_path}")
        except Exception as report_err:
            print(f"\n⚠️  Report generation failed: {report_err}")

        if driver:
            driver.stop()


def run_verify_only(args):
    """Verify cart only (app already open)"""
    driver = None
    try:
        print("\n" + "=" * 70)
        print("VERIFY CART MODE")
        print("=" * 70)
        print("\nAssuming app is already open with cart visible...")

        from src.appium_driver import AppiumDriver

        driver = AppiumDriver(getattr(args, "config", "config/appium_config.yaml"))
        driver.start()

        log_file = args.log if args.log else None
        results = verify_order(driver, expected_items=args.items, log_file=log_file)

        print(f"\n{'='*70}")
        print("VERIFICATION RESULTS")
        print(f"{'='*70}")
        print(f"  Status: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")
        print(f"  Score: {results['score']}/100")
        print(f"  Matched: {results['matched_items']}")
        print(f"  Missing: {results['missing_items']}")
        print(f"  Extra: {results['extra_items']}")
        print(f"  Reasoning: {results['reasoning']}")

        return 0 if results["passed"] else 1

    finally:
        if driver:
            driver.stop()


def main():
    parser = argparse.ArgumentParser(
        description="End-to-End Voice Ordering Test with AI Customer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full flow with AI customer (default persona)
  python end_to_end_voice_test.py --full

  # Full flow with specific persona
  python end_to_end_voice_test.py --full --persona rushed

  # Full flow with custom scenario
  python end_to_end_voice_test.py --full --scenario "hard of hearing customer"

  # Just verify cart (app already open)
  python end_to_end_voice_test.py --verify-only --log logs/test_run_20260209.txt

  # Verify with expected items
  python end_to_end_voice_test.py --verify-only --items "Large pepperoni" "Garlic knots"

Audio Setup (Physical):
  Position phone near computer speakers so phone mic captures Ravi's voice.
  Position computer mic near phone speaker to capture app voice agent.
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--full",
        action="store_true",
        help="Run full flow with AI customer conversation",
    )
    group.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify cart (assumes app already open)",
    )

    parser.add_argument(
        "--persona", type=str, help="AI customer persona name (from personas/ dir)"
    )
    parser.add_argument(
        "--scenario", type=str, help="Generate persona from scenario text"
    )
    parser.add_argument(
        "--mic",
        type=str,
        default="MacBook Pro Microphone",
        help="Microphone name for capturing phone audio",
    )
    parser.add_argument(
        "--cvv",
        type=str,
        default="382",
        help="CVV digits Ravi speaks when the agent requests them (default: 382).",
    )
    parser.add_argument(
        "--termination-trigger",
        dest="termination_trigger",
        choices=["cvv", "order_confirmed"],
        default="cvv",
        help=(
            "What signals the end of the conversation. "
            "'cvv' (default): exit after Ravi speaks the CVV (credit card flow). "
            "'order_confirmed': wait for the agent's order-confirmation phrase "
            "(use when payment is saved card, Apple Pay, PayPal, etc.)."
        ),
    )
    parser.add_argument(
        "--log", type=str, help="Conversation log file for verification"
    )
    parser.add_argument("--items", nargs="+", help="Expected items to verify")
    parser.add_argument(
        "--config",
        default="config/appium_config.yaml",
        help="Path to Appium config YAML (default: config/appium_config.yaml)",
    )
    parser.add_argument(
        "--dump-screen",
        action="store_true",
        help=(
            "Navigate to the voice ordering screen, dump all visible texts and "
            "the full page_source to logs/dump_screen_<ts>.json, then exit. "
            "Use this to inspect live screen content without running a full test."
        ),
    )

    img_group = parser.add_mutually_exclusive_group()
    img_group.add_argument(
        "--show-images",
        dest="show_images",
        action="store_true",
        default=True,
        help="Embed screenshots in HTML report (default: on)",
    )
    img_group.add_argument(
        "--no-images",
        dest="show_images",
        action="store_false",
        help="Omit screenshots from HTML report",
    )

    args = parser.parse_args()

    if args.dump_screen:
        return run_dump_screen(args)
    if args.full:
        return run_full_flow(args)
    else:
        return run_verify_only(args)


if __name__ == "__main__":
    sys.exit(main())
