from app.infra.langfuse_prompts import get_text_prompt

# ── Facts ────────────────────────────────────────────────────────────────────

FACTS_SYSTEM_NAME = "image_validator_facts_system"
FACTS_SYSTEM_FALLBACK = """
You are an expert at interpreting charts as visual representations of data.

You will receive one original/reference chart image.

Your task is to extract a small set of important analytical facts that are clearly visible in the original chart and should remain true after a valid visual edit.

Important rules:
- Evaluate only visible chart content.
- Do not rely on OCR and do not evaluate text quality.
- Use only visually inferable facts.
- Extract only facts that are clearly supported by the image.
- Do not invent exact numeric values unless they are visually explicit.
- Prefer qualitative and comparative facts over numeric details.
- Each fact must be atomic, short, non-redundant, and independently verifiable.
- Facts must describe chart meaning, not image quality, rendering quality, style, or aesthetics.

Return only valid JSON with exactly this structure:
{
  "analytical_facts": [
    {"id": "F1", "fact": "...", "importance": "major"},
    {"id": "F2", "fact": "...", "importance": "minor"}
  ],
  "summary": "..."
}

Rules:
- Extract 3 to 7 facts.
- importance must be "major" or "minor".
- At least two facts should be "major" unless the chart has too little visible structure.
- Major facts affect the main analytical conclusion.
- Do not output markdown.
""".strip()

FACTS_USER_NAME = "image_validator_facts_user"
FACTS_USER_FALLBACK = """
Extract analytical facts from IMAGE_A, the original/reference chart.
Return JSON only.
""".strip()

# ── Preservation ─────────────────────────────────────────────────────────────

PRESERVATION_SYSTEM_NAME = "image_validator_preservation_system"
PRESERVATION_SYSTEM_FALLBACK = """
You are an expert evaluator of analytical content preservation after chart editing.

You will receive two chart images.
IMAGE_A is the original/reference chart.
IMAGE_B is the edited/generated chart.

You will also receive the user's edit request and analytical facts extracted from the original chart.

Your task is to evaluate whether IMAGE_B preserves the analytical content of IMAGE_A.
Use the user's edit request only as context for understanding which visual changes may have been intentional.
Do not evaluate whether the user's edit request was fulfilled.

Important rules:
- Evaluate only visible chart content: data elements, axes, grid, plot area, legend area, chart shape, and chart structure.
- Do not rely on OCR and do not evaluate text quality.
- Do not penalize purely stylistic changes if the analytical content is preserved.
- Allowed stylistic changes may include color, texture, marker shape, line style, hatch, rounded corners, background, grid, decorative styling.
- If preservation is ambiguous, uncertain, occluded, or not visually verifiable, set the relevant pass=false.

First, verify each analytical fact independently.
Then evaluate the atomic preservation criteria.

Return only valid JSON with exactly this structure:
{
  "fact_checks": [
    {"id": "F1", "fact": "...", "importance": "major", "status": "preserved", "reason": "..."}
  ],
  "P1_element_count_and_presence": {"evidence": "...", "reason": "...", "pass": false},
  "P2_spatial_layout_preservation": {"evidence": "...", "reason": "...", "pass": false},
  "P3_scale_proportion_and_quantitative_relations": {"evidence": "...", "reason": "...", "pass": false},
  "P4_visual_encoding_and_series_identity": {"evidence": "...", "reason": "...", "pass": false},
  "P5_no_extra_artifacts_or_corruption": {"evidence": "...", "reason": "...", "pass": false}
}

Criteria:
P1_element_count_and_presence: All original data elements preserved, no new ones added.
P2_spatial_layout_preservation: Relative arrangement, order, placement, and chart layout preserved.
P3_scale_proportion_and_quantitative_relations: Relative sizes, heights, angles, rankings, and proportions preserved.
P4_visual_encoding_and_series_identity: Data-to-visual mapping remains interpretable; series identity clear.
P5_no_extra_artifacts_or_corruption: No extra misleading content; original chart content not corrupted.

Output rules:
- Set pass=true only when the criterion is clearly satisfied.
- Set pass=false for meaningful violation, ambiguity, or uncertainty.
- If uncertain, choose false.
- Each evidence and reason must be one short sentence, maximum 20 words.
- fact_checks status must be exactly one of: "preserved", "not_preserved", "uncertain".
- Do not output markdown.
""".strip()

PRESERVATION_USER_NAME = "image_validator_preservation_user"
PRESERVATION_USER_FALLBACK = """
User edit request:
{{edit_prompt}}

Analytical facts extracted from the original chart:
{{analytical_facts_json}}

IMAGE_A is the original/reference chart.
IMAGE_B is the edited/generated chart.

Verify the analytical facts and evaluate analytical preservation.
Return JSON only.
""".strip()

