const {
  clearAccessToken,
  ensureAuthenticated,
  request,
  uploadFile,
} = require("../../utils/request");

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

let messageSequence = 0;

function nextMessageId() {
  messageSequence += 1;
  return `message-${Date.now()}-${messageSequence}`;
}

function getErrorMessage(error) {
  if (error && (error.kind === "auth" || error.kind === "login")) {
    return "登录失败，请重试。";
  }
  if (error && error.statusCode === 429) {
    return "消息发送太频繁，请稍后再试。";
  }
  if (error && error.statusCode === 503) {
    return "AI暂时无法回复，请稍后再试。";
  }
  if (error && error.kind === "network") {
    return "网络连接失败，请稍后重试。";
  }
  return "请求失败，请稍后重试。";
}

function getImageErrorMessage(error) {
  if (error && (error.kind === "auth" || error.kind === "login")) {
    return "登录失败，请重试。";
  }
  if (error && error.statusCode === 429) {
    return "消息发送太频繁，请稍后再试。";
  }
  if (error && (error.statusCode === 413 || error.statusCode === 422)) {
    return "图片格式或大小不符合要求。";
  }
  if (error && error.statusCode === 503) {
    return "AI暂时无法分析这张图片，请稍后再试。";
  }
  if (error && error.kind === "network") {
    return "网络连接失败，请稍后重试。";
  }
  return "图片上传失败，请稍后重试。";
}

