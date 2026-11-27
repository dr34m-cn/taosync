export function normalizeRemoteRoot(value) {
  const parts = String(value || "").trim().replaceAll("\\", "/").split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    return "/";
  }
  return "/" + parts.join("/");
}

export function formatRemoteRootLabel(driverType, share, basePath) {
  const normalized = normalizeRemoteRoot(basePath);
  const cleanShare = String(share || "").trim();
  if (driverType === "smb" && cleanShare) {
    return `${cleanShare}:${normalized}`;
  }
  return normalized;
}

export function joinRemotePath(basePath, selectedPath) {
  const base = normalizeRemoteRoot(basePath);
  const child = normalizeRemoteRoot(selectedPath);
  if (child === "/") return base;
  if (base === "/") return child;
  return `${base}${child}`;
}
