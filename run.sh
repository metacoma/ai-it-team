openhands-graph-run \
  --workflow team-lead \
  --endpoint http://localhost:3000 \
  --model qwen36-35b \
  --team-lead-base-url http://127.0.0.1:4000/v1 \
  --team-lead-model qwen36-35b \
  --team-lead-api-key sk-local \
  --max-team-lead-steps 42 \
  --ui rich \
  --ui-prompt-chars 12000 \
  --ui-answer-chars 16000 \
  --prompt "
hello
"
