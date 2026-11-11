#!/bin/zsh
cd "$(dirname "$0")" || exit 1
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
open -a Docker
/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose --env-file .mysql.env stop mysql
