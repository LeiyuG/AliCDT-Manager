<template>
  <div class="p-0 sm:p-2 lg:p-6 space-y-5 sm:space-y-6 fade-in">
    <h1 class="text-xl font-semibold text-text">系统设置</h1>

    <!-- 保活策略 -->
    <div class="card p-4 sm:p-5 space-y-4">
      <div class="flex items-center gap-2">
        <span class="text-lg">⏱️</span>
        <div>
          <h2 class="font-medium text-text text-sm">保活检查间隔</h2>
          <p class="text-xs text-text-muted mt-0.5">设置多久检查一次已开启保活的实例，保存后立即生效</p>
        </div>
      </div>

      <div>
        <label class="text-xs text-text-muted mb-1.5 block">检查间隔（分钟）</label>
        <input
          v-model="form.keep_alive_interval_minutes"
          type="number"
          min="1"
          max="1440"
          step="1"
          class="input"
          placeholder="5"
        />
        <div class="text-xs text-text-muted mt-1.5">
          可设置 1～1440 分钟。建议使用 5～15 分钟，间隔越短，调用阿里云接口越频繁。
        </div>
      </div>

      <div class="flex gap-2 flex-wrap">
        <button
          v-for="minutes in [5, 10, 15, 30]"
          :key="minutes"
          type="button"
          class="px-3 py-1.5 rounded-lg text-xs border transition-colors"
          :class="form.keep_alive_interval_minutes === String(minutes)
            ? 'border-accent bg-accent/10 text-accent'
            : 'border-border bg-surface text-text-muted hover:text-text'"
          @click="form.keep_alive_interval_minutes = String(minutes)"
        >
          {{ minutes }} 分钟
        </button>
      </div>

      <button @click="save" :disabled="saving" class="btn-primary w-full sm:w-auto justify-center flex items-center gap-2">
        <span v-if="saving" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
        {{ saving ? '保存中...' : '保存保活设置' }}
      </button>
    </div>

    <!-- 多账号实例轮换 -->
    <div class="card p-4 sm:p-5 space-y-4">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-start gap-2 min-w-0">
          <span class="text-lg">🔁</span>
          <div>
            <h2 class="font-semibold text-text text-sm">多账号实例每日轮换</h2>
            <p class="text-xs text-text-muted mt-1">只管理下方选中的实例，同账号其他实例不会被换班操作</p>
          </div>
        </div>
        <button
          type="button"
          class="relative flex-shrink-0"
          :aria-label="form.rotation_enabled === '1' ? '关闭每日轮换' : '开启每日轮换'"
          @click="form.rotation_enabled = form.rotation_enabled === '1' ? '0' : '1'"
        >
          <span :class="form.rotation_enabled === '1' ? 'bg-accent' : 'bg-border'" class="block w-11 h-6 rounded-full transition-colors"></span>
          <span :class="form.rotation_enabled === '1' ? 'translate-x-5' : 'translate-x-0.5'"
            class="absolute top-0.5 left-0 w-5 h-5 bg-white rounded-full transition-transform shadow"></span>
        </button>
      </div>

      <div class="rounded-xl bg-warning/10 border border-warning/20 px-3 py-2 text-xs text-warning-dark leading-relaxed">
        切换顺序：启动目标实例 → 确认 Running 和公网 IP → 更新 Cloudflare → 等待缓冲 → 节省停机旧实例。
        启用时会立即按“当前当班实例”校准所选机器的状态。
      </div>

      <div class="space-y-2">
        <div class="flex items-center justify-between gap-3">
          <label class="text-xs text-text-muted">轮换实例列表</label>
          <span class="text-xs text-text-muted">每个账号最多选择一台</span>
        </div>
        <div
          v-for="(instanceId, index) in rotationInstanceIds"
          :key="`rotation-${index}`"
          class="flex items-center gap-2"
        >
          <span class="w-7 h-7 flex-shrink-0 rounded-lg bg-accent/10 text-accent text-xs font-semibold flex items-center justify-center">
            {{ index + 1 }}
          </span>
          <select v-model="rotationInstanceIds[index]" class="input min-w-0">
            <option value="">请选择抢占式实例</option>
            <option
              v-for="instance in spotInstances"
              :key="`${index}-${instance.instance_id}`"
              :value="instance.instance_id"
              :disabled="isInstanceUnavailable(instance, index)"
            >
              {{ instanceOptionLabel(instance) }}
            </option>
          </select>
          <button
            type="button"
            class="h-10 px-3 flex-shrink-0 rounded-xl border border-danger/30 bg-danger/5 text-danger text-xs font-medium hover:bg-danger/10 hover:border-danger/60 transition-colors disabled:bg-surface disabled:border-border disabled:text-text-muted disabled:opacity-60 disabled:cursor-not-allowed"
            :disabled="rotationInstanceIds.length <= 2"
            aria-label="移除该轮换实例"
            :title="rotationInstanceIds.length <= 2 ? '启用轮换至少需要保留两项' : '仅移出轮换列表，不会删除实例'"
            @click="removeRotationInstance(index)"
          >
            移出轮换
          </button>
        </div>
        <button type="button" class="btn-ghost border border-border w-full sm:w-auto" @click="addRotationInstance">
          ＋ 添加轮换实例
        </button>
        <p class="text-xs text-text-muted leading-relaxed">
          列表顺序就是轮换顺序。若账号内还有其他地区实例，只要不加入本列表，换班不会启动或停止它。
        </p>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">当前当班实例</label>
          <select v-model="form.rotation_active_instance_id" class="input">
            <option value="">请选择</option>
            <option
              v-for="(instanceId, index) in selectedRotationIds"
              :key="`active-${instanceId}`"
              :value="instanceId"
            >
              {{ index + 1 }} · {{ selectedInstanceLabel(instanceId) }}
            </option>
          </select>
          <div class="text-xs text-text-muted mt-1 leading-relaxed">
            当前真正承载服务的实例；Cloudflare 域名会指向它，其余轮换实例保持节省停机。
          </div>
        </div>
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">每日切换时间（北京时间）</label>
          <input v-model="form.rotation_switch_time" type="time" class="input" />
        </div>
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">流量保护值（GB）</label>
          <input v-model="form.rotation_traffic_protect_gb" type="number" min="1" step="0.1" class="input" />
          <div class="text-xs text-text-muted mt-1">当前账号达到该值时，提前切换到备用账号</div>
        </div>
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">DDNS 切换缓冲（秒）</label>
          <input v-model="form.rotation_grace_seconds" type="number" min="0" max="600" class="input" />
          <div class="text-xs text-text-muted mt-1">建议 60～120 秒；此期间两台实例会短暂同时运行</div>
        </div>
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">状态确认超时（秒）</label>
          <input v-model="form.rotation_timeout_seconds" type="number" min="60" max="900" class="input" />
        </div>
      </div>

      <div class="border-t border-border pt-4 space-y-3">
        <div class="flex items-center gap-2">
          <span>☁️</span>
          <div>
            <div class="text-sm font-medium text-text">Cloudflare DDNS</div>
            <div class="text-xs text-text-muted">密钥仅保存在服务器数据库，页面不会回显</div>
          </div>
        </div>
        <div>
          <label class="text-xs text-text-muted mb-1.5 block">认证方式</label>
          <select v-model="form.cloudflare_auth_mode" class="input">
            <option value="token">API Token（推荐）</option>
            <option value="global_key">邮箱 + Global API Key</option>
          </select>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div v-if="form.cloudflare_auth_mode === 'token'">
            <label class="text-xs text-text-muted mb-1.5 block">API Token</label>
            <input
              v-model="form.cloudflare_api_token"
              type="password"
              class="input"
              :placeholder="cloudflareTokenConfigured ? '已配置，留空不修改' : '需要 DNS Read / DNS Write 权限'"
            />
          </div>
          <div v-if="form.cloudflare_auth_mode === 'token'">
            <label class="text-xs text-text-muted mb-1.5 block">Zone ID</label>
            <input v-model="form.cloudflare_zone_id" class="input font-mono" placeholder="可留空，改用 Zone 名称自动查询" />
          </div>
          <div v-if="form.cloudflare_auth_mode === 'global_key'">
            <label class="text-xs text-text-muted mb-1.5 block">Cloudflare 登录邮箱</label>
            <input v-model="form.cloudflare_auth_email" type="email" class="input" placeholder="name@example.com" />
          </div>
          <div v-if="form.cloudflare_auth_mode === 'global_key'">
            <label class="text-xs text-text-muted mb-1.5 block">Global API Key</label>
            <input
              v-model="form.cloudflare_auth_key"
              type="password"
              class="input"
              :placeholder="cloudflareKeyConfigured ? '已配置，留空不修改' : '不要填写账号密码'"
            />
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1.5 block">
              Zone 名称{{ form.cloudflare_auth_mode === 'token' ? '（与 Zone ID 二选一）' : '' }}
            </label>
            <input v-model="form.cloudflare_zone_name" class="input" placeholder="example.com" />
          </div>
          <div>
            <label class="text-xs text-text-muted mb-1.5 block">A 记录名称</label>
            <input v-model="form.cloudflare_record_name" class="input" placeholder="cdt 或 subdomain.example.com" />
          </div>
        </div>
        <div class="text-xs text-text-muted rounded-lg bg-surface px-3 py-2 leading-relaxed">
          填写 Zone 名称后，可直接使用简短记录名，例如 <span class="font-mono text-text">subdomain</span>，
          系统会自动解析为 <span class="font-mono text-text">subdomain.example.com</span>。
        </div>
      </div>

      <div class="grid grid-cols-1 sm:flex gap-2">
        <button @click="save" :disabled="saving" class="btn-primary justify-center flex items-center gap-2">
          <span v-if="saving" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ saving ? '保存中...' : '保存轮换设置' }}
        </button>
        <button @click="testCloudflare" :disabled="cfTesting"
          class="btn-ghost justify-center flex items-center gap-2 border border-border px-3 py-2 rounded-xl">
          <span v-if="cfTesting" class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin"></span>
          {{ cfTesting ? '验证中...' : '☁️ 验证 Cloudflare' }}
        </button>
      </div>
    </div>

    <!-- TG 通知 -->
    <div class="card p-4 sm:p-5 space-y-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-lg">✈️</span>
        <h2 class="font-medium text-text text-sm">Telegram 通知</h2>
      </div>
      <div>
        <label class="text-xs text-text-muted mb-1.5 block">Bot Token</label>
        <input v-model="form.tg_bot_token" class="input" placeholder="123456:ABC..." />
      </div>
      <div>
        <label class="text-xs text-text-muted mb-1.5 block">Chat ID</label>
        <input v-model="form.tg_chat_id" class="input" placeholder="123..." />
      </div>

      <!-- 每日流量汇报开关 -->
      <div class="flex items-center justify-between gap-4 py-2 border-t border-border">
        <div class="min-w-0">
          <div class="text-sm text-text">每日流量汇报</div>
          <div class="text-xs text-text-muted mt-0.5">每天北京时间 00:00 推送所有实例流量情况</div>
        </div>
        <div class="relative cursor-pointer flex-shrink-0" @click="form.tg_daily_report = form.tg_daily_report === '1' ? '0' : '1'">
          <div :class="form.tg_daily_report === '1' ? 'bg-accent' : 'bg-border'" class="w-11 h-6 rounded-full transition-colors"></div>
          <div :class="form.tg_daily_report === '1' ? 'translate-x-5' : 'translate-x-0.5'"
            class="absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow"></div>
        </div>
      </div>

      <div class="text-xs text-text-muted bg-surface rounded-lg px-3 py-2 space-y-1">
        <div class="font-medium mb-1">通知触发条件：</div>
        <div>• 流量熔断自动停机</div>
        <div>• 抢占式实例被回收并拉起</div>
        <div>• 定时开关机执行</div>
        <div>• 日报优先显示本地备注，并始终保留实例 ID</div>
        <div v-if="form.tg_daily_report === '1'" class="text-accent">• 每日 00:00 流量汇报（已开启）</div>
        <div v-else class="text-text-muted">• 每日流量汇报（已关闭）</div>
      </div>

      <div class="grid grid-cols-1 sm:flex gap-2 sm:flex-wrap">
        <button @click="save" :disabled="saving" class="btn-primary justify-center flex items-center gap-2">
          <span v-if="saving" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ saving ? '保存中...' : '保存设置' }}
        </button>
        <button @click="testTg" :disabled="testing"
          class="btn-ghost justify-center flex items-center gap-2 border border-border px-3 py-2 rounded-xl">
          <span v-if="testing" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ testing ? '发送中...' : '📨 测试消息' }}
        </button>
        <button @click="testDailyReport" :disabled="reportTesting"
          class="btn-ghost justify-center flex items-center gap-2 border border-border px-3 py-2 rounded-xl">
          <span v-if="reportTesting" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ reportTesting ? '发送中...' : '📊 测试流量汇报' }}
        </button>
      </div>
    </div>

    <!-- 修改密码 -->
    <div class="card p-4 sm:p-5 space-y-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-lg">🔒</span>
        <h2 class="font-medium text-text text-sm">修改密码</h2>
      </div>
      <div>
        <label class="text-xs text-text-muted mb-1.5 block">新密码（至少6位）</label>
        <input v-model="newPassword" type="password" class="input" placeholder="••••••••" />
      </div>
      <button @click="changePassword" class="btn-danger w-full sm:w-auto text-xs px-4 py-2">更新密码</button>
    </div>

    <div v-if="msg" class="text-xs rounded-lg px-3 py-2 border"
      :class="msg.startsWith('❌') ? 'text-danger bg-danger/10 border-danger/20' : 'text-success bg-success/10 border-success/20'">
      {{ msg }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStore } from '../stores'
