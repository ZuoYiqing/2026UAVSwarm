#!/usr/bin/env bash
set -euo pipefail
R="$(cd "$(dirname "$0")/../../.."&&pwd)"; C="${PX4_GAZEBO_HARNESS_CONFIG:-$R/simulation/px4_gazebo/config/three_uav_sitl.json}"
X=(); [[ "${1:---gui}" == --headless ]] && X=(--headless)
exec python3 "$R/simulation/px4_gazebo/scripts/manage.py" start --config "$C" "${X[@]}"
