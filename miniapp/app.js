const { ensureAuthenticated } = require("./utils/request");

App({
  onLaunch() {
    ensureAuthenticated().catch(() => {
      // 聊天页会展示登录失败状态和重试入口。
    });
  },
});
