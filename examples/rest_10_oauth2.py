"""
REST OAuth 2.0.

Showcases usage of OAuth 2.0 with IbkrClient.

Using IbkrClient with OAuth 2.0 support will automatically handle signing the JWT client assertions and managing the SSO bearer token. You should be able to use all endpoints in the same way as when not using OAuth.

Importantly, in order to use OAuth 2.0 you're required to set up the following environment variables:

- IBIND_USE_OAUTH: Set to True.
- IBIND_OAUTH2_CLIENT_ID: The OAuth 2.0 client ID issued by IBKR.
- IBIND_OAUTH2_CLIENT_KEY_ID: The OAuth 2.0 client key ID (the JWT 'kid') issued by IBKR.
- IBIND_OAUTH2_USERNAME: The IBKR username associated with the OAuth 2.0 client.
- IBIND_OAUTH2_PRIVATE_KEY_PATH: The path to the private key PEM file used to sign the JWT client assertions.

Alternatively to IBIND_OAUTH2_PRIVATE_KEY_PATH, the key content can be passed in IBIND_OAUTH2_PRIVATE_KEY_PEM. Since environment variables cannot hold literal newlines, the newlines of the PEM may be escaped as '\\n'.

Optionally, you can also set:
- IBIND_OAUTH2_IP_ADDRESS: The public IP address of the machine. If not set, IBind deduces it automatically.
- IBIND_OAUTH2_TOKEN_URL: OAuth 2.0 token endpoint (defaults to 'https://api.ibkr.com/oauth2/api/v1/token').
- IBIND_OAUTH2_SSO_SESSION_URL: OAuth 2.0 SSO session endpoint (defaults to 'https://api.ibkr.com/gw/api/v1/sso-sessions').
- IBIND_OAUTH2_AUDIENCE: JWT audience (defaults to '/token').
- IBIND_OAUTH2_SCOPE: Token scope (defaults to 'sso-sessions.write').
- IBIND_OAUTH2_REST_URL: IBKR REST base URL (defaults to 'https://api.ibkr.com/v1/api/').

If you prefer setting these variables inline, you can pass them to the OAuth2Config instance directly. Any variables not specified will be taken from the environment variables.

Note that unlike OAuth 1.0a, OAuth 2.0 requires an explicit 'oauth_config' parameter, as OAuth1aConfig is used by default.
"""

import os

from ibind import IbkrClient, ibind_logs_initialize
from ibind.oauth.oauth2 import OAuth2Config

ibind_logs_initialize()

cacert = os.getenv('IBIND_CACERT', False)  # insert your cacert path here

client = IbkrClient(
    cacert=cacert,
    use_oauth=True,
    # Optionally, specify OAuth variables dynamically, eg. OAuth2Config(client_id='my_client_id')
    oauth_config=OAuth2Config(),
)

try:
    print('\n#### tickle ####')
    print(client.tickle().data)
finally:
    client.close()
