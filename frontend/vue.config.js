module.exports = {
	productionSourceMap: false,
	devServer: {
		host: '0.0.0.0',
		port: 80,
		open: true,
		proxy: {
			[process.env.VUE_APP_BASE_API]: {
				target: `http://127.0.0.1:8023/svr`,
				changeOrigin: true,
				pathRewrite: {
					['^' + process.env.VUE_APP_BASE_API]: ''
				}
			}
		},
		disableHostCheck: true
	},
}