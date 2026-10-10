"""The planner is read-only: it classifies a source ref's tenant files by sensitivity and compares them with a destination."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tenant_import_plan import build_plan, main

IBAN = 'FR76 3000 6000 0112 3456 7890 189'
EMAILS = '\n'.join('person%d@example.test' % i for i in range(40))


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def put(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'ops'
    r.mkdir()
    git(r, 'init', '-q', '-b', 'main')
    put(r, 'tenants/b/context/voice.md', 'base voice\n')
    put(r, 'tenants/b/context/offer.md', 'base offer\n')
    put(r, 'README.md', 'readme\n')
    git(r, 'add', '-A'); git(r, 'commit', '-q', '-m', 'base')
    git(r, 'checkout', '-q', '-b', 'source')
    put(r, 'tenants/a/wiki/page.md', 'a wiki page\n')
    put(r, 'tenants/a/wiki/slug.json', '{"url": "/blog/dont-ask-sk-abcdefghijklmnopqrstuvwxyz0123456789.html"}\n')
    put(r, 'tenants/a/wiki/leak.md', 'account %s\n' % IBAN)
    put(r, 'tenants/a/wiki/key.md', 'token ghp_abcdefghijklmnopqrstuvwxyz0123456789\n')
    put(r, 'tenants/a/context/voice.md', 'voice\n')
    put(r, 'tenants/a/documents/sold.md', 'entities\n')
    put(r, 'tenants/a/data/extraction/out/mail/contacts.csv', EMAILS)
    put(r, 'tenants/a/data/extraction/README.md', 'how it works\n')
    put(r, 'tenants/a/wiki/some-emails.md', 'write to a@example.test and b@example.test\n')
    put(r, 'tenants/b/context/voice.md', 'source voice\n')
    put(r, 'tenants/b/context/offer.md', 'source offer\n')
    put(r, 'tenants/b/context/same.md', 'identical\n')
    put(r, 'README.md', 'readme from source\n')
    git(r, 'add', '-A'); git(r, 'commit', '-q', '-m', 'source work')
    git(r, 'checkout', '-q', 'main')
    put(r, 'tenants/b/context/offer.md', 'main moved too\n')
    put(r, 'tenants/b/context/same.md', 'identical\n')
    git(r, 'add', '-A'); git(r, 'commit', '-q', '-m', 'main moves')
    return r


def files(plan, tenant):
    return {f['path'].split('/', 2)[2]: f for f in plan['tenants'][tenant]['files']}


def test_tiers_by_path_and_by_content(repo):
    plan = build_plan(repo, 'source', 'main')
    a = files(plan, 'a')
    assert a['wiki/page.md']['tier'] == 'T2'
    assert a['context/voice.md']['tier'] == 'T1'
    assert a['documents/sold.md']['tier'] == 'T0' and 'path:restricted' in a['documents/sold.md']['reasons']
    assert a['data/extraction/out/mail/contacts.csv']['tier'] == 'T0'
    assert a['wiki/leak.md']['tier'] == 'T0' and 'content:iban' in a['wiki/leak.md']['reasons']
    assert a['wiki/key.md']['tier'] == 'T0' and 'content:secret' in a['wiki/key.md']['reasons']
    assert a['wiki/some-emails.md']['tier'] == 'T2'  # a couple of addresses are not a contact export
    assert a['data/extraction/README.md']['tier'] == 'T1'


def test_url_slugs_are_not_mistaken_for_secrets(repo):
    assert files(build_plan(repo, 'source', 'main'), 'a')['wiki/slug.json']['tier'] == 'T2'


def test_actions_against_the_destination(repo):
    b = files(build_plan(repo, 'source', 'main'), 'b')
    assert b['context/same.md']['action'] == 'same'
    assert b['context/voice.md']['action'] == 'modify'  # only the source changed it
    assert b['context/offer.md']['action'] == 'both-changed'
    assert files(build_plan(repo, 'source', 'main'), 'a')['wiki/page.md']['action'] == 'add'


def test_only_t1_and_t2_additions_are_recommended_and_t0_is_held(repo):
    plan = build_plan(repo, 'source', 'main')
    assert 'tenants/a/wiki/page.md' in plan['recommended']['include']
    assert 'tenants/a/context/voice.md' in plan['recommended']['include']
    assert 'tenants/a/documents/sold.md' in plan['recommended']['hold']
    assert 'tenants/a/wiki/leak.md' in plan['recommended']['hold']
    assert 'tenants/b/context/offer.md' in plan['recommended']['review']  # both sides changed it
    assert not set(plan['recommended']['include']) & set(plan['recommended']['hold'])


def test_non_tenant_files_are_reported_separately(repo):
    plan = build_plan(repo, 'source', 'main')
    assert plan['other_files'] == ['README.md']


def test_the_plan_never_contains_matched_text_only_counts_and_reasons(repo):
    text = json.dumps(build_plan(repo, 'source', 'main'))
    for secret in (IBAN, 'ghp_abcdefghijklmnopqrstuvwxyz0123456789', 'person1@example.test', 'a@example.test'):
        assert secret not in text


def test_totals_and_merge_check_are_reported(repo):
    plan = build_plan(repo, 'source', 'main')
    assert plan['totals']['T0'] == 4 and plan['totals']['files'] == sum(len(t['files']) for t in plan['tenants'].values())
    assert plan['merge']['conflicts'] == ['tenants/b/context/offer.md']  # both sides edited the same line; the other overlaps merge cleanly


def test_the_planner_is_read_only(repo):
    before = (git(repo, 'rev-parse', 'HEAD'), git(repo, 'status', '--porcelain'), git(repo, 'branch', '--list'))
    build_plan(repo, 'source', 'main')
    assert (git(repo, 'rev-parse', 'HEAD'), git(repo, 'status', '--porcelain'), git(repo, 'branch', '--list')) == before


def test_cli_writes_json_and_summary(repo, tmp_path, capsys):
    out = tmp_path / 'plan.json'
    assert main(['--repo', str(repo), '--source', 'source', '--dest', 'main', '--out', str(out)]) == 0
    assert json.loads(out.read_text())['tenants']['a']
    assert 'T0' in capsys.readouterr().out
    assert main(['--repo', str(repo), '--source', 'nope', '--dest', 'main']) == 2
