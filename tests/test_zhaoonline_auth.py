from ai_agent.clients.zhaoonline import build_auth_token


def test_build_auth_token_matches_known_example():
    secret = "zhao123"
    ts = "1730707200000"
    # md5("zhao1231730707200000")
    expected = "0f8168a3ba42073a29c3c2e03678713d"
    assert build_auth_token(secret, ts) == expected
