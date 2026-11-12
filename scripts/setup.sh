#!/usr/bin/env bash
# One-command setup for Browser MCP.
# Creates .venv, installs dependencies + Chromium, and installs the skill
# into any agent skills directory that exists (OpenCode, Claude Code).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Creating virtual environment (.venv)"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing browser-mcp (editable)"
pip install --quiet --upgrade pip
pip install --quiet -e .

echo "==> Installing Chromium for Playwright"
python -m playwright install chromium

VENV_BIN="$(pwd)/.venv/bin"
echo
echo "==> Installed. Binary: $VENV_BIN/browser-mcp"

# --- Install the skill into any agent that has a skills directory -----------
install_skill() {
  local dest_dir="$1"
  mkdir -p "$dest_dir"
  cp skills/browser-mcp/SKILL.md "$dest_dir/SKILL.md"
  echo "    skill → $dest_dir/SKILL.md"
}

echo "==> Installing skill into agent skill directories (if present)"
for base in "$HOME/.config/opencode/skills" "$HOME/.claude/skills" "$HOME/.agents/skills"; do
  if [ -d "$(dirname "$base")" ]; then
    install_skill "$base/browser-mcp"
  fi
done

# --- Print MCP registration snippets ----------------------------------------
cat <<EOF

==> Register the MCP server in your agent of choice:

OpenCode (~/.config/opencode/opencode.json):
    {
      "mcp": {
        "servers": {
          "browser": {
            "type": "local",
            "command": ["$VENV_BIN/browser-mcp"],
            "disabled": false
          }
        }
      }
    }

Claude Desktop (claude_desktop_config.json) or generic JSON MCP client:
    {
      "mcpServers": {
        "browser": {
          "command": "$VENV_BIN/browser-mcp"
        }
      }
    }

Claude Code:
    claude mcp add browser -- "$VENV_BIN/browser-mcp"

Cursor / VS Code (mcp.json):
    {
      "servers": {
        "browser": {
          "command": "$VENV_BIN/browser-mcp"
        }
      }
    }

If an agent can't find the skill, copy skills/browser-mcp/ to its skills directory
(e.g. ~/.claude/skills/browser-mcp/SKILL.md).

Verify: $VENV_BIN/browser-mcp --help
EOF
