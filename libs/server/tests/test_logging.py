from ucp_server.logging_setup import mask_secrets


def test_bearer_tokens_are_masked():
    masked = mask_secrets("Authorization: Bearer ghp_abcdef1234567890")
    assert "ghp_abcdef1234567890" not in masked
    assert "***" in masked


def test_api_key_values_are_masked():
    masked = mask_secrets("api_key=sk-verysecretvalue123 used for request")
    assert "sk-verysecretvalue123" not in masked


def test_plain_text_untouched():
    text = "generated github acme/rocket#42 -> github-acme-rocket-42"
    assert mask_secrets(text) == text
