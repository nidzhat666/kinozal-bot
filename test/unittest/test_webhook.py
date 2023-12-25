from fastapi.testclient import TestClient

from bot.main import app

client = TestClient(app)


def test_webhook():
    test_update = {
        "update_id": 123456,
        "message": {
            "message_id": 111,
            "from": {
                "id": 123456789,
                "is_bot": False,
                "first_name": "John",
                "last_name": "Doe",
                "username": "johndoe",
                "language_code": "en"
            },
            "chat": {
                "id": 123456789,
                "first_name": "John",
                "last_name": "Doe",
                "username": "johndoe",
                "type": "private"
            },
            "date": 1611503660,
            "text": "Hello, bot!"
        }
    }

    response = client.post("/webhook", json=test_update)
    assert response.status_code == 200