Page({
  data: {
    messages: [],
    inputValue: "",
    scrollTarget: "",
    loginStatus: "loading",
    loginRetrying: false,
    historyLoading: false,
    sending: false,
    imageAnalyzing: false,
    clearing: false,
  },

  onLoad() {
    this.historyRequestVersion = 0;
    this.messageRevision = 0;
    this.initializeLogin();
  },

  onUnload() {
    this.historyRequestVersion += 1;
  },

  async initializeLogin(forceRefresh = false) {
    this.setData({
      loginStatus: "loading",
      loginRetrying: forceRefresh,
    });
    try {
      await ensureAuthenticated({ forceRefresh });
      this.setData({ loginStatus: "ready", loginRetrying: false });
      this.loadHistory();
    } catch (error) {
      this.setData({ loginStatus: "error", loginRetrying: false });
    }
  },

  async loadHistory() {
    const requestVersion = this.historyRequestVersion + 1;
    const messageRevision = this.messageRevision;
    this.historyRequestVersion = requestVersion;
    this.setData({ historyLoading: true });

    try {
      const response = await request({
        path: "/api/miniapp/v1/history",
      });
      if (
        requestVersion !== this.historyRequestVersion ||
        messageRevision !== this.messageRevision
      ) {
        return;
      }

      const sourceMessages = Array.isArray(response && response.messages)
        ? response.messages
        : [];
      const messages = sourceMessages
        .filter(
          (item) =>
            item &&
            (item.role === "user" || item.role === "assistant") &&
            typeof item.content === "string"
        )
        .map((item) => ({
          id: nextMessageId(),
          role: item.role,
          type: "text",
          content: item.content,
          pending: false,
        }));
      const lastMessage = messages[messages.length - 1];
      this.setData({
        messages,
        scrollTarget: lastMessage ? lastMessage.id : "",
      });
    } catch (error) {
      // History recovery is best-effort; a failure must not block new chats.
    } finally {
      if (requestVersion === this.historyRequestVersion) {
        this.setData({ historyLoading: false });
      }
    }
  },

  retryLogin() {
    if (this.data.loginRetrying) {
      return;
    }
    this.initializeLogin(true);
  },

  handleInput(event) {
    this.setData({ inputValue: event.detail.value });
  },

  async sendMessage() {
    if (
      this.data.sending ||
      this.data.imageAnalyzing ||
      this.data.loginStatus !== "ready"
    ) {
      return;
    }

    const message = this.data.inputValue.trim();
    if (!message) {
      return;
    }
    if (Array.from(message).length > 2000) {
      wx.showToast({
        title: "消息不能超过2000字符",
        icon: "none",
      });
      return;
    }

    const userMessage = {
      id: nextMessageId(),
      role: "user",
      type: "text",
      content: message,
      pending: false,
    };
    const thinkingMessage = {
      id: nextMessageId(),
      role: "assistant",
      type: "text",
      content: "AI 正在思考...",
      pending: true,
    };

    this.messageRevision += 1;
    this.setData({
      messages: [...this.data.messages, userMessage, thinkingMessage],
      inputValue: "",
      sending: true,
      scrollTarget: thinkingMessage.id,
    });

    try {
      const response = await request({
        path: "/api/miniapp/v1/chat",
        method: "POST",
        data: { message },
      });
      if (!response || typeof response.reply !== "string") {
        throw new Error("invalid chat response");
      }

      const assistantMessage = {
        id: thinkingMessage.id,
        role: "assistant",
        type: "text",
        content: response.reply,
        pending: false,
      };
      this.setData({
        messages: this.data.messages.map((item) =>
          item.id === thinkingMessage.id ? assistantMessage : item
        ),
        scrollTarget: assistantMessage.id,
      });
    } catch (error) {
      this.setData({
        messages: this.data.messages.filter(
          (item) => item.id !== thinkingMessage.id
        ),
        scrollTarget: userMessage.id,
      });

      if (error && (error.kind === "auth" || error.kind === "login")) {
        clearAccessToken();
        this.setData({ loginStatus: "error" });
      }
      wx.showToast({ title: getErrorMessage(error), icon: "none" });
    } finally {
      this.setData({ sending: false });
    }
  },

  chooseImage() {
    if (
      this.data.sending ||
      this.data.imageAnalyzing ||
      this.data.clearing ||
      this.data.loginStatus !== "ready"
    ) {
      return;
    }

    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["album", "camera"],
      success: (result) => {
        const selectedFile = result.tempFiles && result.tempFiles[0];
        if (!selectedFile || !selectedFile.tempFilePath) {
          wx.showToast({ title: "图片选择失败，请重试。", icon: "none" });
          return;
        }
        if (
          typeof selectedFile.size === "number" &&
          selectedFile.size > MAX_IMAGE_BYTES
        ) {
          wx.showToast({
            title: "图片格式或大小不符合要求。",
            icon: "none",
          });
          return;
        }
        this.sendImage(selectedFile.tempFilePath);
      },
      fail: (error) => {
        if (!error || !String(error.errMsg || "").includes("cancel")) {
          wx.showToast({ title: "图片选择失败，请重试。", icon: "none" });
        }
      },
    });
  },

  async sendImage(imagePath) {
    if (
      this.data.sending ||
      this.data.imageAnalyzing ||
      this.data.loginStatus !== "ready"
    ) {
      return;
    }

    const imageMessage = {
      id: nextMessageId(),
      role: "user",
      type: "image",
      imagePath,
      pending: false,
    };
    const thinkingMessage = {
      id: nextMessageId(),
      role: "assistant",
      type: "text",
      content: "AI 正在分析图片...",
      pending: true,
    };

    this.messageRevision += 1;
    this.setData({
      messages: [...this.data.messages, imageMessage, thinkingMessage],
      imageAnalyzing: true,
      scrollTarget: thinkingMessage.id,
    });

    try {
      const response = await uploadFile({
        path: "/api/miniapp/v1/image",
        filePath: imagePath,
        name: "file",
      });
      if (!response || typeof response.reply !== "string") {
        throw new Error("invalid image response");
      }

      const assistantMessage = {
        id: thinkingMessage.id,
        role: "assistant",
        type: "text",
        content: response.reply,
        pending: false,
      };
      this.setData({
        messages: this.data.messages.map((item) =>
          item.id === thinkingMessage.id ? assistantMessage : item
        ),
        scrollTarget: assistantMessage.id,
      });
    } catch (error) {
      this.setData({
        messages: this.data.messages.filter(
          (item) => item.id !== thinkingMessage.id
        ),
        scrollTarget: imageMessage.id,
      });

      if (error && (error.kind === "auth" || error.kind === "login")) {
        clearAccessToken();
        this.setData({ loginStatus: "error" });
      }
      wx.showToast({ title: getImageErrorMessage(error), icon: "none" });
    } finally {
      this.setData({ imageAnalyzing: false });
    }
  },

  handleClearMemory() {
    if (
      this.data.clearing ||
      this.data.sending ||
      this.data.imageAnalyzing ||
      this.data.loginStatus !== "ready"
    ) {
      return;
    }

    wx.showModal({
      title: "清空记忆",
      content: "确定清空当前聊天记忆吗？",
      confirmText: "清空",
      confirmColor: "#07a65a",
      success: (result) => {
        if (result.confirm) {
          this.clearMemory();
        }
      },
    });
  },

  async clearMemory() {
    this.setData({ clearing: true });
    try {
      const response = await request({
        path: "/api/miniapp/v1/memory",
        method: "DELETE",
      });
      if (!response || response.cleared !== true) {
        throw new Error("invalid memory response");
      }

      this.messageRevision += 1;
      this.historyRequestVersion += 1;
      this.setData({ messages: [], scrollTarget: "" });
      wx.showToast({ title: "聊天记忆已清空。", icon: "success" });
    } catch (error) {
      if (error && (error.kind === "auth" || error.kind === "login")) {
        clearAccessToken();
        this.setData({ loginStatus: "error" });
      }
      wx.showToast({ title: getErrorMessage(error), icon: "none" });
    } finally {
      this.setData({ clearing: false });
    }
  },
});
