# Local API test helpers. Load with: source scripts/dev-helpers.sh

API=http://localhost:8006/api
J='Content-Type: application/json'

token() {
  curl -s -X POST "$API/auth/token/" \
    -H "$J" \
    -d "{\"username\": \"$1\", \"password\": \"${2:-test-pass-123}\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['access'])"
}

login_all() {
  ACME=$(token acme); GLOBEX=$(token globex); INITECH=$(token initech)
  DANA=$(token dana); SAM=$(token sam); RIYA=$(token riya)
  echo "Tokens loaded (valid 15 min)."
}
# SQS queue depth: messages waiting / in flight. Usage: qdepth job-board-status
qdepth() { docker compose exec -T localstack sh -c "awslocal sqs get-queue-attributes --queue-url \"\$(awslocal sqs get-queue-url --queue-name $1 --query QueueUrl --output text)\" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query Attributes" 2>/dev/null | grep -v WARNING | tr -d '\n '; echo; }

# Wait until the API really answers (after up -d / restart / rebuild). Usage: waitapi
waitapi() { for i in $(seq 30); do curl -s -o /dev/null http://localhost:8006/healthz && { echo "api up after ${i}s"; return 0; }; sleep 1; done; echo "api NOT up after 30s: docker compose logs --tail=30 api"; return 1; }

# Grep the Prometheus metrics. Usage: m 'view="job-list"'
m() { curl -s http://localhost:8006/metrics | grep "$1"; }
