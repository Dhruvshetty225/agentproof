"""AUTH001: deleted authentication/authorization checks."""

import pytest

from agentproof.diff_parser import ChangedLine, FileDiff
from agentproof.rules import auth
from agentproof.schema import Severity


def _deleted(content: str) -> list[FileDiff]:
    return [FileDiff(file_path="app/views.py", deleted_lines=[ChangedLine(10, content)])]


@pytest.mark.parametrize(
    "content",
    [
        # The four lines from the Phase 1 brief.
        "    if not user.is_authorized():",
        "@login_required",
        "    check_permission(user, 'admin')",
        "    verify_token(t)",
        # camelCase / PascalCase equivalents.
        "    if (!user.isAuthorized()) {",
        "@LoginRequired",
        "    checkPermission(user, \"admin\");",
        "    verifyToken(t);",
        # Every requested keyword family.
        "    authorize(request)",
        "    if not authenticate(username, password):",
        "    if not user.has_access(document):",
        "    if (!hasAccess(user, doc)) return;",
        "    if not user.is_admin:",
        "    if (!user.isAdmin()) throw new Forbidden();",
        "    for p in user.permissions:",
        "    csrfMiddleware.check(req)",
        # Security decorators, with and without arguments.
        "@require_role('admin')",
        "@require_role('admin', strict=True)",
        "@permission_required('blog.change_post', raise_exception=True)",
        "@csrf_protect",
        # Pre-existing detection that must keep working.
        "    if is_expired(token):",
        '        raise ValueError("reset token has expired")',
        "    if token.expires_at < now:",
        "    if expiry < now:",
        "    auth.check(request)",
        "    jwt.verify(signature, key)",
        # Common forms of the requested words.
        "    if not request.user.is_authenticated:",
        '    header = request.headers["Authorization"]',
    ],
)
def test_flags_deleted_security_check(content):
    findings = auth.check(_deleted(content))
    assert len(findings) == 1
    assert findings[0].rule_id == "AUTH001"
    assert findings[0].severity == Severity.HIGH
    assert findings[0].line_number == 10
    assert findings[0].evidence == content.strip()


@pytest.mark.parametrize(
    "content",
    [
        # Comment-only lines, even when they mention security words.
        "    # verify the token here",
        "    // check_permission(user) is handled upstream",
        "    /* is_authorized() moved to middleware */",
        "     * @login_required used to live here",
        "     */",
        # Unrelated names that merely contain a keyword as a substring.
        "    author = book.author",
        "    tokenizer = Tokenizer()",
        "    num_tokens = len(words)",
        "    next_page_token = response.next",
        "    authority = 'dns'",
        # Common words that only count as part of a security phrase.
        "    login_page = render('login.html')",
        "    role = user.role",
        "    admin_url = '/admin'",
        "    access_count += 1",
        # Non-security decorators.
        "@staticmethod",
        "@property",
        "@app.route('/admin')",
        "@pytest.fixture",
        "@functools.lru_cache(maxsize=128)",
        "@dataclass(frozen=True)",
    ],
)
def test_ignores_comments_unrelated_names_and_plain_decorators(content):
    assert auth.check(_deleted(content)) == []


def test_trailing_comment_does_not_hide_deleted_check():
    findings = auth.check(_deleted("    if not user.is_authorized():  # guard"))
    assert len(findings) == 1


def test_added_security_lines_are_not_flagged():
    file_diffs = [FileDiff(file_path="app/views.py", added_lines=[ChangedLine(3, "@login_required")])]
    assert auth.check(file_diffs) == []


def test_reports_each_flagged_line_with_its_own_location():
    file_diffs = [
        FileDiff(
            file_path="app/views.py",
            deleted_lines=[
                ChangedLine(4, "@login_required"),
                ChangedLine(5, "def dashboard(request):"),
                ChangedLine(6, "    check_permission(request.user, 'view')"),
            ],
        )
    ]
    findings = auth.check(file_diffs)
    assert [f.line_number for f in findings] == [4, 6]
