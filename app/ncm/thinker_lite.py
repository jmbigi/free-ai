"""Thinker-lite: structured reasoning layer for the gateway.

Clean-room implementation inspired by public principles of jmbigi/thinker (GPL-3.0-only):
structured steps, validation before advancing, anti-repetition, explicit uncertainty.
No source code from that repository is copied here.

This module is **model-agnostic**: it wraps any LLM call made through the gateway,
adding deterministic arithmetic, intent analysis, validation, repair and honest
confidence metadata. It runs as a post-processor on the provider response.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


FILLER = re.compile(r"(\s*[.,]){4,}")
DUP_WORD = re.compile(r"^[a-z']+$")
MATH_WORDS = (
    ("multiplied by", "*"), ("divided by", "/"), ("times", "*"),
    ("plus", "+"), ("minus", "-"), ("over", "/"), ("x", "*"),
    ("×", "*"), ("÷", "/"),
    ("mas", "+"), ("más", "+"),
)
MATH_PREFIX = re.compile(
    r"^(what is|what's|whats|how much is|calculate|cuanto es|cuánto es|result of)\s*"
)
NAME_RE = re.compile(r"\bmy name is\s+([a-z0-9_-]+)", re.I)


def math_answer(text: str) -> str | None:
    """Deterministic arithmetic for simple expressions; None if not arithmetic."""
    t = text.lower().strip()
    for word, symbol in MATH_WORDS:
        t = t.replace(word, symbol)
    t = MATH_PREFIX.sub("", t).strip(" ?.")
    t = re.sub(r"\s+", " ", t)
    expr = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*", t)
    if not expr:
        return None
    a_s, op, b_s = expr.groups()
    a, b = float(a_s), float(b_s)
    if op == "+":
        result = a + b
    elif op == "-":
        result = a - b
    elif op == "*":
        result = a * b
    else:
        if b == 0:
            return "division by zero is undefined"
        result = a / b
    fmt = lambda x: str(int(x)) if float(x).is_integer() else f"{x:g}"
    return f"{fmt(a)} {op} {fmt(b)} = {fmt(result)}"


@dataclass
class Analysis:
    text: str
    intent: str
    confidence: str
    strategy: str
    notes: list[str] = field(default_factory=list)
    math_result: str | None = None
    expected_name: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


class ThinkerLite:
    """Structured pre-analysis, validation and repair for one chat turn.

    Usage:
        layer = ThinkerLite()
        analysis = layer.analyze(user_message)
        if analysis.math_result:
            return analysis.math_result  # deterministic, bypass LLM
        # ... call LLM ...
        valid, notes = layer.validate(llm_reply, analysis)
        if not valid:
            llm_reply = layer.repair(analysis, llm_reply)
        llm_reply = layer.decorate(llm_reply, analysis)
        metadata = layer.trace(analysis, valid=valid, notes=notes,
                               repaired=not valid, candidates=1)
        return llm_reply, metadata
    """

    def analyze(self, text: str) -> Analysis:
        raw = (text or "").strip()
        low = raw.lower()
        steps: list[dict[str, Any]] = [{"step": "normalize", "value": "lowercase/strip"}]
        math = math_answer(raw)
        if math is not None:
            analysis = Analysis(raw, "math", "high", "deterministic_math_guard", math_result=math)
        elif re.search(r"\b(hello|hi|hey|how are you|who are you|your name)\b", low):
            analysis = Analysis(raw, "identity", "high", "direct_llm")
        elif NAME_RE.search(raw):
            analysis = Analysis(raw, "recall", "high", "direct_llm",
                                expected_name=NAME_RE.search(raw).group(1).lower())
        elif re.search(r"\b(code|python|function|bug|implement|program|script|sql|api)\b", low):
            analysis = Analysis(raw, "code", "low", "llm_with_warning",
                                notes=["Model may hallucinate; verify output."])
        elif re.search(r"\b(what is|who is|when|where|how many|capital|define|explain)\b", low):
            analysis = Analysis(raw, "factual", "low", "llm_with_uncertainty",
                                notes=["Factual confidence low; cite sources if possible."])
        else:
            analysis = Analysis(raw, "chat", "medium", "direct_llm")
        steps.append({"step": "intent", "value": analysis.intent})
        steps.append({"step": "plan", "value": analysis.strategy})
        analysis.trace = steps
        return analysis

    def validate(self, reply: str, analysis: Analysis) -> tuple[bool, list[str]]:
        notes: list[str] = []
        text = (reply or "").strip()
        if not text:
            return False, ["empty reply"]
        if FILLER.search(text):
            notes.append("filler collapse detected")
            return False, notes
        words = text.split()
        dups = sum(1 for a, b in zip(words, words[1:]) if a == b and DUP_WORD.fullmatch(a))
        if dups:
            notes.append(f"duplicated neighbouring words: {dups}")
        if analysis.intent == "math":
            if analysis.math_result and analysis.math_result not in text:
                notes.append("math answer does not match deterministic result")
                return False, notes
        if analysis.intent == "recall" and analysis.expected_name:
            if analysis.expected_name not in text.lower():
                notes.append("recall answer does not contain the expected name")
                return False, notes
        if analysis.intent == "code":
            notes.append("code_warning: output not executed or verified")
            return False, notes
        if analysis.intent == "factual":
            notes.append("factual_confidence_low")
            lexical = re.findall(r"[a-z']+", text.lower())
            unique_ratio = len(set(lexical)) / max(1, len(lexical))
            most_common = max((lexical.count(w) for w in set(lexical)), default=0)
            if unique_ratio < 0.6 or most_common > 2:
                notes.append("factual_repetition_or_low_diversity")
                return False, notes
        return True, notes

    def repair(self, analysis: Analysis, reply: str) -> str:
        if analysis.intent == "math" and analysis.math_result:
            return analysis.math_result
        if analysis.intent == "code":
            return "i cannot reliably generate code; please verify any code snippet."
        if analysis.intent == "factual":
            return "i'm not certain about that; please verify from a trusted source."
        if analysis.intent == "recall" and analysis.expected_name:
            return f"your name is {analysis.expected_name}."
        return "i'm not sure how to answer that."

    def decorate(self, reply: str, analysis: Analysis) -> str:
        text = (reply or "").strip()
        if analysis.intent == "factual" and text and not text.startswith("i'm not"):
            return f"i'm not certain, but {text}"
        return text

    def trace(self, analysis: Analysis, *, valid: bool, notes: list[str],
              repaired: bool, candidates: int) -> dict[str, Any]:
        return {
            "steps": analysis.trace + [
                {"step": "generate", "value": f"llm_best_of_{candidates}"},
                {"step": "validate", "value": "pass" if valid else "fail"},
                {"step": "repair", "value": "applied" if repaired else "not_needed"},
            ],
            "intent": analysis.intent,
            "confidence": analysis.confidence,
            "strategy": analysis.strategy,
            "valid": valid,
            "notes": notes,
            "source": "gateway thinker-lite; inspired by jmbigi/thinker (GPL-3.0-only)",
        }


class SlidingWindowContext:
    """Sliding window context management for models with fixed context limits.
    
    For NCM (128 tokens) and other small-context models, this manages
    conversation history by keeping the most recent turns and summarizing older ones.
    """
    
    def __init__(
        self,
        max_tokens: int = 128,
        keep_last_messages: int = 6,
        summary_model: str = "auto",
        summary_prompt: str = "Summarize the following conversation briefly, preserving key facts and decisions:"
    ):
        self.max_tokens = max_tokens
        self.keep_last_messages = keep_last_messages
        self.summary_model = summary_model
        self.summary_prompt = summary_prompt
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token)."""
        return max(1, len(text) // 4)
    
    def count_messages_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.estimate_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("text"):
                        total += self.estimate_tokens(part["text"])
        return total
    
    def compress(self, messages: list[dict]) -> list[dict]:
        """Compress message history to fit within max_tokens."""
        if not messages:
            return messages
        
        total_tokens = self.count_messages_tokens(messages)
        if total_tokens <= self.max_tokens:
            return messages
        
        # Keep system message if present
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        
        # Keep the last N messages
        kept = other_msgs[-self.keep_last_messages:]
        dropped = other_msgs[:-self.keep_last_messages] if len(other_msgs) > self.keep_last_messages else []
        
        if not dropped:
            return system_msgs + kept
        
        # Summarize dropped messages
        summary_text = self._summarize(dropped)
        if summary_text:
            summary_msg = {
                "role": "system",
                "content": f"Previous conversation summary: {summary_text}"
            }
            return system_msgs + [summary_msg] + kept
        else:
            return system_msgs + kept
    
    def _summarize(self, messages: list[dict]) -> str:
        """Generate a summary of old messages (placeholder - would call LLM)."""
        # In production, this would call a small summarization model
        # For now, return a simple factual summary
        facts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 20:
                # Extract first sentence as fact
                first_sent = content.split(".")[0]
                if len(first_sent) > 10:
                    facts.append(f"{role}: {first_sent}")
        if facts:
            return "; ".join(facts[:5]) + "."
        return "Previous discussion covered multiple topics."


def apply_thinker_lite(
    user_content: str,
    llm_content: str,
    *,
    candidates: int = 1,
    thinker: str = "auto",
) -> tuple[str, dict[str, Any]]:
    """Convenience function: analyze → validate → repair → decorate.

    Args:
        thinker: "auto" | "math" | "code" | "fact" | "general"
                 Selects specialized thinker. "auto" routes by intent.
    """
    if thinker == "math" or (thinker == "auto" and _is_math_intent(user_content)):
        layer = MathThinker()
    elif thinker == "code" or (thinker == "auto" and _is_code_intent(user_content)):
        layer = CodeThinker()
    elif thinker == "fact" or (thinker == "auto" and _is_fact_intent(user_content)):
        layer = FactThinker()
    else:
        layer = ThinkerLite()

    analysis = layer.analyze(user_content)
    if analysis.math_result:
        return analysis.math_result, layer.trace(analysis, valid=True, notes=["deterministic_math"],
                                                 repaired=False, candidates=0)
    valid, notes = layer.validate(llm_content, analysis)
    repaired = not valid
    if repaired:
        llm_content = layer.repair(analysis, llm_content)
    llm_content = layer.decorate(llm_content, analysis)
    metadata = layer.trace(analysis, valid=valid, notes=notes,
                           repaired=repaired, candidates=candidates)
    return llm_content, metadata


def _is_math_intent(text: str) -> bool:
    low = text.lower()
    return math_answer(text) is not None or re.search(r"\b(what is|calculate|cuanto es)\b", low)


def _is_code_intent(text: str) -> bool:
    low = text.lower()
    return bool(re.search(r"\b(code|python|function|bug|implement|script|api|sql)\b", low))


def _is_fact_intent(text: str) -> bool:
    low = text.lower()
    return bool(re.search(r"\b(what is|who is|when|where|how many|capital|define|explain)\b", low))


class MathThinker(ThinkerLite):
    """Specialized for deterministic arithmetic and math reasoning."""

    def analyze(self, text: str) -> Analysis:
        math = math_answer(text)
        if math is not None:
            return Analysis(text, "math", "high", "deterministic_math_guard", math_result=math)
        # Fallback to base for non-arithmetic math questions
        return super().analyze(text)

    def validate(self, reply: str, analysis: Analysis) -> tuple[bool, list[str]]:
        notes: list[str] = []
        if analysis.intent == "math" and analysis.math_result:
            if analysis.math_result not in reply:
                notes.append("math answer does not match deterministic result")
                return False, notes
        return True, notes

    def repair(self, analysis: Analysis, reply: str) -> str:
        if analysis.intent == "math" and analysis.math_result:
            return analysis.math_result
        return super().repair(analysis, reply)


class CodeThinker(ThinkerLite):
    """Specialized for code generation: validation, style, safety."""

    # Patterns that indicate common code issues
    BARE_EXCEPT = re.compile(r"except\s*:")
    SQL_INJECTION = re.compile(r"execute\s*\(\s*f[\"']", re.I)
    HARDCODED_SECRETS = re.compile(r"(api_key|password|secret|token)\s*=\s*[\"'][^\"']+[\"']", re.I)

    def analyze(self, text: str) -> Analysis:
        base = super().analyze(text)
        if base.intent == "code":
            base.notes.append("code_generation_requested")
            base.strategy = "code_with_validation"
        return base

    def validate(self, reply: str, analysis: Analysis) -> tuple[bool, list[str]]:
        valid, notes = super().validate(reply, analysis)
        if analysis.intent != "code":
            return valid, notes

        text = reply
        issues: list[str] = []

        if self.BARE_EXCEPT.search(text):
            issues.append("bare_except_catches_all")
        if self.SQL_INJECTION.search(text):
            issues.append("potential_sql_injection_fstring")
        if self.HARDCODED_SECRETS.search(text):
            issues.append("hardcoded_secret_detected")
        if "eval(" in text or "exec(" in text:
            issues.append("dangerous_eval_exec")
        if "subprocess" in text and "shell=True" in text:
            issues.append("subprocess_shell_true_risk")

        if issues:
            notes.extend(issues)
            return False, notes
        return valid, notes

    def repair(self, analysis: Analysis, reply: str) -> str:
        if analysis.intent == "code":
            return ("i cannot reliably generate production-ready code; "
                    "please review for security, style, and correctness. "
                    "consider using a dedicated code model or IDE.")
        return super().repair(analysis, reply)

    def decorate(self, reply: str, analysis: Analysis) -> str:
        if analysis.intent == "code" and reply:
            return f"# ⚠️ Code not verified\n{reply}"
        return super().decorate(reply, analysis)


class FactThinker(ThinkerLite):
    """Specialized for factual QA: uncertainty, citations, hallucination guards."""

    UNCERTAINTY_PHRASES = (
        "i'm not sure", "i don't know", "uncertain", "may be", "possibly",
        "according to", "sources indicate", "as of", "knowledge cutoff",
    )
    HALLUCINATION_PATTERNS = (
        r"\b\d{4}\b",  # specific years (often hallucinated)
        r"\b\d+\.\d+%\b",  # precise percentages
        r"according to (?:a|the) (?:study|report|paper)",  # fake citations
    )

    def analyze(self, text: str) -> Analysis:
        base = super().analyze(text)
        if base.intent == "factual":
            base.notes.append("factual_query_uncertainty_high")
            base.strategy = "answer_with_uncertainty"
        return base

    def validate(self, reply: str, analysis: Analysis) -> tuple[bool, list[str]]:
        valid, notes = super().validate(reply, analysis)
        if analysis.intent != "factual":
            return valid, notes

        text = reply.lower()
        issues: list[str] = []

        # Check for uncertainty markers (good)
        has_uncertainty = any(p in text for p in self.UNCERTAINTY_PHRASES)

        # Check for hallucination patterns (bad)
        for pattern in self.HALLUCINATION_PATTERNS:
            if re.search(pattern, text):
                issues.append(f"hallucination_pattern:{pattern}")

        # Overconfident factual claims without uncertainty
        if not has_uncertainty and len(text) > 50:
            notes.append("factual_confidence_low_no_uncertainty_marker")
            valid = False

        if issues:
            notes.extend(issues)
            return False, notes
        return valid, notes

    def repair(self, analysis: Analysis, reply: str) -> str:
        if analysis.intent == "factual":
            return ("i'm not certain about that specific detail. "
                    "please verify from a trusted primary source. "
                    "my knowledge may be outdated or incomplete.")
        return super().repair(analysis, reply)

    def decorate(self, reply: str, analysis: Analysis) -> str:
        if analysis.intent == "factual" and reply:
            if not any(p in reply.lower() for p in self.UNCERTAINTY_PHRASES):
                return f"i'm not certain, but {reply}"
        return super().decorate(reply, analysis)


def get_thinker(intent: str) -> ThinkerLite:
    """Factory for intent-specific thinker."""
    if intent == "math":
        return MathThinker()
    if intent == "code":
        return CodeThinker()
    if intent == "factual":
        return FactThinker()
    return ThinkerLite()