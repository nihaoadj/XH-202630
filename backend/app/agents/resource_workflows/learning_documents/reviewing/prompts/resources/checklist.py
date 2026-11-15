from ...types import PromptFragment

CHECKLIST = PromptFragment("resource.checklist", "2.0", """复习清单难度的首要依据是覆盖节点属于冻结目标阶级，不能以题型复杂度、数量或挑战等措辞代替。
高级、中级、初级分别覆盖 tier=3、2、1 的目标节点。保持主动回忆结构，不因回忆或辨析题否定高级节点。
标题是服务端批次展示标题；以目标能力节点和 Evidence 审核内容，不仅因标题更宽泛要求返工。""")