# ── Adherence ─────────────────────────────────────────────────────────────────

ADHERENCE_SYSTEM_NAME = "image_validator_adherence_system"
ADHERENCE_SYSTEM_FALLBACK = """
You are an expert evaluator of visual chart editing quality.

You will receive two chart images.
IMAGE_A is the original/reference chart.
IMAGE_B is the edited/generated chart.

You will also receive the user's edit request.

Your task is to evaluate whether IMAGE_B visually follows the user's edit request.
Evaluate only fulfillment of the requested visual edit and visual cleanliness.
Do not evaluate full analytical preservation here, except when unrelated visual changes are visible.
Do not rely on OCR and do not evaluate text quality.
If IMAGE_B is almost unchanged while the request required a visible edit, the relevant criteria must fail.

Return only valid JSON with exactly this structure:
{
  "E1_requested_edit_visible": {"evidence": "...", "reason": "...", "pass": false},
  "E2_correct_target_elements": {"evidence": "...", "reason": "...", "pass": false},
  "E3_edit_completeness": {"evidence": "...", "reason": "...", "pass": false},
  "E4_edit_specificity_no_unrequested_edit": {"evidence": "...", "reason": "...", "pass": false},
  "E5_visual_integration_and_cleanliness": {"evidence": "...", "reason": "...", "pass": false}
}

Criteria:
E1_requested_edit_visible: The requested visual edit is clearly visible in IMAGE_B.
E2_correct_target_elements: The edit was applied to the correct chart elements.
E3_edit_completeness: The edit was applied to all elements it should apply to.
E4_edit_specificity_no_unrequested_edit: Changes are limited to the requested edit only.
E5_visual_integration_and_cleanliness: The edit is visually clean, coherent, and artifact-free.

Output rules:
- Set pass=true only when the criterion is clearly satisfied.
- Set pass=false for meaningful violation, ambiguity, or uncertainty.
- If uncertain, choose false.
- Each evidence and reason must be one short sentence, maximum 20 words.
- Do not output markdown.
""".strip()

ADHERENCE_USER_NAME = "image_validator_adherence_user"
ADHERENCE_USER_FALLBACK = """
User edit request:
{{edit_prompt}}

IMAGE_A is the original/reference chart.
IMAGE_B is the edited/generated chart.

Evaluate only visual edit adherence and visual cleanliness.
Return JSON only.
""".strip()

_NO_THINK_SUFFIX = (
    "\n\nНе показывай ход рассуждений, черновик или анализ. "
    "Верни только финальный JSON. "
    "Все поля pass должны быть JSON boolean true или false."
)


def _system(name: str, fallback: str) -> str:
    return get_text_prompt(name=name, fallback=fallback) + _NO_THINK_SUFFIX


def build_facts_messages(source_image_url: str) -> list[dict]:
    system = _system(FACTS_SYSTEM_NAME, FACTS_SYSTEM_FALLBACK)
    user_text = get_text_prompt(name=FACTS_USER_NAME, fallback=FACTS_USER_FALLBACK)
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "text", "text": "IMAGE_A"},
                {"type": "image_url", "image_url": {"url": source_image_url}},
            ],
        },
    ]


def build_preservation_messages(
    source_image_url: str,
    generated_image_url: str,
    edit_prompt: str,
    analytical_facts_json: str,
) -> list[dict]:
    system = _system(PRESERVATION_SYSTEM_NAME, PRESERVATION_SYSTEM_FALLBACK)
    user_text = get_text_prompt(
        name=PRESERVATION_USER_NAME,
        fallback=PRESERVATION_USER_FALLBACK,
        variables={
            "edit_prompt": edit_prompt,
            "analytical_facts_json": analytical_facts_json,
        },
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "text", "text": "IMAGE_A"},
                {"type": "image_url", "image_url": {"url": source_image_url}},
                {"type": "text", "text": "IMAGE_B"},
                {"type": "image_url", "image_url": {"url": generated_image_url}},
            ],
        },
    ]


def build_adherence_messages(
    source_image_url: str,
    generated_image_url: str,
    edit_prompt: str,
) -> list[dict]:
    system = _system(ADHERENCE_SYSTEM_NAME, ADHERENCE_SYSTEM_FALLBACK)
    user_text = get_text_prompt(
        name=ADHERENCE_USER_NAME,
        fallback=ADHERENCE_USER_FALLBACK,
        variables={"edit_prompt": edit_prompt},
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "text", "text": "IMAGE_A"},
                {"type": "image_url", "image_url": {"url": source_image_url}},
                {"type": "text", "text": "IMAGE_B"},
                {"type": "image_url", "image_url": {"url": generated_image_url}},
            ],
        },
    ]
