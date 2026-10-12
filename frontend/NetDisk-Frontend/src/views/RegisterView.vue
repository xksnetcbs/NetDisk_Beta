<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NInput, useMessage } from 'naive-ui'
import { api } from '../api'

const router = useRouter()
const message = useMessage()

const form = ref({ invite_code: '', username: '', password: '', display_name: '' })
const loading = ref(false)

async function onRegister() {
  loading.value = true
  try {
    await api.register(form.value)
    message.success('已提交注册，等待管理员审核')
    router.replace('/login')
  } catch (e) {
    message.error(e?.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px">
    <NCard style="width: 420px; max-width: 100%" title="注册">
      <NForm :model="form">
        <NFormItem label="邀请码">
          <NInput v-model:value="form.invite_code" placeholder="必填" />
        </NFormItem>
        <NFormItem label="用户名">
          <NInput v-model:value="form.username" placeholder="username" />
        </NFormItem>
        <NFormItem label="密码">
          <NInput v-model:value="form.password" type="password" placeholder="至少 6 位" />
        </NFormItem>
        <NFormItem label="显示名（可选）">
          <NInput v-model:value="form.display_name" placeholder="不填则等同用户名" />
        </NFormItem>
        <NButton type="primary" block :loading="loading" @click="onRegister">提交注册</NButton>
        <div style="margin-top: 10px; display: flex; justify-content: flex-end">
          <NButton text @click="router.replace('/login')">返回登录</NButton>
        </div>
      </NForm>
    </NCard>
  </div>
</template>
