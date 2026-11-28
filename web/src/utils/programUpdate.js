export const LATEST_STABLE_OPTION = 'latest';
export const AUTO_SOURCE_OPTION = 'auto';

export function buildVersionOptions(releases) {
  const versions = Array.isArray(releases?.versions) ? releases.versions : [];
  const latestAvailable = Boolean(releases?.latestAvailable);
  const latestEntry = versions.find(item => item.isLatestStable) || null;
  const options = [
    {
      value: LATEST_STABLE_OPTION,
      isLatestOption: true,
      version: latestEntry?.version || releases?.latestVersion || null,
      available: latestAvailable && Boolean(latestEntry),
      channel: 'stable',
      publishedAt: latestEntry?.publishedAt || null,
      filename: latestEntry?.filename || null,
      sources: latestEntry?.sources || [],
    },
  ];
  for (const item of versions) {
    options.push({
      value: item.version,
      isLatestOption: false,
      version: item.version,
      available: true,
      channel: item.channel,
      isLatestStable: Boolean(item.isLatestStable),
      publishedAt: item.publishedAt || null,
      filename: item.filename || null,
      sources: Array.isArray(item.sources) ? item.sources : [],
    });
  }
  return options;
}

export function resolveSelectedVersionEntry(releases, selectedVersion = LATEST_STABLE_OPTION) {
  const versions = Array.isArray(releases?.versions) ? releases.versions : [];
  if (!selectedVersion || selectedVersion === LATEST_STABLE_OPTION) {
    return versions.find(item => item.isLatestStable) || null;
  }
  return versions.find(item => item.version === selectedVersion) || null;
}

export function buildSourceOptions(releases, selectedVersion = LATEST_STABLE_OPTION) {
  const entry = resolveSelectedVersionEntry(releases, selectedVersion);
  const sources = Array.isArray(entry?.sources) ? entry.sources : [];
  return [
    { value: AUTO_SOURCE_OPTION, isAutoOption: true, id: AUTO_SOURCE_OPTION },
    ...sources.map(source => ({ ...source, value: source.id, isAutoOption: false })),
  ];
}

export function reconcileSelectedSource(releases, selectedVersion, currentSource) {
  if (!currentSource || currentSource === AUTO_SOURCE_OPTION) {
    return AUTO_SOURCE_OPTION;
  }
  const options = buildSourceOptions(releases, selectedVersion);
  return options.some(item => item.value === currentSource) ? currentSource : AUTO_SOURCE_OPTION;
}

export function formatSourceLabel(source, locale = 'zh-CN') {
  if (!source) return '';
  const labels = source.labels;
  if (labels && typeof labels === 'object') {
    if (labels[locale]) return labels[locale];
    const normalized = String(locale || '').toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
    if (labels[normalized]) return labels[normalized];
  }
  return source.name || source.id || '';
}

export function formatByteSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let unit = 0;
  let scaled = value;
  while (unit < units.length - 1 && scaled >= 1024) {
    scaled /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${Math.round(scaled)} B` : `${scaled.toFixed(scaled >= 100 ? 0 : 1)} ${units[unit]}`;
}
