import type { InfraNode } from './contracts';

export const nodes: InfraNode[] = [
  {
    id: 'agent-ceo',
    name: 'Chief Executive Agent',
    short: 'CEO',
    layer: 'strategy',
    color: '#c97858',
    summary: 'Chief Executive Officer leading overall strategy.',
    detail: 'The CEO agent drives strategic vision and decision-making across the infrastructure, ensuring alignment with business goals and long-term planning.',
    sources: [
      'agents/ceo/IDENTITY.md',
      'docs/architecture-overview.md'
    ],
    links: ['agent-cto', 'agent-chief-of-staff'],
    evidence: 'source',
    evidenceNote: 'Identity and architecture overview documents provide role definition and responsibilities.'
  },
  {
    id: 'agent-cto',
    name: 'Chief Technology Agent',
    short: 'CTO',
    layer: 'strategy',
    color: '#d5b466',
    summary: 'Chief Technology Officer responsible for architecture.',
    detail: 'The CTO agent oversees the technical architecture and infrastructure design, guiding technology choices and ensuring system scalability and reliability.',
    sources: [
      'agents/cto/IDENTITY.md',
      'docs/architecture-overview.md'
    ],
    links: ['agent-chief-of-staff', 'runtime-adapters'],
    evidence: 'source',
    evidenceNote: 'Role and architecture responsibilities documented in identity and architecture overview.'
  },
  {
    id: 'agent-chief-of-staff',
    name: 'Agent Chief of Staff',
    short: 'CoS',
    layer: 'orchestration',
    color: '#699a92',
    summary: 'Constraints-first skill routing and coordination.',
    detail: 'The Chief of Staff agent manages constraints-first routing of skills and coordinates between agents to optimize workflows and task assignments.',
    sources: [
      'agents/chief-of-staff/IDENTITY.md',
      'scripts/hermes.py'
    ],
    links: ['agent-librarian', 'agent-interpreter', 'agent-dispatcher', 'agent-sentinel', 'agent-cto', 'agent-ceo'],
    evidence: 'source',
    evidenceNote: 'Defined in identity and hermes script for routing logic.'
  },
  {
    id: 'agent-librarian',
    name: 'Agent Librarian',
    short: 'Librarian',
    layer: 'knowledge',
    color: '#9bac80',
    summary: 'Tenant data ingest and retrieval specialist.',
    detail: 'The Librarian agent handles tenant data ingestion and retrieval, managing knowledge archives and ensuring data availability for other agents.',
    sources: [
      'agents/librarian/IDENTITY.md',
      'docs/architecture/knowledge-ingest.md'
    ],
    links: ['agent-interpreter', 'knowledge-archive'],
    evidence: 'source',
    evidenceNote: 'Role and knowledge ingest process documented in identity and knowledge ingest docs.'
  },
  {
    id: 'agent-interpreter',
    name: 'Agent Interpreter',
    short: 'Interpreter',
    layer: 'knowledge',
    color: '#87a4ac',
    summary: 'Entity, policy, risk, and proposed actions interpreter.',
    detail: 'The Interpreter agent analyzes entities, policies, risks, and proposes actions based on tenant data and system state.',
    sources: [
      'agents/interpreter/IDENTITY.md',
      'scripts/ingest.py'
    ],
    links: ['agent-dispatcher', 'agent-librarian'],
    evidence: 'source',
    evidenceNote: 'Identity and ingest script provide role and function details.'
  },
  {
    id: 'agent-dispatcher',
    name: 'Agent Dispatcher',
    short: 'Dispatcher',
    layer: 'orchestration',
    color: '#d8cfb8',
    summary: 'Task dispatcher from Hermes to Paperclip.',
    detail: 'The Dispatcher agent manages task flow from the Hermes bus to the Paperclip system, ensuring efficient task execution and coordination.',
    sources: [
      'agents/dispatcher/IDENTITY.md',
      'scripts/paperclip_bridge.py'
    ],
    links: ['agent-sentinel', 'agent-interpreter', 'hermes-bus'],
    evidence: 'source',
    evidenceNote: 'Role and task flow documented in identity and paperclip bridge script.'
  },
  {
    id: 'agent-sentinel',
    name: 'Agent Sentinel',
    short: 'Sentinel',
    layer: 'governance',
    color: '#c89292',
    summary: 'Audit and evolution monitoring agent.',
    detail: 'The Sentinel agent performs auditing and evolutionary monitoring of the system, ensuring compliance and continuous improvement.',
    sources: [
      'agents/sentinel/IDENTITY.md',
      'scripts/sentinel_sweep.py'
    ],
    links: ['agent-dispatcher'],
    evidence: 'source',
    evidenceNote: 'Identity and sentinel sweep script define audit and monitoring functions.'
  },
  {
    id: 'hermes-bus',
    name: 'Hermes Bus',
    short: 'Hermes',
    layer: 'orchestration',
    color: '#699a92',
    summary: 'Central message bus for agent communication.',
    detail: 'The Snow Gloves event bus at port 4100 accepts normalized events, routes skills, and appends audit records. It is distinct from the NousResearch Hermes runtime adapter.',
    sources: [
      'scripts/hermes.py',
      'docs/fleet/README.md'
    ],
    links: ['connector-gate', 'agent-chief-of-staff', 'agent-dispatcher'],
    evidence: 'source',
    evidenceNote: 'Defined in hermes script and fleet documentation.'
  },
  {
    id: 'connector-gate',
    name: 'Connector Gate',
    short: 'Gate',
    layer: 'orchestration',
    color: '#d5b466',
    summary: 'Checks tenant enablement, risk, and action approvals.',
    detail: 'The gate reads tenant enabled.yaml, rejects held/refused catalog cards, and checks risk and approval tickets before external capabilities are called.',
    sources: [
      'skills/connector-gate/SKILL.md',
      'connectors/g-stack/capabilities.yaml'
    ],
    links: ['hermes-bus', 'tenant-vault', 'module-catalog'],
    evidence: 'source',
    evidenceNote: 'Skill and gateway documentation provide integration details.'
  },
  {
    id: 'knowledge-archive',
    name: 'Knowledge Archive',
    short: 'Archive',
    layer: 'knowledge',
    color: '#9bac80',
    summary: 'Central knowledge storage and retrieval.',
    detail: 'Tenant-owned wiki sources produce a reviewed ingest plan and vector-index.jsonl through ingest.py and embed_worker.py. The offline embedding stub is supported; this scene does not verify a provider.',
    sources: [
      'scripts/ingest.py',
      'scripts/embed_worker.py',
      'docs/architecture/knowledge-ingest.md'
    ],
    links: ['agent-librarian', 'agent-interpreter'],
    evidence: 'source',
    evidenceNote: 'Catalog and knowledge ingest docs describe archive role.'
  },
  {
    id: 'module-catalog',
    name: 'Module Catalog',
    short: 'Catalog',
    layer: 'knowledge',
    color: '#87a4ac',
    summary: 'Catalog of available modules and options.',
    detail: 'The 135 catalog options comprise 64 add, 45 pointer, 14 hold, and 12 refuse cards. Availability does not enable a module; held and refused cards cannot be enabled.',
    sources: [
      'catalog/modules.json'
    ],
    links: ['tenant-vault'],
    evidence: 'source',
    evidenceNote: 'Catalog JSON provides module and option data.'
  },
  {
    id: 'runtime-adapters',
    name: 'Runtime Adapters',
    short: 'Adapters',
    layer: 'runtime',
    color: '#699a92',
    summary: 'Adapters for runtime environment integration.',
    detail: 'Nine runtime adapters render selected skills, MCP configuration, and rules from tenant choices. Explicitly unverified fields remain visible; definitions do not prove runtime installation.',
    sources: [
      'docs/adapters.md',
      'scripts/lib/adapters.py'
    ],
    links: ['tenant-vault', 'module-catalog', 'fleet-wings'],
    evidence: 'source',
    evidenceNote: 'Runtime supervisor documentation details adapter roles.'
  },
  {
    id: 'fleet-wings',
    name: 'Fleet Wings',
    short: 'Wings',
    layer: 'runtime',
    color: '#9bac80',
    summary: 'Profiles for fleet wings with physical acceptance tracking.',
    detail: 'Fleet Wings define profiles for fleet units, with physical acceptance tracked separately in ISA.md; coding job evidence accepted, marketing and design open.',
    sources: [
      'docs/fleet/README.md',
      'nodes/coding/node.yaml',
      'nodes/marketing/node.yaml',
      'nodes/design/node.yaml'
    ],
    links: ['omniroute-gateway'],
    evidence: 'pending',
    evidenceNote: 'Static wing profiles. ISA.md tracks Coding doctor/job acceptance separately; Marketing and Design remain open. No current device telemetry.'
  },
  {
    id: 'omniroute-gateway',
    name: 'OmniRoute Gateway',
    short: 'OmniRoute',
    layer: 'runtime',
    color: '#87a4ac',
    summary: 'Gateway for omni-routing within the fleet.',
    detail: 'Runtime clients use the shared OmniRoute inference gateway at port 20128. Gateway health, provider authentication, model resolution, and physical fleet acceptance are separate evidence levels.',
    sources: [
      'docs/fleet/04-GATEWAY.md'
    ],
    links: ['cloud-recovery', 'fleet-wings'],
    evidence: 'source',
    evidenceNote: 'Fleet gateway documentation describes routing functions.'
  },
  {
    id: 'cloud-recovery',
    name: 'Cloud Recovery',
    short: 'Recovery',
    layer: 'runtime',
    color: '#d8cfb8',
    summary: 'Cloud worker container for recovery operations.',
    detail: 'The active recovery design connects a Cloudflare Worker, Gateway Durable Object, owned OmniRoute container, and encrypted R2 checkpoints. Local candidate evidence does not establish company deployment, live recovery, or physical acceptance.',
    sources: [
      'docs/fleet/08-CLOUD-GATEWAY.md'
    ],
    links: ['omniroute-gateway'],
    evidence: 'local',
    evidenceNote: 'Local candidate implementation; company deployment, provider admission, and live acceptance remain pending.'
  },
  {
    id: 'tenant-vault',
    name: 'Tenant Vault',
    short: 'Vault',
    layer: 'governance',
    color: '#c97858',
    summary: 'Secure tenant instance data storage.',
    detail: 'SNOWGLOVES_DATA resolves tenant context, enabled modules, approvals, fleet inventory, and receipts into the private snow-gloves-ops checkout. Public fixtures describe contracts; real tenant data is excluded from this scene.',
    sources: [
      'docs/architecture-overview.md'
    ],
    links: ['connector-gate', 'module-catalog', 'runtime-adapters', 'knowledge-archive'],
    evidence: 'source',
    evidenceNote: 'Architecture overview documents tenant data governance and storage.'
  }
];
