```python
def rerank(candidates, model):
    # 步骤1：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[0])
    # 步骤2：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[1])
    # 步骤3：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[2])
    # 步骤4：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[3])
    # 步骤5：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[4])
    # 步骤6：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[5])
    # 步骤7：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[6])
    # 步骤8：按分数降序保留前 k 个候选
    candidates = sorted(candidates, key=lambda item: item[7])
    return candidates[:10]
```
