import httpx
from app.core.settings import Settings


def main() -> None:
    settings = Settings()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        client.get("/health").raise_for_status()
        response = client.get("/ready", auth=(settings.admin_username, settings.admin_password.get_secret_value()))
        response.raise_for_status()
        print(response.json())


if __name__ == "__main__":
    main()
