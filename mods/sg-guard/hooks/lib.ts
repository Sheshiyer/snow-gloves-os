// Pure rules for sg-guard. No $ in this file, so the tests and the Python parity check call it directly.
// The ERP rules port scripts/lib/erp_reader.py validate_query and scripts/hooks/erp-read-only.py;
// the redaction ports scripts/lib/redact.py. tests/redact-fixtures.json holds the cases both languages must agree on.

export const READ_TOOL = 'execute_read_only_query'
export const HARD_CAP = 100
export const NEVER_TABLES = ['TM_MAK_Mcp_Api_Key', 'TR_BAC_Bank_Account']
export const NEVER_COLUMNS = [
  'cli_bank_iban', 'cli_bank_bic', 'cli_bank_name', 'cli_bank_account_holder', 'cli_bank_address', 'cli_email',
  'cli_accounting_email', 'cli_newsletter_email', 'cli_tel1', 'cli_tel2', 'cli_cellphone', 'cli_fax', 'cli_address1',
  'cli_address2', 'cli_first_name', 'cli_last_name', 'cli_notes', 'cli_comment_for_client', 'cli_comment_for_interne',
  'cli_credit_limit', 'cli_discount',
]
const FORBIDDEN = [
  'insert', 'update', 'delete', 'drop', 'alter', 'create', 'truncate', 'grant', 'revoke', 'replace', 'merge', 'call', 'exec',
  'execute', 'pragma', 'attach', 'detach', 'set', 'lock', 'into', 'outfile', 'dumpfile', 'load', 'handler', 'show', 'use',
]

const mask = (sql: string) => sql.replace(/'(?:[^']|'')*'/g, "''")
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// Why a query may not run, or null. Mirrors validate_query, then the hook's table, column and SELECT * rules.
export function queryProblem(sql: unknown, tables = NEVER_TABLES, columns = NEVER_COLUMNS): string | null {
  if (typeof sql !== 'string') return 'execute_read_only_query needs a query string'
  let masked = mask(sql.trim())
  if (!masked) return 'Empty query'
  if (masked.endsWith(';')) masked = masked.slice(0, -1).trimEnd()
  if (masked.includes(';')) return 'Only a single statement is allowed'
  if (masked.includes('--') || masked.includes('/*') || masked.includes('*/')) return 'Comments are not allowed'
  if (!/^\s*(select|with)\b/i.test(masked)) return 'Only SELECT queries are allowed'
  const lowered = masked.toLowerCase()
  for (const word of FORBIDDEN) if (new RegExp('\\b' + word + '\\b').test(lowered)) return 'Keyword not allowed: ' + word
  if (/\bfor\s+(update|share)\b/.test(lowered)) return 'Locking reads are not allowed'
  for (const m of lowered.matchAll(/\blimit\s+(\d+)(?:\s*,\s*(\d+))?/g)) {
    if (Number(m[2] ?? m[1]) > HARD_CAP) return 'LIMIT exceeds the ' + HARD_CAP + '-row cap'
  }
  for (const t of tables) if (new RegExp('\\b' + escape(t.toLowerCase()) + '\\b').test(lowered)) return 'table ' + t + ' must never be touched'
  for (const c of columns) {
    if (new RegExp('\\b' + escape(c.toLowerCase()) + '\\b').test(lowered)) return 'column ' + c + ' is personal or bank data and is not approved'
  }
  if (/select\s+(distinct\s+)?\*/.test(lowered) || /,\s*\*\s*(from|,)/.test(lowered) || /\.\*/.test(lowered)) {
    return 'SELECT * is not allowed; name the columns (ids only)'
  }
  return null
}

// The guard's whole decision for one tool name: null passes the call on, a string refuses it.
export function erpProblem(tool: string, serverId: string, query: unknown): string | null {
  const prefix = 'mcp__' + serverId + '__'
  if (!serverId || !tool.startsWith(prefix)) return null
  const name = tool.slice(prefix.length)
  if (name !== READ_TOOL) return name + ' is not permitted. This ERP is read-only; only ' + READ_TOOL + ' may be used.'
  return queryProblem(query)
}

// Python's \w, \d and \b are Unicode-aware; the classes below match them.
const W = '[\\p{L}\\p{N}_]'
const D = '\\p{Nd}'
const EMAIL = new RegExp(`[${W.slice(1, -1)}.\\-+]+@[${W.slice(1, -1)}.\\-]+\\.[A-Za-z]{2,}`, 'gu')
const CARD = new RegExp(`(?<![\\p{L}\\p{N}_])(?:${D}[ -]*?){13,19}(?![\\p{L}\\p{N}_])`, 'gu')
const PHONE = new RegExp(`(?:\\+?${D}[${D}\\s\\-().]{7,}${D})`, 'gu')
const TOKEN = new RegExp(`(?:bearer|token|secret|api[_-]?key)["':=\\s]+([${W.slice(1, -1)}\\-.]{16,})`, 'giu')

export function redactText(s: string): string {
  let out = s.replace(EMAIL, '[email]').replace(CARD, '[card]').replace(PHONE, '[phone]')
  out = out.replace(TOKEN, (whole, secret: string) => whole.split(secret).join('[secret]'))
  return out
}

// A fresh copy with every string redacted; counts what changed.
export function redact<T>(value: T, tally: { n: number } = { n: 0 }): T {
  if (typeof value === 'string') {
    const next = redactText(value)
    if (next !== value) tally.n += 1
    return next as unknown as T
  }
  if (Array.isArray(value)) return value.map((x) => redact(x, tally)) as unknown as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redact(v, tally)])) as unknown as T
  }
  return value
}

export type Uses = { events: readonly string[]; calls: readonly string[] }
// Why a user-tier mod may not load, or null. A mod that spawns processes or fetches needs a catalog card with disposition add.
export function supplyProblem(name: string, provenance: string, uses: Uses, cards: ReadonlySet<string>): string | null {
  if (provenance.endsWith('@snowgloves-mods')) return null
  const risky = uses.calls.filter((c) => c === 'process.spawn' || c === 'http.fetch' || c === 'fs.write')
  if (!risky.length) return null
  if (cards.has(name)) return null
  return name + ' calls ' + risky.map((c) => '$.' + c).join(', ') + ' and has no add card in the Snow Gloves catalog'
}
