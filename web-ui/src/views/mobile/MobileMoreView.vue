<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Users, Terminal, Settings2, MonitorSmartphone, LogOut, ChevronRight } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { setMobilePref } from '@/router'

const router = useRouter()
const { logout } = useAuth()

const links = [
  { to: '/m/accounts', label: '账号管理', desc: '闲鱼登录状态', icon: Users },
  { to: '/m/logs', label: '运行日志', desc: '查看任务日志', icon: Terminal },
  { to: '/m/settings', label: '设置', desc: '通知、AI 等配置', icon: Settings2 },
]

function goDesktop() {
  setMobilePref('desktop')
  router.push('/dashboard')
}

async function handleLogout() {
  await logout()
  router.push('/login')
}
</script>

<template>
  <div class="p-4 space-y-3">
    <div
      v-for="link in links"
      :key="link.to"
      class="bg-white rounded-2xl border border-slate-200/60 p-4 flex items-center gap-3 active:bg-slate-50 transition-colors"
      @click="router.push(link.to)"
    >
      <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
        <component :is="link.icon" class="w-5 h-5 text-primary" />
      </div>
      <div class="flex-1">
        <p class="font-bold text-slate-800 text-sm">{{ link.label }}</p>
        <p class="text-xs text-slate-400">{{ link.desc }}</p>
      </div>
      <ChevronRight class="w-5 h-5 text-slate-300" />
    </div>

    <button
      type="button"
      class="w-full bg-white rounded-2xl border border-slate-200/60 p-4 flex items-center gap-3 active:bg-slate-50 transition-colors"
      @click="goDesktop"
    >
      <div class="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center flex-shrink-0">
        <MonitorSmartphone class="w-5 h-5 text-slate-500" />
      </div>
      <div class="flex-1 text-left">
        <p class="font-bold text-slate-800 text-sm">切换到电脑版</p>
        <p class="text-xs text-slate-400">完整功能（在手机上可能显示不佳）</p>
      </div>
      <ChevronRight class="w-5 h-5 text-slate-300" />
    </button>

    <button
      type="button"
      class="w-full bg-white rounded-2xl border border-rose-200 p-4 flex items-center justify-center gap-2 text-rose-600 font-bold text-sm active:bg-rose-50 transition-colors"
      @click="handleLogout"
    >
      <LogOut class="w-5 h-5" />
      退出登录
    </button>
  </div>
</template>
