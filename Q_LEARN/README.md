Run
---
pip install numpy
python run_stub.py

Key idea
--------
Q is a 2D array:
    Q[state_index, action_id]

Update is standard off-policy Q-learning:
    target = r + gamma * max_a' Q[s', a']
    td_error = target - Q[s, a]
    Q[s, a] += alpha * td_error
