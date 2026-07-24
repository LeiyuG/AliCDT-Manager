<template>
  <div class="p-0 sm:p-2 lg:p-6 space-y-5 sm:space-y-6 fade-in">
    <!-- 顶部栏 -->
    <div class="flex items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-text">总览</h1>
        <p class="text-sm text-text-muted mt-0.5">{{ now }}</p>
      </div>
      <button @click="sync" :disabled="store.loading"
        class="btn-primary flex items-center gap-2 flex-shrink-0 px-3 sm:px-4">
        <span :class="store.loading ? 'animate-spin' : ''">🔄</span>
        {{ store.loading ? '同步中...' : '立即同步' }}
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
      <StatCard icon="🖥️" label="实例总数" :value="instances.length" />
      <StatCard icon="✅" label="运行中" :value="runningCount" color="success" />
      <StatCard icon="⏹️" label="已停机" :value="stoppedCount" color="danger" />
      <StatCard icon="🛡️" label="保活中" :value="keepAliveCount" color="accent" />
    </div>

    <!-- 实例卡片列表（支持拖拽排序） -->
    <div v-if="sortedInstances.length === 0" class="card p-12 text-center">
      <div class="text-4xl mb-3">🌐</div>
      <div class="text-text-muted text-sm">暂无实例，请先添加账户并同步</div>
    </div>

    <div
      v-else
      class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4"
    >
      <div
        v-for="(inst, index) in sortedInstances"
        :key="inst.instance_id"
        :draggable="canDrag && !orderSaving"
        @dragstart="onDragStart($event, inst.instance_id)"
        @dragover.prevent="onDragOver($event, inst.instance_id)"
        @dragend="onDragEnd"
        @drop.prevent="onDrop($event, inst.instance_id)"
        :class="[
          'h-full flex flex-col transition-all duration-200',
          dragOverId === inst.instance_id && draggingId !== inst.instance_id
            ? 'scale-[1.02] opacity-80'
            : '',
          draggingId === inst.instance_id
            ? 'opacity-40 scale-95'
            : '',
        ]"
      >
        <div v-if="sortedInstances.length > 1" class="lg:hidden flex items-center justify-between px-1 mb-2 text-xs text-text-muted">
          <span>顺序 {{ index + 1 }}</span>
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="w-9 h-9 rounded-lg border border-border bg-surface text-text disabled:opacity-30"
              :disabled="index === 0 || orderSaving"
              :aria-label="`上移 ${inst.remark || inst.instance_name || inst.instance_id}`"
              @click="moveInstance(index, -1)"
            >
              ↑
            </button>
            <button
              type="button"
              class="w-9 h-9 rounded-lg border border-border bg-surface text-text disabled:opacity-30"
              :disabled="index === sortedInstances.length - 1 || orderSaving"
              :aria-label="`下移 ${inst.remark || inst.instance_name || inst.instance_id}`"
              @click="moveInstance(index, 1)"
            >
              ↓
            </button>
          </div>
        </div>
        <InstanceCard
          :instance="inst"
          :account="accountMap[inst.account_id]"
          :settings="store.settings"
          @start="store.controlInstance(inst.instance_id, 'start')"
          @stop="store.controlInstance(inst.instance_id, 'stop')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStore } from '../stores'
import StatCard from '../components/StatCard.vue'
import InstanceCard from '../components/InstanceCard.vue'

const store = useStore()
const now = ref('')
const canDrag = ref(true)
const orderSaving = ref(false)

// 拖拽状态
const draggingId = ref(null)
const dragOverId = ref(null)

// 自定义排序（持久化到 localStorage）
const SORT_KEY = 'instance_sort_order'
const customOrder = ref(parseOrder(localStorage.getItem(SORT_KEY)))

const instances = computed(() => store.instances)
const runningCount = computed(() => instances.value.filter(i => i.status === 'Running').length)
const stoppedCount = computed(() => instances.value.filter(i => i.status === 'Stopped').length)
const keepAliveCount = computed(() => store.accounts.filter(a => a.keep_alive).length)
const accountMap = computed(() => {
  const m = {}
  store.accounts.forEach(a => m[a.id] = a)
  return m
})

// 按自定义顺序排列实例
const sortedInstances = computed(() => {
  const arr = [...instances.value]
  if (customOrder.value.length === 0) return arr
  return arr.sort((a, b) => {
    const ia = customOrder.value.indexOf(a.instance_id)
    const ib = customOrder.value.indexOf(b.instance_id)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
})

function parseOrder(rawValue) {
  try {
    const parsed = JSON.parse(rawValue || '[]')
    return Array.isArray(parsed) ? parsed.filter(Boolean) : []
  } catch {
    return []
  }
}

async function persistOrder(order) {
  customOrder.value = order
  localStorage.setItem(SORT_KEY, JSON.stringify(order))
  orderSaving.value = true
  try {
    await store.saveInstanceOrder(order)
  } catch (error) {
    alert(error.response?.data?.detail || '实例顺序保存失败')
  } finally {
    orderSaving.value = false
  }
}

function onDragStart(e, id) {
  draggingId.value = id
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', id)
}

function onDragOver(e, id) {
  dragOverId.value = id
}

async function onDrop(e, targetId) {
  const sourceId = draggingId.value
  if (!sourceId || sourceId === targetId) return

  const order = sortedInstances.value.map(i => i.instance_id)
  const fromIdx = order.indexOf(sourceId)
  const toIdx = order.indexOf(targetId)
  if (fromIdx === -1 || toIdx === -1) return

  // 移动元素
  order.splice(fromIdx, 1)
  order.splice(toIdx, 0, sourceId)

  await persistOrder(order)
}

async function moveInstance(index, direction) {
  const order = sortedInstances.value.map(instance => instance.instance_id)
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= order.length) return
  ;[order[index], order[targetIndex]] = [order[targetIndex], order[index]]
  await persistOrder(order)
}

function onDragEnd() {
  draggingId.value = null
  dragOverId.value = null
}

function updateTime() {
  now.value = new Date().toLocaleString('zh-CN', { hour12: false })
}

let timer
onMounted(async () => {
  canDrag.value = window.matchMedia('(min-width: 1024px) and (pointer: fine)').matches
  await Promise.all([
    store.fetchAccounts(),
    store.fetchInstances(),
    store.fetchSettings(),
  ])
  const serverOrder = parseOrder(store.settings.instance_sort_order)
  const knownIds = new Set(store.instances.map(instance => instance.instance_id))
  const preferredOrder = serverOrder.length ? serverOrder : customOrder.value
  const normalizedOrder = [
    ...preferredOrder.filter(instanceId => knownIds.has(instanceId)),
    ...store.instances
      .map(instance => instance.instance_id)
      .filter(instanceId => !preferredOrder.includes(instanceId)),
  ]
  if (
    JSON.stringify(normalizedOrder) !== JSON.stringify(serverOrder)
    || JSON.stringify(normalizedOrder) !== JSON.stringify(customOrder.value)
  ) {
    await persistOrder(normalizedOrder)
  } else {
    customOrder.value = normalizedOrder
  }
  updateTime()
  timer = setInterval(updateTime, 1000)
})
onUnmounted(() => clearInterval(timer))

async function sync() {
  await store.syncAll()
}
</script>
