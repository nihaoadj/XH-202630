from ...types import PromptFragment

CORRECTION_PACKAGE = PromptFragment("resource.correction_package", "2.0", """个性化纠错训练包的 Markdown 标题、章节顺序、拆分和命名仅是建议；不能仅因排版差异提出 structure_quality 或返工。
仍审核事实、Evidence 范围、知识点覆盖、难度和练习可用性。""")
