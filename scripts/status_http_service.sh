#!/bin/zsh

set -euo pipefail

LABEL="com.ryan.stock-analysis-api"

launchctl print "gui/$(id -u)/$LABEL"
