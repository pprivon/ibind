"""
Account ids never reach a log record in clear.

`switch_account` used to log `ALSO NEED TO SWITCH WEBSOCKET ACCOUNT TO <id>` at
WARNING with the raw id, so every consumer that switches accounts wrote live
account ids into its stderr / journal. The ids used here are visibly fake.
"""
import logging
from unittest.mock import MagicMock

import pytest
from requests.exceptions import ReadTimeout

from ibind.client.ibkr_client import IbkrClient
from ibind.client.ibkr_ws_client import IbkrWsClient

LIVE_ID = 'U00000001'
LIVE_MASKED = 'U***0001'
PAPER_ID = 'DU0000002'
PAPER_MASKED = 'DU***0002'


def _messages(caplog):
    return [r.getMessage() for r in caplog.records]


def _assert_no_raw_id(caplog, *raw_ids):
    for message in _messages(caplog):
        for raw in raw_ids:
            assert raw not in message, f'raw account id leaked into a log record: {message!r}'


@pytest.fixture
def client():
    c = IbkrClient(use_oauth=False, max_retries=0)
    c.post = MagicMock(return_value=MagicMock(name='Result'))
    return c


@pytest.mark.parametrize('raw, masked', [(LIVE_ID, LIVE_MASKED), (PAPER_ID, PAPER_MASKED)])
def test_switch_account_logs_masked_id_at_debug_not_warning(client, caplog, raw, masked):
    ## Arrange
    caplog.set_level(logging.DEBUG)

    ## Act
    client.switch_account(raw)

    ## Assert
    client.post.assert_called_once_with('iserver/account', params={'acctId': raw})
    assert client.account_id == raw  # the id itself is still used, only the log is masked
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], 'switch_account must not warn'
    _assert_no_raw_id(caplog, raw)
    reminder = [m for m in _messages(caplog) if 'SWITCH WEBSOCKET ACCOUNT' in m]
    assert reminder == [f'ALSO NEED TO SWITCH WEBSOCKET ACCOUNT TO {masked}']
    assert [r.levelno for r in caplog.records if 'SWITCH WEBSOCKET ACCOUNT' in r.getMessage()] == [logging.DEBUG]


@pytest.mark.parametrize('raw, masked', [
    (LIVE_ID, LIVE_MASKED),
    (PAPER_ID, PAPER_MASKED),
    ('DF0000003', 'DF***0003'),
    ('DFP0000004', 'DFP***0004'),
    ('U12', 'U***'),  # too short to keep a tail: mask it all
    ('0000005678', '***5678'),
])
def test_mask_account_id_matches_arbiter_shape(raw, masked):
    from ibind.support.logs import mask_account_id
    assert mask_account_id(raw) == masked


def test_mask_account_id_none_passthrough():
    from ibind.support.logs import mask_account_id
    assert mask_account_id(None) is None


def test_mask_account_ids_in_free_text():
    from ibind.support.logs import mask_account_ids
    text = f"GET https://x/v1/api/portfolio/{LIVE_ID}/positions {{'params': {{'acctId': '{PAPER_ID}'}}}} conid=265598"
    masked = mask_account_ids(text)
    assert LIVE_ID not in masked and PAPER_ID not in masked
    assert LIVE_MASKED in masked and PAPER_MASKED in masked
    assert 'conid=265598' in masked  # numbers that are not account ids are untouched


def test_new_client_banner_masks_account_id_and_headers_notice_is_debug(caplog):
    ## Arrange
    caplog.set_level(logging.DEBUG)

    ## Act
    IbkrClient(use_oauth=False, account_id=LIVE_ID)

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID)
    assert any(f"account_id='{LIVE_MASKED}'" in m for m in _messages(caplog))
    headers_notice = [r for r in caplog.records if '_headers attribute was not initialized' in r.getMessage()]
    assert headers_notice, 'expected the _headers notice to be emitted on construction'
    assert all(r.levelno == logging.DEBUG for r in headers_notice)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_request_log_line_masks_account_ids(client, caplog):
    ## Arrange
    client.account_id = LIVE_ID
    client.use_session = True
    client._session = MagicMock()
    client._session.request.side_effect = ReadTimeout('boom')
    caplog.set_level(logging.DEBUG)

    ## Act
    with pytest.raises(TimeoutError):
        client._request('GET', f'portfolio/{LIVE_ID}/positions/0', params={'acctId': PAPER_ID})

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID, PAPER_ID)
    assert any(LIVE_MASKED in m and PAPER_MASKED in m for m in _messages(caplog))


def test_ws_account_mismatch_and_account_message_are_masked(caplog):
    ## Arrange
    ws = MagicMock()
    ws._account_id = LIVE_ID
    caplog.set_level(logging.DEBUG)

    ## Act
    IbkrWsClient._handle_account_update(ws, {}, {'accounts': [PAPER_ID]})
    IbkrWsClient._handle_account_update(ws, {}, {'accounts': [LIVE_ID], 'selectedAccount': LIVE_ID})

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID, PAPER_ID)
    messages = _messages(caplog)
    assert any('Account ID mismatch' in m and LIVE_MASKED in m and PAPER_MASKED in m for m in messages)
    assert any('Account message' in m and LIVE_MASKED in m for m in messages)
