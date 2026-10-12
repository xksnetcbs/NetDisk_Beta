<script setup>
import { computed, ref } from 'vue'
import { NSelect } from 'naive-ui'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: [Number, Array], default: null },
  multiple: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const list = ref([])
const loading = ref(false)
const reqSeq = ref(0)
const searchTimer = ref(null)
const lastQ = ref(null)

const valueProxy = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function toLabel(u) {
  const dn = (u?.display_name || '').trim()
  const un = (u?.username || '').trim()
  const nick = dn || un || `#${u?.id}`
  const uname = un || nick
  return `${nick} (${uname})`
}

const options = computed(() =>
  (list.value || [])
    .map((u) => ({ label: toLabel(u), value: Number(u?.id) }))
    .filter((x) => Number.isFinite(x.value)),
)

async function fetchUsers(q) {
  const q1 = (q || '').trim()
  if (lastQ.value === q1 && (list.value || []).length > 0) return
  lastQ.value = q1
  const seq = reqSeq.value + 1
  reqSeq.value = seq
  loading.value = true
  try {
    const d = await api.searchUsers({ q: q1, page: 1, page_size: 5000 })
    if (seq !== reqSeq.value) return
    list.value = d.items || []
  } catch {
    if (seq !== reqSeq.value) return
    list.value = []
  } finally {
    if (seq !== reqSeq.value) return
    loading.value = false
  }
}

function onShowChange(show) {
  if (!show) return
  if ((list.value || []).length > 0) return
  fetchUsers('')
}

function onSearch(v) {
  if (searchTimer.value) clearTimeout(searchTimer.value)
  searchTimer.value = setTimeout(() => {
    fetchUsers(v)
  }, 200)
}
</script>

<template>
  <NSelect
    v-model:value="valueProxy"
    :multiple="multiple"
    filterable
    remote
    clearable
    :options="options"
    :loading="loading"
    :placeholder="placeholder || '选择用户'"
    @update:show="onShowChange"
    @search="onSearch"
  />
</template>
