<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NInput, NTabPane, NTabs, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const message = useMessage()

const loginForm = ref({ username: '', password: '' })
const bootstrapForm = ref({ username: '', password: '', display_name: '' })
const loading = ref(false)

async function onLogin() {
  loading.value = true
  try {
    const d = await api.login(loginForm.value)
    auth.setSession(d)
    message.success('登录成功')
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/')
  } catch (e) {
    message.error(e?.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function onBootstrap() {
  loading.value = true
  try {
    const d = await api.bootstrap(bootstrapForm.value)
    auth.setSession(d)
    message.success('初始化成功')
    router.replace('/')
  } catch (e) {
    message.error(e?.message || '初始化失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px">
    <NCard style="width: 420px; max-width: 100%" title="DCP_NetDisk">
      <NTabs type="line" animated>
        <NTabPane name="login" tab="登录">
          <NForm :model="loginForm">
            <NFormItem label="用户名">
              <NInput v-model:value="loginForm.username" placeholder="username" />
            </NFormItem>
            <NFormItem label="密码">
              <NInput v-model:value="loginForm.password" type="password" placeholder="password" />
            </NFormItem>
            <NButton type="primary" block :loading="loading" @click="onLogin">登录</NButton>
            <div style="margin-top: 10px; opacity: 0.7; font-size: 12px">登录后，此设备将在 30 天内自动登录；退出登录后将停止记住账号。</div>
            <div style="margin-top: 10px; display: flex; justify-content: flex-end">
              <NButton text @click="router.push('/register')">注册</NButton>
            </div>

          </NForm>
        </NTabPane>
<!--        <NTabPane name="bootstrap" tab="初始化">-->
<!--          <NForm :model="bootstrapForm">-->
<!--            <NFormItem label="用户名">-->
<!--              <NInput v-model:value="bootstrapForm.username" placeholder="首次初始化将创建 super_admin" />-->
<!--            </NFormItem>-->
<!--            <NFormItem label="密码">-->
<!--              <NInput v-model:value="bootstrapForm.password" type="password" placeholder="至少 6 位" />-->
<!--            </NFormItem>-->
<!--            <NFormItem label="显示名">-->
<!--              <NInput v-model:value="bootstrapForm.display_name" placeholder="可选" />-->
<!--            </NFormItem>-->
<!--            <NButton type="primary" block :loading="loading" @click="onBootstrap">初始化并登录</NButton>-->
<!--          </NForm>-->
<!--        </NTabPane>-->
      </NTabs>
    </NCard>
  </div>
</template>
