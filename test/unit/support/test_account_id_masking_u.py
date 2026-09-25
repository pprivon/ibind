import logging
from unittest.mock import MagicMock

import pytest
from requests.exceptions import ReadTimeout

from ibind.client.ibkr_client import IbkrClient
from ibind.support import logs
from ibind.support.logs import mask_account_id, mask_account_ids

LIVE_ID = 'U00000001'
LIVE_MASKED = 'U***0001'
PAPER_ID = 'DU0000002'
PAPER_MASKED = 'DU***0002'


def _messages(caplog):
    return [r.getMessage() for r in caplog.records]


def _assert_no_raw_id(caplog, *raw_ids):
    for message in _messages(caplog):
        for raw in raw_ids:
            assert raw not in message, f'raw account id in log record: {message!r}'


@pytest.fixture
def client():
    c = IbkrClient(use_oauth=False)
    c.post = MagicMock()
    return c


@pytest.mark.parametrize(
    'raw, masked',
    [
        (LIVE_ID, LIVE_MASKED),
        (PAPER_ID, PAPER_MASKED),
        ('DF0000003', 'DF***0003'),
        ('DFP0000004', 'DFP***0004'),
        ('U1234', 'U***'),
        ('U12', 'U***'),
        ('0000005678', '***5678'),
    ],
)
def test_mask_account_id(raw, masked):
    assert mask_account_id(raw) == masked


def test_mask_account_id_none():
    assert mask_account_id(None) is None


def test_mask_account_ids_in_free_text():
    text = f"GET /portfolio/{LIVE_ID}/positions {{'params': {{'acctId': '{PAPER_ID}'}}}} conid=265598 orderId=U123456789012"

    masked = mask_account_ids(text)

    assert LIVE_ID not in masked and PAPER_ID not in masked
    assert LIVE_MASKED in masked and PAPER_MASKED in masked
    assert 'conid=265598' in masked
    assert 'orderId=U123456789012' in masked


@pytest.mark.parametrize('raw, masked', [(LIVE_ID, LIVE_MASKED), (PAPER_ID, PAPER_MASKED)])
def test_switch_account_masks_account_id(client, caplog, raw, masked):
    ## Arrange
    caplog.set_level(logging.DEBUG)

    ## Act
    client.switch_account(raw)

    ## Assert
    client.post.assert_called_once_with('iserver/account', params={'acctId': raw})
    assert client.account_id == raw
    _assert_no_raw_id(caplog, raw)
    assert f'ALSO NEED TO SWITCH WEBSOCKET ACCOUNT TO {masked}' in _messages(caplog)


def test_switch_account_reminder_is_debug(client, caplog):
    ## Arrange
    caplog.set_level(logging.DEBUG)

    ## Act
    client.switch_account(PAPER_ID)

    ## Assert
    levels = [r.levelno for r in caplog.records if 'SWITCH WEBSOCKET ACCOUNT' in r.getMessage()]
    assert levels == [logging.DEBUG]


def test_new_client_log_masks_account_id(caplog):
    ## Arrange
    caplog.set_level(logging.DEBUG)

    ## Act
    IbkrClient(use_oauth=False, account_id=LIVE_ID)

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID)
    assert any(f"account_id='{LIVE_MASKED}'" in m for m in _messages(caplog))


def test_request_and_retry_logs_mask_account_ids(caplog):
    ## Arrange
    client = IbkrClient(use_oauth=False, max_retries=1, verbose_retries=True)
    client.use_session = True
    client._session = MagicMock()
    client._session.request.side_effect = ReadTimeout('timeout')
    caplog.set_level(logging.DEBUG)

    ## Act
    with pytest.raises(TimeoutError):
        client._request('GET', f'portfolio/{LIVE_ID}/positions/0', params={'acctId': PAPER_ID})

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID, PAPER_ID)
    messages = _messages(caplog)
    assert any(m.startswith('GET ') and LIVE_MASKED in m and PAPER_MASKED in m for m in messages)
    assert any('Timeout for GET' in m and LIVE_MASKED in m and PAPER_MASKED in m for m in messages)


def test_response_log_masks_account_ids(caplog):
    ## Arrange
    client = IbkrClient(use_oauth=False, log_responses=True)
    client.use_session = True
    client._session = MagicMock()
    client._session.request.return_value.json.return_value = {'accountId': LIVE_ID}
    caplog.set_level(logging.DEBUG)

    ## Act
    client._request('GET', f'portfolio/{LIVE_ID}/summary')

    ## Assert
    _assert_no_raw_id(caplog, LIVE_ID)
    assert any(m.startswith('Result(') and LIVE_MASKED in m for m in _messages(caplog))


def test_file_handler_logs_mask_account_id(caplog, monkeypatch, tmp_path):
    ## Arrange
    monkeypatch.setattr(logs, '_log_to_file', True)
    logger_name = 'TestAccountIdMasking'
    filepath = str(tmp_path / f'ibkr_client_{LIVE_ID}')
    caplog.set_level(logging.DEBUG)

    ## Act
    logger = logs.new_daily_rotating_file_handler(logger_name, filepath)
    logs.new_daily_rotating_file_handler(logger_name, filepath)

    ## Assert
    try:
        _assert_no_raw_id(caplog, LIVE_ID)
        messages = _messages(caplog)
        assert any(m.startswith('New daily rotating file handler') and f'ibkr_client_{LIVE_MASKED}' in m for m in messages)
        assert any(m.startswith('Existing daily rotating file handler') and f'ibkr_client_{LIVE_MASKED}' in m for m in messages)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