import axios from 'axios'

const store = useStore()
const saving = ref(false)
const testing = ref(false)
const reportTesting = ref(false)
const cfTesting = ref(false)
const msg = ref('')
const newPassword = ref('')
const cloudflareTokenConfigured = ref(false)
const cloudflareKeyConfigured = ref(false)
const form = ref({
  keep_alive_interval_minutes: '5',
  rotation_enabled: '0',
  rotation_instance_ids: '[]',
  rotation_active_instance_id: '',
  rotation_switch_time: '00:00',
  rotation_traffic_protect_gb: '188',
  rotation_grace_seconds: '90',
  rotation_timeout_seconds: '600',
  cloudflare_auth_mode: 'token',
  cloudflare_api_token: '',
  cloudflare_auth_email: '',
  cloudflare_auth_key: '',
  cloudflare_zone_id: '',
  cloudflare_zone_name: '',
  cloudflare_record_name: '',
  tg_bot_token: '',
  tg_chat_id: '',
  tg_daily_report: '0',
})
const rotationInstanceIds = ref(['', ''])

onMounted(async () => {
  await Promise.all([store.fetchSettings(), store.fetchAccounts(), store.fetchInstances()])
  form.value.keep_alive_interval_minutes = store.settings.keep_alive_interval_minutes || '5'
  form.value.rotation_enabled = store.settings.rotation_enabled || '0'
  try {
    const configuredIds = JSON.parse(store.settings.rotation_instance_ids || '[]')
    rotationInstanceIds.value = Array.isArray(configuredIds)
      ? configuredIds.filter(Boolean)
      : []
  } catch {
    rotationInstanceIds.value = []
  }
  if (!rotationInstanceIds.value.length) {
    rotationInstanceIds.value = [
      store.settings.rotation_instance_a || '',
      store.settings.rotation_instance_b || '',
    ].filter(Boolean)
  }
  while (rotationInstanceIds.value.length < 2) rotationInstanceIds.value.push('')
  form.value.rotation_active_instance_id = store.settings.rotation_active_instance_id || ''
  form.value.rotation_switch_time = store.settings.rotation_switch_time || '00:00'
  form.value.rotation_traffic_protect_gb = store.settings.rotation_traffic_protect_gb || '188'
  form.value.rotation_grace_seconds = store.settings.rotation_grace_seconds || '90'
  form.value.rotation_timeout_seconds = store.settings.rotation_timeout_seconds || '600'
  form.value.cloudflare_auth_mode = store.settings.cloudflare_auth_mode || 'token'
  form.value.cloudflare_auth_email = store.settings.cloudflare_auth_email || ''
  form.value.cloudflare_zone_id = store.settings.cloudflare_zone_id || ''
  form.value.cloudflare_zone_name = store.settings.cloudflare_zone_name || ''
  form.value.cloudflare_record_name = store.settings.cloudflare_record_name || ''
  cloudflareTokenConfigured.value = store.settings.cloudflare_api_token_configured === '1'
  cloudflareKeyConfigured.value = store.settings.cloudflare_auth_key_configured === '1'
  form.value.tg_bot_token = store.settings.tg_bot_token || ''
  form.value.tg_chat_id = store.settings.tg_chat_id || ''
  form.value.tg_daily_report = store.settings.tg_daily_report || '0'
})

