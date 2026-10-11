from enum import Enum


class StageName(str, Enum):
    ingress = "ingress"
    data_parsing = "data_parsing"
    sql_query = "sql_query"
    image_generation = "image_generation"
    plot_rendering = "plot_rendering"
    plot_approval = "plot_approval"
    chart_review = "chart_review"
    chat = "chat"
    error = "error"
