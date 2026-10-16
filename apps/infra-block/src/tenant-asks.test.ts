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
  parent: AskElement | null = null;
  onclick?: () => void | Promise<void>;
  onsubmit?: (event: {preventDefault(): void}) => void | Promise<void>;
  constructor(public tagName: string) {}
  set innerHTML(_: string) { throw new Error('Unsafe HTML insertion'); }
  append(...nodes: AskElement[]) {
    for (const node of nodes) node.parent = this;
    this.children.push(...nodes);
  }
  remove() {
    const index = this.parent?.children.indexOf(this) ?? -1;
    if (index >= 0) this.parent?.children.splice(index, 1);
    this.parent = null;
  }
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

  it('parses an answered ask whose stored answer contains the word token', () => {
    const parsed = parseAsks({asks: [wire({status: 'answered', answer: {value: 'renew the token'}})]}, 'heyzack');
    expect(parsed).toEqual([model({status: 'answered', answer: {value: 'renew the token'}})]);
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

  it('shows a rejection only on that ask and leaves the other card usable', async () => {
    const rejected = model({answerType: 'yes_no', proposed: 'EUR 99'});
    const other = model({id: 'b'.repeat(32), title: 'the domain.', answerType: 'yes_no', proposed: 'hey-zack.fr'});
    const onAnswer = vi.fn(async (ask: TenantAsk) => {
      if (ask.id === rejected.id) throw new Error('Coordinator request failed (400).');
    });
    const stack = render([rejected, other], onAnswer);
    const [rejectedCard, otherCard] = stack.children;
    await rejectedCard.all().find(element => element.tagName === 'button' && element.textContent === 'Yes')?.onclick?.();
    expect(rejectedCard.all().some(element => element.className === 'oc-asks-error' && element.textContent === 'Coordinator request failed (400).')).toBe(true);
    expect(otherCard.all().some(element => element.className === 'oc-asks-error')).toBe(false);
    expect(rejectedCard.all().filter(element => element.tagName === 'button').every(element => element.disabled)).toBe(false);
    expect(otherCard.all().filter(element => element.tagName === 'button').every(element => element.disabled)).toBe(false);
    await otherCard.all().find(element => element.tagName === 'button' && element.textContent === 'No')?.onclick?.();
    expect(onAnswer).toHaveBeenCalledTimes(2);
    expect(onAnswer).toHaveBeenLastCalledWith(other, {accept: false});
  });

  it('re-enables a rejected ask so the founder can retry', async () => {
    const ask = model({answerType: 'yes_no', proposed: 'EUR 99'});
    const onAnswer = vi.fn()
      .mockRejectedValueOnce(new Error('Coordinator request failed (400).'))
      .mockResolvedValueOnce(undefined);
    const stack = render([ask], onAnswer);
    const yes = () => stack.all().find(element => element.tagName === 'button' && element.textContent === 'Yes');
    await yes()?.onclick?.();
    expect(yes()?.disabled).toBe(false);
    await yes()?.onclick?.();
    expect(onAnswer).toHaveBeenCalledTimes(2);
    expect(onAnswer).toHaveBeenNthCalledWith(2, ask, {accept: true});
  });
});

describe('ask sync and fleet client', () => {
  it('keeps the last good list when a later poll fails', async () => {
    const emit = vi.fn();
    const good = [model()];
    const asks = vi.fn().mockResolvedValueOnce(good).mockRejectedValueOnce(new Error('network down'));
    const client = {asks} as unknown as FleetClient;
    let poll: (() => void) | undefined;
    vi.spyOn(globalThis, 'setInterval').mockImplementation(handler => {
      poll = handler as () => void;
      return 1 as unknown as ReturnType<typeof setInterval>;
    });
    vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => {});
    const stop = startAskSync(client, ['heyzack'], emit, 60_000);
    for (let i = 0; i < 8; i++) await Promise.resolve();
    expect(emit).toHaveBeenCalledTimes(1);
    expect(emit).toHaveBeenCalledWith(good);
    poll?.();
    for (let i = 0; i < 8; i++) await Promise.resolve();
    expect(asks).toHaveBeenCalledTimes(2);
    expect(emit).toHaveBeenCalledTimes(1);
    expect(emit.mock.calls.some(call => call[0] === null)).toBe(false);
    stop();
    expect(emit.mock.calls.at(-1)).toEqual([null]);
  });

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
