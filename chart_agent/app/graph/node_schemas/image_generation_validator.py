from pydantic import BaseModel, Field


class CriterionResult(BaseModel):
    evidence: str = Field(default="")
    reason: str = Field(default="")
    passed: bool = Field(default=False)


class FactItem(BaseModel):
    id: str
    fact: str
    importance: str  # "major" | "minor"


class FactCheck(BaseModel):
    id: str
    fact: str
    importance: str
    status: str  # "preserved" | "not_preserved" | "uncertain"
    reason: str


class PreservationResult(BaseModel):
    fact_checks: list[FactCheck] = Field(default_factory=list)
    P1_element_count_and_presence: CriterionResult = Field(default_factory=CriterionResult)
    P2_spatial_layout_preservation: CriterionResult = Field(default_factory=CriterionResult)
    P3_scale_proportion_and_quantitative_relations: CriterionResult = Field(default_factory=CriterionResult)
    P4_visual_encoding_and_series_identity: CriterionResult = Field(default_factory=CriterionResult)
    P5_no_extra_artifacts_or_corruption: CriterionResult = Field(default_factory=CriterionResult)


class AdherenceResult(BaseModel):
    E1_requested_edit_visible: CriterionResult = Field(default_factory=CriterionResult)
    E2_correct_target_elements: CriterionResult = Field(default_factory=CriterionResult)
    E3_edit_completeness: CriterionResult = Field(default_factory=CriterionResult)
    E4_edit_specificity_no_unrequested_edit: CriterionResult = Field(default_factory=CriterionResult)
    E5_visual_integration_and_cleanliness: CriterionResult = Field(default_factory=CriterionResult)


PRESERVATION_CRITERIA = [
    "P1_element_count_and_presence",
    "P2_spatial_layout_preservation",
    "P3_scale_proportion_and_quantitative_relations",
    "P4_visual_encoding_and_series_identity",
    "P5_no_extra_artifacts_or_corruption",
]

ADHERENCE_CRITERIA = [
    "E1_requested_edit_visible",
    "E2_correct_target_elements",
    "E3_edit_completeness",
    "E4_edit_specificity_no_unrequested_edit",
    "E5_visual_integration_and_cleanliness",
]


class ImageGenerationValidationResult(BaseModel):
    preservation: PreservationResult = Field(default_factory=PreservationResult)
    adherence: AdherenceResult = Field(default_factory=AdherenceResult)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    errors_summary: str = Field(default="")
    key_issues: list[str] = Field(default_factory=list)
