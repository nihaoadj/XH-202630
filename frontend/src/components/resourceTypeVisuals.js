import { Collection, Document, EditPen, List, Reading } from '@element-plus/icons-vue'

export const resourceTypeVisuals = {
  讲义: { icon: Reading, description: '理解概念，建立知识框架' },
  实操指南: { icon: EditPen, description: '跟随步骤，在实践中掌握' },
  分阶测试题: { icon: List, description: '分层练习，检验掌握程度' },
  复习清单: { icon: Collection, description: '回顾重点，巩固学习成果' },
  案例分析: { icon: Document, description: '拆解场景，连接真实应用' },
}
