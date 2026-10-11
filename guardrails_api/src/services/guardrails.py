import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from gliner2 import GLiNER2

from core.config import settings
from core.logger import logger
from src.schemas.guardrails import RejectType, Status

SAFETY_LABELS = {
    "safe": "ordinary request about data visualization, chart building, diagrams, or data analysis",
    "unsafe": "request with clearly harmful, threatening, or inappropriate content unrelated to chart building",
}
ADVERSARIAL_LABELS = {
    "none": "ordinary request about data or visualization without any manipulation attempt",
    "instruction_override": "explicit attempt to override system instructions or ignore service rules",
    "jailbreak_persona": "request to pretend to be a different system or an unrestricted persona",
    "jailbreak_hypothetical": "hypothetical scenario used to bypass service restrictions",
    "data_exfiltration": "attempt to extract system prompts, configuration, or internal data",
    "jailbreak_roleplay": "roleplay used as a cover to circumvent restrictions",
}
HARMFUL_LABELS = {
    "none": "standard request about building a chart, analyzing data, or visualization",
    "dangerous_instructions": "instructions for real-world physical harm or illegal activities",
    "harassment": "personal insults or targeted harassment of a specific person",
    "sexual_content": "explicit sexual content",
    "violence": "real threats of violence or glorification of violence against people",
    "hate_speech": "content promoting hatred based on race, gender, or religion",
    "fraud": "instructions for financial fraud or deception",
    "pii_exposure": "attempt to expose personal data or private information of others",
    "discrimination": "content promoting discrimination based on protected characteristics",
    "misinformation": "deliberate spread of knowingly false information",
    "weapons": "instructions for creating or using weapons",
}
INTENT_LABELS = {
    "informational": "user asks a question about data, charts, or service features",
    "conversational": "ordinary conversational exchange or greeting",
    "instructional": "user requests to build, modify, or analyze a chart",
    "adversarial": "user attempts to manipulate the service or bypass its restrictions",
    "creative": "creative or unconventional request about data",
    "threatening": "threats or hostile demands",
}
TOV_LABELS = {
    "neutral": "neutral, professional, or informational tone",
    "aggressive": "hostile, insulting, or threatening tone directed at a person",
    "manipulative": "attempt to manipulate or deceive through intentionally misleading framing",
    "formal": "polite, official, and professional language",
    "distressed": "signal of emotional distress or an acute personal crisis",
}
POLICY_LABELS = {
    "weather": "questions about weather forecasts, temperature, precipitation",
    "date_time": "questions about current date, time, or calendar",
    "small_talk": "casual greetings, jokes, or idle conversation unrelated to service",
    "personal_advice": "personal life advice, relationships, or emotional support",
    "entertainment": "questions about movies, music, sports, games, or celebrities",
    "politics_news": "political topics, news events, elections, or government",
}

TONE_REJECT_LABELS = {"aggressive", "manipulative"}


