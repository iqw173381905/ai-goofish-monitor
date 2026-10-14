<script setup lang="ts">
import { RouterView, useRoute, useRouter } from 'vue-router'
import { ListTodo, Layers, Menu } from 'lucide-vue-next'
import Toaster from '@/components/ui/toast/Toaster.vue'
import { useTaskNotifier } from '@/composables/useTaskNotifier'

useTaskNotifier()
const route = useRoute()
const router = useRouter()

const tabs = [
  { to: '/m/tasks', label: '任务', icon: ListTodo, match: ['MobileTasks'] },
  { to: '/m/results', label: '结果', icon: Layers, match: ['MobileResults'] },
  { to: '/m/more', label: '更多', icon: Menu, match: ['MobileMore'] },
]

function isActive(tab: (typeof tabs)[number]) {
  return tab.match.includes(route.name as string)
}

function go(to: string) {
  router.push(to)
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 flex flex-col max-w-lg mx-auto">
    <!-- 顶部标题栏 -->
    <header class="sticky top-0 z-40 bg-white/90 backdrop-blur-md border-b border-slate-200/60 px-4 py-3">
      <h1 class="text-base font-black text-slate-800 tracking-tight">
        AI <span class="text-primary">闲鱼</span>监控
      </h1>
    </header>

    <!-- 内容区 -->
    <main class="flex-1 overflow-y-auto pb-24">
      <RouterView />
    </main>

    <!-- 底部标签栏 -->
    <nav class="fixed bottom-0 left-0 right-0 z-40 bg-white/95 backdrop-blur-md border-t border-slate-200/60">
      <div class="max-w-lg mx-auto grid grid-cols-3">
        <button
          v-for="tab in tabs"
          :key="tab.to"
          type="button"
          class="flex flex-col items-center gap-1 py-2.5 active:bg-slate-100 transition-colors"
          :class="isActive(tab) ? 'text-primary' : 'text-slate-400'"
          @click="go(tab.to)"
        >
          <component :is="tab.icon" class="w-6 h-6" />
          <span class="text-xs font-bold">{{ tab.label }}</span>
        </button>
      </div>
      <!-- iPhone 底部安全区 -->
      <div class="h-[env(safe-area-inset-bottom)]"></div>
    </nav>

    <Toaster />
  </div>
</template>
