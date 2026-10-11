<template>
  <div class="user-profile-page">
    <section class="profile-page-intro" aria-labelledby="profile-page-title">
      <div>
        <span class="profile-kicker">YOUR PERSONAL LEARNING PROFILE</span>
        <h2 id="profile-page-title">用户资料</h2>
        <p>完善你的个人档案，让每一次学习从你的背景出发。</p>
      </div>
      <el-button class="profile-direction-button" @click="$router.push('/learning/new')">
        去新建学习方向
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12" /></svg>
      </el-button>
    </section>

    <section class="profile-workspace" aria-label="个人资料管理">
      <aside class="account-panel" aria-label="当前保存的资料">
        <div class="account-identity">
          <div class="account-avatar" aria-hidden="true">{{ auth.currentUser?.username?.slice(0, 1).toUpperCase() || 'U' }}</div>
          <div>
            <span class="account-kicker">CURRENT ACCOUNT</span>
            <strong class="account-name">{{ auth.currentUser?.username || '当前账号' }}</strong>
          </div>
        </div>
        <div class="account-status"><i aria-hidden="true" />当前账号 · 已保存资料</div>

        <dl class="account-summary">
          <div>
            <dt>身份<span>IDENTITY</span></dt>
            <dd>{{ auth.currentUser?.identity && auth.currentUser.identity !== '其他' ? auth.currentUser.identity : '待补充' }}</dd>
          </div>
          <div>
            <dt>学历<span>EDUCATION</span></dt>
            <dd>{{ auth.currentUser?.education && auth.currentUser.education !== '未填写' ? auth.currentUser.education : '待补充' }}</dd>
          </div>
          <div>
            <dt>经验年限<span>EXPERIENCE</span></dt>
            <dd v-if="auth.currentUser?.experience_years != null">{{ auth.currentUser.experience_years }}<small>年</small></dd>
            <dd v-else>待补充</dd>
          </div>
        </dl>

        <div class="account-purpose">
          <span class="account-kicker">PROFILE → LEARNING</span>
          <h3>从你的背景，出发。</h3>
          <p>这些信息会在新建学习方向时复用，可按需补充。</p>
          <div class="account-purpose-note">基础资料描述你的背景，方向问卷帮助明确本次学习目标。</div>
        </div>
      </aside>

      <article class="profile-editor" aria-labelledby="profile-editor-title">
        <header class="profile-editor-head">
          <div>
            <span class="profile-kicker">EDIT YOUR PROFILE</span>
            <h3 id="profile-editor-title">资料编辑</h3>
          </div>
          <span class="profile-editor-note">可按需填写</span>
        </header>

        <el-form :model="form" label-position="top">
          <div class="profile-account-field">
            <el-form-item label="用户名" for="user-profile-username">
              <template #label><span class="profile-field-label">用户名<small>USERNAME / READ ONLY</small></span></template>
              <el-input id="user-profile-username" aria-label="用户名" :model-value="auth.currentUser?.username" disabled />
            </el-form-item>
          </div>

          <section class="profile-form-section" aria-labelledby="profile-education-heading">
            <div class="profile-section-head">
              <span class="profile-section-index" aria-hidden="true">01</span>
              <h4 id="profile-education-heading">身份与教育<span>ABOUT YOU</span></h4>
            </div>
            <div class="form-grid">
              <el-form-item label="身份" for="user-profile-identity">
                <template #label><span class="profile-field-label">身份<small>IDENTITY</small></span></template>
                <el-input id="user-profile-identity" aria-label="身份" v-model="form.identity" maxlength="64" placeholder="例如 在校学生" />
              </el-form-item>
              <el-form-item label="学历" for="user-profile-education">
                <template #label><span class="profile-field-label">学历<small>EDUCATION</small></span></template>
                <el-input id="user-profile-education" aria-label="学历" v-model="form.education" maxlength="64" placeholder="例如 本科" />
              </el-form-item>
              <el-form-item class="profile-wide-field" label="专业" for="user-profile-major">
                <template #label><span class="profile-field-label">专业<small>MAJOR</small></span></template>
                <el-input id="user-profile-major" aria-label="专业" v-model="form.major" maxlength="128" placeholder="例如 软件工程" />
              </el-form-item>
            </div>
          </section>

          <section class="profile-form-section" aria-labelledby="profile-experience-heading">
            <div class="profile-section-head">
              <span class="profile-section-index" aria-hidden="true">02</span>
              <h4 id="profile-experience-heading">职业与经验<span>EXPERIENCE</span></h4>
            </div>
            <div class="form-grid">
              <el-form-item label="岗位 / 背景" for="user-profile-job-role">
                <template #label><span class="profile-field-label">岗位 / 背景<small>BACKGROUND</small></span></template>
                <el-input id="user-profile-job-role" aria-label="岗位 / 背景" v-model="form.job_role" maxlength="128" placeholder="例如 算法工程师" />
              </el-form-item>
              <el-form-item label="经验年限" for="user-profile-experience">
                <template #label><span class="profile-field-label">经验年限<small>YEARS</small></span></template>
                <el-input-number id="user-profile-experience" aria-label="经验年限" v-model="form.experience_years" :min="0" :max="50" />
              </el-form-item>
            </div>
          </section>

          <div class="action-row">
            <p>保存后，新建方向将复用这些基础信息。</p>
            <el-button class="profile-save-button" type="primary" :loading="saving" @click="saveProfile">保存资料</el-button>
          </div>
        </el-form>
      </article>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { userApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const saving = ref(false)
const form = reactive({
  identity: '',
  education: '',
  major: '',
  job_role: '',
  experience_years: null,
})

function fillForm(user) {
  form.identity = user?.identity === '其他' ? '' : (user?.identity || '')
  form.education = user?.education === '未填写' ? '' : (user?.education || '')
  form.major = user?.major === '未填写' ? '' : (user?.major || '')
  form.job_role = user?.job_role || ''
  form.experience_years = user?.experience_years ?? null
}

async function saveProfile() {
  if (!auth.currentUser?.user_id) return
  saving.value = true
  try {
    const response = await userApi.update(auth.currentUser.user_id, {
      identity: form.identity || '其他',
      education: form.education || '未填写',
      major: form.major || '未填写',
      job_role: form.job_role || null,
      experience_years: form.experience_years,
    })
    auth.setCurrentUser(response.data)
    fillForm(response.data)
    ElMessage.success('用户资料已保存')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '用户资料保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => fillForm(auth.currentUser))
</script>

<style scoped>
.user-profile-page {
  --profile-ink: #132c40;
  --profile-muted: #536b7d;
  --profile-line: #d9e4eb;
  --profile-teal: #086575;
  --rag-ink: #132c40;
  --rag-line: #d9e4eb;
  --rag-radius: 5px;
  --rag-shadow-soft: none;
  --rag-blue-700: #11283c;
  --rag-blue-800: #1d4055;
  --el-color-primary: #086575;
  --el-border-radius-base: 5px;
  --el-text-color-regular: #132c40;
  display: flex;
  width: 100%;
  min-width: 0;
  max-width: 1440px;
  flex-direction: column;
  gap: 20px !important;
  margin: 0 auto;
  color: var(--profile-ink);
}
.user-profile-page .profile-page-intro { display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 2px 0; border: 0 !important; border-radius: 0 !important; background: transparent; box-shadow: none !important; }
.profile-page-intro > div { min-width: 0; }
.profile-kicker { display: block; color: var(--profile-muted); font: 10px/1.5 Consolas, "SFMono-Regular", monospace; letter-spacing: .025em; }
.profile-page-intro h2 { margin: 7px 0 0; font-size: 26px; font-weight: 650; line-height: 1.35; }
.profile-page-intro p { margin: 8px 0 0; color: var(--profile-muted); font-size: 13px; line-height: 1.75; }
.user-profile-page .profile-direction-button { flex-shrink: 0; min-height: 44px; height: auto; margin: 0; padding: 10px 16px; border: 1px solid #cbdbe4; border-radius: 5px !important; background: #fff; color: var(--profile-ink); font-size: 12px; font-weight: 600; box-shadow: none; }
.profile-direction-button :deep(svg) { width: 16px; height: 16px; margin-left: 12px; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.user-profile-page .profile-direction-button:hover { border-color: #8cb8bb; background: #edf8f6; color: var(--profile-teal); }
.user-profile-page .profile-workspace { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 20px; min-width: 0; border: 0 !important; border-radius: 0 !important; box-shadow: none !important; background: transparent; }
.account-panel { display: flex; min-width: 0; flex-direction: column; padding: 26px 24px; border-left: 3px solid #9cebe1; background: #11283c; color: #edf5fa; }
.account-identity { display: flex; min-width: 0; align-items: center; gap: 14px; }
.account-identity > div:last-child { min-width: 0; }
.account-avatar { display: grid; flex: 0 0 48px; height: 48px; place-items: center; border: 1px solid #5c999f; border-radius: 6px; background: #193f50; color: #a1eee4; font: 23px/1 Consolas, monospace; }
.account-kicker { display: block; color: #b5cbd8; font: 10px/1.5 Consolas, monospace; letter-spacing: .025em; }
.account-name { display: block; margin-top: 6px; color: #f4f9fc; font-size: 20px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.account-status { display: flex; align-items: center; gap: 8px; margin-top: 22px; color: #b5cbd8; font-size: 12px; line-height: 1.65; }
.account-status i { width: 5px; height: 5px; border-radius: 50%; background: #a1eee4; }
.account-summary { margin: 20px 0 0; }
.account-summary > div { padding: 16px 0; border-top: 1px solid #334d5f; }
.account-summary dt { display: flex; justify-content: space-between; align-items: center; gap: 10px; color: #b5cbd8; font-size: 12px; line-height: 1.5; }
.account-summary dt span { font: 10px/1.5 Consolas, monospace; }
.account-summary dd { margin: 8px 0 0; color: #edf5fa; font-size: 15px; line-height: 1.65; overflow-wrap: anywhere; }
.account-summary dd small { margin-left: 6px; color: #b5cbd8; font-size: 12px; }
.account-purpose { margin-top: auto; padding-top: 28px; }
.user-profile-page .account-purpose h3 { margin: 9px 0 0; color: #edf5fa !important; font-size: 19px; font-weight: 600; line-height: 1.5; }
.account-purpose p { margin: 10px 0 0; color: #c2d4df; font-size: 13px; line-height: 1.9; }
.account-purpose-note { margin-top: 22px; padding-top: 16px; border-top: 1px solid #334d5f; color: #b5cbd8; font-size: 12px; line-height: 1.85; }
.profile-editor { min-width: 0; border: 1px solid var(--profile-line); border-top: 2px solid #132c40; background: #fff; }
.profile-editor-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 14px 24px; border-bottom: 1px solid var(--profile-line); }
.profile-editor-head h3 { margin: 4px 0 0; font-size: 20px; font-weight: 650; line-height: 1.4; }
.profile-editor-note { color: var(--profile-muted); font-size: 12px; line-height: 1.6; }
.profile-editor :deep(.el-form) { min-width: 0; padding: 18px 24px 20px; }
.profile-editor :deep(.el-form-item) { min-width: 0; margin-bottom: 0; }
.profile-editor :deep(.el-form-item__label) { display: block; width: 100%; height: auto; margin-bottom: 8px; padding: 0; line-height: 1.5; }
.profile-field-label { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--profile-muted); font-size: 13px; }
.profile-field-label small { color: var(--profile-muted); font: 10px/1.5 Consolas, monospace; }
.profile-editor :deep(.el-input), .profile-editor :deep(.el-input-number) { width: 100%; min-width: 0; }
.profile-editor :deep(.el-input__wrapper) { min-height: 44px; padding: 8px 12px; border-radius: 5px !important; background: #f8fafc; box-shadow: 0 0 0 1px #cbdbe4 inset; }
.profile-editor :deep(.el-input__inner) { height: auto; color: var(--profile-ink); font-size: 13px; line-height: 1.7; }
.profile-editor :deep(.el-input__inner::placeholder) { color: #647a8a; }
.profile-editor :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 2px #167587 inset; }
.profile-editor :deep(.el-input.is-disabled .el-input__wrapper) { background: #eef3f6; box-shadow: 0 0 0 1px #d9e4eb inset; }
.profile-editor :deep(.el-input.is-disabled .el-input__inner) { color: #536b7d; -webkit-text-fill-color: #536b7d; }
.profile-editor :deep(.el-input-number) { height: 44px; line-height: 44px; }
.profile-editor :deep(.el-input-number .el-input__wrapper) { padding-right: 48px; padding-left: 48px; }
.profile-editor :deep(.el-input-number__increase), .profile-editor :deep(.el-input-number__decrease) { width: 44px; height: 42px; background: #f1f6f8; color: #086575; border-color: #cbdbe4; }
.profile-editor :deep(.el-input-number__increase:hover), .profile-editor :deep(.el-input-number__decrease:hover) { background: #e4f3ef; color: #064b59; }
.profile-editor :deep(.el-input-number__increase.is-disabled), .profile-editor :deep(.el-input-number__decrease.is-disabled) { color: #7a8e9d; background: #f1f4f6; }
.profile-editor :deep(.el-input-number__increase:focus-visible), .profile-editor :deep(.el-input-number__decrease:focus-visible) { z-index: 1; outline: 2px solid #167587; outline-offset: 2px; }
.profile-form-section { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--profile-line); }
.profile-section-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.profile-section-index { color: var(--profile-teal); font: 12px/1.5 Consolas, monospace; }
.profile-section-head h4 { display: flex; flex: 1; justify-content: space-between; align-items: center; gap: 14px; margin: 0; color: var(--profile-ink); font-size: 15px; font-weight: 600; line-height: 1.6; }
.profile-section-head h4 span { color: var(--profile-muted); font: 10px/1.5 Consolas, monospace; }
.user-profile-page .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 18px !important; }
.profile-wide-field { grid-column: 1 / -1; }
.action-row { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--profile-line); }
.action-row p { margin: 0; color: var(--profile-muted); font-size: 12px; line-height: 1.75; }
.user-profile-page .profile-save-button { flex-shrink: 0; min-width: 126px; min-height: 44px; height: auto; margin: 0; padding: 10px 20px; border: 1px solid #11283c !important; border-radius: 5px !important; background: #11283c !important; color: #fff !important; font-size: 13px; font-weight: 600; box-shadow: none; }
.user-profile-page .profile-save-button:hover { border-color: #1d4055 !important; background: #1d4055 !important; }
.profile-save-button:focus-visible, .profile-direction-button:focus-visible { outline: 2px solid #167587; outline-offset: 3px; }

/* Keep the shared shell untouched; these rules match only this mounted page. */
:global(.app-shell:has(.user-profile-page)) { background: #f5f7fa; }
:global(.app-shell:has(.user-profile-page) .topbar) { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 16px; min-height: 60px; padding: 8px 28px; background: #fff; border-bottom: 1px solid #d9e4eb; box-shadow: none; }
:global(.app-shell:has(.user-profile-page) .topbar-copy) { display: flex; flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: 14px; min-width: 0; }
:global(.app-shell:has(.user-profile-page) .topbar-copy h1) { margin: 0; font-size: 18px; font-weight: 650; line-height: 1.5; color: #132c40; white-space: nowrap; }
:global(.app-shell:has(.user-profile-page) .topbar-kicker) { margin: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; color: #536b7d; font: 10px/1.5 Consolas, monospace; letter-spacing: 0; }
:global(.app-shell:has(.user-profile-page) .topbar-copy p) { display: none; }
:global(.app-shell:has(.user-profile-page) .topbar-actions) { position: static; display: flex; width: auto; flex-wrap: nowrap; justify-content: flex-end; align-items: center; gap: 8px; margin: 0; transform: none; }
:global(.app-shell:has(.user-profile-page) .topbar-action) { min-height: 44px; margin: 0 !important; padding: 10px 9px; border: 0 !important; border-radius: 5px !important; background: transparent !important; color: #536b7d !important; font-size: 12px; font-weight: 400; box-shadow: none !important; }
:global(.app-shell:has(.user-profile-page) .topbar-action .el-icon) { width: 14px; height: 14px; font-size: 14px; color: #17447e; }
:global(.app-shell:has(.user-profile-page) .topbar-action:hover) { background: #edf8f6 !important; color: #086575 !important; }
:global(.app-shell:has(.user-profile-page) .topbar-action:focus-visible) { outline: 2px solid #167587; outline-offset: 2px; }
:global(.app-shell:has(.user-profile-page) .topbar-meta) { display: flex; align-items: center; min-width: 0; width: auto; gap: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; }
:global(.app-shell:has(.user-profile-page) .topbar-meta > div) { min-width: 58px; padding: 0 6px; border: 0 !important; border-radius: 0 !important; background: transparent !important; box-shadow: none !important; }
:global(.app-shell:has(.user-profile-page) .topbar-meta > div:last-child) { display: none; }
:global(.app-shell:has(.user-profile-page) .topbar-meta span) { font-size: 10px; line-height: 1.5; color: #536b7d; }
:global(.app-shell:has(.user-profile-page) .topbar-meta strong) { max-width: 160px; margin-top: 3px; color: #132c40; white-space: normal; overflow-wrap: anywhere; font-size: 12px; line-height: 1.5; }
:global(.app-shell:has(.user-profile-page) .content-area) { padding: 22px 28px 28px; background: #f5f7fa; overflow-y: auto; }

@media (max-width: 1300px) {
  :global(.app-shell:has(.user-profile-page) .topbar-kicker) { display: none; }
  .user-profile-page .profile-workspace { grid-template-columns: 260px minmax(0, 1fr); }
}
@media (max-width: 1080px) {
  .user-profile-page .profile-workspace { grid-template-columns: 230px minmax(0, 1fr); gap: 16px; }
  .account-panel { padding: 22px 20px; }
  .profile-editor-head { padding: 20px; }
  .profile-editor :deep(.el-form) { padding: 20px; }
  :global(.app-shell:has(.user-profile-page) .topbar) { gap: 10px; }
}
@media (max-width: 860px) {
  .user-profile-page .profile-workspace { grid-template-columns: minmax(0, 1fr); gap: 18px; }
  .account-panel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; padding: 22px; }
  .account-status { grid-column: 1; margin: -12px 0 0; }
  .account-summary { grid-row: 1 / 3; grid-column: 2; margin: 0; }
  .account-summary > div { padding: 9px 0; }
  .account-summary > div:first-child { border-top: 0; }
  .account-summary dd { margin-top: 5px; }
  .account-purpose { grid-column: 1 / -1; margin: 0; padding: 18px 0 0; border-top: 1px solid #334d5f; }
  .account-purpose h3 { font-size: 17px; }
  .account-purpose p { margin-top: 7px; }
  .account-purpose-note { margin-top: 12px; padding: 0; border: 0; }
}
@media (max-width: 760px) {
  :global(.app-shell:has(.user-profile-page) .topbar) { padding: 8px 18px; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; }
  :global(.app-shell:has(.user-profile-page) .topbar-actions) { grid-row: 2; grid-column: 1 / -1; justify-content: flex-start; }
  :global(.app-shell:has(.user-profile-page) .topbar-action) { padding: 10px 8px; }
  :global(.app-shell:has(.user-profile-page) .topbar-meta) { grid-row: 1; grid-column: 2; }
  :global(.app-shell:has(.user-profile-page) .content-area) { padding: 18px 18px 24px; }
  .user-profile-page .profile-page-intro { align-items: flex-start; flex-direction: column; gap: 16px; }
  .action-row { align-items: flex-start; }
}
@media (max-width: 560px) {
  .user-profile-page { gap: 18px !important; }
  .profile-page-intro h2 { font-size: 24px; }
  .account-panel { grid-template-columns: minmax(0, 1fr); padding: 22px 20px; gap: 16px; }
  .account-status { margin: 0; }
  .account-summary { grid-row: auto; grid-column: auto; }
  .account-summary > div { display: grid; grid-template-columns: 1fr 1fr; align-items: start; gap: 16px; padding: 12px 0; }
  .account-summary > div:first-child { border-top: 1px solid #334d5f; }
  .account-summary dt { display: block; }
  .account-summary dt span { display: block; margin-top: 4px; }
  .account-summary dd { margin: 0; text-align: right; }
  .account-purpose { grid-column: auto; }
  .profile-editor-head { padding: 20px 18px; }
  .profile-editor :deep(.el-form) { padding: 18px; }
  .profile-editor :deep(.el-input__inner) { font-size: 16px; }
  .user-profile-page .form-grid { grid-template-columns: minmax(0, 1fr); gap: 16px !important; }
  .profile-wide-field { grid-column: auto; }
  .action-row { flex-direction: column; gap: 16px; }
  .user-profile-page .profile-save-button { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .profile-save-button, .profile-direction-button, .profile-editor :deep(.el-input__wrapper), .profile-editor :deep(.el-input-number__increase), .profile-editor :deep(.el-input-number__decrease) { transition: none; }
  :global(.app-shell:has(.user-profile-page) .topbar-action) { transition: none; }
}
</style>
