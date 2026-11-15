import AgentConstellation from './AgentConstellation.vue'
import EvidenceArchive from './EvidenceArchive.vue'
import LearningJourney from './LearningJourney.vue'
import FeedbackOrbit from './FeedbackOrbit.vue'

export const showcasePages = [
  { key: 'agents', id: 'multi-agent', index: '01', title: '多智能体协同', shortTitle: '协作星图', component: AgentConstellation },
  { key: 'evidence', id: 'evidence', index: '02', title: '知识有据可依', shortTitle: '证据档案', component: EvidenceArchive },
  { key: 'path', id: 'learning-path', index: '03', title: '适合你的学习路径', shortTitle: '成长航线', component: LearningJourney },
  { key: 'feedback', id: 'feedback-loop', index: '04', title: '反馈驱动进步', shortTitle: '反馈进阶', component: FeedbackOrbit },
]
