target='tests/test_stage8_qa_validation_evidence.py'
out='./test_stage8_qa_validation_evidence.py'

for a in \
  /home/bebebeka/Downloads/ai-it-team-accepted-report-ids-fix.tar \
  /home/bebebeka/Downloads/ai-it-team-llm-trust-boundary-fixes.tar \
  /home/bebebeka/Downloads/ai-it-team-publisher-no-checks-ready-files.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-flexible-team-lead.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-coder-qa-fix-v2.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-teamlead-scope-fix.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-teamlead-scope-flag-fix.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-p2-role-policy.tar.gz \
  /home/bebebeka/Downloads/ai-it-team-p2-1-pr-check-policy.tar.gz
do
  member="$(tar -tf "$a" | grep -E -m1 'stage8_qa_validation_evidence\.py' || true)"
  if [ -n "$member" ]; then
    echo "FOUND: $a -> $member"
    tar -xOf "$a" "$member" > "$out"
    echo "COPIED: $out"
    exit 0
  fi
done

echo "NOT FOUND: $target" >&2
