<template>
  <div class="p-0 sm:p-2 lg:p-6 space-y-5 sm:space-y-6 fade-in">
    <div class="flex items-center justify-between gap-3">
      <h1 class="text-xl font-semibold text-text">账户管理</h1>
      <button @click="openAdd" class="btn-primary flex items-center gap-1.5 flex-shrink-0 px-3 sm:px-4">
        <span>＋</span> 添加账户
      </button>
    </div>

    <div class="space-y-3">
      <div v-if="store.accounts.length === 0" class="card p-12 text-center text-text-muted text-sm">
        暂无账户，点击右上角添加
      </div>

      <div v-for="acc in store.accounts" :key="acc.id" class="card p-4 sm:p-5">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-9 h-9 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center text-sm">🔑</div>
            <div class="min-w-0">
              <div class="font-medium text-text text-sm">{{ acc.name }}</div>
              <div class="text-xs text-text-muted font-mono mt-0.5 truncate">{{ acc.access_key_id }}</div>
            </div>
          </div>
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-xs px-2 py-0.5 rounded-full bg-surface border border-border text-text-muted">{{ acc.region_id }}</span>
            <span v-if="acc.keep_alive" class="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent">保活</span>
            <button @click="openEdit(acc)" class="btn-ghost text-xs px-2 py-1">编辑</button>
            <button @click="confirmDelete(acc)" class="btn-danger text-xs px-2 py-1">删除</button>
          </div>
        </div>

        <div class="grid grid-cols-2 lg:grid-cols-5 gap-2 sm:gap-3 mt-4 text-xs">
          <div class="bg-surface rounded-lg px-3 py-2">
            <div class="text-text-muted mb-0.5">流量上限</div>
            <div class="text-text">{{ acc.traffic_limit_gb }} GB</div>
          </div>
          <div class="bg-surface rounded-lg px-3 py-2">
            <div class="text-text-muted mb-0.5">流量熔断</div>
            <div class="text-text">{{ acc.threshold_percent }}%</div>
          </div>
          <div class="bg-surface rounded-lg px-3 py-2">
            <div class="text-text-muted mb-0.5">待还熔断</div>
            <div class="text-text">{{ acc.outstanding_threshold > 0 ? acc.outstanding_threshold : '未启用' }}</div>
          </div>
          <div class="bg-surface rounded-lg px-3 py-2">
            <div class="text-text-muted mb-0.5">停机模式</div>
            <div class="text-text">{{ acc.shutdown_mode === 'StopCharging' ? '节省停机' : '普通停机' }}</div>
          </div>
          <div class="bg-surface rounded-lg px-3 py-2 col-span-2 lg:col-span-1">
            <div class="text-text-muted mb-0.5">自动计划</div>
            <div :class="accountPlan(acc).tone" class="font-medium truncate" :title="accountPlan(acc).detail">
              {{ accountPlan(acc).summary }}
            </div>
            <div v-if="accountPlan(acc).detail" class="text-[11px] text-text-muted mt-0.5 truncate">
              {{ accountPlan(acc).detail }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <Modal v-if="showForm" wide @close="showForm = false">
      <div class="space-y-5">
        <div>
          <h2 class="font-semibold text-text text-lg">{{ editTarget ? '编辑账户' : '添加账户' }}</h2>
          <div class="text-xs text-text-muted mt-1">账户凭据、流量保护和自动化计划可以在同一页完成设置。</div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <section class="rounded-xl border border-border bg-surface/40 p-4 space-y-3">
            <div class="text-sm font-medium text-text flex items-center gap-2"><span>🔑</span> 账户与实例</div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">备注名 *</label>
            <input v-model="form.name" class="input" placeholder="我的阿里云" />
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">AccessKey ID *</label>
            <input v-model="form.access_key_id" class="input" placeholder="LTAI5t..." />
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">
              AccessKey Secret {{ editTarget ? '（不修改请留空）' : '*' }}
            </label>
            <input v-model="form.access_key_secret" type="password" class="input" placeholder="••••••••" />
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-text-muted mb-1 block">地域 ID *</label>
              <input v-model="form.region_id" class="input" placeholder="ap-southeast-1" />
            </div>
            <div>
              <label class="text-xs text-text-muted mb-1 block">站点类型</label>
              <select v-model="form.site_type" class="input">
                <option value="international">国际站</option>
                <option value="china">中国站</option>
              </select>
            </div>
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">实例 ID（用于保活/定时任务）</label>
            <input v-model="form.instance_id" class="input" placeholder="i-..." />
          </div>
          </section>

          <section class="rounded-xl border border-border bg-surface/40 p-4 space-y-3">
            <div class="text-sm font-medium text-text flex items-center gap-2"><span>🛡️</span> 保护策略</div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-text-muted mb-1 block">流量上限 (GB)</label>
              <input v-model.number="form.traffic_limit_gb" type="number" class="input" />
            </div>
            <div>
              <label class="text-xs text-text-muted mb-1 block">流量熔断阈值 (%)</label>
              <input v-model.number="form.threshold_percent" type="number" class="input" />
            </div>
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">待还金额熔断阈值（0表示不启用）</label>
            <input v-model.number="form.outstanding_threshold" type="number" step="0.01" class="input" placeholder="例如 0.45" />
            <div class="text-xs text-text-muted mt-1">当账户待还款金额达到此数值时自动停机</div>
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1 block">停机模式</label>
            <select v-model="form.shutdown_mode" class="input">
              <option value="StopCharging">节省停机（停止计费）</option>
              <option value="KeepCharging">普通停机（继续计费）</option>
            </select>
          </div>

          <label class="flex items-center justify-between gap-3 cursor-pointer rounded-lg bg-background/40 border border-border px-3 py-2.5">
            <span>
              <span class="text-sm text-text block">抢占式实例自动保活</span>
              <span class="text-xs text-text-muted">仅对上方填写的实例 ID 生效</span>
            </span>
            <div class="relative">
              <input type="checkbox" v-model="form.keep_alive" class="sr-only" />
              <div :class="form.keep_alive ? 'bg-accent' : 'bg-border'" class="w-9 h-5 rounded-full transition-colors"></div>
              <div :class="form.keep_alive ? 'translate-x-4' : 'translate-x-0.5'" class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform"></div>
            </div>
          </label>
          </section>
        </div>

        <section class="rounded-xl border border-border bg-surface/40 p-4 space-y-3">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <div class="text-sm font-medium text-text flex items-center gap-2"><span>⏰</span> 定时开关机</div>
              <div class="text-xs text-text-muted mt-1">两个时间都留空即为关闭；设置任一时间后即启用对应任务。</div>
            </div>
            <span
              class="self-start sm:self-auto text-xs px-2.5 py-1 rounded-full border font-medium"
              :class="scheduleEnabled ? 'bg-success/10 border-success/20 text-success' : 'bg-surface border-border text-text-muted'"
            >
              {{ scheduleEnabled ? '已开启' : '未开启' }}
            </span>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-text-muted mb-1 block">定时关机</label>
              <input v-model="form.auto_stop_time" type="time" class="input" />
            </div>
            <div>
              <label class="text-xs text-text-muted mb-1 block">定时开机</label>
              <input v-model="form.auto_start_time" type="time" class="input" />
            </div>
          </div>
          <div class="text-xs text-text-muted bg-surface rounded-lg px-3 py-2">
            💡 开启保活时，定时关机期间保活会自动暂停，定时开机后恢复
          </div>
          <button
            v-if="scheduleEnabled"
            @click="clearSchedule"
            type="button"
            class="btn-ghost text-xs px-3 py-1.5"
          >
            清除定时计划
          </button>
        </section>

        <div v-if="formError" class="text-xs text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
          {{ formError }}
        </div>

        <div class="flex gap-3 pt-2">
          <button @click="showForm = false" class="btn-ghost flex-1">取消</button>
          <button @click="submit" :disabled="submitting" class="btn-primary flex-1">
            {{ submitting ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal v-if="deleteTarget" @close="deleteTarget = null">
      <div class="text-center space-y-4">
        <div class="text-4xl">🗑️</div>
        <div class="font-semibold">确认删除账户？</div>
        <div class="text-sm text-text-muted">{{ deleteTarget.name }}</div>
        <div class="text-xs text-warning bg-warning/10 border border-warning/20 rounded-lg px-3 py-2">
          删除账户后，关联的实例记录也会一并清除
        </div>
        <div class="flex gap-3">
          <button @click="deleteTarget = null" class="btn-ghost flex-1">取消</button>
          <button @click="doDelete" class="btn-danger flex-1">确认删除</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStore } from '../stores'
import Modal from '../components/Modal.vue'

const store = useStore()
const showForm = ref(false)
const editTarget = ref(null)
const deleteTarget = ref(null)
const submitting = ref(false)
const formError = ref('')

const defaultForm = () => ({
  name: '', access_key_id: '', access_key_secret: '',
  region_id: 'ap-southeast-1', site_type: 'international',
  instance_id: '', traffic_limit_gb: 200, threshold_percent: 95,
  outstanding_threshold: 0,
  shutdown_mode: 'StopCharging', keep_alive: false,
  auto_stop_time: null, auto_start_time: null,
})

const form = ref(defaultForm())
const scheduleEnabled = computed(() => Boolean(form.value.auto_stop_time || form.value.auto_start_time))

onMounted(() => Promise.all([
  store.fetchAccounts(),
  store.fetchSettings(),
  store.fetchInstances(),
]))

const rotationIds = computed(() => {
  try {
    const ids = JSON.parse(store.settings.rotation_instance_ids || '[]')
    return Array.isArray(ids) ? ids.filter(Boolean) : []
  } catch {
    return []
  }
})

function accountPlan(acc) {
  if (acc.auto_stop_time || acc.auto_start_time) {
    const parts = []
    if (acc.auto_stop_time) parts.push(`${acc.auto_stop_time} 关`)
    if (acc.auto_start_time) parts.push(`${acc.auto_start_time} 开`)
    return {
      summary: '定时开关机',
      detail: parts.join(' · '),
      tone: 'text-accent',
    }
  }

  if (store.settings.rotation_enabled === '1') {
    const accountRotationId = rotationIds.value.find(instanceId =>
      store.instances.some(instance =>
        instance.instance_id === instanceId && instance.account_id === acc.id
      )
    )
    if (accountRotationId) {
      if (accountRotationId === store.settings.rotation_active_instance_id) {
        return {
          summary: '轮换 · 当前当班',
          detail: '正在承载服务',
          tone: 'text-success',
        }
      }
      return {
        summary: '轮换 · 下次启动',
        detail: nextRotationTime(accountRotationId),
        tone: 'text-accent',
      }
    }
  }

  return {
    summary: '未设置',
    detail: '',
    tone: 'text-text-muted',
  }
}

function nextRotationTime(instanceId) {
  const ids = rotationIds.value
  const activeIndex = ids.indexOf(store.settings.rotation_active_instance_id)
  const targetIndex = ids.indexOf(instanceId)
  if (activeIndex < 0 || targetIndex < 0 || ids.length < 2) return '等待轮换状态校准'

  const steps = (targetIndex - activeIndex + ids.length) % ids.length
  if (steps === 0) return '正在承载服务'

  const [hour, minute] = (store.settings.rotation_switch_time || '00:00')
    .split(':')
    .map(Number)
  const now = new Date()
  const beijingParts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(now).map(part => [part.type, part.value])
  )
  const todaySwitch = new Date(Date.UTC(
    Number(beijingParts.year),
    Number(beijingParts.month) - 1,
    Number(beijingParts.day),
    hour - 8,
    minute,
  ))
  const nextSwitch = new Date(todaySwitch)
  let dayOffset = 0
  if (now >= todaySwitch) {
    nextSwitch.setUTCDate(nextSwitch.getUTCDate() + 1)
    dayOffset = 1
  }
  nextSwitch.setUTCDate(nextSwitch.getUTCDate() + steps - 1)
  dayOffset += steps - 1

  const dayLabel = dayOffset === 0
    ? '今天'
    : dayOffset === 1
      ? '明天'
      : new Intl.DateTimeFormat('zh-CN', {
          timeZone: 'Asia/Shanghai',
          month: 'numeric',
          day: 'numeric',
        }).format(nextSwitch)
  return `${dayLabel} ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function openAdd() {
  editTarget.value = null
  form.value = defaultForm()
  formError.value = ''
  showForm.value = true
}

function openEdit(acc) {
  editTarget.value = acc
  form.value = { ...acc, access_key_secret: '' }
  formError.value = ''
  showForm.value = true
}

function clearSchedule() {
  form.value.auto_stop_time = null
  form.value.auto_start_time = null
}

async function submit() {
  formError.value = ''
  if (!form.value.name || !form.value.access_key_id) {
    formError.value = '请填写必填项'
    return
  }
  if (!editTarget.value && !form.value.access_key_secret) {
    formError.value = '请填写 AccessKey Secret'
    return
  }
  submitting.value = true
  try {
    if (editTarget.value) {
      await store.updateAccount(editTarget.value.id, form.value)
    } else {
      await store.createAccount(form.value)
    }
    showForm.value = false
  } catch (e) {
    formError.value = e.response?.data?.detail || '保存失败'
  } finally {
    submitting.value = false
  }
}

function confirmDelete(acc) { deleteTarget.value = acc }
async function doDelete() {
  await store.deleteAccount(deleteTarget.value.id)
  deleteTarget.value = null
}
</script>
