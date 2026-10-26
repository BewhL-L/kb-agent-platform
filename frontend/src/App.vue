<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
// 根组件：通过 ConfigProvider 注入中文语言包（配合 Element Plus 按需引入）
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>
