<script setup>
import { ref, computed, markRaw } from 'vue'
const props = defineProps(['isCollapse', 'isMobile'])
const emit = defineEmits(['changeCollapse'])
const changeCollapse = function changeCollapse() {
    emit('changeCollapse', !props.isCollapse);
}
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { BellFilled, DataAnalysis, FolderOpened, Setting } from '@element-plus/icons-vue';
const menuList = ref([{
    index: '/home',
    icon: markRaw(DataAnalysis),
    title: computed(() => t('menu.home'))
}, {
    index: '/engine',
    icon: markRaw(FolderOpened),
    title: computed(() => t('menu.engine'))
}, {
    index: '/notify',
    icon: markRaw(BellFilled),
    title: computed(() => t('menu.notify'))
}, {
    index: '/setting',
    icon: markRaw(Setting),
    title: computed(() => t('menu.setting'))
}])
import { useRoute } from 'vue-router'
const route = useRoute()
const leftIndex = computed(() => route.meta?.leftIndex)
</script>

<template>
    <div class="aside-box">
        <div class="aside-main">
            <el-menu :default-active="leftIndex" :router="true" :collapse="isMobile ? false : isCollapse">
                <template v-for="menuItem in menuList" :key="menuItem.index">
                    <el-menu-item :index="menuItem.index" v-if="!menuItem.children">
                        <el-icon>
                            <component :is="menuItem.icon" />
                        </el-icon>
                        <template #title>{{ menuItem.title }}</template>
                    </el-menu-item>
                    <el-sub-menu :index="menuItem.index" v-else>
                        <template #title>
                            <el-icon>
                                <component :is="menuItem.icon" />
                            </el-icon>
                            <span>{{ menuItem.title }}</span>
                        </template>
                        <el-menu-item :index="subItem.index" :key="subItem.index" v-for="subItem in menuItem.children">
                            {{ subItem.title }}
                        </el-menu-item>
                    </el-sub-menu>
                </template>
            </el-menu>
        </div>
        <div class="aside-bottom">
            <el-icon style="cursor: pointer;" size="30" @click="changeCollapse">
                <Expand v-if="isCollapse" />
                <Fold v-else />
            </el-icon>
        </div>
    </div>
</template>

<style lang="scss" scoped>
.aside-box {
    border-right: 1px solid var(--border-color);

    .aside-main {
        height: calc(100% - 40px);
        overflow-y: auto;
        overflow-x: hidden;

        .el-menu {
            background-color: var(--app-left-background-color);
            border-right: none;
        }

        .el-menu--vertical {
            height: 100%;
        }
    }

    .aside-bottom {
        height: 40px;
        border-top: 1px solid var(--border-color);
        box-sizing: border-box;
        display: flex;
        align-items: center;
        padding: 0 18px;
    }
}

@media (max-width: 768px) {
    .aside-box {
        border-top: 1px solid var(--border-color);
        border-right: 0;
        box-shadow: 0 -4px 12px var(--app-header-shadow-color);

        .aside-main {
            height: 100%;
            overflow: hidden;

            .el-menu {
                height: 100%;
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
            }

            :deep(.el-menu-item) {
                height: 63px;
                min-width: 0;
                padding: 6px 4px !important;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 3px;
                line-height: 1.15;
                border-top: 2px solid transparent;
            }

            :deep(.el-menu-item.is-active) {
                border-top-color: var(--active-color);
                background-color: rgba(37, 99, 235, 0.08);
            }

            :deep(.el-menu-item .el-icon) {
                margin-right: 0;
                font-size: 20px;
            }

            :deep(.el-menu-item span) {
                width: 100%;
                overflow: hidden;
                font-size: 12px;
                text-align: center;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
        }

        .aside-bottom {
            display: none;
        }
    }
}
</style>
