export function averageSyncSpeed(current, doneSize) {
  // Prefer the backend's precise elapsed time; support older servers too.
  const duration = current.syncDuration ?? (current.firstSync == null
    ? 0
    : current.duration + current.createTime - current.firstSync);
  const transferredBytes = Math.max(0, doneSize - (current.rapidUploadBytes ?? 0));
  return Number.isFinite(duration) && duration > 0 ? transferredBytes / duration : 0;
}
