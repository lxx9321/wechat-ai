const {
  ACCESS_TOKEN_STORAGE_KEY,
  API_BASE_URL,
} = require("./config");

const LOGIN_PATH = "/api/miniapp/v1/login";

let loginPromise = null;

class RequestError extends Error {
  constructor(kind, statusCode = 0) {
    super(kind);
    this.name = "RequestError";
    this.kind = kind;
    this.statusCode = statusCode;
  }
}

function getStoredToken() {
  const token = wx.getStorageSync(ACCESS_TOKEN_STORAGE_KEY);
  return typeof token === "string" && token ? token : "";
}

function clearAccessToken() {
  wx.removeStorageSync(ACCESS_TOKEN_STORAGE_KEY);
}

function rawRequest({ path, method = "GET", data, header = {} }) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${API_BASE_URL}${path}`,
      method,
      data,
      header: {
        "content-type": "application/json",
        ...header,
      },
      success(response) {
        resolve(response);
      },
      fail() {
        reject(new RequestError("network"));
      },
    });
  });
}

function rawUploadFile({
  path,
  filePath,
  name = "file",
  formData,
  header = {},
}) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${API_BASE_URL}${path}`,
      filePath,
      name,
      formData,
      header,
      success(response) {
        resolve(response);
      },
      fail() {
        reject(new RequestError("network"));
      },
    });
  });
}

function getLoginCode() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(result) {
        if (typeof result.code === "string" && result.code) {
          resolve(result.code);
          return;
        }
        reject(new RequestError("login"));
      },
      fail() {
        reject(new RequestError("login"));
      },
    });
  });
}

async function performLogin() {
  const code = await getLoginCode();
  const response = await rawRequest({
    path: LOGIN_PATH,
    method: "POST",
    data: { code },
  });

  const accessToken = response.data && response.data.access_token;
  if (
    response.statusCode !== 200 ||
    typeof accessToken !== "string" ||
    !accessToken
  ) {
    throw new RequestError("login", response.statusCode);
  }

  wx.setStorageSync(ACCESS_TOKEN_STORAGE_KEY, accessToken);
  return accessToken;
}

function ensureAuthenticated({ forceRefresh = false } = {}) {
  if (!forceRefresh) {
    const storedToken = getStoredToken();
    if (storedToken) {
      return Promise.resolve(storedToken);
    }
  } else {
    clearAccessToken();
  }

  if (loginPromise) {
    return loginPromise;
  }

  loginPromise = performLogin().then(
    (accessToken) => {
      loginPromise = null;
      return accessToken;
    },
    (error) => {
      loginPromise = null;
      throw error;
    }
  );
  return loginPromise;
}

function refreshAfterUnauthorized(failedToken) {
  const currentToken = getStoredToken();
  if (currentToken && currentToken !== failedToken) {
    return Promise.resolve(currentToken);
  }
  return ensureAuthenticated({ forceRefresh: true });
}

async function request(options, hasRetried = false) {
  const accessToken = await ensureAuthenticated();
  const response = await rawRequest({
    ...options,
    header: {
      ...(options.header || {}),
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (response.statusCode === 401) {
    if (!hasRetried) {
      await refreshAfterUnauthorized(accessToken);
      return request(options, true);
    }
    clearAccessToken();
    throw new RequestError("auth", 401);
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new RequestError("api", response.statusCode);
  }

  return response.data;
}

async function uploadFile(options, hasRetried = false) {
  const accessToken = await ensureAuthenticated();
  const response = await rawUploadFile({
    ...options,
    header: {
      ...(options.header || {}),
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (response.statusCode === 401) {
    if (!hasRetried) {
      await refreshAfterUnauthorized(accessToken);
      return uploadFile(options, true);
    }
    clearAccessToken();
    throw new RequestError("auth", 401);
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new RequestError("api", response.statusCode);
  }

  try {
    return typeof response.data === "string"
      ? JSON.parse(response.data)
      : response.data;
  } catch (error) {
    throw new RequestError("api", response.statusCode);
  }
}

module.exports = {
  RequestError,
  clearAccessToken,
  ensureAuthenticated,
  request,
  uploadFile,
};
