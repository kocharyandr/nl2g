def normalize_data(payload: dict | None) -> dict:
    if not payload:
        raise ValueError("Data payload is empty")

    labels = payload.get("labels")
    values = payload.get("values")
    chart_type = payload.get("chart_type")

    if not isinstance(values, list) or not values:
        raise ValueError("values must be a non-empty list")
    if not isinstance(chart_type, str) or not chart_type.strip():
        raise ValueError("chart_type is required")

    try:
        normalized_values = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("values must be numeric") from exc

    if labels is None:
        normalized_labels = [str(i + 1) for i in range(len(normalized_values))]
    elif isinstance(labels, list) and labels:
        if len(labels) != len(normalized_values):
            raise ValueError("labels and values must have the same length")
        normalized_labels = [str(item) for item in labels]
    else:
        raise ValueError("labels must be a list when provided")

    return {
        "labels": normalized_labels,
        "values": normalized_values,
        "chart_type": chart_type.strip().lower(),
    }
