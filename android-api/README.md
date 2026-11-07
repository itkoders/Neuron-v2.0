# NEURON Android API (separate service)

This service is deliberately isolated from the Telegram bot runtime. It does not import main.py, start polling, or modify the bot source.

## Render service
- Root/build command: `pip install -r android-api/requirements.txt`
- Start command: `uvicorn app:app --app-dir android-api --host 0.0.0.0 --port $PORT`
- Required environment variables: `BOT_TOKEN`, `BOT_USERNAME=Neuronv2_bot`, `DATABASE_URL`, `JWT_SECRET`
- Configure Telegram Login Widget domain in @BotFather to the deployed android-api hostname.

## Security
Telegram Login Widget HMAC is verified server-side; login timestamps expire after 10 minutes; app exchange codes expire after 90 seconds and are single-use; API sessions are signed JWTs. Role membership is rechecked against Neon on each /api/me request.
Never put BOT_TOKEN, DATABASE_URL, or JWT_SECRET in the APK.
