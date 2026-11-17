export function averageSyncSpeed(current, doneSize) {
  // Prefer the backend's precise elapsed time; support older servers too.
  const duration = current.syncDuration ?? (current.firstSync == null
    ? 0
    : current.duration + current.createTime - current.firstSync);
  return Number.isFinite(duration) && duration > 0 ? doneSize / duration : 0;
}
