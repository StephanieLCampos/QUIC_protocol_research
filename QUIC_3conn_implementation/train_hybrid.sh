#!/bin/bash
#
# Hybrid Q-Learning Agent Training Script
# Trains the hybrid (10-feature) agent on multiple scenarios
#

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running inside tmux session (called by ourselves)
if [[ "$1" == "--run-training" ]]; then
    # Actually run the training
    set -e

    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}   Hybrid Agent Training${NC}"
    echo -e "${BLUE}============================================${NC}"

    # Clear Q-table if requested (only at start, not between scenarios)
    if [[ "$2" == "--clear" ]]; then
        echo -e "${YELLOW}Clearing Hybrid Q-table...${NC}"
        rm -f results/q_learning_checkpoint_hybrid.json
        echo -e "${GREEN}Q-table cleared.${NC}"
    fi

    # Ensure CLEAR_QTABLE is NOT set (so learning accumulates across scenarios)
    unset CLEAR_QTABLE

    # Build Docker image
    echo -e "\n${BLUE}Building Docker image...${NC}"
    docker compose build

    # ============================================
    # Train Hybrid Agent
    # ============================================
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}   Training Hybrid Agent (10-feature)${NC}"
    echo -e "${BLUE}============================================${NC}"

    echo -e "\n${YELLOW}[1/4] Training Hybrid on per_1 (1% loss) - 5 minutes${NC}"
    ML_AGENT=hybrid SCENARIO=per_1 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[2/4] Training Hybrid on per_5 (5% loss) - 5 minutes${NC}"
    ML_AGENT=hybrid SCENARIO=per_5 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[3/4] Training Hybrid on per_10 (10% loss) - 5 minutes${NC}"
    ML_AGENT=hybrid SCENARIO=per_10 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[4/4] Training Hybrid on varying scenario - 10 minutes${NC}"
    ML_AGENT=hybrid SCENARIO=varying DURATION=600 docker compose up

    echo -e "\n${GREEN}Hybrid agent training complete!${NC}"

    # ============================================
    # Summary
    # ============================================
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}   Training Complete!${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo -e ""
    echo -e "Q-table location:"
    echo -e "  Hybrid:  results/q_learning_checkpoint_hybrid.json"
    echo -e ""
    echo -e "Results saved in: results/<scenario>/run_<timestamp>/"
    echo -e ""

    # Show Q-table stats
    if [ -f results/q_learning_checkpoint_hybrid.json ]; then
        echo -e "${BLUE}Q-table statistics:${NC}"
        python3 -c "
import json
with open('results/q_learning_checkpoint_hybrid.json') as f:
    data = json.load(f)
print(f'  States visited: {len(data[\"q\"])} / 995,328')
print(f'  Steps taken: {data[\"step_count\"]}')
print(f'  Final epsilon: {data[\"epsilon\"]:.3f}')
"
    fi

    echo -e ""
    echo -e "${GREEN}Hybrid agent trained successfully!${NC}"
    echo -e ""
    echo -e "Press any key to close this tmux session, or run 'tmux detach' to keep it."
    read -n 1
    exit 0
fi

# Main entry point - ask questions and launch training
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   Hybrid Q-Learning Agent Training${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e ""
echo -e "Agent: Hybrid (10-feature state)"
echo -e "State space: 995,328 states"
echo -e "Scenarios: per_1, per_5, per_10, varying"
echo -e "Total time: ~25 minutes"
echo -e ""

# Ask if user wants to clear Q-tables
CLEAR_FLAG=""
read -p "Clear existing Q-table before training? (y/n): " clear_tables
if [[ "$clear_tables" == "y" || "$clear_tables" == "Y" ]]; then
    CLEAR_FLAG="--clear"
fi

# Ask if user wants to run in background
read -p "Run training in background (tmux)? (y/n): " run_background

if [[ "$run_background" == "y" || "$run_background" == "Y" ]]; then
    # Check if tmux is installed
    if ! command -v tmux &> /dev/null; then
        echo -e "${RED}Error: tmux is not installed.${NC}"
        echo "Install with: brew install tmux"
        exit 1
    fi

    # Kill existing training session if exists
    tmux kill-session -t hybrid-training 2>/dev/null || true

    # Start new tmux session with training
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    tmux new-session -d -s hybrid-training "cd $(pwd) && $SCRIPT_PATH --run-training $CLEAR_FLAG"

    echo -e "\n${GREEN}Training started in tmux session!${NC}"
    echo -e ""
    echo -e "Session name: ${YELLOW}hybrid-training${NC}"
    echo -e ""
    echo -e "Commands:"
    echo -e "  ${YELLOW}tmux attach -t hybrid-training${NC}        # Connect to live session"
    echo -e "  ${YELLOW}Ctrl+B then D${NC}                         # Detach from session"
    echo -e "  ${YELLOW}tmux kill-session -t hybrid-training${NC}  # Stop training"
    echo -e ""
    echo -e "Estimated completion time: ${YELLOW}~25 minutes${NC}"
    exit 0
fi

# Run in foreground
echo -e "\n${BLUE}Running training in foreground...${NC}"
exec "$0" --run-training $CLEAR_FLAG
