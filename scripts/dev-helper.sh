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