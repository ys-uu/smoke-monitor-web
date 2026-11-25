export async function api(url, options) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const result = await response.json().catch(() => null);
  if (!response.ok || result?.code !== 0) {
    throw new Error(result?.msg || `请求失败 (${response.status})`);
  }
  return result.data;
}

export function post(url, body) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function byId(id) {
  return document.getElementById(id);
}

export function feedback(element, message, tone = "") {
  element.textContent = message;
  element.dataset.tone = tone;
  element.hidden = !message;
}
