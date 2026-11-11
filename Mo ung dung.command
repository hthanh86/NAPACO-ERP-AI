#!/bin/zsh
cd "$(dirname "$0")" || exit 1
python3 scripts/manage.py start
result=$?
if [[ $result -ne 0 ]]; then
  echo "Có lỗi. Vui lòng giữ cửa sổ này để kiểm tra."
  read -r "?Nhấn Enter để đóng…"
fi
exit $result
