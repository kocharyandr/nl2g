from fastapi.testclient import TestClient

from app.api import routes_sessions
from app.infra.llm.client import LLMServiceUnavailableError


def test_create_session(client: TestClient) -> None:
    response = client.post("/sessions")
    assert response.status_code == 200

    payload = response.json()
    assert payload["current_stage"] == "ingress"
    assert isinstance(payload["session_id"], str)
    assert payload["artefacts"]["plot"]["image_base64"] is None


def test_message_builds_chart_and_waits_for_approval(client: TestClient) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"type": "message", "content": "Построй график A=10 B=20 C=15"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "plot_rendering"
    assert "Подтвердите" in payload["assistant_message"]
    assert payload["artefacts"]["plot"]["code"]
    assert payload["artefacts"]["plot"]["chart_attempt"] == 1
    assert payload["artefacts"]["plot"]["image_base64"]
    assert payload["artefacts"]["data"]["user_intent"]["intent_type"] == "build_chart"
    assert (
        payload["artefacts"]["data"]["understanding"]["chart_intent"]["recommended_chart_type"]
        == "bar"
    )
    assert payload["artefacts"]["plot"]["evaluation"]["status"] == "base_chart_rendered"


def test_decision_approve_marks_plot_as_approved(client: TestClient) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    client.post(
        f"/sessions/{session_id}/messages",
        json={"type": "message", "content": "Построй график A=10 B=20 C=15"},
    )
    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"type": "decision", "value": "approve"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "plot_approval"
    assert payload["artefacts"]["plot"]["approved"] is True
    assert payload["assistant_message"] == "График подтвержден."


def test_image_generation_flow_returns_image_artefact(client: TestClient, sample_png_base64: str) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={
            "type": "message",
            "content": "Улучши это изображение графика",
            "images_base64": [sample_png_base64],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "image_generation"

    image = payload["artefacts"]["image"]
    assert image["image_base64"]
    # Цикл всегда отрабатывает весь бюджет итераций и оставляет лучший вариант.
    assert len(image["iterations"]) == 2
    assert image["best_score"] == 1.0
    assert image["need_next_iteration"] is False
    assert image["last_accepted_image_base64"] == image["image_base64"]


def test_csv_histogram_builds_chart_without_clarification(
    client: TestClient,
    sample_csv_data: str,
) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={
            "type": "message",
            "content": "Построй гистограмму по столбцу cost",
            "csv_data": sample_csv_data,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "plot_rendering"
    assert (
        payload["artefacts"]["data"]["understanding"]["chart_intent"]["recommended_chart_type"]
        == "histogram"
    )
    assert payload["artefacts"]["data"]["validation"]["is_valid"] is True
    points = payload["artefacts"]["data"]["understanding"]["dataset_spec"]["points"]
    assert len(points) == 6
    assert points[0]["y"] == 3600.0


def test_csv_bar_chart_uses_aggregation(
    client: TestClient,
    sample_csv_data: str,
) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={
            "type": "message",
            "content": "Построй столбчатый график revenue по region",
            "csv_data": sample_csv_data,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "plot_rendering"

    understanding = payload["artefacts"]["data"]["understanding"]
    assert understanding["chart_intent"]["recommended_chart_type"] == "bar"

    points = understanding["dataset_spec"]["points"]
    values_by_region = {point["label"]: point["y"] for point in points}
    assert sorted(values_by_region) == ["East", "North", "South", "West"]
    # North встречается в трех строках: агрегация суммой должна их сложить.
    assert values_by_region["North"] == 7650.0


def test_rollback_to_ingress_clears_chart_fields(client: TestClient) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    client.post(
        f"/sessions/{session_id}/messages",
        json={"type": "message", "content": "Построй график A=10 B=20 C=15"},
    )

    rollback_response = client.post(
        f"/sessions/{session_id}/rollback",
        json={"target_stage": "ingress"},
    )

    assert rollback_response.status_code == 200
    payload = rollback_response.json()
    assert payload["current_stage"] == "ingress"
    assert payload["artefacts"]["plot"]["code"] == ""
    assert payload["artefacts"]["plot"]["chart_attempt"] == 0
    assert payload["artefacts"]["plot"]["image_base64"] is None
    assert payload["artefacts"]["data"]["understanding"]["dataset_spec"]["points"] == []


def test_unsupported_rollback_stage_returns_400(client: TestClient) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/rollback",
        json={"target_stage": "plot_approval"},
    )

    assert response.status_code == 400


def test_message_returns_503_when_llm_unavailable(client: TestClient, monkeypatch) -> None:
    session_id = client.post("/sessions").json()["session_id"]

    async def interaction_run(*, user_input: str, context: dict | None = None):
        _ = user_input, context
        raise LLMServiceUnavailableError("LLM request failed: connection error")

    monkeypatch.setattr(routes_sessions.registry.interaction, "run", interaction_run)

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"type": "message", "content": "Построй график A=10 B=20 C=15"},
    )

    assert response.status_code == 503
    assert "LLM request failed" in response.json()["detail"]