const accountMap = computed(() => Object.fromEntries(store.accounts.map(account => [account.id, account])))
const spotInstances = computed(() => store.instances.filter(instance => instance.is_spot))
const selectedRotationIds = computed(() => rotationInstanceIds.value.filter(Boolean))

function instanceOptionLabel(instance) {
  const account = accountMap.value[instance.account_id]
  const name = instance.remark || instance.instance_name || instance.instance_id
  return `${name} · ${account?.name || '未知账户'} · ${instance.region_id || '未知地域'} · ${instance.public_ip || '无公网 IP'}`
}

function selectedInstanceLabel(instanceId) {
  const instance = store.instances.find(item => item.instance_id === instanceId)
  return instance ? instanceOptionLabel(instance) : instanceId
}

function addRotationInstance() {
  rotationInstanceIds.value.push('')
}

function isInstanceUnavailable(instance, currentIndex) {
  return rotationInstanceIds.value.some((selectedId, index) => {
    if (!selectedId || index === currentIndex) return false
    const selectedInstance = store.instances.find(item => item.instance_id === selectedId)
    return (
      selectedId === instance.instance_id
      || selectedInstance?.account_id === instance.account_id
    )
  })
}

function removeRotationInstance(index) {
  const removedId = rotationInstanceIds.value[index]
  rotationInstanceIds.value.splice(index, 1)
  if (form.value.rotation_active_instance_id === removedId) {
    form.value.rotation_active_instance_id = selectedRotationIds.value[0] || ''
  }
}

function authHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

function settingsItems() {
  const interval = Number(form.value.keep_alive_interval_minutes)
  if (!Number.isInteger(interval) || interval < 1 || interval > 1440) {
    throw new Error('保活检查间隔必须是 1～1440 之间的整数分钟')
  }
  const rotationIds = selectedRotationIds.value
  form.value.rotation_instance_ids = JSON.stringify(rotationIds)
  if (form.value.rotation_enabled === '1') {
    if (rotationIds.length < 2) {
      throw new Error('请至少选择两台抢占式实例参与轮换')
    }
    if (new Set(rotationIds).size !== rotationIds.length) {
      throw new Error('轮换实例不能重复')
    }
    const selectedInstances = rotationIds.map(instanceId =>
      store.instances.find(instance => instance.instance_id === instanceId)
    )
    if (selectedInstances.some(instance => !instance)) {
      throw new Error('轮换列表中存在已失效的实例，请重新选择')
    }
    if (new Set(selectedInstances.map(instance => instance.account_id)).size !== selectedInstances.length) {
      throw new Error('每个阿里云账号只能选择一台实例参与轮换')
    }
    if (!rotationIds.includes(form.value.rotation_active_instance_id)) {
      throw new Error('请选择当前当班实例')
    }
    if (form.value.cloudflare_auth_mode === 'token') {
      if (!form.value.cloudflare_api_token && !cloudflareTokenConfigured.value) {
        throw new Error('请填写 Cloudflare API Token')
      }
      if (!form.value.cloudflare_zone_id && !form.value.cloudflare_zone_name) {
        throw new Error('请填写 Cloudflare Zone ID 或 Zone 名称')
      }
    } else {
      if (!form.value.cloudflare_auth_email) {
        throw new Error('请填写 Cloudflare 登录邮箱')
      }
      if (!form.value.cloudflare_auth_key && !cloudflareKeyConfigured.value) {
        throw new Error('请填写 Cloudflare Global API Key')
      }
      if (!form.value.cloudflare_zone_name) {
        throw new Error('请填写 Cloudflare Zone 名称')
      }
    }
    if (!form.value.cloudflare_record_name) {
      throw new Error('请填写 Cloudflare A 记录名称')
    }
  }
  form.value.keep_alive_interval_minutes = String(interval)
  return Object.entries(form.value).map(([key, value]) => ({ key, value: String(value) }))
}

