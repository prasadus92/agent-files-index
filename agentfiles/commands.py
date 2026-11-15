"""Detect the shell commands a file tells the agent to run, and tag each with a kind."""
from __future__ import annotations

import re
from dataclasses import dataclass

SHELL_LANGS = {"", "bash", "sh", "shell", "zsh", "console", "terminal", "shell-session", "powershell", "ps1", "cmd", "fish"}
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
JS_PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
KIND_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("test", re.compile(r"\b(test|tests|pytest|jest|vitest|rspec|phpunit|ctest|spec|e2e|playwright|unittest)\b")),
    ("lint", re.compile(r"\b(lint|eslint|ruff|flake8|clippy|golangci-lint|rubocop|biome|stylelint|pylint|shellcheck)\b")),
    ("format", re.compile(r"\b(fmt|format|prettier|black|gofmt|isort|rustfmt)\b")),
    ("typecheck", re.compile(r"\b(typecheck|type-check|tsc|mypy|pyright|check-types)\b")),
    ("build", re.compile(r"\b(build|compile|assemble|bundle|package|make)\b")),
    ("install", re.compile(r"\b(install|sync|setup|bootstrap|ci)\b")),
)
RUN_RE = re.compile(r"\b(run dev|dev\b|start|serve|run\b)")
PROMPT_RE = re.compile(r"^(?:\$|>|%)\s*")
SEGMENT_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;)\s*")
NAVIGATION_HEADS = {"cd", "export"}
VCS_HEADS = {"git", "gh"}


@dataclass(frozen=True)
class Command:
    text: str
    head: str
    kinds: tuple[str, ...]
    negated: bool = False


def classify(command: str, head: str = "") -> tuple[str, ...]:
    if head in VCS_HEADS:
        return ("vcs",)
    low = command.lower()
    kinds = tuple(name for name, rx in KIND_PATTERNS if rx.search(low))
    if kinds:
        return kinds
    return ("run",) if RUN_RE.search(low) else ("other",)


def command_head(line: str) -> str | None:
    line = re.sub(r"^(?:\$|>|%|#\s*\$)\s*", "", line.strip())
    if not line or line.startswith("#"):
        return None
    line = re.sub(r"^(?:sudo|env\s+\S+=\S+|[A-Z_]+=\S+)\s+", "", line)
    words = line.split()
    head = words[0] if words else ""
    return head if head in COMMAND_HEADS or (head.startswith("./") and len(head) > 2) else None


def parse_command(raw: str, negated: bool = False) -> Command | None:
    """`cd web && pnpm test` counts as a pnpm command: the first real tool in a chain sets the head."""
    heads = (command_head(segment) for segment in SEGMENT_SPLIT_RE.split(raw.strip()))
    head = next((h for h in heads if h and h not in NAVIGATION_HEADS), None)
    if not head:
        return None
    text = re.sub(r"\s+#.*$", "", PROMPT_RE.sub("", raw.strip()))
    return Command(text, head, classify(text, head), negated)
