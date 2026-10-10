import type { BrandKnowledge, BrandPlanning } from './brand-summary';
export interface SafeActivityRecord {
  id: string;
  timestamp: string | null;
  tenant: string | null;
  agent: string | null;
  kind: string;
  status: string;
  jobId: string | null;
  artifactId: string | null;
  summary: string;
  sources?: string[];
  /** Canonical fleet slot only; absent attribution never implies a device. */
  nodeId?: string | null;
}

export interface CurrentCatalogCard {
  id: string;
  name: string;
  category: 'skills' | 'mcp' | 'connector' | 'plugin' | 'playbook';
  kind: string;
  disposition: 'add' | 'pointer' | 'hold' | 'refuse';
  repo: string;
  source: string;
  risk: 'low' | 'medium' | 'high';
  approval: 'yes' | 'no';
  agents: string[];
  hooks?: string[];
  runtimes: string[];
  summary: string;
  enableable?: boolean;
  body?: string;
  mcp?: {
    command?: string;
    args?: string[];
    env?: Record<string, string>;
    url?: string;
  };
}

export interface CurrentCatalogAgent {
  slug: string;
  role: string;
  layer: string;
  skill_count: number;
  hooks: string[];
}

export interface CurrentCatalogAdapter {
  schema: 'snowgloves.adapter.v1';
  id: string;
  name: string;
  homepage: string | null;
  question_tool: string;
  plan_mode: string | null;
  paths: Record<string, string | null>;
  formats: Record<string, string>;
  install: string[];
  plugin_install: string | null;
  notes: string;
  verify?: true | Record<string, boolean>;
}

export interface CurrentCatalogConnector {
  id: string;
  auth: string;
  capabilities: Array<{
    id: string;
    risk: 'low' | 'medium' | 'high';
    approval?: 'yes' | 'no' | 'required';
  }>;
  base_url?: string;
  note?: string;
}

export interface OpsSnapshotTenant {
  knowledge?: BrandKnowledge;
  planning?: BrandPlanning;
  slug: string;
  name: string;
  primaryRuntime: string | null;
  agents: string[];
  enabledModules: string[];
  approvalCounts: {
    pending: number;
    approved: number;
    rejected: number;
  };
  sourceCount: number;
  sources: string[];
  availability: 'fixture' | 'local';
  warnings: string[];
}

export interface OpsSnapshotFleetItem {
  id: string;
  name: string;
  wing: string;
  runtime: string | null;
  profile: Record<string, unknown>;
  sources: string[];
  evidence: 'source' | 'local' | 'pending';
}

export interface OpsSnapshotFleetNode {
  id: string;
  name: string;
  wing: 'coding' | 'design' | 'marketing';
  profileId: string;
  assignment: 'configured' | 'planned' | 'template';
  evidence: 'source' | 'local' | 'pending';
  sources: string[];
  observedAt: string | null;
}

export interface OpsSnapshotAcceptanceItem {
  id: string;
  criterion: string;
  status: 'open' | 'accepted';
  source: 'ISA.md';
}

export interface OpsSnapshotRoutingRule {
  id: string;
  agent: string;
  hook: string;
  globs: string[];
  skills: string[];
  source: string;
}

export interface OpsSnapshotDocumentItem {
  path: string;
  title: string;
  kind: string;
  bytes: number;
}

export interface OpsSnapshotServiceItem {
  id: string;
  label: string;
  url: string;
  state: 'reachable' | 'unreachable' | 'auth-required' | 'unknown';
  checkedAt: string | null;
  latencyMs: number | null;
  scope: 'endpoint-only';
}

export interface OpsSnapshotWarningItem {
  code: string;
  message: string;
}

export interface OpsSnapshot {
  schema: 'snowgloves.cockpit.v1';
  generatedAt: string;
  scope: {
    mode: 'public-fixtures' | 'local-private';
    tenant: string | null;
    readOnly: true;
  };
  catalog: {
    cards: CurrentCatalogCard[];
    agents: CurrentCatalogAgent[];
    adapters: CurrentCatalogAdapter[];
    connectors: CurrentCatalogConnector[];
  };
  tenants: OpsSnapshotTenant[];
  fleet: OpsSnapshotFleetItem[];
  fleetNodes?: OpsSnapshotFleetNode[];
  activity: {
    events: SafeActivityRecord[];
    jobs: SafeActivityRecord[];
    artifacts: SafeActivityRecord[];
    approvals: SafeActivityRecord[];
  };
  acceptance: OpsSnapshotAcceptanceItem[];
  routing: {
    rules: OpsSnapshotRoutingRule[];
    skills: Record<string, unknown>[];
  };
  documents: OpsSnapshotDocumentItem[];
  services: OpsSnapshotServiceItem[];
  warnings: OpsSnapshotWarningItem[];
  capabilities: {
    documents: true;
    planPreview: true;
    execute: false;
    enable: false;
    approve: false;
  };
}

export interface PlanRequest {
  tenant: string;
  title: string;
  modules: string[];
  runtime?: string;
  wing?: string;
}

export interface PlanPreviewRoute {
  agent: string;
  hook: string;
  skills: string[];
  source: string;
}

export interface PlanPreviewModule {
  id: string;
  decision: 'allowed' | 'approval-required' | 'disabled' | 'refused' | 'unknown';
  reason: string;
}

export interface PlanPreviewStep {
  id: string;
  label: string;
  status: 'proposed' | 'held';
  reason: string;
}

export interface PlanPreview {
  schema: 'snowgloves.cockpit.plan.v1';
  id: string;
  tenant: string;
  title: string;
  generatedAt: string;
  routes: PlanPreviewRoute[];
  modules: PlanPreviewModule[];
  steps: PlanPreviewStep[];
  executable: false;
  warnings: string[];
}

export interface OpsDocument {
  path: string;
  content: string;
  truncated: boolean;
  sha256: string;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}