async function testCloudflare() {
  cfTesting.value = true
  msg.value = ''
  try {
    const items = settingsItems()
    await axios.post('/api/settings', items, { headers: authHeader() })
    const { data } = await axios.post('/api/settings/test-cloudflare', {}, { headers: authHeader() })
    if (form.value.cloudflare_auth_mode === 'token') {
      cloudflareTokenConfigured.value = true
      form.value.cloudflare_api_token = ''
    } else {
      cloudflareKeyConfigured.value = true
      form.value.cloudflare_auth_key = ''
    }
    msg.value = `✅ Cloudflare 连接成功：${data.record_name} → ${data.content}`
  } catch (e) {
    msg.value = '❌ Cloudflare 验证失败：' + (e.response?.data?.detail || e.message)
  } finally {
    cfTesting.value = false
    setTimeout(() => msg.value = '', 5000)
  }
}

async function save() {
  saving.value = true
  msg.value = ''
  try {
    const items = settingsItems()
    await axios.post('/api/settings', items, { headers: authHeader() })
    if (form.value.cloudflare_api_token) {
      cloudflareTokenConfigured.value = true
      form.value.cloudflare_api_token = ''
    }
    if (form.value.cloudflare_auth_key) {
      cloudflareKeyConfigured.value = true
      form.value.cloudflare_auth_key = ''
    }
    await store.fetchSettings()
    msg.value = '✅ 设置已保存'
  } catch (e) {
    msg.value = '❌ 保存失败：' + (e.response?.data?.detail || e.message)
  } finally {
    saving.value = false
    setTimeout(() => msg.value = '', 3000)
  }
}