class GuardRailsService:
    def __init__(self) -> None:
        logger.info(f"Loading {settings.MODEL_NAME} on {settings.DEVICE}...")
        self._model = GLiNER2.from_pretrained(settings.MODEL_NAME).to(settings.DEVICE)
        self._schema = self._build_schema()
        logger.info("GuardRailsService ready.")

    def _build_schema(self) -> object:
        schema = self._model.create_schema()
        schema = schema.classification(
            task="safety", labels=SAFETY_LABELS, multi_label=False
        )
        schema = schema.classification(
            task="adversarial", labels=ADVERSARIAL_LABELS, multi_label=True
        )
        schema = schema.classification(
            task="harmful", labels=HARMFUL_LABELS, multi_label=True
        )
        schema = schema.classification(task="intent", labels=INTENT_LABELS)
        schema = schema.classification(task="tone", labels=TOV_LABELS)
        return schema.classification(
            task="policy", labels=POLICY_LABELS, multi_label=True
        )

    def _infer(self, text: str) -> dict:
        return self._model.extract(
            text=text, schema=self._schema, include_confidence=True
        )

    async def classify(self, text: str) -> dict:
        raw = await asyncio.to_thread(self._infer, text)
        verdict = self._evaluate(raw)
        return {**raw, **verdict}

    # --- Custom classification with arbitrary labels (zero-shot routing) ---

    def _infer_custom(
        self,
        text: str,
        task: str,
        labels: list[str] | dict[str, str],
        multi_label: bool,
    ) -> dict:
        schema = self._model.create_schema().classification(
            task=task, labels=labels, multi_label=multi_label
        )
        return self._model.extract(text=text, schema=schema, include_confidence=True)

    async def classify_custom(
        self,
        text: str,
        task: str,
        labels: list[str],
        label_descriptions: dict[str, str] | None = None,
        multi_label: bool = False,
    ) -> dict:
        # If descriptions provided, pass {label: description} to improve zero-shot quality
        # (especially helpful for Russian / domain-specific routing tasks).
        labels_arg: list[str] | dict[str, str]
        if label_descriptions:
            labels_arg = {lbl: label_descriptions.get(lbl, lbl) for lbl in labels}
        else:
            labels_arg = labels

        raw = await asyncio.to_thread(
            self._infer_custom, text, task, labels_arg, multi_label
        )

        result = raw.get(task) or {}
        all_scores: dict[str, float] = {}
        top_label: str | None = None
        top_conf: float = 0.0
        labels_list: list[str] = []

        if multi_label:
            for item in result if isinstance(result, list) else []:
                lbl = item.get("label")
                conf = float(item.get("confidence", 0.0))
                if lbl:
                    all_scores[lbl] = conf
                    labels_list.append(lbl)
                    if conf > top_conf:
                        top_label = lbl
                        top_conf = conf
        else:
            if isinstance(result, dict):
                top_label = result.get("label")
                top_conf = float(result.get("confidence", 0.0))
                if top_label:
                    all_scores[top_label] = top_conf

        return {
            "task": task,
            "label": top_label,
            "labels": labels_list,
            "confidence": top_conf,
            "all_scores": all_scores,
            "raw": raw,
        }

    @staticmethod
    def _evaluate(result: dict) -> dict:
        reject = GuardRailsService._pick_reject(result)
        if reject is None:
            return {"status": Status.OK, "type_reject": None, "message": None}
        return {
            "status": Status.REJECT,
            "type_reject": reject,
            "message": _MESSAGES[reject],
        }

    @staticmethod
    def _pick_reject(result: dict) -> RejectType | None:
        candidates = [
            (rule.reject_type, score)
            for rule in _REJECT_RULES
            if (score := rule.score(result)) is not None
        ]
        if candidates:
            return max(candidates, key=lambda item: item[1])[0]
        if (score := _SAFETY_RULE.score(result)) is not None:
            return _SAFETY_RULE.reject_type
        return None


_MESSAGES: dict[RejectType, str] = {
    RejectType.SAFETY: settings.MSG_REJECT_SAFETY,
    RejectType.ADVERSARIAL: settings.MSG_REJECT_ADVERSARIAL,
    RejectType.HARMFUL: settings.MSG_REJECT_HARMFUL,
    RejectType.INTENT: settings.MSG_REJECT_INTENT,
    RejectType.TONE: settings.MSG_REJECT_TONE,
    RejectType.POLICY: settings.MSG_REJECT_POLICY,
}


def _conf(obj: dict) -> float:
    return float(obj.get("confidence", 0.0))


def _single_score(
    key: str, labels: set[str], threshold: float
) -> Callable[[dict], float | None]:
    def score(result: dict) -> float | None:
        obj = result.get(key) or {}
        if obj.get("label") not in labels:
            return None
        conf = _conf(obj)
        return conf if conf >= threshold else None

    return score


def _multi_score(
    key: str, threshold: float, exclude_none: bool
) -> Callable[[dict], float | None]:
    def score(result: dict) -> float | None:
        best: float | None = None
        for item in result.get(key) or []:
            label = item.get("label")
            if not label or (exclude_none and label == "none"):
                continue
            conf = _conf(item)
            if conf >= threshold and (best is None or conf > best):
                best = conf
        return best

    return score


@dataclass(frozen=True)
class _Rule:
    reject_type: RejectType
    score: Callable[[dict], float | None]


_SAFETY_RULE = _Rule(
    RejectType.SAFETY,
    _single_score("safety", {"unsafe"}, settings.THRESHOLD_SAFETY),
)

_REJECT_RULES: tuple[_Rule, ...] = (
    _Rule(
        RejectType.ADVERSARIAL,
        _multi_score("adversarial", settings.THRESHOLD_ADVERSARIAL, exclude_none=True),
    ),
    _Rule(
        RejectType.HARMFUL,
        _multi_score("harmful", settings.THRESHOLD_HARMFUL, exclude_none=True),
    ),
    _Rule(
        RejectType.INTENT,
        _single_score("intent", {"adversarial"}, settings.THRESHOLD_INTENT),
    ),
    _Rule(
        RejectType.TONE,
        _single_score("tone", TONE_REJECT_LABELS, settings.THRESHOLD_TONE),
    ),
    _Rule(
        RejectType.POLICY,
        _multi_score("policy", settings.THRESHOLD_POLICY, exclude_none=False),
    ),
)
