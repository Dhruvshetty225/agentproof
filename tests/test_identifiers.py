import pytest

from agentproof.identifiers import (
    contains_phrase,
    ends_with_phrase,
    identifier_words,
    identifiers_in,
)


@pytest.mark.parametrize(
    "identifier, expected",
    [
        ("check_permission", ["check", "permission"]),
        ("isAuthorized", ["is", "authorized"]),
        ("IsAuthorized", ["is", "authorized"]),
        ("CSRFToken", ["csrf", "token"]),
        ("getHTTPResponse", ["get", "http", "response"]),
        ("DB_PASSWORD", ["db", "password"]),
        ("x-api-key", ["x", "api", "key"]),
        ("sha256Hash", ["sha256", "hash"]),
        ("__init__", ["init"]),
        ("token", ["token"]),
        ("author", ["author"]),
    ],
)
def test_identifier_words_splits_naming_styles(identifier, expected):
    assert identifier_words(identifier) == expected


def test_identifiers_in_finds_names_but_not_punctuation_or_numbers():
    text = "if not user.is_authorized(token, 42): raise Denied('x-y')"
    assert identifiers_in(text) == [
        "if",
        "not",
        "user",
        "is_authorized",
        "token",
        "raise",
        "Denied",
        "x",
        "y",
    ]


def test_contains_phrase_requires_consecutive_words():
    assert contains_phrase(["login", "required"], ("login", "required"))
    assert contains_phrase(["user", "is", "admin", "flag"], ("is", "admin"))
    assert not contains_phrase(["required", "login"], ("login", "required"))
    assert not contains_phrase(["is", "super", "admin"], ("is", "admin"))
    assert not contains_phrase(["login"], ("login", "required"))


def test_ends_with_phrase_only_matches_the_final_words():
    assert ends_with_phrase(["db", "password"], ("password",))
    assert ends_with_phrase(["x", "api", "key"], ("api", "key"))
    assert not ends_with_phrase(["password", "hash"], ("password",))
    assert not ends_with_phrase(["key"], ("api", "key"))
