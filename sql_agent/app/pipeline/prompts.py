"""Prompts for the three pipeline roles.

Kept verbatim from the evaluated NL2SQL configuration wherever possible: the
LoRA adapters were trained against these instruction shapes, so drifting the
wording silently costs accuracy.
"""

SCHEMA_SYSTEM = (
    "You are a database architect. Identify exactly which tables are needed to "
    "answer the question. Return ONLY the table names as a comma-separated list."
)

SCHEMA_SYSTEM_WITH_CLARIFICATION = (
    "You are a database architect. Identify exactly which tables are needed to "
    "answer the question. Return ONLY the table names as a comma-separated list. "
    "If the question is genuinely ambiguous and cannot be answered from this "
    "database without more information, reply with exactly "
    "'NEED_CLARIFICATION: <question to ask the user>' instead."
)

SQL_SYSTEM = (
    "You are an expert SQL developer. First think step-by-step in <thinking> tags. "
    "Then write the exact SQLite query inside ```sql ``` block."
)

CRITIC_SYSTEM = (
    "You are a senior SQL reviewer. Fix syntax errors and logical flaws based on "
    "the SQLite execution feedback. Return ONLY the corrected SQL inside ```sql ``` block."
)

EXPLANATION_SYSTEM = (
    "You explain SQL queries to non-technical analysts. Given a question and the "
    "SQL that answers it, reply with ONE short sentence in Russian describing what "
    "the query returns. No SQL, no preamble, no markdown."
)


def build_schema_prompt(schema_text: str, profile_block: str, question: str) -> str:
    if profile_block:
        return (
            f"Schema:\n{schema_text}\n\n"
            f"Profile:\n{profile_block}\n\n"
            f"Question: '{question}'\nNeeded tables:"
        )
    return f"Schema:\n{schema_text}\n\nQuestion: '{question}'\nNeeded tables:"


def build_sql_prompt(schema_text: str, profile_block: str, question: str) -> str:
    if profile_block:
        return (
            f"Schema:\n{schema_text}\n\n"
            f"Profile:\n{profile_block}\n\n"
            f"Question: '{question}'. Return your thinking and the valid SQL."
        )
    return (
        f"Schema:\n{schema_text}\n\n"
        f"Question: '{question}'. Return your thinking and the valid SQL."
    )


def build_critic_prompt(schema_text: str, question: str, current_sql: str, feedback: str) -> str:
    return (
        f"Schema:\n{schema_text}\n"
        f"Question: '{question}'\n"
        f"Generated SQL: {current_sql}\n"
        f"Feedback from Database: {feedback}\n"
        "Fix the SQL code."
    )


def build_explanation_prompt(question: str, sql: str) -> str:
    return f"Question: '{question}'\nSQL: {sql}\nOne-sentence description:"
