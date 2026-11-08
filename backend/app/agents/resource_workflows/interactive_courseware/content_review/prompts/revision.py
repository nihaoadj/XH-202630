from ..types import PromptFragment

REVISION = PromptFragment("content.revision", "1.0", "只修订给定失败项。返回原identity和changes(item_id,old_value_hash,new_value)。不得修改其他字段、用户原意、冻结题目答案、步骤代码、组件或依据。保持原schema字符上限，不增加新事实。若无法安全修改，返回空changes。不得输出任意JSON patch或路径。")
