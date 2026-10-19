import {afterEach, describe, expect, it, vi} from 'vitest';
import * as THREE from 'three';
import {createBrandMarkers, type BrandTenant} from './brand-atlas';
import {mountHome} from './home';
import {mountCockpit} from './ops';
import type {TenantAsk} from './tenant-asks';

// Record each Field Kit board's pause arguments; the real board still runs.
const boardPauses: unknown[][] = [];
vi.mock('./fleet-tasks', async importOriginal => {
  const actual = await importOriginal<typeof import('./fleet-tasks')>();
  return {...actual, createFleetBoard: () => {
    const board = actual.createFleetBoard();
    const pause = board.pause.bind(board);
    board.pause = (...args: Parameters<typeof pause>) => { boardPauses.push(args); return pause(...args); };
    return board;
  }};
});

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);

class DomStyle {
  setProperty(name: string, value: string): void { (this as unknown as Record<string, string>)[name] = value; }
  getPropertyValue(name: string): string { return (this as unknown as Record<string, string>)[name] ?? ''; }
}

class DomElement {
  children: DomElement[] = [];
  parent: DomElement | null = null;
  attrs: Record<string, string> = {};
  className = '';
  id = '';
  text = '';
  hidden = false;
  disabled = false;
  value = '';
  title = '';
  open = false;
  width = 0;
  height = 0;
  scrollTop = 0;
  tabIndex = 0;
  type = '';
  placeholder = '';
  style = new DomStyle();
  listeners = new Map<string, Array<(event: Event) => void>>();
  onclick: ((event: Event) => void) | null = null;
  oninput: ((event: Event) => void) | null = null;
  onchange: ((event: Event) => void) | null = null;
  onsubmit: ((event: Event) => void) | null = null;
  onkeydown: ((event: Event) => void) | null = null;
  ontoggle: (() => void) | null = null;
  constructor(public tagName: string) {}
  get classList() {
    const el = this;
    return {
      contains: (name: string) => el.tokens().includes(name),
      add: (...names: string[]) => { el.className = [...new Set([...el.tokens(), ...names])].join(' '); },
      remove: (...names: string[]) => { const drop = new Set(names); el.className = el.tokens().filter(name => !drop.has(name)).join(' '); },
      toggle: (name: string, force?: boolean) => {
        const has = el.tokens().includes(name);
        const next = force ?? !has;
        el.className = next ? [...new Set([...el.tokens(), name])].join(' ') : el.tokens().filter(token => token !== name).join(' ');
        return next;
      },
    };
  }
  private tokens(): string[] { return this.className.split(/\s+/).filter(Boolean); }
  get dataset(): Record<string, string> {
    const el = this;
    return new Proxy({} as Record<string, string>, {
      get(_target, key) {
        if (typeof key !== 'string') return undefined;
        return el.getAttribute('data-' + key.replace(/[A-Z]/g, letter => '-' + letter.toLowerCase())) ?? '';
      },
      set(_target, key, value) {
        if (typeof key !== 'string') return false;
        el.setAttribute('data-' + key.replace(/[A-Z]/g, letter => '-' + letter.toLowerCase()), String(value));
        return true;
      },
    });
  }
  set textContent(value: string) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.text = String(value ?? '');
  }
  get textContent(): string {
    if (this.tagName === '#TEXT' || this.children.length === 0) return this.text;
    return this.children.map(child => child.textContent).join('');
  }
  set innerHTML(value: string) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.text = '';
    for (const node of parseFragment(String(value ?? ''))) this.appendChild(node);
  }
  setAttribute(name: string, value: string): void {
    const key = name.toLowerCase();
    this.attrs[key] = String(value);
    if (key === 'id') this.id = String(value);
    if (key === 'class') this.className = String(value);
    if (key === 'hidden') this.hidden = true;
    if (key === 'disabled') this.disabled = true;
    if (key === 'value') this.value = String(value);
  }
  getAttribute(name: string): string | null {
    const key = name.toLowerCase();
    return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null;
  }
  hasAttribute(name: string): boolean { return Object.hasOwn(this.attrs, name.toLowerCase()); }
  removeAttribute(name: string): void {
    const key = name.toLowerCase();
    delete this.attrs[key];
    if (key === 'hidden') this.hidden = false;
    if (key === 'disabled') this.disabled = false;
    if (key === 'id') this.id = '';
  }
  appendChild<T extends DomElement>(child: T): T {
    if (child.parent) child.parent.removeChild(child);
    child.parent = this;
    this.children.push(child);
    return child;
  }
  append(...nodes: Array<DomElement | string>): void {
    for (const node of nodes) {
      if (typeof node === 'string') {
        const text = createElement('#text');
        text.text = node;
        this.appendChild(text);
      } else this.appendChild(node);
    }
  }
  prepend(...nodes: DomElement[]): void {
    const existing = this.children.slice();
    for (const child of existing) child.parent = null;
    this.children = [];
    for (const node of nodes) this.appendChild(node);
    for (const child of existing) this.appendChild(child);
  }
  removeChild<T extends DomElement>(child: T): T {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    if (child.parent === this) child.parent = null;
    return child;
  }
  replaceChildren(...nodes: DomElement[]): void {
    for (const child of this.children) child.parent = null;
    this.children = [];
    for (const node of nodes) this.appendChild(node);
  }
  remove(): void { this.parent?.removeChild(this); }
  replaceWith(...nodes: DomElement[]): void {
    const parent = this.parent;
    if (!parent) return;
    const index = parent.children.indexOf(this);
    this.parent = null;
    const moved = nodes.map(node => {
      node.parent?.removeChild(node);
      node.parent = parent;
      return node;
    });
    parent.children.splice(index, 1, ...moved);
  }
  cloneNode(deep = false): DomElement {
    const copy = createElement(this.tagName === '#TEXT' ? '#text' : this.tagName.toLowerCase());
    copy.className = this.className;
    copy.id = this.id;
    copy.text = this.text;
    copy.hidden = this.hidden;
    copy.disabled = this.disabled;
    copy.value = this.value;
    copy.title = this.title;
    copy.attrs = {...this.attrs};
    if (deep) for (const child of this.children) copy.appendChild(child.cloneNode(true));
    return copy;
  }
  addEventListener(type: string, listener: (event: Event) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }
  removeEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter(item => item !== listener));
  }
  dispatchEvent(event: Event): boolean {
    for (const listener of [...(this.listeners.get(event.type) ?? [])]) listener.call(this, event);
    const property = (this as unknown as Record<string, unknown>)['on' + event.type];
    if (typeof property === 'function') property.call(this, event);
    if (event.bubbles && !event.cancelBubble && this.parent) this.parent.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  querySelector(selector: string): DomElement | null { return queryAll(this, selector)[0] ?? null; }
  querySelectorAll(selector: string): DomElement[] { return queryAll(this, selector); }
  closest(selector: string): DomElement | null {
    const groups = parseGroups(selector);
    let current: DomElement | null = this;
    while (current) {
      if (current.tagName !== '#TEXT' && groups.some(chain => chain.length === 1 && matchesCompound(current as DomElement, chain[0]))) return current;
      current = current.parent;
    }
    return null;
  }
  contains(node: DomElement | null): boolean {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parent;
    }
    return false;
  }
  get isConnected(): boolean {
    let current: DomElement | null = this;
    while (current) {
      if (current === documentRoot) return true;
      current = current.parent;
    }
    return false;
  }
  focus(): void { activeElement = this; }
  click(): void { this.dispatchEvent(new Event('click', {bubbles: true})); }
  getBoundingClientRect(): DOMRect {
    return {x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, toJSON() { return {}; }} as DOMRect;
  }
  setPointerCapture(): void {}
  releasePointerCapture(): void {}
  hasPointerCapture(): boolean { return false; }
  showModal(): void { this.open = true; this.setAttribute('open', ''); }
  close(): void {
    this.open = false;
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  }
  getContext(): CanvasRenderingContext2D {
    return {
      clearRect() {}, fillRect() {}, fillText() {}, beginPath() {}, arc() {}, fill() {}, stroke() {},
      measureText: () => ({width: 12}),
    } as unknown as CanvasRenderingContext2D;
  }
}

