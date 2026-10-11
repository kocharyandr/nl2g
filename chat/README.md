# Chart Agent — Gradio Chat

Веб-интерфейс чата на Gradio для пайплайна chart_agent.
Чат работает с session API:
- `POST /sessions/{session_id}/messages`

`session_id` генерируется на фронте (UUID) и передается в `POST /sessions/{session_id}/messages`.
Если такой `session_id` новый, backend создает state автоматически.

## Запуск

### Docker

```bash
# В .env укажите CHART_AGENT_URL (для Docker с API на хосте:
# http://host.docker.internal:9911 — этот порт chart_agent публикует наружу)
docker compose up --build
```

Откройте http://localhost:7861

### Локально

1. Запустите API (chart_agent) — он публикует порты 8000 и 9911:
   ```bash
   cd ../chart_agent && docker compose up --build
   ```

2. Запустите Gradio-чат:
   ```bash
   set -a && . ./.env && set +a
   pip install -r requirements.txt
   python app.py
   ```

3. Откройте http://localhost:7861

Порт задается через `GRADIO_SERVER_PORT` (в `.env` — 7861; дефолт в коде — 7860).

## Использование

- В первом сообщении можно прикрепить CSV и написать запрос.
- Можно отправлять в одном запросе текст + изображение.
- Изображения отправляются в backend как `images_base64`.
- CSV читается на фронте: в backend отправляется текст + контекст (колонки и preview строк).
- Во время ожидания ответа показывается анимация набора (`.`, `..`, `...`).
- Если backend на стадии `plot_rendering`, под чатом появляется зелёная кнопка `Подтвердить`.
- Вместо кнопки можно отправить обычное сообщение в чат с уточнениями.
- Если backend вернул `artefacts.plot.image_base64` или `artefacts.image.image_base64`, результат автоматически отображается в чате.
- После первого ответа `session_id` хранится в состоянии UI, и диалог продолжается в той же сессии.
