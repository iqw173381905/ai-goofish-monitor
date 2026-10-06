<script setup lang="ts">
import { RouterView } from 'vue-router'
import Toaster from '@/components/ui/toast/Toaster.vue'
import { useTaskNotifier } from '@/composables/useTaskNotifier'

// 全局任务完成通知监听（任务 running -> idle 时弹窗提示）
useTaskNotifier()
</script>

<template>
  <RouterView />
  <Toaster />
</template>
