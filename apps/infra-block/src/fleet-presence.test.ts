import { describe, expect, it } from 'vitest';
import { fleetActivity, fleetNodes } from './fleet-model';
import { derivePresence } from './residents';
import type { OpsSnapshot, SafeActivityRecord } from './ops-contracts';

const NOW = Date.parse('2026-10-08T12:00:00Z');
const timestamp = (offset: number) => new Date(NOW + offset).toISOString();
function record(overrides: Partial<SafeActivityRecord> = {}): SafeActivityRecord {
  return { id:'job-start', timestamp:timestamp(-5000), tenant:'alpha', agent:'ceo', kind:'job',
    status:'running', jobId:'shared-job', artifactId:null, summary:'Sanitized work',
    nodeId:'mac-coding-1', ...overrides };
}
function snapshot(): OpsSnapshot {
  const result: OpsSnapshot = {
    schema:'snowgloves.cockpit.v1', generatedAt:timestamp(0), scope:{mode:'local-private',tenant:'alpha',readOnly:true},
    catalog:{cards:[],agents:[],adapters:[],connectors:[]},tenants:[],fleet:[],
    activity:{events:[],jobs:[],artifacts:[],approvals:[]},acceptance:[],routing:{rules:[],skills:[]},
    documents:[],services:[],warnings:[],capabilities:{documents:true,planPreview:true,execute:false,enable:false,approve:false}
  };
  result.fleetNodes = fleetNodes(null).map(node => ({...node,assignment:'configured',evidence:'local'}));
  return result;
}
function presence(source: OpsSnapshot | null, id = 'mac-coding-1', stale = false) {
  return derivePresence(source ? {...source,activity:fleetActivity(source,id)} : null,NOW,stale);
}

describe('fleet selection composes safely with resident work evidence', () => {
  it('identical job and agent identifiers belong to only their exact Mac', () => {
    const source = snapshot();
    source.activity.jobs = [record(),record({id:'second',nodeId:'mac-coding-2',agent:'cto'})];
    expect(presence(source).filter(item => item.state === 'active').map(item=>item.slug)).toEqual(['ceo']);
    expect(presence(source,'mac-coding-2').filter(item => item.state === 'active').map(item=>item.slug)).toEqual(['cto']);
  });
  it.each([null,undefined,'coding','unknown-mac'])('unattributed or unrecognized node %s supplies no work', nodeId => {
    const source = snapshot(); source.activity.jobs = [record({nodeId})];
    expect(presence(source).every(item => item.state === 'unknown')).toBe(true);
  });
  it('excludes another tenant on the selected Mac', () => {
    const source = snapshot(); source.activity.jobs = [record({tenant:'beta'})];
    expect(presence(source).every(item => item.state === 'unknown')).toBe(true);
  });
  it.each([-120001,1])('rejects stale or future work with offset %s', offset => {
    const source = snapshot(); source.activity.jobs = [record({timestamp:timestamp(offset)})];
    expect(presence(source).every(item => item.state === 'unknown')).toBe(true);
  });
  it.each([-2000,-5000])('same-node terminal without an agent supersedes active at %s', offset => {
    const source = snapshot(); source.activity.events = [record()];
    source.activity.jobs = [record({id:'terminal',status:'completed',agent:null,timestamp:timestamp(offset)})];
    expect(presence(source).every(item => item.state === 'unknown')).toBe(true);
  });
  it.each([
    {nodeId:'mac-coding-2'}, {tenant:'beta'}, {timestamp:timestamp(1)}
  ])('unrelated or future terminal cannot suppress selected Mac work: %j', override => {
    const source = snapshot(); source.activity.events = [record()];
    source.activity.jobs = [record({id:'terminal',status:'completed',agent:null,timestamp:timestamp(-2000),...override})];
    expect(presence(source).find(item=>item.slug==='ceo')?.state).toBe('active');
  });
  it('revocation and stale projection clear every crew member', () => {
    const source = snapshot(); source.activity.jobs = [record()];
    expect(presence(source,undefined,true).every(item=>item.state==='unknown')).toBe(true);
    expect(presence(null).every(item=>item.state==='unknown')).toBe(true);
  });
  it('switching twice preserves source arrays and restores only the selected node', () => {
    const source = snapshot(); source.activity.jobs = [record()]; const original=JSON.stringify(source);
    expect(presence(source).some(item=>item.state==='active')).toBe(true);
    expect(presence(source,'mac-marketing').every(item=>item.state==='unknown')).toBe(true);
    expect(presence(source).some(item=>item.state==='active')).toBe(true);
    expect(JSON.stringify(source)).toBe(original);
  });
});
