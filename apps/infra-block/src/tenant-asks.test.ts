import {afterEach, describe, expect, it, vi} from 'vitest';
import {FleetClient} from './fleet-tasks';
import {parseAsks, renderAskStack, startAskSync, summarizeAsks, type TenantAsk} from './tenant-asks';

const id = 'a'.repeat(32);
const signal = () => new AbortController().signal;
const json = (data: unknown) => new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}});

function wire(over: Record<string, unknown> = {}) {
  return {
    id, project: 'heyzack', tenant: 'heyzack', kind: 'fact', role: 'librarian',
    title: 'the price.', source: 'context/offer.md', answer_type: 'text',
    proposed: null, status: 'open', answer: null, ...over,
  };
}

function model(over: Partial<TenantAsk> = {}): TenantAsk {
  return {
    id, project: 'heyzack', tenant: 'heyzack', kind: 'fact', role: 'librarian',
    title: 'the price.', source: 'context/offer.md', answerType: 'text',
    proposed: null, status: 'open', answer: null, ...over,
  };
}

class AskElement {
  children: AskElement[] = [];
  attrs: Record<string, string> = {};
  textContent = '';
  className = '';
  value = '';
  disabled = false;
  type = '';
  maxLength = -1;
  onclick?: () => void | Promise<void>;
  onsubmit?: (event: {preventDefault(): void}) => void | Promise<void>;
  constructor(public tagName: string) {}
  set innerHTML(_: string) { throw new Error('Unsafe HTML insertion'); }
  append(...nodes: AskElement[]) { this.children.push(...nodes); }
  setAttribute(name: string, value: string) { this.attrs[name] = value; }
  all(): AskElement[] { return [this, ...this.children.flatMap(child => child.all())]; }
}

function render(asks: TenantAsk[], onAnswer: (ask: TenantAsk, answer: {value: string} | {accept: boolean}) => Promise<void>) {
  vi.stubGlobal('document', {createElement: (tag: string) => new AskElement(tag)});
  return renderAskStack(asks, onAnswer) as unknown as AskElement;
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('tenant ask parsing', () => {
  it('camelCases answer_type and rejects a wrong project, unknown kind, or role outside the crew', () => {
    const parsed = parseAsks({asks: [wire({answer_type: 'yes_no', proposed: 'EUR 99'})]}, 'heyzack');
    expect(parsed).toEqual([model({answerType: 'yes_no', proposed: 'EUR 99'})]);
    expect(parsed[0]).not.toHaveProperty('answer_type');
    expect(() => parseAsks({asks: [wire({project: 'other'})]}, 'heyzack')).toThrow(/project/);
    expect(() => parseAsks({asks: [wire({kind: 'invoice'})]}, 'heyzack')).toThrow(/kind/);
    expect(() => parseAsks({asks: [wire({role: 'founder'})]}, 'heyzack')).toThrow(/role/);
  });

  it('counts open asks only, by tenant and crew role', () => {
    const asks = [
      model(),
      model({id: 'b'.repeat(32), status: 'answered', answer: {value: 'EUR 99'}}),
      model({id: 'c'.repeat(32), tenant: '_demo', kind: 'website', role: 'interpreter', answerType: 'text'}),
    ];
    expect(summarizeAsks(asks)).toEqual({
      byTenant: {heyzack: 1, _demo: 1},
      byRole: {librarian: 1, interpreter: 1},
    });
  });
});

describe('ask stack', () => {
  it('shows a proposed yes/no ask and sends accept when Yes is clicked', async () => {
    const ask = model({kind: 'fact', answerType: 'yes_no', proposed: 'EUR 99', title: '<img src=x onerror=alert(1)>'});
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    const stack = render([ask], onAnswer);
    const text = stack.all().map(element => element.textContent).join('\n');
    expect(text).toContain('EUR 99');
    expect(text).toContain('<img src=x onerror=alert(1)>');
    expect(stack.all().some(element => element.tagName === 'button' && element.textContent === 'Yes')).toBe(true);
    expect(stack.all().some(element => element.tagName === 'button' && element.textContent === 'No')).toBe(true);
    await stack.all().find(element => element.tagName === 'button' && element.textContent === 'Yes')?.onclick?.();
    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith(ask, {accept: true});
  });

  it('caps a text ask at 500 characters and ignores an empty submit', async () => {
    const ask = model();
    const onAnswer = vi.fn().mockResolvedValue(undefined);
    const stack = render([ask], onAnswer);
    const input = stack.all().find(element => element.tagName === 'input');
    const form = stack.all().find(element => element.tagName === 'form');
    expect(input?.maxLength).toBe(500);
    input!.value = '';
    await form?.onsubmit?.({preventDefault() {}});
    expect(onAnswer).not.toHaveBeenCalled();
    input!.value = 'EUR 99';
    await form?.onsubmit?.({preventDefault() {}});
    expect(onAnswer).toHaveBeenCalledWith(ask, {value: 'EUR 99'});
  });

  it('disables the stack and shows the coordinator message when an answer is rejected', async () => {
    const ask = model({answerType: 'yes_no', proposed: 'EUR 99'});
    const onAnswer = vi.fn().mockRejectedValue(new Error('Coordinator request failed (400).'));
    const stack = render([ask], onAnswer);
    await stack.all().find(element => element.textContent === 'Yes')?.onclick?.();
    expect(stack.all().filter(element => element.tagName === 'button').every(element => element.disabled)).toBe(true);
    expect(stack.all().some(element => element.textContent.includes('Coordinator request failed (400).'))).toBe(true);
  });
});

describe('ask sync and fleet client', () => {
  it('emits null when ask sync stops', async () => {
    const emit = vi.fn();
    const client = {asks: vi.fn().mockResolvedValue([model()])} as unknown as FleetClient;
    const stop = startAskSync(client, ['heyzack'], emit, 60_000);
    stop();
    expect(emit).toHaveBeenCalledWith(null);
    expect(emit.mock.calls.at(-1)).toEqual([null]);
    await Promise.resolve();
    expect(emit.mock.calls.at(-1)).toEqual([null]);
  });

  it('lists and answers asks through the allowlisted fleet paths', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({asks: [wire({answer_type: 'yes_no', proposed: 'EUR 99'})]}));
    const client = new FleetClient('operator-token', fetcher);
    await expect(client.asks('heyzack')).resolves.toEqual([model({answerType: 'yes_no', proposed: 'EUR 99'})]);
    expect(fetcher.mock.calls[0][0]).toBe('/api/fleet/asks/heyzack');
    expect(fetcher.mock.calls[0][1]).toMatchObject({method: 'GET', credentials: 'omit', cache: 'no-store'});
    fetcher.mockResolvedValueOnce(json({ask: wire({answer_type: 'yes_no', proposed: 'EUR 99', status: 'answered', answer: {accept: true}})}));
    await expect(client.answerAsk('heyzack', id, {accept: true})).resolves.toMatchObject({status: 'answered', answer: {accept: true}});
    expect(fetcher.mock.calls[1][0]).toBe(`/api/fleet/asks/heyzack/${id}/answer`);
    expect(fetcher.mock.calls[1][1]).toMatchObject({method: 'POST', body: JSON.stringify({accept: true})});
    await expect(client.request('/asks/x/notanid/answer', signal(), {accept: true})).rejects.toThrow(/Unsupported/);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
