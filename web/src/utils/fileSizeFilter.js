export const MAX_FILE_SIZE = Number.MAX_SAFE_INTEGER;

export const FILE_SIZE_UNITS = [
  { value: "B", multiplier: 1 },
  { value: "KB", multiplier: 1024 },
  { value: "MB", multiplier: 1024 ** 2 },
  { value: "GB", multiplier: 1024 ** 3 },
];

const DEFAULT_UNIT = "MB";

export function fileSizeMultiplier(unit) {
  return FILE_SIZE_UNITS.find((item) => item.value === unit)?.multiplier ?? 1;
}

export function bytesFromFileSize(value, unit) {
  if (value === null || value === undefined || value === "") return null;
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue) || numericValue < 0) return Number.NaN;
  const bytes = Math.round(numericValue * fileSizeMultiplier(unit));
  return Number.isSafeInteger(bytes) && bytes <= MAX_FILE_SIZE ? bytes : Number.NaN;
}

export function fileSizeInputFromBytes(bytes) {
  if (!isFileSizeBoundaryValid(bytes) || bytes === null) {
    return { value: null, unit: DEFAULT_UNIT };
  }
  for (let index = FILE_SIZE_UNITS.length - 1; index >= 0; index -= 1) {
    const unit = FILE_SIZE_UNITS[index];
    if (bytes < unit.multiplier && unit.multiplier !== 1) continue;
    const value = Number((bytes / unit.multiplier).toFixed(6));
    if (bytesFromFileSize(value, unit.value) === bytes) {
      return { value, unit: unit.value };
    }
  }
  return { value: bytes, unit: "B" };
}

export function isFileSizeBoundaryValid(value) {
  return value === null || (Number.isSafeInteger(value) && value >= 0);
}

export function isFileSizeRangeValid(minFileSize, maxFileSize) {
  if (!isFileSizeBoundaryValid(minFileSize) || !isFileSizeBoundaryValid(maxFileSize)) return false;
  return minFileSize === null || maxFileSize === null || minFileSize <= maxFileSize;
}
