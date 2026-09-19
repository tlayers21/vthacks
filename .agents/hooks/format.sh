#!/usr/bin/env bash

input=$(cat)
f=$(echo "$input" | jq -r '.tool_input.file_path // empty')

if [[ "$f" == *.py ]]; then
  uv run ruff format "$f" >/dev/null 2>&1
fi

exit 0
