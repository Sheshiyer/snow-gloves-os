"""Local, access-scoped stores for restricted tenant data (finance: bank accounts; marketing: contacts).

Why not the shared knowledge base: embedding IBANs and contact lists would send them to hosted model providers on
every retrieval. Here each domain is its own private SQLite file; agents get masked views and counts, secrets are
encrypted at rest, and every reveal or export is audited. Full values leave only through an explicit, logged action.
"""
import base64
import csv
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path

DOMAINS = ('finance', 'marketing')
SAMPLE_CAP = 25
KEYCHAIN_SERVICE = 'snowgloves-tenant-vault'
EMAIL = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
IBAN_CELL = re.compile(r'^[A-Z]{2}\d{2}[0-9A-Z ]{11,30}$')

SCHEMA = {
    'finance': '''
        CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, name TEXT NOT NULL, siren TEXT, vat TEXT,
            source TEXT, erp_ref TEXT, imported_at REAL NOT NULL, UNIQUE(tenant, name));
        CREATE TABLE IF NOT EXISTS bank_accounts (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, entity TEXT NOT NULL, bank TEXT NOT NULL,
            bic TEXT NOT NULL, iban_masked TEXT NOT NULL, iban_hash TEXT NOT NULL, iban_enc TEXT NOT NULL, source TEXT, erp_ref TEXT,
            imported_at REAL NOT NULL, UNIQUE(tenant, iban_hash));''',
    'marketing': '''
        CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, email TEXT NOT NULL, first_name TEXT, last_name TEXT,
            company TEXT, account_id TEXT, segment TEXT, grp TEXT, business_line TEXT, account_status TEXT, revenue_tier TEXT, source TEXT,
            erp_ref TEXT, imported_at REAL NOT NULL, UNIQUE(tenant, email));
        CREATE INDEX IF NOT EXISTS contacts_segment ON contacts(tenant, segment);
        CREATE TABLE IF NOT EXISTS suppression (email TEXT PRIMARY KEY, reason TEXT, imported_at REAL NOT NULL);''',
}
AUDIT = 'CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT, detail TEXT);'


class VaultError(Exception):
    pass


def iban_valid(value):
    text = re.sub(r'\s', '', str(value)).upper()
    if not re.fullmatch(r'[A-Z]{2}\d{2}[0-9A-Z]{11,30}', text):
        return False
    return int(''.join(str(int(c, 36)) for c in text[4:] + text[:4])) % 97 == 1


def normalize_iban(value):
    return re.sub(r'\s', '', str(value)).upper()


def mask_iban(value):
    text = normalize_iban(value)
    return '%s **** %s' % (text[:4], text[-4:])


def mask_email(value):
    local, _, domain = str(value).partition('@')
    return (local[:1].lower() + '***@' + domain.lower()) if local and domain else '***'


def keychain_key(domain):
    """Per-domain key held in the macOS Keychain (created on first use)."""
    def find():
        return subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', domain, '-w'], capture_output=True, text=True)
    found = find()
    if found.returncode == 0 and found.stdout.strip():
        return found.stdout.strip()
    key = secrets.token_hex(32)
    made = subprocess.run(['security', 'add-generic-password', '-s', KEYCHAIN_SERVICE, '-a', domain, '-w', key, '-U'], capture_output=True, text=True)
    if made.returncode:
        raise VaultError('Cannot create the vault key in the Keychain')
    return key


