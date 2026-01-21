import axios from "axios";
import http from "http";
import https from "https";
import dotenv from "dotenv";
dotenv.config();

export interface SeleniumPayload {
  data: any;
  url?: string;
}

const SELENIUM_AGENT_BASE = process.env.SELENIUM_AGENT_BASE_URL;

const httpAgent = new http.Agent({ keepAlive: true, keepAliveMsecs: 60_000 });
const httpsAgent = new https.Agent({ keepAlive: true, keepAliveMsecs: 60_000 });

const client = axios.create({
  baseURL: SELENIUM_AGENT_BASE,
  timeout: 5 * 60 * 1000,
  httpAgent,
  httpsAgent,
  validateStatus: (s) => s >= 200 && s < 600,
});

async function requestWithRetries(
  config: any,
  retries = 4,
  baseBackoffMs = 300
) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const r = await client.request(config);
      if (![502, 503, 504].includes(r.status)) return r;
      console.warn(
        `[selenium-dentaquest-client] retryable HTTP status ${r.status} (attempt ${attempt})`
      );
    } catch (err: any) {
      const code = err?.code;
      const isTransient =
        code === "ECONNRESET" ||
        code === "ECONNREFUSED" ||
        code === "EPIPE" ||
        code === "ETIMEDOUT";
      if (!isTransient) throw err;
      console.warn(
        `[selenium-dentaquest-client] transient network error ${code} (attempt ${attempt})`
      );
    }
    await new Promise((r) => setTimeout(r, baseBackoffMs * attempt));
  }
  // final attempt (let exception bubble if it fails)
  return client.request(config);
}

function now() {
  return new Date().toISOString();
}
function log(tag: string, msg: string, ctx?: any) {
  console.log(`${now()} [${tag}] ${msg}`, ctx ?? "");
}

export async function forwardToSeleniumDentaQuestEligibilityAgent(
  insuranceEligibilityData: any
): Promise<any> {
  const payload = { data: insuranceEligibilityData };
  const url = `/dentaquest-eligibility`;
  log("selenium-dentaquest-client", "POST dentaquest-eligibility", {
    url: SELENIUM_AGENT_BASE + url,
    keys: Object.keys(payload),
  });
  const r = await requestWithRetries({ url, method: "POST", data: payload }, 4);
  log("selenium-dentaquest-client", "agent response", {
    status: r.status,
    dataKeys: r.data ? Object.keys(r.data) : null,
  });
  if (r.status >= 500)
    throw new Error(`Selenium agent server error: ${r.status}`);
  return r.data;
}

export async function forwardOtpToSeleniumDentaQuestAgent(
  sessionId: string,
  otp: string
): Promise<any> {
  const url = `/dentaquest-submit-otp`;
  log("selenium-dentaquest-client", "POST dentaquest-submit-otp", {
    url: SELENIUM_AGENT_BASE + url,
    sessionId,
  });
  const r = await requestWithRetries(
    { url, method: "POST", data: { session_id: sessionId, otp } },
    4
  );
  log("selenium-dentaquest-client", "submit-otp response", {
    status: r.status,
    data: r.data,
  });
  if (r.status >= 500)
    throw new Error(`Selenium agent server error on submit-otp: ${r.status}`);
  return r.data;
}

export async function getSeleniumDentaQuestSessionStatus(
  sessionId: string
): Promise<any> {
  const url = `/dentaquest-session/${sessionId}/status`;
  log("selenium-dentaquest-client", "GET session status", {
    url: SELENIUM_AGENT_BASE + url,
    sessionId,
  });
  const r = await requestWithRetries({ url, method: "GET" }, 4);
  log("selenium-dentaquest-client", "session status response", {
    status: r.status,
    dataKeys: r.data ? Object.keys(r.data) : null,
  });
  if (r.status === 404) {
    const e: any = new Error("not_found");
    e.response = { status: 404, data: r.data };
    throw e;
  }
  return r.data;
}

