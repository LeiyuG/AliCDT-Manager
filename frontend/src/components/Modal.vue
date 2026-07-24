<template>
  <div class="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
    <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="$emit('close')"></div>
    <div class="card p-5 sm:p-6 w-full max-w-sm max-h-[92dvh] overflow-y-auto relative z-10 fade-in rounded-b-none sm:rounded-2xl">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineEmits(['close'])
</script>
