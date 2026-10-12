<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NIcon, NInput, NRadioButton, NRadioGroup, NSpace, useMessage } from 'naive-ui'
import { ColorPaletteOutline, MailOutline, SaveOutline, SettingsOutline } from '@vicons/ionicons5'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const message = useMessage()
const router = useRouter()

const form = ref({ old_password: '', new_password: '' })
const profileForm = ref({ email: '' })
const loading = ref(false)
const profileLoading = ref(false)
const themeMode = computed({
  get: () => ui.themeMode,
  set: (v) => ui.setThemeMode(v),
})

async function onChangePassword() {
  loading.value = true
  try {
    await api.changePassword(form.value)
    message.success('已修改密码，请重新登录')
    form.value = { old_password: '', new_password: '' }
    auth.clearSession()
    router.replace('/login')
  } catch (e) {
    message.error(e?.message || '修改失败')
  } finally {
    loading.value = false
  }
}

async function onSaveProfile() {
  if (!auth.user?.id) return
  profileLoading.value = true
  try {
    const d = await api.patchUser(auth.user.id, { email: profileForm.value.email })
    auth.setUser(d.user)
    message.success('已保存')
  } catch (e) {
    message.error(e?.message || '保存失败')
  } finally {
    profileLoading.value = false
  }
}

watch(
  () => auth.user?.email,
  (v) => {
    profileForm.value.email = v || ''
  },
  { immediate: true },
)
</script>

<template>
  <NSpace vertical size="large">
    <NCard>
      <template #header><span class="dcp-title-with-icon"><NIcon><SettingsOutline /></NIcon>个人设置</span></template>
      <div style="opacity: 0.8">用户：{{ auth.user?.display_name || auth.user?.username }}</div>
    </NCard>

    <NCard>
      <template #header><span class="dcp-title-with-icon"><NIcon><ColorPaletteOutline /></NIcon>主题</span></template>
      <NRadioGroup v-model:value="themeMode">
        <NSpace>
          <NRadioButton value="system">跟随系统</NRadioButton>
          <NRadioButton value="light">亮色</NRadioButton>
          <NRadioButton value="dark">暗色</NRadioButton>
        </NSpace>
      </NRadioGroup>
    </NCard>

    <NCard title="修改密码">
      <NForm :model="form">
        <NFormItem label="旧密码">
          <NInput v-model:value="form.old_password" type="password" />
        </NFormItem>
        <NFormItem label="新密码">
          <NInput v-model:value="form.new_password" type="password" />
        </NFormItem>
        <NButton type="primary" :loading="loading" @click="onChangePassword"><template #icon><NIcon><SaveOutline /></NIcon></template>保存</NButton>
      </NForm>
    </NCard>

    <NCard>
      <template #header><span class="dcp-title-with-icon"><NIcon><MailOutline /></NIcon>邮箱</span></template>
      <NForm :model="profileForm">
        <NFormItem label="邮箱">
          <NInput v-model:value="profileForm.email" placeholder="请输入邮箱（可留空清除）" />
        </NFormItem>
        <NButton type="primary" :loading="profileLoading" @click="onSaveProfile"><template #icon><NIcon><SaveOutline /></NIcon></template>保存</NButton>
      </NForm>
    </NCard>
  </NSpace>
</template>