class Vault:
    def __init__(self, path, domain, key_provider=None):
        if domain not in DOMAINS:
            raise VaultError('Unknown vault domain: %s' % domain)
        self.path, self.domain = Path(path), domain
        self._key_provider = key_provider or (lambda: os.environ.get('SNOWGLOVES_VAULT_KEY') or keychain_key(domain))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        os.close(os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600))
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript(SCHEMA[domain] + AUDIT)
        self.db.commit()

    # --- plumbing -------------------------------------------------------------------------------------------
    def _need(self, domain):
        if self.domain != domain:
            raise VaultError('This is the %s vault; %s data is not available here' % (self.domain, domain))

    def _key(self):
        key = self._key_provider()
        if not key:
            raise VaultError('Vault key unavailable')
        return key

    def _fingerprint(self, iban):
        return hmac.new(self._key().encode(), normalize_iban(iban).encode(), hashlib.sha256).hexdigest()

    def _crypt(self, data, decrypt=False):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'SGV_PASS': self._key()}
        cmd = ['openssl', 'enc', '-d' if decrypt else '-e', '-aes-256-cbc', '-pbkdf2', '-iter', '100000', '-a', '-A', '-pass', 'env:SGV_PASS']
        if not decrypt:
            cmd.insert(3, '-salt')
        done = subprocess.run(cmd, input=data.encode(), capture_output=True, env=env)
        if done.returncode:
            raise VaultError('Decryption failed (wrong key or damaged value)' if decrypt else 'Encryption failed')
        return done.stdout.decode().strip()

    def _audit(self, actor, action, target='', detail=''):
        self.db.execute('INSERT INTO audit(ts, actor, action, target, detail) VALUES(?,?,?,?,?)', (time.time(), actor, action, target, detail))
        self.db.commit()

    def audit_tail(self, n=20):
        return [dict(r) for r in self.db.execute('SELECT ts, actor, action, target, detail FROM audit ORDER BY id DESC LIMIT ?', (max(0, int(n)),))]

    @staticmethod
    def _tables(text):
        """Yield (header cells, rows of cells) for each markdown table."""
        block = []
        for line in text.splitlines() + ['']:
            if line.lstrip().startswith('|'):
                block.append([c.strip().replace('**', '').strip() for c in line.strip().strip('|').split('|')])
            elif block:
                if len(block) >= 2:
                    yield block[0], [r for r in block[2:] if r]
                block = []

    # --- finance --------------------------------------------------------------------------------------------
    def ingest_bank_markdown(self, tenant, text, source=''):
        self._need('finance')
        added = existing = duplicates = entities_added = 0
        invalid, seen, now = [], set(), time.time()
        for header, rows in self._tables(text):
            if any(h.upper().startswith('SIREN') for h in header):
                for row in rows:
                    siren = re.sub(r'\D', '', row[1]) if len(row) > 1 else ''
                    if row and len(siren) == 9:
                        vat = row[2] if len(row) > 2 and re.fullmatch(r'[A-Z]{2}[0-9A-Z]{8,13}', row[2].replace(' ', '')) else None
                        cur = self.db.execute('INSERT OR IGNORE INTO entities(tenant, name, siren, vat, source, imported_at) VALUES(?,?,?,?,?,?)', (tenant, row[0], siren, vat, source, now))
                        entities_added += cur.rowcount
            for row in rows:
                position = next((i for i, c in enumerate(row) if IBAN_CELL.match(c.strip())), None)
                if position is None or position < 1:
                    continue
                entity, raw = row[0], row[position]
                if not iban_valid(raw):
                    invalid.append(entity)
                    continue
                digest = self._fingerprint(raw)
                if digest in seen:
                    duplicates += 1
                    continue
                seen.add(digest)
                if self.db.execute('SELECT 1 FROM bank_accounts WHERE tenant=? AND iban_hash=?', (tenant, digest)).fetchone():
                    existing += 1
                    continue
                bank_cell = row[1] if position > 1 else ''
                match = re.match(r'^(.*?)\s*\(([A-Z0-9]{8,11})\)\s*$', bank_cell)
                bank, bic = (match.group(1).strip(), match.group(2)) if match else (bank_cell, '')
                self.db.execute('INSERT INTO bank_accounts(tenant, entity, bank, bic, iban_masked, iban_hash, iban_enc, source, imported_at) VALUES(?,?,?,?,?,?,?,?,?)',
                                (tenant, entity, bank, bic, mask_iban(raw), digest, self._crypt(normalize_iban(raw)), source, now))
                added += 1
        self.db.commit()
        self._audit('system', 'ingest_bank_markdown', tenant, '%d added, %d existing, %d invalid, %d entities' % (added, existing, len(invalid), entities_added))
        return {'accounts_added': added, 'accounts_existing': existing, 'duplicates': duplicates, 'invalid': invalid, 'entities_added': entities_added}

    def accounts(self):
        self._need('finance')
        return [{'id': r['id'], 'tenant': r['tenant'], 'entity': r['entity'], 'bank': r['bank'], 'bic': r['bic'], 'iban': r['iban_masked'],
                 'source': r['source'], 'erp_ref': r['erp_ref']} for r in self.db.execute('SELECT * FROM bank_accounts ORDER BY tenant, entity, id')]

    def entities(self):
        self._need('finance')
        return [dict(r) for r in self.db.execute('SELECT tenant, name, siren, vat, erp_ref FROM entities ORDER BY tenant, name')]

    def verify_iban(self, entity, candidate):
        """True when the entity has an account with this IBAN. Never reveals a stored value."""
        self._need('finance')
        digest = self._fingerprint(candidate)
        found = self.db.execute('SELECT 1 FROM bank_accounts WHERE entity=? AND iban_hash=?', (entity, digest)).fetchone() is not None
        self._audit('agent', 'verify_iban', entity, 'match' if found else 'no match')
        return found

    def reveal_iban(self, account_id, actor, reason):
        self._need('finance')
        if not str(actor).strip() or not str(reason).strip():
            raise VaultError('A reveal needs an actor and a reason')
        row = self.db.execute('SELECT * FROM bank_accounts WHERE id=?', (account_id,)).fetchone()
        if not row:
            raise VaultError('No such account')
        value = self._crypt(row['iban_enc'], decrypt=True)
        self._audit(actor.strip(), 'reveal_iban', 'account %d' % account_id, 'entity %s; reason: %s' % (row['entity'], reason.strip()))
        return value

    # --- marketing ------------------------------------------------------------------------------------------
    def ingest_contacts(self, tenant, contacts_csv, suppression_csv=None, source=''):
        self._need('marketing')
        added = existing = duplicates = invalid = suppressed = 0
        seen, now = set(), time.time()
        if suppression_csv:
            with open(suppression_csv, newline='', encoding='utf-8-sig', errors='replace') as handle:
                for row in csv.DictReader(handle):
                    email = (row.get('email') or '').strip().lower()
                    if EMAIL.match(email):
                        suppressed += self.db.execute('INSERT OR IGNORE INTO suppression(email, reason, imported_at) VALUES(?,?,?)', (email, row.get('reason') or '', now)).rowcount
        with open(contacts_csv, newline='', encoding='utf-8-sig', errors='replace') as handle:
            for row in csv.DictReader(handle):
                email = (row.get('email') or '').strip().lower()
                if not EMAIL.match(email):
                    invalid += 1
                    continue
                if email in seen:
                    duplicates += 1
                    continue
                seen.add(email)
                cur = self.db.execute('INSERT OR IGNORE INTO contacts(tenant, email, first_name, last_name, company, account_id, segment, grp, business_line, account_status, revenue_tier, source, imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                      (tenant, email, row.get('first_name'), row.get('last_name'), row.get('company'), row.get('account_id'), row.get('segment') or '',
                                       row.get('group'), row.get('business_line'), row.get('account_status'), row.get('revenue_tier'), source, now))
                added += cur.rowcount
                existing += 1 - cur.rowcount
        self.db.commit()
        self._audit('system', 'ingest_contacts', tenant, '%d added, %d existing, %d duplicates, %d invalid, %d suppression entries' % (added, existing, duplicates, invalid, suppressed))
        return {'contacts_added': added, 'duplicates': duplicates, 'invalid': invalid, 'suppressed': suppressed, 'contacts_existing': existing}

    def is_suppressed(self, email):
        self._need('marketing')
        return self.db.execute('SELECT 1 FROM suppression WHERE email=?', (str(email).strip().lower(),)).fetchone() is not None

    def segment_counts(self, tenant=None):
        self._need('marketing')
        sql = ('SELECT c.segment AS segment, COUNT(*) AS total, SUM(s.email IS NOT NULL) AS suppressed FROM contacts c '
               'LEFT JOIN suppression s ON s.email = c.email %s GROUP BY c.segment ORDER BY c.segment')
        rows = self.db.execute(sql % ('WHERE c.tenant=?' if tenant else ''), (tenant,) if tenant else ())
        return {r['segment']: {'total': r['total'], 'suppressed': r['suppressed'], 'reachable': r['total'] - r['suppressed']} for r in rows}

    def _reachable(self, segment, limit=None):
        sql = ('SELECT c.* FROM contacts c LEFT JOIN suppression s ON s.email = c.email WHERE c.segment=? AND s.email IS NULL ORDER BY c.email' + (' LIMIT %d' % limit if limit is not None else ''))
        return self.db.execute(sql, (segment,)).fetchall()

    def sample(self, segment, limit=10):
        self._need('marketing')
        limit = max(0, min(int(limit), SAMPLE_CAP))
        return [{'email': mask_email(r['email']), 'company': r['company'], 'segment': r['segment'], 'revenue_tier': r['revenue_tier']} for r in self._reachable(segment, limit)]

    def export_segment(self, segment, dest, actor, reason):
        """Write full addresses for an approved send step to a private file. Never returned to a caller, never overwrites."""
        self._need('marketing')
        if not str(actor).strip() or not str(reason).strip():
            raise VaultError('An export needs an actor and a reason')
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise VaultError('Export destination already exists') from None
        rows = self._reachable(segment)
        with os.fdopen(fd, 'w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['email', 'first_name', 'last_name', 'company', 'account_id', 'segment'])
            for r in rows:
                writer.writerow([r['email'], r['first_name'], r['last_name'], r['company'], r['account_id'], r['segment']])
        self._audit(actor.strip(), 'export_segment', segment, '%d rows to %s; reason: %s' % (len(rows), dest.name, reason.strip()))
        return len(rows)
