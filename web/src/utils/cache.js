const sessionCache = {
  set(key, value) {
    if (key != null && value != null) {
      sessionStorage.setItem(key, value);
    }
  },
  get(key) {
    return key == null ? null : sessionStorage.getItem(key);
  },
  setJSON(key, jsonValue) {
    if (jsonValue != null) {
      this.set(key, JSON.stringify(jsonValue));
    }
  },
  getJSON(key) {
    const value = this.get(key);
    if (value != null) {
      return JSON.parse(value);
    }
    return null;
  },
  remove(key) {
    sessionStorage.removeItem(key);
  },
};

const localCache = {
  set(key, value) {
    if (key != null && value != null) {
      localStorage.setItem(key, value);
    }
  },
  get(key) {
    return key == null ? null : localStorage.getItem(key);
  },
  setJSON(key, jsonValue) {
    if (jsonValue != null) {
      this.set(key, JSON.stringify(jsonValue));
    }
  },
  getJSON(key) {
    const value = this.get(key);
    if (value != null) {
      return JSON.parse(value);
    }
    return null;
  },
  remove(key) {
    localStorage.removeItem(key);
  },
};

export default {
  session: sessionCache,
  local: localCache,
};