function createElement(tag: string): DomElement {
  if (tag === 'input') return new DomInput(tag.toUpperCase());
  if (tag === 'textarea') return new DomTextArea(tag.toUpperCase());
  return new DomElement(tag === '#text' ? '#TEXT' : tag.toUpperCase());
}
class DomInput extends DomElement {}
class DomTextArea extends DomElement {}

let documentRoot: DomElement | null = null;
let activeElement: DomElement | null = null;

interface Compound {tag: string; id: string; classes: string[]; attrs: Array<{name: string; value?: string}>}

function parseCompound(source: string): Compound {
  const compound: Compound = {tag: '', id: '', classes: [], attrs: []};
  const re = /\[([^\]]+)\]|([#.]?)([a-zA-Z_][\w-]*)/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source))) {
    if (match[1]) {
      const raw = match[1];
      const eq = raw.indexOf('=');
      if (eq === -1) compound.attrs.push({name: raw.trim().toLowerCase()});
      else {
        const name = raw.slice(0, eq).trim().toLowerCase();
        let value = raw.slice(eq + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
        compound.attrs.push({name, value});
      }
    } else if (match[2] === '#') compound.id = match[3];
    else if (match[2] === '.') compound.classes.push(match[3]);
    else compound.tag = match[3].toUpperCase();
  }
  return compound;
}
function parseGroups(selector: string): Compound[][] {
  return selector.split(',').map(part => part.trim()).filter(Boolean).map(part => part.split(/\s+/).map(parseCompound));
}
function matchesCompound(el: DomElement, compound: Compound): boolean {
  if (el.tagName === '#TEXT') return false;
  if (compound.tag && el.tagName !== compound.tag) return false;
  if (compound.id && el.id !== compound.id) return false;
  if (compound.classes.some(name => !el.classList.contains(name))) return false;
  for (const attr of compound.attrs) {
    if (!el.hasAttribute(attr.name)) return false;
    if (attr.value !== undefined && el.getAttribute(attr.name) !== attr.value) return false;
  }
  return true;
}
function matchChain(el: DomElement, chain: Compound[], context: DomElement): boolean {
  if (!matchesCompound(el, chain[chain.length - 1])) return false;
  let current = el.parent;
  for (let index = chain.length - 2; index >= 0; index -= 1) {
    while (current && current !== context && !matchesCompound(current, chain[index])) current = current.parent;
    if (!current || current === context) return false;
    current = current.parent;
  }
  return true;
}
function queryAll(root: DomElement, selector: string): DomElement[] {
  const groups = parseGroups(selector);
  const out: DomElement[] = [];
  const walk = (el: DomElement) => {
    for (const child of el.children) {
      if (child.tagName === '#TEXT') continue;
      if (groups.some(chain => matchChain(child, chain, root))) out.push(child);
      walk(child);
    }
  };
  walk(root);
  return out;
}
function parseFragment(html: string): DomElement[] {
  const nodes: DomElement[] = [];
  let index = 0;
  while (index < html.length) {
    if (html[index] !== '<') {
      const next = html.indexOf('<', index);
      const text = html.slice(index, next === -1 ? html.length : next);
      index = next === -1 ? html.length : next;
      if (text.trim()) {
        const node = createElement('#text');
        node.text = text;
        nodes.push(node);
      }
      continue;
    }
    if (html.startsWith('<!--', index)) {
      const end = html.indexOf('-->', index);
      index = end === -1 ? html.length : end + 3;
      continue;
    }
    if (html.startsWith('</', index)) break;
    const tagEnd = html.indexOf('>', index);
    if (tagEnd === -1) break;
    const raw = html.slice(index + 1, tagEnd).trim();
    const selfClose = raw.endsWith('/');
    const body = selfClose ? raw.slice(0, -1).trim() : raw;
    const nameMatch = /^([^\s/>]+)/.exec(body);
    if (!nameMatch) { index = tagEnd + 1; continue; }
    const name = nameMatch[1].toLowerCase();
    const el = createElement(name);
    const attrSource = body.slice(nameMatch[1].length);
    const attrRe = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+)))?/g;
    let attr: RegExpExecArray | null;
    while ((attr = attrRe.exec(attrSource))) el.setAttribute(attr[1], attr[2] ?? attr[3] ?? attr[4] ?? '');
    index = tagEnd + 1;
    if (!selfClose && !VOID_TAGS.has(name)) {
      const inner = readUntilClose(html, index, name);
      for (const child of parseFragment(inner.html)) el.appendChild(child);
      index = inner.end;
    }
    nodes.push(el);
  }
  return nodes;
}
function readUntilClose(html: string, start: number, name: string): {html: string; end: number} {
  const open = new RegExp(`<${name}(?=[\\s>/])`, 'gi');
  const close = new RegExp(`</${name}\\s*>`, 'gi');
  let depth = 1;
  let index = start;
  while (index < html.length && depth > 0) {
    open.lastIndex = index;
    close.lastIndex = index;
    const nextOpen = open.exec(html);
    const nextClose = close.exec(html);
    if (!nextClose) return {html: html.slice(start), end: html.length};
    if (nextOpen && nextOpen.index < nextClose.index) {
      depth += 1;
      index = html.indexOf('>', nextOpen.index) + 1;
    } else {
      depth -= 1;
      const after = html.indexOf('>', nextClose.index) + 1;
      if (depth === 0) return {html: html.slice(start, nextClose.index), end: after};
      index = after;
    }
  }
  return {html: html.slice(start), end: html.length};
}

