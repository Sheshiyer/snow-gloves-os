import { renderBrandPassport } from './brand-summary';
import './ops.css';
import { loadSnapshot, loadDocument, previewPlan, validateSnapshot } from './ops-client';
import type { OpsSnapshot, OpsDocument, PlanRequest, PlanPreview } from './ops-contracts';
import { fleetNodes, fleetActivity } from './fleet-model';
import { derivePresence } from './residents';

function safeHtml(parts: TemplateStringsArray, ...values: unknown[]): string {
  const escape = (v: unknown): string => {
    if (v === null || v === undefined) return '';
    return String(v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };
  return parts.reduce((out, part, i) => out + part + (i < values.length ? escape(values[i]) : ''), '');
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function toStr(v: unknown, fallback = ''): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return fallback;
}

function toArr<T = unknown>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

function prettyJson(val: unknown): string {
  try {
    return JSON.stringify(val, null, 2);
  } catch {
    return String(val);
  }
}

function sanitizeUrl(raw: unknown): string | null {
  const s = toStr(raw).trim();
  if (s.startsWith('http://') || s.startsWith('https://')) return s;
  return null;
}

export interface CockpitController {
  open(nodeId?: string): void;
  openDocument(path: string): void;
  openTenant(slug: string): void;
}

const BUILDING_ROUTING: Record<string, { section: SectionName; slugMatch?: string }> = {
  'agent-ceo': { section: 'Agents', slugMatch: 'ceo' },
  'agent-cto': { section: 'Agents', slugMatch: 'cto' },
  'agent-chief-of-staff': { section: 'Agents', slugMatch: 'chief-of-staff' },
  'agent-sentinel': { section: 'Agents', slugMatch: 'sentinel' },
  'agent-interpreter': { section: 'Agents', slugMatch: 'interpreter' },
  'agent-dispatcher': { section: 'Agents', slugMatch: 'dispatcher' },
  'agent-librarian': { section: 'Agents', slugMatch: 'librarian' },
  'module-catalog': { section: 'Modules' },
  'runtime-adapters': { section: 'Runtimes' },
  'connector-gate': { section: 'Connectors' },
  'tenant-vault': { section: 'Tenants' },
  'fleet-wings': { section: 'Fleet' },
  'omniroute-gateway': { section: 'Fleet' },
  'cloud-recovery': { section: 'Fleet' },
  'hermes-bus': { section: 'Activity' },
  'knowledge-archive': { section: 'Resources' },
};

const SECTIONS = [
  'Overview',
  'Agents',
  'Modules',
  'Runtimes',
  'Connectors',
  'Tenants',
  'Fleet',
  'Activity',
  'Workbench',
  'Evidence',
  'Resources',
] as const;
type SectionName = (typeof SECTIONS)[number];
const STATION_NAMES: Record<SectionName, string> = {
  Overview: 'Town square',
  Agents: 'Crew',
  Modules: 'Parts chest',
  Runtimes: 'Platforms',
  Connectors: 'Signal plugs',
  Tenants: 'Neighborhoods',
  Fleet: 'Wing hangar',
  Activity: 'Courier trail',
  Workbench: 'Blueprint bench',
  Evidence: 'Stamp book',
  Resources: 'Field notes'
};

export function toyIcon(section: string): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 64 64');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'oc-toy-icon');
  
  let content = '';
  
  switch (section) {
    case 'Agents':
      content = `
        <ellipse cx="32" cy="57" rx="19" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M32 9 v7" stroke="#283d36" stroke-width="2.5" stroke-linecap="round"/>
        <circle cx="32" cy="8" r="3" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="31" cy="7" r="1" fill="#f4edda"/>
        <rect x="17" y="49" width="10" height="6" rx="3" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <rect x="37" y="49" width="10" height="6" rx="3" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <rect x="14" y="15" width="36" height="24" rx="9" fill="#699a92" stroke="#283d36" stroke-width="1.3"/>
        <path d="M17 19 q15 -3 30 0" stroke="#f4edda" stroke-width="1.8" stroke-linecap="round" opacity="0.6" fill="none"/>
        <circle cx="24" cy="26" r="5" fill="#f4edda" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="40" cy="26" r="5" fill="#f4edda" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="25" cy="26" r="2.2" fill="#283d36"/>
        <circle cx="41" cy="26" r="2.2" fill="#283d36"/>
        <circle cx="26" cy="25" r="0.8" fill="#ffffff"/>
        <circle cx="42" cy="25" r="0.8" fill="#ffffff"/>
        <ellipse cx="19" cy="31" rx="2.4" ry="1.4" fill="#d9a8ad"/>
        <ellipse cx="45" cy="31" rx="2.4" ry="1.4" fill="#d9a8ad"/>
        <path d="M28 32 q4 3.5 8 0" stroke="#283d36" stroke-width="1.5" stroke-linecap="round" fill="none"/>
        <rect x="19" y="37" width="26" height="14" rx="5" fill="#58857e" stroke="#283d36" stroke-width="1.3"/>
        <rect x="24" y="40" width="16" height="8" rx="2.5" fill="#d5b466" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="28" cy="44" r="1.4" fill="#f4edda"/>
        <circle cx="36" cy="44" r="1.4" fill="#c97858"/>
        <circle cx="13" cy="42" r="3.5" fill="#d9a8ad" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="51" cy="42" r="3.5" fill="#d9a8ad" stroke="#283d36" stroke-width="1.3"/>
      `;
      break;
    case 'Modules':
      content = `
        <ellipse cx="32" cy="57" rx="22" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M11 41 L27 33 L43 41 L27 49 Z" fill="#d5b466" stroke="#283d36" stroke-width="1.3"/>
        <path d="M11 41 L27 49 L27 56 L11 48 Z" fill="#c49e4d" stroke="#283d36" stroke-width="1.3"/>
        <path d="M27 49 L43 41 L43 48 L27 56 Z" fill="#b38b3a" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="21" cy="39" rx="3" ry="1.5" fill="#f4edda" stroke="#283d36" stroke-width="1.1"/>
        <ellipse cx="33" cy="39" rx="3" ry="1.5" fill="#f4edda" stroke="#283d36" stroke-width="1.1"/>
        <path d="M31 27 L45 20 L57 26 L43 33 Z" fill="#699a92" stroke="#283d36" stroke-width="1.3"/>
        <path d="M31 27 L43 33 L43 42 L31 36 Z" fill="#558079" stroke="#283d36" stroke-width="1.3"/>
        <path d="M43 33 L57 26 L57 35 L43 42 Z" fill="#426761" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="44" cy="26" rx="2.5" ry="1.3" fill="#87a4ac" stroke="#283d36" stroke-width="1"/>
        <path d="M19 19 L32 12 L45 19 L32 26 Z" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <path d="M19 19 L32 26 L32 35 L19 28 Z" fill="#b16142" stroke="#283d36" stroke-width="1.3"/>
        <path d="M32 26 L45 19 L45 28 L32 35 Z" fill="#984b2e" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="32" cy="18.5" rx="3.2" ry="1.7" fill="#f4edda" stroke="#283d36" stroke-width="1.1"/>
        <path d="M21 20 L31 15" stroke="#f4edda" stroke-width="1.2" stroke-linecap="round" opacity="0.6"/>
      `;
      break;
    case 'Runtimes':
      content = `
        <ellipse cx="32" cy="56" rx="22" ry="4.5" fill="#283d36" opacity="0.22"/>
        <rect x="23" y="11" width="18" height="14" rx="2.5" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <rect x="26" y="13" width="12" height="7" rx="1.5" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
        <path d="M28 16 h8" stroke="#c97858" stroke-width="1.5" stroke-linecap="round"/>
        <rect x="12" y="21" width="40" height="31" rx="6" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <path d="M14 24 h36" stroke="#f4edda" stroke-width="1.4" stroke-linecap="round" opacity="0.5" fill="none"/>
        <rect x="17" y="26" width="30" height="14" rx="3" fill="#283d36" stroke="#283d36" stroke-width="1.2"/>
        <rect x="19" y="28" width="26" height="10" rx="2" fill="#9bac80"/>
        <path d="M23 33 h4 M25 31 v4" stroke="#283d36" stroke-width="1.6" stroke-linecap="round"/>
        <circle cx="38" cy="32" r="1.8" fill="#c97858" stroke="#283d36" stroke-width="1"/>
        <circle cx="42" cy="34.5" r="1.8" fill="#d5b466" stroke="#283d36" stroke-width="1"/>
        <rect x="18" y="44" width="13" height="5" rx="2" fill="#f4edda" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="37" cy="46.5" r="2.2" fill="#699a92" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="44" cy="46.5" r="2.2" fill="#699a92" stroke="#283d36" stroke-width="1.2"/>
      `;
      break;
    case 'Connectors':
      content = `
        <ellipse cx="32" cy="56" rx="20" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M10 44 C12 25, 23 23, 27 34" fill="none" stroke="#f4edda" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M10 44 C12 25, 23 23, 27 34" fill="none" stroke="#283d36" stroke-width="9" stroke-linecap="round" style="stroke-linejoin:round"/>
        <path d="M10 44 C12 25, 23 23, 27 34" fill="none" stroke="#f4edda" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M25 31 L37 20" stroke="#283d36" stroke-width="12" stroke-linecap="round"/>
        <path d="M25 31 L37 20" stroke="#c97858" stroke-width="9.5" stroke-linecap="round"/>
        <rect x="35" y="13" width="8" height="11" rx="2" transform="rotate(45 39 18.5)" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <line x1="43" y1="14" x2="47" y2="10" stroke="#d5b466" stroke-width="2.5" stroke-linecap="round"/>
        <line x1="47" y1="18" x2="51" y2="14" stroke="#d5b466" stroke-width="2.5" stroke-linecap="round"/>
        <line x1="43" y1="14" x2="47" y2="10" stroke="#283d36" stroke-width="2.5" stroke-linecap="round" opacity="0.3"/>
        <circle cx="48" cy="9" r="1" fill="#f4edda"/>
        <circle cx="52" cy="13" r="1" fill="#f4edda"/>
        <path d="M51 22 Q56 20 56 15 Q56 10 51 8" fill="none" stroke="#699a92" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M55 26 Q62 23 62 15 Q62 7 55 4" fill="none" stroke="#699a92" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="1 3"/>
      `;
      break;
    case 'Tenants':
      content = `
        <ellipse cx="32" cy="57" rx="23" ry="4.5" fill="#283d36" opacity="0.22"/>
        <polygon points="10,29 19,20 28,29" fill="#d9a8ad" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="12" y="29" width="14" height="19" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <rect x="16" y="37" width="6" height="11" rx="2" fill="#f4edda" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="20.5" cy="43" r="0.7" fill="#283d36"/>
        <polygon points="36,29 45,20 54,29" fill="#d5b466" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="38" y="29" width="14" height="19" fill="#9bac80" stroke="#283d36" stroke-width="1.3"/>
        <rect x="42" y="37" width="6" height="11" rx="2" fill="#f4edda" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="46.5" cy="43" r="0.7" fill="#283d36"/>
        <polygon points="21,21 32,10 43,21" fill="#c97858" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="23" y="21" width="18" height="32" fill="#f4edda" stroke="#283d36" stroke-width="1.3"/>
        <rect x="26" y="25" width="5" height="5" rx="1" fill="#699a92" stroke="#283d36" stroke-width="1.2"/>
        <rect x="33" y="25" width="5" height="5" rx="1" fill="#699a92" stroke="#283d36" stroke-width="1.2"/>
        <rect x="28" y="39" width="8" height="14" rx="3" fill="#699a92" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="34" cy="46" r="0.9" fill="#f4edda"/>
      `;
      break;
    case 'Fleet':
      content = `
        <ellipse cx="32" cy="57" rx="19" ry="4" fill="#283d36" opacity="0.22"/>
        <path d="M11 27 L6 21 L12 24 L14 18 L15 26 Z" fill="#699a92" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <ellipse cx="33" cy="27" rx="22" ry="14" fill="#d5b466" stroke="#283d36" stroke-width="1.3"/>
        <path d="M13 24 Q33 16 53 24" fill="none" stroke="#f4edda" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M13 30 Q33 38 53 30" fill="none" stroke="#c97858" stroke-width="2" stroke-linecap="round" opacity="0.7"/>
        <line x1="25" y1="39" x2="23" y2="45" stroke="#283d36" stroke-width="1.4"/>
        <line x1="39" y1="39" x2="41" y2="45" stroke="#283d36" stroke-width="1.4"/>
        <path d="M20 45 h24 c0 0 -2 6 -7 6 h-10 c-5 0 -7 -6 -7 -6 Z" fill="#c97858" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="24" y="46" width="3.5" height="3.5" rx="1" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
        <rect x="30" y="46" width="3.5" height="3.5" rx="1" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
        <rect x="36" y="46" width="3.5" height="3.5" rx="1" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
        <circle cx="48" cy="24" r="2" fill="#87a4ac" stroke="#283d36" stroke-width="1"/>
        <path d="M48 22 Q52 19 54 22" stroke="#f4edda" stroke-width="1.2" fill="none" stroke-linecap="round"/>
      `;
      break;
    case 'Activity':
      content = `
        <ellipse cx="32" cy="56" rx="22" ry="4.5" fill="#283d36" opacity="0.22"/>
        <rect x="11" y="19" width="42" height="29" rx="4.5" fill="#f4edda" stroke="#283d36" stroke-width="1.3"/>
        <path d="M11 21 L32 37 L53 21" fill="none" stroke="#87a4ac" stroke-width="1.8" stroke-linejoin="round"/>
        <polygon points="11,20 32,36 53,20" fill="#e8dfc8" opacity="0.6" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <rect x="38" y="23" width="9" height="11" rx="1.5" fill="#9bac80" stroke="#283d36" stroke-width="1.2"/>
        <circle cx="42.5" cy="28.5" r="2" fill="#f4edda"/>
        <circle cx="32" cy="38" r="6.5" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="32" cy="38" r="4.5" fill="#b16142"/>
        <path d="M30 36 q2 2 4 0 M32 36 v4" stroke="#f4edda" stroke-width="1.2" stroke-linecap="round" fill="none"/>
        <path d="M14 22 h24" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.7"/>
      `;
      break;
    case 'Workbench':
      content = `
        <ellipse cx="32" cy="56" rx="21" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M12 16 h30 l11 11 v25 h-41 Z" fill="#87a4ac" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <polygon points="42,16 53,27 42,27" fill="#699a92" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <path d="M18 24 h18 M18 30 h24 M18 36 h16 M18 42 h20" stroke="#f4edda" stroke-width="2" stroke-linecap="round" opacity="0.9"/>
        <circle cx="24" cy="42" r="2.5" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
        <path d="M29 48 L49 20 L55 24 L35 52 Z" fill="#d5b466" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <polygon points="29,48 26,55 35,52" fill="#f4edda" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <polygon points="26,55 28,52 30,54" fill="#283d36"/>
        <rect x="49" y="18" width="7" height="4" rx="1.5" transform="rotate(35 52.5 20)" fill="#d9a8ad" stroke="#283d36" stroke-width="1"/>
      `;
      break;
    case 'Evidence':
      content = `
        <ellipse cx="32" cy="57" rx="20" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M32 9 C26 9 27 19 29 25 C30 28 29 32 25 36 L39 36 C35 32 34 28 35 25 C37 19 38 9 32 9 Z" fill="#d5b466" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <ellipse cx="32" cy="10" rx="4.5" ry="3" fill="#f4edda" stroke="#283d36" stroke-width="1.2"/>
        <rect x="21" y="36" width="22" height="7" rx="2" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="32" cy="44" rx="14" ry="4" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="32" cy="50" rx="17" ry="6" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <ellipse cx="32" cy="49" rx="12" ry="3.8" fill="#b16142" stroke="#283d36" stroke-width="1.1"/>
        <circle cx="32" cy="49" r="2.5" fill="#f4edda" opacity="0.8"/>
        <path d="M31 16 Q33 13 34 16" stroke="#f4edda" stroke-width="1.2" fill="none" stroke-linecap="round"/>
      `;
      break;
    case 'Resources':
      content = `
        <ellipse cx="32" cy="57" rx="21" ry="4.5" fill="#283d36" opacity="0.22"/>
        <path d="M13 18 C13 18 24 16 32 20 C40 16 51 18 51 18 L51 46 C41 42 34 44 32 47 C30 44 23 42 13 46 Z" fill="#f4edda" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <path d="M11 20 C11 20 23 18 32 22 C41 18 53 20 53 20 L53 48 C42 44 34 46 32 49 C30 46 22 44 11 48 Z" fill="#699a92" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <path d="M14 20 C14 20 24 18 32 22 C40 18 50 20 50 20 L50 46 C41 42 34 44 32 47 C30 44 23 42 14 46 Z" fill="#f4edda" stroke="#283d36" stroke-width="1.2" stroke-linejoin="round"/>
        <path d="M32 22 L32 47" stroke="#d5b466" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M32 22 L36 34 L32 32 L28 34 Z" fill="#c97858" stroke="#283d36" stroke-width="1" stroke-linejoin="round"/>
        <path d="M18 27 h9 M18 32 h9 M18 37 h7" stroke="#87a4ac" stroke-width="1.5" stroke-linecap="round" opacity="0.8"/>
        <path d="M37 27 h9 M37 32 h9 M37 37 h6" stroke="#87a4ac" stroke-width="1.5" stroke-linecap="round" opacity="0.8"/>
      `;
      break;
    case 'Overview':
    default:
      content = `
        <ellipse cx="32" cy="57" rx="22" ry="4.5" fill="#283d36" opacity="0.22"/>
        <rect x="39" y="12" width="6" height="12" rx="1.5" fill="#87a4ac" stroke="#283d36" stroke-width="1.3"/>
        <rect x="15" y="28" width="34" height="25" rx="4" fill="#9bac80" stroke="#283d36" stroke-width="1.3"/>
        <polygon points="10,29 32,13 54,29" fill="#d9a8ad" stroke="#283d36" stroke-width="1.3" stroke-linejoin="round"/>
        <path d="M13 28 L32 15 L51 28" stroke="#f4edda" stroke-width="1.5" fill="none" stroke-linecap="round" opacity="0.6"/>
        <rect x="19" y="33" width="8" height="8" rx="2" fill="#f4edda" stroke="#283d36" stroke-width="1.2"/>
        <line x1="23" y1="33" x2="23" y2="41" stroke="#283d36" stroke-width="1"/>
        <line x1="19" y1="37" x2="27" y2="37" stroke="#283d36" stroke-width="1"/>
        <rect x="31" y="35" width="12" height="18" rx="3" fill="#c97858" stroke="#283d36" stroke-width="1.3"/>
        <circle cx="40" cy="44" r="1.2" fill="#d5b466" stroke="#283d36" stroke-width="0.8"/>
        <circle cx="24" cy="22" r="2.5" fill="#f4edda" stroke="#283d36" stroke-width="1"/>
      `;
      break;
  }
  
  svg.innerHTML = content.trim();
  return svg;
}

