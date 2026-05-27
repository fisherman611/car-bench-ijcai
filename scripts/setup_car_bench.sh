#!/usr/bin/env bash
# Clone the external CAR-bench repository required by the evaluator.
#
# Windows cannot check out some upstream result files because their names contain
# ":" characters. We do not need those benchmark result artifacts for running the
# evaluator, so this script uses sparse checkout and skips the results/ tree.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CAR_BENCH_DIR="$PROJECT_ROOT/third_party/car-bench"
CAR_BENCH_REPO="https://github.com/CAR-bench/car-bench.git"
CAR_BENCH_SAFE_DIR="$CAR_BENCH_DIR"

if command -v cygpath >/dev/null 2>&1; then
    CAR_BENCH_SAFE_DIR="$(cygpath -w "$CAR_BENCH_DIR" | sed 's#\\#/#g')"
fi

car_bench_git() {
    git -c "safe.directory=$CAR_BENCH_SAFE_DIR" -c core.protectNTFS=false -C "$CAR_BENCH_DIR" "$@"
}

checkout_car_bench() {
    car_bench_git sparse-checkout init --cone
    car_bench_git sparse-checkout set car_bench docs templates
    car_bench_git checkout -f HEAD
}

if [ -d "$CAR_BENCH_DIR/.git" ]; then
    echo "car-bench repository already exists at $CAR_BENCH_DIR"
    echo "Repairing/updating sparse checkout for Windows..."
    checkout_car_bench
elif [ -e "$CAR_BENCH_DIR" ]; then
    echo "Error: $CAR_BENCH_DIR exists but is not a git repository."
    echo "Please remove or rename it, then run this script again."
    exit 1
else
    mkdir -p "$(dirname "$CAR_BENCH_DIR")"

    echo "Cloning car-bench repository..."
    git clone --depth 1 --sparse "$CAR_BENCH_REPO" "$CAR_BENCH_DIR"
    checkout_car_bench
fi

echo ""
echo "Setup complete. car-bench is ready at:"
echo "   $CAR_BENCH_DIR"
echo ""
echo "Note: results/ is skipped because it contains filenames that Windows cannot check out."
echo "Tasks and mock data are automatically loaded from HuggingFace."
echo ""
echo "Next steps:"
echo "   1. Install dependencies: uv sync --extra car-bench-agent --extra car-bench-evaluator"
echo "   2. Run the scenario: uv run car-bench-run scenarios/agent_under_test/local.toml --show-logs"