function installDom(): () => void {
  const previous = {
    document: globalThis.document,
    window: globalThis.window,
    HTMLElement: globalThis.HTMLElement,
    HTMLInputElement: globalThis.HTMLInputElement,
    HTMLTextAreaElement: globalThis.HTMLTextAreaElement,
    HTMLButtonElement: globalThis.HTMLButtonElement,
    SVGElement: globalThis.SVGElement,
    fetch: globalThis.fetch,
    ResizeObserver: globalThis.ResizeObserver,
    MutationObserver: globalThis.MutationObserver,
  };
  const root = createElement('html');
  const body = createElement('body');
  root.appendChild(body);
  documentRoot = root;
  activeElement = body;
  const listeners = new Map<string, Array<(event: Event) => void>>();
  const documentStub = {
    documentElement: root,
    body,
    head: createElement('head'),
    hidden: false,
    visibilityState: 'visible',
    get activeElement() { return activeElement; },
    createElement: (tag: string) => {
      const el = createElement(tag);
      if (tag === 'canvas') { el.width = 64; el.height = 64; }
      return el;
    },
    createElementNS: (_ns: string, tag: string) => createElement(tag),
    getElementById: (id: string) => root.querySelector(`#${id}`),
    querySelector: (selector: string) => root.querySelector(selector),
    querySelectorAll: (selector: string) => root.querySelectorAll(selector),
    addEventListener: (type: string, listener: (event: Event) => void) => {
      const list = listeners.get(type) ?? [];
      list.push(listener);
      listeners.set(type, list);
    },
    removeEventListener: (type: string, listener: (event: Event) => void) => {
      listeners.set(type, (listeners.get(type) ?? []).filter(item => item !== listener));
    },
    dispatchEvent: (event: Event) => {
      for (const listener of [...(listeners.get(event.type) ?? [])]) listener.call(documentStub, event);
      return !event.defaultPrevented;
    },
  };
  const windowStub = {
    document: documentStub,
    innerWidth: 1280,
    innerHeight: 800,
    devicePixelRatio: 1,
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return true; },
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
    setInterval: globalThis.setInterval.bind(globalThis),
    clearInterval: globalThis.clearInterval.bind(globalThis),
    requestAnimationFrame: (callback: FrameRequestCallback) => globalThis.setTimeout(() => callback(Date.now()), 16),
    cancelAnimationFrame: (handle: number) => globalThis.clearTimeout(handle),
    getComputedStyle: () => ({getPropertyValue: () => ''}),
    location: {href: 'http://127.0.0.1/', origin: 'http://127.0.0.1'},
  };
  Object.assign(globalThis, {
    document: documentStub,
    window: windowStub,
    HTMLElement: DomElement,
    HTMLInputElement: DomInput,
    HTMLTextAreaElement: DomTextArea,
    HTMLButtonElement: DomElement,
    SVGElement: DomElement,
    fetch: vi.fn(async () => { throw new Error('offline'); }),
    ResizeObserver: class { observe(): void {} unobserve(): void {} disconnect(): void {} },
    MutationObserver: class { observe(): void {} disconnect(): void {} takeRecords(): [] { return []; } },
  });
  return () => {
    documentRoot = null;
    activeElement = null;
    for (const [key, value] of Object.entries(previous) as Array<[keyof typeof previous, unknown]>) {
      if (value === undefined) delete (globalThis as unknown as Record<string, unknown>)[key];
      else (globalThis as unknown as Record<string, unknown>)[key] = value;
    }
  };
}

