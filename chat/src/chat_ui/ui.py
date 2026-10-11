import gradio as gr

from .config import APP_CSS, ENTER_SUBMIT_JS
from .api_client import fetch_sql_datasources
from .handlers import approve, cancel, send_message


def create_demo() -> gr.Blocks:
    with gr.Blocks(title="Chart Agent Chat", fill_height=True) as demo:
        # Gradio 6 убрал параметр css у Blocks, и demo.css больше ни на что не влияет.
        # Рабочий способ — отдать стили обычным HTML-компонентом.
        gr.HTML(f"<style>{APP_CSS}</style>")
        session_state = gr.State(value=None)
        awaiting_state = gr.State(value=False)

        chatbot = gr.Chatbot(elem_id="chatbot", scale=1)
        with gr.Row():
            approve_btn = gr.Button("Подтвердить", visible=False, interactive=False, elem_id="approve_btn")
            cancel_btn = gr.Button("Отмена", visible=False, interactive=False, elem_id="cancel_btn")
        with gr.Row():
            auto_validate_checkbox = gr.Checkbox(
                value=True,
                label="Автовалидация генерации",
                info="Отключите, чтобы делать только одну генерацию без VL-оценки.",
            )
            no_text_checkbox = gr.Checkbox(
                value=False,
                label="Режим без текста",
                info="График рендерится без подписей — чистая картинка для диффузии. Рядом отображается версия с наложенными подписями.",
            )
            sql_source_checkbox = gr.Checkbox(
                value=False,
                label="Данные из базы",
                info="Вопрос уходит SQL-агенту, который выполняет запрос к базе и возвращает таблицу. Использованный SQL показывается под графиком.",
            )
            _ds_list, _ds_default = fetch_sql_datasources()
            sql_datasource_dropdown = gr.Dropdown(
                choices=_ds_list or [""],
                value=_ds_default or (_ds_list[0] if _ds_list else ""),
                label="База данных",
                info="К какой базе задаётся вопрос (работает при включённой галочке).",
                interactive=bool(_ds_list),
            )
        textbox = gr.MultimodalTextbox(
            elem_id="chat_input",
            file_types=[".csv", "image"],
            sources=["upload"],
            file_count="multiple",
            lines=1,
            max_lines=6,
            submit_btn=False,
            placeholder="Напишите сообщение и/или прикрепите CSV, изображение...",
        )
        send_btn = gr.Button("Отправить", variant="primary", elem_id="send_btn")

        textbox.submit(
            send_message,
            inputs=[textbox, chatbot, session_state, awaiting_state, auto_validate_checkbox, no_text_checkbox, sql_source_checkbox, sql_datasource_dropdown],
            outputs=[chatbot, session_state, awaiting_state, textbox, approve_btn, cancel_btn],
        )
        send_btn.click(
            send_message,
            inputs=[textbox, chatbot, session_state, awaiting_state, auto_validate_checkbox, no_text_checkbox, sql_source_checkbox, sql_datasource_dropdown],
            outputs=[chatbot, session_state, awaiting_state, textbox, approve_btn, cancel_btn],
        )

        approve_btn.click(
            approve,
            inputs=[chatbot, session_state],
            outputs=[chatbot, session_state, awaiting_state, approve_btn, cancel_btn],
        )

        cancel_btn.click(
            cancel,
            inputs=[chatbot, session_state],
            outputs=[chatbot, session_state, awaiting_state, approve_btn, cancel_btn],
        )

    demo.js = ENTER_SUBMIT_JS
    return demo
