from llm_cli.apps.configure import mask_secrets


def test_mask_secrets_api_key():
    config = {"google": {"api_key": "1234567890abcdef"}, "other": "value"}
    masked = mask_secrets(config)
    assert masked["google"]["api_key"] == "...cdef"
    assert masked["other"] == "value"


def test_mask_secrets_github_pat_in_string():
    config = {
        "mcp_servers": [
            {
                "args": [
                    "run",
                    "GITHUB_TOKEN=github_pat_1234567890abcdefGHIKLMNOP",
                    "other_arg",
                ]
            }
        ]
    }
    masked = mask_secrets(config)
    # github_pat_ (11 chars) + ... + last 4 chars
    # github_pat_...MNOP
    val = masked["mcp_servers"][0]["args"][1]
    assert "github_pat_" in val
    assert "..." in val
    assert val.endswith("MNOP")
    assert "1234567890" not in val


def test_mask_secrets_recursive():
    config = {"nested": {"list": [{"api_key": "secret_key_123"}]}}
    masked = mask_secrets(config)
    assert masked["nested"]["list"][0]["api_key"] == "..._123"
