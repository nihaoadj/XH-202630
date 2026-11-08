"""Five resource types pass actual generation/review/Claim/publication/read nodes offline."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.resource_agents.checklist import ReviewChecklistAgent
from app.agents.resource_workflows.learning_documents import generator_agent
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node, claim_decide_node
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.api.learning_documents import documents
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceArtifactMetadata
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for, case, approve, scope_output
from tests.unit.agents.test_resource_type_agents import _inputs, CHECKLIST_PAYLOAD, CASE_STUDY_MARKDOWN
from app.core.retrieval.evidence import source_refs_from_evidence


@pytest.mark.parametrize('kind',['讲义','实操指南','分阶测试题','案例分析','复习清单'])
def test_five_types_generation_review_claim_publication_markdown(kind,monkeypatch):
    sample=case('assessment.clean.01') if kind=='分阶测试题' else case()
    state=state_for(sample)
    source=state['generated_resources'][0]
    if kind in {'讲义','案例分析'}:
        source=source.model_copy(update={'resource_type':kind,'practice_guide_payload':None,
            'practice_guide_payload_hash':None,'content_text':'# 讲义\n\n冻结证据支持这个教学示例。' if kind=='讲义' else CASE_STUDY_MARKDOWN})
    elif kind=='复习清单':
        spec,context,evidence=_inputs('复习清单')
        artifact=ReviewChecklistAgent().generate(spec,context,llm_gateway=ScriptedLLMGateway([CHECKLIST_PAYLOAD]))
        state['retrieved_evidence']=[evidence]
        source=LearningResource(resource_id='checklist',resource_type=kind,difficulty='初级',content_text=artifact.content_text,
            knowledge_points=['skill-search'],review_practice_payload=artifact.artifact_data['review_practice_package'],source_refs=source_refs_from_evidence([evidence]))
    learner=LearnerProfile(learner_id='five-types',learner_type='测试',education='本科',major='测试',learning_goal='冻结流程验收')
    state.update(learner=learner,topic='合成教学',resource_types=[kind],target_skill_nodes=source.knowledge_points,
        generated_resources=[],include_review=True,include_claim_check=True,max_iterations=2,claim_max_iterations=1)
    def generate(spec,context,**kwargs):
        return GeneratedArtifact(metadata=ResourceArtifactMetadata(resource_spec_id=spec.resource_spec_id,
            resource_family_id=spec.resource_family_id,resource_type=kind,representation='text',agent_name='frozen',
            prompt_version='1',artifact_format='markdown',source_evidence_ids=spec.evidence_ids),
            difficulty='初级',mime_type='text/markdown',content_text=source.content_text,knowledge_points=source.knowledge_points,
            artifact_data={key:value for key,value in {'practice_guide_package':source.practice_guide_payload,
                'assessment_package':source.assessment_payload,'review_practice_package':source.review_practice_payload}.items() if value})
    agent=SimpleNamespace(agent_name='frozen',prompt_version='1',artifact_format='markdown',generate=generate)
    monkeypatch.setattr(generator_agent,'get_resource_agent',lambda _:agent)
    state.update(generator_agent.generate_node(state,llm_gateway=ScriptedLLMGateway([])))
    generated=state['generated_resources'][0]
    assert generated.resource_type==kind and generated.review_status=='pending_review'
    state.update(review_node(state,llm_gateway=ScriptedLLMGateway([scope_output(sample),approve()] if kind=='分阶测试题' else [approve()])))
    assert state['review_result']['decision']=='approve'
    def extract(call):
        payload=json.loads(call['messages'][1].content)
        resource=payload['resources'][0]
        content=state['generated_resources'][0].content_text
        text=next((line.strip() for line in content.splitlines() if len(line.strip())>10 and not line.lstrip().startswith('#')),content)[:80]
        start=content.index(text)
        return {'resources':[{'resource_id':resource['resource_id'],'claims':[{'claim_text':text,'claim_type':'factual','source_text':text,
            'source_start':start,'source_end':start+len(text),'knowledge_point_id':source.knowledge_points[0],
            'source_evidence_ids':[payload['allowed_evidence'][0]['evidence_id']]}]}]}
    state.update(claim_extract_node(state,llm_gateway=ScriptedLLMGateway([extract])))
    def judge(call):
        payload=json.loads(call['messages'][1].content)
        return {'judgements':[{'claim_id':claim['claim_id'],'verdict':'supported','evidence_ids':[payload['allowed_evidence'][0]['evidence_id']],
            'reason':'冻结证据支持','confidence':.99} for claim in payload['claims']]}
    state.update(claim_judge_node(state,llm_gateway=ScriptedLLMGateway([judge])))
    state.update(claim_decide_node(state));state.update(decide_node(state))
    resource=state['generated_resources'][0]
    assert resource.publication_status=='published'
    assert resource.claim_metric_status==('not_applicable' if kind=='分阶测试题' else 'complete')
    repo=MemoryResourceRepository();repo.save(resource,learner.learner_id,'合成教学')
    profiles=MemoryLearnerRepository();profiles.save(learner)
    app=FastAPI();app.container=SimpleNamespace(resource_service=lambda:ResourceService(repo),profile_service=lambda:ProfileService(profiles))
    app.include_router(documents.router,prefix='/api/resources')
    response=TestClient(app).get('/api/resources/items/'+resource.resource_id)
    assert response.status_code==200
    assert response.json()['resource']['content_text']==generated.content_text==source.content_text.strip()
    assert response.json()['resource']['mime_type']=='text/markdown'


def test_new_lecture_real_nodes_revision_recheck_claim_publication(monkeypatch):
    from app.agents.resource_workflows.learning_documents.workflow import prepare_revision_node, route_after_review
    from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import text_hash
    from app.models.reviews.lecture_review import LectureReviewPolicyV1
    from app.models.shared.persistence import canonical_hash
    from tests.unit.agents.test_lecture_review_engine import response
    from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
    state=state_for()
    learner=LearnerProfile(learner_id='new-lecture',learner_type='测试',education='本科',major='测试',learning_goal='测试')
    specs=build_resource_specs(run_id=state['run_id'],resource_types=['讲义'],topic='题目',difficulty='初级',
        learning_plan={},evidence=state['retrieved_evidence'],target_skill_nodes=state['target_skill_nodes'])
    policy=LectureReviewPolicyV1(context_tokens=1000000,max_output_tokens=12000).model_dump(mode='json')
    state.update(learner=learner,resource_types=['讲义'],resource_specs=[s.model_dump(mode='json') for s in specs],
        topic='题目',generated_resources=[],include_review=True,include_claim_check=True,max_iterations=2,
        lecture_review_contract_version='1.0',lecture_review_policy=policy,lecture_review_policy_hash=canonical_hash(policy),lecture_ledgers={})
    seen=[]
    def generate(spec,context,**kwargs):
        revision=context.constraints.get('lecture_revision')
        seen.append(revision)
        if revision:
            assert 'revision_feedback' not in context.constraints and 'previous_version_content' not in context.constraints
            assert len(revision['open_issues'])==1
        return GeneratedArtifact(metadata=ResourceArtifactMetadata(resource_spec_id=spec.resource_spec_id,
            resource_family_id=spec.resource_family_id,resource_type='讲义',representation='text',agent_name='frozen',
            prompt_version='1',artifact_format='markdown',source_evidence_ids=spec.evidence_ids),difficulty='初级',
            content_text='题目：提供两路名次和k。'+('补充具体名次1、2和k=60。' if revision else ''),knowledge_points=spec.knowledge_points,mime_type='text/markdown')
    monkeypatch.setattr(generator_agent,'get_resource_agent',lambda _:SimpleNamespace(agent_name='frozen',prompt_version='1',artifact_format='markdown',generate=generate))
    state.update(generator_agent.generate_node(state,llm_gateway=ScriptedLLMGateway([])))
    state.update(review_node(state,llm_gateway=ScriptedLLMGateway([lambda call:response(call,blocking=True)])))
    assert route_after_review(state)=='prepare_revision'
    old_id=state['lecture_ledgers'][specs[0].resource_spec_id]['issues'][0]['issue']['issue_id']
    old_content=state['generated_resources'][0].content_text
    state.update(prepare_revision_node(state));state.update(generator_agent.generate_node(state,llm_gateway=ScriptedLLMGateway([])))
    def fixed(call):
        return response(call,resolutions=[{'issue_id':old_id,'result':'fixed','reason':'当前题目已补名次和k',
            'current_location':{'paragraph_id':'p000001','quote':'题目'},'previous_location':None,'evidence_refs':[]}])
    state.update(review_node(state,llm_gateway=ScriptedLLMGateway([fixed])))
    ledger=state['lecture_ledgers'][specs[0].resource_spec_id]
    assert ledger['issues'][0]['status']=='closed' and len(ledger['observations'])==2
    assert ledger['observations'][-1]['parent_content_hash']==text_hash(old_content)
    assert state['review_audit']['schema_version']=='2.0' and route_after_review(state)=='claim_extract'
    def extract(call):
        payload=json.loads(call['messages'][1].content);r=payload['resources'][0]
        return {'resources':[{'resource_id':r['resource_id'],'claims':[{'claim_text':'两路名次','claim_type':'factual','source_text':'两路名次',
            'source_start':6,'source_end':10,'knowledge_point_id':specs[0].knowledge_points[0],
            'source_evidence_ids':[payload['allowed_evidence'][0]['evidence_id']]}]}]}
    content=state['generated_resources'][0].content_text
    def correct_extract(call):
        value=extract(call);claim=value['resources'][0]['claims'][0];claim['source_start']=content.index('两路名次');claim['source_end']=claim['source_start']+4
        return value
    state.update(claim_extract_node(state,llm_gateway=ScriptedLLMGateway([correct_extract])))
    def judge(call):
        payload=json.loads(call['messages'][1].content)
        return {'judgements':[{'claim_id':i['claim_id'],'verdict':'supported','evidence_ids':[payload['allowed_evidence'][0]['evidence_id']],
            'reason':'冻结证据支持','confidence':.99} for i in payload['claims']]}
    state.update(claim_judge_node(state,llm_gateway=ScriptedLLMGateway([judge])));state.update(claim_decide_node(state));state.update(decide_node(state))
    assert state['generated_resources'][0].publication_status=='published'
    assert state['generated_resources'][0].claim_metric_status=='complete'
    assert seen[0] is None and seen[1]['parent_resource_id']


def test_claim_history_cannot_expand_next_ordinary_revision_to_sibling_spec(monkeypatch):
    from uuid import uuid4
    from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
    state=state_for()
    specs=build_resource_specs(run_id=state['run_id'],resource_types=['讲义'],topic='题目',difficulty='初级',
        learning_plan={},evidence=state['retrieved_evidence'],target_skill_nodes=state['target_skill_nodes'])
    one=specs[0];two=one.model_copy(update={'resource_spec_id':str(uuid4()),'resource_family_id':str(uuid4())})
    resources=[LearningResource(resource_id=f'old-{n}',resource_type='讲义',resource_spec_id=s.resource_spec_id,
        resource_family_id=s.resource_family_id,content_text='题目原文',knowledge_points=s.knowledge_points,
        difficulty='初级',source_refs=[],review_status='revision_requested' if n==1 else 'approved') for n,s in enumerate((one,two),1)]
    state.update(resource_specs=[s.model_dump(mode='json') for s in (one,two)],resource_types=['讲义','讲义'],
        generated_resources=resources,learner=LearnerProfile(learner_id='mixed',learner_type='测试',education='本科',major='测试',learning_goal='测试'),
        topic='题目',revision_count=1,claim_revision_count=1,generation_attempt=3,include_review=True,
        lecture_review_policy={'strategy':'lecture_issue_v1'},
        lecture_revision={one.resource_spec_id:{'previous_content':'题目原文','parent_resource_id':'old-1','claim_only':False}},
        review_result={'revision_instructions':[{'target_resource_type':'讲义','action':'修复一份'}]})
    calls=[]
    def generate(spec,context,**kwargs):
        calls.append(spec.resource_spec_id)
        return GeneratedArtifact(metadata=ResourceArtifactMetadata(resource_spec_id=spec.resource_spec_id,
            resource_family_id=spec.resource_family_id,resource_type='讲义',representation='text',agent_name='frozen',
            prompt_version='1',artifact_format='markdown',source_evidence_ids=spec.evidence_ids),difficulty='初级',
            content_text='题目修复',knowledge_points=spec.knowledge_points)
    monkeypatch.setattr(generator_agent,'get_resource_agent',lambda _:SimpleNamespace(agent_name='frozen',prompt_version='1',artifact_format='markdown',generate=generate))
    result=generator_agent.generate_node(state,llm_gateway=ScriptedLLMGateway([]))
    assert calls==[one.resource_spec_id]
    assert next(r for r in result['generated_resources'] if r.resource_id=='old-2')==resources[1]


def test_failed_lecture_placeholder_can_retry_without_fake_issue_ledger(monkeypatch):
    from app.agents.resource_workflows.learning_documents.workflow import prepare_revision_node, route_after_review
    from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
    state=state_for();spec=build_resource_specs(run_id=state['run_id'],resource_types=['讲义'],topic='题目',difficulty='初级',
        learning_plan={},evidence=state['retrieved_evidence'],target_skill_nodes=state['target_skill_nodes'])[0]
    resource=LearningResource(resource_id='failed',resource_type='讲义',resource_spec_id=spec.resource_spec_id,
        resource_family_id=spec.resource_family_id,content_text='生成失败占位',knowledge_points=spec.knowledge_points,
        difficulty='初级',source_refs=[],review_status='human_review')
    state.update(resource_specs=[spec.model_dump(mode='json')],resource_types=['讲义'],generated_resources=[resource],
        learner=LearnerProfile(learner_id='retry',learner_type='测试',education='本科',major='测试',learning_goal='测试'),
        topic='题目',lecture_review_policy={'strategy':'lecture_issue_v1'},lecture_ledgers={},
        resource_executions=[{'resource_id':'failed','resource_spec_id':spec.resource_spec_id,'resource_type':'讲义','validation_status':'failed'}],
        include_review=True,max_iterations=2,review_result={'decision':'human_review','issues':[],'revision_instructions':[]})
    assert route_after_review(state)=='prepare_revision'
    state.update(prepare_revision_node(state))
    assert state['lecture_revision'][spec.resource_spec_id]['generation_failure']
    assert state['lecture_ledgers']=={}
    def generate(spec,context,**kwargs):
        assert context.constraints['lecture_revision']['generation_failure']
        return GeneratedArtifact(metadata=ResourceArtifactMetadata(resource_spec_id=spec.resource_spec_id,
            resource_family_id=spec.resource_family_id,resource_type='讲义',representation='text',agent_name='frozen',
            prompt_version='1',artifact_format='markdown',source_evidence_ids=spec.evidence_ids),difficulty='初级',
            content_text='重新生成成功正文',knowledge_points=spec.knowledge_points)
    monkeypatch.setattr(generator_agent,'get_resource_agent',lambda _:SimpleNamespace(agent_name='frozen',prompt_version='1',artifact_format='markdown',generate=generate))
    result=generator_agent.generate_node(state,llm_gateway=ScriptedLLMGateway([]))
    assert result['generated_resources'][0].parent_resource_id=='failed'
    assert result['generated_resources'][0].review_status=='pending_review'
