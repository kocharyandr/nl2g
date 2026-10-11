from app.domain import StageName
from app.api.schemas import Artefacts


SUPPORTED_ROLLBACK_STAGES = {
    StageName.ingress,
    StageName.data_parsing,
    StageName.sql_query,
    StageName.plot_rendering,
    StageName.chart_review,
}


def invalidate(state, target_stage: StageName):
    _ = state

    if target_stage not in SUPPORTED_ROLLBACK_STAGES:
        supported = sorted(stage.value for stage in SUPPORTED_ROLLBACK_STAGES)
        raise ValueError(
            f"Rollback to '{target_stage}' is not supported. Supported: {supported}"
        )

    patch: dict[str, object] = {
        "current_stage": target_stage,
        "next_stage": None,
        "assistant_message": f"Rollback выполнен до стадии '{target_stage.value}'.",
    }

    if target_stage == StageName.ingress:
        patch["artefacts"] = Artefacts()
        patch["chart_attempt"] = 0
        patch["chart_last_sent_attempt"] = 0
        patch["awaiting_user_approval"] = False
        patch["persisted_csv"] = None
        # SQL artefacts are downstream state too: a rollback to ingress must
        # not leave a stale table behind for the next question to inherit.
        patch["sql_result_table"] = None
        patch["persisted_sql_result"] = None
        patch["sql_query_text"] = None
        patch["sql_explanation"] = None
        patch["sql_truncated"] = False
        patch["use_sql_source"] = False
        patch["errors"] = []
    elif target_stage == StageName.data_parsing:
        patch["awaiting_user_approval"] = False
        # Keep persisted_sql_result: re-running data parsing should re-use the
        # fetched rows rather than query the database again.
        patch["sql_result_table"] = None
    elif target_stage == StageName.plot_rendering:
        patch["awaiting_user_approval"] = True
    elif target_stage == StageName.sql_query:
        patch["awaiting_user_approval"] = False
        patch["sql_result_table"] = None
        patch["persisted_sql_result"] = None
    elif target_stage == StageName.chart_review:
        patch["awaiting_user_approval"] = False

    return patch
