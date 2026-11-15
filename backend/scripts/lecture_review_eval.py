"""Frozen scripted inputs through the production lecture reviewer; no live quality claim."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine import review_lecture
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.agents.resource_workflows.learning_documents.workflow import route_after_review
from app.core.llm.structured_output import StructuredOutputError
from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import canonical_hash, CreateRunCommand, BeginStepCommand, CompleteStepCommand
from app.db.audit.memory import MemoryAuditRepository
from app.models.reviews.review_audit import ReviewAuditRecordV2, ReviewPolicySnapshotV1, ReviewResourceAuditV1, summarize_review_calls
from datetime import datetime, timezone
from tests.fakes.llm import ScriptedLLMGateway

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / 'tests/fixtures/resource_reviews/lecture_issue_v1/manifest.json'


def evaluate_case(case):
    resource=LearningResource.model_validate(case['resource'])
    evidence=[EvidenceItem.model_validate_json(json.dumps(item)) for item in case['evidence']]
    policy=LectureReviewPolicyV1.model_validate(case['policy']).model_dump(mode='json')
    state={'run_id':'lecture-frozen-eval', 'revision_count':0, 'max_iterations':4,
           'lecture_review_policy':policy,'lecture_review_policy_hash':canonical_hash(policy),
           'lecture_ledgers':{}, 'lecture_revision':{}, 'resource_specs':[{'resource_spec_id':resource.resource_spec_id, 'resource_family_id':resource.resource_family_id, 'knowledge_points':case['targets'], 'difficulty':resource.difficulty}]}
    rows=[]
    for number, review in enumerate(case['reviews'],1):
        if number>1:
            previous=resource
            resource=resource.model_copy(update={'content_text':review['content'], 'version':resource.version+1,
                'parent_resource_id':resource.resource_id,'resource_id':f'{case["case_id"]}-v{number}'})
            state['lecture_revision']={resource.resource_spec_id:{'previous_content':previous.content_text}}
            state['revision_count']=number-1
        template=copy.deepcopy(review['output'])
        ledger_data=state['lecture_ledgers'].get(resource.resource_spec_id)
        if ledger_data:
            ids=[item['issue']['issue_id'] for item in ledger_data['issues']]
            for item in [*template.get('resolutions',[]),*template.get('reopen',[])]:
                if item['issue_id'].startswith('$issue'):
                    item['issue_id']=ids[int(item['issue_id'][6:])-1]
        def scripted(call):
            payload=json.loads(call['messages'][1].content)
            template['binding']=payload['binding']
            if review.get('corrupt_binding'):
                template['binding']['version']+=1
            return template
        gateway=ScriptedLLMGateway([scripted])
        collector=ReviewCallCollector()
        step=f'{case["case_id"]}-review{number}'
        error=None
        assertions={}
        issue_states=[]
        route=None
        try:
            raw, ledger, _, reason=review_lecture(state=state,resource=resource,evidence=evidence,
                step_id=step,context=LLMCallContext(run_id=state['run_id'],step_id=step,node_name='reviewer',schema_name='lecture-eval'),
                gateway=gateway,collector=collector,review_id=f'{step}-rid')
            actual=raw['decision']
            state['lecture_ledgers'][resource.resource_spec_id]=ledger.model_dump(mode='json')
            ledger_hash=canonical_hash(ledger.model_dump(mode='json'))
            persistence_ok = memory_roundtrip(state, resource, ledger, raw, collector, step)
            issue_states=[item.status for item in ledger.issues]
            route=route_after_review({**state,'include_claim_check':True,'generated_resources':[resource],
                'review_result':{**raw,'review_ids':{resource.resource_id:review_id if (review_id:=f'{step}-rid') else ''}}})
            assertions={'memory_roundtrip':persistence_ok,'issue_states':issue_states==review['expected_issue_states'],
                'route':route==review['expected_route'],
                'binding':ledger.binding.resource_id==resource.resource_id and ledger.binding.resource_spec_id==resource.resource_spec_id,
                'history_count':len(ledger.observations)==number,
                'current_resolution_count':len(ledger.observations[-1].output.resolutions)==len(template.get('resolutions',[]))}
        except (ValueError, StructuredOutputError) as exc:
            actual,reason,ledger_hash='invalid',None,None
            error=str(exc)
        rows.append({'review':number,'expected':review['expected'],'actual':actual,'passed':actual==review['expected'] and len(gateway.calls)==review['expected_calls'] and all(assertions.values()),
            'assertions':assertions,'issue_states':issue_states,'route':route,
            'reason':reason,'error':error,'logical_calls':len(gateway.calls),'ledger_hash':ledger_hash,
            'profiles':[call.phase for call in collector.calls],
            'prompt_fingerprints':[call.prompt_fingerprint for call in collector.calls]})
        if actual=='invalid':
            break
    return {'case_id':case['case_id'],'passed':len(rows)==len(case['reviews']) and all(row['passed'] for row in rows),'reviews':rows}


def memory_roundtrip(state, resource, ledger, raw, collector, step):
    repo=MemoryAuditRepository()
    snapshot={key:state[key] for key in ('lecture_review_policy','lecture_review_policy_hash')}
    snapshot.update(lecture_review_contract_version='1.0',review_policy=ReviewPolicySnapshotV1().model_dump(mode='json'))
    now=datetime.now(timezone.utc)
    run=state['run_id']; rid=f'{step}-rid'
    repo.create_run(CreateRunCommand(run_id=run,request_snapshot=snapshot,request_hash=canonical_hash(snapshot)))
    repo.start_run(run,occurred_at=now)
    repo.begin_step(BeginStepCommand(run_id=run,step_id=step,step_sequence=1,node_name='review',agent_name='reviewer',action='冻结审核',started_at=now))
    audit=ReviewAuditRecordV2(run_id=run,step_id=step,generation_attempt=1,revision_count=state['revision_count'],
        policy=ReviewPolicySnapshotV1(),decision=raw['decision'],node_wall_ms=1,
        resources=[ReviewResourceAuditV1(resource_id=resource.resource_id,resource_spec_id=resource.resource_spec_id,
            resource_type='讲义',review_id=rid,structure_status='passed',semantic_status='passed' if raw['decision']=='approve' else 'failed',decision=raw['decision'])],
        calls=collector.calls,summary=summarize_review_calls(collector.calls),lecture_review_policy=state['lecture_review_policy'],
        lecture_review_policy_hash=state['lecture_review_policy_hash'],lecture_ledgers=[ledger])
    command=CompleteStepCommand(run_id=run,step_id=step,trace={'status':'success','attempt':1,
        'resource_ids':[resource.resource_id],'review_ids':[rid]},review_audit=audit.model_dump(mode='json'))
    first=repo.complete_step(command)
    loaded=repo.get_step_review_audit(run,step)
    assert repo.complete_step(command).payload_hash==first.payload_hash
    return loaded.lecture_ledgers[0]==ledger


def evaluate(manifest):
    data=json.loads(Path(manifest).read_text(encoding='utf-8'))
    if data.get('schema_version')!='1.0' or len(data['cases'])<32:
        raise ValueError('lecture frozen manifest incomplete')
    if len({case['case_id'] for case in data['cases']})!=len(data['cases']):
        raise ValueError('duplicate case identity')
    results=[]
    for case in data['cases']:
        if case['input_hash']!=canonical_hash({key:value for key,value in case.items() if key!='input_hash'}):
            raise ValueError('lecture fixture hash mismatch')
        results.append(evaluate_case(case))
    return {'schema_version':'1.0','status':'PASS' if all(r['passed'] for r in results) else 'FAIL',
        'evidence_type':'offline_scripted_policy','real_model_quality':'NOT_RUN_LIVE','end_to_end':'NOT_RUN',
        'manifest_hash':hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),'results':results}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['offline','live-review','live-finalize'],default='offline')
    parser.add_argument('--contract-version',choices=['1.0','2.0'],default='1.0',
                        help='offline: drive the V1 or V2 production engine against the matching frozen manifest')
    parser.add_argument('--manifest',type=Path,default=DEFAULT_MANIFEST)
    parser.add_argument('--dataset',type=Path,help='frozen live dataset directory (live-review)')
    parser.add_argument('--output',type=Path,help='report file (offline) or experiment/analysis directory (live)')
    parser.add_argument('--preflight',action='store_true',help='live-review: print readiness and stop')
    parser.add_argument('--run',type=Path,help='live-finalize: existing run directory')
    parser.add_argument('--adjudication',type=Path,help='live-finalize: adjudication.json')
    args=parser.parse_args(argv)
    if args.mode!='offline':
        from scripts.lecture_review_live import run_cli
        if args.mode=='live-review' and args.preflight:
            return run_cli(dataset=args.dataset,output=args.output,preflight_only=True)
        if args.output is None:
            parser.error('--output is required')
        if args.mode=='live-finalize' and (args.run is None or args.adjudication is None):
            parser.error('--run and --adjudication are required for live-finalize')
        return run_cli(dataset=args.dataset,output=args.output,preflight_only=False,
                       run_dir=args.run if args.mode=='live-finalize' else None,
                       adjudication=args.adjudication if args.mode=='live-finalize' else None)
    if args.output is None:
        parser.error('--output is required')
    if args.output.exists():
        parser.error('output must not already exist')
    if args.contract_version == '2.0':
        from scripts.lecture_review_eval_v2 import evaluate_v2
        result = evaluate_v2(args.manifest)
    else:
        result = evaluate(args.manifest)
    result['source_hashes']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(__file__),
        Path(__file__).resolve().parents[1]/'app/agents/resource_workflows/learning_documents/reviewing/lecture_engine.py',
        Path(__file__).resolve().parents[1]/'app/agents/resource_workflows/learning_documents/reviewing/lecture_ledger.py',
        Path(__file__).resolve().parents[1]/'app/agents/resource_workflows/learning_documents/reviewing/lecture_engine_v2.py',
        Path(__file__).resolve().parents[1]/'app/agents/resource_workflows/learning_documents/reviewing/lecture_ledger_v2.py']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{result["status"]}: {len(result["results"])} frozen cases; real model quality NOT_RUN_LIVE')
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
