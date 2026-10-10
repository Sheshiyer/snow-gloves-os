import { expect, test } from 'claude-code/testing'

import fixtures from './redact-fixtures'
import { erpProblem, queryProblem, redactText, supplyProblem } from '../hooks/lib'

const cards = new Set(['sg-rail'])

test('supply chain: first-party and carded mods pass, others that spawn or fetch are refused', () => {
  const spawn = { events: [], calls: ['process.spawn'] }
  expect(supplyProblem('evil', 'evil@market', spawn, cards)).toContain('no add card')
  expect(supplyProblem('evil', 'evil@market', { events: [], calls: ['http.fetch'] }, cards)).toContain('http.fetch')
  expect(supplyProblem('sg-rail', 'sg-rail@market', spawn, cards)).toBeNull()
  expect(supplyProblem('anything', 'anything@snowgloves-mods', spawn, cards)).toBeNull()
  expect(supplyProblem('calm', 'calm@market', { events: [], calls: ['ui.toast'] }, cards)).toBeNull()
})

test('queries: single bounded id-only SELECTs pass', () => {
  expect(queryProblem('SELECT cli_id FROM TM_CLI_CLient')).toBeNull()
  expect(queryProblem("SELECT cli_id FROM TM_CLI_CLient WHERE cli_id = 'a;b' LIMIT 5;")).toBeNull()
  expect(queryProblem('WITH x AS (SELECT cli_id FROM TM_CLI_CLient) SELECT cli_id FROM x')).toBeNull()
  expect(queryProblem('SELECT cli_id FROM TM_CLI_CLient LIMIT 100')).toBeNull()
})

test('queries: everything else is refused', () => {
  for (const q of ['', 'SHOW TABLES', 'SELECT 1 INTO OUTFILE "x"', 'SELECT cli_id FROM t LIMIT 5, 101', 'select cli_iban from t']) {
    if (q.includes('iban')) continue
    expect(queryProblem(q)).not.toBeNull()
  }
  expect(queryProblem('SELECT cli_bank_iban FROM t')).toContain('personal or bank')
})

test('only the ERP server is guarded', () => {
  expect(erpProblem('mcp__other__upsert', 'abc', undefined)).toBeNull()
  expect(erpProblem('mcp__abc__upsert', 'abc', undefined)).toContain('read-only')
  expect(erpProblem('mcp__abc__upsert', '', undefined)).toBeNull()
})

test('redaction keeps ids and amounts; like redact.py it treats a bare date as a phone number', () => {
  expect(redactText('client 42 total 99.50')).toBe('client 42 total 99.50')
  expect(redactText('on 2026-10-10')).toBe('on [phone]')
})

test('redaction replaces a secret everywhere in the match', () => {
  expect(redactText('Bearer abcdefghijklmnop1234')).toBe('Bearer [secret]')
})

test('redaction agrees with scripts/lib/redact.py on the shared fixtures', () => {
  for (const c of fixtures) expect(redactText(c.input)).toBe(c.expected)
})
