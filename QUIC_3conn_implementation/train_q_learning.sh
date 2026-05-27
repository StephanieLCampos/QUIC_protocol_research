#!/bin/bash
# train_q_learning.sh - Batch train Q-learning across 5 main scenarios

SCENARIOS=(
    "stable_high"
    "congested_low"
    "varying"
    "lossy"
    "asymmetric"
)

DURATION=${DURATION:-300}              # 5 minutes per session (override with DURATION=X)
SESSIONS_PER_SCENARIO=${SESSIONS:-3}   # 3 sessions each (override with SESSIONS=X)

# Clear old Q-table (required after state space change)
echo "Clearing old Q-table checkpoint..."
rm -f output/q_learning_checkpoint.json

echo ""
echo "=========================================="
echo "Q-Learning Batch Training"
echo "=========================================="
echo "Scenarios: ${SCENARIOS[*]}"
echo "Sessions per scenario: $SESSIONS_PER_SCENARIO"
echo "Duration per session: ${DURATION}s"
TOTAL_TIME=$(( ${#SCENARIOS[@]} * SESSIONS_PER_SCENARIO * DURATION / 60 ))
echo "Total estimated time: ${TOTAL_TIME} minutes"
echo "=========================================="
echo ""

SESSION_COUNT=0
TOTAL_SESSIONS=$(( ${#SCENARIOS[@]} * SESSIONS_PER_SCENARIO ))

for scenario in "${SCENARIOS[@]}"; do
    echo ""
    echo "=========================================="
    echo "Scenario: $scenario"
    echo "=========================================="

    for i in $(seq 1 $SESSIONS_PER_SCENARIO); do
        SESSION_COUNT=$((SESSION_COUNT + 1))
        echo ""
        echo "--- Session $SESSION_COUNT/$TOTAL_SESSIONS: $scenario ($i/$SESSIONS_PER_SCENARIO) ---"

        DURATION=$DURATION SCENARIO=$scenario docker-compose up --abort-on-container-exit
        docker-compose down

        # Brief pause between sessions
        sleep 3
    done
done

echo ""
echo "=========================================="
echo "Training Complete!"
echo "=========================================="
echo "Q-table saved to: output/q_learning_checkpoint.json"
echo ""

# Show Q-table stats
if [ -f output/q_learning_checkpoint.json ]; then
    echo "Q-table statistics:"
    python3 -c "
import json
with open('output/q_learning_checkpoint.json') as f:
    data = json.load(f)
print(f'  States visited: {len(data[\"q\"])} / 6912')
print(f'  Steps taken: {data[\"step_count\"]}')
print(f'  Final epsilon: {data[\"epsilon\"]:.3f}')
"
fi