function ask(over: Partial<TenantAsk> = {}): TenantAsk {
  return {
    id: 'a'.repeat(32),
    project: 'heyzack',
    tenant: 'heyzack',
    kind: 'fact',
    role: 'librarian',
    title: 'the price.',
    source: 'context/offer.md',
    answerType: 'text',
    proposed: null,
    status: 'open',
    answer: null,
    ...over,
  };
}

const homeCallbacks = {
  controlResident: () => {},
  moveInput: () => {},
  focusNode: () => {},
  openAgent: () => {},
  openDocument: () => {},
  toggleNotes: () => {},
  onPresence: () => {},
  followTour: () => {},
  openBlueprint: () => {},
};

let restoreDom: (() => void) | null = null;
afterEach(() => {
  restoreDom?.();
  restoreDom = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('tenant asks in the town', () => {
  it('shows the librarian ask count and clears every badge when the board disconnects', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const home = mountHome(host as unknown as HTMLElement, homeCallbacks);
    const asks = [
      ask(),
      ask({id: 'b'.repeat(32), title: 'the offer window.'}),
      ask({id: 'c'.repeat(32), project: '_demo', tenant: '_demo', kind: 'website', role: 'interpreter', title: 'confirm the domain', source: 'MANIFEST.yaml'}),
    ];
    document.dispatchEvent(new CustomEvent('tenant-asks', {detail: asks}));
    const librarian = host.querySelector('#ih-token-librarian');
    expect(librarian?.querySelector('.ih-ask-badge')?.textContent).toBe('2');
    expect(librarian?.textContent).toContain('2 asks waiting');
    expect(host.querySelectorAll('.ih-ask-badge')).toHaveLength(2);
    home.selectResident('librarian');
    const ticket = host.querySelector('#ih-ticket-asks');
    expect(ticket?.textContent).toContain('the price.');
    expect(ticket?.textContent).toContain('the offer window.');
    expect(ticket?.textContent).not.toContain('confirm the domain');
    document.dispatchEvent(new CustomEvent('tenant-asks', {detail: null}));
    expect(host.querySelectorAll('.ih-ask-badge')).toHaveLength(0);
    expect(host.textContent).not.toContain('asks waiting');
    expect(host.querySelector('#ih-ticket-asks')?.textContent ?? '').not.toContain('the price.');
    home.dispose();
  });

  it('places one ask sprite above heyzack and removes it when the count is cleared', () => {
    const canvas = {
      width: 64,
      height: 64,
      getContext: () => ({
        clearRect() {}, fillRect() {}, fillText() {}, beginPath() {}, arc() {}, fill() {},
        measureText: () => ({width: 10}),
        font: '', fillStyle: '', textAlign: '', textBaseline: '',
      }),
    };
    vi.stubGlobal('document', {createElement: () => canvas});
    const markers = createBrandMarkers(new THREE.Vector3(), () => {});
    const tenants: BrandTenant[] = [
      {slug: 'heyzack', name: 'Heyzack', availability: 'fixture'},
      {slug: '_demo', name: 'Demo', availability: 'fixture'},
    ];
    markers.update(tenants, 'public-fixtures', false);
    markers.setAskCounts({heyzack: 3});
    const sprites = () => markers.group.children.filter(child => (child as THREE.Sprite).isSprite);
    expect(sprites()).toHaveLength(1);
    expect(sprites()[0].userData.slug).toBe('heyzack');
    expect((sprites()[0] as THREE.Sprite).material.map).toMatchObject({isCanvasTexture: true});
    markers.setAskCounts({});
    expect(sprites()).toHaveLength(0);
    markers.dispose();
  });

  it('lists only the opened tenant in Waiting on you', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const cockpit = mountCockpit(host as unknown as HTMLElement, () => {});
    document.dispatchEvent(new CustomEvent('tenant-asks', {detail: [
      ask({title: 'the price.'}),
      ask({id: 'b'.repeat(32), title: 'the offer window.'}),
      ask({id: 'c'.repeat(32), project: '_demo', tenant: '_demo', kind: 'website', role: 'interpreter', title: 'confirm the domain', source: 'MANIFEST.yaml'}),
    ]}));
    cockpit.openTenant('heyzack');
    const waiting = host.querySelector('.oc-waiting');
    expect(waiting?.textContent).toContain('Waiting on you');
    expect(waiting?.textContent).toContain('the price.');
    expect(waiting?.textContent).toContain('the offer window.');
    expect(waiting?.textContent).not.toContain('confirm the domain');
    document.dispatchEvent(new CustomEvent('tenant-asks', {detail: null}));
    expect(host.querySelector('.oc-waiting')?.textContent).toContain('Connect the Hermes board to see asks');
    expect(host.querySelector('.oc-waiting')?.textContent).not.toContain('the price.');
    (host.querySelector('#oc-btn-return') as DomElement | null)?.click();
  });

  it('keeps the Hermes board connected when the Field Kit is packed away', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const cockpit = mountCockpit(host as unknown as HTMLElement, () => {});
    cockpit.open();
    boardPauses.length = 0;
    (host.querySelector('#oc-btn-return') as DomElement | null)?.click();
    expect(boardPauses.length).toBeGreaterThan(0);
    // pause(true) would clear the client and stop ask sync; only Disconnect clears it.
    expect(boardPauses.every(args => args[0] !== true)).toBe(true);
  });

  it('keeps a typed draft and its focus in a crew ticket across ask polls', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const home = mountHome(host as unknown as HTMLElement, homeCallbacks);
    const poll = (asks: TenantAsk[]) => document.dispatchEvent(new CustomEvent('tenant-asks', {detail: asks}));
    poll([ask(), ask({id: 'b'.repeat(32), title: 'the offer window.'})]);
    home.selectResident('librarian');
    const input = host.querySelector('#ih-ticket-asks .oc-asks-input') as unknown as HTMLInputElement;
    input.value = 'EUR 9';
    input.focus();
    // The same asks come back as fresh objects on every poll.
    poll([ask(), ask({id: 'b'.repeat(32), title: 'the offer window.'})]);
    expect(host.querySelector('#ih-ticket-asks .oc-asks-input')).toBe(input);
    expect(input.value).toBe('EUR 9');
    expect(document.activeElement).toBe(input);
    // A changed list rebuilds the stack but carries the draft and focus by ask id.
    poll([ask({id: 'c'.repeat(32), title: 'the launch date.'}), ask(), ask({id: 'b'.repeat(32), title: 'the offer window.', status: 'answered', answer: {value: 'May'}})]);
    const carried = Array.from(host.querySelectorAll<HTMLInputElement>('#ih-ticket-asks .oc-asks-input')).find(el => el.getAttribute('data-ask-id') === 'a'.repeat(32));
    expect(carried).toBeDefined();
    expect(carried).not.toBe(input);
    expect(carried?.value).toBe('EUR 9');
    expect(document.activeElement).toBe(carried);
    home.dispose();
  });

  it('keeps a crew ticket draft when the founder opens another resident and comes back', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const home = mountHome(host as unknown as HTMLElement, homeCallbacks);
    document.dispatchEvent(new CustomEvent('tenant-asks', {detail: [
      ask(), ask({id: 'd'.repeat(32), kind: 'website', role: 'interpreter', title: 'confirm the domain', source: 'MANIFEST.yaml'}),
    ]}));
    home.selectResident('librarian');
    const input = host.querySelector('#ih-ticket-asks .oc-asks-input') as unknown as HTMLInputElement;
    input.value = 'EUR 9';
    home.selectResident('interpreter');
    expect(Array.from(host.querySelectorAll<HTMLInputElement>('#ih-ticket-asks .oc-asks-input'))
      .map(el => el.getAttribute('data-ask-id'))).toEqual(['d'.repeat(32)]);
    home.selectResident('librarian');
    const back = host.querySelector('#ih-ticket-asks .oc-asks-input') as unknown as HTMLInputElement;
    expect(back.getAttribute('data-ask-id')).toBe('a'.repeat(32));
    expect(back.value).toBe('EUR 9');
    // Clearing the box drops the draft for good.
    back.value = '';
    home.selectResident('interpreter');
    home.selectResident('librarian');
    expect((host.querySelector('#ih-ticket-asks .oc-asks-input') as unknown as HTMLInputElement).value).toBe('');
    home.dispose();
  });

  it('keeps a typed draft and its focus in the tenant view across ask polls', () => {
    restoreDom = installDom();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const cockpit = mountCockpit(host as unknown as HTMLElement, () => {});
    const poll = (asks: TenantAsk[]) => document.dispatchEvent(new CustomEvent('tenant-asks', {detail: asks}));
    poll([ask(), ask({id: 'b'.repeat(32), title: 'the offer window.'})]);
    cockpit.openTenant('heyzack');
    const input = host.querySelector('.oc-waiting .oc-asks-input') as unknown as HTMLInputElement;
    input.value = 'EUR 9';
    input.focus();
    poll([ask(), ask({id: 'b'.repeat(32), title: 'the offer window.'})]);
    expect(host.querySelector('.oc-waiting .oc-asks-input')).toBe(input);
    expect(input.value).toBe('EUR 9');
    expect(document.activeElement).toBe(input);
    poll([ask({id: 'c'.repeat(32), title: 'the launch date.'}), ask(), ask({id: 'b'.repeat(32), title: 'the offer window.'})]);
    const carried = Array.from(host.querySelectorAll<HTMLInputElement>('.oc-waiting .oc-asks-input')).find(el => el.getAttribute('data-ask-id') === 'a'.repeat(32));
    expect(carried).toBeDefined();
    expect(carried).not.toBe(input);
    expect(carried?.value).toBe('EUR 9');
    expect(document.activeElement).toBe(carried);
    (host.querySelector('#oc-btn-return') as DomElement | null)?.click();
  });
});