async function testTg() {
  saving.value = true
  msg.value = ''
  try {
    const items = settingsItems()
    await axios.post('/api/settings', items, { headers: authHeader() })
  } catch (e) {
    msg.value = '❌ 保存失败，无法发送测试'
    saving.value = false
    return
  }
  saving.value = false
  testing.value = true
  try {
    await axios.post('/api/settings/test-tg', {}, { headers: authHeader() })
    msg.value = '✅ 测试消息已发送，请检查 Telegram'
  } catch (e) {
    msg.value = '❌ 发送失败：' + (e.response?.data?.detail || e.message)
  } finally {
    testing.value = false
    setTimeout(() => msg.value = '', 5000)
  }
}

async function testDailyReport() {
  reportTesting.value = true
  msg.value = ''
  try {
    await axios.post('/api/settings/test-daily-report', {}, { headers: authHeader() })
    msg.value = '✅ 流量汇报已发送，请检查 Telegram'
  } catch (e) {
    msg.value = '❌ 发送失败：' + (e.response?.data?.detail || e.message)
  } finally {
    reportTesting.value = false
    setTimeout(() => msg.value = '', 5000)
  }
}

async function changePassword() {
  if (!newPassword.value || newPassword.value.length < 6) {
    msg.value = '❌ 密码至少6位'
    return
  }
  try {
    await axios.post('/api/settings/change-password',
      { password: newPassword.value },
      { headers: authHeader() }
    )
    newPassword.value = ''
    msg.value = '✅ 密码已更新，下次登录生效'
    setTimeout(() => msg.value = '', 3000)
  } catch (e) {
    msg.value = '❌ 更新失败：' + (e.response?.data?.detail || e.message)
  }
}
</script>
