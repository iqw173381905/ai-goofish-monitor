<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RefreshCcw, UserCircle, CheckCircle2, XCircle } from 'lucide-vue-next'
import { listAccounts, type AccountItem } from '@/api/accounts'
import { toast } from '@/components/ui/toast'

const accounts = ref<AccountItem[]>([])
const isLoading = ref(false)

async function load() {
  isLoading.value = true
  try {
    accounts.value = await listAccounts()
  } catch (e) {
    toast({ title: '加载失败', description: (e as Error).message, variant: 'destructive' })
  } finally {
    isLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="p-4 space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-base font-black text-slate-800">账号管理</h2>
      <button
        type="button"
        class="w-10 h-10 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-slate-500 active:bg-slate-100"
        @click="load"
        aria-label="刷新"
      >
        <RefreshCcw class="w-5 h-5" :class="isLoading && 'animate-spin'" />
      </button>
    </div>

    <div v-if="isLoading && accounts.length === 0" class="flex flex-col items-center py-16 gap-3 text-slate-400">
      <RefreshCcw class="w-8 h-8 animate-spin" />
      <p class="text-sm">加载中…</p>
    </div>

    <div v-else-if="accounts.length === 0" class="text-center py-16 text-slate-300">
      <p class="text-sm font-bold">暂无账号</p>
      <p class="text-xs mt-1">请在电脑端添加闲鱼账号</p>
    </div>

    <article
      v-for="acc in accounts"
      :key="acc.name"
      class="bg-white rounded-2xl border border-slate-200/60 p-4 shadow-sm"
    >
      <div class="flex items-center gap-3">
        <div class="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
          <UserCircle class="w-6 h-6 text-primary" />
        </div>
        <div class="flex-1 min-w-0">
          <h3 class="font-bold text-slate-800 text-sm truncate">{{ acc.name }}</h3>
          <p class="text-xs text-slate-400 mt-0.5">
            {{ acc.valid === false ? '需重新登录' : '登录有效' }}
          </p>
        </div>
        <CheckCircle2 v-if="acc.valid !== false" class="w-6 h-6 text-emerald-500 flex-shrink-0" />
        <XCircle v-else class="w-6 h-6 text-rose-400 flex-shrink-0" />
      </div>
      <p v-if="acc.valid === false" class="mt-2 text-xs text-slate-400">
        请在电脑端账号管理中重新扫码登录
      </p>
    </article>
  </div>
</template>
