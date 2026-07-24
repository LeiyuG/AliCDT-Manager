<template>
  <div class="card p-3 sm:p-5 flex items-center gap-2.5 sm:gap-4 min-w-0">
    <div class="text-xl sm:text-2xl flex-shrink-0">{{ icon }}</div>
    <div>
      <div class="text-xl sm:text-2xl font-bold" :class="colorClass">{{ value }}</div>
      <div class="text-xs text-text-muted mt-0.5">{{ label }}</div>
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
