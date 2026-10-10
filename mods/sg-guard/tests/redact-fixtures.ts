// Generated from redact-fixtures.json by tests/test_sg_guard_parity.py; edit the JSON, then run that test with SG_WRITE_FIXTURES=1.
export default [
 {
  "input": "Mail jean.dupont@example.fr now",
  "expected": "Mail [email] now"
 },
 {
  "input": "Call +33 1 23 45 67 89 please",
  "expected": "Call [phone] please"
 },
 {
  "input": "Card 4111 1111 1111 1111 ok",
  "expected": "Card [card] ok"
 },
 {
  "input": "Authorization: Bearer abcdefghijklmnop1234 end",
  "expected": "Authorization: Bearer [secret] end"
 },
 {
  "input": "api_key=ABCDEFGHIJKLMNOP12 and token: zzzzzzzzzzzzzzzzzzzz",
  "expected": "api_key=[secret] and token: [secret]"
 },
 {
  "input": "plain text with id 12345",
  "expected": "plain text with id 12345"
 },
 {
  "input": "client 42 owes 1200 EUR",
  "expected": "client 42 owes 1200 EUR"
 },
 {
  "input": "two a@b.io and c@d.org",
  "expected": "two [email] and [email]"
 },
 {
  "input": "secret \"s3cr3t-value-0123456789\"",
  "expected": "secret \"s3cr3t-value-[phone]\""
 },
 {
  "input": "order 2026-10-10 total 99.50",
  "expected": "order [phone] total 99.50"
 }
]