interface ActivityRowItem {
  id: string;
  timestamp?: string;
  tenant?: string;
  agent?: string;
  summary?: string;
  status?: string;
  jobId?: string;
  artifactId?: string;
  source?: string;
  payload?: unknown;
}

export function mountCockpit(
  host: HTMLElement,
  onSelectNode: (id: string) => void
): CockpitController {
  let isOpen = false;
  let currentSection: SectionName = 'Overview';
  let selectedNodeContext: string | null = null;
  let selectedTenantScope: string = '';
  let expectedScopeMode: OpsSnapshot['scope']['mode'] | null = null;
  let renderedSection: SectionName | null = null;

  let snapshot: OpsSnapshot | null = null;
  let isFetching = false;
  let isStale = false;
  let lastLoadedSource: 'api' | 'fixture' | null = null;
  let genericFetchError: string | null = null;

  let pollTimer: number | null = null;
  let fetchGeneration = 0;
  let fetchAbortController: AbortController | null = null;
  let docGeneration = 0;
  let docAbortController: AbortController | null = null;
  let planGeneration = 0;
  let planAbortController: AbortController | null = null;
  let lastFocusedElement: HTMLElement | null = null;
  let lastFocusedId = '';

  const moduleFilter = {
    search: '',
    category: 'all',
    disposition: 'all',
    risk: 'all',
    runtime: 'all',
    agent: 'all',
    tenant: 'all',
  };

  const activityFilter = {
    tab: 'events' as 'events' | 'jobs' | 'artifacts' | 'approvals',
    tenant: 'all',
    agent: 'all',
    status: 'all',
    search: '',
  };

  const evidenceFilter = { status: 'all' as 'all' | 'open' | 'accepted' };
  const resourceFilter = { search: '', kind: 'all' };

  const defaultProposalTitle = 'Proposal ' + new Date().toISOString().slice(0, 10);
  const workbenchForm = {
    tenant: '',
    title: defaultProposalTitle,
    modules: new Set<string>(),
    runtime: '',
    wing: '',
  };
  let currentPlanPreview: PlanPreview | null = null;
  let planErrorMsg: string | null = null;
  let isPlanning = false;

  let currentDocModal: OpsDocument | null = null;
  let docLoading = false;
  let docErrorMsg: string | null = null;
  let selectedActivityItem: ActivityRowItem | null = null;

  let globalSearchQuery = '';
  let connectionNotesOpen = false;
  let searchDebounceTimer: number | null = null;

  host.innerHTML = '';
  const rootEl = document.createElement('div');
  rootEl.className = 'oc-cockpit-overlay';
  rootEl.setAttribute('hidden', '');
  rootEl.setAttribute('role', 'region');
  rootEl.setAttribute('aria-label', 'Toy Town Field Kit');
  host.appendChild(rootEl);

  const docDialog = document.createElement('dialog');
  docDialog.className = 'oc-dialog';
  docDialog.setAttribute('id', 'oc-doc-dialog');
  docDialog.setAttribute('aria-label', 'Operations Document Inspector');
  host.appendChild(docDialog);

  const activityDialog = document.createElement('dialog');
  activityDialog.className = 'oc-dialog';
  activityDialog.setAttribute('id', 'oc-activity-dialog');
  activityDialog.setAttribute('aria-label', 'Hermes Activity Record Details');
  host.appendChild(activityDialog);
  let documentTriggerId = '';
  docDialog.addEventListener('close', () => {
    docGeneration++; docAbortController?.abort(); docLoading = false;
    if (isOpen) (document.getElementById(documentTriggerId) || document.getElementById('oc-btn-return'))?.focus();
  });

  function closeOverlay() {
    if (docDialog.open) {
      docDialog.close();
      return;
    }
    if (activityDialog.open) {
      activityDialog.close();
      return;
    }
    isOpen = false;
    rootEl.setAttribute('hidden', '');
    isFetching = false;
    isPlanning = false;
    fetchGeneration++; docGeneration++; planGeneration++;
    stopPolling();
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }
    if (fetchAbortController) {
      fetchAbortController.abort();
      fetchAbortController = null;
    }
    if (docAbortController) {
      docAbortController.abort();
      docAbortController = null;
    }
    if (planAbortController) {
      planAbortController.abort();
      planAbortController = null;
    }
    host.dispatchEvent(new CustomEvent('cockpit-close'));
    const returnFocus = lastFocusedElement?.isConnected && lastFocusedElement.tagName !== 'BODY'
      ? lastFocusedElement : document.getElementById(lastFocusedId);
    if (returnFocus && !returnFocus.closest('[inert]')) returnFocus.focus();
    else document.getElementById('btn-operations')?.focus();
    lastFocusedElement = null;
    lastFocusedId = '';
  }

  // Revocation clears both state and rendered source bodies before any late request can settle.
  function publishSnapshot(): void {
    host.dispatchEvent(new CustomEvent('cockpit-snapshot', {
      bubbles: true,
      detail: {
        snapshot,
        scopeMode: expectedScopeMode,
        tenant: selectedTenantScope || null,
        source: snapshot ? lastLoadedSource || 'unavailable' : 'unavailable',
        stale: isStale || !snapshot,
      },
    }));
  }

  function clearScopedProjection(): void {
    snapshot = null;
    docGeneration++;
    planGeneration++;
    docAbortController?.abort();
    planAbortController?.abort();
    docAbortController = null;
    planAbortController = null;
    currentDocModal = null;
    selectedActivityItem = null;
    currentPlanPreview = null;
    docErrorMsg = null;
    planErrorMsg = null;
    docLoading = false;
    isPlanning = false;
    documentTriggerId = '';
    workbenchForm.tenant = '';
    workbenchForm.title = defaultProposalTitle;
    workbenchForm.modules.clear();
    workbenchForm.runtime = '';
    workbenchForm.wing = '';
    if (docDialog.open) docDialog.close();
    if (activityDialog.open) activityDialog.close();
    docDialog.replaceChildren();
    activityDialog.replaceChildren();
    publishSnapshot();
  }

  async function fetchOperationsData(forceFixtureFallback = false) {
    const currentGen = ++fetchGeneration;
    if (fetchAbortController) {
      fetchAbortController.abort();
    }
    fetchAbortController = new AbortController();
    const signal = fetchAbortController.signal;

    isFetching = true;
    genericFetchError = null;
    render();

    const requestedTenant = selectedTenantScope || undefined;
    const requiresScopedResponse = Boolean(requestedTenant) || expectedScopeMode === 'local-private';

    try {
      if (!forceFixtureFallback) {
        try {
          const data = await loadSnapshot(requestedTenant, { signal });
          if (signal.aborted || currentGen !== fetchGeneration) return;
          if (data && data.schema === 'snowgloves.cockpit.v1') {
            if (expectedScopeMode === 'local-private' && data.scope.mode !== 'local-private') {
              throw new Error('Private instance scope changed unexpectedly');
            }
            snapshot = data;
            expectedScopeMode = data.scope.mode;
            selectedTenantScope = data.scope.tenant || '';
            isStale = false;
            lastLoadedSource = 'api';
            genericFetchError = null;
            return;
          }
          throw new Error('Invalid snapshot schema response');
        } catch (err: unknown) {
          if (signal.aborted || currentGen !== fetchGeneration) return;
          if (requiresScopedResponse) {
            clearScopedProjection();
            isStale = false;
            genericFetchError = `Failed to load the selected scope${requestedTenant ? ` for tenant "${requestedTenant}"` : ''}. Access was refused or the endpoint is unreachable.`;
            return;
          }
          if (!snapshot) {
            // Fall through to public fixture for initial first public load
          } else {
            isStale = true;
            genericFetchError = 'Public endpoint unreachable. Retaining previous known snapshot in stale state.';
            return;
          }
        }
      }

      if (!requiresScopedResponse) {
        const fixtureController = new AbortController();
        const cancelFixture = () => fixtureController.abort();
        signal.addEventListener('abort', cancelFixture, { once: true });
        let fixtureDeadline: ReturnType<typeof setTimeout> | undefined;
        try {
          const rawFixture = await Promise.race([
            fetch('/cockpit-fixture.json', { signal: fixtureController.signal }).then(res => {
              if (!res.ok) throw new Error('Public fixture is unavailable');
              return res.json();
            }),
            new Promise<never>((_, reject) => {
              fixtureDeadline = setTimeout(() => {
                reject(new Error('Public fixture request timed out'));
                fixtureController.abort();
              }, 8000);
            }),
          ]);
          if (signal.aborted || currentGen !== fetchGeneration) return;
          const fixture = validateSnapshot(rawFixture);
          if (
            fixture &&
            fixture.schema === 'snowgloves.cockpit.v1' &&
            fixture.scope.mode === 'public-fixtures'
          ) {
            snapshot = fixture;
            expectedScopeMode = fixture.scope.mode;
            isStale = true;
            lastLoadedSource = 'fixture';
            genericFetchError = null;
            return;
          }
        } finally {
          clearTimeout(fixtureDeadline);
          signal.removeEventListener('abort', cancelFixture);
        }
        throw new Error('Public fixture validation failed');
      }
    } catch (e: unknown) {
      if (signal.aborted || currentGen !== fetchGeneration) return;
      if (requiresScopedResponse) {
        clearScopedProjection();
      } else if (snapshot) {
        isStale = true;
      }
      genericFetchError = genericFetchError || (e instanceof Error ? e.message : 'Operations endpoint request failed');
    } finally {
      if (!signal.aborted && currentGen === fetchGeneration) {
        isFetching = false;
        publishSnapshot();
        render();
      }
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = window.setInterval(() => {
      if (isOpen && document.visibilityState === 'visible' && !isFetching) {
        fetchOperationsData(false);
      }
    }, 15000);
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function openDocViewer(docPath: string) {
    const targetPath = toStr(docPath).trim();
    if (!targetPath) return;
    documentTriggerId = (document.activeElement as HTMLElement | null)?.id || '';

    const currentGen = ++docGeneration;
    if (docAbortController) {
      docAbortController.abort();
    }
    docAbortController = new AbortController();
    const signal = docAbortController.signal;

    docLoading = true;
    docErrorMsg = null;
    currentDocModal = null;
    renderDocDialog();
    if (!docDialog.open) {
      docDialog.showModal();
    }

    if (!snapshot) {
      await fetchOperationsData(false);
      if (signal.aborted || currentGen !== docGeneration) return;
    }

    const registered = snapshot?.documents?.find((d) => d.path === targetPath);
    if (!registered) {
      docLoading = false;
      docErrorMsg = `Document path "${targetPath}" is not registered in authorized cockpit catalog.`;
      renderDocDialog();
      return;
    }

    try {
      const doc = await loadDocument(targetPath, { signal });
      if (signal.aborted || currentGen !== docGeneration) return;
      currentDocModal = doc;
    } catch (e: unknown) {
      if (signal.aborted || currentGen !== docGeneration) return;
      docErrorMsg = 'Failed to load document content: ' + (e instanceof Error ? e.message : String(e));
    } finally {
      if (!signal.aborted && currentGen === docGeneration) {
        docLoading = false;
        renderDocDialog();
      }
    }
  }

  function renderDocDialog() {
    docDialog.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'oc-dialog-header';
    const title = document.createElement('h3');
    title.className = 'oc-dialog-title';
    title.textContent = currentDocModal ? currentDocModal.path : 'Document Viewer';
    const closeBtn = document.createElement('button');
    closeBtn.className = 'oc-btn oc-btn-sm';
    closeBtn.textContent = '✕ Close';
    closeBtn.onclick = () => {
      if (docAbortController) {
        docAbortController.abort();
        docAbortController = null;
      }
      docDialog.close();
    };
    header.append(title, closeBtn);

    const content = document.createElement('div');
    content.className = 'oc-dialog-content';

    if (docLoading) {
      const loadingEl = document.createElement('div');
      loadingEl.className = 'oc-alert oc-alert-info';
      loadingEl.textContent = 'Loading registered document...';
      content.appendChild(loadingEl);
    } else if (docErrorMsg) {
      const errEl = document.createElement('div');
      errEl.className = 'oc-alert oc-alert-error';
      errEl.textContent = docErrorMsg;
      content.appendChild(errEl);
    } else if (currentDocModal) {
      const metaBar = document.createElement('div');
      metaBar.style.display = 'flex';
      metaBar.style.gap = '8px';
      metaBar.style.alignItems = 'center';
      metaBar.style.flexWrap = 'wrap';

      const pathBadge = document.createElement('span');
      pathBadge.className = 'oc-badge';
      pathBadge.textContent = 'PATH: ' + currentDocModal.path;
      metaBar.appendChild(pathBadge);

      const shaBadge = document.createElement('span');
      shaBadge.className = 'oc-badge';
      shaBadge.textContent = 'SHA256: ' + (currentDocModal.sha256 || 'n/a');
      shaBadge.style.overflowWrap = 'anywhere';
      shaBadge.style.minWidth = '0';
      metaBar.appendChild(shaBadge);

      if (new TextEncoder().encode(currentDocModal.content).length !== undefined) {
        const bytesBadge = document.createElement('span');
        bytesBadge.className = 'oc-badge';
        bytesBadge.textContent = `${new TextEncoder().encode(currentDocModal.content).length} B`;
        metaBar.appendChild(bytesBadge);
      }

      if (currentDocModal.truncated) {
        const truncBadge = document.createElement('span');
        truncBadge.className = 'oc-badge oc-badge-stale';
        truncBadge.textContent = 'TRUNCATED PAYLOAD';
        metaBar.appendChild(truncBadge);
      }
      content.appendChild(metaBar);

      const pre = document.createElement('pre');
      pre.className = 'oc-pre';
      pre.textContent = currentDocModal.content || '(empty payload)';
      content.appendChild(pre);
    }

    const footer = document.createElement('div');
    footer.className = 'oc-dialog-footer';
    const doneBtn = document.createElement('button');
    doneBtn.className = 'oc-btn oc-btn-primary';
    doneBtn.textContent = 'Done';
    doneBtn.onclick = () => {
      if (docAbortController) {
        docAbortController.abort();
        docAbortController = null;
      }
      docDialog.close();
    };
    footer.appendChild(doneBtn);

    docDialog.append(header, content, footer);
  }

  function openActivityDialog(item: ActivityRowItem) {
    selectedActivityItem = item;
    activityDialog.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'oc-dialog-header';
    const title = document.createElement('h3');
    title.className = 'oc-dialog-title';
    title.textContent = `Activity Record: ${item.id}`;
    const closeBtn = document.createElement('button');
    closeBtn.className = 'oc-btn oc-btn-sm';
    closeBtn.textContent = '✕ Close';
    closeBtn.onclick = () => activityDialog.close();
    header.append(title, closeBtn);

    const content = document.createElement('div');
    content.className = 'oc-dialog-content';

    const metaGrid = document.createElement('div');
    metaGrid.className = 'oc-grid';
    metaGrid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(200px, 1fr))';

    const metaItems: Array<[string, string | undefined]> = [
      ['Record ID', item.id],
      ['Timestamp', item.timestamp || '—'],
      ['Tenant', item.tenant || '—'],
      ['Agent', item.agent || '—'],
      ['Status', item.status || '—'],
      ['Job ID', item.jobId || '—'],
      ['Artifact ID', item.artifactId || '—'],
      ['Source Doc', item.source || '—'],
    ];

    metaItems.forEach(([k, v]) => {
      const card = document.createElement('div');
      card.className = 'oc-card';
      card.style.padding = '0.5rem 0.75rem';
      card.innerHTML = safeHtml`<div class="oc-stat-label">${k}</div><div style="font-family:var(--oc-font-mono);font-size:0.8rem;margin-top:2px;">${v}</div>`;
      metaGrid.appendChild(card);
    });
    content.appendChild(metaGrid);

    const sumBox = document.createElement('div');
    sumBox.className = 'oc-card';
    sumBox.innerHTML = safeHtml`<h4 style="font-family:var(--oc-font-title);margin:0 0 0.4rem;text-transform:uppercase;">Summary</h4>
      <p style="margin:0;font-size:0.88rem;">${item.summary || 'No summary available'}</p>`;
    content.appendChild(sumBox);

    if (item.source && snapshot?.documents?.some((d) => d.path === item.source)) {
      const srcBtn = document.createElement('button');
      srcBtn.className = 'oc-btn oc-btn-accent oc-btn-sm';
      srcBtn.textContent = `View Source Document (${item.source})`;
      srcBtn.onclick = () => {
        activityDialog.close();
        openDocViewer(item.source!);
      };
      content.appendChild(srcBtn);
    }

    if (item.payload !== undefined) {
      const rawSec = document.createElement('div');
      rawSec.innerHTML = safeHtml`<h4 style="font-family:var(--oc-font-title);margin:0.5rem 0 0.25rem;text-transform:uppercase;">Payload Details</h4>`;
      const pre = document.createElement('pre');
      pre.className = 'oc-pre';
      pre.textContent = prettyJson(item.payload);
      rawSec.appendChild(pre);
      content.appendChild(rawSec);
    }

    const footer = document.createElement('div');
    footer.className = 'oc-dialog-footer';
    const doneBtn = document.createElement('button');
    doneBtn.className = 'oc-btn oc-btn-primary';
    doneBtn.textContent = 'Close Record';
    doneBtn.onclick = () => activityDialog.close();
    footer.appendChild(doneBtn);

    activityDialog.append(header, content, footer);
    activityDialog.showModal();
  }

  async function handlePlanPreview() {
    if (!workbenchForm.tenant || !workbenchForm.title.trim() || workbenchForm.title.length > 160) {
      return;
    }
    const currentGen = ++planGeneration;
    if (planAbortController) {
      planAbortController.abort();
    }
    planAbortController = new AbortController();
    const signal = planAbortController.signal;

    isPlanning = true;
    planErrorMsg = null;
    currentPlanPreview = null;
    render();

    const req: PlanRequest = {
      tenant: workbenchForm.tenant,
      title: workbenchForm.title.trim(),
      modules: Array.from(workbenchForm.modules),
      runtime: workbenchForm.runtime || undefined,
      wing: workbenchForm.wing || undefined,
    };

    const requestIdentity = JSON.stringify(req);
    try {
      const preview = await previewPlan(req, { signal });
      if (signal.aborted || currentGen !== planGeneration) return;
      const latestDraft = {tenant: workbenchForm.tenant, title: workbenchForm.title.trim(), modules: Array.from(workbenchForm.modules), runtime: workbenchForm.runtime || undefined, wing: workbenchForm.wing || undefined};
      if (JSON.stringify(latestDraft) !== requestIdentity) {
        planErrorMsg = 'Draft changed during preview. Generate a new proposal for this draft.';
        return;
      }
      currentPlanPreview = preview;
    } catch (e: unknown) {
      if (signal.aborted || currentGen !== planGeneration) return;
      planErrorMsg = 'Simulation failed: ' + (e instanceof Error ? e.message : 'Server returned an error');
    } finally {
      if (!signal.aborted && currentGen === planGeneration) {
        isPlanning = false;
        render();
      }
    }
  }

  function jumpToBuilding(buildingId: string) {
    closeOverlay();
    onSelectNode(buildingId);
  }

  function visitStation(section: SectionName, nodeId?: string): void {
    currentSection = section;
    focusStation(section, nodeId);
  }

  function focusStation(section: SectionName, nodeId?: string) {
    const landmarks: Record<SectionName, string> = {Overview:'hermes-bus', Agents:'agent-chief-of-staff', Modules:'module-catalog', Runtimes:'runtime-adapters', Connectors:'connector-gate', Tenants:'tenant-vault', Fleet:'fleet-wings', Activity:'hermes-bus', Workbench:'agent-cto', Evidence:'agent-sentinel', Resources:'knowledge-archive'};
    host.dispatchEvent(new CustomEvent('cockpit-station', {detail:{nodeId:nodeId || landmarks[section]}}));
  }

  function render() {
    if (!isOpen) return;

    const focused = document.activeElement as HTMLElement | null;
    const activeId = focused?.id || null;
    const focusWasInKit = Boolean(focused && rootEl.contains(focused));
    let selStart: number | null = null;
    let selEnd: number | null = null;
    if (focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement) {
      try {
        selStart = focused.selectionStart;
        selEnd = focused.selectionEnd;
      } catch {}
    }

    const prevContent = rootEl.querySelector('.oc-content');
    const prevScrollTop = renderedSection === currentSection && prevContent ? prevContent.scrollTop : 0;
    renderedSection = currentSection;

    rootEl.innerHTML = '';

    // Top Brand Header
    const header = document.createElement('header');
    header.className = 'oc-header';

    const brandBlock = document.createElement('div');
    brandBlock.className = 'oc-brand-block';
    const title = document.createElement('h1');
    title.className = 'oc-brand-title';
    title.textContent = 'FIELD KIT';
    const sub = document.createElement('span');
    sub.className = 'oc-brand-subtitle';
    sub.textContent = STATION_NAMES[currentSection];
    const headerMark = document.createElement('span'); headerMark.className = 'oc-object-mark'; headerMark.append(toyIcon(currentSection));
    brandBlock.append(headerMark, title, sub);

    const headerActions = document.createElement('div');
    headerActions.className = 'oc-header-actions';
    const returnBtn = document.createElement('button');
    returnBtn.id = 'oc-btn-return';
    returnBtn.className = 'oc-btn-return';
    returnBtn.textContent = 'Pack away';
    returnBtn.onclick = () => closeOverlay();
    headerActions.appendChild(returnBtn);
    header.append(brandBlock, headerActions);

    // Contextbar
    const contextBar = document.createElement('details');
    contextBar.className = 'oc-contextbar oc-connection-notes';
    contextBar.open = connectionNotesOpen;
    contextBar.ontoggle = () => { connectionNotesOpen = contextBar.open; };
    const connectionSummary = document.createElement('summary'); connectionSummary.textContent = 'Connection notes'; contextBar.append(connectionSummary);

    const tags = document.createElement('div');
    tags.className = 'oc-context-tags';

    // Scope Selector (Default All Public, or choose Tenant)
    const scopeLabel = document.createElement('label');
    scopeLabel.className = 'oc-filter-label';
    scopeLabel.setAttribute('for', 'oc-scope-selector');
    scopeLabel.textContent = 'Scope:';
    tags.appendChild(scopeLabel);

    const scopeSel = document.createElement('select');
    scopeSel.id = 'oc-scope-selector';
    scopeSel.className = 'oc-filter-select';
    const optPublic = document.createElement('option');
    optPublic.value = '';
    optPublic.textContent = expectedScopeMode === 'local-private' ? 'Instance (All Tenants)' : 'Public (All Scope)';
    scopeSel.appendChild(optPublic);
    if (selectedTenantScope && !snapshot?.tenants.some(tenant => tenant.slug === selectedTenantScope)) {
      const pendingScope = document.createElement('option');
      pendingScope.value = selectedTenantScope;
      pendingScope.textContent = `Tenant: ${selectedTenantScope} (${isFetching ? 'loading' : 'unavailable'})`;
      scopeSel.appendChild(pendingScope);
    }

    (snapshot?.tenants || []).forEach((t) => {
      const opt = document.createElement('option');
      opt.value = toStr(t.slug);
      opt.textContent = `Tenant: ${toStr(t.name || t.slug)}`;
      scopeSel.appendChild(opt);
    });
    scopeSel.value = selectedTenantScope;
    scopeSel.onchange = (e) => {
      selectedTenantScope = (e.target as HTMLSelectElement).value;
      clearScopedProjection();
      fetchOperationsData(false);
    };
    tags.appendChild(scopeSel);

    const scopeMode = snapshot?.scope.mode || 'unavailable';
    const scopeBadge = document.createElement('span');
    scopeBadge.className = `oc-badge oc-badge-scope-${scopeMode === 'public-fixtures' ? 'public' : 'private'}`;
    scopeBadge.textContent = `MODE: ${scopeMode.toUpperCase()}`;
    tags.appendChild(scopeBadge);

    const sourceBadge = document.createElement('span');
    const isDisconnected = isStale || lastLoadedSource === 'fixture';
    sourceBadge.className = `oc-badge ${isDisconnected ? 'oc-badge-stale' : 'oc-badge-status-reachable'}`;
    sourceBadge.textContent = !snapshot ? 'SOURCE: UNAVAILABLE' : lastLoadedSource === 'fixture' ? 'SOURCE: PUBLIC FIXTURE (DISCONNECTED · STALE)' : isStale ? 'SOURCE: LAST API SNAPSHOT (STALE)' : 'SOURCE: API (CONNECTED)';
    tags.appendChild(sourceBadge);

    if (snapshot?.generatedAt) {
      const genBadge = document.createElement('span');
      genBadge.className = 'oc-badge';
      genBadge.textContent = `Updated: ${snapshot.generatedAt}`;
      tags.appendChild(genBadge);
      const ageBadge = document.createElement('span');
      ageBadge.className = 'oc-badge';
      const age = Math.max(0, Math.floor((Date.now() - Date.parse(snapshot.generatedAt)) / 1000));
      ageBadge.textContent = `Age: ${age < 60 ? `${age}s` : age < 3600 ? `${Math.floor(age / 60)}m` : `${Math.floor(age / 3600)}h`}`;
      tags.appendChild(ageBadge);
    }

    // Global Search box
    const searchBox = document.createElement('div');
    searchBox.className = 'oc-search-box';
    const searchIcon = document.createElement('span');
    searchIcon.className = 'oc-search-icon';
    searchIcon.append(toyIcon('Resources'));
    const searchInput = document.createElement('input');
    searchInput.id = 'oc-global-search-input';
    searchInput.className = 'oc-search-input';
    searchInput.type = 'text';
    searchInput.placeholder = 'Find a crew member, part, or field note…';
    searchInput.value = globalSearchQuery;
    searchInput.oninput = (e) => {
      const val = (e.target as HTMLInputElement).value;
      if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
      searchDebounceTimer = window.setTimeout(() => {
        globalSearchQuery = val;
        render();
      }, 100);
    };
    searchInput.onkeydown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        globalSearchQuery = '';
        render();
      }
    };
    searchBox.append(searchIcon, searchInput);

    if (globalSearchQuery.trim()) {
      const clearBtn = document.createElement('button');
      clearBtn.id = 'oc-global-search-clear';
      clearBtn.className = 'oc-search-clear';
      clearBtn.textContent = '✕';
      clearBtn.onclick = () => {
        globalSearchQuery = '';
        render();
      };
      searchBox.appendChild(clearBtn);

      const dropdown = renderGlobalSearchResults(globalSearchQuery.trim());
      if (dropdown) searchBox.appendChild(dropdown);
    }

    const refreshBtn = document.createElement('button');
    refreshBtn.id = 'oc-btn-refresh';
    refreshBtn.className = 'oc-btn-refresh';
    refreshBtn.textContent = isFetching ? '⟳ Refreshing...' : '⟳ Refresh';
    refreshBtn.disabled = isFetching;
    refreshBtn.onclick = () => fetchOperationsData(false);

    contextBar.append(tags, refreshBtn);

    // Main Layout
    const main = document.createElement('div');
    main.className = 'oc-main';

    // Navigation with Tablist and keyboard roving
    const nav = document.createElement('nav');
    nav.className = 'oc-nav';
    nav.setAttribute('aria-label', 'Toy town stations');
    const navList = document.createElement('ul');
    navList.className = 'oc-nav-list';
    navList.setAttribute('role', 'tablist');

    SECTIONS.forEach((sec, idx) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'presentation');
      const btn = document.createElement('button');
      btn.id = `oc-nav-tab-${sec.toLowerCase()}`;
      btn.className = `oc-nav-btn ${currentSection === sec ? 'oc-active' : ''}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', currentSection === sec ? 'true' : 'false');
      btn.setAttribute('aria-controls', 'oc-tabpanel-main');
      btn.setAttribute('tabindex', currentSection === sec ? '0' : '-1');

      const nameSpan = document.createElement('span');
      nameSpan.className = 'oc-station-label';
      nameSpan.textContent = STATION_NAMES[sec];
      btn.setAttribute('aria-label', `${sec} · ${STATION_NAMES[sec]}`);
      btn.append(toyIcon(sec));
      btn.appendChild(nameSpan);

      const count = getSectionCount(sec);
      if (count !== null) {
        const countBadge = document.createElement('span');
        countBadge.className = 'oc-nav-count';
        countBadge.textContent = String(count);
        btn.appendChild(countBadge);
      }

      btn.onclick = () => {
        visitStation(sec);
        selectedNodeContext = null;
        render();
      };

      btn.onkeydown = (e) => {
        let targetIdx = idx;
        if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
          e.preventDefault();
          targetIdx = (idx + 1) % SECTIONS.length;
        } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
          e.preventDefault();
          targetIdx = (idx - 1 + SECTIONS.length) % SECTIONS.length;
        } else if (e.key === 'Home') {
          e.preventDefault();
          targetIdx = 0;
        } else if (e.key === 'End') {
          e.preventDefault();
          targetIdx = SECTIONS.length - 1;
        }
        if (targetIdx !== idx) {
          const nextSec = SECTIONS[targetIdx];
          visitStation(nextSec);
          selectedNodeContext = null;
          render();
          const nextBtn = document.getElementById(`oc-nav-tab-${nextSec.toLowerCase()}`);
          nextBtn?.focus();
        }
      };

      li.appendChild(btn);
      navList.appendChild(li);
    });
    nav.appendChild(navList);

    // Content Container as TabPanel
    const content = document.createElement('main');
    content.id = 'oc-tabpanel-main';
    content.className = 'oc-content';
    content.setAttribute('role', 'tabpanel');
    content.setAttribute('aria-labelledby', `oc-nav-tab-${currentSection.toLowerCase()}`);

    if (genericFetchError) {
      const errAlert = document.createElement('div');
      errAlert.className = 'oc-alert oc-alert-error';
      errAlert.innerHTML = safeHtml`<strong>Error:</strong> ${genericFetchError}`;
      const retryScopeBtn = document.createElement('button');
      retryScopeBtn.className = 'oc-btn oc-btn-sm';
      retryScopeBtn.style.marginLeft = 'auto';
      retryScopeBtn.textContent = 'Retry Request';
      retryScopeBtn.onclick = () => fetchOperationsData(false);
      errAlert.appendChild(retryScopeBtn);
      content.appendChild(errAlert);
    }

    if (!snapshot) {
      const emptyCard = document.createElement('div');
      emptyCard.className = 'oc-card';
      emptyCard.innerHTML = safeHtml`<h3 class="oc-card-title">No Snapshot Loaded</h3>
        <p class="oc-card-body">Operations metadata is unavailable for the current scope (${selectedTenantScope ? 'Tenant: ' + selectedTenantScope : 'Server default'}).</p>`;
      const btnRow = document.createElement('div');
      btnRow.style.display = 'flex';
      btnRow.style.gap = '0.5rem';
      const retryBtn = document.createElement('button');
      retryBtn.id = 'oc-btn-empty-retry';
      retryBtn.className = 'oc-btn oc-btn-primary';
      retryBtn.textContent = 'Retry API Load';
      retryBtn.onclick = () => fetchOperationsData(false);
      btnRow.appendChild(retryBtn);

      if (!selectedTenantScope && expectedScopeMode !== 'local-private') {
        const fixtureBtn = document.createElement('button');
        fixtureBtn.id = 'oc-btn-empty-fixture';
        fixtureBtn.className = 'oc-btn';
        fixtureBtn.textContent = 'Load Public Fixture';
        fixtureBtn.onclick = () => fetchOperationsData(true);
        btnRow.appendChild(fixtureBtn);
      }
      emptyCard.appendChild(btnRow);
      content.appendChild(emptyCard);
    } else {
      switch (currentSection) {
        case 'Overview':
          content.appendChild(renderOverview());
          break;
        case 'Agents':
          content.appendChild(renderAgents());
          break;
        case 'Modules':
          content.appendChild(renderModules());
          break;
        case 'Runtimes':
          content.appendChild(renderRuntimes());
          break;
        case 'Connectors':
          content.appendChild(renderConnectors());
          break;
        case 'Tenants':
          content.appendChild(renderTenants());
          break;
        case 'Fleet':
          content.appendChild(renderFleet());
          break;
        case 'Activity':
          content.appendChild(renderActivity());
          break;
        case 'Workbench':
          content.appendChild(renderWorkbenchSection());
          break;
        case 'Evidence':
          content.appendChild(renderEvidence());
          break;
        case 'Resources':
          content.appendChild(renderResources());
          break;
      }
    }

    main.append(content);
    const drawer = document.createElement('section'); drawer.className = 'oc-cockpit'; drawer.dataset.station = currentSection.toLowerCase(); drawer.setAttribute('aria-label', `${STATION_NAMES[currentSection]} field drawer`);
    drawer.append(header, searchBox, contextBar, main);
    content.querySelectorAll<HTMLElement>('.oc-card').forEach(card => { const mark = document.createElement('span'); mark.className = 'oc-object-mark'; mark.append(toyIcon(currentSection)); card.prepend(mark); });
    rootEl.append(drawer, nav);
    // Stable identities keep keyboard focus across polling without relying on list position.
    const focusKeys = new Map<string, number>();
    rootEl.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], summary').forEach(control => {
      if (control.id) return;
      const cardTitle = control.closest('.oc-card, .oc-record-ticket, .oc-lantern-ticket')?.querySelector('h3, .oc-card-title, .oc-ticket-head')?.textContent || '';
      const label = control.getAttribute('aria-label') || control.textContent || control.getAttribute('name') || control.tagName;
      const key = `${currentSection}|${cardTitle.trim()}|${label.trim()}`;
      let hash = 2166136261;
      for (const char of key) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
      const count = focusKeys.get(key) || 0;
      focusKeys.set(key, count + 1);
      control.id = `oc-action-${(hash >>> 0).toString(36)}-${count}`;
    });

    content.scrollTop = prevScrollTop;

    // Focus/Cursor Restoration
    if (activeId) {
      const elToRestore = document.getElementById(activeId) || (focusWasInKit ? document.getElementById(`oc-nav-tab-${currentSection.toLowerCase()}`) : null);
      if (elToRestore) {
        elToRestore.focus();
        if (
          (elToRestore instanceof HTMLInputElement || elToRestore instanceof HTMLTextAreaElement) &&
          selStart !== null &&
          selEnd !== null
        ) {
          try {
            elToRestore.setSelectionRange(selStart, selEnd);
          } catch {}
        }
      }
    }
  }

  function getSectionCount(sec: SectionName): number | null {
    if (!snapshot) return null;
    switch (sec) {
      case 'Agents':
        return snapshot.catalog?.agents?.length || 0;
      case 'Modules':
        return snapshot.catalog?.cards?.length || 0;
      case 'Runtimes':
        return snapshot.catalog?.adapters?.length || 0;
      case 'Connectors':
        return Array.isArray(snapshot.catalog.connectors)
          ? snapshot.catalog.connectors.length
          : isRecord(snapshot.catalog.connectors)
          ? Object.keys(snapshot.catalog.connectors).length
          : 0;
      case 'Tenants':
        return snapshot.tenants?.length || 0;
      case 'Fleet':
        return snapshot.fleet?.length || 0;
      case 'Activity':
        return (
          (snapshot.activity?.events?.length || 0) +
          (snapshot.activity?.jobs?.length || 0) +
          (snapshot.activity?.artifacts?.length || 0) +
          (snapshot.activity?.approvals?.length || 0)
        );
      case 'Evidence':
        return snapshot.acceptance?.length || 0;
      case 'Resources':
        return snapshot.documents?.length || 0;
      default:
        return null;
    }
  }

  function renderGlobalSearchResults(query: string): HTMLElement | null {
    if (!snapshot) return null;
    const q = query.toLowerCase();
    const container = document.createElement('div');
    container.className = 'oc-search-dropdown';

    let matchesCount = 0;

    // Agents
    const agentMatches = (snapshot.catalog?.agents || []).filter(
      (a) => toStr(a.slug).toLowerCase().includes(q) || toStr(a.role).toLowerCase().includes(q)
    );
    if (agentMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Agents (${agentMatches.length})`;
      container.appendChild(gTitle);
      agentMatches.slice(0, 3).forEach((a) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(a.slug)}</span><span class="oc-search-item-sub">Role: ${toStr(a.role)}</span>`;
        item.onclick = () => {
          visitStation('Agents');
          selectedNodeContext = toStr(a.slug);
          globalSearchQuery = '';
          render();
        };
        container.appendChild(item);
      });
    }

    // Modules / Cards (all 135 searchable)
    const cardMatches = (snapshot.catalog?.cards || []).filter(
      (c) =>
        toStr(c.id).toLowerCase().includes(q) ||
        toStr(c.name).toLowerCase().includes(q) ||
        toStr(c.summary).toLowerCase().includes(q) ||
        toStr(c.body).toLowerCase().includes(q)
    );
    if (cardMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Modules (${cardMatches.length})`;
      container.appendChild(gTitle);
      cardMatches.slice(0, 4).forEach((c) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(c.name || c.id)}</span><span class="oc-search-item-sub">${toStr(c.category)} · ${toStr(c.disposition)}</span>`;
        item.onclick = () => {
          visitStation('Modules');
          Object.assign(moduleFilter, { search: toStr(c.id), category: 'all', disposition: 'all', risk: 'all', runtime: 'all', agent: 'all', tenant: 'all' });
          globalSearchQuery = '';
          render();
        };
        container.appendChild(item);
      });
    }

    // Adapters / Runtimes
    const adapterMatches = (snapshot.catalog?.adapters || []).filter(
      (ad) => toStr(ad.id).toLowerCase().includes(q) || toStr(ad.name).toLowerCase().includes(q)
    );
    if (adapterMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Adapters (${adapterMatches.length})`;
      container.appendChild(gTitle);
      adapterMatches.slice(0, 2).forEach((ad) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(ad.name || ad.id)}</span><span class="oc-search-item-sub">Mode: ${toStr(ad.plan_mode, 'default')}</span>`;
        item.onclick = () => {
          visitStation('Runtimes');
          globalSearchQuery = '';
          render();
        };
        container.appendChild(item);
      });
    }

    // Fleet Wings
    const fleetMatches = (snapshot.fleet || []).filter(
      (fl) => toStr(fl.id).toLowerCase().includes(q) || toStr(fl.name).toLowerCase().includes(q) || toStr(fl.wing).toLowerCase().includes(q)
    );
    if (fleetMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Fleet Wings (${fleetMatches.length})`;
      container.appendChild(gTitle);
      fleetMatches.slice(0, 2).forEach((fl) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(fl.name || fl.id)}</span><span class="oc-search-item-sub">Wing: ${toStr(fl.wing)}</span>`;
        item.onclick = () => {
          visitStation('Fleet');
          globalSearchQuery = '';
          render();
        };
        container.appendChild(item);
      });
    }

    // Acceptance Evidence
    const accMatches = (snapshot.acceptance || []).filter(
      (ev) => toStr(ev.id).toLowerCase().includes(q) || toStr(ev.criterion).toLowerCase().includes(q)
    );
    if (accMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Evidence Criteria (${accMatches.length})`;
      container.appendChild(gTitle);
      accMatches.slice(0, 2).forEach((ev) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(ev.id)}: ${toStr(ev.criterion)}</span><span class="oc-search-item-sub">Status: ${toStr(ev.status)}</span>`;
        item.onclick = () => {
          visitStation('Evidence');
          globalSearchQuery = '';
          render();
        };
        container.appendChild(item);
      });
    }

    // Documents
    const docMatches = (snapshot.documents || []).filter(
      (d) => toStr(d.path).toLowerCase().includes(q) || toStr(d.title).toLowerCase().includes(q)
    );
    if (docMatches.length > 0) {
      const gTitle = document.createElement('div');
      gTitle.className = 'oc-search-group-title';
      gTitle.textContent = `Documents (${docMatches.length})`;
      container.appendChild(gTitle);
      docMatches.slice(0, 3).forEach((d) => {
        matchesCount++;
        const item = document.createElement('button');
        item.className = 'oc-search-item';
        item.innerHTML = safeHtml`<span class="oc-search-item-title">${toStr(d.title || d.path)}</span><span class="oc-search-item-sub">${toStr(d.path)}</span>`;
        item.onclick = () => {
          globalSearchQuery = '';
          openDocViewer(toStr(d.path));
        };
        container.appendChild(item);
      });
    }

    for (const tab of ['events', 'jobs', 'artifacts', 'approvals'] as const) {
      const records = snapshot.activity[tab].filter(r => [r.id, r.summary, r.agent, r.status].some(value => toStr(value).toLowerCase().includes(q)));
      if (!records.length) continue;
      const group = document.createElement('div'); group.className = 'oc-search-group-title'; group.textContent = `${tab} (${records.length})`; container.appendChild(group);
      for (const record of records.slice(0, 3)) {
        matchesCount++;
        const button = document.createElement('button'); button.className = 'oc-search-item'; button.textContent = `${record.id} · ${record.summary}`;
        button.onclick = () => { visitStation('Activity'); activityFilter.tab = tab; activityFilter.search = record.id; activityFilter.tenant = 'all'; activityFilter.agent = 'all'; globalSearchQuery = ''; render(); };
        container.appendChild(button);
      }
    }
    if (matchesCount === 0) {
      const noRes = document.createElement('div');
      noRes.style.padding = '8px 12px';
      noRes.style.fontSize = '0.8rem';
      noRes.style.color = 'var(--oc-text-muted)';
      noRes.textContent = 'No matching operational entities found.';
      container.appendChild(noRes);
    }

    return container;
  }

  // Overview Section
function renderOverview(): HTMLElement {
  const frag = document.createElement('div');
  frag.style.display = 'flex';
  frag.style.flexDirection = 'column';
  frag.style.gap = '1.5rem';

  // Companion Greeting Hero Banner
  const welcomeBanner = document.createElement('section');
  welcomeBanner.className = 'oc-town-welcome';
  welcomeBanner.style.display = 'flex';
  welcomeBanner.style.alignItems = 'center';
  welcomeBanner.style.justifyContent = 'space-between';
  welcomeBanner.style.padding = '1.25rem 1.5rem';
  welcomeBanner.style.borderRadius = '16px';
  welcomeBanner.style.background = 'var(--oc-bg-surface, #fbf7ee)';
  welcomeBanner.style.border = '2px solid var(--oc-border-subtle, #e6ded0)';
  welcomeBanner.style.gap = '1.25rem';
  welcomeBanner.style.boxShadow = '0 3px 0 var(--oc-shadow-tactile, #ded5c2)';

  const welcomeText = document.createElement('div');
  welcomeText.innerHTML = safeHtml`
    <div style="font-size: 0.75rem; text-transform: uppercase; font-weight: 700; letter-spacing: 0.08em; color: var(--oc-text-muted, #7c7263); margin-bottom: 0.25rem;">Hello, explorer</div>
    <h2 style="margin: 0; font-family: var(--oc-font-title, inherit); font-size: 1.5rem; color: var(--oc-text-main, #24201b);">Your infrastructure, in miniature</h2>
    <div style="font-size: 0.88rem; color: var(--oc-text-muted, #7c7263); margin-top: 0.25rem;">Every little station opens a real piece of your infrastructure. Pick a token and follow its source notes.</div>
  `;

  const companion = document.createElement('div');
  companion.className = 'oc-companion';
  companion.style.display = 'flex';
  companion.style.alignItems = 'center';
  companion.style.gap = '0.75rem';
  companion.style.padding = '0.5rem 0.85rem';
  companion.style.borderRadius = '12px';
  companion.style.background = 'var(--oc-bg-well, #f0e9dc)';
  companion.style.border = '1.5px solid var(--oc-border-strong, #c8bea9)';

  const robotIcon = toyIcon('Agents');
  robotIcon.style.width = '96px';
  robotIcon.style.height = '96px';
  robotIcon.style.flexShrink = '0';
  robotIcon.style.color = 'var(--oc-color-orange, #d96b27)';

  const companionLabel = document.createElement('div');
  companionLabel.innerHTML = safeHtml`
    <div style="font-size: 0.7rem; text-transform: uppercase; font-weight: 700; color: var(--oc-text-muted, #7c7263);">Your guide</div>
    <div style="font-size: 0.85rem; font-weight: 700; color: var(--oc-text-main, #24201b);">Hermes Mini</div>
  `;
  companion.appendChild(robotIcon);
  companion.appendChild(companionLabel);

  welcomeBanner.appendChild(welcomeText);
  welcomeBanner.appendChild(companion);
  frag.appendChild(welcomeBanner);

  // Warnings Fold
  if (snapshot?.warnings && snapshot.warnings.length > 0) {
    const warnDetails = document.createElement('details');
    warnDetails.className = 'oc-fold-warnings';
    warnDetails.style.padding = '0.75rem 1rem';
    warnDetails.style.borderRadius = '12px';
    warnDetails.style.background = 'var(--oc-bg-warning-soft, #fff5eb)';
    warnDetails.style.border = '1.5px solid var(--oc-border-warning, #f0b884)';

    const warnSumm = document.createElement('summary');
    warnSumm.style.fontWeight = '700';
    warnSumm.style.cursor = 'pointer';
    warnSumm.style.fontSize = '0.85rem';
    warnSumm.style.color = 'var(--oc-color-warning-dark, #a3480a)';
    warnSumm.textContent = `Field notes to check (${snapshot.warnings.length} Active)`;
    warnDetails.appendChild(warnSumm);

    const warnList = document.createElement('div');
    warnList.style.marginTop = '0.5rem';
    warnList.style.display = 'flex';
    warnList.style.flexDirection = 'column';
    warnList.style.gap = '0.35rem';
    snapshot.warnings.forEach((w) => {
      const wItem = document.createElement('div');
      wItem.className = 'oc-alert oc-alert-warning';
      wItem.style.margin = '0';
      wItem.style.fontSize = '0.8rem';
      wItem.innerHTML = safeHtml`<strong>[${toStr(w.code)}]</strong> ${toStr(w.message)}`;
      warnList.appendChild(wItem);
    });
    warnDetails.appendChild(warnList);
    frag.appendChild(warnDetails);
  }

  // Station Tokens Grid
  const stationSection = document.createElement('div');
  const stationTitle = document.createElement('div');
  stationTitle.style.fontSize = '0.8rem';
  stationTitle.style.fontWeight = '700';
  stationTitle.style.textTransform = 'uppercase';
  stationTitle.style.letterSpacing = '0.06em';
  stationTitle.style.color = 'var(--oc-text-muted, #7c7263)';
  stationTitle.style.marginBottom = '0.75rem';
  stationTitle.textContent = 'Choose a station';
  stationSection.appendChild(stationTitle);

  const stationGrid = document.createElement('div');
  stationGrid.className = 'oc-station-grid';
  stationGrid.style.display = 'grid';
  stationGrid.style.gap = '0.85rem';

  const stationKeys: SectionName[] = [
    'Overview',
    'Agents',
    'Modules',
    'Runtimes',
    'Connectors',
    'Tenants',
    'Fleet',
    'Activity',
    'Workbench',
    'Evidence',
    'Resources'
  ];

  stationKeys.forEach((sec) => {
    const count = getSectionCount(sec);
    const isCurrent = currentSection === sec;
    const btn = document.createElement('button');
    btn.className = `oc-station-token ${isCurrent ? 'oc-station-token-active' : ''}`;
    btn.setAttribute('type', 'button');
    btn.setAttribute('aria-label', `${STATION_NAMES[sec]} Station`);
    btn.style.display = 'flex';
    btn.style.flexDirection = 'column';
    btn.style.alignItems = 'center';
    btn.style.justifyContent = 'center';
    btn.style.padding = '0.85rem 0.5rem';
    btn.style.gap = '0.4rem';
    btn.style.borderRadius = '14px';
    btn.style.background = isCurrent ? 'var(--oc-bg-active, #fdf1e4)' : 'var(--oc-bg-card, #ffffff)';
    btn.style.border = isCurrent ? '2px solid var(--oc-color-orange, #d96b27)' : '1.5px solid var(--oc-border-subtle, #e6ded0)';
    btn.style.boxShadow = isCurrent ? '0 3px 0 var(--oc-color-orange-dark, #b55318)' : '0 3px 0 var(--oc-shadow-tactile, #ded5c2)';
    btn.style.cursor = 'pointer';
    btn.style.textAlign = 'center';
    btn.onclick = () => { visitStation(sec); selectedNodeContext = null; render(); };

    const iconWrapper = document.createElement('div');
    iconWrapper.className = 'oc-object-mark';
    iconWrapper.style.width = '30px';
    iconWrapper.style.height = '30px';
    iconWrapper.style.color = isCurrent ? 'var(--oc-color-orange, #d96b27)' : 'var(--oc-color-forest, #2d5a3f)';
    const sIcon = toyIcon(sec);
    sIcon.style.width = '100%';
    sIcon.style.height = '100%';
    iconWrapper.appendChild(sIcon);
    btn.appendChild(iconWrapper);

    const label = document.createElement('span');
    label.className = 'oc-station-label';
    label.style.fontSize = '0.8rem';
    label.style.fontWeight = '700';
    label.style.color = 'var(--oc-text-main, #24201b)';
    label.textContent = STATION_NAMES[sec];
    btn.appendChild(label);

    if (count !== null) {
      const badge = document.createElement('span');
      badge.style.fontSize = '0.7rem';
      badge.style.fontWeight = '700';
      badge.style.padding = '0.1rem 0.45rem';
      badge.style.borderRadius = '999px';
      badge.style.background = 'var(--oc-bg-pill, #eee7da)';
      badge.style.color = 'var(--oc-text-muted, #7c7263)';
      badge.textContent = String(count);
      btn.appendChild(badge);
    }

    stationGrid.appendChild(btn);
  });
  stationSection.appendChild(stationGrid);
  frag.appendChild(stationSection);

  // Endpoint Lantern Tickets (Truthful endpoint-only telemetry)
  const lanternSection = document.createElement('section');
  lanternSection.innerHTML = safeHtml`
    <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.75rem;">
      <h3 style="font-family: var(--oc-font-title, inherit); font-size: 1.1rem; margin: 0; color: var(--oc-text-main, #24201b);">
        Endpoint Lanterns
      </h3>
      <span style="font-size: 0.75rem; color: var(--oc-text-muted, #7c7263); text-transform: uppercase; letter-spacing: 0.05em;">
        Endpoint observations only
      </span>
    </div>
  `;

  const lanternList = document.createElement('div');
  lanternList.className = 'oc-lantern-list';
  lanternList.style.display = 'grid';
  lanternList.style.gap = '0.85rem';

  const services = snapshot?.services || [];
  if (services.length === 0) {
    const emptyBox = document.createElement('div');
    emptyBox.style.gridColumn = '1 / -1';
    emptyBox.style.padding = '1.5rem';
    emptyBox.style.textAlign = 'center';
    emptyBox.style.background = 'var(--oc-bg-card, #ffffff)';
    emptyBox.style.borderRadius = '12px';
    emptyBox.style.border = '1px dashed var(--oc-border-subtle, #e6ded0)';
    emptyBox.style.color = 'var(--oc-text-muted, #7c7263)';
    emptyBox.textContent = 'No endpoint observations are available in this snapshot.';
    lanternList.appendChild(emptyBox);
  } else {
    services.forEach((srv) => {
      const ticket = document.createElement('article');
      ticket.className = 'oc-lantern-ticket';
      ticket.style.display = 'flex';
      ticket.style.flexDirection = 'column';
      ticket.style.padding = '0.85rem 1rem';
      ticket.style.borderRadius = '12px';
      ticket.style.background = 'var(--oc-bg-card, #ffffff)';
      ticket.style.border = '1.5px solid var(--oc-border-subtle, #e6ded0)';
      ticket.style.boxShadow = '0 2px 0 var(--oc-shadow-tactile, #ded5c2)';
      ticket.style.gap = '0.5rem';

      const stateClass = isStale ? 'oc-badge-stale' : `oc-badge-status-${srv.state}`;
      const headRow = document.createElement('div');
      headRow.style.display = 'flex';
      headRow.style.alignItems = 'center';
      headRow.style.justifyContent = 'space-between';
      headRow.style.gap = '0.5rem';
      headRow.innerHTML = safeHtml`
        <div style="font-weight: 700; font-size: 0.9rem; color: var(--oc-text-main, #24201b); display: flex; align-items: center; gap: 0.35rem;">
          <span class="oc-lantern-dot" style="display:inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${srv.state === 'reachable' ? 'var(--oc-color-forest, #2d5a3f)' : 'var(--oc-color-orange, #d96b27)'};"></span>
          ${toStr(srv.label || srv.id)}
        </div>
        <span class="oc-badge ${stateClass}" style="font-size: 0.7rem;">${isStale ? 'LAST KNOWN: ' : ''}${toStr(srv.state).toUpperCase()}</span>
      `;
      ticket.appendChild(headRow);

      const metaRow = document.createElement('div');
      metaRow.style.display = 'flex';
      metaRow.style.alignItems = 'center';
      metaRow.style.gap = '0.5rem';
      metaRow.style.fontSize = '0.75rem';
      metaRow.style.color = 'var(--oc-text-muted, #7c7263)';
      metaRow.innerHTML = safeHtml`
        <span>ID: <code>${toStr(srv.id)}</code></span>
        <span>•</span>
        <span>Scope: <em>${toStr(srv.scope, 'endpoint-only')}</em></span>
      `;
      ticket.appendChild(metaRow);

      // Folded Connection Details
      const details = document.createElement('details');
      details.style.marginTop = '0.25rem';
      details.style.fontSize = '0.75rem';
      details.style.color = 'var(--oc-text-muted, #7c7263)';

      const summary = document.createElement('summary');
      summary.style.cursor = 'pointer';
      summary.style.fontWeight = '600';
      summary.textContent = 'Connection notes';
      details.appendChild(summary);

      const detailsBody = document.createElement('div');
      detailsBody.style.paddingTop = '0.4rem';
      detailsBody.style.display = 'flex';
      detailsBody.style.flexDirection = 'column';
      detailsBody.style.gap = '0.25rem';
      detailsBody.innerHTML = safeHtml`
        <div>URL: <code style="word-break: break-all;">${toStr(srv.url)}</code></div>
        <div>Latency: <strong>${srv.latencyMs !== null ? srv.latencyMs + 'ms' : 'n/a'}</strong></div>
        <div>Checked: <strong>${toStr(srv.checkedAt || 'n/a')}</strong></div>
      `;
      details.appendChild(detailsBody);
      ticket.appendChild(details);

      lanternList.appendChild(ticket);
    });
  }
  lanternSection.appendChild(lanternList);
  frag.appendChild(lanternSection);

  return frag;
}

  // Agents Section
  function renderAgents(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Meet the crew</h2>
      <div class="oc-section-desc">Defined roles, verified skill routes, identity manifests, and direct module linkages</div>
    </div>`;

    if (selectedNodeContext) {
      const selBadge = document.createElement('div');
      selBadge.className = 'oc-alert oc-alert-info';
      selBadge.style.margin = '0';
      selBadge.innerHTML = safeHtml`Filtering Agent: <strong>${selectedNodeContext}</strong>`;
      const clearSelBtn = document.createElement('button');
      clearSelBtn.className = 'oc-btn oc-btn-sm';
      clearSelBtn.style.marginLeft = '0.5rem';
      clearSelBtn.textContent = '✕ Clear Selection';
      clearSelBtn.onclick = () => {
        selectedNodeContext = null;
        render();
      };
      selBadge.appendChild(clearSelBtn);
      secHeader.appendChild(selBadge);
    }
    frag.appendChild(secHeader);

    const agents = (snapshot?.catalog?.agents || []).filter((a) => {
      if (selectedNodeContext && toStr(a.slug).toLowerCase() !== selectedNodeContext.toLowerCase()) {
        return false;
      }
      return true;
    });

    const routingRules = toArr<Record<string, unknown>>(snapshot?.routing?.rules);
    const routingSkills = toArr<Record<string, unknown>>(snapshot?.routing?.skills);

    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    agents.forEach((ag) => {
      const slug = toStr(ag.slug);
      const card = document.createElement('div');
      card.className = 'oc-card';

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${slug.toUpperCase()}</h3>
        <div class="oc-card-subtitle">Layer: ${toStr(ag.layer)} · Declared Skills: ${ag.skill_count || 0}</div>
      </div>
      <span class="oc-badge oc-badge-scope-public">ROLE DEFINITION</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const roleP = document.createElement('p');
      roleP.innerHTML = safeHtml`<strong>Role:</strong> ${toStr(ag.role)}`;
      body.appendChild(roleP);

      const hooksList = toArr<string>(ag.hooks);
      const hooksP = document.createElement('p');
      hooksP.innerHTML = safeHtml`<strong>Hooks:</strong> ${hooksList.length > 0 ? hooksList.join(', ') : 'none'}`;
      body.appendChild(hooksP);

      const nativeBindings = routingSkills.filter(skill => toStr(skill.agent) === slug);
      const nativeP = document.createElement('p');
      nativeP.textContent = `Native Skills (${nativeBindings.length}): ${nativeBindings.map(skill => toStr(skill.id)).join(', ') || 'No native bindings declared'}`;
      body.appendChild(nativeP);

      // Routed Skills from snapshot.routing
      const agentRules = routingRules.filter((r) => toStr(r.agent).toLowerCase() === slug.toLowerCase());
      const routeSec = document.createElement('div');
      routeSec.style.marginTop = '0.5rem';
      routeSec.innerHTML = safeHtml`<div style="font-weight:700;font-size:0.8rem;text-transform:uppercase;color:var(--oc-forest);">Routed Skills (${agentRules.length})</div>`;
      
      if (agentRules.length === 0) {
        const noRules = document.createElement('div');
        noRules.style.fontSize = '0.78rem';
        noRules.style.color = 'var(--oc-text-muted)';
        noRules.textContent = 'No explicit routing rules assigned.';
        routeSec.appendChild(noRules);
      } else {
        const rUl = document.createElement('ul');
        rUl.style.paddingLeft = '1.2rem';
        rUl.style.margin = '4px 0 0 0';
        rUl.style.fontSize = '0.78rem';
        agentRules.forEach((rule) => {
          const li = document.createElement('li');
          const skillId = toArr<string>(rule.skills).join(', ');
          const hook = toStr(rule.hook);
          const globs = toArr<string>(rule.globs).join(', ');
          const src = toStr(rule.source);
          li.innerHTML = safeHtml`<code>${skillId || hook}</code> ${globs ? `[${globs}]` : ''} ${src ? `(src: ${src})` : ''}`;
          if (src && snapshot?.documents?.some((d) => d.path === src)) {
            const viewSrc = document.createElement('button');
            viewSrc.className = 'oc-btn oc-btn-sm';
            viewSrc.style.padding = '0 4px';
            viewSrc.style.marginLeft = '4px';
            viewSrc.textContent = 'doc';
            viewSrc.onclick = () => openDocViewer(src);
            li.appendChild(viewSrc);
          }
          rUl.appendChild(li);
        });
        routeSec.appendChild(rUl);
      }
      body.appendChild(routeSec);

      // Modules related to this agent
      const relatedCards = (snapshot?.catalog?.cards || []).filter((c) => {
        const cAgents = toArr<string>(c.agents).map((s) => toStr(s).toLowerCase());
        return cAgents.includes(slug.toLowerCase());
      });

      const relatedSec = document.createElement('div');
      relatedSec.style.marginTop = '0.5rem';
      relatedSec.innerHTML = safeHtml`<div style="font-weight:700;font-size:0.8rem;text-transform:uppercase;color:var(--oc-forest);">Catalog Modules for This Role (${relatedCards.length})</div>`;
      body.appendChild(relatedSec);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';

      // Identity Doc Link if registered
      const identityPath = `agents/${slug}/IDENTITY.md`;
      const hasIdentity = snapshot?.documents?.some((d) => d.path === identityPath);
      if (hasIdentity) {
        const docBtn = document.createElement('button');
        docBtn.id = `oc-doc-${identityPath}`;
        docBtn.className = 'oc-btn oc-btn-sm';
        docBtn.textContent = 'IDENTITY.md';
        docBtn.onclick = () => openDocViewer(identityPath);
        footer.appendChild(docBtn);
      }

      if (relatedCards.length > 0) {
        const filterModBtn = document.createElement('button');
        filterModBtn.className = 'oc-btn oc-btn-sm';
        filterModBtn.textContent = `Find parts (${relatedCards.length})`;
        filterModBtn.onclick = () => {
          moduleFilter.agent = slug;
          visitStation('Modules');
          render();
        };
        footer.appendChild(filterModBtn);
      }

      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to City';
      jumpBtn.onclick = () => jumpToBuilding(`agent-${slug}`);
      footer.appendChild(jumpBtn);


      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Modules Section (All 135 Searchable)
  function renderModules(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Parts chest</h2>
      <div class="oc-section-desc">Catalog cards with disposition, governance risk, runtime compatibility, and verified tenant enablement</div>
    </div>`;
    frag.appendChild(secHeader);

    const filterBar = document.createElement('div');
    filterBar.className = 'oc-filter-bar';

    const searchInp = document.createElement('input');
    searchInp.id = 'oc-module-search-input';
    searchInp.className = 'oc-input-text';
    searchInp.placeholder = 'Search id/name/summary/body...';
    searchInp.value = moduleFilter.search;
    searchInp.oninput = (e) => {
      moduleFilter.search = (e.target as HTMLInputElement).value;
      render();
    };
    filterBar.appendChild(searchInp);

    // Category Select
    const catSelect = document.createElement('select');
    catSelect.setAttribute('aria-label', 'Module category');
    catSelect.id = 'oc-module-category-select';
    catSelect.className = 'oc-filter-select';
    const categories = Array.from(
      new Set((snapshot?.catalog?.cards || []).map((c) => toStr(c.category)).filter(Boolean))
    ).sort();
    catSelect.innerHTML = safeHtml`<option value="all">All Categories (${categories.length})</option>`;
    categories.forEach((cat) => {
      const opt = document.createElement('option');
      opt.value = cat;
      opt.textContent = cat;
      catSelect.appendChild(opt);
    });
    catSelect.value = moduleFilter.category;
    catSelect.onchange = (e) => {
      moduleFilter.category = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(catSelect);

    // Disposition Select
    const dispSelect = document.createElement('select');
    dispSelect.setAttribute('aria-label', 'Module disposition');
    dispSelect.id = 'oc-module-disp-select';
    dispSelect.className = 'oc-filter-select';
    dispSelect.innerHTML = safeHtml`<option value="all">All Dispositions</option>
      <option value="add">add</option>
      <option value="pointer">pointer</option>
      <option value="hold">hold</option>
      <option value="refuse">refuse</option>`;
    dispSelect.value = moduleFilter.disposition;
    dispSelect.onchange = (e) => {
      moduleFilter.disposition = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(dispSelect);

    // Risk Select
    const riskSelect = document.createElement('select');
    riskSelect.setAttribute('aria-label', 'Module risk');
    riskSelect.id = 'oc-module-risk-select';
    riskSelect.className = 'oc-filter-select';
    riskSelect.innerHTML = safeHtml`<option value="all">All Risk Levels</option>
      <option value="low">low</option>
      <option value="medium">medium</option>
      <option value="high">high</option>`;
    riskSelect.value = moduleFilter.risk;
    riskSelect.onchange = (e) => {
      moduleFilter.risk = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(riskSelect);

    // Runtime Select
    const runtimes = Array.from(
      new Set((snapshot?.catalog?.adapters || []).map((a) => toStr(a.id)).filter(Boolean))
    ).sort();
    const runSelect = document.createElement('select');
    runSelect.setAttribute('aria-label', 'Module runtime');
    runSelect.id = 'oc-module-runtime-select';
    runSelect.className = 'oc-filter-select';
    runSelect.innerHTML = safeHtml`<option value="all">All Runtimes</option>`;
    runtimes.forEach((r) => {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = `Runtime: ${r}`;
      runSelect.appendChild(opt);
    });
    runSelect.value = moduleFilter.runtime;
    runSelect.onchange = (e) => {
      moduleFilter.runtime = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(runSelect);

    // Agent Filter Select
    const agentSelect = document.createElement('select');
    agentSelect.setAttribute('aria-label', 'Module agent');
    agentSelect.id = 'oc-module-agent-select';
    agentSelect.className = 'oc-filter-select';
    const agentSlugs = (snapshot?.catalog?.agents || []).map((a) => toStr(a.slug)).filter(Boolean);
    agentSelect.innerHTML = safeHtml`<option value="all">All Agents</option>`;
    agentSlugs.forEach((s) => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = `Agent: ${s}`;
      agentSelect.appendChild(opt);
    });
    agentSelect.value = moduleFilter.agent;
    agentSelect.onchange = (e) => {
      moduleFilter.agent = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(agentSelect);

    // Tenant Enablement Selector
    const tenantSelect = document.createElement('select');
    tenantSelect.setAttribute('aria-label', 'Module tenant enablement');
    tenantSelect.id = 'oc-module-tenant-select';
    tenantSelect.className = 'oc-filter-select';
    tenantSelect.innerHTML = safeHtml`<option value="all">Enablement: No Tenant Scoped (Unknown)</option>`;
    (snapshot?.tenants || []).forEach((t) => {
      const opt = document.createElement('option');
      opt.value = toStr(t.slug);
      opt.textContent = `Tenant: ${toStr(t.name || t.slug)}`;
      tenantSelect.appendChild(opt);
    });
    tenantSelect.value = moduleFilter.tenant;
    tenantSelect.onchange = (e) => {
      moduleFilter.tenant = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(tenantSelect);

    frag.appendChild(filterBar);

    const cards = snapshot?.catalog?.cards || [];
    const selectedTenantObj = (snapshot?.tenants || []).find((t) => toStr(t.slug) === moduleFilter.tenant);

    const filteredCards = cards.filter((c) => {
      const q = moduleFilter.search.toLowerCase().trim();
      if (q) {
        const matchId = toStr(c.id).toLowerCase().includes(q);
        const matchName = toStr(c.name).toLowerCase().includes(q);
        const matchSum = toStr(c.summary).toLowerCase().includes(q);
        const matchBody = toStr(c.body).toLowerCase().includes(q);
        if (!matchId && !matchName && !matchSum && !matchBody) return false;
      }
      if (moduleFilter.category !== 'all' && toStr(c.category) !== moduleFilter.category) return false;
      if (moduleFilter.disposition !== 'all' && toStr(c.disposition) !== moduleFilter.disposition) return false;
      if (moduleFilter.risk !== 'all' && toStr(c.risk) !== moduleFilter.risk) return false;
      if (moduleFilter.runtime !== 'all') {
        const cRuntimes = toArr<string>(c.runtimes).map(v => toStr(v));
        if (!cRuntimes.includes(moduleFilter.runtime)) {
          return false;
        }
      }
      if (moduleFilter.agent !== 'all') {
        const cAgents = toArr<string>(c.agents).map((s) => toStr(s).toLowerCase());
        if (!cAgents.includes(moduleFilter.agent.toLowerCase())) {
          return false;
        }
      }
      return true;
    });

    const countHeader = document.createElement('div');
    countHeader.style.fontSize = '0.85rem';
    countHeader.style.color = 'var(--oc-text-muted)';
    countHeader.textContent = `Showing ${filteredCards.length} of ${cards.length} module cards`;
    frag.appendChild(countHeader);

    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    filteredCards.forEach((c) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const disp = toStr(c.disposition);
      const isHeldOrRefused = disp === 'hold' || disp === 'refuse';
      const rawEnableable = Boolean(c.enableable);
      const catalogEnableable = rawEnableable && !isHeldOrRefused;

      let tenantEnabledBadge = '';
      if (!selectedTenantObj) {
        tenantEnabledBadge = 'TENANT: UNKNOWN (NO TENANT SELECTED)';
      } else {
        const enabledList = toArr<string>(selectedTenantObj.enabledModules);
        const isTenantEnabled = enabledList.includes(toStr(c.id));
        tenantEnabledBadge = isTenantEnabled
          ? 'TENANT: ENABLED'
          : 'TENANT: NOT ENABLED';
      }

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${toStr(c.name || c.id)}</h3>
        <div class="oc-card-subtitle">ID: ${toStr(c.id)} · Cat: ${toStr(c.category)}</div>
      </div>`;

      const badges = document.createElement('div');
      badges.className = 'oc-card-badges';

      const dispBadge = document.createElement('span');
      dispBadge.className = `oc-badge ${disp === 'refuse' ? 'oc-badge-status-unreachable' : disp === 'hold' ? 'oc-badge-status-warning' : 'oc-badge-status-reachable'}`;
      dispBadge.textContent = disp.toUpperCase();
      badges.appendChild(dispBadge);

      if (c.risk) {
        const riskBadge = document.createElement('span');
        riskBadge.className = 'oc-badge';
        riskBadge.textContent = `RISK: ${toStr(c.risk).toUpperCase()}`;
        badges.appendChild(riskBadge);
      }

      const enableBadge = document.createElement('span');
      enableBadge.className = `oc-badge ${catalogEnableable ? 'oc-badge-status-reachable' : 'oc-badge-status-unreachable'}`;
      enableBadge.textContent = `CATALOG: ${catalogEnableable ? 'ENABLEABLE' : 'NON-ENABLEABLE'}`;
      badges.appendChild(enableBadge);

      header.appendChild(badges);

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const sumP = document.createElement('p');
      sumP.textContent = toStr(c.summary);
      body.appendChild(sumP);

      const metaBlock = document.createElement('div');
      metaBlock.style.marginTop = '6px';
      metaBlock.style.fontSize = '0.78rem';
      metaBlock.style.color = 'var(--oc-text-muted)';
      metaBlock.innerHTML = safeHtml`<div><strong>Approval Required:</strong> ${toStr(c.approval, 'no')}</div>
        <div><strong>Runtime Installation:</strong> Not verified by this source snapshot</div>
        <div style="margin-top:4px;">${tenantEnabledBadge}</div>`;
      body.appendChild(metaBlock);

      // Card details accordion for body/provenance/hooks
      const details = document.createElement('details');
      details.style.marginTop = '8px';
      details.style.fontSize = '0.8rem';
      const summaryEl = document.createElement('summary');
      summaryEl.style.cursor = 'pointer';
      summaryEl.style.fontWeight = '700';
      summaryEl.style.color = 'var(--oc-forest)';
      summaryEl.textContent = 'View Card Specification & Hooks';
      details.appendChild(summaryEl);

      const detailsContent = document.createElement('div');
      detailsContent.style.padding = '6px 0';
      if (c.body) {
        const bodyPre = document.createElement('pre');
        bodyPre.className = 'oc-pre';
        bodyPre.style.maxHeight = '140px';
        bodyPre.textContent = toStr(c.body);
        detailsContent.appendChild(bodyPre);
      }
      if (c.source) {
        const provDiv = document.createElement('div');
        provDiv.innerHTML = safeHtml`<strong>Provenance:</strong> ${toStr(c.source)}`;
        detailsContent.appendChild(provDiv);
      }
      if (c.hooks) {
        const hooksDiv = document.createElement('div');
        hooksDiv.innerHTML = safeHtml`<strong>Hooks:</strong> ${toArr(c.hooks).join(', ')}`;
        detailsContent.appendChild(hooksDiv);
      }
      details.appendChild(detailsContent);
      body.appendChild(details);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';

      const rawSrc = toStr(c.source || c.repo);
      if (rawSrc && snapshot?.documents?.some((d) => d.path === rawSrc)) {
        const docBtn = document.createElement('button');
        docBtn.className = 'oc-btn oc-btn-sm oc-btn-primary';
        docBtn.textContent = 'View Registered Doc';
        docBtn.onclick = () => openDocViewer(rawSrc);
        footer.appendChild(docBtn);
      } else {
        const safeExternal = sanitizeUrl(rawSrc);
        if (safeExternal) {
          const extLink = document.createElement('a');
          extLink.className = 'oc-btn oc-btn-sm';
          extLink.href = safeExternal;
          extLink.target = '_blank';
          extLink.rel = 'noopener noreferrer';
          extLink.textContent = '↗ Source Repo';
          footer.appendChild(extLink);
        }
      }

      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Catalog';
      jumpBtn.onclick = () => jumpToBuilding('module-catalog');
      footer.appendChild(jumpBtn);

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Runtimes Section
  function renderRuntimes(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Platforms</h2>
      <div class="oc-section-desc">Format matrix (object), MCP skill paths, plan modes, and read-only install instructions</div>
    </div>`;
    frag.appendChild(secHeader);

    const adapters = snapshot?.catalog?.adapters || [];
    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    adapters.forEach((ad) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${toStr(ad.name || ad.id)}</h3>
        <div class="oc-card-subtitle">ID: ${toStr(ad.id)} · Plan Mode: ${toStr(ad.plan_mode, 'default')}</div>
      </div>
      <span class="oc-badge">ADAPTER</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      // Formats is an object shape
      const formatsObj = isRecord(ad.formats) ? ad.formats : { formats: ad.formats };
      const formatsP = document.createElement('div');
      formatsP.style.fontSize = '0.8rem';
      formatsP.innerHTML = safeHtml`<strong>Formats Matrix:</strong>
        <pre class="oc-pre" style="margin:4px 0;">${prettyJson(formatsObj)}</pre>`;
      body.appendChild(formatsP);

      if (ad.paths) {
        const pathsP = document.createElement('div');
        pathsP.style.fontSize = '0.8rem';
        pathsP.innerHTML = safeHtml`<strong>Skill / MCP / Rules Paths:</strong>
          <pre class="oc-pre" style="margin:4px 0;">${prettyJson(ad.paths)}</pre>`;
        body.appendChild(pathsP);
      }

      if (ad.question_tool !== undefined || ad.verify !== undefined) {
        const verifyDiv = document.createElement('div');
        verifyDiv.style.fontSize = '0.78rem';
        verifyDiv.style.color = 'var(--oc-text-muted)';
        verifyDiv.style.marginTop = '4px';
        const unverifiedFields = ad.verify === true ? 'Entire adapter definition' : isRecord(ad.verify) ? Object.entries(ad.verify).filter(([, pending]) => pending === true).map(([field]) => field).join(', ') : '';
        verifyDiv.innerHTML = safeHtml`<div><strong>Question Tool:</strong> ${toStr(ad.question_tool, 'n/a')}</div>
          <div><strong>Fields Still to Verify:</strong> ${unverifiedFields || 'No unconfirmed fields declared'}</div>
          <div>Runtime installation has not been observed by this workspace.</div>`;
        body.appendChild(verifyDiv);
      }

      const notesP = document.createElement('p');
      notesP.style.margin = '6px 0 0 0';
      notesP.innerHTML = safeHtml`<strong>Notes:</strong> ${toStr(ad.notes, 'None specified')}`;
      body.appendChild(notesP);

      const installSteps = toArr<string>(ad.install);
      const installDiv = document.createElement('div');
      installDiv.style.marginTop = '6px';
      installDiv.innerHTML = safeHtml`<strong>Install Instructions (Read-Only):</strong>
        <pre class="oc-pre" style="margin:4px 0;">${installSteps.join('\n') || '# No specific install instructions'}</pre>`;
      body.appendChild(installDiv);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';
      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Runtimes';
      jumpBtn.onclick = () => jumpToBuilding('runtime-adapters');
      footer.appendChild(jumpBtn);

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Connectors Section
  function renderConnectors(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Signal plugs</h2>
      <div class="oc-section-desc">Structured authentication models, connector capabilities, and tenant gating states</div>
    </div>`;
    frag.appendChild(secHeader);

    const rawConnectors = snapshot?.catalog.connectors;
    const connList: Array<{ id: string; auth?: unknown; capabilities?: unknown; raw: unknown }> = [];
    if (Array.isArray(rawConnectors)) {
      rawConnectors.forEach((c) => {
        if (isRecord(c)) connList.push({ id: toStr(c.id || c.name), auth: c.auth, capabilities: c.capabilities, raw: c });
      });
    } else if (isRecord(rawConnectors)) {
      Object.entries(rawConnectors).forEach(([k, v]) => {
        if (isRecord(v)) connList.push({ id: k, auth: v.auth, capabilities: v.capabilities, raw: v });
        else connList.push({ id: k, capabilities: v, raw: v });
      });
    }

    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    connList.forEach((conn) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${conn.id.toUpperCase()}</h3>
        <div class="oc-card-subtitle">Gateway Connector</div>
      </div>
      <span class="oc-badge">GATEWAY</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const authBlock = document.createElement('div');
      authBlock.style.fontSize = '0.8rem';
      authBlock.innerHTML = safeHtml`<strong>Authentication Configuration:</strong>
        <pre class="oc-pre" style="margin:4px 0;">${isRecord(conn.auth) ? prettyJson(conn.auth) : toStr(conn.auth, 'None / Open')}</pre>`;
      body.appendChild(authBlock);

      const capBlock = document.createElement('div');
      capBlock.style.fontSize = '0.8rem';
      capBlock.style.marginTop = '6px';
      capBlock.innerHTML = safeHtml`<strong>Capabilities & Gate Policies:</strong>
        <pre class="oc-pre" style="margin:4px 0;">${isRecord(conn.capabilities) || Array.isArray(conn.capabilities) ? prettyJson(conn.capabilities) : toStr(conn.capabilities, 'standard')}</pre>`;
      body.appendChild(capBlock);

      const stateDiv = document.createElement('div');
      stateDiv.style.fontSize = '0.78rem';
      stateDiv.style.color = 'var(--oc-text-muted)';
      stateDiv.style.marginTop = '6px';
      stateDiv.textContent = 'Connection Status: Not observed. Capability definitions do not verify credentials or live access.';
      body.appendChild(stateDiv);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';
      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Connector Gate';
      jumpBtn.onclick = () => jumpToBuilding('connector-gate');
      footer.appendChild(jumpBtn);

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Tenants Section
  function renderTenants(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Neighborhoods</h2>
      <div class="oc-section-desc">Tenant enablements, assigned agents, approval records, and source metadata</div>
    </div>`;
    frag.appendChild(secHeader);

    const tenants = snapshot?.tenants || [];
    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    tenants.forEach((t) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const slug = toStr(t.slug);
      const enabled = toArr<string>(t.enabledModules);
      const ags = toArr<string>(t.agents);

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${toStr(t.name || t.slug)}</h3>
        <div class="oc-card-subtitle">Slug: ${slug} · Runtime: ${toStr(t.primaryRuntime, 'Unconfigured')}</div>
      </div>
      <span class="oc-badge oc-badge-scope-private">TENANT VAULT</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const modP = document.createElement('p');
      modP.innerHTML = safeHtml`<strong>Enabled Modules (${enabled.length}):</strong> ${enabled.join(', ') || 'None'}`;
      body.appendChild(modP);

      const agP = document.createElement('p');
      agP.innerHTML = safeHtml`<strong>Assigned Agents (${ags.length}):</strong> ${ags.join(', ') || 'None'}`;
      body.appendChild(agP);

      const appP = document.createElement('div');
      appP.style.fontSize = '0.8rem';
      appP.innerHTML = safeHtml`<strong>Approval Counts:</strong>
        <pre class="oc-pre" style="margin:4px 0;">${isRecord(t.approvalCounts) ? prettyJson(t.approvalCounts) : toStr(t.approvalCounts, '0')}</pre>`;
      body.appendChild(appP);

      const availP = document.createElement('p');
      availP.style.margin = '4px 0 0 0';
      availP.innerHTML = safeHtml`<strong>Dataset:</strong> ${toStr(t.availability, 'unavailable')} · <strong>Registered Sources:</strong> ${t.sourceCount}`;
      body.appendChild(availP);
      body.appendChild(renderBrandPassport(t));
      const provenanceP = document.createElement('p');
      provenanceP.textContent = `Source References: ${t.sources.join(', ') || 'None available'}`;
      body.appendChild(provenanceP);
      if (t.warnings.length) {
        const warningsP = document.createElement('p');
        warningsP.className = 'oc-alert oc-alert-warning';
        warningsP.textContent = t.warnings.join(' · ');
        body.appendChild(warningsP);
      }

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';

      const filterModsBtn = document.createElement('button');
      filterModsBtn.className = 'oc-btn oc-btn-sm';
      filterModsBtn.textContent = `Find parts`;
      filterModsBtn.onclick = () => {
        moduleFilter.tenant = slug;
        visitStation('Modules');
        render();
      };
      footer.appendChild(filterModsBtn);

      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Tenant Vault';
      jumpBtn.onclick = () => jumpToBuilding('tenant-vault');
      footer.appendChild(jumpBtn);
      for (const [label, section, node] of [['Knowledge Archive', 'Resources', 'knowledge-archive'], ['Brand blueprints', 'Workbench', 'chief-of-staff']] as const) {
        const button = document.createElement('button'); button.className = 'oc-btn oc-btn-sm'; button.textContent = label;
        button.onclick = () => { visitStation(section, node); render(); }; footer.appendChild(button);
      }

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Fleet Section
  function renderFleet(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Fleet archipelago</h2>
      <div class="oc-section-desc">Four island towns, three role profiles, and source evidence for the fleet</div>
    </div>`;
    frag.appendChild(secHeader);

    const islandChart = document.createElement('section');
    islandChart.className = 'oc-island-chart';
    islandChart.setAttribute('aria-label', 'Four Mac mini island slots');
    const chartHeading = document.createElement('h3');
    chartHeading.className = 'oc-island-chart-title';
    chartHeading.textContent = 'Two Coding · One Creative · One Marketing';
    const chartNote = document.createElement('p');
    chartNote.className = 'oc-island-chart-note';
    chartNote.textContent = 'Visit each island to explore its town. Inventory assignment and current work evidence are separate. Brand stations are shared portfolio sources without a device assignment.';
    const islandGrid = document.createElement('div');
    islandGrid.className = 'oc-island-grid';
    const generatedMs = Date.parse(snapshot?.generatedAt || '');
    const age = Date.now() - generatedMs;
    const workStale = isStale || lastLoadedSource === 'fixture' || !Number.isFinite(age) || age < 0 || age > 120000;
    for (const node of fleetNodes(snapshot)) {
      const slot = document.createElement('article');
      slot.className = 'oc-island-slot';
      slot.dataset.wing = node.wing;
      slot.dataset.assignment = node.assignment;
      const name = document.createElement('h4');
      name.textContent = node.name;
      const assignment = document.createElement('span');
      assignment.className = 'oc-island-assignment';
      assignment.textContent = node.assignment === 'configured' ? 'Configured inventory slot' : node.assignment === 'template' ? 'Public template' : 'Planned · Device pending';
      const presence = derivePresence(snapshot ? { ...snapshot, activity: fleetActivity(snapshot, node.id) } : null, Date.now(), workStale || node.assignment === 'planned');
      const observed = presence.filter(item => item.evidence === 'observed');
      const work = document.createElement('p');
      work.textContent = observed.length ? `Work observed · ${observed.filter(item => item.state === 'active').length} active crew` : 'Work unknown · No current device-bound activity';
      const role = document.createElement('p');
      role.className = 'oc-island-role';
      role.textContent = `Role: ${node.wing === 'design' ? 'Creative' : node.wing === 'coding' ? 'Coding' : 'Marketing'} · Profile: ${node.profileId}`;
      const visit = document.createElement('button');
      visit.type = 'button';
      visit.className = 'oc-btn oc-btn-sm oc-island-visit';
      visit.textContent = `Visit ${node.name}`;
      visit.onclick = () => host.dispatchEvent(new CustomEvent('fleet-visit', { bubbles: true, detail: { id: node.id } }));
      slot.append(name, assignment, role, work, visit);
      islandGrid.appendChild(slot);
    }
    islandChart.append(chartHeading, chartNote, islandGrid);
    frag.appendChild(islandChart);

    const profilesHeading = document.createElement('h3');
    profilesHeading.className = 'oc-section-title';
    profilesHeading.textContent = 'Wing profile contracts';
    frag.appendChild(profilesHeading);

    const setup = document.createElement('button'); setup.className = 'oc-btn'; setup.textContent = 'New Mac setup guide';
    setup.onclick = () => { void openDocViewer('docs/OPS-WORKSPACE.md'); }; frag.appendChild(setup);
    const fleet = snapshot?.fleet || [];
    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    fleet.forEach((fl) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${toStr(fl.name || fl.id)}</h3>
        <div class="oc-card-subtitle">Wing: ${toStr(fl.wing)} · Runtime: ${toStr(fl.runtime)}</div>
      </div>
      <span class="oc-badge">FLEET WING</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const profP = document.createElement('p');
      profP.innerHTML = safeHtml`<strong>Profile:</strong> ${prettyJson(fl.profile)}`;
      body.appendChild(profP);

      const evP = document.createElement('p');
      evP.innerHTML = safeHtml`<strong>Profile Evidence:</strong> ${fl.evidence === 'local' ? 'Local instance metadata' : fl.evidence === 'source' ? 'Source definition' : 'Pending'} · Device execution is tracked separately in the evidence ledger.`;
      body.appendChild(evP);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';

      const recDocPath = snapshot?.documents.find(d => d.path === 'docs/fleet/09-RUNTIME-SUPERVISOR.md')?.path || '';
      if (recDocPath && snapshot?.documents?.some((d) => d.path === recDocPath)) {
        const recBtn = document.createElement('button');
        recBtn.className = 'oc-btn oc-btn-sm oc-btn-primary';
        recBtn.textContent = 'Recovery Doc';
        recBtn.onclick = () => openDocViewer(recDocPath);
        footer.appendChild(recBtn);
      }

      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Wings';
      jumpBtn.onclick = () => jumpToBuilding('fleet-wings');
      footer.appendChild(jumpBtn);

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    const contracts = document.createElement('div');
    contracts.className = 'oc-card';
    const contractsTitle = document.createElement('h3');
    contractsTitle.className = 'oc-card-title';
    contractsTitle.textContent = 'Sessions & Recovery Contracts';
    const contractsNote = document.createElement('p');
    contractsNote.textContent = 'Session supervision and cloud recovery have source contracts. This workspace has no session execution or restore control API. Company deployment, provider admission, and physical recovery require their own evidence.';
    const contractsLinks = document.createElement('div');
    contractsLinks.className = 'oc-card-footer';
    for (const [label, path] of [
      ['Runtime Supervisor', 'docs/fleet/09-RUNTIME-SUPERVISOR.md'],
      ['Cloud Gateway & Recovery', 'docs/fleet/08-CLOUD-GATEWAY.md'],
      ['Session World', 'docs/SESSION-WORLD-DESIGN.md'],
      ['Control Plane Plan', 'docs/FLEET-CONTROL-PLANE-PLAN.md'],
    ]) {
      if (!snapshot?.documents.some(doc => doc.path === path)) continue;
      const button = document.createElement('button');
      button.id = `oc-doc-${path}`;
      button.className = 'oc-btn oc-btn-sm';
      button.textContent = label;
      button.onclick = () => openDocViewer(path);
      contractsLinks.appendChild(button);
    }
    const evidenceButton = document.createElement('button');
    evidenceButton.className = 'oc-btn oc-btn-sm';
    evidenceButton.textContent = 'Review Open Evidence';
    evidenceButton.onclick = () => { visitStation('Evidence'); evidenceFilter.status = 'open'; render(); };
    contractsLinks.appendChild(evidenceButton);
    contracts.append(contractsTitle, contractsNote, contractsLinks);
    frag.appendChild(contracts);
    return frag;
  }

  // Activity Section
function renderActivity(): HTMLElement {
  const frag = document.createElement('div');
  frag.style.display = 'flex';
  frag.style.flexDirection = 'column';
  frag.style.gap = '1.25rem';

  const secHeader = document.createElement('div');
  secHeader.className = 'oc-section-header';
  secHeader.innerHTML = safeHtml`<div>
    <h2 class="oc-section-title">Courier trail</h2>
    <div class="oc-section-desc">Scoped projection trail of courier events, jobs, artifacts, and approvals</div>
  </div>`;
  frag.appendChild(secHeader);

  const filterBar = document.createElement('div');
  filterBar.className = 'oc-filter-bar';

  // Tab selection
  (['events', 'jobs', 'artifacts', 'approvals'] as const).forEach((t) => {
    const btn = document.createElement('button');
    btn.id = `oc-activity-tab-${t}`;
    btn.className = `oc-btn oc-btn-sm ${activityFilter.tab === t ? 'oc-btn-primary' : ''}`;
    btn.textContent = t.toUpperCase();
    btn.onclick = () => {
      activityFilter.tab = t;
      render();
    };
    filterBar.appendChild(btn);
  });

  // Activity search filter
  const searchInp = document.createElement('input');
  searchInp.id = 'oc-activity-search-input';
  searchInp.className = 'oc-input-text';
  searchInp.placeholder = 'Filter activity text...';
  searchInp.value = activityFilter.search;
  searchInp.oninput = (e) => {
    activityFilter.search = (e.target as HTMLInputElement).value;
    render();
  };
  filterBar.appendChild(searchInp);

  // Tenant select
  const tenantSel = document.createElement('select');
  tenantSel.id = 'oc-activity-tenant-select';
  tenantSel.className = 'oc-filter-select';
  tenantSel.innerHTML = safeHtml`<option value="all">All Tenants</option>`;
  (snapshot?.tenants || []).forEach((t) => {
    const opt = document.createElement('option');
    opt.value = toStr(t.slug);
    opt.textContent = `Tenant: ${toStr(t.slug)}`;
    tenantSel.appendChild(opt);
  });
  tenantSel.value = activityFilter.tenant;
  tenantSel.onchange = (e) => {
    activityFilter.tenant = (e.target as HTMLSelectElement).value;
    render();
  };
  filterBar.appendChild(tenantSel);

  // Agent select
  const agentSel = document.createElement('select');
  agentSel.id = 'oc-activity-agent-select';
  agentSel.className = 'oc-filter-select';
  agentSel.innerHTML = safeHtml`<option value="all">All Agents</option>`;
  (snapshot?.catalog?.agents || []).forEach((a) => {
    const opt = document.createElement('option');
    opt.value = toStr(a.slug);
    opt.textContent = `Agent: ${toStr(a.slug)}`;
    agentSel.appendChild(opt);
  });
  agentSel.value = activityFilter.agent;
  agentSel.onchange = (e) => {
    activityFilter.agent = (e.target as HTMLSelectElement).value;
    render();
  };
  filterBar.appendChild(agentSel);

  // Status select
  const statusSel = document.createElement('select');
  statusSel.id = 'oc-activity-status-select';
  statusSel.className = 'oc-filter-select';
  statusSel.setAttribute('aria-label', 'Activity status');
  const allStatus = document.createElement('option');
  allStatus.value = 'all';
  allStatus.textContent = 'All Statuses';
  statusSel.appendChild(allStatus);
  const statuses = new Set((snapshot?.activity?.[activityFilter.tab] || []).map(item => item.status));
  for (const status of [...statuses].sort()) {
    const opt = document.createElement('option');
    opt.value = status;
    opt.textContent = status;
    statusSel.appendChild(opt);
  }
  statusSel.value = statuses.has(activityFilter.status) ? activityFilter.status : 'all';
  statusSel.onchange = () => { activityFilter.status = statusSel.value; render(); };
  filterBar.appendChild(statusSel);

  frag.appendChild(filterBar);

  const rawActivityData = snapshot?.activity ? snapshot.activity[activityFilter.tab] || [] : [];
  const normalizedList: ActivityRowItem[] = toArr<Record<string, unknown>>(rawActivityData).map((item) => ({
    id: toStr(item.id),
    timestamp: toStr(item.timestamp || item.created || item.time),
    tenant: toStr(item.tenant),
    agent: toStr(item.agent),
    summary: toStr(item.summary || item.title || item.name || item.action),
    status: toStr(item.status || 'unknown'),
    jobId: toStr(item.jobId),
    artifactId: toStr(item.artifactId),
    source: toStr(toArr<string>(item.sources)[0]),
    payload: item,
  }));

  const filteredData = normalizedList.filter((act) => {
    const q = activityFilter.search.toLowerCase().trim();
    if (q) {
      const matchId = act.id.toLowerCase().includes(q);
      const matchSum = (act.summary || '').toLowerCase().includes(q);
      if (!matchId && !matchSum) return false;
    }
    if (activityFilter.tenant !== 'all' && act.tenant !== activityFilter.tenant) return false;
    if (activityFilter.agent !== 'all' && act.agent !== activityFilter.agent) return false;
    if (statuses.has(activityFilter.status) && act.status !== activityFilter.status) return false;
    return true;
  });

  const ticketList = document.createElement('div');
  ticketList.className = 'oc-ticket-list';
  ticketList.style.display = 'flex';
  ticketList.style.flexDirection = 'column';
  ticketList.style.gap = '0.75rem';

  if (filteredData.length === 0) {
    const emptyCard = document.createElement('div');
    emptyCard.style.padding = '1.75rem';
    emptyCard.style.textAlign = 'center';
    emptyCard.style.borderRadius = '12px';
    emptyCard.style.border = '1px dashed var(--oc-border-subtle, #e6ded0)';
    emptyCard.style.color = 'var(--oc-text-muted, #7c7263)';
    emptyCard.style.background = 'var(--oc-bg-surface, #fbf7ee)';
    emptyCard.textContent = rawActivityData.length
      ? 'No activity records match the selected filters.'
      : `No scoped ${activityFilter.tab} records are available in this snapshot. This view shows projected records, not a live execution feed.`;
    ticketList.appendChild(emptyCard);
  } else {
    filteredData.forEach((act) => {
      const ticket = document.createElement('article');
      ticket.className = 'oc-record-ticket';
      ticket.style.display = 'flex';
      ticket.style.flexDirection = 'column';
      ticket.style.padding = '0.9rem 1.15rem';
      ticket.style.borderRadius = '14px';
      ticket.style.background = 'var(--oc-bg-card, #ffffff)';
      ticket.style.border = '1.5px solid var(--oc-border-subtle, #e6ded0)';
      ticket.style.boxShadow = '0 3px 0 var(--oc-shadow-tactile, #ded5c2)';
      ticket.style.gap = '0.5rem';

      const head = document.createElement('div');
      head.className = 'oc-ticket-head';
      head.style.display = 'flex';
      head.style.alignItems = 'center';
      head.style.justifyContent = 'space-between';
      head.style.gap = '0.75rem';

      const titleBox = document.createElement('div');
      titleBox.style.display = 'flex';
      titleBox.style.alignItems = 'center';
      titleBox.style.gap = '0.5rem';
      titleBox.innerHTML = safeHtml`
        <span class="oc-object-mark" style="display:inline-flex; width:20px; height:20px; color:var(--oc-color-orange, #d96b27);"></span>
        <code style="font-weight:700;">${act.id}</code>
        <span style="font-weight:600; color:var(--oc-text-main, #24201b); font-size: 0.9rem;">${act.summary || '—'}</span>
      `;
      const iconSlot = titleBox.querySelector('.oc-object-mark')!;
      iconSlot.appendChild(toyIcon('Activity'));
      head.appendChild(titleBox);

      const stamp = document.createElement('span');
      stamp.className = 'oc-ticket-stamp oc-badge';
      stamp.style.textTransform = 'uppercase';
      stamp.style.fontSize = '0.75rem';
      stamp.textContent = act.status || 'n/a';
      head.appendChild(stamp);
      ticket.appendChild(head);

      const meta = document.createElement('div');
      meta.className = 'oc-ticket-meta';
      meta.style.display = 'flex';
      meta.style.alignItems = 'center';
      meta.style.justifyContent = 'space-between';
      meta.style.flexWrap = 'wrap';
      meta.style.gap = '0.5rem';
      meta.style.fontSize = '0.78rem';
      meta.style.color = 'var(--oc-text-muted, #7c7263)';

      const tags = document.createElement('div');
      tags.style.display = 'flex';
      tags.style.gap = '0.75rem';
      tags.innerHTML = safeHtml`
        <span>Time: <strong>${act.timestamp || '—'}</strong></span>
        <span>Tenant: <strong>${act.tenant || '—'}</strong></span>
        <span>Agent: <strong>${act.agent || '—'}</strong></span>
      `;
      meta.appendChild(tags);

      const viewBtn = document.createElement('button');
      viewBtn.className = 'oc-btn oc-btn-sm';
      viewBtn.textContent = 'View Envelope';
      viewBtn.onclick = () => openActivityDialog(act);
      meta.appendChild(viewBtn);

      ticket.appendChild(meta);
      ticketList.appendChild(ticket);
    });
  }

  frag.appendChild(ticketList);
  return frag;
}

  // Workbench Section
  function renderWorkbenchSection(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1.5rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Blueprint bench</h2>
      <div class="oc-section-desc">Read-only planning simulation with tenant context, route projection, step verification, and authorization guarantees</div>
    </div>`;
    frag.appendChild(secHeader);

    // Display Server Authorized Capabilities Status Card (No mutations allowed)
    const capCard = document.createElement('div');
    capCard.className = 'oc-card';
    capCard.innerHTML = safeHtml`<h3 class="oc-card-title">Sketch a mission</h3><p class="oc-card-body">Choose a neighborhood and collect the parts. The bench returns a paper proposal with real route and enablement decisions; execution, enabling and approval remain separate.</p>`;
    frag.appendChild(capCard);

    const isDisconnected = isStale || lastLoadedSource === 'fixture';
    if (isDisconnected) {
      const warn = document.createElement('div');
      warn.className = 'oc-alert oc-alert-warning';
      warn.innerHTML = safeHtml`<strong>Plan simulation offline:</strong> Fallback fixture active or disconnected. Plan preview requires active connected API verification.`;
      frag.appendChild(warn);
    }

    const form = document.createElement('div');
    form.className = 'oc-card oc-blueprint-board';
    form.style.display = 'flex';
    form.style.flexDirection = 'column';
    form.style.gap = '1rem';

    // Tenant select (required)
    const tenantGroup = document.createElement('div');
    tenantGroup.className = 'oc-form-group';
    tenantGroup.innerHTML = safeHtml`<label class="oc-form-label" for="oc-wb-tenant-select">Target Tenant * (Required)</label>`;
    const tenantSel = document.createElement('select');
    tenantSel.id = 'oc-wb-tenant-select';
    tenantSel.className = 'oc-filter-select';
    tenantSel.innerHTML = safeHtml`<option value="">-- Select Target Tenant --</option>`;
    (snapshot?.tenants || []).forEach((t) => {
      const opt = document.createElement('option');
      opt.value = toStr(t.slug);
      opt.textContent = `${toStr(t.name || t.slug)} (${toStr(t.slug)})`;
      tenantSel.appendChild(opt);
    });
    if (!workbenchForm.tenant && selectedTenantScope && snapshot?.tenants.some(t => t.slug === selectedTenantScope)) workbenchForm.tenant = selectedTenantScope;
    tenantSel.value = workbenchForm.tenant;
    tenantSel.onchange = (e) => {
      workbenchForm.tenant = (e.target as HTMLSelectElement).value;
      currentPlanPreview = null;
      render();
    };
    tenantGroup.appendChild(tenantSel);
    form.appendChild(tenantGroup);

    // Proposal Title
    const titleGroup = document.createElement('div');
    titleGroup.className = 'oc-form-group';
    titleGroup.innerHTML = safeHtml`<label class="oc-form-label" for="oc-wb-title-input">Proposal Title * (Max 160 Chars)</label>`;
    const titleInp = document.createElement('input');
    titleInp.id = 'oc-wb-title-input';
    titleInp.className = 'oc-input-text';
    titleInp.maxLength = 160;
    titleInp.value = workbenchForm.title;
    titleInp.oninput = (e) => {
      workbenchForm.title = (e.target as HTMLInputElement).value;
      currentPlanPreview = null;
      render();
    };
    titleGroup.appendChild(titleInp);
    form.appendChild(titleGroup);

    // Runtime Dropdown (Actual Adapters)
    const runGroup = document.createElement('div');
    runGroup.className = 'oc-form-group';
    runGroup.innerHTML = safeHtml`<label class="oc-form-label" for="oc-wb-runtime-select">Runtime Adapter (Optional)</label>`;
    const runSel = document.createElement('select');
    runSel.id = 'oc-wb-runtime-select';
    runSel.className = 'oc-filter-select';
    runSel.innerHTML = safeHtml`<option value="">Default Runtime</option>`;
    (snapshot?.catalog?.adapters || []).forEach((ad) => {
      const opt = document.createElement('option');
      opt.value = toStr(ad.id);
      opt.textContent = `${toStr(ad.name || ad.id)} (${toStr(ad.plan_mode, 'default')})`;
      runSel.appendChild(opt);
    });
    runSel.value = workbenchForm.runtime;
    runSel.onchange = (e) => {
      workbenchForm.runtime = (e.target as HTMLSelectElement).value;
      currentPlanPreview = null;
      render();
    };
    runGroup.appendChild(runSel);
    form.appendChild(runGroup);

    // Wing Dropdown (Actual Unique Fleet Wings)
    const wingGroup = document.createElement('div');
    wingGroup.className = 'oc-form-group';
    wingGroup.innerHTML = safeHtml`<label class="oc-form-label" for="oc-wb-wing-select">Target Fleet Wing (Optional)</label>`;
    const wingSel = document.createElement('select');
    wingSel.id = 'oc-wb-wing-select';
    wingSel.className = 'oc-filter-select';
    const uniqueWings = Array.from(new Set((snapshot?.fleet || []).map((f) => toStr(f.wing)).filter(Boolean))).sort();
    wingSel.innerHTML = safeHtml`<option value="">All Fleet Wings</option>`;
    uniqueWings.forEach((w) => {
      const opt = document.createElement('option');
      opt.value = w;
      opt.textContent = `Wing: ${w}`;
      wingSel.appendChild(opt);
    });
    wingSel.value = workbenchForm.wing;
    wingSel.onchange = (e) => {
      workbenchForm.wing = (e.target as HTMLSelectElement).value;
      currentPlanPreview = null;
      render();
    };
    wingGroup.appendChild(wingSel);
    form.appendChild(wingGroup);

    // Module selection list (Allows selection of held modules to observe backend refusal)
    const modGroup = document.createElement('div');
    modGroup.className = 'oc-form-group';
    modGroup.innerHTML = safeHtml`<label class="oc-form-label">Select Candidate Modules (${workbenchForm.modules.size} selected)</label>`;
    const modBox = document.createElement('div');
    modBox.className = 'oc-checkbox-list';
    (snapshot?.catalog?.cards || []).forEach((c) => {
      const id = toStr(c.id);
      const disp = toStr(c.disposition);
      const isHeldOrRefused = disp === 'hold' || disp === 'refuse';
      const lbl = document.createElement('label');
      lbl.className = 'oc-checkbox-label';
      const chk = document.createElement('input');
      chk.type = 'checkbox';
      chk.id = `oc-wb-mod-${id}`;
      chk.checked = workbenchForm.modules.has(id);
      chk.onchange = () => {
        if (chk.checked) workbenchForm.modules.add(id);
        else workbenchForm.modules.delete(id);
        currentPlanPreview = null;
        render();
      };
      lbl.append(chk, document.createTextNode(`${toStr(c.name || id)} [${disp}]${isHeldOrRefused ? ' (held or refused)' : ''}`));
      modBox.appendChild(lbl);
    });
    modGroup.appendChild(modBox);
    form.appendChild(modGroup);

    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.gap = '0.75rem';
    actions.style.alignItems = 'center';
    actions.style.flexWrap = 'wrap';

    const previewBtn = document.createElement('button');
    previewBtn.id = 'oc-wb-btn-simulate';
    previewBtn.className = 'oc-btn oc-btn-primary';
    previewBtn.textContent = isPlanning ? 'Simulating Plan...' : 'Generate Plan Preview (Read-Only)';
    const isTitleValid = Boolean(workbenchForm.title.trim()) && workbenchForm.title.length <= 160;
    previewBtn.disabled = isPlanning || !workbenchForm.tenant || !isTitleValid || isDisconnected;
    previewBtn.onclick = () => handlePlanPreview();
    actions.appendChild(previewBtn);

    const clearPropsBtn = document.createElement('button');
    clearPropsBtn.id = 'oc-wb-btn-clear';
    clearPropsBtn.className = 'oc-btn';
    clearPropsBtn.textContent = 'Clear Form';
    clearPropsBtn.onclick = () => {
      workbenchForm.tenant = '';
      workbenchForm.title = defaultProposalTitle;
      workbenchForm.modules.clear();
      workbenchForm.runtime = '';
      workbenchForm.wing = '';
      currentPlanPreview = null;
      planErrorMsg = null;
      render();
    };
    actions.appendChild(clearPropsBtn);

    form.appendChild(actions);
    frag.appendChild(form);

    if (planErrorMsg) {
      const err = document.createElement('div');
      err.className = 'oc-alert oc-alert-error';
      err.textContent = planErrorMsg;
      frag.appendChild(err);
    }

    if (currentPlanPreview) {
      const planResult = document.createElement('div');
      planResult.className = 'oc-card';
      planResult.style.display = 'flex';
      planResult.style.flexDirection = 'column';
      planResult.style.gap = '1rem';

      planResult.innerHTML = safeHtml`<div class="oc-card-header">
        <div>
          <h3 class="oc-card-title">Preview Result: ${toStr(currentPlanPreview.title)}</h3>
          <div class="oc-card-subtitle">Generated: ${toStr(currentPlanPreview.generatedAt)} · Schema: ${toStr(currentPlanPreview.schema)}</div>
        </div>
        <div class="oc-card-badges">
          <span class="oc-badge oc-badge-status-warning">READ-ONLY PROPOSAL</span>
          <span class="oc-badge oc-badge-status-unreachable">EXECUTABLE: FALSE</span>
        </div>
      </div>`;

      // Module Decisions
      const modSec = document.createElement('div');
      modSec.innerHTML = safeHtml`<h4 style="font-family: var(--oc-font-title); font-size:1.1rem; text-transform:uppercase;">Module Decisions</h4>`;
      const mList = document.createElement('ul');
      mList.style.paddingLeft = '1.2rem';
      toArr<Record<string, unknown>>(currentPlanPreview.modules).forEach((m) => {
        const li = document.createElement('li');
        li.innerHTML = safeHtml`<strong>${toStr(m.id)}</strong>: <span class="oc-badge">${toStr(m.decision)}</span> — <em>${toStr(m.reason, 'No reason provided')}</em>`;
        mList.appendChild(li);
      });
      modSec.appendChild(mList);
      planResult.appendChild(modSec);

      // Projected Routes & Skills
      const routeSec = document.createElement('div');
      routeSec.innerHTML = safeHtml`<h4 style="font-family: var(--oc-font-title); font-size:1.1rem; text-transform:uppercase;">Projected Agent Routes & Skills</h4>`;
      const rList = document.createElement('ul');
      rList.style.paddingLeft = '1.2rem';
      toArr<Record<string, unknown>>(currentPlanPreview.routes).forEach((r) => {
        const li = document.createElement('li');
        li.innerHTML = safeHtml`Agent <strong>${toStr(r.agent)}</strong> via <code>${toStr(r.hook)}</code> · Skills: ${toArr<string>(r.skills).join(', ')} (Source: ${toStr(r.source, 'catalogue')})`;
        rList.appendChild(li);
      });
      routeSec.appendChild(rList);
      planResult.appendChild(routeSec);

      // Steps / Reason / Warnings
      if (currentPlanPreview.steps) {
        const stepSec = document.createElement('div');
        stepSec.innerHTML = safeHtml`<h4 style="font-family: var(--oc-font-title); font-size:1.1rem; text-transform:uppercase;">Execution Steps (Simulation Only)</h4>`;
        const sList = document.createElement('ol');
        sList.style.paddingLeft = '1.2rem';
        toArr<Record<string, unknown>>(currentPlanPreview.steps).forEach((s) => {
          const li = document.createElement('li');
          li.innerHTML = safeHtml`<strong>${toStr(s.label)}</strong> [${toStr(s.status)}]: ${toStr(s.reason)}`;
          sList.appendChild(li);
        });
        stepSec.appendChild(sList);
        planResult.appendChild(stepSec);
      }

      if (currentPlanPreview.warnings && toArr(currentPlanPreview.warnings).length > 0) {
        const warnSec = document.createElement('div');
        toArr<Record<string, unknown>>(currentPlanPreview.warnings).forEach((w) => {
          const alert = document.createElement('div');
          alert.className = 'oc-alert oc-alert-warning';
          alert.innerHTML = safeHtml`<strong>Warning:</strong> ${toStr(w.message || w)}`;
          warnSec.appendChild(alert);
        });
        planResult.appendChild(warnSec);
      }

      // Download sanitized Proposal JSON
      const dlBtn = document.createElement('button');
      dlBtn.id = 'oc-wb-btn-download';
      dlBtn.className = 'oc-btn oc-btn-accent';
      dlBtn.textContent = '⬇ Download Full Proposal JSON';
      dlBtn.onclick = () => {
        if (!currentPlanPreview || isPlanning) return;
        const safeName = (workbenchForm.tenant || 'proposal').replace(/[^a-zA-Z0-9_-]/g, '_');
        const blob = new Blob([JSON.stringify(currentPlanPreview, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `plan-preview-${safeName}.json`;
        a.click();
        URL.revokeObjectURL(url);
      };
      planResult.appendChild(dlBtn);

      frag.appendChild(planResult);
    }

    return frag;
  }

  // Evidence Section
function renderEvidence(): HTMLElement {
  const frag = document.createElement('div');
  frag.style.display = 'flex';
  frag.style.flexDirection = 'column';
  frag.style.gap = '1.25rem';

  const secHeader = document.createElement('div');
  secHeader.className = 'oc-section-header';
  secHeader.innerHTML = safeHtml`<div>
    <h2 class="oc-section-title">Stamp book</h2>
    <div class="oc-section-desc">Formal specification acceptance ledger stamped against ISA.md criteria</div>
  </div>`;
  frag.appendChild(secHeader);

  const filterBar = document.createElement('div');
  filterBar.className = 'oc-filter-bar';
  const sel = document.createElement('select');
  sel.id = 'oc-evidence-status-select';
  sel.className = 'oc-filter-select';
  sel.innerHTML = safeHtml`<option value="all">All Criteria</option>
    <option value="open">Open</option>
    <option value="accepted">Accepted</option>`;
  sel.value = evidenceFilter.status;
  sel.onchange = (e) => {
    evidenceFilter.status = (e.target as HTMLSelectElement).value as 'all' | 'open' | 'accepted';
    render();
  };
  filterBar.appendChild(sel);
  frag.appendChild(filterBar);

  const rawList = snapshot?.acceptance || [];
  const totalCount = rawList.length;
  const acceptedCount = rawList.filter((i) => i.status === 'accepted').length;
  const openCount = totalCount - acceptedCount;

  const statSummary = document.createElement('div');
  statSummary.style.fontSize = '0.85rem';
  statSummary.style.color = 'var(--oc-text-muted, #7c7263)';
  statSummary.style.display = 'flex';
  statSummary.style.alignItems = 'center';
  statSummary.style.gap = '1rem';
  statSummary.innerHTML = safeHtml`
    <span>Stamped Total: <strong>${totalCount}</strong></span>
    <span>•</span>
    <span>Accepted: <strong>${acceptedCount}</strong></span>
    <span>•</span>
    <span>Open Verification: <strong>${openCount}</strong></span>
  `;
  frag.appendChild(statSummary);

  // Honest Evidence Notice
  const stampNotice = document.createElement('div');
  stampNotice.style.padding = '0.65rem 0.9rem';
  stampNotice.style.borderRadius = '10px';
  stampNotice.style.background = 'var(--oc-bg-surface, #fbf7ee)';
  stampNotice.style.border = '1px dashed var(--oc-border-subtle, #e6ded0)';
  stampNotice.style.fontSize = '0.75rem';
  stampNotice.style.color = 'var(--oc-text-muted, #7c7263)';
  stampNotice.textContent = 'Notice: Acceptance stamps reflect declared ISA.md ledger status. An open or unverified stamp indicates pending formal verification, not runtime operational failure.';
  frag.appendChild(stampNotice);

  const list = rawList.filter((item) => {
    if (evidenceFilter.status !== 'all' && item.status !== evidenceFilter.status) return false;
    return true;
  });

  const stampGrid = document.createElement('div');
  stampGrid.className = 'oc-ticket-list';
  stampGrid.style.display = 'flex';
  stampGrid.style.flexDirection = 'column';
  stampGrid.style.gap = '0.75rem';

  if (list.length === 0) {
    const emptyBox = document.createElement('div');
    emptyBox.style.padding = '1.75rem';
    emptyBox.style.textAlign = 'center';
    emptyBox.style.borderRadius = '12px';
    emptyBox.style.border = '1px dashed var(--oc-border-subtle, #e6ded0)';
    emptyBox.style.color = 'var(--oc-text-muted, #7c7263)';
    emptyBox.textContent = 'No acceptance criteria match the active stamp filter.';
    stampGrid.appendChild(emptyBox);
  } else {
    list.forEach((ev) => {
      const isAcc = ev.status === 'accepted';
      const srcDoc = toStr(ev.source, 'ISA.md');

      const ticket = document.createElement('article');
      ticket.className = 'oc-record-ticket';
      ticket.style.display = 'flex';
      ticket.style.flexDirection = 'column';
      ticket.style.padding = '0.9rem 1.15rem';
      ticket.style.borderRadius = '14px';
      ticket.style.background = 'var(--oc-bg-card, #ffffff)';
      ticket.style.border = isAcc ? '1.5px solid var(--oc-border-subtle, #e6ded0)' : '1.5px dashed var(--oc-border-warning, #f0b884)';
      ticket.style.boxShadow = '0 3px 0 var(--oc-shadow-tactile, #ded5c2)';
      ticket.style.gap = '0.5rem';

      const head = document.createElement('div');
      head.className = 'oc-ticket-head';
      head.style.display = 'flex';
      head.style.alignItems = 'flex-start';
      head.style.justifyContent = 'space-between';
      head.style.gap = '0.75rem';

      const leftBox = document.createElement('div');
      leftBox.style.display = 'flex';
      leftBox.style.alignItems = 'flex-start';
      leftBox.style.gap = '0.6rem';

      const iconWrap = document.createElement('div');
      iconWrap.className = 'oc-object-mark';
      iconWrap.style.width = '22px';
      iconWrap.style.height = '22px';
      iconWrap.style.flexShrink = '0';
      iconWrap.style.marginTop = '2px';
      iconWrap.style.color = isAcc ? 'var(--oc-color-forest, #2d5a3f)' : 'var(--oc-color-orange, #d96b27)';
      iconWrap.appendChild(toyIcon('Evidence'));
      leftBox.appendChild(iconWrap);

      const critInfo = document.createElement('div');
      critInfo.innerHTML = safeHtml`
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--oc-text-muted, #7c7263); margin-bottom: 0.15rem;">
          Criterion <code>${toStr(ev.id)}</code>
        </div>
        <div style="font-size: 0.9rem; font-weight: 600; color: var(--oc-text-main, #24201b); line-height: 1.35;">
          ${toStr(ev.criterion)}
        </div>
      `;
      leftBox.appendChild(critInfo);
      head.appendChild(leftBox);

      const stampBadge = document.createElement('span');
      stampBadge.className = `oc-ticket-stamp oc-badge ${isAcc ? 'oc-badge-status-reachable' : 'oc-badge-status-warning'}`;
      stampBadge.style.fontSize = '0.75rem';
      stampBadge.style.fontWeight = '700';
      stampBadge.style.flexShrink = '0';
      stampBadge.textContent = toStr(ev.status).toUpperCase();
      head.appendChild(stampBadge);
      ticket.appendChild(head);

      const footer = document.createElement('div');
      footer.className = 'oc-ticket-meta';
      footer.style.display = 'flex';
      footer.style.alignItems = 'center';
      footer.style.justifyContent = 'space-between';
      footer.style.paddingTop = '0.35rem';
      footer.style.borderTop = '1px solid var(--oc-border-subtle, #f0e9dc)';
      footer.style.fontSize = '0.78rem';
      footer.style.color = 'var(--oc-text-muted, #7c7263)';

      const docLabel = document.createElement('span');
      docLabel.textContent = 'Specification Ledger:';
      footer.appendChild(docLabel);

      if (snapshot?.documents?.some((d) => d.path === srcDoc)) {
        const docBtn = document.createElement('button');
        docBtn.className = 'oc-btn oc-btn-sm';
        docBtn.textContent = `${srcDoc}`;
        docBtn.onclick = () => openDocViewer(srcDoc);
        footer.appendChild(docBtn);
      } else {
        const codeEl = document.createElement('code');
        codeEl.textContent = srcDoc;
        footer.appendChild(codeEl);
      }

      ticket.appendChild(footer);
      stampGrid.appendChild(ticket);
    });
  }

  frag.appendChild(stampGrid);
  return frag;
}

  // Resources Section
  function renderResources(): HTMLElement {
    const frag = document.createElement('div');
    frag.style.display = 'flex';
    frag.style.flexDirection = 'column';
    frag.style.gap = '1rem';

    const secHeader = document.createElement('div');
    secHeader.className = 'oc-section-header';
    secHeader.innerHTML = safeHtml`<div>
      <h2 class="oc-section-title">Field notes</h2>
      <div class="oc-section-desc">Authorized registered documents catalog, source architecture references, and contract specifications</div>
    </div>`;
    frag.appendChild(secHeader);

    const filterBar = document.createElement('div');
    filterBar.className = 'oc-filter-bar';

    const searchInp = document.createElement('input');
    searchInp.id = 'oc-resource-search-input';
    searchInp.className = 'oc-input-text';
    searchInp.placeholder = 'Search document path/title/description...';
    searchInp.value = resourceFilter.search;
    searchInp.oninput = (e) => {
      resourceFilter.search = (e.target as HTMLInputElement).value;
      render();
    };
    filterBar.appendChild(searchInp);

    const kindSel = document.createElement('select');
    kindSel.setAttribute('aria-label', 'Document kind');
    kindSel.id = 'oc-resource-kind-select';
    kindSel.className = 'oc-filter-select';
    const kinds = Array.from(
      new Set((snapshot?.documents || []).map((d) => toStr(d.kind)).filter(Boolean))
    ).sort();
    kindSel.innerHTML = safeHtml`<option value="all">All Document Kinds (${kinds.length})</option>`;
    kinds.forEach((k) => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = `Kind: ${k}`;
      kindSel.appendChild(opt);
    });
    kindSel.value = resourceFilter.kind;
    kindSel.onchange = (e) => {
      resourceFilter.kind = (e.target as HTMLSelectElement).value;
      render();
    };
    filterBar.appendChild(kindSel);
    frag.appendChild(filterBar);

    const docs = snapshot?.documents || [];
    const filteredDocs = docs.filter((d) => {
      const q = resourceFilter.search.toLowerCase().trim();
      if (q) {
        const matchPath = toStr(d.path).toLowerCase().includes(q);
        const matchTitle = toStr(d.title).toLowerCase().includes(q);
        const matchDesc = false;
        if (!matchPath && !matchTitle && !matchDesc) return false;
      }
      if (resourceFilter.kind !== 'all' && toStr(d.kind) !== resourceFilter.kind) {
        return false;
      }
      return true;
    });

    const countHeader = document.createElement('div');
    countHeader.style.fontSize = '0.85rem';
    countHeader.style.color = 'var(--oc-text-muted)';
    countHeader.textContent = `Showing ${filteredDocs.length} of ${docs.length} registered documents`;
    frag.appendChild(countHeader);

    const grid = document.createElement('div');
    grid.className = 'oc-grid';

    filteredDocs.forEach((d) => {
      const card = document.createElement('div');
      card.className = 'oc-card';

      const docPath = toStr(d.path);
      const docTitle = toStr(d.title || d.path);
      const docKind = toStr(d.kind, 'general');

      const header = document.createElement('div');
      header.className = 'oc-card-header';
      header.innerHTML = safeHtml`<div>
        <h3 class="oc-card-title">${docTitle}</h3>
        <div class="oc-card-subtitle"><code>${docPath}</code></div>
      </div>
      <span class="oc-badge">${docKind.toUpperCase()}</span>`;

      const body = document.createElement('div');
      body.className = 'oc-card-body';

      const metaBlock = document.createElement('div');
      metaBlock.style.marginTop = '6px';
      metaBlock.style.fontSize = '0.78rem';
      metaBlock.style.color = 'var(--oc-text-muted)';
      metaBlock.innerHTML = safeHtml`<div><strong>SHA256:</strong> <code>Computed when document is opened</code></div>
        <div><strong>Size:</strong> ${d.bytes !== undefined ? `${d.bytes} bytes` : 'n/a'}</div>`;
      body.appendChild(metaBlock);

      const footer = document.createElement('div');
      footer.className = 'oc-card-footer';

      const viewBtn = document.createElement('button');
      viewBtn.id = `oc-doc-${docPath}`;
      viewBtn.className = 'oc-btn oc-btn-sm oc-btn-primary';
      viewBtn.textContent = 'Inspect Document';
      viewBtn.onclick = () => openDocViewer(docPath);
      footer.appendChild(viewBtn);

      const jumpBtn = document.createElement('button');
      jumpBtn.className = 'oc-btn oc-btn-sm';
      jumpBtn.textContent = 'Jump to Archive';
      jumpBtn.onclick = () => jumpToBuilding('knowledge-archive');
      footer.appendChild(jumpBtn);

      card.append(header, body, footer);
      grid.appendChild(card);
    });

    frag.appendChild(grid);
    return frag;
  }

  // Global Keydown Listener for accessibility
  const handleGlobalKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && isOpen && !document.querySelector('dialog[open]')) {
      e.preventDefault();
      closeOverlay();
    }
  };
  window.addEventListener('keydown', handleGlobalKeydown);

  return {
    openTenant(slug: string) {
      if (!/^[a-z0-9_]+(?:-[a-z0-9]+)*$/.test(slug) || slug.length > 64) return;
      selectedTenantScope = slug;
      clearScopedProjection();
      this.open('tenant-vault');
    },
    open(nodeId?: string) {
      lastFocusedElement = (document.activeElement as HTMLElement) || null;
      lastFocusedId = lastFocusedElement?.id || '';
      isOpen = true;
      rootEl.removeAttribute('hidden');
      host.dispatchEvent(new CustomEvent('cockpit-open'));

      if (nodeId && BUILDING_ROUTING[nodeId]) {
        const route = BUILDING_ROUTING[nodeId];
        visitStation(route.section, nodeId);
        selectedNodeContext = route.slugMatch || null;
      } else if (nodeId && nodeId.startsWith('agent-')) {
        visitStation('Agents', nodeId);
        selectedNodeContext = nodeId.replace(/^agent-/, '');
      } else {
        visitStation('Overview');
        selectedNodeContext = null;
      }

      startPolling();
      fetchOperationsData(false);
      render();

      const returnBtn = document.getElementById('oc-btn-return');
      if (returnBtn) {
        returnBtn.focus();
      } else {
        rootEl.focus();
      }
    },

    async openDocument(path: string) {
      lastFocusedElement = (document.activeElement as HTMLElement) || null;
      lastFocusedId = lastFocusedElement?.id || '';
      isOpen = true;
      rootEl.removeAttribute('hidden');
      host.dispatchEvent(new CustomEvent('cockpit-open'));
      startPolling();

      const expectedFetchGeneration = fetchGeneration + (snapshot ? 0 : 1);
      if (!snapshot) {
        await fetchOperationsData(false);
      }
      if (!isOpen || fetchGeneration !== expectedFetchGeneration) return;
      render();
      await openDocViewer(path);
    },
  };
}
