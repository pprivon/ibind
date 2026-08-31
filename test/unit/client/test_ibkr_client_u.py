import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ibind.client.ibkr_client import IbkrClient


@pytest.fixture
def client():
    # Minimal config for IbkrClient, mock dependencies
    c = IbkrClient(use_oauth=False, auto_register_shutdown=False)
    c.check_auth_status = MagicMock()
    c.stop_tickler = MagicMock()
    c.oauth_init = MagicMock()
    c.oauth_config = MagicMock()
    c.oauth_config.maintain_oauth = True
    c.oauth_config.init_brokerage_session = True
    c.oauth_config.shutdown_oauth = False
    return c


def test_handle_auth_status_healthy(client, caplog):
    ## Arrange
    client.check_auth_status.return_value = True

    ## Act
    with caplog.at_level('WARNING', logger='ibind.client.ibkr_client'):
        assert client.handle_auth_status() is True

    ## Assert
    # No warning should be logged
    assert not any('IBKR connection is not healthy' in r.message for r in caplog.records)
    client.check_auth_status.assert_called_once()
    client.stop_tickler.assert_not_called()
    client.oauth_init.assert_not_called()


def test_handle_auth_status_not_healthy_no_oauth(client, caplog):
    ## Arrange
    client.check_auth_status.return_value = False
    client._use_oauth = False

    ## Act
    with caplog.at_level('WARNING', logger='ibind.client.ibkr_client'), patch('ibind.client.ibkr_client._HEALTH_SLEEP_INTERVAL', 0.01):
        assert client.handle_auth_status() is False

    ## Assert
    assert any('IBKR connection is not healthy. Ensure authentication with the Gateway is re-established.' in r.message for r in caplog.records)
    client.stop_tickler.assert_not_called()
    client.oauth_init.assert_not_called()


def test_handle_auth_status_not_healthy_oauth_success(client, caplog):
    ## Arrange
    client.check_auth_status.return_value = False
    client._use_oauth = True
    client.stop_tickler.side_effect = None
    client.oauth_init.side_effect = None

    ## Act
    with caplog.at_level('WARNING', logger='ibind.client.ibkr_client'), patch('ibind.client.ibkr_client._HEALTH_SLEEP_INTERVAL', 0.01):
        assert client.handle_auth_status() is False

    ## Assert
    assert any('IBKR connection is not healthy. Attempting to re-establish OAuth authentication.' in r.message for r in caplog.records)
    client.stop_tickler.assert_called_once_with(15)
    client.oauth_init.assert_called_once_with(maintain_oauth=True, init_brokerage_session=True)


_OAUTH_FREE_STARTUP = """
import importlib.abc
import sys


class BlockCrypto(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'Crypto' or fullname.startswith('Crypto.'):
            raise ImportError(f'{fullname} is not installed')
        return None


sys.meta_path.insert(0, BlockCrypto())

from ibind import IbkrClient

client = IbkrClient(use_oauth=False, auto_register_shutdown=False, url='https://localhost:5000/v1/api/')
assert client._get_headers('GET', 'https://localhost:5000/v1/api/tickle') == {}
assert 'ibind.oauth.oauth1a' not in sys.modules
assert 'ibind.oauth.oauth2' not in sys.modules
"""


def test_client_without_oauth_never_imports_oauth_modules():
    """Runs against the CP Gateway without the optional OAuth dependencies installed."""
    # Arrange
    project_root = Path(__file__).parents[3]

    # Act
    result = subprocess.run(  # noqa: S603
        [sys.executable, '-c', _OAUTH_FREE_STARTUP],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert result.returncode == 0, result.stderr


def test_client_rejects_unsupported_oauth_config():
    """Rejects an OAuth config that is neither OAuth 1.0a nor OAuth 2.0."""
    # Arrange
    unsupported_config = object()

    # Act / Assert
    with pytest.raises(ValueError, match='Unsupported OAuth configuration type'):
        IbkrClient(use_oauth=True, oauth_config=unsupported_config, auto_register_shutdown=False)
