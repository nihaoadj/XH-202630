<template>
  <div>
    <h2>系统首页</h2>
    <p>欢迎使用领域知识个性化生成与多智能体协同决策系统。</p>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card>
          <template #header>学习者画像</template>
          <p>录入学历、测试结果与学习目标</p>
          <el-button type="primary" @click="$router.push('/generate')">开始生成</el-button>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>学情报告</template>
          <p>查看知识盲区与资源难度匹配曲线</p>
          <el-button @click="$router.push('/report')">查看报告</el-button>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>学习反馈</template>
          <p>提交答题正确率，触发动态迭代</p>
          <el-button @click="$router.push('/feedback')">提交反馈</el-button>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
</script>
