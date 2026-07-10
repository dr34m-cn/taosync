<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { getUser } from '@/api/user';
import { useRouter } from 'vue-router';
const router = useRouter();
import { useAppStore } from '@/store/useAppStore';
const appStore = useAppStore();
const showFail = ref(false);
const loading = ref(true);
import lightDark from './components/lightDark.vue';
import locale from './components/locale.vue';
let timer = null;
const init = () => {
    timer = setTimeout(() => {
        showFail.value = true;
        timer = null;
    }, 1000);
    loading.value = true;
    setTimeout(() => {
        getUser().then(res => {
            appStore.set('user', res.data);
            router.replace('/home');
        }).finally(() => {
            loading.value = false;
        })
    }, 300)
}
onMounted(() => {
    init();
})
onBeforeUnmount(() => {
    if (timer) {
        clearTimeout(timer);
    }
})
</script>

<template>
    <div class="app-index" v-loading="loading || !showFail">
        <template v-if="!loading && showFail">
            <div class="top-box">
                <locale />
                <lightDark style="margin-left: 18px;" />
            </div>
            <p>{{ $t('error') }}</p>
            <el-button @click="init" size="large" type="primary">{{ $t('retry') }}</el-button>
        </template>
    </div>
</template>

<style lang="scss" scoped>
.app-index {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    right: 0;
    font-size: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;

    .top-box {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: right;
        padding: 16px 48px 5vh 0;
    }
}

@media (max-width: 768px) {
    .app-index {
        padding: 0 20px;
        box-sizing: border-box;
        font-size: 28px;
        text-align: center;

        .top-box {
            padding: 12px 0 12vh;
            justify-content: flex-end;
        }
    }
}
</style>
