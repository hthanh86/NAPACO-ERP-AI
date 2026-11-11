#!/bin/zsh
cd "$(dirname "$0")" || exit 1
python3 scripts/configure_google.py
result=$?
if [[ $result -ne 0 ]]; then
  read -r "?Nhấn Enter để đóng…"
fi
exit $result
