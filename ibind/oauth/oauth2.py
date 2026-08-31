import base64
import json
import math
import time
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

import requests

# TODO: Remove bandit ignore once we have a new Crypto implementation
# Check repo wiki for more details on Security consideration
from Crypto.Hash import SHA256  # nosec
from Crypto.PublicKey import RSA  # nosec
from Crypto.Signature import PKCS1_v1_5  # nosec

from ibind import var
from ibind.oauth import OAuthConfig
from ibind.support.errors import ExternalBrokerError
from ibind.support.logs import project_logger

if TYPE_CHECKING:  # pragma: no cover
    from ibind.client.ibkr_client import IbkrClient

_LOGGER = project_logger(__file__)


@dataclass
class OAuth2Config(OAuthConfig):
    """
    Dataclass encapsulating OAuth 2.0 configuration parameters.
    """

    client_id: str = var.IBIND_OAUTH2_CLIENT_ID
    """ OAuth 2.0 Client ID. """

    client_key_id: str = var.IBIND_OAUTH2_CLIENT_KEY_ID
    """ OAuth 2.0 Client Key ID. """

    private_key_pem: Optional[str] = var.IBIND_OAUTH2_PRIVATE_KEY_PEM
    """ OAuth 2.0 private key PEM content. """

    private_key_path: Optional[str] = var.IBIND_OAUTH2_PRIVATE_KEY_PATH
    """ Path to the OAuth 2.0 private key PEM file. """

    username: Optional[str] = var.IBIND_OAUTH2_USERNAME
    """ IBKR username used for the OAuth 2.0 credential claim. """

    ip_address: Optional[str] = var.IBIND_OAUTH2_IP_ADDRESS
    """ Public IP address for the OAuth 2.0 credential claim. """

    token_url: str = field(default=var.IBIND_OAUTH2_TOKEN_URL or 'https://api.ibkr.com/oauth2/api/v1/token')
    """ OAuth 2.0 token endpoint URL. """

    sso_session_url: str = field(default=var.IBIND_OAUTH2_SSO_SESSION_URL or 'https://api.ibkr.com/gw/api/v1/sso-sessions')
    """ OAuth 2.0 SSO session endpoint URL. """

    audience: str = field(default=var.IBIND_OAUTH2_AUDIENCE or '/token')
    """ OAuth 2.0 JWT audience. """

    scope: str = field(default=var.IBIND_OAUTH2_SCOPE or 'sso-sessions.write')
    """ OAuth 2.0 token scope. """

    oauth_rest_url: str = var.IBIND_OAUTH2_REST_URL or var.IBIND_REST_URL or 'https://api.ibkr.com/v1/api/'
    """ REST base URL for OAuth 2.0 authenticated requests. """

    oauth_ws_url: str = var.IBIND_OAUTH2_WS_URL or var.IBIND_WS_URL or 'wss://api.ibkr.com/v1/api/ws'
    """ WebSocket base URL for OAuth 2.0 authenticated requests. """

    access_token: Optional[str] = field(default=None, init=False)
    """ OAuth 2.0 access token returned by the token endpoint. """

    sso_bearer_token: Optional[str] = field(default=None, init=False)
    """ SSO bearer token returned by the IBKR gateway. """

    def __post_init__(self) -> None:
        if self.private_key_pem is None and self.private_key_path:
            try:
                with open(self.private_key_path, 'r', encoding='utf-8') as file:
                    self.private_key_pem = file.read()
            except OSError as exc:
                _LOGGER.error(f'Failed to load OAuth 2.0 private key from {self.private_key_path}: {exc}')

    def version(self):
        return 2.0

    def has_sso_bearer_token(self) -> bool:
        """Checks if an SSO bearer token is present and non-empty."""
        return bool(self.sso_bearer_token)

    def verify_config(self) -> None:
        required_params = ['client_id', 'client_key_id', 'private_key_pem', 'username', 'token_url', 'sso_session_url', 'audience', 'scope']
        missing_params = [param for param in required_params if not getattr(self, param)]
        if missing_params:
            raise ValueError(f'OAuth2Config is missing required parameters: {", ".join(missing_params)}')
        super().verify_config()


def _get_public_ip() -> Optional[str]:
    """Fetches the public IP address from an external service."""
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        response.raise_for_status()
        ip_address = response.json()['ip']
        _LOGGER.debug(f'Successfully fetched public IP address: {ip_address}')
        return ip_address
    except requests.exceptions.RequestException as e:
        _LOGGER.error(f'Could not fetch public IP address: {e}')
        return None
    except json.JSONDecodeError as e:
        _LOGGER.error(f'Could not parse IP address from response: {e}')
        return None
    except KeyError as e:
        _LOGGER.error(f'Could not extract IP from response (KeyError: {e})')
        return None
    except Exception as e:
        _LOGGER.error(f'An unexpected error occurred while fetching public IP: {e}')
        return None


