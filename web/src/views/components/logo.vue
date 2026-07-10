<template>
    <div class="logo">
        <el-image style="width: 36px; height: 36px" src="/logo.png" fit="contain" />
        <div class="logo-title">{{ $t('title') }}</div>
    </div>
</template>

<style lang="scss" scoped>
.logo {
    display: flex;
    align-items: center;

    .logo-title {
        font-family: "Poppins", "微软雅黑", sans-serif;
        font-size: 24px;
        font-weight: bold;
        margin-left: 12px;
        background: linear-gradient(60deg,
                #f5d31b 0%,
                #d4a127 10%,
                #f5d31b 20%,
                #d4a127 30%,
                #f5d31b 40%,
                #d4a127 50%,
                #f5d31b 60%,
                #d4a127 70%,
                #f5d31b 80%,
                #d4a127 90%,
                #f5d31b 100%);
        background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: shine 8s linear infinite;
        background-size: 200% auto;
    }

    @keyframes shine {
        to {
            background-position: 200% center;
        }
    }
}
</style>
