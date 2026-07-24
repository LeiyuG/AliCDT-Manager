<template>
  <div class="card p-3 sm:p-5 flex items-center gap-2.5 sm:gap-4 min-w-0">
    <div class="text-xl sm:text-2xl flex-shrink-0">{{ icon }}</div>
    <div class="flex items-baseline gap-2 min-w-0">
      <div class="text-xl sm:text-2xl font-bold flex-shrink-0" :class="colorClass">{{ value }}</div>
      <div class="text-xs text-text-muted whitespace-nowrap">{{ label }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ icon: String, label: String, value: [Number, String], color: String })
const colorClass = computed(() => ({
  success: 'text-success',
  danger: 'text-danger',
  accent: 'text-accent',
  warning: 'text-warning',
}[props.color] || 'text-text'))
</script>