class OAuth2Handler:
    """
    Handles the OAuth 2.0 Client Credentials Grant flow with Interactive Brokers.

    Signs JWT client assertions with the configured private key, exchanges them for an
    access token, and then trades that access token for the SSO bearer token used by all
    subsequent Web API requests. All HTTP calls go through the `IbkrClient` that owns this
    handler, so they share its session, retry, logging and error handling behaviour.
    """

    def __init__(self, client: 'IbkrClient'):
        self.client = client
        if not self.client.oauth_config.private_key_pem:
            raise ValueError('Private key PEM cannot be empty (accessed via client.oauth_config).')
        try:
            # Environment variables cannot hold literal newlines, so an escaped '\n' is accepted too
            self.jwt_private_key = RSA.import_key(self.client.oauth_config.private_key_pem.replace('\\n', '\n'))
        except Exception as e:
            raise ValueError(f'Failed to import private key: {e}') from e

    def _base64_encode(self, val: bytes) -> str:
        return base64.b64encode(val).decode().replace('+', '-').replace('/', '_').rstrip('=')

    def _make_jws(self, header: dict, claims: dict) -> str:
        json_header = json.dumps(header, separators=(',', ':')).encode()
        encoded_header = self._base64_encode(json_header)
        json_claims = json.dumps(claims, separators=(',', ':')).encode()
        encoded_claims = self._base64_encode(json_claims)
        payload = f'{encoded_header}.{encoded_claims}'
        md = SHA256.new(payload.encode())
        signer = PKCS1_v1_5.new(self.jwt_private_key)
        signature = signer.sign(md)
        encoded_signature = self._base64_encode(signature)
        return f'{payload}.{encoded_signature}'

    def _compute_client_assertion(self, url_for_assertion: str) -> str:
        oauth_config = self.client.oauth_config
        now = math.floor(time.time())
        header = {'alg': 'RS256', 'typ': 'JWT', 'kid': oauth_config.client_key_id}

        if url_for_assertion == oauth_config.token_url:
            claims = {
                'iss': oauth_config.client_id,
                'sub': oauth_config.client_id,
                'aud': oauth_config.audience,
                'exp': now + 60,
                'iat': now - 10,
            }
        elif url_for_assertion == oauth_config.sso_session_url:
            claims = {
                'ip': oauth_config.ip_address,
                'credential': oauth_config.username,
                'iss': oauth_config.client_id,
                'exp': now + 86400,
                'iat': now,
            }
        else:
            raise ValueError(f'Unknown URL for client assertion: {url_for_assertion}')

        return self._make_jws(header, claims)

    def get_access_token(self) -> Optional[str]:
        """Gets an OAuth 2.0 access token."""
        url = self.client.oauth_config.token_url
        form_data = {
            'grant_type': 'client_credentials',
            'scope': self.client.oauth_config.scope,
            'client_id': self.client.oauth_config.client_id,
            'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
            'client_assertion': self._compute_client_assertion(url),
        }
        headers = {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'}

        _LOGGER.debug(f'Requesting OAuth 2.0 access token from {url}')

        try:
            result = self.client._request(method='POST', endpoint=url, base_url='', extra_headers=headers, data=form_data)
        except ExternalBrokerError as e:
            _LOGGER.error(f'Error obtaining OAuth 2.0 access token: {e}')
            return None

        if not isinstance(result.data, dict):
            _LOGGER.error(f'Unexpected OAuth 2.0 access token response: {result.data}')
            return None

        access_token = result.data.get('access_token')
        if not access_token:
            _LOGGER.error(f'access_token not found in response: {result.data}')
            return None

        _LOGGER.debug('Successfully obtained OAuth 2.0 access token.')
        return access_token

    def get_sso_bearer_token(self, access_token: str) -> Optional[str]:
        """Gets an SSO bearer token using a previously obtained access token."""
        url = self.client.oauth_config.sso_session_url
        signed_request_assertion_jwt = self._compute_client_assertion(url)
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/jwt',
            'Accept': 'application/json',
        }

        _LOGGER.debug(f'Requesting SSO bearer token from {url}')

        try:
            result = self.client._request(method='POST', endpoint=url, base_url='', extra_headers=headers, data=signed_request_assertion_jwt)
        except ExternalBrokerError as e:
            _LOGGER.error(f'Error obtaining SSO bearer token: {e}')
            return None

        if not isinstance(result.data, dict):
            _LOGGER.error(f'Unexpected SSO bearer token response: {result.data}')
            return None

        sso_bearer_token = result.data.get('access_token')
        if not sso_bearer_token:
            _LOGGER.error(f"SSO bearer token ('access_token') not found in response: {result.data}")
            return None

        _LOGGER.debug('Successfully obtained SSO bearer token.')
        return sso_bearer_token

    def authenticate(self) -> Optional[str]:
        """Runs the full OAuth 2.0 flow and stores the resulting tokens in the client's OAuth config."""
        access_token = self.get_access_token()
        if not access_token:
            _LOGGER.error('OAuth 2.0 authentication failed: could not retrieve access token.')
            return None

        sso_bearer_token = self.get_sso_bearer_token(access_token)
        if not sso_bearer_token:
            _LOGGER.error('OAuth 2.0 authentication failed: could not retrieve SSO bearer token.')
            return None

        self.client.oauth_config.access_token = access_token
        self.client.oauth_config.sso_bearer_token = sso_bearer_token
        _LOGGER.debug('OAuth 2.0 authentication successful. Tokens stored in the OAuth config.')
        return sso_bearer_token


