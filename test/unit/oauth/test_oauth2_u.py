from pathlib import Path
from unittest.mock import MagicMock

import pytest
from Crypto.PublicKey import RSA  # nosec

from ibind.base.rest_client import Result
from ibind.client.ibkr_client import IbkrClient
from ibind.oauth.oauth2 import OAuth2Config, OAuth2Handler, establish_oauth2_brokerage_session
from ibind.support.errors import ExternalBrokerError

_PRIVATE_KEY_PEM = RSA.generate(2048).export_key().decode()


def make_oauth2_config(**overrides) -> OAuth2Config:
    config = {
        'client_id': 'client-id',
        'client_key_id': 'key-id',
        'private_key_pem': 'dummy-private-key',
        'username': 'user-name',
    }
    config.update(overrides)
    return OAuth2Config(**config)


def make_oauth2_client(oauth_config: OAuth2Config) -> IbkrClient:
    client = IbkrClient(use_oauth=False, auto_register_shutdown=False)
    client._use_oauth = True
    client.oauth_config = oauth_config
    return client


def test_oauth2_config_loads_private_key_from_path(tmp_path: Path) -> None:
    """Reads the private key from private_key_path when no PEM content is given."""
    # Arrange
    key_path = tmp_path / 'private.pem'
    key_path.write_text('file-private-key', encoding='utf-8')

    # Act
    config = make_oauth2_config(private_key_pem=None, private_key_path=str(key_path))

    # Assert
    assert config.private_key_pem == 'file-private-key'


def test_oauth2_config_verify_config_reports_missing_parameters() -> None:
    """Names every missing required parameter rather than failing on the first one."""
    # Arrange
    config = make_oauth2_config(client_id=None, username=None)

    # Act / Assert
    with pytest.raises(ValueError, match='client_id, username'):
        config.verify_config()


def test_oauth2_handler_accepts_private_key_with_escaped_newlines() -> None:
    """Restores newlines in a PEM supplied through an environment variable."""
    # Arrange
    escaped_pem = _PRIVATE_KEY_PEM.replace('\n', '\\n')
    client = make_oauth2_client(make_oauth2_config(private_key_pem=escaped_pem))

    # Act
    handler = OAuth2Handler(client=client)

    # Assert
    assert handler.jwt_private_key.export_key().decode() == _PRIVATE_KEY_PEM


def test_oauth2_get_headers_skips_token_and_sso_requests() -> None:
    """Sends no OAuth headers to the endpoints that mint the tokens."""
    # Arrange
    oauth_config = make_oauth2_config()
    oauth_config.sso_bearer_token = 'sso-token'  # noqa: S105
    client = make_oauth2_client(oauth_config)

    # Act
    token_headers = client._get_headers('POST', oauth_config.token_url)
    sso_headers = client._get_headers('POST', oauth_config.sso_session_url)

    # Assert
    assert token_headers == {}
    assert sso_headers == {}


def test_oauth2_get_headers_adds_bearer_token_for_api_requests() -> None:
    """Authorises regular Web API requests with the SSO bearer token."""
    # Arrange
    oauth_config = make_oauth2_config()
    oauth_config.sso_bearer_token = 'sso-token'  # noqa: S105
    client = make_oauth2_client(oauth_config)

    # Act
    headers = client._get_headers('GET', 'https://api.ibkr.com/v1/api/portfolio/accounts')

    # Assert
    assert headers == {'Authorization': 'Bearer sso-token'}


def test_oauth2_get_headers_without_sso_token_returns_empty_headers(caplog: pytest.LogCaptureFixture) -> None:
    """Logs an error and sends no Authorization header when the SSO token is missing."""
    # Arrange
    client = make_oauth2_client(make_oauth2_config())

    # Act
    with caplog.at_level('ERROR', logger='ibind.client.ibkr_client'):
        headers = client._get_headers('GET', 'https://api.ibkr.com/v1/api/portfolio/accounts')

    # Assert
    assert headers == {}
    assert 'SSO bearer token is missing' in caplog.text


def make_brokerage_session_client(validate_data: dict) -> MagicMock:
    client = MagicMock()
    client.validate.return_value = Result(data=validate_data)
    client.initialize_brokerage_session.return_value = Result(data={'authenticated': True})
    client.authentication_status.return_value = Result(data={'authenticated': True})
    return client


def test_establish_brokerage_session_initialises_once_on_success() -> None:
    """Stops after the first successful brokerage session initialization."""
    # Arrange
    client = make_brokerage_session_client({'RESULT': True})

    # Act
    establish_oauth2_brokerage_session(client)

    # Assert
    client.initialize_brokerage_session.assert_called_once_with(compete=True)
    client.authentication_status.assert_called_once()


def test_establish_brokerage_session_accepts_authenticated_validation() -> None:
    """Accepts an 'authenticated' flag when /sso/validate omits 'RESULT'."""
    # Arrange
    client = make_brokerage_session_client({'authenticated': True})

    # Act
    establish_oauth2_brokerage_session(client)

    # Assert
    client.initialize_brokerage_session.assert_called_once_with(compete=True)


def test_establish_brokerage_session_skips_init_when_validation_fails(caplog: pytest.LogCaptureFixture) -> None:
    """Does not initialize the brokerage session when /sso/validate fails."""
    # Arrange
    client = make_brokerage_session_client({'RESULT': False})

    # Act
    with caplog.at_level('WARNING', logger='ibind.oauth.oauth2'):
        establish_oauth2_brokerage_session(client)

    # Assert
    client.initialize_brokerage_session.assert_not_called()
    assert '/sso/validate did not indicate a clear success' in caplog.text


def test_establish_brokerage_session_retries_without_competing_on_dh_token_error() -> None:
    """Retries with compete=False when IBKR fails to generate the SSO DH token."""
    # Arrange
    client = make_brokerage_session_client({'RESULT': True})
    dh_error = ExternalBrokerError('failed to generate sso dh token', status_code=500)
    client.initialize_brokerage_session.side_effect = [dh_error, Result(data={'authenticated': True})]

    # Act
    establish_oauth2_brokerage_session(client)

    # Assert
    assert [call.kwargs['compete'] for call in client.initialize_brokerage_session.call_args_list] == [True, False]


def test_establish_brokerage_session_raises_after_exhausting_retries() -> None:
    """Raises once the DH token error persists past max_retries."""
    # Arrange
    client = make_brokerage_session_client({'RESULT': True})
    dh_error = ExternalBrokerError('failed to generate sso dh token', status_code=500)
    client.initialize_brokerage_session.side_effect = dh_error

    # Act / Assert
    with pytest.raises(ExternalBrokerError):
        establish_oauth2_brokerage_session(client, max_retries=1)

    assert client.initialize_brokerage_session.call_count == 2


def test_establish_brokerage_session_does_not_retry_other_errors() -> None:
    """Does not retry brokerage session errors unrelated to the DH token."""
    # Arrange
    client = make_brokerage_session_client({'RESULT': True})
    client.initialize_brokerage_session.side_effect = ExternalBrokerError('some other failure', status_code=503)

    # Act
    establish_oauth2_brokerage_session(client)

    # Assert
    client.initialize_brokerage_session.assert_called_once_with(compete=True)
