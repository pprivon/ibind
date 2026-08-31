# OAuth 2.0

IBKR also offers [OAuth 2.0][ibkr-oauth2] as an alternative to [OAuth 1.0a][oauth1a] for headless communication with the Client Portal Web API. IBind supports the Client Credentials Grant flow, in which IBind signs a JWT client assertion with your private key, exchanges it for an access token, and then exchanges that access token for the SSO bearer token used by all subsequent Web API requests.

* [Enabling OAuth 2.0](#enabling_oauth2)
* [Using OAuth 2.0 in IBind](#using_oauth2_in_ibind)
* [Differences from OAuth 1.0a](#differences)

## <a name="enabling_oauth2"></a> Enabling OAuth 2.0

At the time of writing, OAuth 2.0 is provisioned by IBKR on request rather than through a self-service portal, and appears to be primarily targeted at business accounts. Contact IBKR API support to have it enabled for your account. They will supply the client ID, the client key ID and the details needed to register your public key.

You will end up with:

* a **client ID** identifying your OAuth 2.0 client,
* a **client key ID** (the `kid` used in the JWT header),
* a **private key** in PEM format whose public counterpart is registered with IBKR,
* the **IBKR username** the sessions are created for.

IBKR also binds the SSO session to a public IP address. IBind sends the IP address you configure, and deduces the machine's public IP automatically when you don't configure one.

## <a name="using_oauth2_in_ibind"></a> Using OAuth 2.0 in IBind

OAuth 2.0 support is an optional extension of IBind. To use it, first install its additional dependencies by running:

```python
pip install ibind[oauth]
```

In order to use OAuth 2.0 you're required to provide a number of parameters in one of the two ways:

- As environment variables
- As constructor parameters of `OAuth2Config`

### Environment Variables

Set the following environment variables:

1. `IBIND_USE_OAUTH` set to `True`.
1. `IBIND_OAUTH2_CLIENT_ID`: The OAuth 2.0 client ID issued by IBKR.
1. `IBIND_OAUTH2_CLIENT_KEY_ID`: The OAuth 2.0 client key ID (the JWT `kid`) issued by IBKR.
1. `IBIND_OAUTH2_USERNAME`: The IBKR username associated with the OAuth 2.0 client.
1. The private key used to sign the JWT client assertions, in one of two ways:
    - `IBIND_OAUTH2_PRIVATE_KEY_PATH`: The path to the private key PEM file. This is the recommended option.
    - `IBIND_OAUTH2_PRIVATE_KEY_PEM`: The private key PEM content. Since environment variables cannot hold literal newlines, the newlines of the PEM may be escaped as `\n`.

Unlike OAuth 1.0a, an `OAuth2Config` instance has to be passed explicitly, as `OAuth1aConfig` is used by default:

```python
from ibind import IbkrClient
from ibind.oauth.oauth2 import OAuth2Config

client = IbkrClient(use_oauth=True, oauth_config=OAuth2Config())  # remaining parameters read from environment variables
```

### Constructor Parameters

Alternatively, all OAuth 2.0 parameters can be specified as parameters to `OAuth2Config`, although caution is advised in order to avoid exposing these credentials in your code base:

```python
client = IbkrClient(
    use_oauth=True,
    oauth_config=OAuth2Config(
        client_id='my_client_id',
        client_key_id='my_client_key_id',
        username='my_ibkr_username',
        private_key_path='/path/to/private_key.pem',
    ),
)
```

Any parameters not specified programmatically will be read from environment variables.

### Basic Usage

Once correctly set up, you can utilise the `IbkrClient` class normally to communicate with the IBKR REST API:

```python
portfolio_accounts = client.portfolio_accounts().data
```

See ["rest_10_oauth2"][rest_10_oauth2] for an example of how to use OAuth 2.0 with IBind.

## <a name="differences"></a> Differences from OAuth 1.0a

* `oauth_config` must be provided explicitly - IBind defaults to OAuth 1.0a when it is omitted.
* There is no live session token and no Diffie-Hellman exchange. IBind holds an access token and an SSO bearer token instead, both of which are discarded on `oauth_shutdown`.
* The brokerage session is established through `/sso/validate` followed by `/iserver/auth/ssodh/init`. When IBKR fails to generate the SSO DH token while competing for the session, IBind retries without competing.
* The `Tickler` keeps the session alive in the same way as it does for OAuth 1.0a.
* WebSocket connections are not yet supported with OAuth 2.0 - see [Advanced OAuth 1.0a][advanced-oauth1a] for the OAuth 1.0a WebSocket setup.

See the [OAuth environment variables][configuration] section for the full list of OAuth 2.0 variables and their defaults.

[ibkr-oauth2]: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#oauth-20
[oauth1a]: ./oauth_1a.md
[advanced-oauth1a]: ./advanced_oauth_1a.md
[configuration]: ../configuration.md#oauth-environment-variables
[rest_10_oauth2]: https://github.com/Voyz/ibind/blob/master/examples/rest_10_oauth2.py
