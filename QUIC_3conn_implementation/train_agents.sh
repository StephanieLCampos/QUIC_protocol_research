#!/bin/bash
#
# Q-Learning Agent Training Script
# Trains Andy's, Default, and Hybrid Q-learning agents on multiple scenarios
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
    echo -e "${BLUE}   Starting Training${NC}"
    echo -e "${BLUE}============================================${NC}"

    # Clear Q-tables if requested (only at start, not between scenarios)
    if [[ "$2" == "--clear" ]]; then
        echo -e "${YELLOW}Clearing Q-tables...${NC}"
        rm -f results/q_learning_checkpoint_andy.json
        rm -f results/q_learning_checkpoint.json
        rm -f results/q_learning_checkpoint_hybrid.json
        echo -e "${GREEN}Q-tables cleared.${NC}"
        # NOTE: Don't export CLEAR_QTABLE here - we want learning to accumulate
        # across scenarios. The files are already deleted, so agents start fresh.
    fi

    # Ensure CLEAR_QTABLE is NOT set (so learning accumulates across scenarios)
    unset CLEAR_QTABLE

    # Build Docker image
    echo -e "\n${BLUE}Building Docker image...${NC}"
    docker compose build

    # ============================================
    # Train Andy's Agent
    # ============================================
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}   Training Andy's Agent${NC}"
    echo -e "${BLUE}============================================${NC}"

    echo -e "\n${YELLOW}[1/4] Training Andy on per_1 (1% loss) - 5 minutes${NC}"
    ML_AGENT=andy SCENARIO=per_1 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[2/4] Training Andy on per_5 (5% loss) - 5 minutes${NC}"
    ML_AGENT=andy SCENARIO=per_5 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[3/4] Training Andy on per_10 (10% loss) - 5 minutes${NC}"
    ML_AGENT=andy SCENARIO=per_10 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[4/4] Training Andy on varying scenario - 10 minutes${NC}"
    ML_AGENT=andy SCENARIO=varying DURATION=600 docker compose up

    echo -e "\n${GREEN}Andy's agent training complete!${NC}"

    # ============================================
    # Train Default Agent
    # ============================================
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}   Training Default Agent${NC}"
    echo -e "${BLUE}============================================${NC}"

    echo -e "\n${YELLOW}[1/4] Training Default on per_1 (1% loss) - 5 minutes${NC}"
    ML_AGENT=default SCENARIO=per_1 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[2/4] Training Default on per_5 (5% loss) - 5 minutes${NC}"
    ML_AGENT=default SCENARIO=per_5 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[3/4] Training Default on per_10 (10% loss) - 5 minutes${NC}"
    ML_AGENT=default SCENARIO=per_10 DURATION=300 docker compose up

    echo -e "\n${YELLOW}[4/4] Training Default on varying scenario - 10 minutes${NC}"
    ML_AGENT=default SCENARIO=varying DURATION=600 docker compose up

    echo -e "\n${GREEN}Default agent training complete!${NC}"

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
    echo -e "Q-table locations:"
    echo -e "  Andy's:   results/q_learning_checkpoint_andy.json"
    echo -e "  Default:  results/q_learning_checkpoint.json"
    echo -e "  Hybrid:   results/q_learning_checkpoint_hybrid.json"
    echo -e ""
    echo -e "Results saved in: results/<scenario>/run_<timestamp>/"
    echo -e ""
    echo -e "${GREEN}All three agents trained successfully!${NC}"
    echo -e ""
    echo -e "Press any key to close this tmux session, or run 'tmux detach' to keep it."
    read -n 1
    exit 0
fi

# Main entry point - ask questions and launch training
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   Q-Learning Agent Training Script${NC}"
echo -e "${BLUE}   (Andy + Default + Hybrid)${NC}"
echo -e "${BLUE}============================================${NC}"

# Ask if user wants to clear Q-tables
CLEAR_FLAG=""
read -p "Clear existing Q-tables before training? (y/n): " clear_tables
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
    tmux kill-session -t qlearning-training 2>/dev/null || true

    # Start new tmux session with training
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    tmux new-session -d -s qlearning-training "cd $(pwd) && $SCRIPT_PATH --run-training $CLEAR_FLAG"

    echo -e "\n${GREEN}Training started in tmux session!${NC}"
    echo -e ""
    echo -e "Session name: ${YELLOW}qlearning-training${NC}"
    echo -e ""
    echo -e "Commands:"
    echo -e "  ${YELLOW}tmux attach -t qlearning-training${NC}   # Connect to live session"
    echo -e "  ${YELLOW}Ctrl+B then D${NC}                       # Detach from session"
    echo -e "  ${YELLOW}tmux kill-session -t qlearning-training${NC}  # Stop training"
    echo -e ""
    echo -e "Estimated completion time: ${YELLOW}~75 minutes${NC} (3 agents)"
    exit 0
fi

# Run in foreground
echo -e "\n${BLUE}Running training in foreground...${NC}"
exec "$0" --run-training $CLEAR_FLAG
