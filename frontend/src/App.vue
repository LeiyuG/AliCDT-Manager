<template>
  <div class="min-h-screen bg-background text-text font-sans antialiased">
    <button
      v-if="isLogin"
      type="button"
      class="fixed top-4 right-4 z-50 h-10 px-3 rounded-xl bg-surface/90 border border-border shadow-sm backdrop-blur-md text-sm text-text hover:border-accent/50 hover:text-accent transition-colors flex items-center gap-2"
      :title="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
      @click="toggleTheme"
    >
      <span aria-hidden="true">{{ theme === 'light' ? '🌙' : '☀️' }}</span>
      <span class="hidden sm:inline">{{ theme === 'light' ? '深色' : '浅色' }}</span>
    </button>

    <!-- 登录页 -->
    <div v-if="isLogin">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </div>

    <!-- 主应用台 -->
    <div v-else class="min-h-screen lg:flex">
      <!-- 移动端顶部栏 -->
      <header class="lg:hidden fixed inset-x-0 top-0 z-40 h-16 px-4 flex items-center justify-between bg-surface/90 backdrop-blur-xl border-b border-border/70">
        <div class="flex items-center gap-2.5 min-w-0">
          <div class="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center border border-accent/20 flex-shrink-0">
            <span class="text-lg">🛡️</span>
          </div>
          <div class="min-w-0">
            <div class="text-sm font-bold truncate">AliCDT Manager</div>
            <div class="text-xs text-text-muted">{{ currentPageLabel }}</div>
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="w-10 h-10 rounded-xl text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
            :aria-label="theme === 'light' ? '切换到深色主题' : '切换到浅色主题'"
            @click="toggleTheme"
          >
            {{ theme === 'light' ? '🌙' : '☀️' }}
          </button>
          <button
            type="button"
            class="w-10 h-10 rounded-xl text-text-muted hover:text-danger hover:bg-danger/10 transition-colors"
            aria-label="退出登录"
            @click="logout"
          >
            🚪
          </button>
        </div>
      </header>

      <!-- 侧边栏 -->
      <aside class="hidden lg:flex w-64 flex-shrink-0 flex-col bg-surface/80 backdrop-blur-xl border-r border-border fixed h-full z-30 transition-all duration-300">
        <!-- Logo区 -->
        <div class="h-20 flex items-center px-6 border-b border-border/50">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-2xl bg-accent/10 flex items-center justify-center border border-accent/20 shadow-glow">
              <span class="text-xl animate-pulse">🛡️</span>
            </div>
            <div>
              <h1 class="text-base font-bold tracking-tight">AliCDT Manager</h1>
              <p class="text-xs text-text-muted font-medium">流量守护</p>
            </div>
          </div>
        </div>

        <!-- 导航菜单 -->
        <nav class="flex-1 px-4 py-6 relative">
          <!-- 滑动指示器：改为使用 transform 实现 GPU 加速，计算更精准 -->
          <div
            class="absolute left-4 right-4 h-11 rounded-xl bg-accent/10 border border-accent/20 transition-transform duration-300 cubic-bezier(0.4, 0, 0.2, 1) pointer-events-none"
            :style="{ transform: `translateY(${activeIndex * 52}px)` }"
          ></div>

          <!-- 导航项列表 -->
          <div class="flex flex-col gap-2 relative z-10">
            <div
              v-for="(item, index) in navItems"
              :key="item.path"
              class="flex items-center gap-3 px-4 h-11 rounded-xl text-sm font-medium cursor-pointer transition-colors duration-200"
              :class="activeIndex === index ? 'text-accent' : 'text-text-muted hover:text-text hover:bg-surface-hover/50'"
              @click="navigate(item.path)"
            >
              <span class="text-lg opacity-80 transition-opacity" :class="{ 'opacity-100': activeIndex === index }">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </div>
          </div>
        </nav>

        <!-- 底部操作 -->
        <div class="p-4 border-t border-border/50 space-y-1">
          <button @click="toggleTheme"
            class="w-full flex items-center justify-center gap-2 px-4 h-11 rounded-xl text-sm font-medium text-text-muted hover:text-accent hover:bg-accent/10 transition-colors duration-200">
            <span>{{ theme === 'light' ? '🌙' : '☀️' }}</span>
            <span>{{ theme === 'light' ? '切换深色主题' : '切换浅色主题' }}</span>
          </button>
          <button @click="logout"
            class="w-full flex items-center justify-center gap-2 px-4 h-11 rounded-xl text-sm font-medium text-text-muted hover:text-danger hover:bg-danger/10 transition-colors duration-200 group">
            <span class="group-hover:-translate-x-1 transition-transform duration-200">🚪</span>
            <span>退出登录</span>
          </button>
        </div>
      </aside>

      <!-- 主内容区 -->
      <main class="lg:ml-64 flex-1 min-h-screen bg-background relative overflow-x-hidden">
        <div class="px-3 pt-20 pb-28 sm:px-5 lg:p-8 max-w-7xl mx-auto">
          <!-- 路由过渡动画 -->
          <router-view v-slot="{ Component }">
            <transition name="fade-slide" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>

      <!-- 移动端底部导航 -->
      <nav class="lg:hidden fixed inset-x-0 bottom-0 z-40 bg-surface/95 backdrop-blur-xl border-t border-border/70 pb-[env(safe-area-inset-bottom)]">
        <div class="grid grid-cols-4 h-16">
          <button
            v-for="item in navItems"
            :key="item.path"
            type="button"
            class="flex flex-col items-center justify-center gap-1 text-xs transition-colors"
            :class="routeMatches(item.path) ? 'text-accent' : 'text-text-muted'"
            @click="navigate(item.path)"
          >
            <span
              class="w-8 h-7 rounded-lg flex items-center justify-center text-base transition-colors"
              :class="routeMatches(item.path) ? 'bg-accent/10' : ''"
            >
              {{ item.icon }}
            </span>
            <span>{{ item.label }}</span>
          </button>
        </div>
      </nav>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const theme = ref(localStorage.getItem('theme') === 'dark' ? 'dark' : 'light')

document.documentElement.dataset.theme = theme.value

const isLogin = computed(() => route.path === '/login')

const navItems = [
  { path: '/', icon: '⚡', label: '总览' },
  { path: '/accounts', icon: '🔑', label: '账户管理' },
  { path: '/logs', icon: '📋', label: '系统日志' },
  { path: '/settings', icon: '⚙️', label: '系统设置' },
]

// 智能计算激活状态：废弃容易脱节的 watch，改用纯 computed
// 增加了对子路由（如 /accounts/detail）的高亮支持
const activeIndex = computed(() => {
  const index = navItems.findIndex(item => routeMatches(item.path))
  return index === -1 ? 0 : index
})

const currentPageLabel = computed(() => navItems[activeIndex.value]?.label || '控制台')

function routeMatches(path) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function navigate(path) {
  router.push(path)
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  document.documentElement.dataset.theme = theme.value
  localStorage.setItem('theme', theme.value)
}

function logout() {
  localStorage.removeItem('token')
  router.push('/login')
}
</script>

<style scoped>
/* 路由切换：缩放与透明度融合的现代过渡效果 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(15px) scale(0.99);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-15px) scale(0.99);
}

/* 基础渐变效果 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
