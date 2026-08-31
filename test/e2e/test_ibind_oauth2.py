"""
End-to-end tests for OAuth 2.0 authentication against the live IBKR Web API.

These tests require an IBKR account with OAuth 2.0 enabled. They are skipped unless the
following environment variables are set:

- IBIND_ACCOUNT_ID
- IBIND_OAUTH2_CLIENT_ID
- IBIND_OAUTH2_CLIENT_KEY_ID
- IBIND_OAUTH2_USERNAME
- IBIND_OAUTH2_PRIVATE_KEY_PEM or IBIND_OAUTH2_PRIVATE_KEY_PATH
"""

import os

import pytest

from ibind.client.ibkr_client import IbkrClient
from ibind.oauth.oauth2 import OAuth2Config

_REQUIRED_ENV_VARS = [
    'IBIND_ACCOUNT_ID',
    'IBIND_OAUTH2_CLIENT_ID',
    'IBIND_OAUTH2_CLIENT_KEY_ID',
    'IBIND_OAUTH2_USERNAME',
]


@pytest.fixture(scope='module')
def oauth2_client():
    missing_vars = [var_name for var_name in _REQUIRED_ENV_VARS if not os.getenv(var_name)]
    if missing_vars:
        pytest.skip(f'Missing environment variables for the OAuth 2.0 e2e tests: {", ".join(missing_vars)}')

    if not os.getenv('IBIND_OAUTH2_PRIVATE_KEY_PEM') and not os.getenv('IBIND_OAUTH2_PRIVATE_KEY_PATH'):
        pytest.skip('Neither IBIND_OAUTH2_PRIVATE_KEY_PEM nor IBIND_OAUTH2_PRIVATE_KEY_PATH is set.')

    client = IbkrClient(account_id=os.getenv('IBIND_ACCOUNT_ID'), use_oauth=True, oauth_config=OAuth2Config())
    try:
        yield client
    finally:
        client.close()


def test_client_holds_an_sso_bearer_token(oauth2_client):
    """Authenticates on construction and retains the SSO bearer token."""
    # Arrange
    oauth_config = oauth2_client.oauth_config

    # Act
    has_token = oauth_config.has_sso_bearer_token()

    # Assert
    assert isinstance(oauth_config, OAuth2Config)
    assert has_token


def test_authorises_requests_with_the_sso_bearer_token(oauth2_client):
    """Signs regular Web API requests with the SSO bearer token."""
    # Arrange
    request_url = f'{oauth2_client.base_url}portfolio/accounts'

    # Act
    headers = oauth2_client._get_headers('GET', request_url)

    # Assert
    assert headers == {'Authorization': f'Bearer {oauth2_client.oauth_config.sso_bearer_token}'}


def test_tickle(oauth2_client):
    """Keeps the authenticated session alive."""
    # Arrange / Act
    result = oauth2_client.tickle()

    # Assert
    assert isinstance(result.data, dict)


def test_portfolio_accounts(oauth2_client):
    """Reads the portfolio accounts over the OAuth 2.0 session."""
    # Arrange / Act
    result = oauth2_client.portfolio_accounts()

    # Assert
    assert isinstance(result.data, list)


def test_portfolio_summary(oauth2_client):
    """Reads the portfolio summary of the configured account."""
    # Arrange
    account_id = oauth2_client.account_id

    # Act
    result = oauth2_client.portfolio_summary(account_id=account_id)

    # Assert
    assert isinstance(result.data, dict)


def test_positions(oauth2_client):
    """Reads the positions of the configured account."""
    # Arrange
    account_id = oauth2_client.account_id

    # Act
    result = oauth2_client.positions(account_id=account_id, page=0)

    # Assert
    assert isinstance(result.data, list)


def test_trades_history(oauth2_client):
    """Reads the recent trade history of the configured account."""
    # Arrange
    account_id = oauth2_client.account_id

    # Act
    result = oauth2_client.trades(account_id=account_id, days='7')

    # Assert
    assert isinstance(result.data, list)


def test_live_marketdata_snapshot(oauth2_client):
    """Reads a live market data snapshot over the OAuth 2.0 session."""
    # Arrange
    oauth2_client.portfolio_accounts()

    # Act
    result = oauth2_client.live_marketdata_snapshot_by_symbol(queries=['AAPL', 'MSFT'], fields=['31', '84', '86'])

    # Assert
    assert isinstance(result, dict)
