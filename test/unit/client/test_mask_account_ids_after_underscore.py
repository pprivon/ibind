"""
`mask_account_ids` anchors on `\\b`, but there is no word boundary between an
underscore and a letter. That let a full account id leak into the "New/Existing
daily rotating file handler" log line, whose filepath is built as
`ibkr_client_<id>` (see `new_daily_rotating_file_handler` in
`ibind/support/logs.py`). The ids used here are visibly fake.
"""
from ibind.support.logs import mask_account_ids

LIVE_ID = 'U00000001'
LIVE_MASKED = 'U***0001'
PAPER_ID = 'DU0000002'
PAPER_MASKED = 'DU***0002'


def test_mask_account_ids_in_file_handler_path():
    # Mirrors the log line emitted by new_daily_rotating_file_handler().
    text = f'New daily rotating file handler for logger "ibkr_client_{LIVE_ID}": /var/log/ibind/ibkr_client_{LIVE_ID}.log'
    masked = mask_account_ids(text)
    assert LIVE_ID not in masked, f'raw account id leaked into masked text: {masked!r}'
    assert LIVE_MASKED in masked


def test_mask_account_ids_id_followed_by_underscore_and_suffix():
    text = f'{PAPER_ID}_x'
    masked = mask_account_ids(text)
    assert PAPER_ID not in masked, f'raw account id leaked into masked text: {masked!r}'
    assert masked == f'{PAPER_MASKED}_x'


def test_mask_account_ids_prefixed_by_underscore_prefix_word():
    text = f'ACCOUNT_{LIVE_ID}'
    masked = mask_account_ids(text)
    assert LIVE_ID not in masked, f'raw account id leaked into masked text: {masked!r}'
    assert masked == f'ACCOUNT_{LIVE_MASKED}'


def test_mask_account_ids_does_not_false_positive_on_letter_prefixed_token():
    # A digit run preceded directly by another letter (e.g. a SKU code, not an
    # underscore) is not an account id and must be left untouched. This is what
    # the negative lookbehind guards against, as opposed to simply dropping the
    # boundary check altogether.
    text = 'SKU1234567 in stock'
    assert mask_account_ids(text) == text

