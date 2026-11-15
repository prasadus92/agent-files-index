"""Parse an agent instruction file into structural features. Stdlib only."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
URL_RE = re.compile(r"https?://[^\s)>\]\"'`]+")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
IMPORT_RE = re.compile(r"(?:^|\s)@((?:\.{0,2}/|~/)?[\w.\-/]+\.\w+)")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
PATHLIKE_RE = re.compile(r"^(?:\./)?(?:[\w.\-]+/)+[\w.\-]*$|^[\w.\-]+\.(?:md|ts|tsx|js|jsx|py|go|rs|java|kt|toml|json|ya?ml|sh|rb|cs|cpp|h|swift|sql|lock|cfg|ini|txt)$")

SHELL_LANGS = {"", "bash", "sh", "shell", "zsh", "console", "terminal", "shell-session", "powershell", "ps1", "cmd", "fish"}

# First token (or first two) of a shell command line that we count as a command.
COMMAND_HEADS = {
    "npm", "pnpm", "yarn", "bun", "bunx", "npx", "node", "deno", "tsc", "eslint", "prettier", "biome", "jest", "vitest",
    "playwright", "make", "cmake", "ninja", "bazel", "bazelisk", "buck2", "just", "task", "cargo", "rustup", "go",
    "gofmt", "golangci-lint", "python", "python3", "pip", "pip3", "uv", "uvx", "poetry", "pdm", "hatch", "pytest",
    "tox", "nox", "ruff", "black", "mypy", "pyright", "flake8", "isort", "pre-commit", "gradle", "./gradlew", "gradlew",
    "mvn", "./mvnw", "mvnw", "sbt", "dotnet", "msbuild", "swift", "xcodebuild", "pod", "flutter", "dart", "mix",
    "elixir", "iex", "bundle", "rake", "rails", "rspec", "rubocop", "gem", "php", "composer", "phpunit", "docker",
    "docker-compose", "kubectl", "helm", "terraform", "git", "gh", "nx", "turbo", "lerna", "rush", "pixi", "conda",
    "mamba", "stack", "cabal", "ghc", "zig", "clang", "gcc", "ctest", "meson", "scons", "lua", "luarocks", "R",
    "Rscript", "julia", "nix", "devbox", "mise", "asdf", "tsx", "ts-node", "vite", "next", "expo", "ng", "dune",
    "opam", "sbcl", "clojure", "lein", "./scripts", "scripts", "bin", "./bin", "sh", "bash", "hugo", "jekyll",
}

TEST_WORDS = re.compile(r"\b(test|tests|pytest|jest|vitest|rspec|phpunit|ctest|spec|e2e|playwright|unittest|check)\b")
LINT_WORDS = re.compile(r"\b(lint|eslint|ruff|flake8|clippy|golangci-lint|rubocop|biome|stylelint|pylint|shellcheck)\b")
FORMAT_WORDS = re.compile(r"\b(fmt|format|prettier|black|gofmt|isort|rustfmt)\b")
TYPE_WORDS = re.compile(r"\b(typecheck|type-check|tsc|mypy|pyright|check-types)\b")
BUILD_WORDS = re.compile(r"\b(build|compile|assemble|bundle|package|make)\b")
INSTALL_WORDS = re.compile(r"\b(install|sync|setup|bootstrap|ci)\b")

PACKAGE_MANAGERS = {"npm": "npm", "pnpm": "pnpm", "yarn": "yarn", "bun": "bun"}

# Normalised section categories; matched against lower-cased heading text.
SECTION_CATEGORIES: dict[str, re.Pattern] = {
    "overview": re.compile(r"overview|about|introduction|project (?:description|summary|context)|what is|purpose|summary"),
    "setup": re.compile(r"setup|set up|install|getting started|prerequisite|quick ?start|environment|requirements|dev(?:elopment)? env"),
    "commands": re.compile(r"command|scripts|usage|how to run|running|workflow"),
    "build": re.compile(r"\bbuild"),
    "testing": re.compile(r"test|verification|validat|qa\b"),
    "lint_format": re.compile(r"lint|format|style check"),
    "architecture": re.compile(r"architecture|structure|layout|organi[sz]ation|modules|components|directory|directories|codebase|repo(?:sitory)? map|key files|tech stack|stack"),
    "code_style": re.compile(r"code style|coding|convention|style guide|guidelines|best practice|patterns|naming|standards"),
    "git_pr": re.compile(r"\bgit\b|commit|pull request|\bprs?\b|branch|review|contribut|changelog|release"),
    "security": re.compile(r"security|secret|credential|permission|safety|sensitive"),
    "deployment": re.compile(r"deploy|ci\b|ci/cd|continuous|pipeline|infra"),
    "config": re.compile(r"config|configuration|env(?:ironment)? var|settings|\.env"),
    "documentation": re.compile(r"documentation|docs\b|docstring|comments"),
    "dependencies": re.compile(r"dependenc|packages|librar"),
    "troubleshooting": re.compile(r"troubleshoot|debug|common (?:issues|problems|pitfalls)|gotcha|known issues|faq|pitfall"),
    "boundaries": re.compile(r"do not|don't|never|avoid|boundar|restriction|constraint|rules|important|critical|must"),
    "agent_workflow": re.compile(r"agent|ai\b|assistant|claude|codex|copilot|llm|workflow|when (?:you|working)|task"),
}

MUST_RE = re.compile(r"\b(must|always|required|mandatory|shall)\b", re.I)
NEVER_RE = re.compile(r"\b(never|do not|don't|must not|mustn't|should not|shouldn't|avoid|forbidden|prohibited)\b", re.I)
EMPHASIS_RE = re.compile(r"\b(IMPORTANT|CRITICAL|MUST|NEVER|ALWAYS|YOU MUST)\b")
TESTS_MENTION_RE = re.compile(r"\b(tests?|testing|unit test|integration test|test suite|coverage)\b", re.I)
CI_MENTION_RE = re.compile(r"\b(CI|CI/CD|github actions|\.github/workflows|continuous integration|pipeline|pre-commit)\b")
SECURITY_MENTION_RE = re.compile(r"\b(security|secrets?|credentials?|api keys?|tokens?|\.env|vulnerab\w*|sanitiz\w*|injection)\b", re.I)
VAGUE_RE = re.compile(
    r"\b(write (?:clean|good|high[- ]quality|readable|maintainable) code|follow best practices|use best practices|"
    r"be careful|make sure (?:everything|it) works|keep (?:the )?code clean|use common sense)\b", re.I)
HOME_PATH_RE = re.compile(r"(?:/Users/[A-Za-z0-9._-]+/|/home/(?!user/|username/|runner/|<)[A-Za-z0-9._-]+/|C:\\\\Users\\\\[A-Za-z0-9._-]+)")

# Secret-like patterns. Only names and counts ever leave the parser; matched values are never stored.
SECRET_PATTERNS: dict[str, re.Pattern] = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "stripe_live_key": re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "credential_assignment": re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']([A-Za-z0-9/+_\-!@#$%^&*]{12,})[\"']"),
    "connection_string_with_password": re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:([^\s@/]{6,})@"),
}
PLACEHOLDER_RE = re.compile(
    r"(?i)x{4,}|\*{3,}|\.{3}|<[^>]+>|\$\{?[A-Z_]+|your|example|placeholder|changeme|dummy|test|fake|sample|redacted|"
    r"secret_here|0{8,}|1234|abcd|password123|\{\{")

INJECTION_RE = re.compile(
    r"(?i)\b(?:ignore|disregard|forget) (?:all |any )?(?:of )?(?:the |your )?(?:previous|prior|above|earlier) instructions\b|"
    r"\bhide (?:this|it|these) from the user\b|"
    r"\b(?:do not|don't|never) (?:reveal|disclose|mention) (?:this|these instructions|this file|that you) to the user\b")
PIPE_SHELL_RE = re.compile(r"(?i)\b(?:curl|wget)\b[^\n|`]*https?://[^\n|`]*\|\s*(?:sudo\s+)?(?:ba|z)?sh(?:\s+-s\b|\s*(?:$|[`'\";)]))", re.M)
QUOTED_SPAN_RE = re.compile(r"\"[^\"\n]{0,200}\"|“[^”\n]{0,200}”|`[^`\n]{0,200}`")


@dataclass
class Command:
    text: str
    head: str
    kinds: list[str]


@dataclass
class Features:
    bytes: int = 0
    lines: int = 0
    nonblank_lines: int = 0
    words: int = 0
    est_tokens: int = 0
    headings: list[tuple[int, str]] = field(default_factory=list)
    section_categories: set[str] = field(default_factory=set)
    n_code_blocks: int = 0
    n_bullets: int = 0
    commands: list[Command] = field(default_factory=list)
    n_must: int = 0
    n_never: int = 0
    n_emphasis_caps: int = 0
    mentions_tests: bool = False
    mentions_ci: bool = False
    mentions_security: bool = False
    urls: list[str] = field(default_factory=list)
    relative_links: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    inline_paths: list[str] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    package_managers: set[str] = field(default_factory=set)
    vague_phrases: int = 0
    home_paths: int = 0
    secret_hits: dict[str, int] = field(default_factory=dict)
    injection_hits: int = 0
    pipe_shell_hits: int = 0
    frontmatter: dict[str, str] | None = None
    frontmatter_error: str | None = None
    body_lines: int = 0

    def command_kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.commands:
            for k in c.kinds:
                out[k] = out.get(k, 0) + 1
        return out


def normalise_heading(text: str) -> str:
    text = re.sub(r"[`*_~\[\]()]", "", text)
    text = re.sub(r"^[\W\d.]+", "", text)  # leading emoji, numbering, punctuation
    return re.sub(r"\s+", " ", text).strip().lower()


def classify_heading(norm: str) -> set[str]:
    return {k for k, rx in SECTION_CATEGORIES.items() if rx.search(norm)}


def classify_command(cmd: str) -> list[str]:
    kinds = []
    low = cmd.lower()
    for name, rx in (("test", TEST_WORDS), ("lint", LINT_WORDS), ("format", FORMAT_WORDS),
                     ("typecheck", TYPE_WORDS), ("build", BUILD_WORDS), ("install", INSTALL_WORDS)):
        if rx.search(low):
            kinds.append(name)
    if re.search(r"\b(run dev|dev\b|start|serve|run\b)", low) and not kinds:
        kinds.append("run")
    return kinds or ["other"]


def _command_head(line: str) -> str | None:
    line = line.strip()
    line = re.sub(r"^(?:\$|>|%|#\s*\$)\s*", "", line)
    if not line or line.startswith("#"):
        return None
    line = re.sub(r"^(?:sudo|env\s+\S+=\S+|[A-Z_]+=\S+)\s+", "", line)
    head = line.split()[0] if line.split() else ""
    if head in COMMAND_HEADS or head.startswith("./") and len(head) > 2:
        return head
    return None


def _parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str | None, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, None, text
    fm: dict[str, str] = {}
    key = None
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if km and not raw.startswith((" ", "\t")):
            key = km.group(1)
            val = km.group(2).strip()
            if val in (">", "|", ">-", "|-"):
                val = ""
            fm[key] = val.strip("\"'")
        elif key and raw.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + raw.strip()).strip()
        else:
            return fm, f"unparsed frontmatter line: {raw[:40]!r}", text[m.end():]
    return fm, None, text[m.end():]


def parse(text: str) -> Features:
    f = Features()
    f.bytes = len(text.encode("utf-8"))
    lines = text.splitlines()
    f.lines = len(lines)
    f.nonblank_lines = sum(1 for ln in lines if ln.strip())
    f.words = len(re.findall(r"\S+", text))
    f.est_tokens = round(len(text) / 4)
    f.frontmatter, f.frontmatter_error, body = _parse_frontmatter(text)
    f.body_lines = len(body.splitlines())

    in_fence, fence_lang, fence_mark = False, "", ""
    seen_cmds: set[str] = set()

    def add_cmd(raw: str) -> None:
        segments = re.split(r"\s*(?:&&|\|\||;)\s*", raw.strip())
        head = next((h for h in map(_command_head, segments) if h and h not in ("cd", "export")), None)
        if not head:
            return
        cmd = re.sub(r"^(?:\$|>|%)\s*", "", raw.strip())
        cmd = re.sub(r"\s+#.*$", "", cmd)
        if cmd in seen_cmds:
            return
        seen_cmds.add(cmd)
        f.commands.append(Command(cmd, head, classify_command(cmd)))
        if head in PACKAGE_MANAGERS and len(cmd.split()) > 1:
            f.package_managers.add(head)

    for ln in lines:
        fm = FENCE_RE.match(ln)
        if fm:
            if not in_fence:
                in_fence, fence_lang, fence_mark = True, fm.group(2).lower(), fm.group(1)[0]
                f.n_code_blocks += 1
            elif fm.group(1)[0] == fence_mark:
                in_fence = False
            continue
        if in_fence:
            if fence_lang in SHELL_LANGS:
                add_cmd(ln)
            continue
        hm = HEADING_RE.match(ln)
        if hm:
            norm = normalise_heading(hm.group(2))
            if norm:
                f.headings.append((len(hm.group(1)), norm))
                f.section_categories |= classify_heading(norm)
            continue
        if BULLET_RE.match(ln):
            f.n_bullets += 1
        for code in INLINE_CODE_RE.findall(ln):
            add_cmd(code)
            c = code.strip().rstrip(".,:;")
            if PATHLIKE_RE.match(c) and "://" not in c and not c.startswith(("/", "~")) and "*" not in c:
                f.inline_paths.append(c[2:] if c.startswith("./") else c)
        for link in MD_LINK_RE.findall(ln):
            if not re.match(r"^(?:[a-z]+:|#|/)", link):
                f.relative_links.append(link.split("#")[0])
        for imp in IMPORT_RE.findall(ln):
            if "@" + imp in ln and not re.search(r"[\w.]@" + re.escape(imp), ln):
                f.imports.append(imp)

    prose = "\n".join(ln for ln in lines)
    outside_code = "\n".join(_outside_fences(lines))
    f.n_must = len(MUST_RE.findall(prose))
    f.n_never = len(NEVER_RE.findall(prose))
    f.n_emphasis_caps = len(EMPHASIS_RE.findall(prose))
    f.mentions_tests = bool(TESTS_MENTION_RE.search(prose))
    f.mentions_ci = bool(CI_MENTION_RE.search(prose))
    f.mentions_security = bool(SECURITY_MENTION_RE.search(prose))
    f.urls = URL_RE.findall(prose)
    f.vague_phrases = len(VAGUE_RE.findall(prose))
    f.home_paths = len(HOME_PATH_RE.findall(prose))
    f.injection_hits = count_unquoted(INJECTION_RE, outside_code)
    f.pipe_shell_hits = len(PIPE_SHELL_RE.findall(prose))
    f.secret_hits = scan_secrets(prose)
    f.relative_links = sorted(set(p for p in f.relative_links if p))
    f.inline_paths = sorted(set(f.inline_paths))
    f.referenced_paths = sorted(set(f.inline_paths) | set(f.relative_links))
    return f


def _outside_fences(lines: list[str]) -> list[str]:
    out, in_fence = [], False
    for ln in lines:
        if FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(ln)
    return out


def count_unquoted(rx: re.Pattern, text: str) -> int:
    """Count matches that are not inside a quoted or backticked span (quotes usually mean the text is discussed, not issued)."""
    spans = [m.span() for m in QUOTED_SPAN_RE.finditer(text)]
    return sum(1 for m in rx.finditer(text) if not any(a <= m.start() and m.end() <= b for a, b in spans))


LOCAL_HOST_RE = re.compile(r"@(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal|db|postgres|mysql|redis|mongo|database)\b", re.I)
DEV_PASSWORD_RE = re.compile(r"(?i)^(?:password|passwd|postgres|secret|dev|devpass|test|guest|admin|root|pass|changeme|example)\w{0,4}$")
GENERIC_PATTERNS = {"credential_assignment", "connection_string_with_password"}


def entropy(s: str) -> float:
    """Shannon entropy in bits per character."""
    import math
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def scan_secrets_raw(text: str) -> dict[str, int]:
    """What a naive regex scanner would report: every pattern match, no filtering."""
    hits: dict[str, int] = {}
    for name, rx in SECRET_PATTERNS.items():
        n = len(rx.findall(text))
        if n:
            hits[name] = n
    return hits


def scan_secrets(text: str) -> dict[str, int]:
    """Count secret-like strings by pattern, skipping placeholders, local dev credentials and low-entropy values.

    Never returns the values.
    """
    hits: dict[str, int] = {}
    for name, rx in SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            value = m.group(m.lastindex) if m.lastindex else m.group(0)
            context = text[max(0, m.start() - 20):m.end() + 20]
            if PLACEHOLDER_RE.search(value):
                continue
            if name in GENERIC_PATTERNS:
                if PLACEHOLDER_RE.search(context) or DEV_PASSWORD_RE.match(value):
                    continue
                if name == "connection_string_with_password" and LOCAL_HOST_RE.search(text[m.start():m.end() + 40]):
                    continue
                if len(value) < 16 or entropy(value) < 3.5:
                    continue
            if name == "private_key_block" and not re.search(r"[A-Za-z0-9+/]{40,}", text[m.end():m.end() + 300]):
                continue
            if name == "jwt" and _example_jwt(value):
                continue
            hits[name] = hits.get(name, 0) + 1
    return hits


def _example_jwt(token: str) -> bool:
    """The jwt.io sample and tokens whose payload names an obvious test subject."""
    import base64
    try:
        part = token.split(".")[1]
        payload = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8", "replace")
    except (IndexError, ValueError):
        return False
    return bool(re.search(r"(?i)john doe|1234567890|example|test|demo|\"sub\":\s*\"(?:user|123)", payload))
