import pytest
import aiohttp
from aioresponses import aioresponses

from services.kinozal_auth_service import KinozalAuthService
from config import KINOZAL_CREDENTIALS


@pytest.mark.asyncio
async def test_authenticate_success():
    service = KinozalAuthService(**KINOZAL_CREDENTIALS)

    with aioresponses() as m:
        m.post("https://kinozal.tv/takelogin.php", status=200)

        session = await service.authenticate()
        assert isinstance(session, aiohttp.ClientSession)
        await session.close()


@pytest.mark.asyncio
async def test_authenticate_failure():
    username = "wronguser"
    password = "wrongpass"

    service = KinozalAuthService(username, password)

    with aioresponses() as m:
        m.post("https://kinozal.tv/takelogin.php", status=401)

        with pytest.raises(Exception):
            await service.authenticate()
