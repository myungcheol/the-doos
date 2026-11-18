export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export function required(value: string | null): string {
  if (!value || value.length > 200)
    throw new HttpError(400, "요청 값이 올바르지 않습니다.");
  return value;
}
export function pageId(value: string) {
  if (!/^[1-9]\d{0,18}$/.test(value))
    throw new HttpError(400, "페이지 번호가 올바르지 않습니다.");
  return value;
}
export function personId(value: string) {
  if (!/^PER_[0-9a-fA-F]{32}$/.test(value))
    throw new HttpError(400, "인물 ID가 올바르지 않습니다.");
  return value;
}
export function offset(value: string | null) {
  if (value === null) return 0;
  if (!/^\d{1,7}$/.test(value))
    throw new HttpError(400, "목록 위치가 올바르지 않습니다.");
  return Number(value);
}
export function literalLike(value: string) {
  return value.replace(/[\\%_]/g, "\\$&");
}
