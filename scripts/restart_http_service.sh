#!/bin/zsh

set -euo pipefail

LABEL="com.ryan.stock-analysis-api"

launchctl kickstart -k "gui/$(id -u)/$LABEL"