def authenticate_oauth2(client: 'IbkrClient') -> Optional[str]:
    """
    Authenticates the client using OAuth 2.0 and returns the SSO bearer token.

    Parameters:
        client (IbkrClient): The client whose `oauth_config` holds the OAuth 2.0 credentials.

    Returns:
        Optional[str]: The SSO bearer token, or None if authentication failed.

    Raises:
        ValueError: If the OAuth 2.0 configuration is incomplete or the private key cannot be read.
    """
    config = client.oauth_config
    config.verify_config()

    if not config.ip_address:
        config.ip_address = _get_public_ip()
        if not config.ip_address:
            _LOGGER.error(f'{client}: Failed to deduce the public IP address. Cannot proceed with OAuth 2.0.')
            return None
        _LOGGER.info(f'{client}: Using automatically deduced public IP address: {config.ip_address}')

    return OAuth2Handler(client=client).authenticate()


def establish_oauth2_brokerage_session(client: 'IbkrClient', max_retries: int = 2) -> None:
    """
    Establishes the brokerage session for an OAuth 2.0 authenticated client.

    This involves validating the SSO session and then initializing the brokerage session.

    Parameters:
        client (IbkrClient): The OAuth 2.0 authenticated client.
        max_retries (int): How many times to retry initializing the brokerage session. Default is 2.

    Raises:
        ExternalBrokerError: If initializing the brokerage session keeps failing after `max_retries`.
    """
    _LOGGER.debug(f'{client}: OAuth 2.0: Attempting to establish brokerage session (/sso/validate and initialize).')

    validation_result = client.validate()
    _LOGGER.debug(f'{client}: /sso/validate result: {validation_result.data}')

    if not (validation_result.data.get('RESULT') or validation_result.data.get('authenticated')):
        _LOGGER.warning(
            f'{client}: /sso/validate did not indicate a clear success. '
            f'Cannot proceed with brokerage session initialization. '
            f'Validation data: {validation_result.data}'
        )
        return

    _LOGGER.debug(f'{client}: /sso/validate successful. Now attempting to initialize brokerage session.')

    # IBKR occasionally fails to generate the SSO DH token when competing for the session, in which
    # case retrying without competing tends to succeed.
    compete = True
    for attempt in range(max_retries + 1):
        try:
            init_result = client.initialize_brokerage_session(compete=compete)
            _LOGGER.debug(f'{client}: initialize_brokerage_session(compete={compete}) result: {init_result.data}')

            auth_status_after_init = client.authentication_status()
            _LOGGER.debug(f'{client}: /iserver/auth/status (after compete={compete} init): {auth_status_after_init.data}')
            if not auth_status_after_init.data.get('authenticated'):
                _LOGGER.warning(f'{client}: Still not authenticated after compete={compete} init.')

            return

        except ExternalBrokerError as e:
            _LOGGER.error(f'{client}: Establishing OAuth 2.0 brokerage session failed: {e}')

            if attempt >= max_retries:
                raise

            if e.status_code == 500 and 'failed to generate sso dh token' in str(e):
                compete = False
                _LOGGER.info(
                    f'{client}: Retrying initialize_brokerage_session with compete=False due to DH token error. '
                    f'Retrying attempt {attempt + 1}/{max_retries}'
                )
                continue

            # we don't retry for non-DH token errors
            break
