import axios from "axios";

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") {
    return fallback;
  }

  if (axios.isAxiosError(error)) {
    if (error.code === "ECONNABORTED" || /timeout/i.test(error.message || "")) {
      return "The request timed out. The autofill may still be running in the background, please wait a moment and refresh.";
    }
    if (error.code === "ERR_NETWORK") {
      return "The app could not reach the backend service. Verify the API is running and try again.";
    }
  }

  const response = "response" in error ? (error as { response?: unknown }).response : undefined;
  if (!response || typeof response !== "object") {
    const message = "message" in error ? (error as { message?: unknown }).message : undefined;
    if (typeof message === "string" && message.trim()) {
      return message.trim();
    }
    return fallback;
  }

  const data = "data" in response ? (response as { data?: unknown }).data : undefined;
  if (typeof data === "string" && data.trim()) {
    return data.trim();
  }
  if (!data || typeof data !== "object") {
    return fallback;
  }

  const detail = "detail" in data ? (data as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === "object") {
    const message = "message" in detail ? (detail as { message?: unknown }).message : undefined;
    if (typeof message === "string" && message.trim()) {
      return message.trim();
    }
  }

  const message = "message" in data ? (data as { message?: unknown }).message : undefined;
  if (typeof message === "string" && message.trim()) {
    return message.trim();
  }

  return fallback;
}
